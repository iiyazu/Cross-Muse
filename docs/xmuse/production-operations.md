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
export XMUSE_TUI_OPERATOR_ID=operator
export XMUSE_TUI_OPERATOR_ROLE=operator
export XMUSE_TUI_OPERATOR_CAPABILITIES=chat_create_conversation,chat_post_message,chat_bootstrap,chat_approve_proposal,chat_manage_participants,chat_freeze_blueprint,register_god_cli,select_god_cli,release_gate,workflow_write
export XMUSE_MCP_AUTH_TOKEN=<server-token>
export XMUSE_LIVE_MEMORYOS_LITE=1
export XMUSE_MEMORYOS_LITE_URL=<memoryos-lite-base-url>
export XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT=xmuse/work/release_readiness/memoryos-trace.json
export XMUSE_NATURAL_GOD_TRANSCRIPT_PATH=xmuse/work/release_readiness/natural-transcript.json
export XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT=xmuse/work/release_readiness/real-provider-runtime.json
export XMUSE_GITHUB_TRUTH_REPO=iiyazu/Cross-Muse
export XMUSE_GITHUB_TRUTH_PULL_REQUEST=<pr-number>
export XMUSE_GITHUB_TRUTH_BASE_BRANCH=main
export XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS=quality-gates,contract-smoke-gates,real-runtime-integration-gate
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

The TUI reads `XMUSE_CHAT_API_KEY`, `XMUSE_TUI_OPERATOR_ID`,
`XMUSE_TUI_OPERATOR_ROLE`, and `XMUSE_TUI_OPERATOR_CAPABILITIES` and forwards
them as Chat API write headers. This applies to ordinary mutating Chat API
routes as well as operator actions:

- `chat_create_conversation` for `/new` group conversation creation;
- `chat_post_message` for sending human messages;
- `chat_bootstrap` for bootstrap proposal creation and apply;
- `chat_approve_proposal` for proposal approval;
- `chat_manage_participants` for participant add/remove;
- `chat_freeze_blueprint` for `/freeze` blueprint freeze requests;
- `register_god_cli`, `select_god_cli`, and `release_gate` for operator
  actions.
- `workflow_write` for guarded `/lane retry` and `/lane abort` operator
  actions.

`XMUSE_TUI_OPERATOR_ROLE` defaults to `operator` and
`XMUSE_TUI_OPERATOR_ID` defaults to `local-operator`. Capabilities are not
self-granted by the TUI; missing capabilities are forwarded as missing and an
auth-enabled Chat API will reject the write. Read routes remain unauthenticated
until a broader deployment policy decides otherwise.

Operator actions currently use these focused capabilities:

- `register_god_cli` for manual GOD CLI registration;
- `select_god_cli` for per-conversation GOD CLI selection;
- `release_gate` for `/release refresh`, `/release pack`,
  `/release candidates`, `/release attempt`, and
  `/release export <natural|provider|memoryos>`.
- `workflow_write` for guarded lane retry/abort requests.
- `chat_freeze_blueprint` for guarded blueprint freeze requests.

Blueprint freeze is an operator action, not a TUI projection write:

```text
/freeze target_ref=<ref> blueprint_id=<id> goal=<goal> scope=<items> acceptance=<items>
```

The command calls the Chat API operator action endpoint with
`freeze_blueprint`, requires `chat_freeze_blueprint`, and then uses the same
deliberation freeze contract as `/api/chat/conversations/{id}/freeze-blueprint`.
Unresolved blocking objections still block freeze, and the TUI only displays
the audited result.

Lane workflow control is also an operator action, not a projection edit:

```text
/lane retry <lane_id> <current_status> [reason]
/lane abort <lane_id> <current_status> [reason]
```

Both commands call the Chat API operator action endpoint when available, or the
same local `OperatorActionService` fallback when Chat API is unavailable. They
require `workflow_write`, require the operator to provide the current lane
status as a guard, stamp `last_mutation_audit`, and use `LaneStateMachine`
transition rules. If the guard does not match, the state transition is blocked
and the lane is left unchanged.

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

