# Music Agent Architecture

## Companion Docs

- `SPEC.md`: product scope, user experience, and acceptance criteria
- `UI_DESIGN_PROMPT.md`: ready-to-paste prompt for Claude Design
- `TEST_PLAN.md`: TDD strategy, test seams, and session guardrails

## Goal

Build `moodio`, a personal AI radio / voice DJ system that follows the layered station idea already captured in the repo docs, but replaces the `claude -p` subprocess with the latest compatible OpenAI Agents SDK as the base harness.

The important shift is:

- the model runtime is no longer a black-box CLI subprocess
- tool access, memory, scheduling, and action output become first-class parts of the app
- the overall product shape still stays the same: taste files + music APIs + context assembly + orchestration + TTS + playback + desktop app shell

## Core Decision

Use the latest compatible OpenAI Agents SDK as the base harness and turn orchestrator, not as the whole product.

That means:

- the app owns state, scheduling, APIs, and device integration
- the agent owns reasoning over the current turn and deciding which tools to call
- the SDK's tool, prompt, and hook surfaces are the first place to extend runtime behavior
- the final model output is the short spoken DJ line; app state changes happen through typed tools

This is a better fit than a `claude -p` wrapper because the harness becomes explicit and portable.

## System Shape

Keep the four-layer system shape:

1. Inputs and external services
2. Local orchestration modules
3. Runtime turn assembly and agent loop
4. Delivery surfaces: desktop app shell, HTTP API, audio stream, scheduler hooks

## Product Experience

This is not just "an agent with music tools". It is a personal radio station with a persistent on-air identity.

The UI should preserve these qualities:

- broadcast feel rather than chatbot feel
- one named station host with a stable persona: `moodio`
- visible live state: `on air`, `speaking`, `playing`, `connected`
- synced transcript while TTS is speaking
- music-first controls, with chat as a secondary lane
- support an expanded desktop console and a compact widget-like collapsed state

The desktop UI should therefore be treated as a station console, not a generic assistant dashboard.

## Layer 1: Inputs And External Services

These are the core external inputs and services the system depends on.

### User corpus

Persistent preference files that define the station identity:

- `data/user/taste.md`
- `data/user/routines.md`
- `data/user/playlists.json`
- `data/user/mood_rules.md`
- `data/user/persona.md`

These should be treated as durable editorial inputs, not ephemeral chat history.

### Music services

Initial target:

- SoundCloud embed playback through oEmbed
- provider adapters for future NetEase, Audius, or other music APIs

Expose them through app-owned tool wrappers such as:

- `queue_soundcloud_embed(url)`
- `search_tracks(query, mood, limit)`
- `get_track_details(track_id)`
- `get_recommendations(seed_track_ids, mood, limit)`
- `get_lyrics(track_id)`
- `resolve_playable_url(track_id)`

### Voice and context services

Initial target tools:

- `get_weather_snapshot()`
- `synthesize_tts(script, voice, style)`
- `play_audio_on_device(url_or_path, target_device)`
- `notify_feishu(message)`

Keep device control and TTS outside the model. The agent can request them, but never executes them directly.

## External APIs

The system should keep external providers behind narrow adapter interfaces. The application should depend on provider capabilities, not provider-specific payloads.

### MVP-required providers

#### Music provider

Required capabilities:

- track search
- track metadata
- playable URL, stream source, or frontend-playback identifier
- recommendations if available

Strongly preferred:

- lyrics
- album art

Suggested adapter:

- `MusicProvider`

#### TTS provider

Required capabilities:

- speech synthesis
- voice selection
- audio file or stream output

Strongly preferred:

- duration metadata
- segment timing metadata if available

Suggested adapter:

- `TTSProvider`

#### LLM provider

Required capabilities:

- model invocation for the station agent
- structured output support
- tool-calling support
- streaming support for interactive runs

Suggested adapter:

- `ModelProvider`

#### Weather provider

Required capabilities:

- current weather snapshot

Suggested adapter:

- `WeatherProvider`

### Optional later providers

- standalone lyrics provider if the music provider does not expose lyrics well
- speech-to-text if microphone input becomes important
- notification providers if out-of-app nudges become useful
- listening-history integrations if external taste signals become important

### Not in MVP

- calendar providers
- user accounts and auth providers
- social music APIs
- browser automation providers

### Ownership boundary

These parts should stay app-owned even when external providers are used:

- playback engine
- queue state
- favorites
- transcript state
- SQLite persistence
- executor logic

## Frontend/Backend Boundary

The frontend and backend are co-located. The backend is expected to run as a local server, not as a public internet service.

### Recommended transport split

Use:

- HTTP for commands, current snapshots, and asset fetches
- WebSocket for live state, transcript, queue, and playback lifecycle events

Suggested shape:

- `POST /api/command`
- `POST /api/play`
- `POST /api/pause`
- `POST /api/next`
- `POST /api/previous`
- `POST /api/favorite`
- `GET /api/now`
- `GET /api/transcript/current`
- `GET /api/tts/:id`
- `WS /api/stream`

### Playback ownership

The frontend should own actual playback sequencing and transport state.

The backend should own:

- agent runs
- queue planning
- TTS generation requests
- persistence
- policy and pacing rules

The frontend should own:

- MusicKit playback
- local audio element playback for TTS audio
- final sequencing between speech and music
- reporting playback lifecycle events back to the backend

This keeps the backend simple and acknowledges that Apple Music playback belongs on the client side.

## Apple Music Boundary

If Apple Music is used, treat it as a split integration:

- backend: metadata, selection logic, queue planning, and app state
- frontend: actual playback through MusicKit

The backend should not try to act as a raw Apple Music streaming proxy or replace MusicKit playback.

For Apple-backed tracks, the queue item should therefore be able to store a frontend-playback identifier instead of assuming a raw audio URL.

## Layer 2: Local Orchestration Modules

These modules preserve the intended station runtime structure, but the model-facing boundary is cleaner.

### `router.py`

Acts as a thin hard-edge gate before the model runs.

It should stay deterministic code and only own cases where the app should not spend time asking the model what to do, for example:

- direct transport and favorite actions
- empty queue or explicit recovery conditions
- obvious playback lifecycle hooks that should immediately continue the station loop

For everything else, the router should not try to fully classify the user intent itself. It should hand the turn to the station agent and let the model decide which app tools to call.

### `context_builder.py`

Builds the model input from six buckets:

1. system instructions
2. user corpus
3. environment snapshot
4. persisted memory
5. latest user input and tool results
6. scheduler trigger payload

This module should own:

- trimming
- recency rules
- what enters the prompt versus what stays in app state
- conversion into the SDK input format

### `station_agent.py`

Defines the main agent:

- instructions: act like the station brain / DJ
- tools: only app-owned tools
- output type: plain text, intended for TTS

This agent is the runtime "brain" module, implemented as an SDK `Agent`.

### `scheduler.py`

Owns wall-clock and periodic triggers such as:

- hourly mood/weather check
- playback finished -> decide next segment

The scheduler should never ask the model to decide whether the scheduler exists. It only emits structured trigger events into the runtime.

### `tts.py`

Owns:

- voice selection
- synthesis provider integration
- content hashing
- audio cache layout

Default voice should be male. Voice selection is still configurable, but the product default should not drift.

Suggested cache layout:

- `var/cache/tts/<sha256>.mp3`

### `state_store.py`

Persistent memory and operational state.

Use SQLite first. That is enough for a single-user local system.

Tables:

- `messages`
- `tool_events`
- `plays`
- `prefs`
- `scheduler_events`
- `generated_audio`

The model should not read raw tables directly. The app should query and summarize the relevant slices.

## Layer 3: Runtime Turn Loop

This is the heart of the system.

### Trigger types

A run begins from one of these triggers:

- user text input from the desktop app shell
- direct button action like "next track" or "favorite"
- natural-language user request like "play something calmer"
- scheduled event
- playback lifecycle event like "track ended"
- external webhook event

### Turn assembly

For each trigger:

1. `router.py` checks whether the trigger is a hard deterministic case.
2. If yes, the app runs the deterministic path immediately.
3. Otherwise, `context_builder.py` assembles the current prompt payload.
4. The app invokes `Runner.run()` or `Runner.run_streamed()` with the station agent.
5. The agent may call tools.
6. Tool results are appended into the run.
7. The agent ends with a concise spoken line for TTS.
8. App tools have already applied any requested state changes.
9. State is persisted.
10. UI and audio state are updated.

This matches the Agents SDK loop directly:

- model call
- tool calls
- rerun
- final output

If needed for latency, the app can add a lightweight first-pass model classification for non-hard-edge triggers:

- no tools
- tiny prompt
- strict enum output
- low token budget

But that should still be treated as part of the model path, not as a large deterministic router.

### Final response contract

Do not use the agent's final response as an executable action object.

The current contract is:

- model-callable tools inspect and mutate app state
- direct UI actions call the same runtime operations where possible
- the final model output is only the short spoken line that the app can send to TTS
- risky state changes belong behind typed app tools, not in free-form text parsing

Tool implementations should enforce product pacing and safety rules:

