def fake_agent_result(mode: str = "radio_continue") -> dict:
    return {
        "mode": mode,
        "say": {
            "text": "Staying warm and gentle here.",
            "voice": "default_male_1",
            "interruptible": True,
        },
        "queue_tracks": [],
        "player_actions": [],
        "talk_density": "balanced",
    }
