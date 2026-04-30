from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from agents import Agent, RunConfig, Runner, function_tool
from agents.models.openai_provider import OpenAIProvider

from moodio.runtime.control import StationControl


_LOCAL_ENV_KEYS = {
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
}
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_AGENT_TIMEOUT_SECONDS = 45.0


def build_station_agent(control: StationControl | None = None) -> Agent:
    tools = build_station_tools(control) if control is not None else []
    return Agent(
        name="moodio",
        instructions=(
            "Act as the on-air station host. "
            "Use tools to inspect and control app state. "
            "Return only the short spoken DJ line for text-to-speech."
        ),
        tools=tools,
        output_type=str,
    )


def build_station_tools(control: StationControl) -> list:
    @function_tool
    async def get_station_state() -> dict:
        """Return the current station state."""
        return await control.get_station_state()

    @function_tool
    async def get_queue() -> dict:
        """Return the current station queue."""
        return await control.get_queue()

    @function_tool
    async def get_transcript() -> dict:
        """Return the current spoken transcript segments."""
        return await control.get_transcript()

    @function_tool
    async def get_recent_context(limit: int = 5) -> dict:
        """Return recent commands, plays, and transcript memory."""
        return await control.get_recent_context(limit=limit)

    @function_tool
    async def web_search(query: str, limit: int = 5) -> dict:
        """Search the web for current information."""
        return await control.web_search(query, limit=limit)

    @function_tool
    async def get_weather(location: str) -> dict:
        """Return current weather for a location."""
        return await control.get_weather(location)

    @function_tool
    async def queue_soundcloud_embed(url: str) -> dict:
        """Resolve a SoundCloud URL through oEmbed and queue it next."""
        return await control.queue_soundcloud_embed(url)

    @function_tool
    async def next_track() -> dict:
        """Advance to the next queued track."""
        return await control.next_track()

    @function_tool
    async def previous_track() -> dict:
        """Return to the previous track if available."""
        return await control.previous_track()

    @function_tool
    async def play() -> dict:
        """Resume playback."""
        return await control.play()

    @function_tool
    async def pause() -> dict:
        """Pause playback."""
        return await control.pause()

    @function_tool
    async def favorite_track(track_id: str) -> dict:
        """Favorite a track by track id."""
        return await control.favorite_track(track_id)

    @function_tool
    async def set_talk_density(level: str) -> dict:
        """Set talk density to low, balanced, or high."""
        if level not in {"low", "balanced", "high"}:
            raise ValueError("level must be one of: low, balanced, high")
        return await control.set_talk_density(level)

    return [
        get_station_state,
        get_queue,
        get_transcript,
        get_recent_context,
        web_search,
        get_weather,
        queue_soundcloud_embed,
        next_track,
        previous_track,
        play,
        pause,
        favorite_track,
        set_talk_density,
    ]


def parse_agent_result(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    return str(payload)


def load_local_env(env_path: Path | str = ".env") -> dict[str, str]:
    path = Path(env_path)
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in _LOCAL_ENV_KEYS and value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value

    return loaded


def build_model_config() -> RunConfig | None:
    load_local_env()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL")
    if not api_key:
        return None
    if not model:
        raise ValueError("OPENROUTER_MODEL is required when OPENROUTER_API_KEY is set")

    return RunConfig(
        model=model,
        model_provider=OpenAIProvider(
            api_key=api_key,
            base_url=os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_OPENROUTER_BASE_URL),
            use_responses=False,
        ),
        tracing_disabled=True,
    )


async def run_station_turn(input_payload: dict, control: StationControl | None = None) -> str:
    model_input = json.dumps(input_payload, sort_keys=True)
    timeout_seconds = float(os.environ.get("MOODIO_AGENT_TIMEOUT_SECONDS", _DEFAULT_AGENT_TIMEOUT_SECONDS))
    try:
        result = await asyncio.wait_for(
            Runner.run(build_station_agent(control), input=model_input, run_config=build_model_config()),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"station agent turn timed out after {timeout_seconds:g}s") from exc
    return parse_agent_result(result.final_output)
