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
export XMUSE_DEPLOYMENT_PROFILE=production
export XMUSE_CHAT_API_URL=http://127.0.0.1:8201
export XMUSE_CHAT_API_AUTH_TOKEN=<server-token>
export XMUSE_CHAT_API_KEY=<same-token-for-tui-client>
export XMUSE_MCP_AUTH_TOKEN=<server-token>
```

`XMUSE_DEGRADED_LOCAL_GOD_MODE=1` is an explicit degraded local mode. It is not
the happy path and must be visible in health/readiness output or lane/peer traces.

`XMUSE_DEPLOYMENT_PROFILE=production` makes Chat API and MCP startup fail closed
when their mutating write-surface tokens are missing. Leave it unset for
no-secrets local contract tests and default development runs.

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

## Live Gate Status Capture

Use this command before the release readiness capture when live MemoryOS,
GitHub, provider, or natural transcript evidence has not yet produced gate
artifacts:

```bash
uv run xmuse-live-gate-status-capture \
  --output-dir xmuse/work/release_readiness/artifacts/live_gate_status
```

The command records which production live gates are configured or missing and
writes `xmuse.production_evidence.v1` gate artifacts with `manual_gap` proof.
Configured-but-uncaptured gates are written as blockers. It records environment
key names and probe results only; token/API-key values are not written.

This command does not run MemoryOS, GitHub server-truth, Ray/Codex/OpenCode, or
natural GOD transcript proof. It creates honest blocker artifacts for the
release-readiness report.

## MemoryOS Lite Live Release Gate

After a live MemoryOS Lite create/ingest/build-context/trace run has written an
`xmuse.memoryos_lite_trace.v1` artifact, convert it to a release gate artifact:

```bash
uv run xmuse-memoryos-live-gate-capture \
  --artifact xmuse/work/release_readiness/memoryos-trace.json \
  --output xmuse/work/release_readiness/artifacts/live-memoryos.json
```

The trace artifact must carry `proof_level: live_service_proof`, a `memory://`
namespace URI, a session id, non-empty trace events, and source refs tying the
trace back to xmuse workflow evidence. Contract traces, fixture/local events,
empty trace events, or malformed token counts write a blocked `manual_gap`
gate.

If the live trace artifact has unresolved blockers, the gate keeps
`live_service_proof` but remains `blocked`, so release readiness cannot become
`ready` until the blockers are resolved.

This command does not start MemoryOS Lite. It only validates and converts an
existing live trace artifact.

## GitHub Server Truth Release Gate

After a draft PR exists, capture GitHub server truth into both a raw GitHub
truth snapshot and a release gate artifact:

```bash
uv run python scripts/github_server_truth_capture.py \
  --repo iiyazu/Cross-Muse \
  --pull-request <pr-number> \
  --output xmuse/work/release_readiness/artifacts/github-truth.json \
  --release-gate-output xmuse/work/release_readiness/artifacts/github-server-truth.json \
  --base-branch main
```

Exit code `2` means the PR is not allowed to emit `pr_merged`; this is expected
for an unmerged draft PR. If branch protection/ruleset and required check truth
were captured, the release gate artifact can still satisfy the
`github_server_truth` gate with `server_side_enforcement_proof`. Review truth
and merge truth remain separate requirements and must not be inferred from this
gate.

## Internal Review Release Gate

Use a structured internal review artifact only after a reviewer has reviewed the
current PR head:

```json
{
  "schema_version": "xmuse.internal_review.v1",
  "review_id": "review-pr-<number>-<head-sha>",
  "reviewer": "codex-reviewer",
  "reviewed_head_sha": "<current-head-sha>",
  "decision": "approved",
  "summary": "No blocking findings.",
  "findings": [],
  "source_refs": ["github:pr:<number>"]
}
```

Convert it to a release gate artifact:

```bash
uv run xmuse-internal-review-gate-capture \
  --artifact xmuse/work/release_readiness/internal-review.json \
  --expected-head-sha <current-head-sha> \
  --output xmuse/work/release_readiness/artifacts/internal-review.json
```

The command writes `internal_review_proof` only when the artifact is approved,
matches the expected head SHA, has a reviewer, and contains no open
critical/important findings. It is internal review truth only; it is not GitHub
server-side enforcement.

## Natural GOD Deliberation Release Gate

