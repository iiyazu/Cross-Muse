# xmuse Production Operations

Date: 2026-06-04

Scope: Path A Phase 2 runtime operations after V8 independent installability.

## Runtime Topology

Production groupchat runtime is:

```text
operator
-> Chat API :8201
-> platform runner
-> PeerChatScheduler
-> RayGodSessionLayer
-> RayGodActor
-> Codex app-server thread
-> MCP /mcp/chat :8100
-> chat.db + god_sessions.json
```

Durable authority remains in `chat.db`, `god_sessions.json`, lane projections,
and graph/status stores. Ray actors, Codex app-server threads, provider sessions,
and HTTP processes are runtime resources, not durable authority.

## Env Bundle

Use this bundle for the real groupchat Ray/Codex/MCP writeback path:

```bash
export XMUSE_PEER_GOD_BACKEND=ray
export XMUSE_EXECUTE_GOD_BACKEND=ray
export XMUSE_REVIEW_GOD_BACKEND=ray
export XMUSE_RAY_GOD_TRANSPORT=app-server
export XMUSE_RAY_GOD_EFFORT=low
export XMUSE_RAY_GOD_MCP=1
export XMUSE_CHAT_API_URL=http://127.0.0.1:8201
export XMUSE_CHAT_API_AUTH_TOKEN=<server-token>
export XMUSE_CHAT_API_KEY=<same-token-for-tui-client>
export XMUSE_MCP_AUTH_TOKEN=<server-token>
```

`XMUSE_DEGRADED_LOCAL_GOD_MODE=1` is an explicit degraded local mode. It is not
the happy path and must be visible in health/readiness output or lane/peer traces.

When `XMUSE_CHAT_API_AUTH_TOKEN` or `XMUSE_CHAT_API_KEY` is set for the Chat API
process, mutating `/api/chat/*` routes require:

- `X-XMUSE-API-Key` matching the configured token;
- `X-XMuse-Operator-Role` such as `operator` or `admin`;
- `X-XMuse-Operator-Capabilities` containing the route capability, for example
  `chat_create_conversation` or `select_god_cli`.

The TUI reads `XMUSE_CHAT_API_KEY` and forwards it to Chat API operator action
requests. Read routes remain unauthenticated until a broader deployment policy
decides otherwise.

When `XMUSE_MCP_AUTH_TOKEN` or `XMUSE_MCP_API_KEY` is set for the MCP process,
mutating JSON-RPC `tools/call` requests on `/mcp`, `/mcp/chat`, `/sse`, and
`/messages` require:

- `X-XMUSE-API-Key` matching the configured MCP token;
- `X-XMuse-Operator-Role` such as `operator`, `god`, or `admin`;
- `X-XMuse-Operator-Capabilities` containing the exact MCP tool name for
  non-admin writes, for example `enqueue_lane` or `chat_emit_proposal`.

Read-only MCP tools remain token-free under the current local trust policy.
MCP auth does not replace tool-specific audit guards or GOD session identity
checks.

## Startup

Start services from the xmuse repo root:

```bash
uv run python -m xmuse.chat_api
uv run python -m xmuse.mcp_server --port 8100
uv run xmuse-platform-runner --peer-chat --mcp-port 8100
```

Expected ports:

| Port | Owner | Purpose |
| --- | --- | --- |
| 8100 | MCP server | `/mcp`, `/mcp/chat`, `/health`, `/sse` |
| 8201 | Chat API | `/api/chat/*`, `/health` |

Expected durable state files under `$XMUSE_ROOT`:

- `chat.db`
- `god_sessions.json`
- `feature_lanes.json`
- `feature_lanes.json.writer_lease.json` while the runner is active

## Health

Use:

```bash
uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100
```

The JSON includes `operations`:

- `ports`: MCP, MCP chat, and Chat API URLs.
- `readiness.chat_api`: HTTP `/health` readiness when `--health-check-http` is used.
- `readiness.mcp`: HTTP `/health` readiness when `--health-check-http` is used.
- `readiness.runner`: runner process count.
- `readiness.ray_god_layer`: configured backend, transport, and MCP enablement.
- `readiness.codex_app_server`: observed or orphaned Codex app-server process state.
- `durable_state`: `chat.db` and `god_sessions.json` existence.
- `scheduler_progress`: recent peer turn trace status from `chat.db`.
- `cleanup`: leftover Codex app-server and Ray process evidence when no runner owns them.

`xmuse.chat_api` also exposes `/health`. `xmuse.mcp_server` exposes `/health`
with `/mcp`, `/mcp/chat`, `/sse`, `chat.db`, `god_sessions.json`, and MCP auth
metadata.

## Degradation Matrix

| Condition | Expected behavior |
| --- | --- |
| Ray available | use `RayGodSessionLayer` and Ray actors |
| Codex app-server + MCP enabled | use MCP writeback; peer traces show `delivery_mode=mcp_writeback` |
| Ray import/prewarm fails and degraded local mode is disabled | startup/prewarm fails; do not silently run native fallback |
| Ray import/prewarm fails and `XMUSE_DEGRADED_LOCAL_GOD_MODE=1` | use native GOD layer with degraded runtime attributes |
| Provider writes stdout but no MCP side effect | only persists when degraded fallback is explicitly enabled; trace shows `stdout_fallback` |
| Provider unavailable or no real writeback message | scheduler trace records failed/degraded reason; not counted as happy path |

## Shutdown And Cleanup

Normal runner shutdown must:

- stop reconcile/background tasks,
- cancel in-flight lane tasks,
- call `shutdown()` on Ray/app-server GOD layers,
- release the writer lease.

Post-run cleanup check:

```bash
uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100
```

`operations.cleanup.status` must be `clean` when no runner is expected. If it is
`dirty`, inspect `operations.cleanup.leftovers` for `leftover_codex_app_server`,
`leftover_raylet`, `leftover_gcs_server`, or `leftover_ray_worker`.

V11 cleanup contract:

- automated cleanup covers normal runner shutdown: task cancellation, GOD layer
  shutdown, app-server transport shutdown, Ray actor shutdown, and writer lease
  release.
- report-only detection covers post-run leftovers. Health entries such as
  `leftover_codex_app_server`, `leftover_raylet`, `leftover_gcs_server`, and
  `leftover_ray_worker` are reported with `action=report_only` and
  `automated_cleanup=false`; V11 does not kill those processes automatically.
- stale lane repair is separate from process cleanup: stale dispatched lanes may
  be marked failed, but degraded runtime states remain visible.

## Restart And Resume

Ray GOD app-server sessions persist their Codex app-server thread id in
`god_sessions.json` as `provider_session_id` with kind
`codex_app_server_thread`. On restart, `RayGodSessionLayer` passes that id as
`resume_thread_id` and keeps MCP writeback as the required happy path.

The real restart/resume gate is:

```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
```

## Known Risks

- Health HTTP probing is opt-in through `--health-check-http` to avoid making
  normal read-only health summaries block on ports.
- Process discovery is Linux `/proc` based.
- Chat API and MCP have opt-in token plus role/capability gating for mutating
  routes. Read routes remain under the local trust policy until a broader
  deployment decision requires read authentication.
- Fake/local smoke remains useful for installability but does not replace real
  Ray/Codex/MCP writeback evidence.
