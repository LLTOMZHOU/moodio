# Moodio Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status note:** This file is the executed working plan. The task order, scope, and architecture decisions remain useful history, but the inline code snippets are draft implementation targets from before review/fix iterations and are not the final source of truth for shipped code.

**Goal:** Replace the seeded in-memory backend with a real TDD-built runtime that uses the latest compatible OpenAI Agents SDK as the base harness and keeps app-owned routing, state, execution, tools, prompts, and hooks explicit.

**Architecture:** Keep the existing FastAPI + WebSocket surface stable while adding a thin hard-edge router around the latest OpenAI Agents SDK. The app owns deterministic operational gates, context assembly, SQLite state, playback/TTS policy, and final-action execution; the Agents SDK owns non-hard-edge mode selection, tool use, and structured final output.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, pytest, httpx, sqlite3, OpenAI Agents SDK (`openai-agents`)

---

## File Structure

**Create:**
- `docs/superpowers/plans/2026-04-22-moodio-backend-foundation.md`
- `src/moodio/domain/triggers.py`
- `src/moodio/domain/events.py`
- `src/moodio/router.py`
- `src/moodio/state_store.py`
- `src/moodio/context_builder.py`
- `src/moodio/executor.py`
- `src/moodio/station_agent.py`
- `src/moodio/runtime/service.py`
- `tests/unit/test_router.py`
- `tests/unit/test_state_store.py`
- `tests/unit/test_context_builder.py`
- `tests/integration/test_runtime_loop.py`
- `tests/fixtures/fake_model.py`
- `tests/fixtures/fake_context.py`

**Modify:**
- `pyproject.toml`
- `src/moodio/api/server.py`
- `src/moodio/api/schemas.py`
- `src/moodio/runtime/in_memory.py`
- `tests/integration/test_server_http.py`
- `tests/integration/test_server_ws.py`

**Keep As-Is Until Final Cleanup:**
- `tests/unit/test_action_schema.py`
- `tests/unit/test_domain_models.py`
- `tests/contract/test_api_schemas.py`
- `tests/contract/test_event_schemas.py`

---

### Task 1: Deterministic Trigger Models And Router

**Files:**
- Create: `src/moodio/domain/triggers.py`
- Create: `src/moodio/router.py`
- Test: `tests/unit/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
from moodio.domain.triggers import PlaybackTrigger, SchedulerTrigger, UserCommandTrigger
from moodio.router import route_trigger


def test_route_user_command_to_user_request() -> None:
    trigger = UserCommandTrigger(text="play something warmer")

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "user_request"


def test_route_playback_near_end_to_radio_continue() -> None:
    trigger = PlaybackTrigger(
        event_type="music.playback.near_end",
        track_id="apple:track:if-bread",
        position_seconds=182,
        duration_seconds=197,
    )

    route = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)

    assert route == "radio_continue"


def test_route_empty_queue_to_recovery() -> None:
    trigger = SchedulerTrigger(reason="hourly refresh")

    route = route_trigger(trigger=trigger, queue_depth=0, provider_error=False)

    assert route == "recovery"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_router.py -q`
Expected: `ModuleNotFoundError` for `moodio.domain.triggers` or `moodio.router`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/domain/triggers.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserCommandTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["user_command"] = "user_command"
    text: str = Field(min_length=1)


class PlaybackTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["playback"] = "playback"
    event_type: Literal["music.playback.near_end", "music.playback.ended"]
    track_id: str = Field(min_length=1)
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)


class SchedulerTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["scheduler"] = "scheduler"
    reason: str = Field(min_length=1)


Trigger = UserCommandTrigger | PlaybackTrigger | SchedulerTrigger
```

```python
# src/moodio/router.py
from __future__ import annotations

from moodio.domain.models import StationMode
from moodio.domain.triggers import PlaybackTrigger, Trigger, UserCommandTrigger


def route_trigger(trigger: Trigger, queue_depth: int, provider_error: bool) -> StationMode:
    if provider_error or queue_depth == 0:
        return "recovery"
    if isinstance(trigger, UserCommandTrigger):
        return "user_request"
    if isinstance(trigger, PlaybackTrigger):
        return "radio_continue"
    return "radio_continue"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_router.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_router.py src/moodio/domain/triggers.py src/moodio/router.py
