from __future__ import annotations

from fastapi.testclient import TestClient

from moodio.music.providers import ProviderTrack
from moodio.api.server import create_app
from moodio.runtime.control import StationControl
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


def test_get_root_serves_minimal_frontend() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    script_response = client.get("/app.js")
    style_response = client.get("/styles.css")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "moodio-console" in response.text
    assert "https://w.soundcloud.com/player/api.js" in response.text
    assert script_response.status_code == 200
    assert "application/javascript" in script_response.headers["content-type"]
    assert "refreshState" in script_response.text
    assert "SC.Widget" in script_response.text
    assert "soundCloudReady" in script_response.text
    assert "renderedPlaybackRef" in script_response.text
    assert "renderQueueItem" in script_response.text
    assert "demo" in script_response.text
    assert "chatMessages" in script_response.text
    assert "addChatMessage" in script_response.text
    assert "playTtsAudio" in script_response.text
    assert "showTtsFailure" in script_response.text
    assert "SC.Widget.Events.READY" in script_response.text
    assert "playSoundCloud" in script_response.text
    assert "soundcloud-open-link" in response.text
    assert "radio-dial" in response.text
    assert "vu-meter" in response.text
    assert "speaker-grille" in response.text
    assert "chat-panel" in response.text
    assert "voice-button" in response.text
    assert "Talk to moodio" in response.text
    assert "soundcloud url" not in response.text.lower()
    assert 'id="embed-form"' not in response.text
    assert 'id="embed-input"' not in response.text
    assert "https://soundcloud.com/..." not in response.text
    assert "openSoundCloudTrack" in script_response.text
    assert style_response.status_code == 200
    assert "text/css" in style_response.headers["content-type"]


def test_post_soundcloud_embed_queues_embeddable_track(tmp_path) -> None:
    soundcloud_url = "https://soundcloud.com/ofmonstersandmen/the-actor"

    class FakeSoundCloudProvider:
        async def resolve_embed_url(self, url: str) -> ProviderTrack:
            assert url == soundcloud_url
            return ProviderTrack(
                provider="soundcloud",
                provider_track_id=url,
                title="The Actor",
                artist="Of Monsters and Men",
                album=None,
                duration_seconds=1,
                artwork_url="https://i1.sndcdn.com/artworks-actor.jpg",
                playback_ref=f"soundcloud:embed:{url}",
                external_url=url,
                stream_url=None,
                embed_html="<iframe></iframe>",
                attribution={
                    "source": "SoundCloud",
                    "creator": "Of Monsters and Men",
                    "external_url": url,
                },
            )

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        soundcloud_provider=FakeSoundCloudProvider(),
    )
    client = TestClient(create_app(runtime=runtime))

    response = client.post("/api/queue/soundcloud-embed", json={"url": soundcloud_url})

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["queue"][0]["track_id"] == f"soundcloud:embed:{soundcloud_url}"
    assert runtime.station_state.queue[0].artist == "Of Monsters and Men"


def test_post_command_runs_full_runtime_loop(tmp_path) -> None:
    seen_payloads: list[dict] = []
    seen_controls: list[StationControl] = []

    async def fake_run_station_turn(input_payload: dict | str, control: StationControl, session) -> str:
        seen_payloads.append(input_payload)
        seen_controls.append(control)
        await control.set_talk_density("low")
        return "Let me warm things up a touch."

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
    assert seen_controls[0].runtime is runtime
    # With multi-turn sessions, the runner receives the raw user text,
    # not an assembled context dict. The agent accesses state through tools.
    assert seen_payloads[0] == "play something warmer"

    recent_context = app.state.runtime.state_store.recent_context(limit=5)
    assert recent_context.commands[0].text == "play something warmer"

    now_response = client.get("/api/now")
    now_payload = now_response.json()
    assert now_payload["mode"] == "user_request"
    assert now_payload["status"] == "speaking"
    assert now_payload["talk_density"] == "low"

    transcript_response = client.get("/api/transcript/current")
    transcript_payload = transcript_response.json()
    assert transcript_payload["segments"][0]["text"] == "Let me warm things up a touch."


def test_post_command_updates_persisted_play_context_for_next_turn(tmp_path) -> None:
    seen_payloads: list[dict] = []

    async def fake_run_station_turn(input_payload: dict | str, control: StationControl, session) -> str:
        seen_payloads.append(input_payload)
        if len(seen_payloads) == 1:
            await control.next_track()
            return "Moving to the warmer follow-up."

        return "Keeping it flowing."

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_run_station_turn,
    )
    client = TestClient(create_app(runtime=runtime))

    first_response = client.post("/api/command", json={"text": "play something warmer"})
    assert first_response.status_code == 202
    first_recent_context = runtime.state_store.recent_context(limit=5)
    assert first_recent_context.plays[0].track_id == "apple:track:soft-sunset-02"

    second_response = client.post("/api/command", json={"text": "keep it flowing"})
    assert second_response.status_code == 202

    # With multi-turn sessions, the runner receives the raw user text.
    # Persisted memory is available to the agent via tools, not in the input payload.
    assert seen_payloads[1] == "keep it flowing"
    recent_context = runtime.state_store.recent_context(limit=5)
    assert recent_context.commands[0].text == "keep it flowing"
    assert recent_context.plays[0].track_id == "apple:track:soft-sunset-02"

def test_post_next_advances_queue_and_returns_current_track() -> None:
    client = TestClient(create_app())

    response = client.post("/api/next")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["now_playing"]["track_id"] == "apple:track:soft-sunset-02"


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


def test_post_transcribe_returns_text_from_audio_body(tmp_path) -> None:
    class FakeTranscriber:
        def transcribe(self, audio: bytes, *, filename: str, content_type: str) -> str:
            assert audio == b"audio-bytes"
            assert filename == "command.wav"
            assert content_type == "audio/wav"
            return "play something warmer"

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        speech_transcriber=FakeTranscriber(),
    )
    client = TestClient(create_app(runtime=runtime))

    response = client.post(
        "/api/transcribe?filename=command.wav",
        content=b"audio-bytes",
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "play something warmer"}


def test_get_tts_audio_serves_cached_audio_file(tmp_path) -> None:
    cache_dir = tmp_path / "tts"
    cache_dir.mkdir()
    audio_file = cache_dir / "line.mp3"
    audio_file.write_bytes(b"mp3-bytes")

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        tts_cache_dir=cache_dir,
    )
    client = TestClient(create_app(runtime=runtime))

    response = client.get("/api/tts/line.mp3")

    assert response.status_code == 200
    assert response.content == b"mp3-bytes"
    assert response.headers["content-type"] == "audio/mpeg"



def test_post_preferences_import_persists_listener_preferences(tmp_path) -> None:
    runtime = RuntimeService(state_store=StateStore(tmp_path / "moodio.db"))
    client = TestClient(create_app(runtime=runtime))

    response = client.post(
        "/api/preferences/import",
        json={
            "source": "apple_music",
            "profile_text": "Phoebe Bridgers\nJapanese Breakfast\nRainy Day",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "apple_music"
    assert len(payload["seed_queries"]) >= 3
    assert runtime.state_store.get_listener_preferences() is not None
