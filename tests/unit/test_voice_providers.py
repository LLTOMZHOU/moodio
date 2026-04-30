from __future__ import annotations

from pathlib import Path

from moodio.voice import OpenAISpeechSynthesizer, OpenAITranscriber, SpeechAudio


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
    assert Path(audio.path).read_bytes() == b"audio-bytes"


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
