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

import uvicorn

from moodio.api.schemas import CommandRequest, FavoriteRequest
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
    if args.command_name == "search":
        provider = provider_factory()
        tracks = await provider.search_tracks(args.query, limit=args.limit)
        _print_json([track.model_dump() for track in tracks], stdout)
        return 0

    runtime = runtime_factory()

    if args.command_name == "now":
        _print_json(runtime.snapshot().model_dump(), stdout)
    elif args.command_name == "transcript":
        _print_json(runtime.transcript_snapshot(), stdout)
    elif args.command_name == "command":
        response = await runtime.accept_command(CommandRequest(text=args.text))
        _print_json(response.model_dump(), stdout)
    elif args.command_name == "transcribe":
        audio_path = args.audio_file
        _print_json(
            runtime.transcribe_audio(
                audio_path.read_bytes(),
                filename=audio_path.name,
                content_type=_audio_content_type(audio_path),
            ),
            stdout,
        )
    elif args.command_name == "next":
        _print_json(await runtime.next_track(), stdout)
    elif args.command_name == "previous":
        _print_json(await runtime.previous_track(), stdout)
    elif args.command_name == "favorite":
        response = await runtime.favorite_track(FavoriteRequest(track_id=args.track_id))
        _print_json(response.model_dump(), stdout)
    elif args.command_name == "queue":
        provider_name, provider_track_id = _parse_track_ref(args.track_ref)
        if provider_name != "youtube":
            raise ValueError(f"unsupported provider: {provider_name}")
        provider = provider_factory()
        provider_track = await provider.resolve_track(provider_track_id)
        _print_json(await runtime.queue_track(provider_track.to_queue_item()), stdout)
    elif args.command_name == "preferences_import":
        preferences = runtime.import_listener_preferences(
            args.profile_file.read_text(encoding="utf-8"),
            source=args.source,
        )
        _print_json(
            {
                "source": preferences.source,
                "raw_text": preferences.raw_text,
                "seed_queries": preferences.seed_queries,
            },
            stdout,
        )
    elif args.command_name == "preferences_apple_music_import":
        _print_json(await runtime.import_apple_music_export(args.xml_file.read_bytes()), stdout)
    else:
        raise ValueError(f"unsupported command: {args.command_name}")

    return 0


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

    if event_name == "agent.turn.completed":
        output = payload.get("output", "")
        if len(output) > 60:
            output = output[:57] + "..."
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
    tail.add_argument("--host", default="127.0.0.1")
    tail.add_argument("--port", default=8765, type=int)
    tail.add_argument("--filter", action="append", help="Filter events by substring (e.g. 'tts', 'agent')")
    tail.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted events")

    subcommands.add_parser("now", help="Print current station state")
    subcommands.add_parser("transcript", help="Print current transcript")
    subcommands.add_parser("next", help="Advance to next queued track")
    subcommands.add_parser("previous", help="Return to previous track")

    command = subcommands.add_parser("command", help="Send a natural-language station command")
    command.add_argument("text")

    transcribe = subcommands.add_parser("transcribe", help="Transcribe an audio command file")
    transcribe.add_argument("audio_file", type=Path)

    search = subcommands.add_parser("search", help="Search the configured music provider")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    queue = subcommands.add_parser("queue", help="Queue a provider track ref as the next track")
    queue.add_argument("track_ref")

    favorite = subcommands.add_parser("favorite", help="Favorite a track id")
    favorite.add_argument("track_id")

    preferences = subcommands.add_parser("preferences", help="Manage listener taste inputs")
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


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
