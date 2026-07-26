# Music Agent Spec

## Product Definition

Build a personal, long-running AI radio / voice DJ product that feels like a live station, not a chatbot with a play button or a static playlist generator.

Canonical one-line framing:

A personal radio station that grows to understand your taste, follows relevant live context, and keeps programming music through an AI DJ.

The core experience is:

- a named host with a stable on-air identity
- continuous music playback shaped by user taste and context
- short spoken interstitials between tracks or segments
- lightweight listener steering through short commands
- a live interface that shows what is happening now
- durable learning from explicit instructions and observed listening behavior
- autonomous but bounded station upkeep when the queue, clock, or real-world music context calls for it
- DJ-managed scheduled follow-ups that remain visible and bounded

Product defaults:

- product name: `moodio`
- host name: `moodio`
- default voice: male

Implementation note:

- use the latest compatible OpenAI Agents SDK release as the base harness
- extend it with app-owned tools, prompts, hooks, and typed app-control boundaries

## Product Principles

- Broadcast, not chatbot: the default mode is an ongoing station flow.
- Music first: playback and mood steering matter more than open-ended chat.
- Host identity matters: the DJ should feel consistent and editorially intentional.
- Live state matters: users should always understand whether the station is thinking, speaking, or playing.
- Context should shape programming: time, mood, weather, and recent history should influence what happens next.
- Controls should stay light: quick nudges are preferred over complex manual programming.
- Human control wins: direct listener actions must take effect immediately and be visible to the DJ.
- The model chooses; the runtime guarantees: the agent provides editorial judgment while typed controls protect queue and playback correctness.
- Music stays provider-backed: Moodio may cache metadata and taste signals, never download or retain tracks.

## Target User

The initial user is one person running a personal station for themselves from a desktop-first app.

This user wants:

- a station that knows their taste
- low-friction mood steering
- company while working or winding down
- context-aware transitions instead of random shuffle
- visibility into what the station is doing

## Primary Jobs To Be Done

1. Start the station and immediately get something coherent.
2. Let the station continue on its own without constant intervention.
3. Nudge the station with short requests like "warmer", "less vocals", or "talk less".
4. See what is playing and what the host is saying right now.
5. Understand why a track or segment was chosen.
6. Trust that the station remembers durable taste without overfitting to one turn.
7. Ask the station to follow an explicit instruction or working taste note and later inspect, edit, or forget it.
8. Occasionally hear about a relevant new release without having to monitor every favorite artist manually.

## Core Modes

### Radio continue

The default live mode.

Behavior:

- inspect current playback, queue, mood, and context
- decide whether to speak
- decide what to queue next
- keep the station coherent with minimal user input

### User request

A direct response mode for concise user steering.

Examples:

- play something warmer
- less vocals
- what is this song
- why did you pick this
- talk less for a while
- talk more for a while

### Recovery

A system resilience mode.

Used when:

- queue is empty
- playback failed
- TTS failed
- model run failed
- provider data is missing

## Functional Requirements

### Station identity

The system must support a named host persona and durable taste inputs.

Inputs include:

- `taste.md`
- `routines.md`
- `playlists.json`
- `mood_rules.md`
- `persona.md`

### Music playback

The system must:

- search tracks
- let the Listener search provider candidates and directly choose **Play now** or **Queue next** for an exact selection; both validate availability before committing, while Play now records the prior track as skipped only on success and repeated Queue next choices preserve click order ahead of DJ-programmed music
- present direct search as one fuzzy music-search field with Song, Artist, Album, Video, and Playlist result pills
- let Artist, Album, and Playlist results open further provider results rather than queueing them as tracks, with fuzzy-search fallback when richer provider expansion is slow or unreliable
- treat genre, mood, and activity as query formulation and candidate-ranking work, not as promised provider filters
- select tracks
- let the DJ use immediate play only for an explicit Listener request during an active interaction; autonomous programming queues rather than interrupts
- resolve playable sources
- manage queue state
- expose transport controls
- represent the upcoming station program as ordered music and commentary items
- support an immediate direct response outside that program
- keep at least 1-2 upcoming tracks prepared when possible, rather than waiting until the current track fully ends
- use provider-backed playback without downloading or retaining track audio
- reject unavailable candidates before presenting them as playing
- validate the experimental provider against representative song, artist, album, genre, and mood searches before relying on it for the Station

