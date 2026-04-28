# Music Agent Docs

- [SPEC.md](/Users/yuxingzhou/Local_Projects/music_agent/SPEC.md)
- [ARCHITECTURE.md](/Users/yuxingzhou/Local_Projects/music_agent/ARCHITECTURE.md)
- [UI_DESIGN_PROMPT.md](/Users/yuxingzhou/Local_Projects/music_agent/UI_DESIGN_PROMPT.md)
- [TEST_PLAN.md](/Users/yuxingzhou/Local_Projects/music_agent/TEST_PLAN.md)

## Current Direction

The implementation baseline for `moodio` is the latest compatible OpenAI Agents SDK release as the base harness.

That means this repo is intended to layer app-owned tools, prompts, hooks, state, and execution policy on top of the SDK rather than building a bespoke agent loop first.

## Development Setup

This repo currently uses a local Python virtual environment in `.venv/`.

Prerequisites:

- Python 3.11
- `uv`

Bootstrap a fresh clone with:

```bash
uv venv --python python3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

Run the backend test suite with:

```bash
.venv/bin/pytest -q
```

## Headless CLI

The local package installs a `moodie` command for running the backend without a browser UI:

```bash
moodie now
moodie transcript
moodie command "play something warmer"
moodie search "of monsters and men"
moodie queue soundcloud:track:123
moodie serve --host 127.0.0.1 --port 8765
```

`moodie search` and `moodie queue` currently use the SoundCloud provider adapter. Set either `SOUNDCLOUD_CLIENT_ID` or `SOUNDCLOUD_OAUTH_TOKEN` before using live SoundCloud API calls.
