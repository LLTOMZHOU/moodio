from __future__ import annotations

from typing import Any

from moodio.api.schemas import FinalAction, QueueTrackAction, StreamEvent
from moodio.domain.models import QueueItem, StationState, TranscriptSegment
from moodio.runtime.in_memory import InMemoryRuntime


RuntimeEvent = dict[str, Any]


def _catalog_payloads() -> dict[str, dict[str, Any]]:
    runtime = InMemoryRuntime()
    tracks = [runtime.station_state.now_playing, *runtime.station_state.queue]
    return {track.track_id: track.model_dump() for track in tracks}


def _fallback_queue_payload(track: QueueTrackAction) -> dict[str, Any]:
    title = track.track_id.rsplit(":", maxsplit=1)[-1].replace("-", " ").title()
    return {
        "track_id": track.track_id,
        "title": title or "Queued Track",
        "artist": "Unknown Artist",
        "album": "Runtime Queue",
        "duration_seconds": 180,
        "playback_ref": track.track_id,
        "artwork_url": "https://example.test/artwork/runtime-placeholder.jpg",
    }


def _queue_items(queue_tracks: list[QueueTrackAction]) -> list[QueueItem]:
    catalog = _catalog_payloads()
    return [
        QueueItem.model_validate(catalog.get(track.track_id, _fallback_queue_payload(track)))
        for track in queue_tracks
    ]


def _station_state(action: FinalAction, queue: list[QueueItem]) -> StationState:
    runtime = InMemoryRuntime()
    runtime.station_state.mode = action.mode
    runtime.station_state.status = "speaking" if action.say is not None else "playing"
    if action.talk_density is not None:
        runtime.station_state.talk_density = action.talk_density
    if queue:
        runtime.station_state.queue = queue
    return runtime.station_state


def _event(event: str, payload: dict[str, Any]) -> RuntimeEvent:
    return StreamEvent.model_validate({"event": event, "payload": payload}).model_dump()


def execute_action(action: FinalAction) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    queue = _queue_items(action.queue_tracks)
    station_state = _station_state(action, queue)

    if action.say is not None:
        segment_payload = TranscriptSegment.model_validate(
            {
                "segment_id": "seg_runtime_001",
                "text": action.say.text,
                "start_ms": 0,
                "duration_ms": 3000,
                "voice": action.say.voice,
                "state": "speaking",
            }
        ).model_dump()
        events.append(_event("tts.segment.started", segment_payload))
        events.append(_event("tts.segment.completed", segment_payload))

    if queue:
        events.append(_event("queue.updated", {"queue": [item.model_dump() for item in queue]}))

    events.append(_event("station.state.updated", station_state.model_dump()))

    return events
