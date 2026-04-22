from __future__ import annotations

import asyncio

from moodio.api.schemas import (
    AcceptedResponse,
    CommandRequest,
    FavoriteRequest,
    FavoriteResponse,
    NowResponse,
    PlaybackEventRequest,
    TransportActionResponse,
)
from moodio.domain.models import QueueItem, StationState, TranscriptSegment


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


class InMemoryRuntime:
    def __init__(self) -> None:
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
        return AcceptedResponse(accepted=True, kind="natural_language", text=request.text)

    async def next_track(self) -> dict:
        if self.station_state.queue:
            self._previous_tracks.append(self.station_state.now_playing)
            next_track = self.station_state.queue.pop(0)
            self.station_state.now_playing = next_track

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
