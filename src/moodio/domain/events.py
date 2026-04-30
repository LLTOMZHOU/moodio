from __future__ import annotations

from typing import Any, Literal, TypedDict


RuntimeEventName = Literal[
    "music.playback.started",
    "music.playback.progress",
    "music.playback.near_end",
    "music.playback.ended",
    "music.playback.paused",
    "music.playback.resumed",
    "tts.segment.started",
    "tts.audio.ready",
    "tts.segment.completed",
    "station.state.updated",
    "queue.updated",
    "favorites.updated",
]


class RuntimeEvent(TypedDict):
    event: RuntimeEventName
    payload: dict[str, Any]
