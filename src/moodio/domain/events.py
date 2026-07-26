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
    "profile.updated",
    "profile.imported",
    # Agent turn lifecycle
    "agent.turn.started",
    "agent.turn.model_started",
    "agent.turn.first_token",
    "agent.turn.round_first_token",
    "agent.turn.completed",
    "agent.turn.failed",
    # Durable conversation lifecycle
    "conversation.message.saved",
    "conversation.cleared",
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
