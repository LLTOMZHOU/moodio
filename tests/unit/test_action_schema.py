from __future__ import annotations

import pytest

from moodio.api.schemas import FinalAction

from tests.fixtures.sample_data import sample_favorite_action, sample_radio_continue_action


def test_final_action_accepts_valid_radio_continue_payload() -> None:
    action = FinalAction.model_validate(sample_radio_continue_action())

    assert action.mode == "radio_continue"
    assert action.say is not None
    assert action.say.voice == "default_male_1"


def test_final_action_accepts_deterministic_favorite_player_action() -> None:
    action = FinalAction.model_validate(sample_favorite_action())

    assert len(action.player_actions) == 1
    assert action.player_actions[0].type == "favorite"


def test_final_action_rejects_unknown_mode() -> None:
    payload = sample_radio_continue_action()
    payload["mode"] = "freestyle"

    with pytest.raises(Exception):  # noqa: B017 - initial contract
        FinalAction.model_validate(payload)


def test_final_action_rejects_overlong_dj_line() -> None:
    payload = sample_radio_continue_action()
    payload["say"]["text"] = "x" * 5000

    with pytest.raises(Exception):  # noqa: B017 - initial contract
        FinalAction.model_validate(payload)


def test_final_action_rejects_unknown_player_action() -> None:
    payload = sample_favorite_action()
    payload["player_actions"][0]["type"] = "shuffle_everything"

    with pytest.raises(Exception):  # noqa: B017 - initial contract
        FinalAction.model_validate(payload)
