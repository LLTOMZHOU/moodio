from moodio.api.schemas import FinalAction
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, StationState, TranscriptSegment
from moodio.executor import execute_action


def test_execute_action_emits_tts_before_queue_update() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "radio_continue",
            "say": {
                "text": "A softer turn here.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [
                {
                    "track_id": "apple:track:rainy-focus-02",
                    "reason": "keep the station warm",
                    "start_policy": "after_tts",
                }
            ],
            "player_actions": [],
            "talk_density": "balanced",
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.segment.completed",
        "queue.updated",
        "station.state.updated",
    ]

    tts_started, tts_completed, queue_updated, state_updated = events

    started_segment = TranscriptSegment.model_validate(tts_started["payload"])
    completed_segment = TranscriptSegment.model_validate(tts_completed["payload"])
    assert completed_segment.model_dump() == started_segment.model_dump()

    queue_payload = queue_updated["payload"]
    queue = [QueueItem.model_validate(item) for item in queue_payload["queue"]]
    assert [item.track_id for item in queue] == ["apple:track:rainy-focus-02"]

    station_state = StationState.model_validate(state_updated["payload"])
    assert station_state.mode == "radio_continue"
    assert station_state.status == "speaking"
    assert station_state.talk_density == "balanced"
    assert station_state.queue[0].track_id == "apple:track:rainy-focus-02"
