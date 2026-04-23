from pathlib import Path

from moodio.state_store import StateStore


def test_state_store_persists_recent_operational_history(tmp_path: Path) -> None:
    db_path = tmp_path / "moodio.db"

    first_store = StateStore(db_path)
    first_store.record_command("play something warmer")
    first_store.record_play("apple:track:if-bread", "If")
    first_store.record_transcript("seg_001", "A late-night exhale.", 0, 3200)

    second_store = StateStore(db_path)
    second_store.record_command("play something brighter")
    second_store.record_play("apple:track:sunrise-set", "Sunrise Set")
    second_store.record_transcript("seg_002", "Turn it up a little.", 3200, 1800)

    snapshot = second_store.recent_context(limit=1)

    assert snapshot.commands[0].text == "play something brighter"
    assert snapshot.plays[0].track_id == "apple:track:sunrise-set"
    assert snapshot.transcript[0].segment_id == "seg_002"

    full_snapshot = second_store.recent_context(limit=5)

    assert [item.text for item in full_snapshot.commands] == [
        "play something brighter",
        "play something warmer",
    ]
    assert [item.track_id for item in full_snapshot.plays] == [
        "apple:track:sunrise-set",
        "apple:track:if-bread",
    ]
    assert [item.segment_id for item in full_snapshot.transcript] == [
        "seg_002",
        "seg_001",
    ]


def test_state_store_rejects_negative_limits(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "moodio.db")

    store.record_command("play something warmer")

    try:
        store.recent_context(limit=-1)
    except ValueError:
        pass
    else:
        raise AssertionError("recent_context() should reject negative limits")
