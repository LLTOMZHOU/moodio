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


def test_route_playback_ended_falls_back_to_radio_continue() -> None:
    trigger = PlaybackTrigger(
        event_type="music.playback.ended",
        track_id="apple:track:if-bread",
        position_seconds=197,
        duration_seconds=197,
    )

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "radio_continue"


def test_route_empty_queue_to_recovery() -> None:
    trigger = SchedulerTrigger(reason="hourly refresh")

    route = route_trigger(trigger=trigger, queue_depth=0, provider_error=False)

    assert route == "recovery"


def test_scheduler_with_non_empty_queue_uses_radio_continue_fallback() -> None:
    trigger = SchedulerTrigger(reason="hourly refresh")

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "radio_continue"


def test_empty_queue_takes_precedence_over_user_and_playback_routes() -> None:
    user_route = route_trigger(
        trigger=UserCommandTrigger(text="play something warmer"),
        queue_depth=0,
        provider_error=False,
    )
    playback_route = route_trigger(
        trigger=PlaybackTrigger(
            event_type="music.playback.near_end",
            track_id="apple:track:if-bread",
            position_seconds=182,
            duration_seconds=197,
        ),
        queue_depth=0,
        provider_error=False,
    )

    assert user_route == "recovery"
    assert playback_route == "recovery"
