from __future__ import annotations

from typing import Any, Literal, TypedDict


RuntimeEventName = Literal[
    # Playback lifecycle
    "music.playback.started",
    "music.playback.progress",
    "music.playback.near_end",
    "music.playback.ended",
    "music.playback.paused",
    "music.playback.resumed",
    # TTS pipeline
    "tts.segment.started",
    "tts.audio.ready",
    "tts.audio.failed",
    "tts.segment.completed",
    # Station state
    "station.state.updated",
    "queue.updated",
    "favorites.updated",
    # Agent turn lifecycle
    "agent.turn.started",
    "agent.turn.completed",
    "agent.turn.failed",
    # Agent tool calls
    "agent.tool.call",
    "agent.tool.result",
    # Provider calls
    "provider.request",
    "provider.error",
]


class RuntimeEvent(TypedDict):
    event: RuntimeEventName
    payload: dict[str, Any]
    trace_id: str
    span_id: str
    timestamp: str
