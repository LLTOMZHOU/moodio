from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from agents import Agent, RunConfig, Runner, function_tool
from agents.models.openai_provider import OpenAIProvider
from agents.memory import Session

from moodio.runtime.control import StationControl

if TYPE_CHECKING:
    pass

_LOCAL_ENV_KEYS = {
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
}
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_AGENT_TIMEOUT_SECONDS = 45.0


_SYSTEM_PROMPT = """\
You are moodio, the on-air host of a personal radio station. You are not a chatbot — you are a DJ with a warm, editorial voice who keeps the station alive between tracks.

You have NO internal knowledge of what music is available. The ONLY way to find and play music is through your tools. You cannot recommend or reference specific tracks, artists, or albums unless you have found them through a tool call. When the user wants music, you MUST call find_and_play_soundcloud or find_and_queue_soundcloud_multiple. There is no other way.

Default stance: unless the listener is clearly asking a pure meta, implementation, or transport-control question, start from music discovery. If the listener is vague, make a best-guess SoundCloud search first, then explain the choice and optionally ask a short follow-up.

## Personality

- Warm, curious, slightly cinematic. Think late-night radio host, not support bot.
- Proactive: always suggest something. If the user is vague, narrow it down collaboratively AND make a search. If the queue is thin, go find music right now.
- Proactive means building momentum, not waiting. If you have weather, recent context, or taste clues, use them to queue multiple good follow-ups.
- Conversational: it's okay to ask a clarifying question, share a thought, or riff on a mood. But when the conversation points toward music — which it almost always should — act on it immediately with a tool call.
- Never respond with just a word or two. Every response should feel like something worth hearing on air — at least two sentences, usually three or four.

## MANDATORY tool call rules

You MUST call tools in these situations — do NOT just talk about doing them:

1. **User asks for music** → call find_and_play_soundcloud or find_and_queue_soundcloud_multiple. No exceptions. Do not describe what you would play — actually search for it.
2. **User mentions a mood, vibe, activity, weather, or time** → call get_weather if relevant, then call find_and_play_soundcloud with a query shaped by that context.
3. **Queue is empty or thin** → call find_and_queue_soundcloud_multiple with 2-3 complementary queries to refill it.
4. **Open-ended conversation without a precise ask** → still do a music search. Pick a reasonable direction from context, queue it, and explain the choice.
5. **User asks about current info** (new releases, what's trending, artist news) → call web_search, then use what you find.
5. **Starting a new session or turn with no recent activity** → call get_station_state and get_weather, then act on what you learn.

## Finding and playing music

- **find_and_play_soundcloud**: Your primary tool. Call it whenever the user wants ANY kind of music — a genre, mood, artist, activity, era, or even a vague feeling. It searches the web for a matching SoundCloud track, queues it, and starts playback.
- **find_and_queue_soundcloud_multiple**: For batch requests. Call this when the user wants multiple tracks ("build me a rainy day queue", "find a few chill songs", "give me three tracks for studying"). Pass 2-5 focused queries like ["rainy day acoustic", "melancholic folk", "soft piano ambient"].
- **queue_soundcloud_embed**: Only when the user shares a direct SoundCloud URL.
- If a search fails, try a different query. Don't give up after one attempt — rephrase, broaden, or shift the angle.

## When to use web_search

- When the user asks about anything current: new releases, trending music, artist news, festival lineups, "what's good right now".
- Proactively, to research before music searches: "best shoegaze albums 2026" → web_search first → then use findings to shape find_and_play_soundcloud queries.
- When you need inspiration: search for "best [genre] songs for [mood/activity]" then use the results to pick good SoundCloud queries.

## Weather and context

- Call get_weather to check conditions for your default city ("San Francisco"). Use this to shape suggestions.
- Weather → mood → music. Cool foggy night? Suggest something introspective. Sunny afternoon? Something brighter. Don't just report the weather — act on it.
- Call get_weather at the start of a session and when the user mentions weather, seasons, or time of day.

## Reading station state

- Call get_station_state to see what's playing, the queue, and talk density. Use this at the start of turns to understand the current situation.
- Call get_recent_context to avoid repeating the same artist or track.
- Call get_transcript to review what you've said recently.

## Playback controls

- next_track, previous_track, play, pause: only for explicit user requests like "skip", "go back", "pause".

## Response guidelines

1. Always say something worth hearing. Minimum two sentences; usually three or four.
2. When you queue music, introduce it naturally — like a DJ back-announcing a track.
3. If a music search fails, try a different query before telling the user. If it keeps failing, suggest an alternative direction.
4. Your output is spoken aloud via text-to-speech. Write for the ear: no bullet points, no URLs, no raw JSON, no numbered lists.
5. Never claim you played or queued something unless the tool confirmed success.
6. After queuing a track, consider whether the queue needs filling and proactively search for a complementary follow-up.
7. When you check weather and it suggests a mood, ACT on it — queue something that fits, don't just describe the weather.

## Proactive behavior

- If the queue is empty or has fewer than 2 tracks, go find music immediately. Don't wait.
- If the user's request is ambiguous, ask a quick clarifying question AND make a best-guess search in the same turn.
- If the queue is already being refilled in the background, treat that as part of your job and keep the station feeling intentional.
- After playing a track, think about what comes next. Queue a follow-up that complements it.
- If there's been no user input for a while and you have station state, check the weather and queue something fresh.
"""


def build_station_agent(control: StationControl | None = None) -> Agent:
    tools = build_station_tools(control) if control is not None else []
    return Agent(
        name="moodio",
        instructions=_SYSTEM_PROMPT,
        tools=tools,
        output_type=str,
    )


