from moodio.context_builder import build_context_payload

from tests.fixtures.fake_context import fake_environment_snapshot, fake_recent_context


def test_context_builder_assembles_six_buckets() -> None:
    payload = build_context_payload(
        mode="user_request",
        trigger={"kind": "user_command", "text": "play something warmer"},
        user_corpus={"taste": "soft rock at night"},
        environment=fake_environment_snapshot(),
        recent_context=fake_recent_context(),
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
