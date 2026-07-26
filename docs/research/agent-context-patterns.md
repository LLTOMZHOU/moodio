# Context patterns for a long-running tool-using agent

**Scope:** how to present changing application state and durable memory to one
long-running LLM agent. This report uses only first-party framework documents
and source-linked documentation, checked 2026-07-25. “Persisted” below means
the framework/application's conversation or memory store—not provider logging
or retention settings.

## Short conclusion

There is no single universal “agent context” mechanism. The common architecture
is a **separation of ledgers**:

1. a durable application source of truth (state, events, tasks, profile);
2. a bounded conversation/session history for the model's working continuity;
3. a deliberately curated view of (1) and (2) for each inference.

The useful choice is therefore not *snapshot or tool* globally. It is which
facts must be present before the first model decision, which can be retrieved
on demand, and which deserve durable semantic memory. Anthropic explicitly
describes a hybrid of up-front retrieval plus autonomous exploration; its
Claude Code example loads small instruction files up front and uses search
tools just in time. [Anthropic: Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

## What the Agents SDK actually distinguishes

The Agents SDK's `context` object is local application state: tools and hooks
can use it, but it is **not sent to the LLM**. To make data model-visible, the
SDK documents four routes: instructions, run input, function tools, or
retrieval/web search. [Agents SDK: context management](https://openai.github.io/openai-agents-python/context/)

With an SDK session, the runner prepends retrieved session history to each new
turn; after the run it stores new user input, assistant responses, and tool
calls/results. This is working conversation history, not an application-state
database. [Agents SDK: session behavior](https://openai.github.io/openai-agents-python/sessions/#core-session-behavior)

## Patterns

| Pattern | What reaches the model | What becomes durable conversation history | Strength | Principal risk |
| --- | --- | --- | --- | --- |
| 1. Dynamic instruction snapshot | A freshly rendered instruction/developer section, usually alongside stable policy | Not a new session item; the local context object is never sent directly | Immediate and reliable | Repeated tokens; a large snapshot can crowd out the task |
| 2. Tool-first retrieval | Tool schema first; current state arrives only after the model calls it | Tool call and result from the run | On-demand detail and an audit trail | Extra round trip; a model can omit or misuse the read |
| 3. Event/history injection and curation | Selected events or a summary are placed in input/history | New injected turn items persist; selected old history does not get re-persisted | Preserves useful chronology | Fake “user” events and stale history can confuse the agent |
| 4. Durable notes / long-term store | A small note is loaded or read on demand | Separate memory/profile store, not necessarily the transcript | Survives compaction; keeps long-term facts compact | Notes can become stale or overgeneralized |
| 5. Application-state/checkpoint boundary | The application owns state; the model sees it only through one of the above interfaces | State snapshots/events are separate from chat history | Clear authority, recovery, and human/agent concurrency | Requires explicit interface design rather than treating chat as state |

### 1. Dynamic instruction/system snapshots (“push”)

An agent may use a static instruction string or a dynamic instruction function
that receives local run context and returns a prompt. The SDK presents this as
the normal route for data that is always useful, such as a name or date.
[Agents SDK: dynamic instructions](https://openai.github.io/openai-agents-python/agents/#dynamic-instructions)

**Sent:** the rendered text is included as model instructions for that run.
**Persisted:** the SDK session documentation says it persists the run's new
items; a dynamic instruction is not passed as a new input item. The local object
from which it was rendered is never model-visible by itself. This makes an
instruction snapshot the clean way to show current facts without creating a
fake user turn. [Agents SDK: context and session behavior](https://openai.github.io/openai-agents-python/context/) · [Sessions](https://openai.github.io/openai-agents-python/sessions/#core-session-behavior)

**Best fit:** a short run contract that must be obeyed before the first tool
call: run mode, trigger, response-channel policy, current revision, or a small
durable instruction/profile. It is a poor fit for a full event log or queue.

### 2. Tool-first state retrieval (“pull”)

The base instructions require or encourage a `get_station_context()` tool. The
model calls it, receives a structured snapshot, and then decides. The Agents
SDK explicitly identifies function tools as the route for on-demand context.
[Agents SDK: agent/LLM context](https://openai.github.io/openai-agents-python/context/#agentllm-context)

**Sent:** the tool schema is present from the start; state is sent only in a
tool result after the call. **Persisted:** with a session, the tool call/result
is one of the new run items automatically saved, so it may form a useful
chronology of observations. [Agents SDK: core session behavior](https://openai.github.io/openai-agents-python/sessions/#core-session-behavior)

**Best fit:** current queue, now-playing, recent meaningful events, tasks, and
the full profile. Return a compact structured object with a `station_revision`.
Treat its result as authoritative only for that observation; old tool results
in a persistent session are historical evidence, not current state.

### 3. Event/history injection, selection, and compaction

This is two related techniques that should not be conflated:

- An application can add an event as **new run input**. It then becomes a
  conversation item, and is persisted with the turn. This is appropriate only
  when it genuinely is a model-facing message/trigger, not for every UI click.
- It can curate **existing history** before a call. `session_input_callback`
  receives retrieved history and new input and returns the list sent to the
  model; filtering/reordering old history does not save those old items again.
  [Agents SDK: custom session input](https://openai.github.io/openai-agents-python/sessions/#control-how-history-and-new-input-merge)

For long-lived sessions, compaction is a third form of curation. The Agents SDK
offers a compaction wrapper that clears and rewrites its underlying session
history; it notes that automatic compaction can delay streamed completion.
[Agents SDK: compaction sessions](https://openai.github.io/openai-agents-python/sessions/#openai-responses-compaction-sessions)
Anthropic likewise frames compaction as summarizing a near-limit conversation
into a new context, and recommends discarding redundant old tool output.
[Anthropic: long-horizon context](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

**Best fit:** genuine listener text and DJ tool activity stay in the session;
compact them at a generous threshold. Do not inject raw direct-control events
as disguised listener messages. A small selected event window may be returned
by the state tool instead.

### 4. Durable notes / a long-term memory store

This is distinct from transcript summarization. Anthropic's memory tool stores
files under application-controlled storage and supports just-in-time retrieval,
so the model need not retain all learned material in its context window.
[Anthropic: memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
Anthropic also describes structured note-taking as persisted memory that is
pulled back later, alongside compaction rather than as a replacement for it.
[Anthropic: structured note-taking](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

LangGraph makes the same separation explicit: checkpointers hold thread-scoped
state, while Stores hold application-defined, cross-thread facts such as user
preferences. [LangGraph: persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

**Best fit:** Moodio's editable Listener profile/instructions and perhaps a
small task/reflection note. Keep it readable and scoped. It should not be an
opaque append-only transcript, a confidence graph, or an excuse to put the
authoritative live queue in memory.

### 5. Application state separate from chat (“two-ledger”)

LangGraph's checkpoint/store split is a concrete framework example of the
broader pattern: state snapshots belong to a thread/checkpointer and durable
facts to a separate store, rather than both being inferred from messages.
[LangGraph: checkpointer vs. store](https://docs.langchain.com/oss/python/langgraph/persistence/#checkpointer-vs-store)
Its tools can also receive state, immutable run context, and a persistent store
through a runtime object that is hidden from the LLM tool schema. [LangChain:
tool runtime](https://docs.langchain.com/oss/python/langchain/tools/#access-context)

For a Station, this means the controller/files are authoritative. A session is
never allowed to resurrect playback, overwrite a manual queue choice, or infer
current transport from an old assistant message. The model observes the Station
through a deliberately bounded dynamic header and/or tool, while direct UI
commands take their deterministic controller path.

## Recommendation for one persistent DJ Station

Use a hybrid of patterns **1, 2, 4, and 5**; use pattern 3 only for genuine
conversation and compaction.

1. Keep stable DJ policy in the base instructions: controller authority,
   direct-response rules, and no acknowledgement of direct controls.
2. Render a *tiny* dynamic header for every run: `mode`, `trigger`,
   `response_policy`, and `station_revision`. This prevents an autonomous run
   from behaving as though it were listener chat, without injecting a fake
   message.
3. Make `get_station_context()` the first planning tool. It returns current
   playback/queue, a compact recent-event window, task state, and the profile
   (or lets the agent read the profile separately). It records the agent's
   actual observation in session history.
4. Keep the Station snapshot, event feed, and Listener profile outside the
   session as durable application data. UI controls append domain events after
   the immediate controller mutation; they do not automatically start an agent
   turn or become a `user` message.
5. Preserve only real listener text, agent replies, and tool activity in the
one shared conversation session. Compact it when needed. Retain high-value
taste conclusions in the readable profile, because compaction is necessarily
lossy.

## Follow-up experiment: role for hidden Listener actions

Moodio's initial projection of a meaningful direct Listener action is a hidden
`developer`-role message, because the action is trusted application context
rather than a conversational request. This is a harness hypothesis, not a
settled semantic fact. Compare it with a hidden `user`-role item explicitly
labelled as a non-conversational Listener action, using the same Station-event
fixtures. Measure whether the DJ uses the action correctly, produces unwanted
acknowledgement, chooses appropriate tools, and behaves consistently across
the selected OpenAI-compatible model/provider. The durable Station feed stays
the source of truth in both cases.

This keeps the valuable “state changed over time” trail, but gives it the right
meaning: the chronological Station feed is the audit/source-of-truth record;
tool results are observations; and the conversation session is continuity—not
the Station database.

## Sources

- [OpenAI Agents SDK: Context management](https://openai.github.io/openai-agents-python/context/)
- [OpenAI Agents SDK: Sessions](https://openai.github.io/openai-agents-python/sessions/)
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [LangGraph: Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangChain: Tool runtime/context access](https://docs.langchain.com/oss/python/langchain/tools/#access-context)
