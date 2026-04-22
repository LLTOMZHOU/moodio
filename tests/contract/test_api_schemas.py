from __future__ import annotations

import pytest

from moodio.api.schemas import CommandRequest, FavoriteRequest, NowResponse

from tests.fixtures.sample_data import sample_station_state


def test_command_request_accepts_natural_language_prompt() -> None:
    request = CommandRequest.model_validate({"text": "play something warmer"})

    assert request.text == "play something warmer"


def test_favorite_request_accepts_direct_button_action() -> None:
    request = FavoriteRequest.model_validate({"track_id": "apple:track:if-bread"})

    assert request.track_id == "apple:track:if-bread"


def test_now_response_accepts_current_station_snapshot() -> None:
    response = NowResponse.model_validate(sample_station_state())

    assert response.host_name == "moodio"
    assert response.now_playing.track_id == "apple:track:if-bread"


def test_command_request_rejects_empty_prompt() -> None:
    with pytest.raises(Exception):  # noqa: B017 - initial contract
        CommandRequest.model_validate({"text": ""})
