from __future__ import annotations

from moodio.domain.models import NowPlaying, PlaybackEvent, QueueItem, StationState, TranscriptSegment

from tests.fixtures.sample_data import (
    sample_playback_event,
    sample_station_state,
    sample_track,
    sample_transcript_segment,
)


def test_now_playing_accepts_frontend_playback_reference() -> None:
    model = NowPlaying.model_validate(sample_track())

    assert model.track_id == "apple:track:if-bread"
    assert model.playback_ref == "apple_music:catalog:12345"


def test_station_state_keeps_queue_warm() -> None:
    state = StationState.model_validate(sample_station_state())

    assert state.status == "playing"
    assert len(state.queue) >= 1
    assert state.queue[0].track_id == "apple:track:rainy-focus-02"


def test_transcript_segment_requires_male_default_voice_in_fixture() -> None:
    segment = TranscriptSegment.model_validate(sample_transcript_segment())

    assert segment.voice == "default_male_1"
    assert segment.duration_ms > 0


def test_playback_event_supports_near_end_signal() -> None:
    event = PlaybackEvent.model_validate(sample_playback_event())

    assert event.event_type == "music.playback.near_end"
    assert event.position_seconds < event.duration_seconds


def test_queue_item_rejects_missing_playback_reference() -> None:
    payload = sample_track()
    payload.pop("playback_ref")

    try:
        QueueItem.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - initial TDD contract only
        assert "playback_ref" in str(exc)
    else:
        raise AssertionError("QueueItem accepted a payload without playback_ref")
