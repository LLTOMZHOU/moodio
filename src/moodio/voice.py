from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
import requests


_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "mp3_44100_128": "audio/mpeg",
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
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
        cache_dir: Path | str = "var/cache/tts",
        public_url_prefix: str = "/api/tts",
    ) -> None:
        self.client = client or OpenAI(api_key=api_key or _openai_audio_api_key(), base_url=base_url)
        self.model = model or os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = voice or os.environ.get("OPENAI_TTS_VOICE", "cedar")
        self.response_format = response_format or os.environ.get("OPENAI_TTS_RESPONSE_FORMAT", "mp3")
        self.cache_dir = Path(cache_dir)
        self.public_url_prefix = public_url_prefix.rstrip("/")

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
            url=f"{self.public_url_prefix}/{audio_path.name}",
            path=audio_path,
            content_type=_CONTENT_TYPES.get(self.response_format, "application/octet-stream"),
            text=text,
            voice=selected_voice,
        )


class ElevenLabsSpeechSynthesizer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
        output_format: str | None = None,
        cache_dir: Path | str = "var/cache/tts",
        public_url_prefix: str = "/api/tts",
        http_client: object | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS")
        if not self.voice_id:
            raise ValueError("ELEVENLABS_VOICE_ID is required for ElevenLabs TTS")

        self.model = model or os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
        self.output_format = output_format or os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
        self.cache_dir = Path(cache_dir)
        self.public_url_prefix = public_url_prefix.rstrip("/")
        self.http_client = http_client or requests

    def synthesize(self, text: str, *, voice: str | None = None) -> SpeechAudio:
        response = self.http_client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            params={"output_format": self.output_format},
            headers={"xi-api-key": self.api_key, "content-type": "application/json"},
            json={"text": text, "model_id": self.model},
            timeout=30,
        )
        response.raise_for_status()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"elevenlabs:{self.model}:{self.voice_id}:{text}".encode("utf-8")).hexdigest()
        suffix = "mp3" if self.output_format.startswith("mp3") else self.output_format.split("_", maxsplit=1)[0]
        audio_path = self.cache_dir / f"{digest}.{suffix}"
        audio_path.write_bytes(response.content)
        return SpeechAudio(
            url=f"{self.public_url_prefix}/{audio_path.name}",
            path=audio_path,
            content_type=_CONTENT_TYPES.get(self.output_format, "application/octet-stream"),
            text=text,
            voice=self.voice_id,
        )


class OpenAITranscriber:
    def __init__(self, *, client: OpenAI | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.client = client or OpenAI(api_key=api_key or _openai_audio_api_key())
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


def _openai_audio_api_key() -> str | None:
    return os.environ.get("OPENAI_AUDIO_API_KEY") or os.environ.get("OPENAI_API_KEY")
