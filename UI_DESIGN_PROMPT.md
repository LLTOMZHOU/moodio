# UI Design Prompt

Use this as the prompt for Claude Design.

## Prompt

Design the UI for a personal AI radio / voice DJ product called `moodio`.

Canonical product framing:

A personal radio station shaped by your taste, live context, and an AI DJ, with a lightweight, elegant interface.

Read and follow these repo docs as the source of truth:

- `SPEC.md`
- `ARCHITECTURE.md`

Important framing:

- This is not a generic AI assistant dashboard.
- This is not a normal chat app with music controls bolted on.
- This should feel like a live personal radio station with a named host.
- The host has a persistent on-air identity and speaks between tracks.
- The product name is `moodio`.
- The host name is also `moodio`.
- The product should behave like a desktop music app with an expanded view and a compact collapsed widget state.

Design goals:

- broadcast feel rather than chatbot feel
- calm, editorial, slightly cinematic tone
- music-first experience
- clear live state: `thinking`, `speaking`, `playing`, `recovering`, `offline`
- synced transcript while TTS is speaking
- lightweight user steering through short commands
- default male voice
- spoken interstitials should feel agentic but usually stay under 20 seconds

Make the product feel cohesive, intentional, and production-worthy.

### Product context

The app runtime is an agent-driven music station. It uses:

- durable taste files
- context such as time and weather
- music provider tools
- TTS
- playback queue and transport controls
- a live event stream to the UI

The UI needs to present:

- host identity
- on-air state
- current segment title
- now playing track
- queue summary
- transcript feed
- quick controls
- listener input
- recent memory where useful
- direct favorite control
- talk-density controls that can also be expressed in natural language

### Deliverables

Produce a design spec in markdown with these sections:

1. Product framing
2. Design principles
3. Information architecture
4. Desktop station console
5. Collapsed widget state
6. Shared component system
7. Visual design system
8. Interaction and motion
9. State design for `idle`, `thinking`, `speaking`, `playing`, `recovering`, `offline`
10. Edge cases and failure states
11. Frontend implementation guidance

### Required detail

For the desktop station console, include:

- screen regions
- component hierarchy
- behavior of now-playing controls
- queue display behavior
- how the transcript/live feed works
- how listener input is placed without turning the experience into chat
- how direct favorites and AI-offered favorites coexist
- how "talk less / talk more" appears as both a setting and a natural-language affordance

For the collapsed widget state, include:

- what remains visible when collapsed
- progress and playback controls
- favorite affordance
- expand / restore behavior

For the design system, specify:

- color palette
- type system
- spacing rhythm
- corner radius strategy
- icon style
- waveform / audio visualization approach
- light/dark strategy if both exist

For motion, specify:

- how state changes appear
- speaking animation behavior
- queue and track transition behavior
- loading and recovery behavior

### Constraints

- Avoid generic SaaS dashboard patterns.
- Avoid a full-screen message thread as the primary layout.
- Avoid making the system feel overly technical.
- Preserve a strong sense of "station" and "host".
- The collapsed state should feel like classic desktop music software, not like a generic mini-player.
- The result should be implementable as a desktop-first app shell.

### Output quality bar

Be opinionated. Make concrete design choices. Do not hedge with multiple equally weighted options unless a tradeoff is critical.

Where useful, include:

- annotated wireframe descriptions
- component state tables
- text examples for labels and status copy
- notes for responsive behavior
