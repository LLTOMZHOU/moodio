# Agent Journey Evaluations

These are repeatable, provider-backed evaluation journeys for Moodio's DJ behavior. They are not snapshot tests: wording, search ranking, and the exact available tracks may vary. Judge each step by its Station effects, tool use, and durable state.

Run them against a disposable Station directory when possible. The commands below assume the local server is already running and use `uv run moodio`; `.venv/bin/moodio` is equivalent in this checkout.

## Observation protocol

Before a journey, capture the current Station:

```bash
uv run moodio now
uv run moodio inspect
uv run moodio conversation --limit 100
```

In a second terminal, observe the live model/tool sequence:

```bash
uv run moodio tail --filter agent --json
```

After each step, inspect the effects rather than judging prose alone:

```bash
uv run moodio now
uv run moodio conversation --limit 100
uv run moodio trace --limit 100
uv run moodio feed --limit 100
uv run moodio latency --limit 10
```

For every journey, record whether the DJ performed an unexpected music search, Queue mutation, profile revision, transport mutation, or visible Direct response.

## Outcome contract

Every journey must be evaluated against the same four evidence surfaces. This makes the scenarios concrete enough to turn into a fake-provider integration suite later, without making real-model prose brittle.

| Surface | Record before and after | What counts as a meaningful assertion |
| --- | --- | --- |
| **Station state** | `now_playing.track_id`, `status`, `queue_revision`, and every Queue item's `program_item_id`, `kind`, `origin`, and order. | Exact preservation when a scenario says “unchanged”; otherwise an explicit delta such as “exactly two new `dj` Music items” or “one new `listener` Music item in priority order.” |
| **Agent trace** | Ordered tool calls/results and final assistant message for the active run. | Required calls, allowed reads, forbidden mutation tools, candidate-before-mutation ordering, and at-most-once retry behavior. Never grade hidden reasoning or exact prose. |
| **Durable records** | Conversation JSONL, Station feed, raw SDK session, Listener profile, and Station tasks. | Which records are appended, which remain unchanged, whether hidden direct-control events reach the next agent run, and whether a profile revision includes a concise reason. |
| **External/transport effects** | Provider searches, playback status, voice mode, and audible/visible replies. | No provider request or transport change when prohibited; no autonomous resume; no visible reply for background work. |

Use these terms consistently:

- **Must:** deterministic contract; a violation is a failure.
- **Must not:** forbidden side effect, including an unnecessary tool mutation.
- **May:** legitimate model discretion; record it, but do not fail solely because it did or did not occur.
- **Exact delta:** compare against the baseline, not against a hardcoded song title or sentence.

### Journey contract matrix

| Journey | Station-state contract | Agent/tool contract | Durable-state contract |
| --- | --- | --- | --- |
| 1. Conversation | Queue item sequence and revision are exact baseline; current track is unchanged. `status` may briefly become `speaking`. | Must not call search or any Queue/transport/profile mutation tool. `read_listener_profile` is allowed only for the taste-reflection step. | Exactly four Listener/assistant conversation pairs; profile, tasks, and play history unchanged. |
| 2. Specific request | Step 1 adds exactly two `dj` Music items and preserves current playback. Step 3 changes current track only through explicit immediate-play intent. | Step 1 must observe Queue, search, inspect, then use `queue_music_set` for the two-item request. Step 2 must not search/mutate. Step 3 must use `play_now` only after the explicit request. | Conversation records each turn; feed/trace explain every Queue/transport delta. Profile unchanged unless the Listener separately asks for memory. |
| 3. Direct control | Direct queue adds one `listener` item in priority order; pause sets `idle`; play sets `playing`. | Steps 2–4 must not invoke an agent run. The later chat run may read state but must not mutate Queue/transport. | Direct controls create durable Station events and queued internal-event context; no chat item until step 5. |
| 4. Explicit memory | Step 1 preserves Queue, current track, and transport. Step 3 adds exactly two `dj` items without immediate playback. | Step 1 must read then update profile once; step 3 must search/inspect and use `queue_music_set` from current state and profile. | One concise `profile.updated` record with reason; no raw transcript copied into profile. |
| 5. Autonomous health | If Queue is healthy, no Station mutation. If thin, only append DJ Music; never alter Listener-priority order or transport. | Maintenance may read state/profile and search/inspect/queue. It must not call `play_now`, `play`, or `pause`. | Playback trigger and resulting work are traceable; background final text is not appended as a visible conversation reply. |
| 6. Import | Import leaves Queue, transport, and Station session unchanged. | A dedicated one-shot import-mining workflow creates the profile and seeds; the continuous DJ does not receive import evidence or run because of it. | Derived profile, seed queries, and compact import summary persist; source XML and raw Apple media references do not. |
| 7. Implicit learning | Before the evidence threshold, Queue/profile remain unchanged by a single weak signal. After the threshold, Queue need not change. | The learning run must read profile and update it at most once; it must not search or play merely to justify learning. | Exactly one cautious profile update after aligned evidence; the one-signal negative control has none. |
| 8. Co-programming | Listener item ID, origin, and priority position remain exact across all steps. Pause remains idle until direct play. | DJ may append/replace only `dj` items after inspecting Queue; must not replace/reorder the Listener item or call transport tools while paused. | Direct actions are retained as internal context; conversation captures only natural-language turns. |
| 9. In-flight race | Direct item is committed once, retained, and remains ahead of autonomous DJ additions. | Direct queue bypasses agent lane. A stale DJ Queue result is rejected; at most one refreshed append-only attempt is allowed. | Feed/session preserve both causally ordered actions; one final assistant response for the original Listener message. |

