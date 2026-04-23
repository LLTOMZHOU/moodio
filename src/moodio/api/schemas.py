from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from moodio.domain.events import RuntimeEventName
from moodio.domain.models import PlaybackEvent, StationState, TalkDensity


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)


class NowResponse(StationState):
    pass


class SayAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    voice: str = Field(min_length=1)
    interruptible: bool


class QueueTrackAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=400)
    start_policy: Literal["after_tts", "immediate"]


class PlayerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["play", "pause", "resume", "next", "previous", "favorite", "unfavorite"]
    track_id: str | None = None

    @model_validator(mode="after")
    def validate_track_requirement(self) -> "PlayerAction":
        if self.type in {"favorite", "unfavorite"} and not self.track_id:
            raise ValueError("track_id is required for favorite actions")
        return self


class FinalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["radio_continue", "user_request", "recovery"]
    say: SayAction | None
    queue_tracks: list[QueueTrackAction]
    player_actions: list[PlayerAction]
    talk_density: TalkDensity | None = None


class StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: RuntimeEventName
    payload: Any


class TranscriptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[Any]


class AcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    kind: str
    text: str | None = None


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    track_id: str
    favorited: bool


class TransportActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    action: Literal["play", "pause", "next", "previous"]


class PlaybackEventRequest(PlaybackEvent):
    pass
