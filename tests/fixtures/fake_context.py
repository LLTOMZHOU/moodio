from __future__ import annotations

from moodio.state_store import CommandRecord, PlayRecord, StateContext, TranscriptRecord

from tests.fixtures.sample_data import sample_track, sample_transcript_segment


def fake_environment_snapshot() -> dict:
    return {"time_of_day": "night", "weather": "cool and clear"}


def fake_recent_context() -> StateContext:
    track = sample_track()
    transcript = sample_transcript_segment()

    return StateContext(
        commands=[CommandRecord(text="talk less")],
        plays=[PlayRecord(track_id=track["track_id"], title=track["title"])],
        transcript=[
            TranscriptRecord(
                segment_id=transcript["segment_id"],
                text=transcript["text"],
                start_ms=transcript["start_ms"],
                duration_ms=transcript["duration_ms"],
            )
        ],
    )
