from __future__ import annotations

import asyncio
import json
import os

from agents import Agent, Runner
from pydantic import BaseModel, Field

from moodio.station_agent import build_model_config


_DEFAULT_SYNTHESIS_TIMEOUT_SECONDS = 45.0


class AppleMusicProfileSynthesis(BaseModel):
    """The only durable result of one Apple Music import-mining run."""

    profile_markdown: str = Field(min_length=1, max_length=12_000)
    seed_queries: list[str] = Field(min_length=4, max_length=12)
    reason: str = Field(min_length=1, max_length=500)


_SYNTHESIS_PROMPT = """\
You mine a Listener-selected Apple Music export into a useful, editable initial
profile for a personal AI DJ. You receive only a bounded, descriptive evidence
packet—not the XML file itself. Return the requested structured result.

The profile is a provisional working note, not an identity judgement. Give
stronger weight to explicit favorites, ratings, and repeated listening than to
whole-library totals. A library can contain collecting, soundtracks, and
one-off exploration. Do not infer demographics, personality, health, identity,
or life circumstances.

Write `profile_markdown` with each of these headings exactly once, in this order:

# Listener profile
## Explicit instructions
## Taste notes
## Favorite artists and albums
## Imported music evidence
## Discovery starting points

Use concise bullets under each heading. Preserve any supplied explicit
instructions verbatim. Mine concrete, useful patterns: genres or styles,
favorite artists, favorite albums, representative repeated tracks, and any
meaningful contrast between primary taste and library-only context. State
uncertainty where appropriate.

Under `## Favorite artists and albums`, name 8–15 specific artists from the
explicit-favorites and repeated-listening evidence, with a supporting album or
track where useful. Do not collapse strong artists into a generic genre label:
if an artist has four or more explicit favorites, or several high-repeat tracks,
give them their own bullet. Treat albums as anchors when several favored or
repeated tracks come from the same release; do not fabricate album preference
when an artist's favorites are spread across singles and releases. Include a
favorite or repeat count when it materially explains why an artist is an anchor.

Choose 4–12 `seed_queries`. Every seed must name at least one imported artist,
album, or track. Prefer a diverse mix of exact high-signal tracks and
artist/album searches; never use a bare genre, mood, language, or era. These
seeds are discovery starting points only, never a Queue.

Set `reason` to one concise sentence explaining the evidence used to make this
provisional profile revision.
"""


async def synthesize_apple_music_profile(
    evidence: dict[str, object],
    *,
    existing_profile: str,
) -> AppleMusicProfileSynthesis:
    """Run one non-session model call over bounded import evidence.

    This is intentionally separate from the continuous Station session: source
    evidence should shape the materialized profile, not become recurring DJ
    conversation context.
    """
    model_config = build_model_config()
    if model_config is None:
        raise ValueError("Apple Music import synthesis requires OPENROUTER_API_KEY and OPENROUTER_MODEL.")

    input_payload = json.dumps(
        {
            "existing_profile": existing_profile,
            "apple_music_evidence": evidence,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    timeout_seconds = float(os.environ.get("MOODIO_IMPORT_SYNTHESIS_TIMEOUT_SECONDS", _DEFAULT_SYNTHESIS_TIMEOUT_SECONDS))
    try:
        result = await asyncio.wait_for(
            Runner.run(
                Agent(
                    name="apple_music_profile_miner",
                    instructions=_SYNTHESIS_PROMPT,
                    output_type=AppleMusicProfileSynthesis,
                ),
                input=input_payload,
                run_config=model_config,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"Apple Music profile synthesis timed out after {timeout_seconds:g}s") from exc

    output = result.final_output
    if not isinstance(output, AppleMusicProfileSynthesis):
        return AppleMusicProfileSynthesis.model_validate(output)
    return output
