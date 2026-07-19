# xmuse contributor guide

## Direction and evidence

xmuse implements natural, logically decentralized Agent group conversations. Persistent
Agents observe shared Room events and independently choose whether and how to respond.
Infrastructure owns delivery, identity, causality, attempts, safety, and privileged
execution; it must not impersonate an Agent.

Treat implementation and fresh tests as evidence. Documentation is descriptive.

## Layout

| Path | Role |
| --- | --- |
| `xmuse/` | Runtime/application layer; intentionally has no `__init__.py`. |
| `src/xmuse_core/` | Reusable Room, Agent, runtime, provider, and Skill logic. |
| `tests/xmuse/` | Backend behavior and boundary tests. |
| `frontend/` | Browser Workroom. |

`xmuse/` may import `xmuse_core.*`; core must not import the application layer or
`memoryos_lite`. The optional adapter speaks only the public loopback HTTP contract.

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
`xmuse-workroom`, and `xmuse-data`. Entrypoints read exported environment variables and
do not load `.env`.

## Runtime boundaries

- `chat.db` is durable Room authority; `god_sessions.json` is durable
  participant/provider binding state.
- Human speech atomically creates root observations for every active participant. Once the
  root phase terminates, same-participant peer observations for that correlation are claimed
  as an immutable batch with one attempt and outcome. Mentions affect priority, not
  eligibility or the bounded response budget.
- The browser consumes `room_list_projection/v1`, `room_chat_projection/v3`, and
  `room_operations_projection/v2`.
- Room Agent response previews use a separate private disposable cache and
  `room_agent_stream_projection/v1` SSE. They are sanitized provider evidence only, never
  Room speech, memory, execution evidence, or completion authority.
- The isolated Room Runner does not initialize a platform queue, scheduler, review plane,
  execution harness, self-evolution controller, or A2A transport.
- Room Codex sessions are participant-bound, read-only, network-disabled, and config-isolated.
- Managed MCP exposes only `/health`, `/mcp/room`, and
  `chat_room_submit_outcome`. New batch deliveries bind that outcome to the exact batch and
  may name a reply target from the delivered members. Provider final text is not Room truth.
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
  `python-uv-ty/v1`, `node-pnpm-library/v1`, and `node-pnpm-next-workspace/v1`. They invoke
  only server-owned direct entrypoints whose marker, lock, configuration, and local capability
  have been frozen; they never accept repository scripts, arbitrary argv, or network installs.
- Source-backed memory remains optional at installation time. Workroom defaults to
  `--memory-mode auto`: it selects only an installer-owned, digest-verified full-local
  companion; `--memory`/`--memory-mode on` is the explicit source/development path and
  `--no-memory`/`--memory-mode off` disables it. `chat.db` owns its outbox, approvals,
  delivery evidence, and recall receipts; the MemoryOS archive database is derived and
  rebuildable. Recall accepts only bounded archival items whose source documents/activities
  can be re-proved, and any failure remains Host attention rather than Room Runtime failure.
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
- Do not reintroduce a central speaker queue, platform runner, broad MCP, Dashboard, A2A
  experiment, an always-on or authoritative MemoryOS runtime, Ray, repository-local OpenCode
  orchestration, or LangGraph execution into the default product.
- Do not commit databases, logs, PID/receipt files, runtime roots, `node_modules`,
  `.next`, or caches.
- Preserve unrelated user changes. Never use `git reset --hard`.
