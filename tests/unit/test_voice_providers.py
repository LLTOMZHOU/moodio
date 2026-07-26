from __future__ import annotations

from pathlib import Path

from moodio.voice import ElevenLabsSpeechSynthesizer, OpenAISpeechSynthesizer, OpenAITranscriber, SpeechAudio


def test_speech_audio_payload_exposes_frontend_ready_metadata(tmp_path) -> None:
    audio_path = tmp_path / "line.mp3"
    audio_path.write_bytes(b"mp3")

    payload = SpeechAudio(
        url=f"file://{audio_path}",
        path=audio_path,
        content_type="audio/mpeg",
        text="Short line.",
        voice="cedar",
    ).model_dump()

    assert payload == {
        "url": f"file://{audio_path}",
        "path": audio_path,
        "content_type": "audio/mpeg",
        "text": "Short line.",
        "voice": "cedar",
    }


def test_openai_speech_synthesizer_writes_response_bytes(tmp_path) -> None:
    class FakeSpeech:
        def create(self, **kwargs):
            assert kwargs == {
                "model": "tts-test",
                "voice": "cedar",
                "input": "Hello from moodio.",
                "response_format": "mp3",
            }
            return b"audio-bytes"

    class FakeClient:
        class Audio:
            speech = FakeSpeech()

        audio = Audio()

    synthesizer = OpenAISpeechSynthesizer(
        client=FakeClient(),
        model="tts-test",
        voice="cedar",
        response_format="mp3",
        cache_dir=tmp_path,
    )

    audio = synthesizer.synthesize("Hello from moodio.", voice="cedar")

    assert audio.content_type == "audio/mpeg"
    assert audio.text == "Hello from moodio."
    assert audio.voice == "cedar"
    assert audio.url.startswith("/api/tts/")
    assert Path(audio.path).read_bytes() == b"audio-bytes"


def test_openai_speech_synthesizer_uses_dedicated_audio_api_key(monkeypatch, tmp_path) -> None:
    seen: dict[str, str | None] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            seen["api_key"] = api_key
            seen["base_url"] = base_url

        class Audio:
            class Speech:
                def create(self, **_: object) -> bytes:
                    return b"audio-bytes"

            speech = Speech()

        audio = Audio()

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_AUDIO_API_KEY", "audio-key")
    monkeypatch.setattr("moodio.voice.OpenAI", FakeOpenAI)

    synthesizer = OpenAISpeechSynthesizer(cache_dir=tmp_path)
    synthesizer.synthesize("Hello from moodio.")

    assert seen["api_key"] == "audio-key"


def test_openai_speech_synthesizer_can_target_openrouter_base_url(monkeypatch, tmp_path) -> None:
    seen: dict[str, str | None] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            seen["api_key"] = api_key
            seen["base_url"] = base_url

        class Audio:
            class Speech:
                def create(self, **kwargs: object) -> bytes:
                    seen["model"] = str(kwargs["model"])
                    return b"audio-bytes"

            speech = Speech()

        audio = Audio()

    monkeypatch.setattr("moodio.voice.OpenAI", FakeOpenAI)

    synthesizer = OpenAISpeechSynthesizer(
        api_key="router-key",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o-mini-tts-2025-12-15",
        cache_dir=tmp_path,
    )
    synthesizer.synthesize("Hello from moodio.")

    assert seen["api_key"] == "router-key"
    assert seen["base_url"] == "https://openrouter.ai/api/v1"
    assert seen["model"] == "openai/gpt-4o-mini-tts-2025-12-15"


def test_openai_transcriber_returns_text_from_audio_bytes() -> None:
    class FakeTranscriptions:
        def create(self, **kwargs):
            assert kwargs["model"] == "transcribe-test"
            assert kwargs["file"][0] == "input.wav"
            assert kwargs["file"][1].read() == b"wav-bytes"
            assert kwargs["file"][2] == "audio/wav"
            return type("Transcription", (), {"text": "play something softer"})()

    class FakeClient:
        class Audio:
            transcriptions = FakeTranscriptions()

        audio = Audio()

    transcriber = OpenAITranscriber(client=FakeClient(), model="transcribe-test")

    assert (
        transcriber.transcribe(b"wav-bytes", filename="input.wav", content_type="audio/wav")
        == "play something softer"
    )


def test_elevenlabs_speech_synthesizer_writes_response_bytes(tmp_path) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        ok = True
        content = b"eleven-audio"

        def raise_for_status(self) -> None:
            return None

    class FakeHttpClient:
        def post(self, url: str, **kwargs: object) -> FakeResponse:
            seen["url"] = url
            seen.update(kwargs)
            return FakeResponse()

    synthesizer = ElevenLabsSpeechSynthesizer(
        api_key="eleven-key",
        voice_id="voice-123",
        model="eleven_flash_v2_5",
        output_format="mp3_44100_128",
        cache_dir=tmp_path,
        http_client=FakeHttpClient(),
    )

    audio = synthesizer.synthesize("Hello from moodio.", voice="ignored-runtime-voice")

    assert seen["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-123"
    assert seen["params"] == {"output_format": "mp3_44100_128"}
    assert seen["headers"] == {"xi-api-key": "eleven-key", "content-type": "application/json"}
    assert seen["json"] == {"text": "Hello from moodio.", "model_id": "eleven_flash_v2_5"}
    assert audio.content_type == "audio/mpeg"
    assert audio.voice == "voice-123"
    assert audio.url.startswith("/api/tts/")
    assert Path(audio.path).read_bytes() == b"eleven-audio"