git commit -m "feat: add deterministic trigger router"
```

---

### Task 2: SQLite State Store For Recent Plays, Commands, And Transcript

**Files:**
- Create: `src/moodio/state_store.py`
- Test: `tests/unit/test_state_store.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from moodio.state_store import StateStore


def test_state_store_persists_recent_operational_history(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "moodio.db")

    store.record_command("play something warmer")
    store.record_play("apple:track:if-bread", "If")
    store.record_transcript("seg_001", "A late-night exhale.", 0, 3200)

    snapshot = store.recent_context(limit=5)

    assert snapshot["commands"][0]["text"] == "play something warmer"
    assert snapshot["plays"][0]["track_id"] == "apple:track:if-bread"
    assert snapshot["transcript"][0]["segment_id"] == "seg_001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_state_store.py -q`
Expected: `ModuleNotFoundError: No module named 'moodio.state_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/state_store.py
from __future__ import annotations

import sqlite3
from pathlib import Path


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists commands (
                  id integer primary key,
                  text text not null
                );
                create table if not exists plays (
                  id integer primary key,
                  track_id text not null,
                  title text not null
                );
                create table if not exists transcript_segments (
                  id integer primary key,
                  segment_id text not null,
                  text text not null,
                  start_ms integer not null,
                  duration_ms integer not null
                );
                """
            )

    def record_command(self, text: str) -> None:
        with self._connect() as conn:
            conn.execute("insert into commands(text) values (?)", (text,))

    def record_play(self, track_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute("insert into plays(track_id, title) values (?, ?)", (track_id, title))

    def record_transcript(self, segment_id: str, text: str, start_ms: int, duration_ms: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into transcript_segments(segment_id, text, start_ms, duration_ms) values (?, ?, ?, ?)",
                (segment_id, text, start_ms, duration_ms),
            )

    def recent_context(self, limit: int) -> dict:
        with self._connect() as conn:
            commands = conn.execute("select text from commands order by id desc limit ?", (limit,)).fetchall()
            plays = conn.execute("select track_id, title from plays order by id desc limit ?", (limit,)).fetchall()
            transcript = conn.execute(
                "select segment_id, text, start_ms, duration_ms from transcript_segments order by id desc limit ?",
                (limit,),
            ).fetchall()
        return {
            "commands": [{"text": row[0]} for row in commands],
            "plays": [{"track_id": row[0], "title": row[1]} for row in plays],
            "transcript": [
                {"segment_id": row[0], "text": row[1], "start_ms": row[2], "duration_ms": row[3]}
                for row in transcript
            ],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_state_store.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_state_store.py src/moodio/state_store.py
git commit -m "feat: add sqlite state store"
```

---

### Task 3: Context Builder With The Six Architecture Buckets

**Files:**
- Create: `src/moodio/context_builder.py`
- Create: `tests/fixtures/fake_context.py`
- Test: `tests/unit/test_context_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from moodio.context_builder import build_context_payload
from tests.fixtures.fake_context import fake_environment_snapshot, fake_recent_context


def test_context_builder_assembles_six_buckets() -> None:
    payload = build_context_payload(
        mode="user_request",
        trigger={"kind": "user_command", "text": "play something warmer"},
        user_corpus={"taste": "soft rock at night"},
        environment=fake_environment_snapshot(),
        recent_context=fake_recent_context(),
        scheduler_payload=None,
    )

    assert payload["mode"] == "user_request"
    assert set(payload["context"].keys()) == {
        "system_instructions",
        "user_corpus",
        "environment_snapshot",
        "persisted_memory",
        "latest_input",
        "scheduler_payload",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context_builder.py -q`