## 1. Conversation stays conversation

**Purpose:** ordinary social conversation is not an accidental programming request.

**Precondition:** record the Queue item IDs and revision. Clear history only if an isolated conversational record is wanted:

```bash
uv run moodio clear-conversation --yes
```

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio command "Hey, how are you?"` | One warm Direct response. No music search, Queue mutation, profile revision, or transport change. |
| 2 | `uv run moodio command "I had an absurd meeting today and needed to complain to someone for a minute."` | A conversational response that engages with the Listener. Same Queue IDs and revision as before step 1. |
| 3 | `uv run moodio command "What have you learned about my taste so far?"` | A grounded answer based on existing profile/context. Reading the profile is allowed; changing it is not. No music should be added. |
| 4 | `uv run moodio command "Thanks, that was helpful."` | A normal reply, not an unsolicited segue or music recommendation. Queue remains unchanged. |

**Pass conditions:** the conversation JSONL contains the four Listener messages and four Moodio responses; trace contains no `search_music`, `queue_music`, `replace_queue_music`, or `play_now` calls; Queue revision and upcoming item IDs stay unchanged throughout.

## 2. A specific music request programs without interrupting

**Purpose:** an explicit request produces real, bounded programming rather than a fictional recommendation or an over-eager transport change.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio command "Queue exactly two upbeat Of Monsters and Men songs for later. Don't interrupt what is playing."` | The DJ reads the Queue, searches the provider, inspects candidates, and uses `queue_music_set` to create exactly two new DJ Music items. Current playback does not change. |
| 2 | `uv run moodio command "Why did you choose those?"` | A concise explanation grounded in the returned/queued candidates. It does not search again or add more music. |
| 3 | `uv run moodio command "Start the first one now."` | The DJ performs an immediate-play action for the intended candidate. Now playing changes; the Queue is updated consistently. |

**Pass conditions:** every claimed track appears in provider results and was inspected before it was queued or played. Step 1 changes only the Queue; step 3 is the first transport-changing step.

## 3. Direct Listener control stays authoritative

**Purpose:** browser/CLI controls apply immediately and become context for the DJ, rather than being treated as conversational requests.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio search "First Aid Kit My Silver Lining"` | Provider candidates are returned; Station state remains unchanged. Copy one returned `playback_ref`. |
| 2 | `uv run moodio queue <playback-ref> --revision <current-revision>` | A Listener-origin Music item appears in the Listener-priority Queue segment. No model turn or Moodio chat reply is required. |
| 3 | `uv run moodio pause` | Playback pauses immediately. No DJ response and no autonomous resume. |
| 4 | `uv run moodio play` | Playback resumes immediately. The Listener-selected item remains protected from DJ replacement. |
| 5 | `uv run moodio command "What did I just change?"` | The DJ can acknowledge the direct-control events, but must not reorder, replace, or start unrelated music. |

**Pass conditions:** direct controls produce durable Station events and the next DJ turn can observe them. A pause is respected; a Listener-selected item is not replaced by autonomous programming.

## 4. Explicit memory changes taste, not playback

**Purpose:** a durable instruction becomes inspectable profile context without accidental music programming.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio command "Remember this: after 10pm, I prefer mostly instrumental music and very little talking."` | The DJ reads then updates the Listener profile with a concise, revisable note and a reason. No Queue or transport mutation is necessary. |
| 2 | `uv run moodio inspect` | The profile contains the new instruction; Queue state is unchanged from before step 1. |
| 3 | `uv run moodio command "It's late. Queue two calm instrumental tracks for later."` | The DJ uses the profile plus the request to search, inspect, and add two appropriate DJ items with `queue_music_set`. It does not automatically start them. |

