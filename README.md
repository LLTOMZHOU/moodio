# moodio

> A personal, long-running AI DJ that learns your taste, keeps the music moving, and stays curious about the world around you.

`moodio` is not a chatbot that produces a playlist after a prompt. It is a private station with a persistent DJ: it can keep a queue healthy, react when you take control, remember what you love or skip, and gradually develop better programming instincts for you.

The project is local-first and single-listener by design. It owns the station state, memory, queue, and agent harness; it does not own, copy, or download the music catalog.

## Why moodio

Most AI DJ products are a static command-to-playlist flow:

```text
prompt -> generated playlist -> listener starts over next time
```

Moodio is meant to feel more like a living station:

```text
conversation + listening behaviour + live context
  -> persistent taste memory
  -> ongoing programming decisions
  -> a queue, a voice, and a station that continues without being prompted
```

The DJ is allowed to have editorial judgment. It should make a coherent next move, explain itself when asked, ease off when the listener wants quiet, and change course immediately when the listener intervenes.

## What makes it different

- **Long-running, not turn-bound.** The station can act when the queue runs low, a track is ending, an hour changes, or a real-world event matters—not only after a chat message.
- **Personal, but evidence-based.** Explicit instructions, favorites, searches, plays, skips, and conversation all become useful signals. A single accidental skip should not become a permanent taste rule.
- **Shared control.** Human and agent operate the same queue and transport controls. The DJ sees human actions as first-class events rather than guessing what happened in the player.
- **Agentic discovery, bounded execution.** The agent can search, compare candidates, and form a musical arc. It may only queue tracks the provider actually returned, through typed station controls.
- **Contextually curious.** Over time, the DJ can notice new releases by favorite artists, connect a rainy afternoon to a warmer selection, or surface a meaningful music-world update when it is genuinely relevant.
- **Respectful of the catalog.** Moodio does not download or retain tracks. Playback stays provider-backed and the app stores only the small amount of metadata and listening history needed to run the station.

## Hero journeys

### Start the day without programming a playlist

You open moodio while making coffee. It knows you tend to prefer gentle music in the morning, sees that yesterday ended with ambient electronic, and begins with something adjacent rather than repeating the same artists. It says little, keeps two tracks ready, and lets the room fill naturally.

### Take control without breaking the flow

You search for a specific song, queue it, pause the station, then resume it later. Those are direct controls—not requests that wait for an agent. The DJ sees each action in the station event stream, adjusts its plan, and does not speak over your intervention.

### Ask for a feeling, not a title

You say, “make this a little warmer, but keep the momentum.” The DJ searches the active provider, inspects real candidates, chooses one available track, and queues it with a concise reason. It does not hallucinate a song name or rely on a brittle first web result.

### Be understood over months, not one prompt

You favorite a few tracks, repeatedly skip a certain strain of vocal-heavy music, and explicitly say that you want less talking during work hours. Moodio keeps the evidence and forms a compact, revisable taste profile. You can inspect, correct, or forget it.

### Catch up with the music world

On a weekly or release-aware check-in, moodio can notice that a favorite artist has released something new. It can bring that fact into the station only when it is relevant, then find a playable candidate rather than treating news as a separate feed.

## Product principles

- **Broadcast, not chatbot.** Music and pacing come first; conversation is a steering lane.
- **Human control wins.** Direct transport and queue actions take effect immediately.
- **The model chooses; the runtime guarantees.** Prompts shape taste and behavior. Typed tools and state rules protect correctness, playback, and concurrency.
- **Memory is editable.** Moodio distinguishes raw observations from inferred preferences and keeps the listener in control of durable instructions.
- **No hidden music collection.** The product can cache metadata and preference signals, never the underlying audio catalog.

## Product direction

The next provider target is an experimental YouTube-backed music adapter built around [yt-dlp](https://github.com/yt-dlp/yt-dlp). Moodio will use it as a replaceable resolver and streaming dependency behind an app-owned adapter; it will not build an extractor or download tracks.

The current SoundCloud path remains in the codebase as an experimental legacy adapter, but it is no longer the intended discovery or playback direction.

The detailed design, module seams, state model, and contracts live in [ARCHITECTURE.md](ARCHITECTURE.md). The product requirements and acceptance criteria are in [SPEC.md](SPEC.md).

## Current status

Moodio has an early local runtime with:

- an OpenAI Agents SDK station agent and persistent local session
- a station queue, transport controls, transient WebSocket events, and playback lifecycle ingestion
- a browser station console and TTS support
- basic persistence for commands, plays, transcript, and imported listener preferences

The YouTube provider spike, stream proxy, generalized control plane, durable Station feed, autonomous DJ worker, and simple editable listener profile are the next design-led milestones. The v0.2 target will use app-owned file snapshots and a JSONL feed, plus HTTP commands/history and SSE for live UI updates; it will not use ChatKit as its UI foundation.

## Development setup

This repo uses a local Python virtual environment.

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

## Local environment

Use the repo-local `.env` file for model and provider keys so this checkout does not accidentally inherit unrelated keys from `~/.zshrc`.

For OpenRouter-backed station commands:

```bash
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openai/gpt-5.4-mini
MOODIO_AGENT_TIMEOUT_SECONDS=45
```

For OpenRouter TTS:

```bash
OPENROUTER_TTS_MODEL=openai/gpt-4o-mini-tts-2025-12-15
OPENROUTER_TTS_VOICE=alloy
OPENROUTER_TTS_RESPONSE_FORMAT=mp3
```

For direct OpenAI TTS/STT fallback:

```bash
OPENAI_AUDIO_API_KEY=
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=cedar
OPENAI_TTS_RESPONSE_FORMAT=mp3
OPENAI_STT_MODEL=gpt-4o-mini-transcribe
```

When `OPENROUTER_API_KEY` is set, the station agent uses the OpenAI Agents SDK with OpenRouter's OpenAI-compatible Chat Completions endpoint. The default runtime also exposes credential-free read tools for DuckDuckGo-backed web search and Open-Meteo weather snapshots.

## Headless CLI

The local package installs a `moodio` command for running the backend without a browser UI:

```bash
moodio now
moodio transcript
moodio command "play something warmer"
moodio transcribe ./command.wav
moodio serve --host 127.0.0.1 --port 8765
```

The legacy SoundCloud commands remain available for development while that adapter is deprecated:

```bash
moodio embed "https://soundcloud.com/ofmonstersandmen/the-actor"
moodio search "of monsters and men"
```

Set either `SOUNDCLOUD_CLIENT_ID` or `SOUNDCLOUD_OAUTH_TOKEN` before using the credentialed legacy search path.

## Docs

- [Product specification](SPEC.md)
- [Architecture and contracts](ARCHITECTURE.md)
- [UI design prompt](UI_DESIGN_PROMPT.md)
- [Test plan](TEST_PLAN.md)
