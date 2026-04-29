from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from agents import Agent, RunConfig, Runner
from agents.models.openai_provider import OpenAIProvider

from moodio.api.schemas import FinalAction


_LOCAL_ENV_KEYS = {
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
}
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_AGENT_TIMEOUT_SECONDS = 45.0


def build_station_agent() -> Agent:
    return Agent(
        name="moodio",
        instructions=(
            "Act as the on-air station host. "
            "When the app sends you a non-hard-edge turn, choose the correct mode "
            "and return a strict FinalAction."
        ),
        output_type=FinalAction,
    )


def parse_agent_result(payload: dict) -> FinalAction:
    return FinalAction.model_validate(payload)


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


async def run_station_turn(input_payload: dict) -> FinalAction:
    model_input = json.dumps(input_payload, sort_keys=True)
    timeout_seconds = float(os.environ.get("MOODIO_AGENT_TIMEOUT_SECONDS", _DEFAULT_AGENT_TIMEOUT_SECONDS))
    try:
        result = await asyncio.wait_for(
            Runner.run(build_station_agent(), input=model_input, run_config=build_model_config()),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"station agent turn timed out after {timeout_seconds:g}s") from exc
    return parse_agent_result(result.final_output)
