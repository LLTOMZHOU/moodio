from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
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
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment
from moodio.domain.triggers import UserCommandTrigger
from moodio.executor import execute_action
from moodio.info import (
    DuckDuckGoSearchProvider,
    FetchWeatherProvider,
    NoopWebSearchProvider,
    StaticWeatherProvider,
    WeatherProvider,
    WebSearchProvider,
)
from moodio.music.soundcloud import SoundCloudProvider
from moodio.router import route_trigger
from agents.memory import Session

from moodio.runtime.control import StationControl
from moodio.runtime.session import SqliteSession
from moodio.state_store import ListenerPreferences, StateStore
from moodio.station_agent import run_station_turn
from moodio.voice import (
    ElevenLabsSpeechSynthesizer,
    OpenAISpeechSynthesizer,
    OpenAITranscriber,
    SpeechSynthesizer,
    SpeechTranscriber,
)


_OPENAI_AUDIO_ENV_KEYS = {
    "OPENAI_AUDIO_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_TTS_MODEL",
    "OPENROUTER_TTS_VOICE",
    "OPENROUTER_TTS_RESPONSE_FORMAT",
    "OPENAI_TTS_MODEL",
    "OPENAI_TTS_VOICE",
    "OPENAI_TTS_RESPONSE_FORMAT",
    "OPENAI_STT_MODEL",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_OUTPUT_FORMAT",
}
_DEFAULT_QUEUE_TARGET = 10
_DEFAULT_QUEUE_LOW_WATERMARK = 3


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
            "track_id": "apple:track:soft-sunset-02",
            "title": "Soft Sunset",
            "artist": "Example Artist",
            "album": "Golden Hour",
            "duration_seconds": 212,
            "playback_ref": "apple_music:catalog:67890",
            "artwork_url": "https://example.test/artwork/soft-sunset.jpg",
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
        station_turn_runner: Callable[[dict | str, StationControl, Session], Awaitable[str]] | None = None,
        runtime_event_executor: Callable[[FinalAction], list[RuntimeEvent]] | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
        speech_transcriber: SpeechTranscriber | None = None,
        web_search_provider: WebSearchProvider | None = None,
        weather_provider: WeatherProvider | None = None,
        soundcloud_provider: object | None = None,
        tts_cache_dir: Path | str = "var/cache/tts",
    ) -> None:
        self._temp_dir: TemporaryDirectory[str] | None = None
        if state_store is None:
            self._temp_dir = TemporaryDirectory(prefix="moodio-runtime-")
            state_store = StateStore(Path(self._temp_dir.name) / "moodio.db")

        self.state_store = state_store
        self._station_turn_runner = station_turn_runner or run_station_turn
        self._runtime_event_executor = runtime_event_executor or execute_action
        self.speech_synthesizer = speech_synthesizer
        self.speech_transcriber = speech_transcriber
        self.web_search_provider = web_search_provider or NoopWebSearchProvider()
        self.weather_provider = weather_provider or StaticWeatherProvider()
        self.soundcloud_provider = soundcloud_provider or SoundCloudProvider()
        self.tts_cache_dir = Path(tts_cache_dir)
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
        self._session: Session = SqliteSession(self.state_store.db_path, session_id="default")
        self._subscribers: list[asyncio.Queue[dict]] = []
        self._trace_id: str = ""
        self._span_counter: int = 0
        self._weather_task: asyncio.Task | None = None
        self._queue_refill_task: asyncio.Task | None = None
        self._seed_store()

    async def start(self) -> None:
        """Run the startup turn and begin the weather cadence.

        Call this after constructing the service (e.g. on FastAPI lifespan startup)
        so the station greets the listener and begins refreshing context.
        """
        await self._startup_turn()
        self._weather_task = asyncio.create_task(self._weather_cadence())
        self._queue_refill_task = asyncio.create_task(self._queue_refill_cadence())

    async def stop(self) -> None:
        """Stop the background weather cadence."""
        if self._weather_task is not None:
            self._weather_task.cancel()
            try:
                await self._weather_task
            except asyncio.CancelledError:
                pass
            self._weather_task = None
        if self._queue_refill_task is not None:
            self._queue_refill_task.cancel()
            try:
                await self._queue_refill_task
            except asyncio.CancelledError:
                pass
            self._queue_refill_task = None

    async def _startup_turn(self) -> None:
        """Generate an opening line on first load by checking weather and station state."""
        self._trace_id = uuid.uuid4().hex[:16]
        self._span_counter = 0
        started_at = datetime.now(timezone.utc).isoformat()
        await self.broadcast("agent.turn.started", {
            "input": "[startup]",
            "mode": "radio_continue",
            "trigger": {"kind": "scheduler", "reason": "station_startup"},
            "started_at": started_at,
        })
        try:
            agent_message = await self._station_turn_runner(
                "You just came on air. Check the weather and station state, then introduce yourself "
                "to the listener with a warm opening line. If the weather suggests a mood, "
                "queue something that fits. If the queue is thin, go find a good opening track.",
                StationControl(self),
                session=self._session,
            )
        except Exception as exc:
            await self.broadcast("agent.turn.failed", {
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            return

        await self._apply_agent_message(agent_message)
        self._sync_persisted_play_context()
        await self.ensure_queue_seeded(reason="startup")

        await self.broadcast("agent.turn.completed", {
            "output": agent_message,
            "mode": "radio_continue",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def _weather_cadence(self) -> None:
        """Periodically refresh weather context so the agent stays aware of conditions."""
        try:
            while True:
                await asyncio.sleep(600)  # every 10 minutes
                weather = self.weather_provider.get_weather("San Francisco")
                await self.broadcast("provider.request", {
                    "provider": "weather",
                    "action": "cadence_refresh",
                    "result": weather.model_dump(),
                })
        except asyncio.CancelledError:
            pass

    async def _queue_refill_cadence(self) -> None:
        try:
            while True:
                await asyncio.sleep(600)
                await self.ensure_queue_seeded(reason="cadence")
        except asyncio.CancelledError:
            pass

    def import_listener_preferences(self, profile_text: str, *, source: str = "apple_music") -> ListenerPreferences:
        seed_queries = _seed_queries_from_profile_text(profile_text)
        preferences = ListenerPreferences(source=source, raw_text=profile_text.strip(), seed_queries=seed_queries)
        self.state_store.save_listener_preferences(preferences)
        return preferences

    async def ensure_queue_seeded(self, *, reason: str) -> dict:
        preferences = self.state_store.get_listener_preferences()
        if preferences is None or not preferences.seed_queries:
            await self.broadcast("provider.request", {
                "provider": "soundcloud_discovery",
                "action": "queue_refill.skipped",
                "reason": "no_preferences",
                "trigger": reason,
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        needed = max(0, _DEFAULT_QUEUE_TARGET - len(self.station_state.queue))
        if needed <= 0:
            await self.broadcast("provider.request", {
                "provider": "soundcloud_discovery",
                "action": "queue_refill.skipped",
                "reason": "queue_full",
                "trigger": reason,
                "queue_size": len(self.station_state.queue),
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        queries = self._candidate_queries(preferences, needed)
        if not queries:
            await self.broadcast("provider.request", {
                "provider": "soundcloud_discovery",
                "action": "queue_refill.skipped",
                "reason": "no_candidate_queries",
                "trigger": reason,
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        await self.broadcast("provider.request", {
            "provider": "soundcloud_discovery",
            "action": "queue_refill.started",
            "trigger": reason,
            "needed": needed,
            "query_count": len(queries),
        })
        result = await StationControl(self).find_and_queue_soundcloud_multiple(queries)
        await self.broadcast("provider.request", {
            "provider": "soundcloud_discovery",
            "action": "queue_refill.completed",
            "trigger": reason,
            "queued_count": result["total_queued"],
            "failed": result["failed"],
            "queue_size": len(self.station_state.queue),
        })
        return result

    def _candidate_queries(self, preferences: ListenerPreferences, needed: int) -> list[str]:
        seen_refs = {self.station_state.now_playing.playback_ref, *(track.playback_ref for track in self.station_state.queue)}
        chosen: list[str] = []
        for query in preferences.seed_queries:
            normalized = query.strip()
            if not normalized or normalized in chosen:
                continue
            if any(normalized.lower() in ref.lower() for ref in seen_refs):
                continue
            chosen.append(normalized)
            if len(chosen) >= needed:
                break
        return chosen

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

    def _next_span_id(self) -> str:
        self._span_counter += 1
        return f"{self._trace_id}-{self._span_counter:04d}"

    async def broadcast(self, event: str, payload: dict) -> None:
        envelope = {
            "event": event,
            "payload": payload,
            "trace_id": self._trace_id,
            "span_id": self._next_span_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for subscriber in list(self._subscribers):
            await subscriber.put(envelope)

    async def accept_command(self, request: CommandRequest) -> AcceptedResponse:
        self.state_store.record_command(request.text)

        trigger = UserCommandTrigger(text=request.text)
        mode = route_trigger(
            trigger=trigger,
            queue_depth=len(self.station_state.queue),
            provider_error=False,
        )
        self.station_state = self.station_state.model_copy(update={"mode": mode})

        self._trace_id = uuid.uuid4().hex[:16]
        self._span_counter = 0
        turn_started_at = datetime.now(timezone.utc).isoformat()
        await self.broadcast("agent.turn.started", {
            "input": request.text,
            "mode": mode,
            "trigger": trigger.model_dump(),
            "started_at": turn_started_at,
        })

        try:
            agent_message = await self._station_turn_runner(
                request.text,
                StationControl(self),
                session=self._session,
            )
        except Exception as exc:
            await self.broadcast("agent.turn.failed", {
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            raise

        await self._apply_agent_message(agent_message)
        self._sync_persisted_play_context()

        await self.broadcast("agent.turn.completed", {
            "output": agent_message,
            "mode": mode,
            "started_at": turn_started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        return AcceptedResponse(accepted=True, kind="natural_language", text=request.text)

    async def _apply_agent_message(self, text: str) -> None:
        if not text:
            return

        segment = TranscriptSegment.model_validate(
            {
                "segment_id": "seg_runtime_001",
                "text": text,
                "start_ms": 0,
                "duration_ms": 3000,
                "voice": "default_male_1",
                "state": "speaking",
            }
        )
        self.transcript_segments = [segment]
        self.state_store.record_transcript(
            segment_id=segment.segment_id,
            text=segment.text,
            start_ms=segment.start_ms,
            duration_ms=segment.duration_ms,
        )
        self.station_state = self.station_state.model_copy(update={"status": "speaking"})

        await self.broadcast("tts.segment.started", segment.model_dump())
        if self.speech_synthesizer is not None:
            try:
                audio = self.speech_synthesizer.synthesize(segment.text, voice=segment.voice)
            except Exception as exc:
                await self.broadcast("tts.audio.failed", {"message": str(exc), "provider": "tts"})
            else:
                await self.broadcast("tts.audio.ready", audio.model_dump(mode="json"))
        await self.broadcast("tts.segment.completed", segment.model_dump())
        await self.broadcast("station.state.updated", self.station_state.model_dump())

    def transcribe_audio(self, audio: bytes, *, filename: str, content_type: str) -> dict:
        if self.speech_transcriber is None:
            raise ValueError("speech transcriber is not configured")
        return {
            "text": self.speech_transcriber.transcribe(
                audio,
                filename=filename,
                content_type=content_type,
            )
        }

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
        if len(self.station_state.queue) < _DEFAULT_QUEUE_LOW_WATERMARK:
            await self.ensure_queue_seeded(reason="queue_low")

        return {
            "accepted": True,
            "now_playing": self.station_state.now_playing.model_dump(),
            "queue": [track.model_dump() for track in self.station_state.queue],
        }

    async def queue_track(self, track: QueueItem) -> dict:
        self.station_state.queue.insert(0, track)
        self._record_play_if_new(track)

        queue_payload = {"queue": [item.model_dump() for item in self.station_state.queue]}
        await self.broadcast("queue.updated", queue_payload)
        await self.broadcast("station.state.updated", self.station_state.model_dump())

        return {
            "accepted": True,
            "queue": queue_payload["queue"],
        }

    async def queue_soundcloud_embed(self, url: str) -> dict:
        provider_track = await self.soundcloud_provider.resolve_embed_url(url)
        return await self.queue_track(provider_track.to_queue_item())

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
        if request.event_type in {"music.playback.near_end", "music.playback.ended"}:
            await self.ensure_queue_seeded(reason=request.event_type)
        return AcceptedResponse(accepted=True, kind="playback_event", text=None)


def _seed_queries_from_profile_text(profile_text: str) -> list[str]:
    lines = [line.strip(" -•\t") for line in profile_text.splitlines()]
    cleaned = [line for line in lines if line]
    deduped: list[str] = []
    for item in cleaned:
        if item not in deduped:
            deduped.append(item)

    expanded: list[str] = []
    suffixes = [
        "SoundCloud",
        "indie",
        "dream pop",
        "late night",
        "rainy day",
        "heartbreak songs",
    ]
    for item in deduped:
        expanded.append(item)
        for suffix in suffixes:
            expanded.append(f"{item} {suffix}")

    final: list[str] = []
    for item in expanded:
        normalized = item.strip()
        if normalized and normalized not in final:
            final.append(normalized)
        if len(final) >= 20:
            break
    return final


def build_runtime_from_env() -> RuntimeService:
    load_local_openai_audio_env()
    elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY")
    elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    openrouter_tts_model = os.environ.get("OPENROUTER_TTS_MODEL")
    audio_api_key = os.environ.get("OPENAI_AUDIO_API_KEY") or os.environ.get("OPENAI_API_KEY")
    runtime_kwargs = {
        "web_search_provider": DuckDuckGoSearchProvider(),
        "weather_provider": FetchWeatherProvider(),
    }
    if elevenlabs_api_key and elevenlabs_voice_id:
        return RuntimeService(
            **runtime_kwargs,
            speech_synthesizer=ElevenLabsSpeechSynthesizer(
                api_key=elevenlabs_api_key,
                voice_id=elevenlabs_voice_id,
                model=os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
                output_format=os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
                cache_dir="var/cache/tts",
            ),
        )
    if openrouter_api_key and openrouter_tts_model:
        synthesizer_kwargs = {
            "api_key": openrouter_api_key,
            "base_url": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "model": openrouter_tts_model,
            "cache_dir": "var/cache/tts",
        }
        if os.environ.get("OPENROUTER_TTS_VOICE"):
            synthesizer_kwargs["voice"] = os.environ["OPENROUTER_TTS_VOICE"]
        if os.environ.get("OPENROUTER_TTS_RESPONSE_FORMAT"):
            synthesizer_kwargs["response_format"] = os.environ["OPENROUTER_TTS_RESPONSE_FORMAT"]
        return RuntimeService(
            **runtime_kwargs,
            speech_synthesizer=OpenAISpeechSynthesizer(**synthesizer_kwargs),
        )
    if not audio_api_key:
        return RuntimeService(**runtime_kwargs)
    return RuntimeService(
        **runtime_kwargs,
        speech_synthesizer=OpenAISpeechSynthesizer(api_key=audio_api_key, cache_dir="var/cache/tts"),
        speech_transcriber=OpenAITranscriber(api_key=audio_api_key),
    )


def load_local_openai_audio_env(env_path: Path | str = ".env") -> dict[str, str]:
    path = Path(env_path)
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in _OPENAI_AUDIO_ENV_KEYS and value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value

    return loaded
