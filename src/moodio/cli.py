from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

import uvicorn

from moodio.api.schemas import CommandRequest, FavoriteRequest
from moodio.music.providers import MusicProvider
from moodio.music.soundcloud import SoundCloudProvider
from moodio.runtime.service import RuntimeService


def default_music_provider() -> MusicProvider:
    return SoundCloudProvider(
        client_id=os.environ.get("SOUNDCLOUD_CLIENT_ID"),
        oauth_token=os.environ.get("SOUNDCLOUD_OAUTH_TOKEN"),
    )


def run(
    argv: list[str] | None = None,
    *,
    runtime_factory: Callable[[], RuntimeService] = RuntimeService,
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
    elif args.command_name == "next":
        _print_json(await runtime.next_track(), stdout)
    elif args.command_name == "previous":
        _print_json(await runtime.previous_track(), stdout)
    elif args.command_name == "favorite":
        response = await runtime.favorite_track(FavoriteRequest(track_id=args.track_id))
        _print_json(response.model_dump(), stdout)
    elif args.command_name == "queue":
        provider_name, provider_track_id = _parse_track_ref(args.track_ref)
        if provider_name != "soundcloud":
            raise ValueError(f"unsupported provider: {provider_name}")
        provider = provider_factory()
        provider_track = await provider.resolve_track(provider_track_id)
        _print_json(await runtime.queue_track(provider_track.to_queue_item()), stdout)
    else:
        raise ValueError(f"unsupported command: {args.command_name}")

    return 0


def _parse_track_ref(track_ref: str) -> tuple[str, str]:
    parts = track_ref.split(":")
    if len(parts) != 3 or parts[1] != "track" or not parts[0] or not parts[2]:
        raise ValueError("track ref must look like '<provider>:track:<id>'")
    return parts[0], parts[2]


def _print_json(payload: Any, stdout: TextIO) -> None:
    stdout.write(json.dumps(payload, indent=2, sort_keys=True))
    stdout.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moodio")
    subcommands = parser.add_subparsers(dest="command_name", required=True)

    serve = subcommands.add_parser("serve", help="Run the moodio HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)

    subcommands.add_parser("now", help="Print current station state")
    subcommands.add_parser("transcript", help="Print current transcript")
    subcommands.add_parser("next", help="Advance to next queued track")
    subcommands.add_parser("previous", help="Return to previous track")

    command = subcommands.add_parser("command", help="Send a natural-language station command")
    command.add_argument("text")

    search = subcommands.add_parser("search", help="Search the configured music provider")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    queue = subcommands.add_parser("queue", help="Queue a provider track ref as the next track")
    queue.add_argument("track_ref")

    favorite = subcommands.add_parser("favorite", help="Favorite a track id")
    favorite.add_argument("track_id")

    return parser


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
