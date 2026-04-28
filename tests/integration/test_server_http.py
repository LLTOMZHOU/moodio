from __future__ import annotations

from fastapi.testclient import TestClient

from moodio.api.schemas import FinalAction
from moodio.api.server import create_app
from moodio.runtime.service import RuntimeService
from moodio.state_store import StateStore


def test_get_now_returns_station_snapshot() -> None:
    client = TestClient(create_app())

    response = client.get("/api/now")

    assert response.status_code == 200
    payload = response.json()
    assert payload["host_name"] == "moodio"
    assert payload["status"] in {"playing", "thinking", "speaking", "idle", "recovering", "offline"}
    assert payload["now_playing"]["track_id"] == "apple:track:if-bread"


def test_get_current_transcript_returns_current_segment_list() -> None:
    client = TestClient(create_app())

    response = client.get("/api/transcript/current")

    assert response.status_code == 200
    payload = response.json()
    assert "segments" in payload
    assert len(payload["segments"]) >= 1
    assert payload["segments"][0]["segment_id"] == "seg_001"


def test_post_command_runs_full_runtime_loop(tmp_path) -> None:
    seen_payloads: list[dict] = []

    async def fake_run_station_turn(input_payload: dict) -> FinalAction:
        seen_payloads.append(input_payload)
        return FinalAction.model_validate(
            {
                "mode": "user_request",
                "say": {
                    "text": "Let me warm things up a touch.",
                    "voice": "default_male_1",
                    "interruptible": True,
                },
                "queue_tracks": [
                    {
                        "track_id": "apple:track:cozy-synth-01",
                        "reason": "warmer follow-up",
                        "start_policy": "after_tts",
                    }
                ],
                "player_actions": [],
                "talk_density": "low",
            }
        )

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_run_station_turn,
    )
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post("/api/command", json={"text": "play something warmer"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["kind"] == "natural_language"
    assert payload["text"] == "play something warmer"
    assert len(seen_payloads) == 1
    input_payload = seen_payloads[0]
    assert input_payload["mode"] == "user_request"
    assert input_payload["context"]["latest_input"] == {
        "kind": "user_command",
        "text": "play something warmer",
    }
    assert input_payload["context"]["persisted_memory"]["commands"][0]["text"] == "play something warmer"
    assert input_payload["context"]["persisted_memory"]["plays"][0]["track_id"] == "apple:track:if-bread"
    assert input_payload["context"]["environment_snapshot"]["station_state"]["mode"] == "radio_continue"

    recent_context = app.state.runtime.state_store.recent_context(limit=5)
    assert recent_context.commands[0].text == "play something warmer"

    now_response = client.get("/api/now")
    now_payload = now_response.json()
    assert now_payload["mode"] == "user_request"
    assert now_payload["status"] == "speaking"
    assert now_payload["talk_density"] == "low"
    assert now_payload["queue"][0]["track_id"] == "apple:track:cozy-synth-01"

    transcript_response = client.get("/api/transcript/current")
    transcript_payload = transcript_response.json()
    assert transcript_payload["segments"][0]["text"] == "Let me warm things up a touch."


def test_post_command_updates_persisted_play_context_for_next_turn(tmp_path) -> None:
    seen_payloads: list[dict] = []

    async def fake_run_station_turn(input_payload: dict) -> FinalAction:
        seen_payloads.append(input_payload)
        if len(seen_payloads) == 1:
            return FinalAction.model_validate(
                {
                    "mode": "user_request",
                    "say": None,
                    "queue_tracks": [
                        {
                            "track_id": "apple:track:cozy-synth-01",
                            "reason": "warmer follow-up",
                            "start_policy": "after_tts",
                        }
                    ],
                    "player_actions": [],
                    "talk_density": "low",
                }
            )

        return FinalAction.model_validate(
            {
                "mode": "radio_continue",
                "say": None,
                "queue_tracks": [],
                "player_actions": [],
                "talk_density": "balanced",
            }
        )

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_run_station_turn,
    )
    client = TestClient(create_app(runtime=runtime))

    first_response = client.post("/api/command", json={"text": "play something warmer"})
    assert first_response.status_code == 202

    second_response = client.post("/api/command", json={"text": "keep it flowing"})
    assert second_response.status_code == 202

    second_persisted_memory = seen_payloads[1]["context"]["persisted_memory"]
    assert second_persisted_memory["commands"][0]["text"] == "keep it flowing"
    assert second_persisted_memory["plays"][0]["track_id"] == "apple:track:cozy-synth-01"

def test_post_next_advances_queue_and_returns_current_track() -> None:
    client = TestClient(create_app())

    response = client.post("/api/next")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["now_playing"]["track_id"] == "apple:track:rainy-focus-02"


def test_post_previous_restores_previous_track_after_next() -> None:
    client = TestClient(create_app())

    next_response = client.post("/api/next")
    assert next_response.status_code == 200

    response = client.post("/api/previous")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["now_playing"]["track_id"] == "apple:track:if-bread"


def test_post_pause_accepts_direct_transport_action() -> None:
    client = TestClient(create_app())

    response = client.post("/api/pause")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["action"] == "pause"


def test_post_play_accepts_direct_transport_action() -> None:
    client = TestClient(create_app())

    response = client.post("/api/play")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["action"] == "play"


def test_post_favorite_marks_current_track_favorited() -> None:
    client = TestClient(create_app())

    response = client.post("/api/favorite", json={"track_id": "apple:track:if-bread"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["track_id"] == "apple:track:if-bread"
    assert payload["favorited"] is True


def test_post_playback_event_accepts_near_end_signal_from_frontend() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events/playback",
        json={
            "event_type": "music.playback.near_end",
            "track_id": "apple:track:if-bread",
            "position_seconds": 182,
            "duration_seconds": 197,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["kind"] == "playback_event"
