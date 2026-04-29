from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from moodio.domain.models import QueueItem


_PROVIDER_LABELS = {
    "soundcloud": "SoundCloud",
}


class ProviderTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    provider_track_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    album: str | None = None
    duration_seconds: int = Field(gt=0)
    artwork_url: str | None = None
    playback_ref: str = Field(min_length=1)
    external_url: str | None = None
    stream_url: str | None = None
    embed_html: str | None = None
    attribution: dict[str, str] = Field(default_factory=dict)

    def to_queue_item(self) -> QueueItem:
        return QueueItem.model_validate(
            {
                "track_id": self.playback_ref,
                "title": self.title,
                "artist": self.artist,
                "album": self.album or _PROVIDER_LABELS.get(self.provider, self.provider.title()),
                "duration_seconds": self.duration_seconds,
                "playback_ref": self.playback_ref,
                "artwork_url": self.artwork_url or "https://example.test/artwork/provider-track.jpg",
            }
        )


class MusicProvider(Protocol):
    async def search_tracks(self, query: str, limit: int = 10) -> list[ProviderTrack]:
        """Search provider catalog for streamable or queueable tracks."""
        ...

    async def resolve_track(self, provider_track_id: str) -> ProviderTrack:
        """Resolve a provider-specific track id to normalized metadata."""
        ...

    async def queue_payload(self, track: ProviderTrack) -> QueueItem:
        """Return the runtime queue representation for a normalized track."""
        ...
