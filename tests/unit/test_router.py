from __future__ import annotations

from moodio.domain.triggers import PlaybackTrigger, SchedulerTrigger, UserCommandTrigger
from moodio.router import route_trigger


def test_route_user_command_to_user_request() -> None:
    trigger = UserCommandTrigger(text="play something warmer")

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "user_request"


def test_route_playback_near_end_to_radio_continue() -> None:
    trigger = PlaybackTrigger(
        event_type="music.playback.near_end",
        track_id="apple:track:if-bread",
        position_seconds=182,
        duration_seconds=197,
    )

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "radio_continue"


def test_route_empty_queue_to_recovery() -> None:
    trigger = SchedulerTrigger(reason="hourly refresh")

    route = route_trigger(trigger=trigger, queue_depth=0, provider_error=False)

    assert route == "recovery"
