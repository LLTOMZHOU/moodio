from pathlib import Path

from moodio.state_store import StateStore


def test_state_store_persists_recent_operational_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "moodio.db")

    store.record_command("play something warmer")
    store.record_play("apple:track:if-bread", "If")
    store.record_transcript("seg_001", "A late-night exhale.", 0, 3200)

    snapshot = store.recent_context(limit=5)

    assert snapshot["commands"][0]["text"] == "play something warmer"
    assert snapshot["plays"][0]["track_id"] == "apple:track:if-bread"
    assert snapshot["transcript"][0]["segment_id"] == "seg_001"
