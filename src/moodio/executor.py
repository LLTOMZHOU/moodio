from __future__ import annotations

from typing import Any

from moodio.api.schemas import FinalAction, QueueTrackAction, StreamEvent
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment


_DEFAULT_NOW_PLAYING = {
    "track_id": STATION_PLACEHOLDER_TRACK_ID,
    "title": "Current Station Track",
    "artist": "Moodio Runtime",
    "album": "Current Playback",
    "duration_seconds": 240,
    "playback_ref": STATION_PLACEHOLDER_TRACK_ID,
    "artwork_url": "https://example.test/artwork/current-playback.jpg",
}


def _queue_item_payload(track: QueueTrackAction) -> dict[str, Any]:
    title = track.track_id.rsplit(":", maxsplit=1)[-1].replace("-", " ").title()
    return {
        "track_id": track.track_id,
        "title": title or "Queued Track",
        "artist": "Moodio Runtime",
        "album": "Pending Queue",
        "duration_seconds": 180,
        "playback_ref": track.track_id,
        "artwork_url": "https://example.test/artwork/pending-queue.jpg",
    }


def _queue_items(queue_tracks: list[QueueTrackAction]) -> list[QueueItem]:
    return [QueueItem.model_validate(_queue_item_payload(track)) for track in queue_tracks]


def _station_state(action: FinalAction, queue: list[QueueItem], *, is_speaking: bool) -> StationState:
    return StationState.model_validate(
        {
            "host_name": "moodio",
            "mode": action.mode,
            "status": "speaking" if is_speaking else "playing",
            "talk_density": action.talk_density or "balanced",
            "now_playing": _DEFAULT_NOW_PLAYING,
            "queue": [item.model_dump() for item in queue],
            "favorites_enabled": True,
        }
    )


def _event(event: str, payload: dict[str, Any]) -> RuntimeEvent:
    return StreamEvent.model_validate({"event": event, "payload": payload}).model_dump()


def execute_action(action: FinalAction, tts_should_fail: bool = False) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    queue = _queue_items(action.queue_tracks)
    should_emit_tts = action.say is not None and not tts_should_fail
    station_state = _station_state(action, queue, is_speaking=should_emit_tts)

    if should_emit_tts:
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
