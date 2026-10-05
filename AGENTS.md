# xmuse contributor guide

## Direction and evidence

xmuse is a heterogeneous Agent workroom: independent Agents from different vendors (Codex,
Claude Code, Antigravity, OpenCode, ...) join one durable Room with a Human and collaborate by
capability. A Room selects a collaboration mode:

- `broadcast` (default, the original protocol): every active Agent observes Room events and
  independently chooses whether and how to respond.
- `addressed`: only Agents addressed by a Human mention or a peer handoff observe an
  activity; an unaddressed Human message goes to the Room's default lead. The lead is a
  fallback recipient, not a central router or speaker queue; any addressed Agent may defer
  or hand off.

Infrastructure owns delivery, identity, causality, attempts, safety, and privileged
execution; it must not impersonate an Agent. Provider transports differ (Codex app-server,
ACP, the Antigravity agy CLI), but every Agent writes Room truth only through the same
identity-, attempt-, and lease-bound Room MCP tools: one outcome tool that ends a turn, plus
board tools for coordinating mid-turn (module charters, versioned interface contracts,
progress, peer questions).

Treat implementation and fresh tests as evidence. Documentation is descriptive.

## Layout

| Path | Role |
| --- | --- |
| `xmuse/` | Runtime/application layer; intentionally has no `__init__.py`. |
| `src/xmuse_core/` | Reusable Room, Agent, runtime, provider, and Skill logic. |
| `tests/xmuse/` | Backend behavior and boundary tests. |
| `frontend/` | Browser Workroom. |
| `integrations/` | Host plugins and CLI adapters (Claude Code mod, OpenCode, `xmuse-ctl`). |
| `docs/contracts/` | Public read-model contracts with JSON Schemas and golden fixtures. |

`xmuse/` may import `xmuse_core.*`; core must not import the application layer or
`memoryos_lite`. The optional adapter speaks only the public loopback HTTP contract.
`integrations/` speaks only the public loopback HTTP contract documented in
`docs/contracts/`: it never imports `xmuse` or `xmuse_core`, never holds the operator token,
never registers writes as model-callable tools, and never copies agent-authored text into
model context.

## Commands

```bash
uv sync --frozen --all-groups
PYTHONWARNINGS=error TMPDIR=/tmp uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy --explicit-package-bases xmuse src/xmuse_core scripts
uv build
cd frontend
npm ci
npm run typecheck
npm test
npm run lint
npm run build
npm run test:e2e
cd ..
uv run python scripts/room_soak_chaos.py ci-sim \
  --root /tmp/xmuse-ci-sim \
  --result /tmp/xmuse-ci-sim-result.json \
  --no-build-frontend
```

Public commands: `xmuse-chat-api`, `xmuse-mcp-server`, `xmuse-room-runner`,
`xmuse-workroom`, `xmuse-data`, and `xmuse-ctl` (the read-only board command line under
`integrations/xmuse-ctl`: loopback HTTP only, no operator token, no agent text in its
output). Entrypoints read exported environment variables and do not load `.env`.

## Runtime boundaries

- `chat.db` is durable Room authority; `god_sessions.json` is durable
  participant/provider binding state.
- In `broadcast` mode, Human speech atomically creates root observations for every active
  participant; in `addressed` mode, only for the addressed participants (or the lead). Once the
  root phase terminates, same-participant peer observations for that correlation are claimed
  as an immutable batch with one attempt and outcome. In `broadcast` mode mentions affect
  priority, not eligibility or the bounded response budget; in `addressed` mode they select
  eligibility. Addressed deliveries carry `room_context.collaboration` (mode, lead, whether the
  recipient is the lead, and handoff guidance) because peers never see unaddressed work.
- The browser consumes `room_list_projection/v1`, `room_chat_projection/v3`,
  `room_operations_projection/v2`, and `room_board_projection/v2`. The board projection,
  its summary, change feeds and contract detail are specified in
  `docs/contracts/room_board_projection_v2.md`; one derivation module computes module
  lifecycle, host verification, state, attention and metrics for every consumer, and
  agent-authored text only leaves wrapped as untrusted `AgentText`.
- Room Agent response previews use a separate private disposable cache and
  `room_agent_stream_projection/v1` SSE. They are sanitized provider evidence only, never
  Room speech, memory, execution evidence, or completion authority.
- The isolated Room Runner does not initialize a platform queue, scheduler, review plane,
  execution harness, self-evolution controller, or A2A transport.
