from __future__ import annotations

from fastapi.testclient import TestClient

from moodio.api.server import create_app


def test_websocket_sends_initial_station_state_snapshot() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/api/stream") as websocket:
        event = websocket.receive_json()

    assert event["event"] == "station.state.updated"
    assert event["payload"]["host_name"] == "moodio"


def test_websocket_receives_queue_update_after_next_action() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/api/stream") as websocket:
        initial_event = websocket.receive_json()
        assert initial_event["event"] == "station.state.updated"

        response = client.post("/api/next")
        assert response.status_code == 200

        queue_event = websocket.receive_json()
        state_event = websocket.receive_json()

    assert queue_event["event"] == "queue.updated"
    assert state_event["event"] == "station.state.updated"
    assert state_event["payload"]["now_playing"]["track_id"] == "apple:track:rainy-focus-02"


def test_websocket_receives_favorite_event_after_direct_favorite() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/api/stream") as websocket:
        initial_event = websocket.receive_json()
        assert initial_event["event"] == "station.state.updated"

        response = client.post("/api/favorite", json={"track_id": "apple:track:if-bread"})
        assert response.status_code == 200

        event = websocket.receive_json()

    assert event["event"] == "favorites.updated"
    assert event["payload"]["track_id"] == "apple:track:if-bread"
    assert event["payload"]["favorited"] is True


def test_websocket_receives_playback_near_end_event_after_frontend_signal() -> None:
    client = TestClient(create_app())

    with client.websocket_connect("/api/stream") as websocket:
        initial_event = websocket.receive_json()
        assert initial_event["event"] == "station.state.updated"

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

        event = websocket.receive_json()

    assert event["event"] == "music.playback.near_end"
    assert event["payload"]["track_id"] == "apple:track:if-bread"
