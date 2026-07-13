# xmuse

[![xmuse CI](https://github.com/iiyazu/Cross-Muse/actions/workflows/xmuse-ci.yml/badge.svg)](https://github.com/iiyazu/Cross-Muse/actions/workflows/xmuse-ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

xmuse is a local runtime for natural, logically decentralized Agent group conversations.
Persistent Agents observe the same durable Room activity and independently choose whether
to `respond`, `handoff`, `propose`, `defer`, or `noop`. Infrastructure owns
delivery, identity, causality, attempts, safety, and recovery; it never speaks as an Agent.

## Current product loop

```text
Browser
  -> fixed same-origin Next routes
  -> Room-only Chat API
  -> RoomDatabase / RoomKernel
  -> isolated Room Runner
  -> participant-bound read-only Codex session
  -> bundled Skill decision and context evidence
  -> Room-only MCP chat_room_submit_outcome
  -> durable outcome
  -> Room projection / Operations Inspector

execution proposal
  -> immutable exact-patch candidate in chat.db
  -> manual confirmation (default), or startup-enabled unanimous Room consensus
  -> one-shot networkless Bubblewrap controller in a detached worktree
  -> fixed path-selected gates
  -> guarded promotion of the same patch + execution infrastructure activity

optional source-backed memory
  -> visible Room activity / approved Agent candidate memory outbox in chat.db
  -> archive-only MemoryOS index (rebuildable, loopback, no LLM/vector network)
  -> bounded source-validated memory_evidence in the next Agent context
```

- `chat.db` is authority for Room activity, observations, attempts, controls, messages,
  proposals, cursors, leases, Skill evidence, accepted outcomes, exact-patch candidates,
  assessments, authorizations, execution attempts, gate evidence, and promotion journals.
  It also owns memory outbox rows, candidate approvals, delivery evidence, and recall
  receipts; the MemoryOS database is a disposable index, never Room authority.
- `god_sessions.json` records durable participant/provider bindings. Provider stdout,
  browser state, screenshots, and telemetry are not authority.
- Human speech atomically creates one root observation for every active participant. After
  that root phase terminates, peer activities for the same participant and correlation are
  claimed as one immutable batch (at most 16 items), with one attempt, Skill decision, and
  durable outcome. Mentions and handoffs change attention priority, never eligibility or the
  per-turn response budget.
- Only the identity-, attempt-, and lease-bound MCP outcome becomes Agent speech. Provider
  final text is diagnostic.
- Room Codex sessions use a config-isolated home, read-only filesystem policy, no network,
  and exactly one pre-approved MCP outcome tool.
- Agents can author or assess an exact unified diff through that same durable outcome tool;
  they never receive a writable workspace or arbitrary command surface. Execution is manual
  by default. Consensus execution additionally requires the startup kill-switch, a Room
  policy opt-in, a frozen unanimous peer snapshot, complete patch-review receipts, and the
  server-only low-risk policy.
- The one-shot Harness applies only the authorized bytes in a detached worktree. Bubblewrap
  removes network and ambient credentials. A server-owned, versioned gate profile freezes
  repository markers, the complete local toolchain capability, and the path-selected gate
  order into the authorization. Frontend gates invoke fixed read-only dependency entrypoints,
  never candidate-controlled package scripts. Promotion rechecks policy, clean HEAD, profile
  evidence, and file digests. Pre-promotion failure leaves target bytes unchanged; an
  ambiguous promotion image is blocked for human repair.
- Confirmed-dead Runner attempts are fenced and reopened only after provider cleanup.
  Cancel/retry and guarded Runtime recovery use durable, idempotent control ledgers.
- The browser consumes bounded `room_list_projection/v1`,
  `room_chat_projection/v3`, and `room_operations_projection/v2`.
- Provider context uses `room_context_envelope/v2`: the Human root, primary source, causal
  ancestry, batch members, bounded recent burst, active roster, and frozen role persona are
  retained under a 64 KiB limit. A peer follow-up may create visible speech once; its tail is
  context-only and cannot start a third provider wave.
- Optional MemoryOS recall accepts only bounded `metadata.v3_context.items[]` archival
  evidence whose document and activity sources can be re-proved from `chat.db`. Timeouts,
  malformed data, and sidecar failure degrade memory only; the Room attempt still completes
  from its causal context. Agents may propose source-backed memory candidates, but only
  Room facts/decisions auto-publish to that Room. User preferences and project rules require
  an explicit operator approval before shared-archive recall.
- This remains a loopback-only, single-user application. Managed writes use a server-only
  `XMUSE_OPERATOR_TOKEN`; fixed Next routes never expose it to the browser.

The default product has no platform runner, central speaker queue, fixed role sequence,
Dashboard, broad MCP root, self-evolution control plane, MemoryOS sidecar, or A2A runtime.
MemoryOS is an explicit `--memory` archive-only option; it does not expand the Room Agent's
single MCP tool or filesystem/network permissions. Retired implementations live only in Git
history.

## Run locally

Requirements: Linux or WSL, Python 3.11+, `uv`, Git, Bubblewrap, Node.js 20.9+, npm,
and an authenticated Codex CLI on `PATH`.

```bash
uv sync --frozen --all-groups
cd frontend
npm ci
NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL=http://127.0.0.1:8201/api/chat npm run build
cd ..
export XMUSE_ROOT=/tmp/xmuse-local
uv run xmuse-workroom doctor
uv run xmuse-workroom start
```

Open `http://127.0.0.1:3000`. From another terminal:

```bash
uv run xmuse-workroom status
uv run xmuse-workroom stop
```

The default execution workspace is this xmuse checkout with
`xmuse-monorepo/v2`. To use another clean Git workspace, choose its fixed profile
explicitly; the same path is mounted read-only for Room Agents and used as the exact-patch
promotion target:

```bash
uv run xmuse-workroom start \
  --workspace /absolute/path/to/python-project \
  --execution-profile python-uv/v1
```

The fixed profiles are `docs/v1` (documentation plus diff-check), `python-uv/v1`
(`ruff`, `mypy src`, and `pytest`), and `xmuse-monorepo/v2` (backend plus direct
TypeScript, ESLint, Vitest, and Next build gates). Only `docs/v1` can run diff-check alone.
Missing markers, preinstalled dependencies, Bubblewrap, or fixed tool entrypoints block both
manual and consensus execution. Python gates are supervised at 2 GiB aggregate RSS, 64
processes, and 1 GiB scratch; frontend gates use 4 GiB, 128 processes, and 2 GiB scratch.
Neither the workspace path nor internal profile/toolchain digests enter browser projections.

To opt into the source-backed archive index, point Workroom at a real MemoryOS executable:

```bash
uv run xmuse-workroom start --memory \
  --memoryos-executable /absolute/path/to/memoryos
```

Workroom fixes the sidecar to loopback, creates a private derived data directory and random
server-only API key, and disables its agent kernel, rewrite, rerank, paging, item extraction,
recall cache, and archival vector network. MemoryOS health is reported separately and never
changes Room Runtime readiness. A confirmed-dead owned sidecar is restarted with bounded
`1/2/4/8/16/30s` backoff while the same Workroom generation retains its private endpoint,
key, and data directory; a live-but-unhealthy, identity-mismatched, or unknown port owner is
reported as degraded and is never killed speculatively. Crash-loop or explicit derived-cache
blockers can be rebuilt from the Inspector through a guarded, durable operator action. The
manager first proves and stops the sidecar, deletes only the fixed derived directory, resets
bindings/outbox from `chat.db`, restarts the same capability, and waits for replay evidence.

The five supported commands are `xmuse-chat-api`, `xmuse-mcp-server`,
`xmuse-room-runner`, `xmuse-workroom`, and `xmuse-data`.

## Data maintenance

```bash
uv run xmuse-data doctor --root "$XMUSE_ROOT"
uv run xmuse-data backup /path/to/new-backup --root "$XMUSE_ROOT"
uv run xmuse-workroom stop --root "$XMUSE_ROOT"
uv run xmuse-data restore /path/to/backup --root "$XMUSE_ROOT" --replace
uv run xmuse-data compact --root "$XMUSE_ROOT"
```

`xmuse-data` recognizes current `xmuse.room_db/v1` and old
`xmuse.chat_db/v1` database variants for offline doctor/backup/restore/compact only. It
preserves schema markers and durable identities without initializing or running retired
product surfaces. Backups contain `chat.db` and the fenced participant binding snapshot, not
the MemoryOS cache. Restore clears only the fixed derived MemoryOS directory, forgets old
session/attachment bindings, and reopens visible activities plus approved candidates for
rebuild.

## Verify

```bash
TMPDIR=/tmp uv run pytest -q
uv run ruff check .
uv run mypy --explicit-package-bases xmuse src/xmuse_core \
  scripts/room_first_real_acceptance.py scripts/room_soak_chaos.py
cd frontend
npm ci && npm run typecheck && npm test && npm run lint && npm run build && npm run test:e2e
```

The independent multi-Room lab exercises the same production Kernel/Host path without
adding a telemetry API or Dashboard. `ci-sim` is deterministic and suitable for ordinary
CI; live profiles require a clean HEAD, free fixed ports, authenticated Codex, and a result
path outside the workspace:

```bash
uv run python scripts/room_soak_chaos.py ci-sim --result /tmp/xmuse-ci-soak.json
uv run python scripts/room_soak_chaos.py live-short --result /tmp/xmuse-live-short.json
uv run python scripts/room_soak_chaos.py memory-recovery \
  --memoryos-executable /absolute/path/to/memoryos \
  --result /tmp/xmuse-memory-recovery.json
uv run python scripts/room_soak_chaos.py live-soak \
  --confirm-provider-cost \
  --result /tmp/xmuse-live-soak.json
```

`memory-recovery` uses two phases: nine warm-up turns and one post-recovery turn per Room.
This deliberately moves the recall anchor beyond the default eight-activity recent burst,
so a passing receipt proves archival MemoryOS evidence instead of duplicating Room context.
`live-soak` distributes four provider waves across at least 60 minutes; the confirmation
flag is mandatory. Results use `room_soak_chaos_result/v1` and contain only aggregate
counts, percentiles, stable reason codes, resource totals, and digests. Room/provider text,
tokens, process identities, bindings, and local paths are rejected by the result contract.

Implementation and fresh tests are evidence. See [QUICKSTART.md](QUICKSTART.md) and the
[implementation map](docs/xmuse/README.md).
