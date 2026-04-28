from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Awaitable, Callable

from moodio.api.schemas import (
    AcceptedResponse,
    CommandRequest,
    FinalAction,
    FavoriteRequest,
    FavoriteResponse,
    NowResponse,
    PlaybackEventRequest,
    TransportActionResponse,
)
from moodio.context_builder import build_context_payload
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment
from moodio.domain.triggers import UserCommandTrigger
from moodio.executor import execute_action
from moodio.router import route_trigger
from moodio.state_store import StateStore
from moodio.station_agent import run_station_turn


def _seed_now_playing() -> QueueItem:
    return QueueItem.model_validate(
        {
            "track_id": "apple:track:if-bread",
            "title": "If",
            "artist": "Bread",
            "album": "Manna",
            "duration_seconds": 197,
            "playback_ref": "apple_music:catalog:12345",
            "artwork_url": "https://example.test/artwork/if.jpg",
        }
    )


def _seed_next_track() -> QueueItem:
    return QueueItem.model_validate(
        {
            "track_id": "apple:track:rainy-focus-02",
            "title": "Rainy Focus",
            "artist": "Example Artist",
            "album": "Desk Hours",
            "duration_seconds": 212,
            "playback_ref": "apple_music:catalog:67890",
            "artwork_url": "https://example.test/artwork/rainy-focus.jpg",
        }
    )


def _seed_transcript() -> TranscriptSegment:
    return TranscriptSegment.model_validate(
        {
            "segment_id": "seg_001",
            "text": "This is moodio. If you're enjoying this, I can favorite it for you.",
            "start_ms": 0,
            "duration_ms": 7400,
            "voice": "default_male_1",
            "state": "speaking",
        }
    )


