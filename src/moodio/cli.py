from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import httpx
import uvicorn

from moodio.music.providers import MusicProvider
from moodio.music.youtube import YouTubeProvider
from moodio.runtime.service import RuntimeService, build_runtime_from_env


def default_music_provider() -> MusicProvider:
    return YouTubeProvider()


def run(
    argv: list[str] | None = None,
    *,
    runtime_factory: Callable[[], RuntimeService] = build_runtime_from_env,
    provider_factory: Callable[[], MusicProvider] = default_music_provider,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.command_name == "serve":
        uvicorn.run(
            "moodio.api.server:create_app",
            factory=True,
            host=args.host,
            port=args.port,
        )
        return 0

    if args.command_name == "tail":
        return asyncio.run(_tail(args, stdout, stderr))

    try:
        return asyncio.run(_run_async(args, runtime_factory, provider_factory, stdout))
    except Exception as exc:
        print(f"moodio: {exc}", file=stderr)
        return 1


async def _run_async(
    args: argparse.Namespace,
    runtime_factory: Callable[[], RuntimeService],
    provider_factory: Callable[[], MusicProvider],
    stdout: TextIO,
) -> int:
    if args.command_name == "now":
        _print_json(await _server_request(args, "GET", "/api/now"), stdout)
    elif args.command_name == "transcript":
        _print_json(await _server_request(args, "GET", "/api/transcript/current"), stdout)
    elif args.command_name == "inspect":
        _print_json(await _server_request(args, "GET", "/api/debug/inspect"), stdout)
    elif args.command_name == "feed":
        _print_json(await _server_request(args, "GET", "/api/feed", params={"limit": args.limit}), stdout)
    elif args.command_name == "trace":
        _print_json(await _server_request(args, "GET", "/api/debug/trace", params={"limit": args.limit}), stdout)
    elif args.command_name == "session":
        _print_json(await _server_request(args, "GET", "/api/debug/session", params={"limit": args.limit}), stdout)
    elif args.command_name == "latency":
        _print_json(await _server_request(args, "GET", "/api/debug/latency", params={"limit": args.limit}), stdout)
    elif args.command_name == "command":
        _print_json(await _server_request(args, "POST", "/api/command", json={"text": args.text}, timeout=120), stdout)
    elif args.command_name == "transcribe":
        audio_path = args.audio_file
        _print_json(await _server_request(
            args,
            "POST",
            f"/api/transcribe?filename={audio_path.name}",
            content=audio_path.read_bytes(),
            headers={"content-type": _audio_content_type(audio_path)},
            timeout=120,
        ), stdout)
    elif args.command_name == "search":
        response = await _server_request(
            args,
            "POST",
            "/api/music/search",
            json={"query": args.query, "limit": args.limit, "preferences": {}},
            timeout=60,
        )
        _print_json(response, stdout)
    elif args.command_name == "next":
        _print_json(await _server_request(args, "POST", "/api/next"), stdout)
    elif args.command_name == "previous":
        _print_json(await _server_request(args, "POST", "/api/previous"), stdout)
    elif args.command_name == "favorite":
        _print_json(await _server_request(args, "POST", "/api/favorite", json={"track_id": args.track_id}), stdout)
    elif args.command_name == "queue":
        provider_name, provider_track_id = _parse_track_ref(args.track_ref)
        if provider_name != "youtube":
            raise ValueError(f"unsupported provider: {provider_name}")
        _print_json(await _server_request(
            args,
            "POST",
            "/api/music/queue-next",
            json={"candidate_id": provider_track_id, "reason": "CLI queue next"},
            timeout=60,
        ), stdout)
    elif args.command_name == "preferences_import":
        response = await _server_request(
            args,
            "POST",
            "/api/preferences/import",
            json={"source": args.source, "profile_text": args.profile_file.read_text(encoding="utf-8")},
        )
        _print_json(response, stdout)
    elif args.command_name == "preferences_apple_music_import":
        _print_json(await _server_request(
            args,
            "POST",
            "/api/preferences/apple-music-xml",
            content=args.xml_file.read_bytes(),
            headers={"content-type": "application/xml"},
            timeout=120,
        ), stdout)
    else:
        raise ValueError(f"unsupported command: {args.command_name}")

    return 0


async def _server_request(
    args: argparse.Namespace,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15,
) -> dict:
    """Send an operator command to the running Station, never a second local runtime."""
    url = f"http://{args.host}:{args.port}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, json=json, params=params, content=content, headers=headers)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip() or str(exc)
        raise ValueError(f"server request failed: {detail}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("server returned a non-object response")
    return payload


async def _tail(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    """Connect to a running moodio server and stream events to the terminal."""
    try:
        import websockets
    except ImportError:
        print("moodio tail requires the 'websockets' package", file=stderr)
        return 1

    url = f"ws://{args.host}:{args.port}/api/stream"
    filters = args.filter or []
    json_mode = args.json

    try:
        async with websockets.connect(url) as websocket:
            print(f"connected to {url}", file=stderr)
            async for raw_message in websocket:
                try:
                    event = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                event_name = event.get("event", "")

                if filters and not any(f in event_name for f in filters):
                    continue

                if json_mode:
                    stdout.write(json.dumps(event, sort_keys=True))
                    stdout.write("\n")
                    stdout.flush()
                    continue

                _print_event(event, stdout)
                stdout.flush()
    except KeyboardInterrupt:
        print("\ndisconnected", file=stderr)
    except Exception as exc:
        print(f"moodio tail: {exc}", file=stderr)
        return 1

    return 0


_EVENT_COLORS = {
    "agent.turn": "\033[35m",       # magenta
    "agent.tool": "\033[36m",       # cyan
    "tts.": "\033[33m",             # yellow
    "station.": "\033[32m",         # green
    "queue.": "\033[34m",           # blue
    "favorites.": "\033[34m",       # blue
    "music.": "\033[36m",           # cyan
    "provider.": "\033[31m",        # red
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _color_for_event(event_name: str) -> str:
    for prefix, color in _EVENT_COLORS.items():
        if event_name.startswith(prefix):
            return color
    return ""


def _print_event(event: dict, stdout: TextIO) -> None:
    event_name = event.get("event", "?")
    payload = event.get("payload", {})
    trace_id = event.get("trace_id", "")
    timestamp = event.get("timestamp", "")
    color = _color_for_event(event_name)

    ts_short = timestamp[11:19] if len(timestamp) >= 19 else timestamp
    trace_short = trace_id[:8] if trace_id else "--------"

    header = f"{_DIM}{ts_short}{_RESET} {color}{event_name:<30}{_RESET} {_DIM}{trace_short}{_RESET}"

    # Summarize common payloads instead of dumping full JSON
    summary = _summarize_payload(event_name, payload)

    if summary:
        stdout.write(f"{header}  {summary}\n")
    else:
        stdout.write(f"{header}\n")


def _summarize_payload(event_name: str, payload: dict) -> str:
    if event_name == "agent.turn.started":
        mode = payload.get("mode", "")
        input_text = payload.get("input", "")
        if len(input_text) > 60:
            input_text = input_text[:57] + "..."
        return f"mode={mode} input=\"{input_text}\""

    if event_name == "agent.turn.model_started":
        return (
            f"round={payload.get('round', '?')} "
            f"lane_wait={payload.get('agent_lane_wait_ms', '?')}ms"
        )

    if event_name == "agent.turn.first_token":
        return (
            f"round={payload.get('round', '?')} "
            f"ttft={payload.get('time_to_first_token_ms', '?')}ms"
        )

    if event_name == "agent.turn.round_first_token":
        return (
            f"round={payload.get('round', '?')} "
            f"round_ttft={payload.get('round_time_to_first_token_ms', '?')}ms"
        )

    if event_name == "agent.turn.completed":
        output = payload.get("output", "")
        if len(output) > 60:
            output = output[:57] + "..."
        timing = payload.get("timing", {})
        if isinstance(timing, dict) and timing.get("total_ms") is not None:
            return (
                f"total={timing.get('total_ms')}ms "
                f"ttft={timing.get('time_to_first_token_ms')}ms "
                f"output=\"{output}\""
            )
        return f"output=\"{output}\""

    if event_name == "agent.turn.failed":
        return f"error={payload.get('error_type', '?')}: {payload.get('error', '')}"

    if event_name == "tts.segment.started" or event_name == "tts.segment.completed":
        text = payload.get("text", "")
        if len(text) > 50:
            text = text[:47] + "..."
        return f"text=\"{text}\""

    if event_name == "tts.audio.ready":
        return f"url={payload.get('url', '?')}"

    if event_name == "tts.audio.failed":
        return f"message=\"{payload.get('message', '')}\""

    if event_name == "station.state.updated":
        mode = payload.get("mode", "?")
        status = payload.get("status", "?")
        talk = payload.get("talk_density", "?")
        return f"mode={mode} status={status} talk={talk}"

    if event_name == "queue.updated":
        count = len(payload.get("queue", []))
        return f"queue_size={count}"

    if event_name == "favorites.updated":
        return f"track_id={payload.get('track_id', '?')} favorited={payload.get('favorited', '?')}"

    if event_name.startswith("music.playback"):
        track = payload.get("track_id", "?")
        pos = payload.get("position_seconds", "?")
        dur = payload.get("duration_seconds", "?")
        return f"track={track} pos={pos}/{dur}"

    if event_name == "agent.tool.call":
        return f"tool={payload.get('tool', '?')}"

    if event_name == "agent.tool.result":
        return f"tool={payload.get('tool', '?')}"

    if event_name == "provider.request":
        provider = payload.get("provider", "?")
        action = payload.get("action", "?")
        query = payload.get("query")
        if query:
            if len(query) > 40:
                query = query[:37] + "..."
            return f"provider={provider} action={action} query=\"{query}\""
        return f"provider={provider} action={action}"

    if event_name == "provider.error":
        return f"provider={payload.get('provider', '?')} action={payload.get('action', '?')} error={payload.get('error_type', '?')}"

    return json.dumps(payload, sort_keys=True) if payload else ""


def _parse_track_ref(track_ref: str) -> tuple[str, str]:
    parts = track_ref.split(":")
    if len(parts) != 3 or parts[1] not in {"track", "video"} or not parts[0] or not parts[2]:
        raise ValueError("track ref must look like '<provider>:video:<id>'")
    return parts[0], parts[2]


def _print_json(payload: Any, stdout: TextIO) -> None:
    stdout.write(json.dumps(payload, indent=2, sort_keys=True))
    stdout.write("\n")


def _audio_content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if guessed == "audio/x-wav":
        return "audio/wav"
    return guessed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moodio")
    subcommands = parser.add_subparsers(dest="command_name", required=True)

    serve = subcommands.add_parser("serve", help="Run the moodio HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)

    tail = subcommands.add_parser("tail", help="Stream runtime events from a running server")
    _add_server_options(tail)
    tail.add_argument("--filter", action="append", help="Filter events by substring (e.g. 'tts', 'agent')")
    tail.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted events")

    now = subcommands.add_parser("now", help="Print current station state from the running server")
    _add_server_options(now)
    transcript = subcommands.add_parser("transcript", help="Print the current server transcript")
    _add_server_options(transcript)
    inspect = subcommands.add_parser("inspect", help="Inspect live Queue, profile, context, and tasks")
    _add_server_options(inspect)
    feed = subcommands.add_parser("feed", help="Read the persisted listener-facing station history")
    _add_server_options(feed)
    feed.add_argument("--limit", default=100, type=int)
    trace = subcommands.add_parser("trace", help="Read finalized persisted Agents SDK conversation items")
    _add_server_options(trace)
    trace.add_argument("--limit", default=100, type=int)
    session = subcommands.add_parser("session", help="Alias for trace")
    _add_server_options(session)
    session.add_argument("--limit", default=100, type=int)
    latency = subcommands.add_parser("latency", help="Read durable server-side timing for recent Listener turns")
    _add_server_options(latency)
    latency.add_argument("--limit", default=20, type=int)
    next_command = subcommands.add_parser("next", help="Advance to next queued track on the running server")
    _add_server_options(next_command)
    previous = subcommands.add_parser("previous", help="Return to previous track on the running server")
    _add_server_options(previous)

    command = subcommands.add_parser("command", help="Send a natural-language station command")
    _add_server_options(command)
    command.add_argument("text")

    transcribe = subcommands.add_parser("transcribe", help="Transcribe an audio command file")
    _add_server_options(transcribe)
    transcribe.add_argument("audio_file", type=Path)

    search = subcommands.add_parser("search", help="Search through the running station's music provider")
    _add_server_options(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    queue = subcommands.add_parser("queue", help="Queue a YouTube provider track ref on the running station")
    _add_server_options(queue)
    queue.add_argument("track_ref")

    favorite = subcommands.add_parser("favorite", help="Favorite a track id")
    _add_server_options(favorite)
    favorite.add_argument("track_id")

    preferences = subcommands.add_parser("preferences", help="Manage listener taste inputs")
    _add_server_options(preferences)
    preference_subcommands = preferences.add_subparsers(dest="preferences_command", required=True)

    preference_import = preference_subcommands.add_parser("import", help="Import listener preferences from a text file")
    preference_import.add_argument("profile_file", type=Path)
    preference_import.add_argument("--source", default="apple_music")
    preference_import.set_defaults(command_name="preferences_import")

    apple_music_import = preference_subcommands.add_parser(
        "import-apple-music",
        help="Import a Music.app XML playlist or library export without retaining the XML",
    )
    apple_music_import.add_argument("xml_file", type=Path)
    apple_music_import.set_defaults(command_name="preferences_apple_music_import")

    return parser


def _add_server_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Moodio server host")
    parser.add_argument("--port", default=8765, type=int, help="Moodio server port")


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
