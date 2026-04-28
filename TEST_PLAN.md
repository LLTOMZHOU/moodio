# Test Plan

## Goal

Design the test strategy so the project can be built in long, low-touch TDD sessions without depending on constant human review.

This document is the operating contract for implementation work:

- product behavior comes from `SPEC.md`
- system structure comes from `ARCHITECTURE.md`
- implementation should advance through failing tests, minimal code, review, and then expansion
- the latest compatible OpenAI Agents SDK release is the base harness under test, with app-owned tools, prompts, hooks, and executor logic layered around it

## TDD Working Rules

Every meaningful production change should follow this order:

1. write or update a failing test
2. implement the smallest change that makes it pass
3. run the narrowest relevant test set
4. review the diff against spec and architecture
5. only then widen scope

Rules:

- no silent product behavior changes without tests
- no provider-dependent logic in unit tests
- no reimplementation of the SDK loop in tests when a fake around our SDK integration seam is enough
- no "we will test this later" for core contracts
- every bug fix starts with a reproducer test
- every schema change requires contract tests

## Test Phases

TDD should be split into two clearly separated tracks.

### Phase 1: backend-first server tests

This is the immediate focus.

Scope:

- HTTP server behavior
- WebSocket server behavior
- backend runtime orchestration
- backend state transitions
- backend queue and transcript contracts

This phase should use:

- normal server tests
- schema and contract tests
- integration tests with fake adapters

This phase should not depend on:

- Playwright
- browser automation
- rendered UI assertions

### Phase 2: frontend browser tests

This comes later, after backend contracts are stable.

Scope:

- frontend playback behavior
- widget expand/collapse behavior
- transcript rendering behavior
- event handling in the browser
- UI interaction flows

Suggested tools later:

- Playwright
- browser-use or similar browser automation where useful

The rule is:

- stabilize backend contracts first
- then test the frontend against those contracts

## Testing Goals

The test suite should prove:

- the hard deterministic routing edges behave correctly
- context assembly is predictable and bounded
- agent output is validated before side effects occur
- side effects are executed in the right order
- transcript and playback state remain synchronized
- recovery behavior is deterministic
- the HTTP and WebSocket surfaces expose the right state

For now, these goals should be satisfied primarily through backend-server tests.

## Test Levels

### 1. Unit tests

Fast and deterministic.

Targets:

- `router.py`
- `context_builder.py`
- schema validators
- event models
- transcript timing helpers
- queue and playback state reducers
- state store query helpers

Requirements:

- no network
- no real clock without a fake
- no real filesystem outside temp dirs
- no real model provider

### 2. Contract tests

Lock the boundaries between modules.

Targets:

- final action schema
- tool input and output shapes
- API request and response schemas
- WebSocket event payload schemas
- persisted event formats

These tests matter because the project will likely be implemented across long autonomous sessions. Contracts prevent drift.

### 3. Integration tests

Run several modules together with fake adapters.

Targets:

- trigger -> hard-edge router -> context builder -> fake station agent -> executor
- executor -> TTS adapter -> transcript events
- executor -> playback adapter -> queue state changes
- scheduler trigger -> station response
- command API -> runtime -> state update

Integration tests should use in-process fakes, not real providers.

### 4. End-to-end simulation tests

Use a fake model adapter and fake external services to simulate full user-visible flows.

Required scenarios:

- user says "play something warmer" and the station adapts
- track ends and the station continues coherently
- frontend sends `near_end` and the backend prepares the next transition without an audible gap
- TTS failure falls back to music-only continuation
- empty queue triggers recovery behavior
- user favorites a track directly and the state updates
- the agent offers to favorite a track and the favorite action remains deterministic

These tests should verify emitted events and persisted state, not pixel output.

At this stage, "end-to-end" still means backend end-to-end, not browser end-to-end.

### 5. Focused manual review

Reserve manual review for areas that automated tests cannot fully judge:

- UI layout quality
- motion quality
- audio feel
- editorial quality of transitions

Manual review should happen on small vertical slices, not after a huge batch of work.

### 6. Frontend browser tests later

Once the backend contracts are stable, add browser-driven tests for:

- transport controls
- transcript updates
- widget collapse/expand behavior
- WebSocket reconnection behavior
- Apple Music / playback integration boundaries where testable

These should be added only after the backend HTTP and WebSocket contracts stop moving frequently.

## Required Test Doubles

The implementation should define stable fake adapters early.

### Fake model adapter

Needed to test:

- tool call flows
- final action parsing
- failure and malformed output handling

Capabilities:

- return a final action directly
- return a sequence of tool calls followed by a final action
- return malformed output for validation tests
- return provider errors for recovery tests

### Fake music provider

