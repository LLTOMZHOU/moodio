from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
}


class SpeechAudio(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str = Field(min_length=1)
    path: Path
    content_type: str = Field(min_length=1)
    text: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechAudio:
        """Synthesize spoken audio for a station line."""
        ...


class SpeechTranscriber(Protocol):
    def transcribe(self, audio: bytes, *, filename: str, content_type: str) -> str:
        """Transcribe an audio command into text."""
        ...


class OpenAISpeechSynthesizer:
    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
        cache_dir: Path | str = "var/cache/tts",
    ) -> None:
        self.client = client or OpenAI()
        self.model = model or os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = voice or os.environ.get("OPENAI_TTS_VOICE", "cedar")
        self.response_format = response_format or os.environ.get("OPENAI_TTS_RESPONSE_FORMAT", "mp3")
        self.cache_dir = Path(cache_dir)

    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechAudio:
        selected_voice = voice or self.voice
        response = self.client.audio.speech.create(
            model=self.model,
            voice=selected_voice,
            input=text,
            response_format=self.response_format,
        )
        audio_bytes = _response_bytes(response)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{self.model}:{selected_voice}:{text}".encode("utf-8")).hexdigest()
        audio_path = self.cache_dir / f"{digest}.{self.response_format}"
        audio_path.write_bytes(audio_bytes)
        return SpeechAudio(
            url=audio_path.resolve().as_uri(),
            path=audio_path,
            content_type=_CONTENT_TYPES.get(self.response_format, "application/octet-stream"),
            text=text,
            voice=selected_voice,
        )


class OpenAITranscriber:
    def __init__(self, *, client: OpenAI | None = None, model: str | None = None) -> None:
        self.client = client or OpenAI()
        self.model = model or os.environ.get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")

    def transcribe(self, audio: bytes, *, filename: str, content_type: str) -> str:
        result = self.client.audio.transcriptions.create(
            model=self.model,
            file=(filename, BytesIO(audio), content_type),
        )
        text = getattr(result, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("transcription response did not include text")
        return text.strip()


def _response_bytes(response: object) -> bytes:
    if isinstance(response, bytes):
        return response
    if hasattr(response, "read"):
        content = response.read()
        if isinstance(content, bytes):
            return content
    if hasattr(response, "content") and isinstance(response.content, bytes):
        return response.content
    if hasattr(response, "write_to_file"):
        buffer = BytesIO()
        response.write_to_file(buffer)
        return buffer.getvalue()
    raise TypeError("unsupported speech response type")
