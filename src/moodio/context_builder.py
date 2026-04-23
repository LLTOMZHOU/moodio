from __future__ import annotations


def build_context_payload(
    mode: str,
    trigger: dict,
    user_corpus: dict,
    environment: dict,
    recent_context: dict,
    scheduler_payload: dict | None,
) -> dict:
    return {
        "mode": mode,
        "context": {
            "system_instructions": {
                "host_name": "moodio",
                "voice": "default_male_1",
            },
            "user_corpus": user_corpus,
            "environment_snapshot": environment,
            "persisted_memory": recent_context,
            "latest_input": trigger,
            "scheduler_payload": scheduler_payload,
        },
    }
