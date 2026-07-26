# Moodio

Moodio is a personal, long-running AI DJ. It maintains one listener's music experience over time while keeping human listening controls authoritative.

## Language

**Listener**:
The person whose taste, instructions, and listening experience a Station serves.
_Avoid_: User, account, customer

**Station**:
The persistent music experience owned by exactly one Listener, including playback, Queue, Listener profile, and DJ context.
_Avoid_: Session, playlist, room

**Queue**:
The ordered Program items the Station has committed to surface after its current item.
_Avoid_: Playlist, recommendations

**Program item**:
One planned item in a Queue, either a Music item or a Commentary item.
_Avoid_: Track, message

**Music item**:
A Program item referring to an Available candidate that the Station intends to play.
_Avoid_: Download, file

**Commentary item**:
A Program item containing DJ editorial content for a natural point in the Station program.
_Avoid_: Direct response, notification

**Anchored Commentary**:
A Commentary item optionally tied as a lead-in to one upcoming Music item. It moves or is removed with that Music item.
_Avoid_: Required commentary, previous-track annotation

**Direct response**:
The final DJ answer to a Listener during an Active interaction; it does not enter the Queue.
_Avoid_: Commentary item, chat history

**Active interaction**:
The bounded period in which the Listener has directly asked or acted on the Station and expects a response.
_Avoid_: Background job, scheduled run

**Active listening window**:
A period beginning when Station playback starts and ending on an explicit Listener pause. It permits at most one low-priority editorial pulse per hour, whether or not the UI remains open.
_Avoid_: Open browser tab, background process

**Voice mode**:
A Listener-controlled UI setting that determines whether DJ text is also rendered as speech.
_Avoid_: DJ instruction, agent tool

**Station task**:
A persisted plain-language DJ intention with a next run time or recurrence for one Station.
_Avoid_: Cron job, background process

**Station session**:
The one continuous, compacted DJ conversation associated with a Station and shared by its bounded runs.
_Avoid_: Process, task, profile

**Profile revision**:
An immutable full-text snapshot of the Listener profile with its parent, source, and concise reason. Diffs are derived between snapshots; restoring one creates a new revision rather than mutating history.
_Avoid_: Notification, approval

**Station command**:
An intentional request from a Listener or the DJ to change one Station's playback, Queue, or settings.
_Avoid_: Event, suggestion

**Pending control**:
A browser-local visual acknowledgement of a direct Listener control before the Station controller confirms or rejects it. It is never durable Station state.
_Avoid_: Optimistic Queue, source of truth

**Recovering playback**:
The Station state after a server restart while the browser player's actual state is not yet known, or its reported track does not match the persisted current item. The Queue is retained, but playback is not assumed to have resumed and history is never inferred from a mismatch.
_Avoid_: Playing, automatic resume

**Station event**:
An immutable, app-owned fact about a Station change or meaningful player/scheduler observation. It is not raw tool telemetry.
_Avoid_: Log entry, Listener message

**Internal Station-event item**:
A compact, invisible, model-facing rendering of a meaningful Station event, retained in the Station session as application context. It is not a Listener message and does not invoke or require a DJ response.
_Avoid_: Chat message, feed card, raw event log

**Station feed**:
The Listener-facing, ordered projection of relevant Station events and Direct responses. Meaningful Listener controls appear as quiet activity cards, never chat bubbles; the UI decides other event presentation.
_Avoid_: Chat transcript, agent trace

**Listener message**:
Natural-language input intentionally sent to the DJ as a conversation turn.
_Avoid_: Button click, control event

**DJ**:
The agent that proposes and makes bounded Station changes in service of a Listener.
_Avoid_: Controller, player

**Listener profile**:
The Listener's editable, harness-owned plain-language notepad: their instructions, working taste notes, and recent meaningful signals.
_Avoid_: Preference graph, taste model

