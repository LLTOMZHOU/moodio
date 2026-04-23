from __future__ import annotations

from moodio.api.schemas import FinalAction
from moodio.domain.events import RuntimeEvent


def execute_action(action: FinalAction) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []

    if action.say is not None:
        segment_payload = {
            "segment_id": "seg_runtime_001",
            "text": action.say.text,
            "start_ms": 0,
            "duration_ms": 3000,
            "voice": action.say.voice,
            "state": "speaking",
        }
        events.append({"event": "tts.segment.started", "payload": segment_payload})
        events.append({"event": "tts.segment.completed", "payload": segment_payload})

    if action.queue_tracks:
        events.append({"event": "queue.updated", "payload": {"queue": action.queue_tracks}})

    events.append({"event": "station.state.updated", "payload": {"mode": action.mode}})

    return events
