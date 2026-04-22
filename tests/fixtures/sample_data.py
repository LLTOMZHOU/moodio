from __future__ import annotations


def sample_track() -> dict:
    return {
        "track_id": "apple:track:if-bread",
        "title": "If",
        "artist": "Bread",
        "album": "Manna",
        "duration_seconds": 197,
        "playback_ref": "apple_music:catalog:12345",
        "artwork_url": "https://example.test/artwork/if.jpg",
    }


def sample_next_track() -> dict:
    return {
        "track_id": "apple:track:rainy-focus-02",
        "title": "Rainy Focus",
        "artist": "Example Artist",
        "album": "Desk Hours",
        "duration_seconds": 212,
        "playback_ref": "apple_music:catalog:67890",
        "artwork_url": "https://example.test/artwork/rainy-focus.jpg",
    }


def sample_transcript_segment() -> dict:
    return {
        "segment_id": "seg_001",
        "text": "This is moodio. If you're enjoying this, I can favorite it for you.",
        "start_ms": 0,
        "duration_ms": 7400,
        "voice": "default_male_1",
        "state": "speaking",
    }


def sample_station_state() -> dict:
    return {
        "host_name": "moodio",
        "mode": "radio_continue",
        "status": "playing",
        "talk_density": "balanced",
        "now_playing": sample_track(),
        "queue": [sample_next_track()],
        "favorites_enabled": True,
    }


def sample_playback_event() -> dict:
    return {
        "event_type": "music.playback.near_end",
        "track_id": "apple:track:if-bread",
        "position_seconds": 182,
        "duration_seconds": 197,
    }


def sample_radio_continue_action() -> dict:
    return {
        "mode": "radio_continue",
        "say": {
            "text": "A late-night exhale. Staying warm and gentle here.",
            "voice": "default_male_1",
            "interruptible": True,
        },
        "queue_tracks": [
            {
                "track_id": "apple:track:rainy-focus-02",
                "reason": "Keeps the station one track ahead with a calm tone.",
                "start_policy": "after_tts",
            }
        ],
        "player_actions": [],
        "talk_density": "balanced",
    }


def sample_favorite_action() -> dict:
    return {
        "mode": "user_request",
        "say": None,
        "queue_tracks": [],
        "player_actions": [
            {
                "type": "favorite",
                "track_id": "apple:track:if-bread",
            }
        ],
        "talk_density": None,
    }
