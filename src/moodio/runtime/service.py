from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
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
from moodio.domain.models import ProgramItem, QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment
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
from moodio.imports.apple_music import import_apple_music_xml
from moodio.music.providers import MusicProvider, ProviderTrack
from moodio.music.soundcloud import SoundCloudProvider
from moodio.music.youtube import YouTubeProvider
from moodio.router import route_trigger
from agents.memory import Session

from moodio.runtime.control import StationControl
from moodio.runtime.journal import StationJournal
from moodio.runtime.session import JsonlSession
from moodio.runtime.tasks import StationTaskStore
from moodio.state_store import ListenerPreferences, StateStore
from moodio.station_agent import run_station_turn, run_station_turn_streaming
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
_FEED_EVENT_PREFIXES = (
    "queue.",
    "playback.",
    "favorites.",
    "profile.",
    "task.",
    "program.",
    "provider.error",
    "agent.turn.",
)


@dataclass
class _TurnTiming:
    """Monotonic timing for one Listener-requested Station turn."""

    received_at: str
    received_monotonic: float
    first_model_started_at: str | None = None
    first_model_started_monotonic: float | None = None
    first_token_at: str | None = None
    first_token_monotonic: float | None = None
    first_agent_lane_wait_ms: int | None = None
    model_rounds: int = 0


def _elapsed_ms(start: float | None, end: float) -> int | None:
    if start is None:
        return None
    return round((end - start) * 1_000)