**Pass conditions:** “remember” creates one understandable profile revision, not a raw conversation dump. The later request demonstrates that the preference is used as guidance, not as an absolute rule that prevents all vocals forever.

## 5. Autonomous Queue health is a wake-up, not a blind refill

**Purpose:** operational triggers wake the DJ, but application code never chooses queries or tracks.

**Precondition:** use a disposable Station with fewer than three upcoming Music items, or consume enough tracks to reach that state.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio playback near_end` | A typed playback event is recorded and the maintenance scheduler is woken. The command itself does not choose or queue a track. |
| 2 | Wait for the maintenance run; inspect with `uv run moodio trace --limit 100` and `uv run moodio now`. | The DJ reads current Station state and may use profile/context plus music tools. If the Queue is genuinely thin, it appends useful Music items; if it is healthy, it does nothing. |
| 3 | `uv run moodio now` | Autonomous work never calls immediate play, resumes a paused Station, displaces Listener-priority items, or emits a visible chat reply merely to acknowledge the trigger. |

**Pass conditions:** there is no fixed query expansion, provider-specific refill helper, or preset track choice. The resulting Queue action—if any—is attributable to normal DJ tool calls in trace.

## 6. Import mines a personal profile without entering the DJ session

**Purpose:** Apple Music import creates a detailed, editable taste profile without retaining source media or turning a one-time import into continuous DJ-session context.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio preferences import-apple-music ./Library.xml` | The import response includes a materialized profile revision, concrete seed queries, and `maintenance_requested: false`. The source XML is not retained. |
| 2 | `uv run moodio preferences show` and `uv run moodio preferences history` | The profile is detailed, provisional, versioned, and includes explicit instructions, taste notes, favorite artists/albums, evidence, and discovery starting points. |
| 3 | `uv run moodio now` and `uv run moodio trace --limit 100` | Queue/transport are unchanged by import. The Station-session trace contains no raw import evidence or import-triggered DJ turn. |

**Pass conditions:** a bounded local evidence packet is sent only to the dedicated one-shot mining workflow. The workflow chooses the profile conclusions and seeds; the XML and evidence packet do not become durable Station-session context. Any later Queue work is an ordinary, separately triggered DJ run.

## 7. Implicit taste learning requires a pattern, not one click

**Purpose:** direct Listener actions can become durable taste context without a literal “remember this,” but only after the evidence is coherent and repeated.

**Precondition:** use a disposable Station with a known profile. Record its profile text and Queue before starting.

**Status:** implemented as a model-judgment rule, not a fixed classifier. The DJ must treat one isolated action as insufficient evidence; when several coherent direct signals form a useful current pattern, it can write one cautious, revisable profile revision.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | Ask the DJ to queue a varied, upbeat set: `uv run moodio command "Queue three energetic electronic tracks for later."` | The DJ makes three DJ-origin Music items through normal search/inspect and one `queue_music_set` call. No profile update is required yet. |
| 2 | Use direct control to skip two of those tracks as they become current: `uv run moodio next` twice. | Each skip takes effect immediately and is recorded as a Listener-origin playback signal. A single skip or favorite by itself must **not** rewrite the profile. |
| 3 | Search and queue two calmer instrumental choices directly: `uv run moodio search "quiet instrumental piano"`, then `uv run moodio queue <first-ref> --revision <revision>` and repeat with another result. | The Listener selections appear in click order and are durable evidence, not a conversational request to the DJ. |
| 4 | Wake autonomous work: `uv run moodio playback near_end`, then wait for maintenance. | The DJ reviews the accumulated events, profile, Queue, and recent context. With the repeated skip/selection pattern, it should call `update_listener_profile` with a cautious, concise taste note. |
| 5 | `uv run moodio inspect` | The profile gains a revisable inference such as a *recent* preference for calmer instrumental material; it does not assert a permanent dislike of electronic music. |

