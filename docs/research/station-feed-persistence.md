# Station feed and agent-session persistence

**Scope:** one local Moodio Station: a small chronological UI feed plus one
long-running Agents SDK session. This is research only; it does not prescribe a
schema or change the runtime. Sources were checked on 2026-07-25 and are limited
to SQLite, Python standard-library, and OpenAI Agents SDK primary sources.

## Short answer

SQLite has **stronger built-in transactional and crash-recovery semantics** than
an ordinary text/JSONL file. It does not, however, make data intrinsically more
durable than the filesystem: the selected journal mode and `synchronous` setting
still determine the trade-off around power loss.

For Moodio, those facts point to different sensible defaults:

1. Use the Agents SDK's built-in **file-backed `SQLiteSession`** (optionally
   wrapped in its compaction session) for the agent transcript. The SDK supplies
   that implementation; a JSONL session would mean owning the full
   `get/add/pop/clear` lifecycle and safe rewrite logic ourselves.
2. A **small append-only JSONL Station feed** is a credible choice for the
   user-facing panel, provided it has a deliberate write/recovery policy. It is
   naturally chronological and needs no query model. SQLite is also a perfectly
   reasonable single-file alternative if we prefer one persistence mechanism and
   want feed revisions/queries later.

The recommendation is an engineering judgment, not an SDK requirement.

## Verified facts

### SQLite