def _seed_now_playing() -> QueueItem:
    return QueueItem.model_validate(
        {
            "track_id": STATION_PLACEHOLDER_TRACK_ID,
            "title": "Choose something to start",
            "artist": "Moodio",
            "album": "Your personal station",
            "duration_seconds": 1,
            "playback_ref": STATION_PLACEHOLDER_TRACK_ID,
            "artwork_url": "https://example.test/artwork/station-idle.jpg",
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
        music_provider: MusicProvider | None = None,
        tts_cache_dir: Path | str = "var/cache/tts",
        station_dir: Path | str | None = None,
    ) -> None:
        self._temp_dir: TemporaryDirectory[str] | None = None
        if state_store is None:
            self._temp_dir = TemporaryDirectory(prefix="moodio-runtime-")
            state_store = StateStore(Path(self._temp_dir.name) / "moodio.db")

        self.state_store = state_store
        self.station_dir = Path(station_dir) if station_dir else self.state_store.db_path.parent / "station"
        self.journal = StationJournal(self.station_dir)
        self.task_store = StationTaskStore(self.station_dir / "station-tasks.json")
        self._station_turn_runner = station_turn_runner or run_station_turn
        self._runtime_event_executor = runtime_event_executor or execute_action
        self.speech_synthesizer = speech_synthesizer
        self.speech_transcriber = speech_transcriber
        self.web_search_provider = web_search_provider or NoopWebSearchProvider()
        self.weather_provider = weather_provider or StaticWeatherProvider()
        self.soundcloud_provider = soundcloud_provider or SoundCloudProvider()
        # An explicitly injected SoundCloud provider keeps old test/dev setups working;
        # normal construction and the environment factory use YouTube.
        self._legacy_soundcloud_refill = music_provider is None and soundcloud_provider is not None
        self.music_provider = music_provider or YouTubeProvider()
        self._candidates: dict[str, ProviderTrack] = {}
        self.tts_cache_dir = Path(tts_cache_dir)
        self.station_state = StationState.model_validate(
            {
                "host_name": "moodio",
                "mode": "radio_continue",
                "status": "idle",
                "talk_density": "balanced",
                "now_playing": _seed_now_playing().model_dump(),
                "queue": [],
                "favorites_enabled": True,
                "voice_mode": False,
            }
        )
        persisted_snapshot = self.journal.load_snapshot()
        if persisted_snapshot is not None:
            try:
                self.station_state = StationState.model_validate(persisted_snapshot)
            except Exception:
                self.journal.append("station.snapshot.invalid", {"reason": "validation_failed"})
        self.transcript_segments = [_seed_transcript()]
        self.favorites: set[str] = set()
        self._previous_tracks: list[QueueItem] = []
        self._listener_priority_count = 0
        self._session: Session = JsonlSession(self.station_dir / "agent-session.jsonl")
        self._agent_lane = asyncio.Lock()
        self._pending_internal_events: list[dict[str, object]] = []
        self._subscribers: list[asyncio.Queue[dict]] = []
        self._trace_id: str = ""
        self._span_counter: int = 0
        self._weather_task: asyncio.Task | None = None
        self._queue_refill_task: asyncio.Task | None = None
        self._last_editorial_pulse_at: datetime | None = None
        self._seed_store()
        self.journal.ensure_conversation_history()
        self.journal.save_snapshot(self.station_state.model_dump(mode="json"))

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
            agent_message = await self._run_agent(
                "You just came on air. Check the weather and station state, then introduce yourself "
                "to the listener with a warm opening line. If the weather suggests a mood, "
                "queue something that fits. If the queue is thin, go find a good opening track."
            )
        except Exception as exc:
            await self.broadcast("agent.turn.failed", {
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            return

        await self._commit_moodio_message(agent_message)
        await self._apply_agent_message(agent_message)
        self._sync_persisted_play_context()
        await self.ensure_queue_seeded(reason="startup")
        await self.run_due_tasks()

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
                await self.run_due_tasks()
                await self._maybe_editorial_pulse()
        except asyncio.CancelledError:
            pass

    async def run_due_tasks(self) -> None:
        tasks = self.task_store.list()
        due_ids = {task.task_id for task in self.task_store.due()}
        if not due_ids:
            return
        updated = []
        for task in tasks:
            if task.task_id not in due_ids:
                updated.append(task)
                continue
            await self.broadcast("task.started", {"task_id": task.task_id, "instruction": task.instruction})
            try:
                await self._run_agent(f"[scheduled station task] {task.instruction}")
            except Exception as exc:
                await self.broadcast("task.failed", {"task_id": task.task_id, "error": str(exc)})
                updated.append(task)
                continue
            updated.append(self.task_store.advance(task))
            await self.broadcast("task.completed", {"task_id": task.task_id})
        self.task_store.save(updated)

    async def _maybe_editorial_pulse(self) -> None:
        if self.station_state.status != "playing":
            return
        now = datetime.now(timezone.utc)
        if self._last_editorial_pulse_at and now - self._last_editorial_pulse_at < timedelta(hours=1):
            return
        self._last_editorial_pulse_at = now
        try:
            await asyncio.wait_for(
                self._run_agent("[editorial pulse] Quietly inspect the station and only queue useful follow-ups."),
                timeout=20,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            await self.broadcast("provider.error", {"provider": "scheduler", "action": "editorial_pulse.failed", "error": str(exc)})

    def import_listener_preferences(self, profile_text: str, *, source: str = "apple_music") -> ListenerPreferences:
        seed_queries = _seed_queries_from_profile_text(profile_text)
        preferences = ListenerPreferences(source=source, raw_text=profile_text.strip(), seed_queries=seed_queries)
        self.state_store.save_listener_preferences(preferences)
        (self.station_dir / "listener-profile.md").write_text(profile_text.strip() + "\n", encoding="utf-8")
        return preferences

    async def import_apple_music_export(self, content: bytes) -> dict:
        """Apply a Listener-selected Music.app XML export without retaining it."""
        imported = import_apple_music_xml(content)
        preferences = ListenerPreferences(
            source="apple_music_xml",
            raw_text=imported.profile_text,
            seed_queries=imported.seed_queries,
        )
        self.state_store.save_listener_preferences(preferences)
        (self.station_dir / "listener-profile.md").write_text(imported.profile_text + "\n", encoding="utf-8")
        summary = {
            "source": preferences.source,
            "track_count": imported.track_count,
            "playlist_count": imported.playlist_count,
            "top_artists": imported.top_artists,
            "top_genres": imported.top_genres,
            "seed_queries": imported.seed_queries,
        }
        await self.broadcast("profile.imported", summary)
        self._queue_internal_event("profile.imported", summary)
        queue_result = await self.ensure_queue_seeded(reason="apple_music_import", max_new_items=5)
        return {"import": summary, "queue": queue_result}

    async def ensure_queue_seeded(self, *, reason: str, max_new_items: int | None = None) -> dict:
        if self._legacy_soundcloud_refill:
            return await self._ensure_legacy_soundcloud_queue_seeded(reason=reason)
        preferences = self.state_store.get_listener_preferences()
        if preferences is None or not preferences.seed_queries:
            await self.broadcast("provider.request", {
                "provider": self.music_provider.key,
                "action": "queue_refill.skipped",
                "reason": "no_preferences",
                "trigger": reason,
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        needed = max(0, _DEFAULT_QUEUE_TARGET - self._queued_music_count())
        if max_new_items is not None:
            needed = min(needed, max(0, max_new_items))
        if needed <= 0:
            await self.broadcast("provider.request", {
                "provider": self.music_provider.key,
                "action": "queue_refill.skipped",
                "reason": "queue_full",
                "trigger": reason,
                "queue_size": self._queued_music_count(),
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        queries = self._candidate_queries(preferences, needed)
        if not queries:
            await self.broadcast("provider.request", {
                "provider": self.music_provider.key,
                "action": "queue_refill.skipped",
                "reason": "no_candidate_queries",
                "trigger": reason,
            })
            return {"queued": [], "failed": [], "total_queued": 0}

        await self.broadcast("provider.request", {
            "provider": self.music_provider.key,
            "action": "queue_refill.started",
            "trigger": reason,
            "needed": needed,
            "query_count": len(queries),
        })
        result = await StationControl(self).find_and_queue_music_multiple(queries)
        await self.broadcast("provider.request", {
            "provider": self.music_provider.key,
            "action": "queue_refill.completed",
            "trigger": reason,
            "queued_count": result["total_queued"],
            "failed": result["failed"],
            "queue_size": self._queued_music_count(),
        })
        return result

    async def _ensure_legacy_soundcloud_queue_seeded(self, *, reason: str) -> dict:
        """Compatibility path for explicit legacy SoundCloud injection only."""
        preferences = self.state_store.get_listener_preferences()
        if preferences is None or not preferences.seed_queries:
            return {"queued": [], "failed": [], "total_queued": 0}
        needed = max(0, _DEFAULT_QUEUE_TARGET - self._queued_music_count())
        if needed <= 0:
            return {"queued": [], "failed": [], "total_queued": 0}
        await self.broadcast("provider.request", {
            "provider": "soundcloud_discovery",
            "action": "queue_refill.started",
            "trigger": reason,
            "needed": needed,
        })
        result = await StationControl(self).find_and_queue_soundcloud_multiple(
            self._candidate_queries(preferences, needed)
        )
        await self.broadcast("provider.request", {
            "provider": "soundcloud_discovery",
            "action": "queue_refill.completed",
            "trigger": reason,
            "queued_count": result["total_queued"],
            "failed": result["failed"],
        })
        return result

    def _candidate_queries(self, preferences: ListenerPreferences, needed: int) -> list[str]:
        seen_refs = {
            self.station_state.now_playing.playback_ref,
            *(item.track.playback_ref for item in self.station_state.queue if item.kind == "music" and item.track),
        }
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
        timestamp = datetime.now(timezone.utc).isoformat()
        span_id = self._next_span_id()
        envelope = {
            "event": event,
            "payload": payload,
            "trace_id": self._trace_id,
            "span_id": span_id,
            "timestamp": timestamp,
        }
        if event.startswith(_FEED_EVENT_PREFIXES):
            self.journal.append(
                event,
                payload,
                at=timestamp,
                trace_id=self._trace_id,
                span_id=span_id,
            )
        if event in {"station.state.updated", "queue.updated"}:
            self.journal.save_snapshot(self.station_state.model_dump(mode="json"))
        for subscriber in list(self._subscribers):
            await subscriber.put(envelope)

    def debug_snapshot(self) -> dict:
        """Return local operator state without creating another Station runtime."""
        preferences = self.state_store.get_listener_preferences()
        return {
            "station": self.snapshot().model_dump(),
            "listener_profile": self._listener_profile_text(),
            "recent_context": asdict(self.state_store.recent_context(limit=20)),
            "tasks": [task.model_dump(mode="json") for task in self.task_store.list()],
            "conversation_path": str(self.journal.conversation_path),
            "agent_session_path": str(self.station_dir / "agent-session.jsonl"),
            "profile_source": preferences.source if preferences else None,
        }

    def raw_session_history(self, limit: int = 100) -> list[dict]:
        session_path = self.station_dir / "agent-session.jsonl"
        if not session_path.exists():
            return []
        entries: list[dict] = []
        for raw_line in session_path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def latency_snapshot(self, limit: int = 20) -> list[dict]:
        """Return completed Listener turns with durable server-side latency markers."""
        completed_turns = [
            entry
            for entry in self.journal.recent(limit=500)
            if entry.get("event") == "agent.turn.completed"
            and isinstance(entry.get("payload"), dict)
            and entry["payload"].get("mode") == "user_request"
            and isinstance(entry["payload"].get("timing"), dict)
            and "agent_lane_wait_ms" in entry["payload"]["timing"]
        ]
        return [
            {
                "trace_id": entry.get("trace_id"),
                "span_id": entry.get("span_id"),
                "completed_at": entry.get("at"),
                "timing": entry["payload"].get("timing", {}),
            }
            for entry in completed_turns[-max(1, limit):]
        ]

    def _timing_payload(self, timing: _TurnTiming, completed_at: str) -> dict[str, object]:
        completed_monotonic = time.perf_counter()
        return {
            "received_at": timing.received_at,
            "model_started_at": timing.first_model_started_at,
            "first_token_at": timing.first_token_at,
            "completed_at": completed_at,
            "agent_lane_wait_ms": timing.first_agent_lane_wait_ms,
            "time_to_first_token_ms": _elapsed_ms(timing.received_monotonic, timing.first_token_monotonic),
            "model_time_to_first_token_ms": _elapsed_ms(
                timing.first_model_started_monotonic,
                timing.first_token_monotonic,
            ),
            "total_ms": _elapsed_ms(timing.received_monotonic, completed_monotonic),
            "model_rounds": timing.model_rounds,
        }

    async def clear_conversation_history(self) -> dict:
        """Forget conversation text while retaining materialized Station state and preferences."""
        async with self._agent_lane:
            await self._session.clear_session()
            self.journal.clear_conversation()
            self.state_store.clear_conversation_records()
            self.transcript_segments = []
        await self.broadcast("conversation.cleared", {
            "preserved": ["listener_profile", "queue", "play_signals", "station_tasks"],
        })
        return {"cleared": True, "preserved": ["listener_profile", "queue", "play_signals", "station_tasks"]}

    async def _commit_moodio_message(self, text: str) -> None:
        """Durably save a visible reply before announcing it to connected consoles."""
        item = self.journal.append_conversation("moodio", text)
        await self.broadcast("conversation.message.saved", {"item": item})

    async def accept_command(self, request: CommandRequest) -> AcceptedResponse:
        self.state_store.record_command(request.text)
        self.journal.append_conversation("listener", request.text)

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
        turn_timing = _TurnTiming(
            received_at=turn_started_at,
            received_monotonic=time.perf_counter(),
        )
        await self.broadcast("agent.turn.started", {
            "input": request.text,
            "mode": mode,
            "trigger": trigger.model_dump(),
            "started_at": turn_started_at,
        })

        try:
            agent_message = await self._run_agent_streaming(request.text, timing=turn_timing)
        except Exception as exc:
            await self.broadcast("agent.turn.failed", {
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            raise

        await self._commit_moodio_message(agent_message)
        await self._apply_agent_message(agent_message)
        self._sync_persisted_play_context()

        completed_at = datetime.now(timezone.utc).isoformat()
        await self.broadcast("agent.turn.completed", {
            "output": agent_message,
            "mode": mode,
            "started_at": turn_started_at,
            "completed_at": completed_at,
            "timing": self._timing_payload(turn_timing, completed_at),
        })

        return AcceptedResponse(accepted=True, kind="natural_language", text=request.text)

    def _listener_profile_text(self) -> str:
        profile_path = self.station_dir / "listener-profile.md"
        if profile_path.exists():
            return profile_path.read_text(encoding="utf-8").strip()
        preferences = self.state_store.get_listener_preferences()
        return preferences.raw_text.strip() if preferences else ""

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
        if self.station_state.voice_mode and self.speech_synthesizer is not None:
            try:
                audio = self.speech_synthesizer.synthesize(segment.text, voice=segment.voice)
            except Exception as exc:
                await self.broadcast("tts.audio.failed", {"message": str(exc), "provider": "tts"})
            else:
                await self.broadcast("tts.audio.ready", audio.model_dump(mode="json"))
        await self.broadcast("tts.segment.completed", segment.model_dump())
        await self.broadcast("station.state.updated", self.station_state.model_dump())

    async def _run_agent(self, input_payload: str) -> str:
        """Serialize the shared DJ session and flush typed direct-control context."""
        async with self._agent_lane:
            if self._pending_internal_events:
                items = [
                    {
                        "role": "developer",
                        "content": "[Internal Station event — application context, not a Listener request]\n"
                        + json.dumps(event, sort_keys=True),
                    }
                    for event in self._pending_internal_events
                ]
                await self._session.add_items(items)
                self._pending_internal_events.clear()
            return await self._station_turn_runner(input_payload, StationControl(self), session=self._session)

    async def _run_agent_streaming(self, input_payload: str, *, timing: _TurnTiming | None = None) -> str:
        lane_requested_monotonic = time.perf_counter()
        async with self._agent_lane:
            lane_acquired_monotonic = time.perf_counter()
            if self._pending_internal_events:
                await self._session.add_items([
                    {"role": "developer", "content": "[Internal Station event]\n" + json.dumps(event, sort_keys=True)}
                    for event in self._pending_internal_events
                ])
                self._pending_internal_events.clear()

            if timing is not None:
                timing.model_rounds += 1
                model_started_at = datetime.now(timezone.utc).isoformat()
                model_started_monotonic = time.perf_counter()
                agent_lane_wait_ms = _elapsed_ms(lane_requested_monotonic, lane_acquired_monotonic)
                if timing.first_model_started_monotonic is None:
                    timing.first_model_started_at = model_started_at
                    timing.first_model_started_monotonic = model_started_monotonic
                    timing.first_agent_lane_wait_ms = agent_lane_wait_ms
                await self.broadcast("agent.turn.model_started", {
                    "round": timing.model_rounds,
                    "model_started_at": model_started_at,
                    "agent_lane_wait_ms": agent_lane_wait_ms,
                    "station_context_prepare_ms": _elapsed_ms(
                        lane_acquired_monotonic,
                        model_started_monotonic,
                    ),
                    "elapsed_since_received_ms": _elapsed_ms(
                        timing.received_monotonic,
                        model_started_monotonic,
                    ),
                })

            round_first_token_monotonic: float | None = None

            async def on_delta(delta: str) -> None:
                nonlocal round_first_token_monotonic
                if delta:
                    if timing is not None and round_first_token_monotonic is None:
                        round_first_token_monotonic = time.perf_counter()
                        await self.broadcast("agent.turn.round_first_token", {
                            "round": timing.model_rounds,
                            "round_time_to_first_token_ms": _elapsed_ms(
                                model_started_monotonic,
                                round_first_token_monotonic,
                            ),
                            "elapsed_since_received_ms": _elapsed_ms(
                                timing.received_monotonic,
                                round_first_token_monotonic,
                            ),
                        })
                    if timing is not None and timing.first_token_monotonic is None:
                        timing.first_token_at = datetime.now(timezone.utc).isoformat()
                        timing.first_token_monotonic = round_first_token_monotonic or time.perf_counter()
                        await self.broadcast("agent.turn.first_token", {
                            "first_token_at": timing.first_token_at,
                            "time_to_first_token_ms": _elapsed_ms(
                                timing.received_monotonic,
                                timing.first_token_monotonic,
                            ),
                            "model_time_to_first_token_ms": _elapsed_ms(
                                timing.first_model_started_monotonic,
                                timing.first_token_monotonic,
                            ),
                            "round": timing.model_rounds,
                        })
                    await self.broadcast("agent.response.delta", {"delta": delta})

            if self._station_turn_runner is run_station_turn:
                return await run_station_turn_streaming(input_payload, StationControl(self), self._session, on_delta)
            return await self._station_turn_runner(input_payload, StationControl(self), session=self._session)

    def _queue_internal_event(self, kind: str, payload: dict[str, object]) -> None:
        self._pending_internal_events.append({"kind": kind, "origin": "listener", "payload": payload})

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
        for queued_item in self.station_state.queue:
            if queued_item.kind == "music" and queued_item.track:
                self._record_play_if_new(queued_item.track)

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
                queue = [ProgramItem.model_validate(item) for item in payload["queue"]]
                self.station_state = self.station_state.model_copy(update={"queue": queue})
            elif event_name == "station.state.updated":
                self.station_state = StationState.model_validate(payload)

            await self.broadcast(event_name, payload)

    async def next_track(self) -> dict:
        while self.station_state.queue and self.station_state.queue[0].kind == "commentary":
            commentary = self.station_state.queue.pop(0)
            await self.broadcast("program.commentary.consumed", commentary.model_dump())
        if self.station_state.queue:
            self._previous_tracks.append(self.station_state.now_playing)
            next_item = self.station_state.queue.pop(0)
            if next_item.track is None:
                raise ValueError("music program item missing track")
            next_track = next_item.track
            if self._listener_priority_count:
                self._listener_priority_count -= 1
            self.station_state.now_playing = next_track
            self.state_store.record_play(track_id=next_track.track_id, title=next_track.title)

        self._bump_queue_revision()
        await self.broadcast("queue.updated", self._queue_payload())
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        self._queue_internal_event("playback.skipped", {"track_id": self.station_state.now_playing.track_id})
        if self._queued_music_count() < _DEFAULT_QUEUE_LOW_WATERMARK:
            await self.ensure_queue_seeded(reason="queue_low")

        return {
            "accepted": True,
            "now_playing": self.station_state.now_playing.model_dump(),
            "queue": self._queue_payload()["queue"],
        }

    async def queue_track(
        self,
        track: QueueItem,
        *,
        listener_priority: bool = False,
        origin: str = "dj",
        reason: str = "Station programming",
    ) -> dict:
        item = ProgramItem.music(track, origin=origin, reason=reason)
        if listener_priority:
            # Consecutive “Queue next” clicks remain in click order directly
            # after the current item, ahead of autonomous DJ programming.
            self.station_state.queue.insert(self._listener_priority_count, item)
            self._listener_priority_count += 1
        else:
            self.station_state.queue.insert(0, item)
        self._record_play_if_new(track)

        self._bump_queue_revision()
        queue_payload = self._queue_payload()
        await self.broadcast("queue.updated", queue_payload)
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        if origin == "listener":
            self._queue_internal_event("queue.listener_added", {"track_id": track.track_id, "reason": reason})

        return {
            "accepted": True,
            "revision": queue_payload["revision"],
            "queue": queue_payload["queue"],
        }

    def remember_candidates(self, tracks: list[ProviderTrack]) -> None:
        for track in tracks:
            self._candidates[track.playback_ref] = track

    async def resolve_candidate(self, candidate_id: str) -> ProviderTrack:
        candidate = self._candidates.get(candidate_id)
        raw_id = candidate.provider_track_id if candidate else candidate_id
        resolved = await self.music_provider.resolve_track(raw_id)
        self._candidates[resolved.playback_ref] = resolved
        return resolved

    def _queued_music_count(self) -> int:
        return sum(1 for item in self.station_state.queue if item.kind == "music")

    def _queue_payload(self) -> dict:
        return {
            "revision": self.station_state.queue_revision,
            "queue": [item.model_dump(mode="json") for item in self.station_state.queue],
        }

    def _bump_queue_revision(self) -> None:
        self.station_state = self.station_state.model_copy(
            update={"queue_revision": self.station_state.queue_revision + 1}
        )

    async def queue_soundcloud_embed(self, url: str) -> dict:
        provider_track = await self.soundcloud_provider.resolve_embed_url(url)
        return await self.queue_track(provider_track.to_queue_item())

    async def previous_track(self) -> dict:
        if self._previous_tracks:
            previous = self._previous_tracks.pop()
            self.station_state.queue.insert(0, ProgramItem.music(
                self.station_state.now_playing, origin="listener", reason="Previous track"
            ))
            self.station_state.now_playing = previous
            self.state_store.record_play(track_id=previous.track_id, title=previous.title)

        self._bump_queue_revision()
        await self.broadcast("queue.updated", self._queue_payload())
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        self._queue_internal_event("playback.previous", {"track_id": self.station_state.now_playing.track_id})

        return {
            "accepted": True,
            "now_playing": self.station_state.now_playing.model_dump(),
            "queue": self._queue_payload()["queue"],
        }

    async def play(self) -> TransportActionResponse:
        if self.station_state.now_playing.track_id == STATION_PLACEHOLDER_TRACK_ID and self.station_state.queue:
            await self.next_track()
        self.station_state = self.station_state.model_copy(update={"status": "playing"})
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        self._queue_internal_event("playback.resumed", {})
        return TransportActionResponse(accepted=True, action="play")

    async def pause(self) -> TransportActionResponse:
        self.station_state = self.station_state.model_copy(update={"status": "idle"})
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        self._queue_internal_event("playback.paused", {})
        return TransportActionResponse(accepted=True, action="pause")

    async def favorite_track(self, request: FavoriteRequest) -> FavoriteResponse:
        self.favorites.add(request.track_id)
        payload = {"track_id": request.track_id, "favorited": True}
        await self.broadcast("favorites.updated", payload)
        self._queue_internal_event("listener.favorite", payload)
        return FavoriteResponse(accepted=True, track_id=request.track_id, favorited=True)

    async def set_voice_mode(self, enabled: bool) -> dict:
        self.station_state = self.station_state.model_copy(update={"voice_mode": enabled})
        await self.broadcast("station.state.updated", self.station_state.model_dump())
        return {"enabled": enabled}

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
    # The production/local-server factory owns a durable Station directory.  Keep
    # RuntimeService's temporary default for isolated callers, but never use it
    # for `moodio serve`: that would silently discard the JSONL conversation on
    # every restart.
    data_dir = Path(os.environ.get("MOODIO_DATA_DIR", "var/data"))
    runtime_kwargs = {
        "state_store": StateStore(data_dir / "moodio.db"),
        "station_dir": data_dir / "station",
        "web_search_provider": DuckDuckGoSearchProvider(),
        "weather_provider": FetchWeatherProvider(),
        "music_provider": YouTubeProvider(),
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
