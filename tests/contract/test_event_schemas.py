from __future__ import annotations

import pytest

from moodio.api.schemas import StreamEvent

from tests.fixtures.sample_data import sample_playback_event, sample_station_state, sample_transcript_segment


def test_stream_event_accepts_music_near_end_payload() -> None:
    event = StreamEvent.model_validate(
        {
            "event": "music.playback.near_end",
            "payload": sample_playback_event(),
        }
    )

    assert event.event == "music.playback.near_end"


def test_stream_event_accepts_station_state_snapshot_payload() -> None:
    event = StreamEvent.model_validate(
        {
            "event": "station.state.updated",
            "payload": sample_station_state(),
        }
    )

    assert event.event == "station.state.updated"


def test_stream_event_accepts_transcript_segment_payload() -> None:
    event = StreamEvent.model_validate(
        {
            "event": "tts.segment.started",
            "payload": sample_transcript_segment(),
        }
    )

    assert event.event == "tts.segment.started"


def test_stream_event_rejects_unknown_event_name() -> None:
    with pytest.raises(Exception):  # noqa: B017 - initial contract
        StreamEvent.model_validate(
            {
                "event": "agent.did_something_weird",
                "payload": {},
            }
        )
