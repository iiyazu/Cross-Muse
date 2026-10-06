# Module memory — contract v1

Status: draft, implemented behind a switch that is **off by default**. With it off, no table row is
written, no MemoryOS call is made, and every owner sees exactly the board view it saw before, so
evaluation arms stay comparable.

## 1. What it is

A handover notebook per module. The host (xmuse) keeps it; MemoryOS only drafts it. When an owner is
replaced (quota, 401, stall) or picks a module up again later, it reads the notebook instead of
repeating old mistakes or overturning decisions the Room already made. MemoryOS' own evaluation found
that the largest gain is keeping an agent from reusing patterns the history has abandoned, so the
"superseded, do not use" list is shown prominently.

xmuse renders deterministic state (charter, contracts, verification, review) itself, as before. Module
memory adds only what the board cannot record: lessons from failures the gates and reviewers caught,
decisions and facts stated in messages, and which of them were replaced.

## 2. Switch

- `XMUSE_MODULE_MEMORY=on` turns it on. Anything else, or unset, is off.
- It also needs the MemoryOS sidecar (`XMUSE_MEMORYOS_URL`, `XMUSE_MEMORYOS_API_KEY`) with
  `capabilities.curate = memoryos_curate/v1` and an LLM key on the sidecar side. Missing pieces leave
  it off and record why (`module_memory_unavailable`), never a Room failure.
- The evaluation driver takes `--module-memory` and sets the same variable.

## 3. Windows (host → `POST /curate`, `profile: "module"`)

A background worker in the Chat API reconcile loop scans each active module's Room activities after
its cursor and builds windows of the module's activities:

| Activity | Window type | Text sent |
| --- | --- | --- |
| `board.verification`, status `failed`, the module's | `gate_failure` | reason code, failed gate ids, output tails |
| `board.review`, verdict `object`, the module's | `review_objection` | summary and findings |
| `board.integration` naming the module as conflicted or suspect | `gate_failure` | status, reason code, conflict paths, gate ids |
| `board.progress` by the module's owner | `message` | status, summary, claims |
| `board.question` asked by or to the owner | `message` | the question |
| a Human message that mentions the owner, or the owner's own message | `message` | the text |

- A window is flushed when it holds a `gate_failure` or `review_objection`, or 12 messages; at most 32
  activities; up to 8 earlier activities go as read-only `context`.
- `active` holds the module's active memories (at most 60, newest first).
- Texts are bounded (8 KiB per activity). They are agent- and tool-authored and go only to the
  sidecar, which already holds the Room archive.

## 4. Storage (`chat.db`, host is the authority)

- `room_module_memories`: one row per memory version (`memory_id` from MemoryOS, `kind`,
  `topic_key`, `statement`, `version`, `occurrences`, cited `sources`, `supersedes_id`) with
  `status` `active` or `superseded` (and `superseded_by`). Storing a response is one transaction:
  insert the new versions, mark the ones they supersede, advance the cursor.
- `room_module_memory_runs`: one row per window (first and last seq, status `done`, `failed` or
  `skipped`, attempts, `unaccounted` activity ids, MemoryOS diagnostics, error code).
- A failed call is retried with backoff (30 s × attempts); after 3 attempts the window is marked
  `skipped` and the cursor moves on. Memory is derived: it never blocks a Room.

## 5. Rendering

`.xmuse/memory.md` in the owner's board view, written only when the module has at least one memory:

1. Do not repeat (lessons, most occurrences first).
2. Superseded, do not use (old statement, then the current one).
3. Current decisions and facts.

The owner's `charter.md` then gains one line pointing to it. Without memories neither file changes.
The owner prompt is unchanged.

## 6. Not in v1

- A `memory_ask` board tool (pull side, `POST /sessions/{id}/ask`). It changes the Room MCP tool set
  that every provider's permission path pins, so it gets its own change.
- Approval of memories by the Human, and showing them in the board projection or the host plugins.
- Lessons across Rooms (same repository, a new Room).

## 7. Tests

Window building per activity type, the flush rule and bounds; storing a response with supersession
and cursor in one transaction; retry, backoff and skip; rendering with and without memories; the
switch off writes nothing and calls nothing.
