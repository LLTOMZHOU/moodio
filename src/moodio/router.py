from __future__ import annotations

from moodio.domain.models import StationMode
from moodio.domain.triggers import PlaybackTrigger, Trigger, UserCommandTrigger


def route_trigger(trigger: Trigger, queue_depth: int, provider_error: bool) -> StationMode:
    if queue_depth == 0:
        return "recovery"
    if isinstance(trigger, UserCommandTrigger):
        return "user_request"
    if isinstance(trigger, PlaybackTrigger) and trigger.event_type == "music.playback.near_end":
        return "radio_continue"
    return "radio_continue"
