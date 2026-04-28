from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class NowPlaying(QueueItem):
    pass


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
    queue: list[QueueItem]
    favorites_enabled: bool