After a real multi-GOD conversation has been exported to an
`xmuse.operator_transcript.v1` artifact, convert it to a release gate artifact:

```bash
uv run xmuse-natural-deliberation-gate-capture \
  --artifact xmuse/work/release_readiness/natural-transcript.json \
  --output xmuse/work/release_readiness/artifacts/natural-deliberation.json
```

The transcript must carry `proof_level: real_provider_proof`,
`natural_deliberation: true`, at least two distinct `god_id` participants, and
provider/session metadata for each participant. Any deterministic replay,
`contract_proof`, single-GOD transcript, missing provider session metadata, or
unresolved blocker writes a blocked gate. If unresolved blockers exist, the
gate keeps `real_provider_proof` but remains `blocked`, so release readiness
cannot become `ready`.

This command does not create the natural transcript. It only converts an
already exported transcript into the `natural_deliberation` release gate.

## Real Provider Runtime Release Gate

After a real Ray/Codex/OpenCode runtime soak has written an
`xmuse.real_provider_runtime.v1` artifact, convert it to a release gate
artifact:

```bash
uv run xmuse-real-provider-runtime-gate-capture \
  --artifact xmuse/work/release_readiness/real-provider-runtime.json \
  --output xmuse/work/release_readiness/artifacts/real-provider-runtime.json
```

The artifact must carry `proof_level: real_provider_proof`, provider/session
metadata, real runtime backend and transport values, MCP writeback for every
turn, ordered finite stage timings, and restart/resume evidence that reuses the
same provider session. Deterministic fixtures, fake app-server transports,
`stdout_fallback`, missing stage timings, or missing fresh/resume turns write a
blocked `manual_gap` gate.

If a real soak artifact has unresolved blockers, the gate keeps
`real_provider_proof` but remains `blocked`, so release readiness cannot become
`ready` until the blockers are resolved.

This command does not start Ray, Codex, OpenCode, or MCP. It only validates and
converts an existing real-provider runtime artifact.

## Release Readiness Capture

Use this command to aggregate release gate artifacts into a redacted readiness
report:

```bash
uv run xmuse-release-readiness-capture \
  --artifacts-dir xmuse/work/release_readiness/artifacts \
  --output xmuse/work/release_readiness/report.json
```

The input directory contains JSON gate artifacts with `gate_id`, `kind` or
`release_gate_kind`, `status`, `proof_level`, `configured`, `required`,
`owner`, and `summary`. The output report is ignored runtime state. It redacts
token/API-key shaped strings and evaluates readiness with the same proof-level
rules used by `src/xmuse_core/platform/release_readiness.py`. If multiple
artifacts share the same `gate_id`, the strongest non-blocking proof is used so
fresh live/server evidence can replace earlier status-capture blockers.

## Proof Contamination Audit

Run this command after release gate artifacts are captured and before claiming
release readiness:

```bash
uv run xmuse-proof-contamination-audit \
  --artifacts-dir xmuse/work/release_readiness/artifacts \
  --output xmuse/work/release_readiness/proof-contamination-audit.json
```

The audit scans release gate artifacts for proof contamination. It fails when an
`ok` production gate uses a weak proof level, when a production proof contains
fake/fixture/stdout/local-only markers, or when a `pr_merged`/GitHub merge gate
appears without `server_side_merge_proof` and `can_emit_pr_merged=true`.

`decision: clean` means no contamination was found in the scanned artifacts.
It does not mean missing live gates were satisfied; release readiness still
comes from `xmuse-release-readiness-capture`.

## Release Evidence Pack

Use this command when the operator needs one handoff artifact for the current
release-gate directory:

```bash
uv run xmuse-release-evidence-pack \
  --artifacts-dir xmuse/work/release_readiness/artifacts \
  --output xmuse/work/release_readiness/evidence-pack.json
```

The command writes three ignored runtime-state reports:

- `evidence-pack.json`;
- `release-readiness.json`;
- `proof-contamination-audit.json`.

The pack decision is `contaminated` when the proof audit finds contamination.
Otherwise it mirrors the release-readiness decision: `ready`, `blocked`, or
`not_evaluated`. This command aggregates existing release-gate artifacts only;
it does not start live services, call GitHub, run providers, or turn
`manual_gap` blockers into production proof.

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