## GOD CLI Registration And Selection

Manual GOD CLI registration is a production control action, not a projection
edit. Use the Chat API operator action endpoint:

```bash
curl -sS http://127.0.0.1:8201/api/chat/operator/actions \
  -H "Content-Type: application/json" \
  -H "X-XMUSE-API-Key: $XMUSE_CHAT_API_KEY" \
  -H "X-XMuse-Operator-Id: operator" \
  -H "X-XMuse-Operator-Role: operator" \
  -H "X-XMuse-Operator-Capabilities: register_god_cli" \
  -d '{
    "action": "register_god_cli",
    "idempotency_key": "operator-register-custom-peer-1",
    "payload": {
      "cli_id": "custom.peer",
      "display_name": "Custom Peer",
      "command_family": "custom-cli",
      "provider_profile_ref": "custom.peer",
      "capabilities": ["peer_god"],
      "supports_persistent_sessions": true,
      "supports_mcp_writeback": true,
      "state_write_allowed": true,
      "proof_level": "real_provider_proof",
      "proof_refs": ["provider-run://custom.peer/live-smoke-1"]
    }
  }'
```

From TUI, use the same contract through slash commands:

```text
/god register cli_id=custom.peer display_name="Custom Peer" command_family=custom-cli provider_profile_ref=custom.peer capabilities=peer_god proof_level=real_provider_proof supports_persistent_sessions=true supports_mcp_writeback=true state_write_allowed=true proof_refs=provider-run://custom.peer/live-smoke-1
/god select custom.peer
```

Manual `peer_god` registration requires `real_provider_proof`, at least one
proof ref, persistent sessions, MCP writeback, and state-write permission. The
registration file (`god_cli_registrations.json`) is ignored runtime state and
records the operator decision plus proof refs. It does not satisfy the
real-provider release gate by itself; release readiness still needs an explicit
real-provider runtime gate artifact.

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
writes `xmuse.production_evidence.v1` gate artifacts. Configured-but-uncaptured
gates are written as blockers. It records environment key names and probe
results only; token/API-key values are not written.

When `XMUSE_GITHUB_TRUTH_REPO` and `XMUSE_GITHUB_TRUTH_PULL_REQUEST` are set,
the command also runs the opt-in read-only GitHub server truth collector and
writes the raw snapshot plus the `github_server_truth` release gate. This can
satisfy `server_side_enforcement_proof` when branch protection/ruleset and
required-check truth are captured. It still cannot create review truth, merge
truth, or `pr_merged`.

When `XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT`,
`XMUSE_NATURAL_GOD_TRANSCRIPT_PATH`, or `XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT`
point at existing artifacts, the command validates and converts those artifacts
through the same release-gate contracts as the standalone capture commands.
Invalid, missing, fake/local, blocked, or stale artifacts remain blockers.

This command does not run MemoryOS, Ray/Codex/OpenCode, or natural GOD
transcript sessions. It creates honest blocker artifacts for those gates until
their live proof artifacts are supplied. For MemoryOS Lite, use
`xmuse-memoryos-live-trace-capture` first, then rerun live-gate status capture
with `XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT` pointing at the captured trace.

## MemoryOS Lite Live Release Gate

Run the explicit opt-in REST capture against a configured MemoryOS Lite service:

```bash
XMUSE_LIVE_MEMORYOS_LITE=1 \
XMUSE_MEMORYOS_LITE_URL=<memoryos-lite-base-url> \
uv run xmuse-memoryos-live-trace-capture \
  --repo-id iiyazu/Cross-Muse \
  --workspace-id xmuse \
  --god-id god-review \
  --conversation-id <conversation-id> \
  --thread-id <thread-id> \
  --blueprint-id <blueprint-id> \
  --feature-id <feature-id> \
  --lane-id <lane-id> \
  --actor-id god-review \
  --content "Live MemoryOS Lite production evidence." \
  --query "production evidence" \
  --source-ref lane:<lane-id> \
  --source-ref blueprint:<blueprint-id> \
  --output xmuse/work/release_readiness/memoryos-trace.json
```