- Room Codex sessions are participant-bound, read-only, network-disabled, and config-isolated.
  Other providers' non-owner sessions must deny or be instructed against workspace writes
  (owners are described below); their confinement
  level is reported per provider and never assumed equal to Codex. Workspace changes still
  enter only through exact-patch candidates. Claude ACP sessions run with built-in tools
  limited to Read/Glob/Grep (no Bash), no workspace project/local settings, no MCP servers
  from the operator's user config (`strictMcpConfig`), the `default` permission mode pinned
  via `session/set_mode`, and only the exact Room MCP tools (outcome and board) approved by
  the ACP permission callback. OpenCode ACP sessions run its own tools without
  asking the client, so the agent process runs under bubblewrap instead: filesystem and
  workspace read-only, private `/tmp`, other tools' credential stores and the xmuse root
  masked, only OpenCode's own state directories writable (`os_read_only_sandbox`). Its model
  comes from `XMUSE_OPENCODE_MODEL` and an unknown model fails the attempt rather than
  falling back. A turn that ends without a durable outcome gets at most one in-lease reminder
  prompt for profiles that opt in (OpenCode); provider text is still never Room truth.
- Antigravity participants run the standalone `agy` CLI under bubblewrap with an
  allowlisted home (only agy's own state directory stays writable and only its
  config plus the generated Room MCP file stay readable), and
  `--dangerously-skip-permissions` is passed only inside that sandbox.
  Non-owners are confined read-only (`os_read_only_sandbox`); `workspace_write`
  owners work in their own clone with the board view mounted read-only at
  `.xmuse` (`os_workspace_write_sandbox`).
- On WSL every provider bubblewrap sandbox (`os_read_only_sandbox` and
  `os_workspace_write_sandbox`, for OpenCode, agy and owners alike) also masks the Windows
  drives as empty tmpfs: every drvfs mount (`/mnt/c`, `/mnt/d`, ...) with its Windows-side
  `.ssh`, `.aws`, `.claude` and browser profiles. The masks go before any re-bind, so a
  workspace or owner clone that lives on a drive stays reachable; nothing else on that drive
  is. Off WSL there are no such mounts and nothing changes.
- A roster may declare a Claude, OpenCode, or Antigravity participant `workspace_write` (an owner). An
  owner works in its own local clone (`git clone --no-hardlinks`, no origin remote, under
  `<root>/runtime/owner-clones`) with its provider's full native tools; its agent process
  runs under bubblewrap where only that clone and that provider's own state are writable,
  every other provider's state, other credential stores and the xmuse root (including other
  owners' clones) are masked, and the network stays shared (`os_workspace_write_sandbox`).
  Owners keep their own MCP servers and Skills: for Claude the permission callback approves
  every tool and neither `strictMcpConfig` nor a Skill ban is set. Known, operator-accepted
  residual: an MCP server reached over the network, or one that delegates to another agent,
  runs outside the sandbox. The owner's board view (charter and contracts) is a host-owned
  directory mounted read-only at `<clone>/.xmuse`, excluded from commits and rejected by
  patch export. The clone is a draft area only: workspace changes still enter only through
  exact-patch candidates, and the host never runs git inside an owner clone after creating
  it (patches are exported through a host-owned bare mirror). Participants without the
  attribute are unchanged in rows, identities, fingerprints, projections, transports and
  timeouts.
- Owner turns may run for hours: the host renews the lease in fenced slices while the
  provider reports progress, and ends the turn only on a stall (`room_turn_stalled`), a run
  of identical finished tool calls (`room_turn_looping`), the hard cap, or transport failure.
  A lapsed or superseded lease is never renewed. Once the attempt's own outcome has committed,
  the provider gets a bounded grace to end its turn, so the next delivery reuses its session.
- A failed attempt reopens immediately only when its transport proved the provider
  generation gone (`cleanup_succeeded`); otherwise it waits out its lease. The attempt limit
  applies either way.
- Managed MCP exposes only `/health`, `/mcp/room`, `chat_room_submit_outcome`, and the
  `chat_room_board_*` tools (read, propose_split, claim, publish_contract, report_progress,
  ask, review). New batch deliveries bind that outcome to the exact batch and may name a reply
  target from the delivered members. Provider final text is not Room truth.
- Board tools require the caller's live lease exactly like the outcome tool, are idempotent
  by `client_request_id`, and append a `board.*` Room activity in the same transaction as the
  board state change. Only the Room lead proposes a module split; it takes effect only after
  a guarded operator approval. Charter-derived rules (who may revise a contract, report on
  or claim a module) are enforced server-side, not by prompts. A contract revision wakes
  every owner whose charter depends on it; a charter change never rewrites persona snapshots
  or provider session identity.
- An owner's `done` report is a claim, not completion. It enqueues a durable verification in
  the same transaction; a Chat API background loop (never the delivery path or startup)
  exports the owner branch through the host mirror, rejects changes outside the charter
  paths, and runs only the server-owned gate profile on a detached stage at the owner base.
  Charter `acceptance` text is never executed. The result is an `infrastructure`
  `board.verification` activity: a failure wakes the owner (repeated failures also the lead),
  a newer `done` supersedes older verifications, and verification never promotes.