Expected: `ModuleNotFoundError: No module named 'moodio.context_builder'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/context_builder.py
from __future__ import annotations


def build_context_payload(
    mode: str,
    trigger: dict,
    user_corpus: dict,
    environment: dict,
    recent_context: dict,
    scheduler_payload: dict | None,
) -> dict:
    return {
        "mode": mode,
        "context": {
            "system_instructions": {
                "host_name": "moodio",
                "voice": "default_male_1",
            },
            "user_corpus": user_corpus,
            "environment_snapshot": environment,
            "persisted_memory": recent_context,
            "latest_input": trigger,
            "scheduler_payload": scheduler_payload,
        },
    }
```

```python
# tests/fixtures/fake_context.py
def fake_environment_snapshot() -> dict:
    return {"time_of_day": "night", "weather": "cool and clear"}


def fake_recent_context() -> dict:
    return {
        "commands": [{"text": "talk less"}],
        "plays": [{"track_id": "apple:track:if-bread", "title": "If"}],
        "transcript": [{"segment_id": "seg_001", "text": "Late-night exhale."}],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context_builder.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_context_builder.py tests/fixtures/fake_context.py src/moodio/context_builder.py
git commit -m "feat: add context builder"
```

---

### Task 4: Executor That Validates Final Actions And Emits Ordered Events

**Files:**
- Create: `src/moodio/domain/events.py`
- Create: `src/moodio/executor.py`
- Test: `tests/integration/test_runtime_loop.py`

- [ ] **Step 1: Write the failing test**

```python
from moodio.api.schemas import FinalAction
from moodio.executor import execute_action


def test_execute_action_emits_tts_before_queue_update() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "radio_continue",
            "say": {
                "text": "A softer turn here.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [
                {
                    "track_id": "apple:track:rainy-focus-02",
                    "reason": "keep the station warm",
                    "start_policy": "after_tts",
                }
            ],
            "player_actions": [],
            "talk_density": "balanced",
        }
    )

    events = execute_action(action)

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.segment.completed",
        "queue.updated",
        "station.state.updated",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_runtime_loop.py::test_execute_action_emits_tts_before_queue_update -q`
Expected: `ModuleNotFoundError: No module named 'moodio.executor'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/domain/events.py
from __future__ import annotations

from typing import TypedDict


class RuntimeEvent(TypedDict):
    event: str
    payload: dict
```

```python
# src/moodio/executor.py
from __future__ import annotations

from moodio.api.schemas import FinalAction
from moodio.domain.events import RuntimeEvent


def execute_action(action: FinalAction) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    if action.say is not None:
        segment_payload = {
            "segment_id": "seg_runtime_001",
            "text": action.say.text,
            "start_ms": 0,
            "duration_ms": 3000,
            "voice": action.say.voice,
            "state": "speaking",
        }
        events.append({"event": "tts.segment.started", "payload": segment_payload})
        events.append({"event": "tts.segment.completed", "payload": segment_payload})
    if action.queue_tracks:
        events.append({"event": "queue.updated", "payload": {"queue": action.queue_tracks}})
    events.append({"event": "station.state.updated", "payload": {"mode": action.mode}})
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/integration/test_runtime_loop.py::test_execute_action_emits_tts_before_queue_update -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_runtime_loop.py src/moodio/domain/events.py src/moodio/executor.py
git commit -m "feat: add final action executor"
```

---

### Task 5: Thin OpenAI Agents SDK Adapter Around Structured FinalAction Output

**Files:**
- Modify: `pyproject.toml`
- Create: `src/moodio/station_agent.py`
- Create: `tests/fixtures/fake_model.py`
- Modify: `tests/integration/test_runtime_loop.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.fixtures.fake_model import fake_agent_result
from moodio.station_agent import parse_agent_result


def test_station_agent_parses_structured_final_action() -> None:
    result = parse_agent_result(fake_agent_result())

    assert result.mode == "radio_continue"
    assert result.say is not None
    assert result.say.voice == "default_male_1"


def test_station_agent_accepts_model_selected_mode_on_soft_turns() -> None:
    result = parse_agent_result(fake_agent_result(mode="user_request"))

    assert result.mode == "user_request"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_runtime_loop.py::test_station_agent_parses_structured_final_action -q`
Expected: `ModuleNotFoundError: No module named 'moodio.station_agent'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
dependencies = [
  "fastapi>=0.115",
  "pydantic>=2.10",
  "openai-agents",
]
```