- between-track speech should usually stay under 20 seconds
- overlong speech should be clipped or rejected before synthesis

Tool boundaries should distinguish between:

- deterministic player actions such as `next`, `pause`, `resume`, `favorite`
- agent-requested state changes such as `queue_track`, `set_talk_density`, and `save_memory_note`

### Agent structure

Start with one orchestrator agent, not many agents.

Initial design:

- one `StationAgent`
- specialist work happens through tools, not handoffs

Why:

- the domain is still narrow
- tool boundaries are clearer than agent boundaries
- fewer hidden transcripts
- easier debugging

Later, if needed, split into:

- `TasteEditorAgent`
- `MusicResearchAgent`

But the first version should keep one agent in charge.

## Layer 4: Delivery Surfaces

### Desktop app shell

The user-facing surface should behave like a desktop music app first, even if implemented with web technology.

The shell should support two presentation states:

- expanded station console
- compact widget-like collapsed player

### Desktop station console

Key regions:

- station header with identity, connection state, and theme controls
- large ambient clock and day/date block
- on-air state indicator
- now-playing rail with transport controls, queue, favorite, and volume
- live station feed with the DJ's latest spoken segment
- lightweight listener input box for "say something to the DJ"
- clear separation between direct transport controls and AI steering

This should feel like a persistent session, not a page that refreshes around each prompt.

### Collapsed widget state

Key regions:

- compact now-playing identity bar
- primary transport controls
- progress state
- quick favorite action
- one clear affordance to expand back to the full console

### Initial screens and states

Initial screens:

- desktop station console
- collapsed widget player
- current spoken transcript
- queue and recent plays
- taste profile editor
- recent memory/events

Core live states:

- `idle`
- `thinking`
- `speaking`
- `playing`
- `recovering`
- `offline`

### HTTP API

Suggested first endpoints:

- `GET /api/now`
- `GET /api/transcript/current`
- `GET /api/history/recent`
- `POST /api/command`
- `POST /api/play`
- `POST /api/pause`
- `POST /api/resume`
- `POST /api/next`
- `POST /api/previous`
- `POST /api/favorite`
- `WS /api/stream`

### Internal event bus

Even for a local-first app, define an internal event shape early:

- `user.command.received`
- `user.transport_action.received`
- `scheduler.triggered`
- `tts.segment.started`
- `tts.audio.ready`
- `tts.segment.completed`
- `music.playback.started`
- `music.playback.near_end`
- `playback.track_ended`
- `agent.run.started`
- `agent.run.completed`
- `tts.completed`
- `queue.updated`

This will keep the UI, playback engine, and agent runtime decoupled.

## Recommended Repository Shape

```text
music_agent/
  ARCHITECTURE.md
  pyproject.toml
  src/music_agent/
    app.py
    config.py
    router.py
    context_builder.py
    station_agent.py
    executor.py
    scheduler.py
    tts.py
    playback.py
    state_store.py
    api/
      server.py
      schemas.py
    tools/
      music.py
      weather.py
      memory.py
      playback.py
      tts.py
    prompts/
      system.md
      output_schema.json
    domain/
      events.py
      models.py
  web/
    README.md
  data/
    user/
      taste.md
      routines.md
      playlists.json
      mood_rules.md
      persona.md
  var/
    cache/
      tts/
    state/
      music_agent.db
```

## Agents SDK Integration

Use the latest compatible OpenAI Agents SDK release as the runtime loop and base harness, not as a replacement for app architecture.

The implementation stance is:

- start from the SDK's built-in agent loop rather than building a custom harness first
- add app-owned tools, prompts, hooks, and typed tool boundaries on top of that base
- keep long-lived state, scheduling, playback policy, and persistence in app code
- upgrade the SDK deliberately as part of normal dependency maintenance instead of pinning the design to one old release

### Primary use

- `Agent(...)` for the station brain
- `function_tool` wrappers for app capabilities
- prompt and hook surfaces for run-time instrumentation, guardrails, and traceability
- `Runner.run_streamed(...)` for interactive runs
- `Runner.run(...)` for scheduler/background turns

### Memory strategy

Do not rely on provider-managed conversation state as the primary memory system.

Prefer:

- app-owned SQLite state
- app-owned context assembly
- passing a fresh, trimmed input each turn

This keeps the system portable across providers and reduces hidden coupling.

### Model/provider boundary

Treat the model provider as swappable.

Use a model adapter boundary like:

- default provider: OpenRouter-backed OpenAI-compatible model
- later options: direct OpenAI, Anthropic, local model

The app should never bake provider quirks into the domain logic.

## Tool Design Principles

Tools should be narrow, typed, and side-effect aware.

Split them into:

