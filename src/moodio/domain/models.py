from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STATION_PLACEHOLDER_TRACK_ID = "moodio:track:current"


StationMode = Literal["radio_continue", "user_request", "recovery", "chat", "playlist_build", "manual_control"]
StationStatus = Literal["idle", "thinking", "speaking", "playing", "recovering", "offline"]
TalkDensity = Literal["low", "balanced", "high"]
PlaybackEventType = Literal[
    "music.playback.started",
    "music.playback.progress",
    "music.playback.near_end",
    "music.playback.ended",
    "music.playback.paused",
    "music.playback.resumed",
]


class QueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    album: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    playback_ref: str = Field(min_length=1)
    artwork_url: str = Field(min_length=1)
    external_url: str | None = None


class NowPlaying(QueueItem):
    pass


ProgramItemKind = Literal["music", "commentary"]
ProgramItemOrigin = Literal["listener", "dj", "scheduler"]
ProgramItemStatus = Literal["queued", "current", "played", "skipped", "unavailable"]


class ProgramItem(BaseModel):
    """One ordered station-program entry, either music or optional commentary."""

    model_config = ConfigDict(extra="forbid")

    program_item_id: str = Field(default_factory=lambda: f"pi_{uuid.uuid4().hex[:12]}")
    kind: ProgramItemKind
    origin: ProgramItemOrigin
    reason: str = Field(min_length=1, max_length=400)
    status: ProgramItemStatus = "queued"
    track: QueueItem | None = None
    text: str | None = Field(default=None, max_length=1_500)
    for_music_item_id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ProgramItem":
        if self.kind == "music" and self.track is None:
            raise ValueError("music program items require a track")
        if self.kind == "commentary" and not (self.text or "").strip():
            raise ValueError("commentary program items require text")
        if self.kind == "commentary" and self.track is not None:
            raise ValueError("commentary program items cannot include a track")
        return self

    @classmethod
    def music(cls, track: QueueItem, *, origin: ProgramItemOrigin, reason: str) -> "ProgramItem":
        return cls(kind="music", origin=origin, reason=reason, track=track)

    @classmethod
    def commentary(
        cls,
        text: str,
        *,
        origin: ProgramItemOrigin,
        reason: str,
        for_music_item_id: str | None = None,
    ) -> "ProgramItem":
        return cls(
            kind="commentary",
            origin=origin,
            reason=reason,
            text=text,
            for_music_item_id=for_music_item_id,
        )


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1_500)
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    voice: str = Field(min_length=1)
    state: Literal["speaking"]


class PlaybackEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: PlaybackEventType
    track_id: str = Field(min_length=1)
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)


class StationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(min_length=1)
    mode: StationMode
    status: StationStatus
    talk_density: TalkDensity
    now_playing: NowPlaying
    queue: list[ProgramItem]
    queue_revision: int = Field(default=0, ge=0)
    favorites_enabled: bool
    voice_mode: bool = False