class RuntimeService:
    def __init__(
        self,
        *,
        state_store: StateStore | None = None,
        station_turn_runner: Callable[[dict], Awaitable[FinalAction]] | None = None,
    ) -> None:
        self._temp_dir: TemporaryDirectory[str] | None = None
        if state_store is None:
            self._temp_dir = TemporaryDirectory(prefix="moodio-runtime-")
            state_store = StateStore(Path(self._temp_dir.name) / "moodio.db")

        self.state_store = state_store
        self._station_turn_runner = station_turn_runner or run_station_turn
        self.station_state = StationState.model_validate(
            {
                "host_name": "moodio",
                "mode": "radio_continue",
                "status": "playing",
                "talk_density": "balanced",
                "now_playing": _seed_now_playing().model_dump(),
                "queue": [_seed_next_track().model_dump()],
                "favorites_enabled": True,
            }
        )
        self.transcript_segments = [_seed_transcript()]
        self.favorites: set[str] = set()
        self._previous_tracks: list[QueueItem] = []
        self._subscribers: list[asyncio.Queue[dict]] = []
        self._seed_store()

    def _seed_store(self) -> None:
        recent_context = self.state_store.recent_context(limit=1)
        if not recent_context.plays:
            now_playing = self.station_state.now_playing
            self.state_store.record_play(track_id=now_playing.track_id, title=now_playing.title)
        if not recent_context.transcript:
            segment = self.transcript_segments[0]
            self.state_store.record_transcript(
                segment_id=segment.segment_id,
                text=segment.text,
                start_ms=segment.start_ms,
                duration_ms=segment.duration_ms,
            )

    def snapshot(self) -> NowResponse:
        return NowResponse.model_validate(self.station_state.model_dump())

    def transcript_snapshot(self) -> dict:
        return {"segments": [segment.model_dump() for segment in self.transcript_segments]}

    async def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def broadcast(self, event: str, payload: dict) -> None:
        for subscriber in list(self._subscribers):
            await subscriber.put({"event": event, "payload": payload})

    async def accept_command(self, request: CommandRequest) -> AcceptedResponse:
        self.state_store.record_command(request.text)

        trigger = UserCommandTrigger(text=request.text)
        mode = route_trigger(
            trigger=trigger,
            queue_depth=len(self.station_state.queue),
            provider_error=False,
        )
        context_payload = build_context_payload(
            mode=mode,
            trigger=trigger.model_dump(),
            user_corpus={},
            environment={"station_state": self.station_state.model_dump()},
            recent_context=self.state_store.recent_context(limit=5),
            scheduler_payload=None,
        )
        final_action = await self._station_turn_runner(context_payload)
        runtime_events = execute_action(final_action)
        await self._apply_runtime_events(runtime_events)
        self._sync_persisted_play_context()

        return AcceptedResponse(accepted=True, kind="natural_language", text=request.text)

    def _sync_persisted_play_context(self) -> None:
        if self.station_state.now_playing.track_id != STATION_PLACEHOLDER_TRACK_ID:
            self._record_play_if_new(self.station_state.now_playing)
        for queued_track in self.station_state.queue:
            self._record_play_if_new(queued_track)

    def _record_play_if_new(self, track: QueueItem) -> None:
        latest_plays = self.state_store.recent_context(limit=1).plays
        if latest_plays:
            latest_play = latest_plays[0]
            if latest_play.track_id == track.track_id and latest_play.title == track.title:
                return

        self.state_store.record_play(track_id=track.track_id, title=track.title)

    async def _apply_runtime_events(self, events: list[RuntimeEvent]) -> None:
        for event in events:
            payload = event["payload"]
            event_name = event["event"]

            if event_name in {"tts.segment.started", "tts.segment.completed"}:
                segment = TranscriptSegment.model_validate(payload)
                self.transcript_segments = [segment]
                if event_name == "tts.segment.completed":
                    self.state_store.record_transcript(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        start_ms=segment.start_ms,
                        duration_ms=segment.duration_ms,
                    )
            elif event_name == "queue.updated":
                queue = [QueueItem.model_validate(item) for item in payload["queue"]]
                self.station_state = self.station_state.model_copy(update={"queue": queue})
            elif event_name == "station.state.updated":
                self.station_state = StationState.model_validate(payload)

            await self.broadcast(event_name, payload)

    async def next_track(self) -> dict:
        if self.station_state.queue:
            self._previous_tracks.append(self.station_state.now_playing)
            next_track = self.station_state.queue.pop(0)
            self.station_state.now_playing = next_track
            self.state_store.record_play(track_id=next_track.track_id, title=next_track.title)

        await self.broadcast("queue.updated", {"queue": [track.model_dump() for track in self.station_state.queue]})
        await self.broadcast("station.state.updated", self.station_state.model_dump())

        return {
            "accepted": True,
            "now_playing": self.station_state.now_playing.model_dump(),
            "queue": [track.model_dump() for track in self.station_state.queue],
        }

    async def previous_track(self) -> dict:
        if self._previous_tracks:
            previous = self._previous_tracks.pop()
            self.station_state.queue.insert(0, self.station_state.now_playing)
            self.station_state.now_playing = previous
            self.state_store.record_play(track_id=previous.track_id, title=previous.title)

        await self.broadcast("queue.updated", {"queue": [track.model_dump() for track in self.station_state.queue]})
        await self.broadcast("station.state.updated", self.station_state.model_dump())

        return {
            "accepted": True,
            "now_playing": self.station_state.now_playing.model_dump(),
            "queue": [track.model_dump() for track in self.station_state.queue],
        }

    async def play(self) -> TransportActionResponse:
        return TransportActionResponse(accepted=True, action="play")

    async def pause(self) -> TransportActionResponse:
        return TransportActionResponse(accepted=True, action="pause")

    async def favorite_track(self, request: FavoriteRequest) -> FavoriteResponse:
        self.favorites.add(request.track_id)
        payload = {"track_id": request.track_id, "favorited": True}
        await self.broadcast("favorites.updated", payload)
        return FavoriteResponse(accepted=True, track_id=request.track_id, favorited=True)

    async def ingest_playback_event(self, request: PlaybackEventRequest) -> AcceptedResponse:
        await self.broadcast(request.event_type, request.model_dump())
        return AcceptedResponse(accepted=True, kind="playback_event", text=None)