### Read tools

Safe informational tools:

- `read_current_weather`
- `web_search`
- `read_recent_plays`
- `read_taste_profile`
- `search_tracks`
- `read_queue`

### Write or action tools

Side-effectful tools:

- `queue_track`
- `replace_queue`
- `synthesize_station_line`
- `send_to_output_device`
- `favorite_track`
- `set_talk_density`
- `save_memory_note`
- `schedule_follow_up`

For risky write tools, add executor confirmation rules in code, not in prompt text.

Favorites should be available both as a direct UI action and as a model-callable capability. The model should be able to offer the action conversationally, but the underlying favorite operation stays deterministic app code.

## Run Modes

The app is not one generic chatbot. Preserve that.

Define explicit run modes, but let the model choose between the editorial modes on non-hard-edge turns:

### `radio_continue`

Default autonomous station behavior:

- inspect playback and context
- choose what to say
- choose what to play next
- keep the queue warm with at least 1-2 upcoming tracks when possible

### `user_request`

Direct response to user input such as:

- "play something warmer"
- "less vocals"
- "what are you playing now?"
- "talk less for a while"
- "talk more for a while"

### `recovery`

Used when:

- queue is empty
- music API failed
- TTS failed
- provider request failed

The recovery path should be deterministic where possible.

## Transcript And Timing Model

Speech is not just audio output. It is a timed live artifact that the UI should render.

That means the runtime should emit transcript segments with timestamps:

- segment text
- segment start time
- optional word or phrase timing
- associated track or station mode

Minimum viable approach:

- store the exact TTS script
- record segment start time and duration
- stream coarse transcript chunks to the UI

Better later:

- word-level timing for transcript highlighting
- waveform segments derived from actual speech audio

This requirement should influence the executor and TTS interfaces from day one.

## Audio Sequencing

The frontend should be the final audio sequencer.

Recommended model:

1. backend decides the next spoken line and upcoming track queue
2. backend generates or retrieves cached TTS audio
3. frontend receives a playback plan over WebSocket or snapshot refresh
4. frontend plays TTS audio locally
5. when TTS completes, frontend starts the queued music item through its music playback layer
6. frontend reports music lifecycle events back to the backend
7. backend uses `near_end` and `ended` signals to prepare the next transition

This makes speech/music coordination explicit without requiring the backend to be the actual audio renderer.

### Playback lifecycle events

The frontend should send at least:

- `music.playback.started`
- `music.playback.progress`
- `music.playback.near_end`
- `music.playback.ended`
- `music.playback.paused`
- `music.playback.resumed`

`near_end` should fire early enough for the backend to prepare the next speech + track transition without a gap.

### Queue policy

The runtime should aim to keep:

- the current track
- at least 1 queued next track
- preferably 2 queued next tracks when provider state allows

Speech should be attached to transitions, not treated as an always-on second queue.

## Safety And Control

The app should not trust model output blindly.

Validation rules:

- final output must match schema
- only known track IDs can be queued
- playback commands must target known devices
- TTS text length should be capped
- memory writes should be summarized and bounded
- scheduler writes must respect rate limits

Add app-level fallbacks:

- if the model fails, continue current queue or play safe fallback playlist
- if TTS fails, skip speech and continue music
- if music search fails, reuse recent good candidates

## MVP Scope

The first shippable version should be intentionally small.

### MVP capabilities

- one user
- one playback target
- one TTS provider
- one music provider
- one main station agent
- SQLite memory
- desktop app shell with expanded and collapsed states
- explicit scheduler triggers

### Not in MVP

- multi-user support
- free-form subagent graph
- autonomous browsing
- complex long-horizon planning
- self-editing taste files without review

## Suggested Build Order

1. Define domain models and typed app-control tools.
2. Implement SQLite store and event log.
3. Implement read-only tools: taste, recent plays, weather, music search.
4. Implement `StationAgent` with mock playback executor.
5. Add TTS generation and local queue execution.
6. Add scheduler triggers.
7. Add desktop app shell and WebSocket stream.
8. Add recovery paths and observability.

## Why This Matches The Screenshot

This design preserves the original idea:

- user taste corpus remains central
- music, weather, and voice integrations remain external capability blocks
- local modules still look like router/context/scheduler/tts/state
- the runtime still assembles a context window from fixed buckets
- the frontend is still a desktop app shell plus HTTP/WebSocket contract

The only major replacement is the "brain" box:

- before: local `claude -p` subprocess with hidden harness behavior
- now: explicit agent runtime with owned tools, owned state, and plain spoken output

That is the right replacement if the goal is to understand and control the system rather than wrap somebody else's CLI.
