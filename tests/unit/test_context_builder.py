import json

from moodio.context_builder import build_context_payload
from moodio.state_store import StateStore

from tests.fixtures.sample_data import sample_track, sample_transcript_segment


def test_context_builder_assembles_six_buckets(tmp_path) -> None:
    db_path = tmp_path / "moodio.db"
    store = StateStore(db_path)
    track = sample_track()
    transcript = sample_transcript_segment()

    store.record_command("play something warmer")
    store.record_play(track["track_id"], track["title"])
    store.record_transcript(
        transcript["segment_id"],
        transcript["text"],
        transcript["start_ms"],
        transcript["duration_ms"],
    )

    payload = build_context_payload(
        mode="user_request",
        trigger={"kind": "user_command", "text": "play something warmer"},
        user_corpus={"taste": "soft rock at night"},
        environment={"time_of_day": "night", "weather": "cool and clear"},
        recent_context=store.recent_context(limit=5),
        scheduler_payload=None,
    )

    assert payload["mode"] == "user_request"
    assert set(payload["context"].keys()) == {
        "system_instructions",
        "user_corpus",
        "environment_snapshot",
        "persisted_memory",
        "latest_input",
        "scheduler_payload",
    }
    assert payload["context"]["persisted_memory"]["plays"][0]["track_id"] == track["track_id"]
    assert payload["context"]["persisted_memory"]["transcript"][0]["segment_id"] == transcript["segment_id"]
    json.dumps(payload)