Needed to test:

- search results
- recommendations
- missing tracks
- empty result sets

### Fake TTS adapter

Needed to test:

- successful synthesis
- duration metadata
- transcript segment timing
- synthesis failure

### Fake playback adapter

Needed to test:

- queue updates
- start / pause / resume / skip
- track-ended events
- near-end events
- device targeting

### Fake context providers

Needed to test:

- weather snapshots
- current time and schedule windows

## Contracts To Lock Early

These should be specified before deeper implementation.

### Domain models

- `StationState`
- `NowPlaying`
- `QueueItem`
- `TranscriptSegment`
- `SchedulerTrigger`
- `UserCommand`

### Final action output

The agent's final action object is one of the highest-risk seams and must be locked down with tests before wiring real providers.

Tests should cover:

- valid radio continuation action
- valid speech-only action
- valid recovery action
- unknown mode rejection
- invalid track ID rejection
- missing required fields rejection

### Event stream

The UI depends on these events being stable.

Tests should cover:

- ordering
- payload shape
- correlation IDs where used
- state transitions for `thinking`, `speaking`, and `playing`
- frontend playback lifecycle events including `started`, `near_end`, and `ended`

## Proposed Test Layout

```text
tests/
  unit/
    test_router.py
    test_context_builder.py
    test_domain_models.py
    test_action_schema.py
    test_transcript_timing.py
    test_state_store.py
  contract/
    test_api_schemas.py
    test_event_schemas.py
    test_tool_contracts.py
  integration/
    test_runtime_loop.py
    test_executor_tts.py
    test_executor_playback.py
    test_playback_event_flow.py
    test_scheduler_flow.py
    test_command_flow.py
  e2e/
    test_warmer_request_flow.py
    test_track_end_continuation.py
    test_near_end_preparation_flow.py
    test_recovery_on_empty_queue.py
    test_recovery_on_tts_failure.py
    test_direct_favorite_flow.py
    test_agent_offered_favorite_flow.py
  fixtures/
    fake_model.py
    fake_music_provider.py
    fake_tts.py
    fake_playback.py
    fake_context.py
frontend_tests/
  playwright/
    test_transport_controls.spec.ts
    test_transcript_updates.spec.ts
    test_widget_toggle.spec.ts
    test_ws_reconnect.spec.ts
```

The `frontend_tests/` tree is explicitly deferred until Phase 2.

## Slice-By-Slice Implementation Order

### Slice 1: domain models and schemas

Write tests first for:

- core enums and data models
- final action schema
- transcript segment model

Done means:

- all contracts compile
- invalid payloads are rejected clearly

### Slice 2: backend HTTP and WebSocket contracts

Write tests first for:

- `GET /api/now`
- `GET /api/transcript/current`
- `POST /api/command`
- direct transport endpoints like `POST /api/next` and `POST /api/favorite`
- WebSocket event payloads and ordering

Done means:

- the server contract is stable enough for the rest of backend work
- browser/UI work can be deferred safely

### Slice 3: router

Write tests first for:

- direct deterministic actions
- empty-queue recovery routing
- obvious playback lifecycle gating
- pass-through behavior for non-hard-edge turns

Done means:

- the hard-edge gate is deterministic
- the model is only skipped for the explicit hard-edge cases

### Slice 4: state store

Write tests first for:

- persist and read recent plays
- persist and read recent commands
- persist transcript segments
- derive UI-ready recent state

### Slice 5: executor

Write tests first for:

- apply valid action
- reject invalid action
- emit correct events
- sequence TTS before playback when required

### Slice 6: context builder

Write tests first for:

- correct six-bucket assembly
- recency trimming
- prompt size limits
- omission of raw internal data that should stay outside the model

### Slice 7: station agent adapter

Write tests first for:

- lightweight mode classification on non-hard-edge turns
- fake tool call loop
- final action extraction
- malformed model output recovery

### Slice 8: full simulated backend flows

Write tests first for the end-to-end scenarios listed above.

### Slice 9: frontend browser tests later

Write tests first for:

- transport button flows in the desktop shell
- transcript rendering after backend events
- widget collapse and expand flows
- resilience to WebSocket reconnects

## Review Checklist Per Session

At the end of each implementation session, review:

- does the change match `SPEC.md`
- does the structure match `ARCHITECTURE.md`
- were tests written first
- are new contracts explicitly covered
- were fake adapters used instead of real providers where appropriate
- is recovery behavior covered
- did the diff stay within one coherent slice

## Definition Of Done

A slice is done only when:

- the intended behavior is covered by tests
- the tests pass locally
- the implementation follows the architecture
- failure and recovery cases were considered
- the public contract for that slice is stable enough for the next session
