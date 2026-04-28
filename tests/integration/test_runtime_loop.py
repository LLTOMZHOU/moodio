import asyncio
from types import SimpleNamespace

from moodio.api.schemas import FinalAction
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment
from moodio.executor import execute_action
from moodio.station_agent import run_station_turn
from tests.fixtures.fake_model import fake_agent_result


def test_station_agent_runs_structured_final_action_through_runner(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_run(agent, input):
        seen["agent"] = agent
        seen["input"] = input
        return SimpleNamespace(final_output=fake_agent_result())

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-1"}))

    assert result.mode == "radio_continue"
    assert result.say is not None
    assert result.say.voice == "default_male_1"
    assert seen["input"] == {"turn_id": "soft-turn-1"}
    assert seen["agent"].output_type is FinalAction
    assert seen["agent"].tools == []


def test_station_agent_accepts_model_selected_mode_on_soft_turns(monkeypatch) -> None:
    async def fake_run(agent, input):
        return SimpleNamespace(final_output=fake_agent_result(mode="user_request"))

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-2"}))

    assert result.mode == "user_request"


def test_station_agent_delegates_result_parsing(monkeypatch) -> None:
    payload = fake_agent_result(mode="user_request")
    expected = FinalAction.model_validate(fake_agent_result(mode="recovery"))
    seen: dict[str, object] = {}

    async def fake_run(agent, input):
        return SimpleNamespace(final_output=payload)

    def fake_parse_agent_result(raw_payload):
        seen["payload"] = raw_payload
        return expected

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)
    monkeypatch.setattr("moodio.station_agent.parse_agent_result", fake_parse_agent_result)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-3"}))

    assert seen["payload"] == payload
    assert result is expected


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
    assert station_state.now_playing.track_id == STATION_PLACEHOLDER_TRACK_ID
    assert station_state.queue[0].track_id == "apple:track:rainy-focus-02"


def test_execute_action_with_no_queue_tracks_keeps_station_queue_empty() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "radio_continue",
            "say": {
                "text": "Staying with the current track.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [],
            "player_actions": [],
            "talk_density": "balanced",
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.segment.completed",
        "station.state.updated",
    ]

    station_state = StationState.model_validate(events[-1]["payload"])
    assert station_state.queue == []
    assert station_state.status == "speaking"


def test_execute_action_maps_unknown_track_id_to_deterministic_queue_payload() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "user_request",
            "say": None,
            "queue_tracks": [
                {
                    "track_id": "apple:track:brand-new-id",
                    "reason": "requested next",
                    "start_policy": "immediate",
                }
            ],
            "player_actions": [],
            "talk_density": None,
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "queue.updated",
        "station.state.updated",
    ]

    queue_item = QueueItem.model_validate(events[0]["payload"]["queue"][0])
    assert queue_item.model_dump() == {
        "track_id": "apple:track:brand-new-id",
        "title": "Brand New Id",
        "artist": "Moodio Runtime",
        "album": "Pending Queue",
        "duration_seconds": 180,
        "playback_ref": "apple:track:brand-new-id",
        "artwork_url": "https://example.test/artwork/pending-queue.jpg",
    }

    station_state = StationState.model_validate(events[1]["payload"])
    assert station_state.queue[0].model_dump() == queue_item.model_dump()
    assert station_state.talk_density == "balanced"
    assert station_state.status == "playing"