The command uses the REST-only MemoryOS Lite adapter. It creates or reuses the
durable namespace/session binding, ingests source-attributed evidence, builds
context, fetches `/sessions/{session_id}/trace`, and writes an
`xmuse.memoryos_lite_trace.v1` artifact. If trace fetch is unavailable, it
writes a blocked `manual_gap` artifact rather than relabeling a partial run as
`live_service_proof`.

After that live artifact exists, convert it to a release gate artifact:

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

The same MemoryOS trace capture and gate conversion is available through the
audited TUI operator action surface when the live service is explicitly
configured:

```text
/release export memoryos repo_id=iiyazu/Cross-Muse workspace_id=xmuse god_id=<god-id> thread_id=<thread-id> blueprint_id=<blueprint-id> feature_id=<feature-id> lane_id=<lane-id> actor_id=<actor-id> content='<content>' query='<query>'
```

The action is `export_memoryos_live_trace`, requires `release_gate`, requires
`XMUSE_LIVE_MEMORYOS_LITE=1` and `XMUSE_MEMORYOS_LITE_URL`, writes
`xmuse/work/release_readiness/memoryos-trace.json`, then writes
`xmuse/work/release_readiness/artifacts/live-memoryos.json`. It uses the same
REST-only adapter as the CLI command and does not import `memoryos_lite`.

The gate command does not start MemoryOS Lite. It only validates and converts an
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

After a real selected-GOD conversation has produced durable GOD speech-act
messages and provider session metadata, export the transcript artifact:

```bash
uv run xmuse-natural-deliberation-transcript-capture \
  --conversation-id <conversation-id> \
  --chat-db xmuse/chat.db \
  --registry xmuse/god_sessions.json \
  --target-ref blueprint:<blueprint-id> \
  --target-ref lane:<lane-id> \
  --output xmuse/work/release_readiness/natural-transcript.json
```

The transcript export reads durable `chat.db` and `god_sessions.json`. It only
uses `god_speech_act` envelopes from assistant GOD participants and requires
provider session metadata for each participant before emitting
`real_provider_proof`. Deterministic `deliberation` envelopes, single-GOD
transcripts, and missing provider session ids remain `manual_gap`.

After the `xmuse.operator_transcript.v1` artifact exists, convert it to a
release gate artifact:

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

The gate command does not create the natural transcript. It only converts an
already exported transcript into the `natural_deliberation` release gate.

The same export-and-gate conversion is available through the audited TUI
operator action surface:

```text
/release export natural target_ref=blueprint:<blueprint-id>
```

The action is `export_natural_deliberation_transcript`, requires
`release_gate`, reads durable `chat.db` and `god_sessions.json`, writes
`xmuse/work/release_readiness/natural-transcript.json`, then writes
`xmuse/work/release_readiness/artifacts/natural-deliberation.json`. It does not
synthesize GOD messages or provider sessions; weak evidence remains a blocked
gate.

## Real Provider Runtime Release Gate

After a real Ray/Codex/OpenCode fresh/resume runtime soak has produced durable
peer latency traces and provider session metadata, export the runtime artifact:

```bash
uv run xmuse-real-provider-runtime-soak-capture \
  --conversation-id <conversation-id> \
  --fresh-inbox-item-id <fresh-inbox-id> \
  --resume-inbox-item-id <resume-inbox-id> \
  --runtime-backend ray \
  --transport codex-app-server \
  --chat-db xmuse/chat.db \
  --registry xmuse/god_sessions.json \
  --run-id real-soak-<pr-or-release-id> \
  --output xmuse/work/release_readiness/real-provider-runtime.json
```

The soak export reads `peer_turn_latency_traces` from durable `chat.db` and
provider session metadata from `god_sessions.json`. The operator must identify
the fresh and resumed peer inbox traces; probe output alone cannot satisfy this
gate. Fake/local/stdout runtime labels, non-`mcp_writeback` delivery, degraded
turns, missing provider session ids, or non-reused provider sessions remain
`manual_gap`.

