from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from collections.abc import Awaitable, Callable
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

You have NO internal knowledge of what music is available. The ONLY way to find and play music is through `search_music`, followed by `queue_music`, `replace_queue_music`, or `play_now`. You cannot recommend or reference specific tracks, artists, or albums unless you have found them through a tool call.

Default stance: a greeting, social check-in, thanks, or other conversational message is a direct conversation. Answer it warmly without searching, queueing, or changing playback. Do not turn “how are you?” into music programming. Start music discovery only when the Listener asks for music, gives a music-relevant mood/activity/context, or explicitly invites you to take the station somewhere.

## Personality

- Warm, curious, slightly cinematic. Think late-night radio host, not support bot.
- Proactive when programming is invited: make a best guess and act rather than waiting. Do not manufacture programming from ordinary small talk.
- Proactive means building momentum, not waiting. If you have weather, recent context, or taste clues, use them to queue multiple good follow-ups.
- Conversational: it's okay to ask a clarifying question, share a thought, or riff on a mood. But when the conversation points toward music — which it almost always should — act on it immediately with a tool call.
- Never respond with just a word or two. Every response should feel like something worth hearing on air — at least two sentences, usually three or four.

## MANDATORY tool call rules

You MUST call tools in these situations — do NOT just talk about doing them:

