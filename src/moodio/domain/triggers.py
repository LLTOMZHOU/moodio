from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from moodio.domain.models import PlaybackEventType


class UserCommandTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user_command"] = "user_command"
    text: str = Field(min_length=1)


class PlaybackTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["playback"] = "playback"
    event_type: PlaybackEventType
    track_id: str = Field(min_length=1)
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)


class SchedulerTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["scheduler"] = "scheduler"
    reason: str = Field(min_length=1)


Trigger = UserCommandTrigger | PlaybackTrigger | SchedulerTrigger
