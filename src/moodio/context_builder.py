from __future__ import annotations

from dataclasses import asdict, is_dataclass


def build_context_payload(
    mode: str,
    trigger: dict,
    user_corpus: dict,
    environment: dict,
    recent_context: dict,
    scheduler_payload: dict | None,
) -> dict:
    if is_dataclass(recent_context):
        persisted_memory = asdict(recent_context)
    else:
        persisted_memory = recent_context

    return {
        "mode": mode,
        "context": {
            "system_instructions": {
                "host_name": "moodio",
                "voice": "default_male_1",
            },
            "user_corpus": user_corpus,
            "environment_snapshot": environment,
            "persisted_memory": persisted_memory,
            "latest_input": trigger,
            "scheduler_payload": scheduler_payload,
        },
    }
