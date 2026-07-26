# ChatKit and transport research

**Scope:** Moodio's single-listener, long-running Station UI. Checked 2026-07-25. Sources are limited to official OpenAI ChatKit and Agents SDK documentation. Facts below are cited; recommendations are explicitly marked as inference.

## Short answer

ChatKit is a capable **drop-in chat surface**: it has persisted thread items, structured widgets, actions, progress, and an SSE stream. It can sit beside a player, but it is not a clean fit as Moodio's primary Station feed: Moodio needs a bespoke player/program surface, independent human controls, and background station events that are not inherently a chat turn. Use it only if we want to adopt its chat/thread model and widget vocabulary; otherwise keep the custom UI and use the same underlying event ideas.

For Moodio's own UI, use ordinary HTTP for commands/history plus **SSE for live Station-feed updates** as the initial transport. Keep a reconnectable persisted feed as the source of truth. This is an architecture inference, not an Agents SDK prescription: the SDK has no documented browser-transport opinion for normal text agents.

## Verified documentation facts

### ChatKit: UI, items, actions, and progress

- ChatKit is a framework-agnostic, drop-in chat component with configuration for its header, composer, history panel, thread, theme, and thread-item actions. Its documented theme controls are colours, colour scheme, density, radius, and typography. [ChatKit overview](https://openai.github.io/chatkit-js/) · [options](https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/chatkitoptions/) · [theme](https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/themeoption/)
- A ChatKit thread is an ordered persisted timeline of messages, widgets, workflows, hidden context, and metadata. Its client re-renders the persisted items when loading history. Its `Store` is application-provided: it must load/save threads and paginated items. [threads and items](https://openai.github.io/chatkit-python/concepts/threads/) · [Store API](https://openai.github.io/chatkit-python/api/chatkit/store/)
- A stream can add, update, finish, remove, or replace thread items. ChatKit persists an item when it is marked done or replaced; progress updates and client effects are transient and are not stored. [thread stream events](https://openai.github.io/chatkit-python/concepts/thread-stream-events/) · [progress and client effects](https://openai.github.io/chatkit-python/guides/update-client-during-response/)
- It supports widgets and application-defined actions. Actions can be server-handled, client-handled, or sent by client code with `sendCustomAction`; the default streaming action path is blocked while a thread response streams, while `sync_action` is documented for side effects while streaming. [actions](https://openai.github.io/chatkit-python/concepts/actions/) · [ChatKit client API](https://openai.github.io/chatkit-js/api/openai/chatkit/interfaces/openaichatkit/)
- The documented dynamic widget roots are `Card`, `ListView`, and `Basic`. The documentation shows widget actions and theme/configuration, but I found no documented arbitrary React renderer for each custom thread-item kind. [widget API](https://openai.github.io/chatkit-python/api/chatkit/widgets/) · [widget action option](https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/widgetsoption/)

### ChatKit: server, stream, and persistence

- A self-hosted ChatKit backend accepts HTTP requests at one endpoint. Its streaming response has media type `text/event-stream`; ChatKit documents its `ThreadStreamEvent`s as SSE payloads. [Python quickstart](https://openai.github.io/chatkit-python/quickstart/) · [thread stream events](https://openai.github.io/chatkit-python/concepts/thread-stream-events/)
- ChatKit requires a Store even in the simple case. The quickstart's in-memory store intentionally loses data on restart; the docs advise a database-backed store for restart persistence. This is ChatKit's storage abstraction, not a supplied SQLite implementation or durability guarantee. [Python quickstart](https://openai.github.io/chatkit-python/quickstart/)
- In the documented self-hosted-backend mode, **you** run the chat server and own messages/attachments, while the ChatKit comparison table still identifies OpenAI as hosting the iframe that renders the Chat UI. [ChatKit overview](https://openai.github.io/chatkit-js/)

### Agents SDK: sessions and transport

- The SDK supports both a lightweight file-backed `SQLiteSession` and custom/client-managed sessions; it also lists a file-backed-session example. The official docs do **not** compare SQLite's crash consistency/durability semantics with append-only JSON/text files. Therefore this research cannot support a claim that SQLite is categorically safer than a carefully written text-file design. [sessions](https://openai.github.io/openai-agents-python/sessions/) · [examples](https://openai.github.io/openai-agents-python/examples/)
- `OpenAIResponsesCompactionSession` can wrap an underlying local session. Its auto-compaction rewrites history and can keep a stream open after the last visible token; the docs explicitly allow disabling auto-compaction and calling it during idle time. [sessions and compaction](https://openai.github.io/openai-agents-python/sessions/)
- `Runner.run_streamed()` exposes an async stream of raw model and higher-level run-item events inside the application process. The documentation does not supply a browser UI endpoint or choose WebSocket, SSE, or polling for an app's frontend. [Agents SDK streaming](https://openai.github.io/openai-agents-python/streaming/)
- The SDK's optional Responses **WebSocket** transport is a server-to-OpenAI connection. HTTP/SSE is the default, and its docs say to prefer HTTP/SSE when reliability matters more than WebSocket latency. This is not a recommendation for Moodio's browser connection. [model transports](https://openai.github.io/openai-agents-python/models/) · [running agents](https://openai.github.io/openai-agents-python/running_agents/)

## Fit against Moodio's ideal UI

| Concern | ChatKit fit | Assessment |
| --- | --- | --- |
| Half player / half conversation layout | The component can be mounted in a React page next to a custom player; client lifecycle state can also drive host-app UI. | **Possible.** [host-app sync](https://openai.github.io/chatkit-python/guides/keep-your-app-in-sync-with-chatkit/) |
| Profile-update card, diff, task card, queued track/card | Widgets and persisted thread items can represent these, but in ChatKit's item/widget model and documented widget vocabulary. | **Possible, with adaptation.** |
| Playback/queue controls during an agent stream | Default server widget actions are blocked during a stream; the docs offer client handlers or a separate sync-action path. | **Friction:** Moodio must keep direct player controls outside the ordinary streamed-chat action path. [actions](https://openai.github.io/chatkit-python/concepts/actions/) |
| Background autonomous changes | ChatKit's documented stream lifecycle is a response to a user message or action. | **Unproven as a complete Station push layer.** Moodio would still need its own persisted feed/history and a way to notify an open UI about scheduler-originated changes. This is an inference from the documented request/response model. |
| Local-first custom surface | A custom backend and Store are supported; the documented UI is still an OpenAI-hosted iframe. | **Potential product mismatch** if local UI ownership is a requirement. |

## Browser transport choices for Moodio

| Option | Verified relevant fact | Moodio interpretation (inference) |
| --- | --- | --- |
| HTTP + SSE | ChatKit uses HTTP requests and `text/event-stream` for server-to-client thread events. Agents SDK streaming is an async iterator that an application can map to a client stream. | Best initial fit: commands and history remain normal HTTP; one SSE feed streams agent tokens, tool/status events, playback changes, and scheduler-originated events. On reconnect, reload the persisted feed after the last event ID. |
| WebSocket | The Agents SDK supports an *optional server-to-OpenAI* Responses WebSocket, but recommends HTTP/SSE where reliability matters more than latency. | Do not introduce a browser WebSocket merely because the model SDK offers one. Revisit only if the UI needs frequent bidirectional low-latency messages beyond commands and SSE updates. |
| Polling | No relevant ChatKit or Agents SDK frontend-polling recommendation was found in the permitted documentation. | Good only as a recovery/history-refresh fallback. It is a poor primary choice for token streaming, prompt progress, and timely autonomous station updates. |

## Storage conclusion

For the **Agent SDK session**, file-backed SQLite is the lowest-friction supported option, including the compaction wrapper. For Moodio's **user-visible Station feed**, neither SDK requires SQLite: ChatKit requires only a Store, and a custom Moodio feed can be a small append-only file or SQLite.

**Recommendation (inference):** do not choose the feed store for query power. Choose it for safe small writes, monotonic event IDs, atomic recovery, and one implementation path shared by the agent session, queue, tasks, and feed. SQLite is likely the simpler single local persistence boundary; a text/JSON log remains defensible if we deliberately implement atomic write/rotation/recovery. The official OpenAI docs do not settle this durability trade-off, so it should be verified separately before being made an ADR.

## Recommendation

Do **not** make ChatKit the v0.2 UI foundation. Keep Moodio's custom half-player/half-feed UI and own the Station-feed schema. Borrow the useful pattern—persisted domain items plus ephemeral progress/client effects—rather than ChatKit's whole thread renderer.

**Design decision after this research:** v0.2 uses a small, app-owned file store: atomic JSON snapshots plus an append-only JSONL Station feed. It uses a custom file-backed Agents SDK session implementation under the compaction wrapper. This intentionally accepts the small recovery work of a local file store to avoid introducing a database abstraction before the single-Station product needs one.

Use:

1. `POST`/`GET` endpoints for Listener commands and paginated Station history;
2. one UI-facing SSE endpoint for live, domain-shaped Station feed events;
3. the Agents SDK's normal HTTP/SSE model transport initially; and
4. a file-backed compacted agent session, while keeping the user-visible feed independent of raw SDK conversation items.

This keeps the player always independently controllable, gives profile/task/queue changes first-class cards, and avoids committing to an iframe/chat UI model before it has earned that complexity.

## Exact sources consulted

- https://openai.github.io/chatkit-js/
- https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/chatkitoptions/
- https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/themeoption/
- https://openai.github.io/chatkit-js/api/openai/chatkit/interfaces/openaichatkit/
- https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/widgetsoption/
- https://openai.github.io/chatkit-python/quickstart/
- https://openai.github.io/chatkit-python/concepts/threads/
- https://openai.github.io/chatkit-python/concepts/thread-stream-events/
- https://openai.github.io/chatkit-python/concepts/actions/
- https://openai.github.io/chatkit-python/guides/update-client-during-response/
- https://openai.github.io/chatkit-python/guides/keep-your-app-in-sync-with-chatkit/
- https://openai.github.io/chatkit-python/api/chatkit/store/
- https://openai.github.io/chatkit-python/api/chatkit/widgets/
- https://openai.github.io/openai-agents-python/sessions/
- https://openai.github.io/openai-agents-python/streaming/
- https://openai.github.io/openai-agents-python/models/
- https://openai.github.io/openai-agents-python/running_agents/
- https://openai.github.io/openai-agents-python/examples/
