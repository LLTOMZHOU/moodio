from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tomllib

import pytest

from moodio.api.schemas import FinalAction
from moodio.cli import run
from moodio.music.providers import ProviderTrack
from moodio.runtime.service import RuntimeService
from moodio.state_store import StateStore


def _runtime(tmp_path) -> RuntimeService:
    return RuntimeService(state_store=StateStore(tmp_path / "moodio.db"))


def _provider_track() -> ProviderTrack:
    return ProviderTrack(
        provider="soundcloud",
        provider_track_id="123",
        title="The Actor",
        artist="Of Monsters and Men",
        album=None,
        duration_seconds=211,
        artwork_url="https://i1.sndcdn.com/artworks-actor.jpg",
        playback_ref="soundcloud:track:123",
        external_url="https://soundcloud.com/ofmonstersandmen/the-actor",
        stream_url=None,
        attribution={
            "source": "SoundCloud",
            "creator": "Of Monsters and Men",
            "external_url": "https://soundcloud.com/ofmonstersandmen/the-actor",
        },
    )


def test_cli_now_prints_station_snapshot(tmp_path) -> None:
    stdout = io.StringIO()

    exit_code = run(["now"], runtime_factory=lambda: _runtime(tmp_path), stdout=stdout)

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["host_name"] == "moodio"
    assert payload["now_playing"]["track_id"] == "apple:track:if-bread"


def test_cli_search_prints_provider_results_as_json() -> None:
    class FakeProvider:
        async def search_tracks(self, query: str, limit: int = 10) -> list[ProviderTrack]:
            assert query == "of monsters and men"
            assert limit == 5
            return [_provider_track()]

    stdout = io.StringIO()

    exit_code = run(
        ["search", "of monsters and men", "--limit", "5"],
        provider_factory=lambda: FakeProvider(),
        stdout=stdout,
    )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload[0]["provider"] == "soundcloud"
    assert payload[0]["playback_ref"] == "soundcloud:track:123"


def test_cli_queue_resolves_provider_track_and_updates_runtime(tmp_path) -> None:
    runtime = _runtime(tmp_path)

    class FakeProvider:
        async def resolve_track(self, provider_track_id: str) -> ProviderTrack:
            assert provider_track_id == "123"
            return _provider_track()

    stdout = io.StringIO()

    exit_code = run(
        ["queue", "soundcloud:track:123"],
        runtime_factory=lambda: runtime,
        provider_factory=lambda: FakeProvider(),
        stdout=stdout,
    )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["accepted"] is True
    assert payload["queue"][0]["track_id"] == "soundcloud:track:123"
    assert runtime.station_state.queue[0].track_id == "soundcloud:track:123"


def test_cli_command_runs_runtime_command_path(tmp_path) -> None:
    async def fake_station_turn(_: dict) -> FinalAction:
        return FinalAction.model_validate(
            {
                "mode": "user_request",
                "say": None,
                "queue_tracks": [],
                "player_actions": [],
                "talk_density": "low",
            }
        )

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_station_turn,
    )
    stdout = io.StringIO()

    exit_code = run(["command", "play something warmer"], runtime_factory=lambda: runtime, stdout=stdout)

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload == {
        "accepted": True,
        "kind": "natural_language",
        "text": "play something warmer",
    }


def test_cli_module_entrypoint_runs_command() -> None:
    env = {**os.environ, "PYTHONPATH": "src:."}

    result = subprocess.run(
        [sys.executable, "-m", "moodio.cli", "now"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["host_name"] == "moodio"


def test_package_exposes_moodie_console_script() -> None:
    with open("pyproject.toml", "rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    assert pyproject["project"]["scripts"]["moodie"] == "moodio.cli:main"


def test_cli_help_uses_moodie_program_name(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        run(["--help"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("usage: moodie ")