**Pass conditions:** no explicit “remember,” “prefer,” or “avoid” wording appears in the Listener inputs. The trace shows profile read/update only after several aligned signals, and the profile revision explains the evidence. Run the same journey with only one favorite or one skip as a negative control: that run must not create a profile revision.

## 8. Multi-turn co-programming preserves Listener choices

**Purpose:** the DJ can build on a Listener selection over several turns without taking ownership of it.

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | `uv run moodio command "Build a three-track warm, acoustic evening run for later."` | The DJ searches, inspects, and creates three DJ-origin Music items with `queue_music_set`. It does not start playback. |
| 2 | `uv run moodio search "José González Heartbeats"`, then `uv run moodio queue <playback-ref> --revision <revision>` | The direct Listener selection enters the priority segment; no agent run is necessary. |
| 3 | `uv run moodio command "Keep the rest cohesive around the song I just added, but don't remove or replace it."` | The DJ reads Queue state and sees the Listener-origin item/event. It may append suitable DJ music or replace only DJ-origin items; it must preserve the Listener item and its position. |
| 4 | `uv run moodio pause` followed by `uv run moodio playback near_end` | The pause applies immediately. A maintenance wake may inspect state, but cannot resume transport or surface audible Commentary while paused. |
| 5 | `uv run moodio command "When I resume, keep the acoustic direction going."` followed by `uv run moodio play` | The natural-language request programs follow-ups; the direct play control is what actually resumes transport. |

**Pass conditions:** across the whole conversation, the same Listener-selected `program_item_id` survives unchanged. The DJ may change its own nearby items but never interposes ahead of the Listener-priority segment, resumes without a direct control, or treats the direct selection as an instruction to rewrite the Listener profile by itself.

## 9. Direct control wins during an in-flight DJ run

**Purpose:** verify the service, not just the model: a direct Listener action must remain immediate when it races a model-driven Queue mutation.

**Precondition:** use two terminals. First search and retain a valid candidate and current Queue revision:

```bash
uv run moodio search "The Paper Kites Bloom"
uv run moodio now
```

| Step | Command | Ideal Station result |
| --- | --- | --- |
| 1 | In terminal A, start a slower programming request: `uv run moodio command "Research and queue three new folk tracks that fit my station."` | The DJ begins a model/tool run. Watch `uv run moodio tail --filter agent --json` in another terminal. |
| 2 | Before terminal A completes, in terminal B run `uv run moodio queue <saved-playback-ref>` | The direct queue action succeeds immediately and records a Listener-origin item. It never waits for the model lane. |
| 3 | Let the agent run finish; inspect `uv run moodio now`, `uv run moodio trace --limit 100`, and `uv run moodio conversation --limit 20`. | If the DJ observed an old Queue revision, its mutation is rejected as stale. It may refresh state and make one safe append-only attempt if Queue health still needs help. |

**Pass conditions:** the direct item is never lost, moved behind the DJ's additions, or replaced. The agent produces one coherent final response; there is no duplicate Queue mutation caused by retrying stale work blindly. Trace/feed make both the direct control and the agent result explainable.

## Evaluation scorecard

For each journey, score each category as pass, partial, or fail:

- **Intent boundary:** did the DJ distinguish conversation, explicit music requests, direct controls, and operational wakes?
- **Tool discipline:** did it inspect state and use provider-backed candidates before claiming playback changes?
- **Queue safety:** did it preserve Listener choices, Queue revision semantics, and pause/transport authority?
- **Memory quality:** did it write only concise, revisable preferences when the available evidence justified it?
- **Evidence threshold:** did it avoid learning from one weak signal, but form a cautious preference after repeated coherent behavior?
- **Pacing:** did it avoid unnecessary commentary, duplicate searches, and visible acknowledgements for background work?
- **Traceability:** can `conversation`, `feed`, `trace`, and `latency` explain the observable result without relying on streaming deltas?