```python
# tests/fixtures/fake_model.py
def fake_agent_result(mode: str = "radio_continue") -> dict:
    return {
        "mode": mode,
        "say": {
            "text": "Staying warm and gentle here.",
            "voice": "default_male_1",
            "interruptible": True,
        },
        "queue_tracks": [],
        "player_actions": [],
        "talk_density": "balanced",
    }
```

```python
# src/moodio/station_agent.py
from __future__ import annotations

from agents import Agent, Runner, function_tool

from moodio.api.schemas import FinalAction


def build_station_agent() -> Agent:
    @function_tool
    def read_queue() -> dict:
        return {"queue_depth": 1}

    return Agent(
        name="moodio",
        instructions=(
            "Act as the on-air station host. "
            "When the app sends you a non-hard-edge turn, choose the correct mode "
            "and return a strict FinalAction."
        ),
        tools=[read_queue],
        output_type=FinalAction,
    )


def parse_agent_result(payload: dict) -> FinalAction:
    return FinalAction.model_validate(payload)


async def run_station_turn(input_payload: dict) -> FinalAction:
    result = await Runner.run(build_station_agent(), input=input_payload)
    return FinalAction.model_validate(result.final_output)
```

- [ ] **Step 4: Reinstall dependencies and run the test to verify it passes**

Run: `uv pip install --python .venv/bin/python -e '.[dev]' && .venv/bin/pytest tests/integration/test_runtime_loop.py::test_station_agent_parses_structured_final_action tests/integration/test_runtime_loop.py::test_station_agent_accepts_model_selected_mode_on_soft_turns -q`
Expected: dependency install succeeds and the test ends with `2 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/fixtures/fake_model.py src/moodio/station_agent.py tests/integration/test_runtime_loop.py
git commit -m "feat: add agents sdk station adapter"
```

---

### Task 6: Runtime Service And FastAPI Wiring

**Files:**
- Create: `src/moodio/runtime/service.py`
- Modify: `src/moodio/api/server.py`
- Modify: `src/moodio/runtime/in_memory.py`
- Modify: `tests/integration/test_server_http.py`
- Modify: `tests/integration/test_server_ws.py`
- Modify: `tests/integration/test_runtime_loop.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from moodio.api.server import create_app


def test_post_command_runs_full_runtime_loop() -> None:
    client = TestClient(create_app())

    response = client.post("/api/command", json={"text": "play something warmer"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["kind"] == "natural_language"

    now_response = client.get("/api/now")
    now_payload = now_response.json()
    assert now_payload["mode"] in {"user_request", "radio_continue", "recovery"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_server_http.py::test_post_command_runs_full_runtime_loop -q`
Expected: FAIL because `/api/command` still only echoes input and `/api/now` still comes from seeded `InMemoryRuntime`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/runtime/service.py
from __future__ import annotations

from moodio.api.schemas import AcceptedResponse, CommandRequest, PlaybackEventRequest
from moodio.context_builder import build_context_payload
from moodio.domain.triggers import UserCommandTrigger
from moodio.executor import execute_action
from moodio.router import route_trigger
from moodio.state_store import StateStore
from moodio.station_agent import run_station_turn


class RuntimeService:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.mode = "radio_continue"

    async def accept_command(self, request: CommandRequest) -> AcceptedResponse:
        self.store.record_command(request.text)
        trigger = UserCommandTrigger(text=request.text)
        hard_edge_mode = route_trigger(trigger=trigger, queue_depth=1, provider_error=False)
        payload = build_context_payload(
            mode=hard_edge_mode or "model_select",
            trigger=trigger.model_dump(),
            user_corpus={"taste": "soft rock at night"},
            environment={"time_of_day": "night", "weather": "clear"},
            recent_context=self.store.recent_context(limit=5),
            scheduler_payload=None,
        )
        action = await run_station_turn(payload)
        self.mode = action.mode
        self.last_events = execute_action(action)
        return AcceptedResponse(accepted=True, kind="natural_language", text=request.text)

    async def ingest_playback_event(self, request: PlaybackEventRequest) -> AcceptedResponse:
        return AcceptedResponse(accepted=True, kind="playback_event", text=None)
