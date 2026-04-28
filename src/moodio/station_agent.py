from __future__ import annotations

from agents import Agent, Runner

from moodio.api.schemas import FinalAction


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


async def run_station_turn(input_payload: dict) -> FinalAction:
    result = await Runner.run(build_station_agent(), input=input_payload)
    return FinalAction.model_validate(result.final_output)