- SQLite transactions appear atomic across an operating-system crash or power
  failure: either all changes in a transaction appear or none do. In rollback
  journal mode, an interrupted commit is detected via a hot journal and rolled
  back automatically on the next open. [Atomic Commit in SQLite](https://www.sqlite.org/atomiccommit.html)
- SQLite's guarantees are conditional on the storage stack behaving as its VFS
  expects. Its own documentation explicitly notes OS write buffering/reordering,
  the use of flush/`fsync` at key points, and the possibility of corruption if a
  platform's `fsync` is broken. [SQLite hardware assumptions](https://www.sqlite.org/atomiccommit.html#hardwareassumptions)
- In WAL mode, readers and a writer can usually proceed concurrently. WAL also
  has extra `-wal` and `-shm` files, checkpointing, and does not work across a
  network filesystem. [SQLite WAL overview](https://www.sqlite.org/wal.html)
- SQLite still permits one writer at a time. In rollback-journal locking, only
  one process can hold the reserved lock; other processes may read while it is
  held. [SQLite locking and concurrency](https://www.sqlite.org/lockingv3.html)
- Durability is a configuration choice, not a generic property of a `.db` file.
  `synchronous=FULL` in WAL mode is ACID; `synchronous=NORMAL` in WAL mode keeps
  consistency but a committed transaction can roll back after a power failure;
  `OFF` can corrupt after OS crash/power loss. `EXTRA` adds a directory sync in
  rollback mode. [SQLite `PRAGMA synchronous`](https://www.sqlite.org/pragma.html#pragma_synchronous)

### Plain files / JSONL with Python

- Python's `os.write()` reports how many bytes were written, rather than
  promising it wrote an entire record. A correct low-level append implementation
  therefore must handle a short write. [Python `os.write`](https://docs.python.org/3/library/os.html#os.write)
- Python exposes append and synchronization primitives, but does not turn them
  into a transaction system: `os.O_APPEND` is an open flag, and `os.fsync(fd)`
  forces the file's writes to disk. For a buffered file object, Python says to
  flush it before `fsync`. [Python file flags](https://docs.python.org/3/library/os.html#open-flag-constants) · [Python `os.fsync`](https://docs.python.org/3/library/os.html#os.fsync)
- `os.replace(src, dst)` is atomic on POSIX after success, but that describes a
  replacement operation—not a durable multi-file transaction or an append log.
  It is useful for replacing a compacted snapshot/profile, not for preserving
  the individual history of a feed. [Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace)

**Implication (inference):** JSONL is not unsafe by definition, but it has no
automatic equivalent to SQLite's transaction journal, rollback, ordering, or
query layer. The application must choose what happens to a partial final record,
when it calls `fsync`, and how it makes any rewrite/replay recoverable.

### OpenAI Agents SDK sessions

- The SDK's documented built-in local implementation is `SQLiteSession`; it can
  be in-memory or file-backed (`SQLiteSession("user_123", "conversations.db")`).
  The SDK lists it as its lightweight option for local development and simple
  applications. [Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/#sqlite-sessions)
- SDK sessions support `get_items`, `add_items`, `pop_item`, and
  `clear_session`. `SessionSettings(limit=N)` limits how much stored history is
  retrieved for a run; it does not eliminate the stored history by itself.
  [Session operations and retrieval limits](https://openai.github.io/openai-agents-python/sessions/#memory-operations)
- `OpenAIResponsesCompactionSession` wraps an underlying session, compacts with
  `responses.compact`, and **clears and rewrites** the stored session history.
  It auto-compacts after its threshold by default; the SDK recommends disabling
  auto-triggering and calling `run_compaction()` during idle time when
  low-latency streaming matters. [Agents SDK compaction sessions](https://openai.github.io/openai-agents-python/sessions/#openai-responses-compaction-sessions)
- The official stateless compaction example pairs the wrapper with a
  `SQLiteSession`; when `store=False`, automatic mode uses locally stored input
  items for input-based compaction. [Official stateless compaction example](https://github.com/openai/openai-agents-python/blob/main/examples/memory/compaction_session_stateless_example.py)
- The documented built-in-session list includes SQLite, Async SQLite, Redis,
  SQLAlchemy, Dapr, MongoDB, advanced SQLite, and encryption wrappers. It does
  not document a built-in file/JSONL session. The SDK permits custom session
  implementations, but offers no official file-session example in that list.
  [Agents SDK built-in sessions](https://openai.github.io/openai-agents-python/sessions/#built-in-session-implementations)

## Comparison for Moodio

| Concern | SQLite | Append-only JSONL |
| --- | --- | --- |
| Write one feed event | A committed `INSERT` is a natural atomic unit. | Append one encoded line; application owns short-write handling and sync policy. |
| Crash/power-loss recovery | Journal/WAL machinery handles incomplete transactions. Exact durability depends on `synchronous` and filesystem. | Application must define recovery, e.g. validate records and discard/quarantine an incomplete final line. `fsync` controls when a successfully written record is requested to reach disk. |
| Update/delete/revision | Transactional, including changes to several rows. | Needs an extra event, a rewritten snapshot, or a compaction protocol. |
| Chronological panel | `ORDER BY sequence/timestamp`; easy paging and filtering if later needed. | File order is chronological by construction; read/parse sequentially or keep a small in-memory index. |
| Concurrency | One writer; WAL permits reader/writer overlap in common cases. | Single process can serialize appends simply; multi-writer safety and reader consistency become application work. |
| Agent session with SDK | Official, file-backed option; directly supports `get/add/pop/clear` and the official compaction wrapper. | Requires a custom `SessionABC` implementation and safe full-history replacement when compaction runs. |
| Operational complexity | One database file, with journal/WAL sidecar behavior depending on mode. | Human-readable and portable, but the app owns append, sync, tail recovery, snapshot replacement, and migration conventions. |

## Recommendations

These are proposed defaults, not requirements.

### 1. Keep the agent session in file-backed SQLite

Use the documented `SQLiteSession(station_id, path)` as the compaction
underlying store. It is the smallest official local option and avoids building a
custom persistent session merely to write JSON. Configure compaction with a
generous threshold and run it during an idle scheduler slot, not on the
listener's response path. The report does **not** recommend creating subagents
or separate session infrastructure for this.

Before implementation, inspect the actual session implementation/version used by
Moodio and explicitly choose its SQLite journal/sync settings rather than assume
defaults meet the desired power-loss policy.

### 2. Start the Station feed as an app-owned append-only JSONL log

This matches the stated use: a small, single-Station, chronological panel—not a
database to query. One event can be a simple object such as:

```json
{"id":"...","at":"...","kind":"profile.updated","data":{...}}
```

Keep the contract intentionally small: append only, stable IDs, and no raw model
reasoning, provider secrets, or expiring stream URLs. The UI reads this app-owned
feed, never the SDK session transcript.

A minimal reliability policy should be written down before coding:

1. Serialize one complete JSON object plus newline; handle short writes.
2. Choose either `flush` + `fsync` per acknowledged event (stronger last-event
   durability, more I/O) or a documented batched-sync loss window.
3. On startup, parse sequentially; preserve valid preceding events and handle a
   malformed trailing record as an interrupted append rather than treating the
   whole feed as unusable.
4. If a later compacted feed snapshot is added, write it separately, sync it as
   appropriate, then replace it deliberately; do not overwrite the live JSONL
   log in place.

These are implementation recommendations inferred from the Python I/O primitives
above, not guarantees supplied by JSONL or the SDK.

### 3. Keep an escape hatch, not a premature data model

Define a tiny `StationFeed` interface (`append`, `list`, optionally `get`) so
the panel is not coupled to JSONL. If the feed later needs server-side paging,
cross-event atomic updates, editing, multiple processes, or richer filters,
implement that same interface on SQLite. No migration needs to be designed now;
the JSON objects themselves are a straightforward import source.

## Decision framing

SQLite *does* provide stronger out-of-the-box guarantees than a normal text file:
atomic multi-step commits, automatic interrupted-transaction recovery, locking,
and configurable durability. That is valuable for the SDK session because
compaction rewrites history. For a small UI-only chronological feed, those
capabilities may not justify the extra model and query surface. A carefully
written JSONL append log is a reasonable simpler choice—so long as we explicitly
accept and implement its smaller durability/recovery contract.
