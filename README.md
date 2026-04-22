# Music Agent Docs

- [SPEC.md](/Users/yuxingzhou/Local_Projects/music_agent/SPEC.md)
- [ARCHITECTURE.md](/Users/yuxingzhou/Local_Projects/music_agent/ARCHITECTURE.md)
- [UI_DESIGN_PROMPT.md](/Users/yuxingzhou/Local_Projects/music_agent/UI_DESIGN_PROMPT.md)
- [TEST_PLAN.md](/Users/yuxingzhou/Local_Projects/music_agent/TEST_PLAN.md)

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
