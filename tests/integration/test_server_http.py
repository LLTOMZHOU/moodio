from __future__ import annotations

from fastapi.testclient import TestClient

from moodio.api.server import create_app


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


def test_post_command_accepts_natural_language_request() -> None:
    client = TestClient(create_app())

    response = client.post("/api/command", json={"text": "play something warmer"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["kind"] == "natural_language"
    assert payload["text"] == "play something warmer"


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