**Listener instruction**:
An explicit rule in the Listener profile that the DJ must follow when it applies.
_Avoid_: Preference, hint

**Taste note**:
A revisable plain-language conclusion about the Listener's current musical taste.
_Avoid_: Fact, permanent preference

**Music provider**:
An external service or resolver that supplies a catalogue and currently available playback for a Candidate.
_Avoid_: Music library, archive

**Available candidate**:
A Candidate that a Music provider has just confirmed it can serve in the Listener's current context.
_Avoid_: Download, cached file

**Listener selection**:
An Available candidate the Listener directly chooses to Play now or Queue next without DJ approval. Both validate availability before committing and revalidate near playback. Play now then records the interrupted Music item as skipped and does not reinsert it, while on failure it preserves current playback. Queue next appends in click order to the Listener-priority segment after the current item without changing transport.
_Avoid_: Recommendation, DJ choice

**Search result**:
A fuzzy provider match shown to the Listener, classified as music, artist, album, video, or playlist.
_Avoid_: Guaranteed playable track

**Browse result**:
An artist, album, or playlist Search result that opens further provider results instead of entering the Queue.
_Avoid_: Listener selection, Music item

## Relationships

- A **Listener** owns exactly one local **Station** in v0.2.
- A **Station** belongs to exactly one **Listener** and is identified by a `station_id`, even though v0.2 provisions only one local Station.
- A **Station** has one **Queue**.
- A **Queue** contains ordered **Program items**.
- Each **Program item** is either one **Music item** or one **Commentary item**.
- A **Commentary item** may be **Anchored Commentary** or remain unanchored for a general transition.
- A **Direct response** does not change the **Queue**.
- A voice-rendered **Direct response** during an **Active interaction** may briefly duck and resume Music; a **Commentary item** does not interrupt Music.
- **Voice mode** controls rendering, not what the DJ writes.
- A **Commentary item** is consumed at its natural transition even when **Voice mode** is off; its text is shown without delaying the next Music item.
- A **Commentary item** is optional editorial programming, not a required cadence; silence is normal when it adds nothing.
- A **Commentary item** is delivered only after normal Music completion; direct transport intervention suppresses waiting Commentary.
- A **Station task** wakes one bounded DJ run and may be created, revised, or cancelled by the DJ.
- v0.2 runs the scheduler only while the local Moodio service is running; startup coalesces overdue task and operational work into one catch-up DJ run.
- A Station has harness-owned queue-health/recovery triggers and at most one low-priority editorial pulse per **Active listening window** hour; a **Station task** adds DJ-managed follow-up work rather than replacing those baseline triggers.
- While paused, the DJ may safely append Music items after Listener choices for any relevant reason, including queue health or a relevant release, but may not resume transport, reorder/replace Listener choices, or surface audible Commentary.
- A **Station** has one **Station session**; Listener messages and DJ tasks continue it without becoming separate agents.
- A **Station** runs one serialized DJ lane: a **Listener message** outranks scheduled or operational work, which is deferred or coalesced when it has not started.
- An already-started bounded DJ run finishes rather than being cancelled mid-mutation; direct Listener controls still execute immediately, and the waiting **Listener message** runs next.
- Background DJ runs have a configurable short wall-clock budget (initially about 20 seconds), checked between model and tool steps; a later trigger continues work that did not fit. Listener-requested runs have a looser budget.
- A Listener profile change creates a **Profile revision** that the Listener may inspect or restore without approving the change first.
- A **Profile revision** is append-only and stores the whole editable profile so its diff remains available even when later revisions change the profile again.
- Restoring a **Profile revision** writes a new child revision with the restored text; it never rewrites prior profile history.
- An automatic **Profile revision** stores its one-sentence reason in revision/event metadata, not in the editable Listener profile text.
- A **Station command** is serialized for one **Station** and produces one or more **Station events**.
- A **Pending control** may make a direct Listener action feel immediate, but the controller-confirmed Station snapshot always wins.
- A Listener-originated **Station command** takes precedence over an overlapping DJ-originated command.
- A DJ Queue command is conditional on the Queue revision it inspected. A stale command is rejected; it may make one fresh append-only attempt only if the Queue still needs help.
- `get_queue()` provides Queue revision, playback/current-item state, and ordered upcoming Program items with type, origin, and anchor relationship; it excludes provider URLs and raw event history.
- Operational context is exposed through focused tools such as `get_playback_state()`, `get_queue()`, profile, event, and task tools; there is no generic Station-state dump.
- The DJ may use `play_now` only for an explicit immediate-play request during an **Active interaction**; autonomous programming only queues.
- A direct Listener control is a **Station command**, not a **Listener message**. Its meaningful resulting **Station event** is written immediately and rendered as an **Internal Station-event item** at the next safe Station-session boundary for a later DJ run.
- Only a **Listener message** enters the **Station session** as a user conversation turn.
- Cosmetic controls, such as volume and seek, do not create **Internal Station-event items**.
- A **Station** uses one editable **Listener profile** as durable context.
- A **Listener instruction** outranks a **Taste note** when they conflict.
- The DJ may revise a **Taste note** during any relevant bounded run when it has a concise, revisable explanation; a single favorite, removal, or other isolated action is evidence, not an automatic durable conclusion.
- Recurring artist-release interest is represented by a simple **Listener profile** note or **Station task**, not a separate followed-artist model in v0.2.
- A relevant release is ordinary DJ programming: it may append if it fits the Listener and current Queue, but never interrupts or notifies merely because it is new.
- Release research creates a visible Station-feed card only when it changes the Queue or Listener profile; no-op checks remain internal.
- A **Station** queues only an **Available candidate** from a **Music provider**.
- A **Listener selection** is applied through the same Station command path as a DJ-selected Music item, with explicit **Play now** or **Queue next** intent.
- The Listener-priority segment preserves **Queue next** click order; the DJ may not interpose Music items there, and Anchored Commentary moves with the displaced target.
- The Listener may reorder upcoming Music items; **Anchored Commentary** moves with its target and unanchored Commentary is not independently reordered in v0.2.
- The Listener may remove any upcoming Music item; its **Anchored Commentary** is removed too, and the resulting meaningful event may inform later DJ programming.
- **Previous** restarts the current Music item after roughly five seconds of play; otherwise it re-resolves and replays the preceding completed Music item, or reports it unavailable without substitution.
- `queue_commentary` accepts an optional upcoming `for_music_item_id`: omitted is a general transition, supplied creates **Anchored Commentary**.
- A **Search result** may be an Available candidate or a **Browse result**.
- A **Browse result** never enters the Queue directly.
- **Discovery preferences** are small, caller-visible search preferences rather than a provider query language: music-first duration ranking is the default; a duration cap is explicit; recency is best-effort and may be unknown.
- Search normally down-ranks results longer than roughly 30 minutes, but that is a preference rather than a hard limit when a mix, ambience, DJ set, or extended session is wanted.

## Example dialogue

> **Dev:** "The Listener paused the Station. Should the DJ start another track?"
> **Domain expert:** "No. The DJ serves that Station; it must respect the Listener's direct control."

> **Dev:** "The DJ finished looking for tracks after the Listener selected an album. Can it replace the Queue?"
> **Domain expert:** "No. Its result is stale; it may only add suitable tracks after the Listener's choices if the Queue still needs them."

> **Dev:** "The Listener skipped three songs at a party. Is that a permanent Taste note?"
> **Domain expert:** "No. It is a signal the DJ may consider, but durable context stays revisable and understandable to the Listener."

> **Dev:** "The DJ has a useful thought about the next song. Is that a Direct response?"
> **Domain expert:** "No. Unless the Listener asked it directly, it is a Commentary item and waits in the Queue for a natural transition."