```

```python
# src/moodio/api/server.py
from pathlib import Path

from moodio.runtime.service import RuntimeService
from moodio.state_store import StateStore


def create_app() -> FastAPI:
    app = FastAPI()
    app.state.runtime = RuntimeService(StateStore(Path("var/state/music_agent.db")))
    return app
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `.venv/bin/pytest tests/integration/test_server_http.py tests/integration/test_server_ws.py tests/integration/test_runtime_loop.py -q`
Expected: all edited tests pass without network access

- [ ] **Step 5: Commit**

```bash
git add src/moodio/runtime/service.py src/moodio/api/server.py src/moodio/runtime/in_memory.py src/moodio/state_store.py tests/integration/test_server_http.py tests/integration/test_server_ws.py tests/integration/test_runtime_loop.py
git commit -m "feat: wire runtime service through fastapi"
```

---

### Task 7: Recovery Path And Full Regression Pass

**Files:**
- Modify: `tests/integration/test_runtime_loop.py`
- Modify: `src/moodio/executor.py`
- Modify: `src/moodio/runtime/service.py`

- [ ] **Step 1: Write the failing test**

```python
from moodio.api.schemas import FinalAction
from moodio.executor import execute_action


def test_execute_action_handles_tts_failure_with_music_only_fallback() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "recovery",
            "say": {
                "text": "Fallback line.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [
                {
                    "track_id": "apple:track:rainy-focus-02",
                    "reason": "safe fallback",
                    "start_policy": "immediate",
                }
            ],
            "player_actions": [],
            "talk_density": "low",
        }
    )

    events = execute_action(action, tts_should_fail=True)

    assert [event["event"] for event in events] == [
        "queue.updated",
        "station.state.updated",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_runtime_loop.py::test_execute_action_handles_tts_failure_with_music_only_fallback -q`
Expected: FAIL because `execute_action` does not accept `tts_should_fail`

- [ ] **Step 3: Write minimal implementation**

```python
# src/moodio/executor.py
def execute_action(action: FinalAction, tts_should_fail: bool = False) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    if action.say is not None and not tts_should_fail:
        segment_payload = {
            "segment_id": "seg_runtime_001",
            "text": action.say.text,
            "start_ms": 0,
            "duration_ms": 3000,
            "voice": action.say.voice,
            "state": "speaking",
        }
        events.append({"event": "tts.segment.started", "payload": segment_payload})
        events.append({"event": "tts.segment.completed", "payload": segment_payload})
    if action.queue_tracks:
        events.append({"event": "queue.updated", "payload": {"queue": action.queue_tracks}})
    events.append({"event": "station.state.updated", "payload": {"mode": action.mode}})
    return events
```

- [ ] **Step 4: Run the full regression suite**

Run: `.venv/bin/pytest -q`
Expected: all unit, contract, and integration tests pass

- [ ] **Step 5: Commit**

```bash
git add src/moodio/executor.py src/moodio/runtime/service.py tests/integration/test_runtime_loop.py
git commit -m "feat: add recovery fallback path"
```

---

## Self-Review

### Spec Coverage

- `radio_continue`, `user_request`, and `recovery` are covered by Tasks 1, 4, 6, and 7.
- app-owned state and recent memory are covered by Task 2.
- six-bucket prompt assembly is covered by Task 3.
- the latest compatible OpenAI Agents SDK base harness is covered by Task 5.
- execution ordering and recovery fallback are covered by Tasks 4 and 7.
- HTTP/WebSocket continuity is covered by Task 6.
- desktop shell and browser tests are intentionally deferred; that matches `TEST_PLAN.md` Phase 2.

### Placeholder Scan

- No `TODO`, `TBD`, or “implement later” markers remain.
- Commands, file paths, and test names are explicit.

### Type Consistency

- `FinalAction` stays in `src/moodio/api/schemas.py` for this first backend plan.
- `route_trigger(...)` returns existing `StationMode` values.
- runtime integration consistently uses `AcceptedResponse` for command/event acceptance.