### Spoken interstitials

The system must:

- generate spoken lines between tracks or segments
- render them through TTS
- expose transcript text live in the UI
- let the Listener enable or disable voice rendering of DJ text
- allow a voice response to an active listener request to briefly duck and resume music
- keep autonomous commentary in the upcoming program rather than interrupting music
- associate speech with station state and timing
- keep typical between-track speech under 20 seconds
- allow speech density to be tuned up or down

### Live state

The system must expose at least these states:

- `idle`
- `thinking`
- `speaking`
- `playing`
- `recovering`
- `offline`

### User steering

The system must support lightweight commands from the UI:

- free-text short prompt
- skip
- previous: restart the current track after roughly five seconds, otherwise re-resolve and replay the prior completed track; never silently substitute on provider failure
- pause
- resume
- favorite
- volume

These actions should be split into two categories:

- direct button-driven actions that never require agent reasoning
- natural-language actions that may update agent behavior or trigger agent planning

The MVP button-driven actions are:

- play/pause
- next track
- previous track
- reorder upcoming Music items; anchored commentary follows its target
- remove any upcoming Music item; anchored commentary is removed with its target
- favorite / unfavorite
- expand / collapse widget
- volume

Favorites must work in two ways:

- as a direct non-AI user action
- as an AI-visible capability the host can offer, such as "if you're enjoying this, I can favorite it for you"

### Context awareness

The system should incorporate:

- current time
- weather
- recent plays
- recent user nudges
- routine rules
- explicit listener instructions
- relevant real-world music context, such as a new release by a followed artist

### Memory

The system must distinguish between:

- an editable, plain-language listener profile containing instructions and revisable taste notes
- short-lived conversational context
- recent operational history such as queue and plays

The listener profile may be Markdown or simple JSON. It must remain easy to inspect, edit, reset, and extend; the system does not need a complex preference schema, confidence model, or taste graph. Explicit listener instructions outrank taste notes.

Automatic profile revisions retain a one-sentence reason in revision/event metadata so the UI can show it beside a diff without cluttering the editable profile.

DJ profile updates apply automatically. The interface may show a quiet activity item and must let the Listener open the current profile or a revision diff; it does not require approval or an interruptive alert.

## User Experience Requirements

### Desktop app shell

The product should feel like a desktop music app first, even if implemented with web technology.

The app should support:

- an expanded main window
- a compact widget-like collapsed state

The expanded desktop view should feel like a radio control room.

Required traits:

- persistent station identity
- large ambient time signal
- clear on-air status
- visible now-playing controls
- visible queue or queue summary
- live feed of the host's latest spoken segment
- lightweight listener input
- support a compact collapsed player/widget mode
- clear distinction between direct player controls and AI/natural-language controls

### Tone

The product should feel:

- calm
- editorial
- slightly cinematic
- intentional rather than noisy

It should not feel:

- like a dashboard full of metrics
- like a generic AI chat window
- like a random playlist generator

## Acceptance Criteria For MVP

The MVP is successful if:

- the station can run a coherent `radio_continue` flow for a single user
- the UI clearly shows `thinking`, `speaking`, and `playing`
- the station can speak a short introduction and then play a chosen track
- the user can issue a short steering command and see the station adapt
- the current transcript is visible while TTS is speaking
- favorites work both directly and through AI-assisted confirmation
- the queue usually stays at least one track ahead, and preferably two when provider state allows
- the system can recover safely from missing queue or provider failure

## Non-Goals For MVP

- multi-user support
- social features
- unbounded autonomous web browsing
- complex subagent choreography
- open-ended long-form conversation as the main surface
- downloading, retaining, or redistributing music tracks
- self-modifying prompts or tools without evaluation and review

## Product Risks

- Too much chat behavior will dilute the radio feel.
- Too much automation without clear state will make the system feel opaque.
- Too much UI chrome will weaken the calm, listening-first experience.
- TTS without transcript timing will make the interface feel disconnected from audio.
- Overlong between-track speech will slow the station down and make it feel self-indulgent.

## Open Product Decisions

These do not block architecture, but they should be decided before heavy UI work:

- whether the collapsed widget is always-on-top by default
- whether favorites should affect future recommendations immediately or only after persistence
- whether "talk less / talk more" should be a temporary command, a taste note, or both