After the `xmuse.real_provider_runtime.v1` artifact exists, convert it to a
release gate artifact:

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

The TUI operator action path can export the raw soak artifact and the matching
release gate in one audited step:

```text
/release export provider fresh_inbox=<fresh-inbox-id> resume_inbox=<resume-inbox-id> runtime_backend=ray transport=codex-app-server run_id=<run-id>
```

The action is `export_real_provider_runtime_soak`, requires `release_gate`, and
uses the same durable peer latency trace and `god_sessions.json` inputs as the
CLI capture. The operator must still identify the fresh and resume inbox trace
ids; CLI version probes never satisfy this gate.

The gate command does not start Ray, Codex, OpenCode, or MCP. It only validates
and converts an existing real-provider runtime artifact.

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

The same capture is available through the TUI operator action surface:

```bash
export XMUSE_TUI_OPERATOR_CAPABILITIES=release_gate
uv run xmuse-tui
# in the active group chat:
/release refresh
/release pack
/release candidates
/release attempt natural provider memoryos runtime_backend=ray transport=codex-app-server repo_id=iiyazu/Cross-Muse workspace_id=xmuse god_id=<god-id> thread_id=<thread-id> blueprint_id=<blueprint-id> feature_id=<feature-id> lane_id=<lane-id> actor_id=<actor-id> content='<content>' query='<query>'
/release export natural target_ref=blueprint:<blueprint-id>
/release export provider fresh_inbox=<fresh-inbox-id> resume_inbox=<resume-inbox-id> runtime_backend=ray transport=codex-app-server
/release export memoryos repo_id=iiyazu/Cross-Muse workspace_id=xmuse god_id=<god-id> thread_id=<thread-id> blueprint_id=<blueprint-id> feature_id=<feature-id> lane_id=<lane-id> actor_id=<actor-id> content='<content>' query='<query>'
```

`/release refresh` calls `refresh_live_gate_status` and writes the live-gate
status blocker artifacts under `xmuse/work/release_readiness/artifacts`.
`/release pack` calls `capture_release_evidence_pack` and writes the operator
handoff pack plus nested readiness/audit reports. `/release candidates` calls
`inspect_release_evidence_candidates` and reads durable `chat.db`,
`god_sessions.json`, the peer latency trace table, and redacted MemoryOS env
presence to show whether the operator has enough inputs for the export actions.
It does not create artifacts. `/release attempt` calls
`attempt_release_evidence`, reuses the candidate report, and then invokes the
same release evidence export actions only for candidate inputs that are
export-ready. It writes `release-evidence-attempt.json` under
`xmuse/work/release_readiness` and may write the raw evidence plus matching gate
artifacts for successful export attempts. Missing MemoryOS configuration,
missing peer latency traces, missing natural GOD speech acts, missing runtime
metadata, fake/local labels, and blocked live captures remain blocked
`manual_gap` attempt rows; the attempt action does not start absent services or
upgrade weak evidence. `/release export natural`, `/release export provider`,
and `/release export memoryos` call the matching release evidence export
operator actions and write both the raw evidence artifact and the corresponding
release gate artifact under `xmuse/work/release_readiness`. These TUI paths go
through the Chat API operator action endpoint when available, or the same local
contract service when Chat API is unavailable. These actions require
`release_gate`, write an operator audit row, and restrict operator-supplied paths
to `xmuse/work/release_readiness`.

The refresh action records configured/missing gate status; it does not create
live MemoryOS, GitHub, provider, or natural transcript proof. The export
actions can capture and gate durable evidence, but they do not upgrade weak
inputs: missing MemoryOS live configuration, deterministic transcripts,
single-GOD transcripts, stdout fallback, fake/local runtime labels, or missing
provider session metadata remain blocked/manual-gap evidence.

The refresh operator response includes `gate_statuses`, `blockers`, and
`release_decision` derived from the release gate artifacts it just wrote. The
TUI renders those fields in the command output so the operator can see which
gates remain blocked. This is a read projection over generated artifacts; it
does not replace release readiness capture and does not make the TUI
authoritative.

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