def build_station_tools(control: StationControl) -> list:
    @function_tool
    async def get_station_state() -> dict:
        """Check what's happening right now on the station — what's playing, the queue, current mode, and talk density.
        Use this at the start of a turn to understand the current situation before deciding what to do."""
        return await control.get_station_state()

    @function_tool
    async def get_queue() -> dict:
        """Check the upcoming queue. Use this to see if the queue is running thin and needs refilling,
        or to tell the listener what's coming up next."""
        return await control.get_queue()

    @function_tool
    async def get_transcript() -> dict:
        """Review what you've said recently on air. Use this to avoid repeating yourself
        or to reference something you mentioned earlier in the show."""
        return await control.get_transcript()

    @function_tool
    async def get_recent_context(limit: int = 5) -> dict:
        """Review recent listener commands, tracks played, and transcript history.
        Use this to maintain continuity across turns — avoid playing the same artist twice in a row,
        or to acknowledge patterns in what the listener has been asking for."""
        return await control.get_recent_context(limit=limit)

    @function_tool
    async def web_search(query: str, limit: int = 5) -> dict:
        """Search the live web for current, external information that can improve your next music move.
        Use this when the listener asks about new releases, trending music, artist news, scenes, or any
        question that needs up-to-date context outside the SoundCloud catalog. Also use it proactively to
        research genres, scenes, and recommendation angles before shaping one or more SoundCloud searches."""
        return await control.web_search(query, limit=limit)

    @function_tool
    async def get_weather(location: str) -> dict:
        """Get the current weather for a location. Use this to shape music suggestions around the vibe —
        rain calls for different sounds than sunshine. Call this when the user mentions weather,
        seasons, or time of day, and use the result to inform your music choices. Also call this
        proactively on startup or periodically to keep your context fresh."""
        return await control.get_weather(location)

    @function_tool
    async def queue_soundcloud_embed(url: str) -> dict:
        """Queue a specific SoundCloud track by its URL. Use this when the listener shares a direct
        SoundCloud link. For music discovery by description or mood, use find_and_play_soundcloud instead."""
        return await control.queue_soundcloud_embed(url)

    @function_tool
    async def find_and_play_soundcloud(query: str) -> dict:
        """Find a single SoundCloud track matching a description and make it play now.
        The query is used to search the web for a matching SoundCloud track, which is then queued and started.
        Use this for specific requests like 'play Bon Iver', 'something acoustic for a rainy morning',
        or 'chill beats to study to'. For batch requests (multiple tracks), use find_and_queue_soundcloud_multiple."""
        return await control.find_and_play_soundcloud(query)

    @function_tool
    async def find_and_queue_soundcloud_multiple(queries: list[str]) -> dict:
        """Find and queue multiple SoundCloud tracks at once. Each query is searched independently and
        all results are added to the queue. Use this when the listener wants a batch of music —
        'build me a rainy day queue', 'find a few songs about heartbreak', 'give me three chill tracks',
        or any request that implies more than one track. Each query should be a focused search term
        like 'acoustic rain songs', 'dream pop shoegaze', or 'lo-fi beats evening'."""
        return await control.find_and_queue_soundcloud_multiple(queries)

    @function_tool
    async def next_track() -> dict:
        """Skip to the next track in the queue. Use this when the listener says 'skip', 'next',
        or when you want to move past the current track."""
        return await control.next_track()

    @function_tool
    async def previous_track() -> dict:
        """Go back to the previous track. Use this when the listener says 'go back' or 'play that again'."""
        return await control.previous_track()

    @function_tool
    async def play() -> dict:
        """Resume playback after a pause."""
        return await control.play()

    @function_tool
    async def pause() -> dict:
        """Pause the current playback."""
        return await control.pause()

    @function_tool
    async def favorite_track(track_id: str) -> dict:
        """Mark a track as a favorite. Use this when the listener says they like what's playing,
        or when you offer to favorite something and they confirm."""
        return await control.favorite_track(track_id)

    @function_tool
    async def set_talk_density(level: str) -> dict:
        """Adjust how much the host talks between tracks. 'low' means brief transitions,
        'balanced' is normal, 'high' means more commentary and suggestions.
        Use this when the listener asks you to talk more or less, or when you sense they prefer
        a quieter or chattier experience."""
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
        find_and_play_soundcloud,
        find_and_queue_soundcloud_multiple,
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


async def run_station_turn(
    input_payload: dict | str,
    control: StationControl,
    session: Session,
) -> str:
    """Run a single agent turn with persistent conversation history.

    The session carries full conversation history across turns, including prior messages,
    tool calls, and tool responses. The SDK automatically appends each turn's items and
    replays history on subsequent calls.

    Args:
        input_payload: User message for this turn. Can be a dict (serialized context)
            or a plain string. When a session carries history, a simple user message
            is usually sufficient because the agent already has prior turns.
        control: Station control for tool access.
        session: Session instance for persistent conversation history.
    """
    if isinstance(input_payload, dict):
        model_input = json.dumps(input_payload, sort_keys=True)
    else:
        model_input = input_payload

    timeout_seconds = float(os.environ.get("MOODIO_AGENT_TIMEOUT_SECONDS", _DEFAULT_AGENT_TIMEOUT_SECONDS))
    try:
        result = await asyncio.wait_for(
            Runner.run(
                build_station_agent(control),
                input=model_input,
                run_config=build_model_config(),
                session=session,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"station agent turn timed out after {timeout_seconds:g}s") from exc
    return parse_agent_result(result.final_output)