- Cross-family board review is server-assigned by rule `cross_family/v1`: the author
  never chooses its reviewer and never reviews its own work; only the assigned
  reviewer participant may rule with `chat_room_board_review`; when no other model
  family is present a Human reviews instead, never a same-family fallback; the
  assignment inputs are persisted with the review.
- `room_context_envelope/v2` preserves the Human root, primary source and ancestry while
  bounding recent context to 64 KiB. Bundled roster personas are immutable Room snapshots and
  participate in provider session identity.
- Managed writes and operator actions require server-only `XMUSE_OPERATOR_TOKEN`.
- Exact-patch authorization uses only server-owned `room_execution_gate_profile/v1`
  profiles. The configured profile's repository markers, complete local toolchain capability,
  and ordered path-selected gates are frozen durably and re-proved before promotion. External
  workspaces require an explicit profile; their path and private digests never enter browser
  projections. Harness frontend gates call fixed read-only dependency entrypoints rather than
  candidate-controlled package scripts.
- The fixed Harness profiles are `docs/v1`, `python-uv/v1`, `xmuse-monorepo/v2`,
  `python-uv-ty/v1`, `node-pnpm-library/v1`, `node-pnpm-next-workspace/v1`, and
  `remix-monorepo/v1`. They invoke only server-owned direct entrypoints whose marker, lock,
  configuration, and local capability have been frozen; they never accept repository scripts,
  arbitrary argv, or network installs. The one controlled exception is `remix-monorepo/v1`:
  a server-owned driver runs `tsc --noEmit` and the repository's own test runner
  (`remix test --type server`) per affected workspace package (derived from the changed
  paths). The runner's dispatch path (`packages/test/`, `packages/assert/`, the remix
  `cli-entry.ts`/`cli.ts` and the cli `index.ts`, `cli.ts` and test command) is frozen file by
  file as repository markers and is never a candidate path; package scripts are only checked
  for presence, never executed. As with every test gate, candidate code still runs while the
  tests run.
- Source-backed memory remains optional at installation time. Workroom defaults to
  `--memory-mode auto`: it selects only an installer-owned, digest-verified full-local
  companion; `--memory`/`--memory-mode on` is the explicit source/development path and
  `--no-memory`/`--memory-mode off` disables it. `chat.db` owns its outbox, approvals,
  delivery evidence, and recall receipts; the MemoryOS archive database is derived and
  rebuildable. Recall accepts only bounded archival items whose source documents/activities
  can be re-proved, and any failure remains Host attention rather than Room Runtime failure.
  With the opt-in `full-local-curated` profile, the MemoryOS Curator may propose memory
  candidates as an external proposer (`proposer_kind=memoryos_curator`), never as an Agent;
  every proposal cites Room activities with verbatim quotes that are re-proved in `chat.db`
  and passes the same approval rules. Its LLM key reaches only the MemoryOS sidecar. The
  Curator is the only memory proposer besides Agents: MemoryOS' heuristic agent kernel and
  paging stay off, and any other MemoryOS advisory is rejected rather than attributed to the
  recalling participant.
- The MemoryOS sidecar and Room Runner may receive the server-only MemoryOS API key. Room
  MCP, Codex sessions, the browser, Operations, commands, receipts, and logs must not.
- The Workroom manager automatically restarts only its identity-confirmed-dead MemoryOS
  child with bounded backoff. Live-but-unhealthy, identity-mismatched, and unknown port
  owners remain degraded without speculative signals. Guarded derived-index rebuilds are
  durable `chat.db` actions; they stop the proven child before deleting only the fixed cache,
  reset bindings/outbox transactionally, and resume replay without changing Room readiness.
- `xmuse-data` may inspect old `xmuse.chat_db/v1` databases only for offline
  doctor/backup/restore/compact. It must not initialize a retired runtime.
- The local application remains loopback-only and single-user.
- The Workbench is a progressive Room-first UI: the shared timeline remains primary while the
  Agent, Room, and Runtime dock exposes safe native Codex activity and actionable Room state.
  It must not duplicate native authority, reveal raw thinking/tool payloads/paths, or revive a
  Dashboard.

## Cleanup and safety

- Use Git history instead of repository `legacy/`, `archive/`, or source backups.
- Preserve authority, identity, causality, idempotency, recovery, and data-safety invariants.
- Avoid inventory and exact-document-wording tests; test behavior and package direction.
- Do not reintroduce a central speaker queue or LLM router that decides for Agents, platform
  runner, a general-purpose MCP surface beyond the Room outcome and board tools, Dashboard, A2A
  experiment, an always-on or authoritative MemoryOS runtime, Ray, repository-local OpenCode
  orchestration (OpenCode as a sandboxed Room participant is a provider, not orchestration),
  or LangGraph execution into the default product.
- Do not commit databases, logs, PID/receipt files, runtime roots, `node_modules`,
  `.next`, or caches.
- Preserve unrelated user changes. Never use `git reset --hard`.