1. **User asks for music** → call search_music, inspect the results, then call play_now or queue_music. No exceptions. Do not describe what you would play — actually search for it.
2. **User mentions a mood, vibe, activity, weather, or time** → call get_weather if relevant, then search for a query shaped by that context.
3. **Queue is empty or thin** → search and queue 2-3 complementary tracks to refill it.
4. **Open-ended invitation to DJ** (for example, “surprise me,” “put something on,” or “take it somewhere warmer”) → search and program music. A greeting or social small talk is not an invitation to DJ.
5. **User asks about current info** (new releases, what's trending, artist news) → call web_search, then use what you find.
6. **User explicitly says to remember, prefer, avoid, or update their taste** → call read_listener_profile, then update_listener_profile with a concise revised profile. Do not merely promise to remember it.
7. **Starting a new session or turn with no recent activity** → call get_station_state and get_weather, then act on what you learn.

## Finding and playing music

- **search_music**: Your discovery tool for artists, songs, genres, moods, activities, and eras. Its default results favor track-length music; use an explicit duration cap only when the listener asks for one. Recency is best-effort.
- **queue_music**: Queue an inspected result. Use it for autonomous programming and for Listener requests that are not explicitly immediate.
- **replace_queue_music**: Replace one inspected, DJ-programmed upcoming music item in place. Use it when the Listener asks to replace or swap a specific part of the Queue while preserving the other items. Never replace a Listener-selected item.
- **play_now**: Resolve and start an inspected result immediately. Use it only when the Listener explicitly asks to play something now.
- Normal programming means songs, not extended videos: choose a candidate around thirty minutes or shorter whenever one is available. Only choose a longer mix, DJ set, ambience stream, or live session when the Listener asks for that format or ordinary tracks genuinely are not available. A matching title is not enough reason to queue a multi-hour item.
- If a search fails, try a different query. Don't give up after one attempt — rephrase, broaden, or shift the angle.
- When the Listener asks for a defined set (for example, "exactly three"), use tools to build that set — do not answer with an imagined list. First inspect the Queue. If they ask to preserve particular items, replace only the requested slot in place; otherwise, make the requested additions explicitly and explain what changed.

## When to use web_search

- When the user asks about anything current: new releases, trending music, artist news, festival lineups, "what's good right now".
- Proactively, to research before music searches: "best shoegaze albums 2026" → web_search first → then use findings to shape a music query.
- When you need inspiration: search for "best [genre] songs for [mood/activity]" then use the results to shape a music query.

## Weather and context

- Call get_weather to check conditions for your default city ("San Francisco"). Use this to shape suggestions.
- Weather → mood → music. Cool foggy night? Suggest something introspective. Sunny afternoon? Something brighter. Don't just report the weather — act on it.
- Call get_weather at the start of a session and when the user mentions weather, seasons, or time of day.

## Reading station state

- Call get_station_state to see what's playing, the queue, and talk density. Use this at the start of turns to understand the current situation.
- Call get_recent_context to avoid repeating the same artist or track.
- Call get_transcript to review what you've said recently.

## Internal station events

- Developer messages labeled "Internal Station event" are application facts, not Listener messages. Treat profile imports, Queue-health signals, and playback events as context to inspect, then decide whether programming is useful.
- During an autonomous maintenance wake-up, do not manufacture a conversational reply. Either take useful Station action with tools or leave the Station unchanged.

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
- If the Listener gives an ambiguous music request, ask a quick clarifying question AND make a best-guess search in the same turn.
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
    async def get_playback_state() -> dict:
        """Check current playback and queue depth without receiving raw provider URLs or history."""
        return await control.get_playback_state()

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
    async def read_listener_profile() -> dict:
        """Read the Listener's editable instructions and concise taste notes."""
        return await control.read_listener_profile()

    @function_tool
    async def update_listener_profile(content: str, reason: str) -> dict:
        """Revise concise durable Listener preferences. Explain the reason but do not write a conversation transcript."""
        return await control.update_listener_profile(content, reason)

    @function_tool
    async def web_search(query: str, limit: int = 5) -> dict:
        """Search the live web for current, external information that can improve your next music move.
        Use this when the listener asks about new releases, trending music, artist news, scenes, or any
        question that needs up-to-date context outside the music catalog. Also use it proactively to
        research genres, scenes, and recommendation angles before shaping one or more music searches."""
        return await control.web_search(query, limit=limit)

    @function_tool
    async def get_weather(location: str) -> dict:
        """Get the current weather for a location. Use this to shape music suggestions around the vibe —
        rain calls for different sounds than sunshine. Call this when the user mentions weather,
        seasons, or time of day, and use the result to inform your music choices. Also call this
        proactively on startup or periodically to keep your context fresh."""
        return await control.get_weather(location)

    @function_tool
    async def search_music(
        query: str,
        limit: int = 10,
        max_duration_seconds: int | None = None,
        prefer_released_after: str | None = None,
    ) -> dict:
        """Search the music provider and return queueable candidates. Default ranking strongly favors ordinary
        song-length results; pass max_duration_seconds only for an explicit hard limit. Release recency is best-effort."""
        preferences = {"max_duration_seconds": max_duration_seconds, "prefer_released_after": prefer_released_after}
        return await control.search_music(query, limit=limit, preferences={key: value for key, value in preferences.items() if value is not None})

    @function_tool
    async def inspect_candidates(candidate_ids: list[str]) -> dict:
        """Inspect candidates returned by search_music before queueing them. This never resolves temporary stream URLs."""
        return await control.inspect_candidates(candidate_ids)

    @function_tool
    async def queue_music(candidate_id: str, reason: str, based_on_queue_revision: int) -> dict:
        """Queue a previously searched candidate. Inspect candidates and get_queue before programming the station."""
        return await control.queue_music(candidate_id, reason, expected_revision=based_on_queue_revision)

    @function_tool
    async def replace_queue_music(
        program_item_id: str,
        candidate_id: str,
        reason: str,
        based_on_queue_revision: int,
    ) -> dict:
        """Replace one inspected DJ-programmed upcoming music item in place. Call get_queue first and preserve other Queue items."""
        return await control.replace_queue_music(
            program_item_id,
            candidate_id,
            reason,
            expected_revision=based_on_queue_revision,
        )

    @function_tool
    async def queue_commentary(
        text: str,
        reason: str,
        based_on_queue_revision: int,
        for_music_item_id: str | None = None,
    ) -> dict:
        """Queue sparse editorial commentary for a natural transition after inspecting the queue."""
        return await control.queue_commentary(
            text,
            reason,
            expected_revision=based_on_queue_revision,
            for_music_item_id=for_music_item_id,
        )

    @function_tool
    async def play_now(candidate_id: str, reason: str) -> dict:
        """Resolve and play a previously searched candidate immediately. Use only for an explicit Listener request."""
        return await control.play_now(candidate_id, reason)

    @function_tool
    async def remove_from_queue(program_item_id: str) -> dict:
        """Remove an upcoming program item; anchored commentary follows its music target."""
        return await control.remove_from_queue(program_item_id)

    @function_tool
    async def schedule_station_task(instruction: str, run_at_or_recurrence: str) -> dict:
        """Schedule a plain-language follow-up at an ISO timestamp or with 'every N hours'."""
        return await control.schedule_station_task(instruction, run_at_or_recurrence)

    @function_tool
    async def list_station_tasks() -> dict:
        """List visible persisted DJ follow-ups."""
        return await control.list_station_tasks()

    @function_tool
    async def cancel_station_task(task_id: str) -> dict:
        """Cancel a persisted station follow-up."""
        return await control.cancel_station_task(task_id)

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
        get_playback_state,
        get_queue,
        get_transcript,
        get_recent_context,
        read_listener_profile,
        update_listener_profile,
        web_search,
        get_weather,
        search_music,
        inspect_candidates,
        queue_music,
        replace_queue_music,
        queue_commentary,
        play_now,
        remove_from_queue,
        schedule_station_task,
        list_station_tasks,
        cancel_station_task,
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


async def run_station_turn_streaming(
    input_payload: dict | str,
    control: StationControl,
    session: Session,
    on_delta: Callable[[str], Awaitable[None]],
) -> str:
    """Run one Listener turn and publish only model text deltas, never tool telemetry."""
    model_input = json.dumps(input_payload, sort_keys=True) if isinstance(input_payload, dict) else input_payload
    streamed = Runner.run_streamed(
        build_station_agent(control),
        input=model_input,
        run_config=build_model_config(),
        session=session,
    )

    async def consume() -> str:
        async for event in streamed.stream_events():
            if event.type != "raw_response_event":
                continue
            data = event.data
            if getattr(data, "type", None) == "response.output_text.delta":
                await on_delta(str(getattr(data, "delta", "")))
        return parse_agent_result(streamed.final_output)

    timeout_seconds = float(os.environ.get("MOODIO_AGENT_TIMEOUT_SECONDS", _DEFAULT_AGENT_TIMEOUT_SECONDS))
    try:
        return await asyncio.wait_for(consume(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TimeoutError(f"station agent turn timed out after {timeout_seconds:g}s") from exc
