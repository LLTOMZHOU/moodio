from __future__ import annotations


def fake_environment_snapshot() -> dict:
    return {"time_of_day": "night", "weather": "cool and clear"}


def fake_recent_context() -> dict:
    return {
        "commands": [{"text": "talk less"}],
        "plays": [{"track_id": "apple:track:if-bread", "title": "If"}],
        "transcript": [{"segment_id": "seg_001", "text": "Late-night exhale."}],
    }
