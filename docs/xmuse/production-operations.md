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
export XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT=xmuse/work/release_readiness/god-runtime-continuity.json
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

## Production Baseline Capture

Before a long production `/goal` changes behavior, capture the S0 truth map:

```bash
uv run xmuse-production-baseline-capture \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output xmuse/work/release_readiness/production-baseline.json
```

The command writes an ignored runtime artifact with schema
`xmuse.production_baseline.v1`. It records the current git branch/head/dirty
state, verifies that `xmuse/__init__.py` is absent, reports redacted env key
presence, and probes GitHub auth, Codex, OpenCode, and Ray import visibility.
It inventories MemoryOS Lite, GitHub truth target, provider runtime, natural
GOD deliberation, Chat API auth, and MCP auth readiness with blockers and next
actions.

This is `contract_proof` baseline evidence only. It does not call live
MemoryOS, does not run providers, does not call GitHub server truth APIs beyond
the configured auth probe, and does not create release-readiness proof. Missing
or configured-but-uncaptured live inputs stay visible as `manual_gap` blockers
for later S4/S6 evidence capture.

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
  `/release export <natural|provider|memoryos|github>`.
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

After a blueprint is frozen, export the replay artifact from durable
`chat.db` resolution authority:

```bash
uv run xmuse-frozen-blueprint-export \
  --chat-db xmuse/chat.db \
  --conversation-id <conversation-id> \
  --output xmuse/work/release_readiness/mission-blueprint.json
```

Use `--resolution-id <resolution-id>` when the exact approved freeze resolution
is known. The exporter only reads approved `deliberation_freeze` resolutions
with embedded frozen `mission_blueprint.v1` content. It does not read
`feature_lanes.json`, does not write lane status, and does not upgrade draft or
ordinary manual approvals into freeze proof.

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
If internal review evidence is supplied to the GitHub truth collector, it must
be the same structured full-PR/current-head artifact accepted by
`xmuse-internal-review-gate-capture`; arbitrary files or partial reviews do not
satisfy `review_truth`.

For one-off operator runs, the same GitHub target may be supplied directly:

```bash
uv run xmuse-live-gate-status-capture \
  --github-repo iiyazu/Cross-Muse \
  --github-pull-request <pr-number> \
  --github-base-branch main \
  --github-required-check quality-gates \
  --github-required-check contract-smoke-gates \
  --github-required-check real-runtime-integration-gate \
  --github-expected-head-sha "$(git rev-parse HEAD)"
```

These flags populate the same `XMUSE_GITHUB_TRUTH_*` inputs for that command
invocation only; they do not bypass review truth, merge truth, or `pr_merged`.

When `XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT`,
`XMUSE_NATURAL_GOD_TRANSCRIPT_PATH`,
`XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT`, or
`XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT` point at existing artifacts, the command
validates and converts those artifacts through the same release-gate contracts
as the standalone capture commands. Natural deliberation conversion requires
both the transcript and selected-GOD runtime continuity artifacts. Invalid,
missing, fake/local, blocked, or stale artifacts remain blockers.

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
`xmuse.memoryos_lite_trace.v1` artifact. If the live environment is not
configured, or trace fetch is unavailable after an opt-in run, it still writes a
blocked `manual_gap` artifact rather than leaving replay evidence unattached or
relabeling a partial run as `live_service_proof`.

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

The action is `export_memoryos_live_trace`, requires `release_gate`, writes
`xmuse/work/release_readiness/memoryos-trace.json`, then writes
`xmuse/work/release_readiness/artifacts/live-memoryos.json`. When
`XMUSE_LIVE_MEMORYOS_LITE=1` and `XMUSE_MEMORYOS_LITE_URL` are configured, it
uses the same REST-only adapter as the CLI command and does not import
`memoryos_lite`. When the live environment is not configured, it still writes a
blocked `xmuse.memoryos_lite_trace.v1` `manual_gap` artifact and a blocked
`live-memoryos` gate so release replay can cite the exact missing prerequisite.

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

The same read-only capture is available from the TUI/operator action surface:

```text
/release export github repo=iiyazu/Cross-Muse pr=<pr-number> \
  expected_head=<current-head-sha> base=main \
  check=quality-gates,contract-smoke-gates,real-runtime-integration-gate
```

This calls `export_github_server_truth` with `release_gate`, writes
`github-server-truth-snapshot.json` plus
`artifacts/github-server-truth.json` under `xmuse/work/release_readiness`, and
records an operator audit row. It performs read-only `gh api` capture through
the contract handler; it does not create review truth, merge truth, or
`pr_merged`.

## Internal Review Release Gate

Use a structured internal review artifact only after a reviewer has reviewed the
current PR head:

```json
{
  "schema_version": "xmuse.internal_review.v1",
  "review_id": "review-pr-<number>-<head-sha>",
  "reviewer": "codex-reviewer",
  "reviewed_head_sha": "<current-head-sha>",
  "review_scope": "full_pr_current_head",
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
matches the expected head SHA, declares `review_scope=full_pr_current_head`, has
a reviewer, and contains no open critical/important findings. Latest-commit or
partial-scope reviews remain `manual_gap`. It is internal review truth only; it
is not GitHub server-side enforcement.

When assembling a release evidence pack, pass
`--internal-review-expected-head-sha <current-head-sha>` even before the
structured review artifact exists if the handoff must make the missing current
head review explicit. Without `--internal-review-artifact`, the pack writes a
blocked `internal-review` `manual_gap` gate pointing at the expected
`internal-review-input.json` path instead of silently omitting the review gate.

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

Selected-GOD runtime continuity also reads durable `god_sessions.json`.
`GodSessionRegistry.record_heartbeat(...)` records
`last_heartbeat_at_utc` for a GOD session. The continuity view reports
heartbeat freshness from that timestamp; stale or invalid heartbeats block
`peer_god_ready` and remain `manual_gap` until a fresh heartbeat is recorded.
This proves only session-continuity metadata. It does not create live provider
proof, natural transcript proof, GitHub truth, or release readiness by itself.

Export that selected-GOD runtime continuity artifact from durable local stores
before converting the transcript gate:

```bash
uv run xmuse-god-runtime-continuity-capture \
  --conversation-id <conversation-id> \
  --selection-store xmuse/god_cli_selections.json \
  --registration-store xmuse/god_cli_registrations.json \
  --registry xmuse/god_sessions.json \
  --output xmuse/work/release_readiness/god-runtime-continuity.json
```

The command writes `xmuse.god_runtime_continuity.v1` from the durable GOD CLI
selection store, durable manual registration store, and durable GOD session
registry. Missing selection, missing session, missing provider session metadata,
bounded selected CLIs, or stale/invalid heartbeat evidence remains blocked or
`manual_gap`; the capture command never upgrades a selected CLI into peer-GOD
proof by assertion.

The same capture is available through the audited TUI/operator action surface:

```text
/release export god-runtime ttl=300 output=xmuse/work/release_readiness/god-runtime-continuity.json
```

The action is `export_god_runtime_continuity`, requires `release_gate`, and uses
the standard durable stores under `$XMUSE_ROOT`. It does not accept alternate
selection/session store paths through TUI, so the operator console cannot point
release evidence at a hand-edited projection file.

After the `xmuse.operator_transcript.v1` artifact exists, convert it to a
release gate artifact:

```bash
uv run xmuse-natural-deliberation-gate-capture \
  --artifact xmuse/work/release_readiness/natural-transcript.json \
  --god-runtime xmuse/work/release_readiness/god-runtime-continuity.json \
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
`xmuse/work/release_readiness/natural-transcript.json`, captures selected-GOD
runtime continuity from the durable GOD CLI selection, registration, and session
stores to `xmuse/work/release_readiness/god-runtime-continuity.json`, then writes
`xmuse/work/release_readiness/artifacts/natural-deliberation.json`. It does not
synthesize GOD messages or provider sessions; weak evidence remains a blocked
gate.

The default TUI/operator path therefore binds natural transcript export to the
same selected-GOD runtime continuity input required by the release gate. Operators
can pass `ttl=<seconds>` / `heartbeat_ttl=<seconds>` to control heartbeat
freshness and `runtime_output=<path>` to choose a release-root-scoped runtime
artifact path. `god_runtime=skip` is available only for compatibility or replay
debugging; it keeps the older no-runtime gate conversion path and must not be
treated as production release evidence.

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

## Overnight Supervisor Snapshot

Use the supervisor snapshot during long `/goal` runs to keep stage progress,
self-review, blockers, and fallback decisions replayable:

```bash
uv run xmuse-overnight-supervisor \
  --run-id overnight-$(date -u +%Y%m%dT%H%M%SZ) \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S6="fresh GitHub truth" \
  --stage S7="TUI proof cockpit" \
  --stage-priority S6=100 \
  --stage-priority S7=40 \
  start-stage S6
```

Periodic self-review is contract evidence, not live/provider/server proof:

```bash
uv run xmuse-overnight-supervisor \
  --run-id <run-id> \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S6="fresh GitHub truth" \
  --stage S7="TUI proof cockpit" \
  --stage-priority S6=100 \
  --stage-priority S7=40 \
  --resume \
  self-review S6 \
  --summary "reviewed proof boundary and runtime state" \
  --finding "review truth is not merge truth" \
  --decision continue \
  --minutes-since-previous-review 52
```

If a configured live/auth/provider gate blocks, record it as a blocker and keep
the next independent stage moving:

```bash
uv run xmuse-overnight-supervisor \
  --run-id <run-id> \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S6="fresh GitHub truth" \
  --stage S6-pack="release pack after GitHub truth" \
  --stage S7="TUI proof cockpit" \
  --stage-priority S6=100 \
  --stage-priority S6-pack=90 \
  --stage-priority S7=40 \
  --stage-depends-on S6-pack=S6 \
  --resume \
  blocked-fallback S6 \
  --reason "GitHub review truth is configured but unavailable." \
  --failure-class github_review_truth_unavailable \
  --attempted-command "gh api repos/iiyazu/Cross-Muse/pulls/43/reviews" \
  --next-action "continue to independent TUI proof cockpit work"
```

The snapshot and fallback artifacts are ignored runtime state. A
`blocked-fallback` command returning exit code 0 means the blocker was captured
and the next ready independent stage was started. Stages declared with
`--stage-depends-on` are skipped while their dependencies are blocked,
`manual_gap`, running, or pending; ready stages are selected by highest
`--stage-priority` and declaration order. This does not mean the blocked release
evidence became acceptable.

For no-secrets long-run simulation, use virtual time instead of sleeping:

```bash
uv run xmuse-overnight-supervisor \
  --run-id <run-id> \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S4="live gates" \
  --stage S7="TUI proof cockpit" \
  simulate \
  --total-minutes 480 \
  --heartbeat-interval-minutes 15 \
  --self-review-interval-minutes 60 \
  --checkpoint-interval-minutes 120
```

The supervisor snapshot persists `virtual_soaks` with SLO status, max heartbeat
gap, max self-review gap, and violations. Supervisor replay evidence includes
the latest virtual-soak SLO in its summary; a violated SLO becomes
`manual_gap` with a scheduling next action. The TUI proof cockpit projects the
same virtual-soak summary and blocker, including `next=` recovery guidance,
without treating the simulation as live provider, MemoryOS, or GitHub proof.

Repeated failures on the same stage/function boundary are not treated as an
open-ended retry loop. The third matching failure classification marks the
stage blocked with `refactor_required`, writes a supervisor issue queue row,
and emits `failure_refactor_escalation` production evidence. Refactor that
boundary before retrying the same function again.

```bash
uv run xmuse-overnight-supervisor \
  --run-id <run-id> \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S6="fresh GitHub truth" \
  --resume \
  classify-failure S6 \
  --failure-class github_review_truth_unavailable \
  --reason "same GitHub review truth path failed again" \
  --retryable
```

When a bounded `/goal` stage was executed through `scripts/goal_stage_runner.py`,
import its `result.json` into the supervisor snapshot instead of summarizing it
only in prose:

```bash
uv run xmuse-overnight-supervisor \
  --run-id <run-id> \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S4="live gates" \
  --stage S5="docs and validation" \
  --resume \
  import-stage-result /tmp/goal-runs/S4/result.json
```

The import records a `goal_stage_result_imported` production-evidence envelope
with `source_authority=goal_stage_harness`, indexes the result, prompt,
manifest, and engine-output artifacts when present, and updates only the
supervisor stage state. `ok` results are `contract_proof`; blocked stage
results remain `manual_gap` blockers and may start the next ready independent
stage. Repeated imported `retry` results for the same stage feed the same
failure classification policy; the third retry import writes
`refactor_required` escalation evidence instead of keeping the stage in an
open-ended retry loop. This is not lane status authority, review truth, GitHub
truth, release readiness proof, or live runtime proof.

The TUI proof cockpit read model can project the supervisor snapshot's
`goal_stage_results` as an operator-visible stage spine. It shows per-stage
status, proof level, engine, result artifact, blocker reason, and dependency
fallback target when present. This is a projection of supervisor evidence only:
rendering the stage spine does not mutate the supervisor, satisfy release
readiness, or promote a bounded worker to peer-GOD status.

When supervisor production evidence is attached to the replay bundle, the proof
cockpit can also render the replay section's structured `supervisor` detail:
run/stage ids, heartbeat/checkpoint/manual-gap counts, self-review and
blocked-fallback counts, latest stage pointers, and virtual-soak status. These
lines are audit context from the supervisor evidence contract; they are not
durable lane status, release readiness, or live runtime proof.

For CI or local no-secrets rehearsal, use virtual time instead of sleeping for
8 hours. Failure injection is JSON so long `/goal` scripts can record exact
stage, minute, command, and source refs without shell-specific parsing:

```bash
uv run xmuse-overnight-supervisor \
  --run-id overnight-virtual-smoke \
  --artifact-dir xmuse/work/release_readiness/overnight_supervisor \
  --stage S4="live gates" \
  --stage S5-pack="release pack after live gates" \
  --stage S5="docs and validation" \
  --stage-priority S4=100 \
  --stage-priority S5-pack=90 \
  --stage-priority S5=40 \
  --stage-depends-on S5-pack=S4 \
  simulate \
  --total-minutes 480 \
  --heartbeat-interval-minutes 15 \
  --self-review-interval-minutes 60 \
  --checkpoint-interval-minutes 120 \
  --failure-json '{"minute":180,"stage_id":"S4","reason":"GitHub review truth is configured but unavailable.","failure_class":"github_review_truth_unavailable","attempted_command":"gh api repos/iiyazu/Cross-Muse/pulls/43/reviews","source_refs":["github://iiyazu/Cross-Muse/pull/43"]}'
```

The simulation writes the normal supervisor snapshot with `logical_minute`
markers, heartbeats, checkpoints, self-reviews, and blocker/fallback evidence.
It is `contract_proof` only; it proves the state machine and SLO accounting, not
live MemoryOS, provider, GitHub review, or merge truth.

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

The command writes ignored runtime-state reports:

- `evidence-pack.json`;
- `release-readiness.json`;
- `proof-contamination-audit.json`;
- `overnight-replay-bundle.json`.

The pack decision is `contaminated` when the proof audit finds contamination.
Otherwise it mirrors the release-readiness decision: `ready`, `blocked`, or
`not_evaluated`. This command can aggregate existing release-gate artifacts and
can convert explicitly supplied raw live/provider artifacts into release-gate
artifacts before readiness. It does not start live services, call GitHub, run
providers, or turn `manual_gap` blockers into production proof.

For long `/goal` handoff packs, the command can also convert explicit replay
section inputs before assembling the nested overnight replay bundle:

```bash
uv run xmuse-release-evidence-pack \
  --artifacts-dir xmuse/work/release_readiness/artifacts \
  --output xmuse/work/release_readiness/evidence-pack.json \
  --production-baseline xmuse/work/release_readiness/production-baseline.json \
  --goal-stage-result /tmp/goal-runs/S1/result.json \
  --supervisor-snapshot xmuse/work/release_readiness/overnight-supervisor.json \
  --deliberation-transcript xmuse/work/release_readiness/natural-transcript.json \
  --god-runtime xmuse/work/release_readiness/god-runtime-continuity.json \
  --natural-deliberation-transcript xmuse/work/release_readiness/natural-transcript.json \
  --natural-deliberation-god-runtime xmuse/work/release_readiness/god-runtime-continuity.json \
  --github-server-truth xmuse/work/release_readiness/artifacts/github-truth.json \
  --github-expected-head-sha "$(git rev-parse HEAD)" \
  --internal-review-artifact xmuse/work/release_readiness/internal-review.json \
  --internal-review-expected-head-sha "$(git rev-parse HEAD)" \
  --frozen-blueprint xmuse/work/release_readiness/mission-blueprint.json \
  --feature-contract xmuse/work/release_readiness/feature-owner-contract.json \
  --memoryos-live-trace xmuse/work/release_readiness/memoryos-trace.json \
  --real-provider-runtime xmuse/work/release_readiness/real-provider-runtime.json \
  --memoryos-writeback-event xmuse/work/release_readiness/memoryos-writeback-event.json
```

`--production-baseline` attaches the S0 `xmuse.production_baseline.v1` truth
map to the top-level pack summary and `source_reports`. It does not become a
release gate, replay section, live proof, or readiness input; it records the
starting branch/env/resource/blocker state for operator handoff.
`--goal-stage-result` converts one or more goal-stage runner `result.json`
files into the replay `stage_evidence` section. The generated
`goal-stage-production-evidence.json` indexes stage id, engine, status,
attempt, related prompt/manifest/engine-output artifacts, and non-ok blockers.
It is replay/evidence-spine metadata only; it does not become lane status,
review truth, GitHub truth, release readiness proof, or live runtime proof.
`--supervisor-snapshot` generates the replay `supervisor` section from a durable
`xmuse.overnight_supervisor.v1` snapshot. `--deliberation-transcript` generates
the replay `deliberation_transcript` section from an
`xmuse.operator_transcript.v1` artifact and needs `--god-runtime` selected-GOD
continuity before it can become ok production evidence. Omitting that runtime
artifact leaves the replay evidence blocked/manual_gap. `uv run
xmuse-frozen-blueprint-export --chat-db xmuse/chat.db --conversation-id
CONVERSATION --output BLUEPRINT` exports the frozen blueprint artifact from
chat resolution authority; `--frozen-blueprint` then generates the replay
`frozen_blueprint` section from that `mission_blueprint.v1` artifact.
Repeated `--feature-contract` inputs generate the replay `feature_lineage`
section from graph-native `xmuse.feature_owner_execution_contract.v2`
contracts. The v2 contract carries ready-set provenance, explicit lane blocker
refs, and `read_only_contract_no_status_writes`; it is replay evidence, not a
lane status writer.
`uv run xmuse-feature-owner-contract-export --graph-set GRAPH_SET --output-dir DIR`
exports those v2 contracts directly from graph-set JSON authority. It does not
read `feature_lanes.json`, does not write lane status, and requires graph/lane
allowed-file evidence either from graph-set `expected_touched_areas` or explicit
`--allowed-file` arguments.
`--memoryos-governance-plan` and `--memoryos-writeback-event` generate the
replay `memory_governance` section from governed MemoryOS policy inputs.
These replay-section conversions are contract-level handoff evidence only and
must not be passed together with an explicit `--section-artifact` for the same
section. `--natural-deliberation-transcript` writes
`artifacts-dir/natural-deliberation.json` through the same validator as
`xmuse-natural-deliberation-gate-capture`; it requires
`--natural-deliberation-god-runtime` so bounded selected CLIs or missing GOD
runtime rows cannot satisfy release readiness. This flag is separate from
`--deliberation-transcript`, which only creates the replay
`deliberation_transcript` section. `--memoryos-live-trace` writes
`artifacts-dir/live-memoryos.json` through the same validator as
`xmuse-memoryos-live-gate-capture`; it emits `live_service_proof` only when the
raw trace artifact already carries valid live MemoryOS Lite evidence.
`--real-provider-runtime` writes `artifacts-dir/real-provider-runtime.json`
through the same validator as `xmuse-real-provider-runtime-gate-capture`; it
emits `real_provider_proof` only when the raw runtime artifact already proves
real provider MCP writeback and restart/resume continuity. None of these
handoffs create GitHub merge proof. `--github-server-truth` converts an
explicit `github_server_side_truth_capture.v1` raw snapshot into
`artifacts-dir/github-server-truth.json` through the same GitHub server truth
gate builder as `scripts/github_server_truth_capture.py --release-gate-output`.
The pack does not call GitHub itself. Pass `--github-expected-head-sha` for the
current PR head; a stale snapshot remains `manual_gap`. GitHub server
enforcement proof can satisfy the `github_server_truth` release gate, but
review truth, merge truth, and `pr_merged` remain separate server-side facts.
`--internal-review-artifact` writes `artifacts-dir/internal-review.json`
through the same validator as `xmuse-internal-review-gate-capture`. It emits
`internal_review_proof` only for an approved current-head review artifact with
no open critical/important findings. This is internal review truth only; it
does not become GitHub server-side review enforcement.

The same capture is available through the TUI operator action surface:

```bash
export XMUSE_TUI_OPERATOR_CAPABILITIES=release_gate
uv run xmuse-tui
# in the active group chat:
/release refresh
/release pack
/release pack baseline=production-baseline.json
/release pack stage=goal/S1.result.json
/release pack github=artifacts/github-truth.json github_head=<current-head-sha>
/release pack review=internal-review.json review_head=<current-head-sha>
/release candidates repository=iiyazu/Cross-Muse pr=<pr-number> \
  expected_head=<current-head-sha> base=main \
  check=quality-gates,contract-smoke-gates,real-runtime-integration-gate
/release attempt natural provider memoryos github runtime_backend=ray \
  transport=codex-app-server repo_id=iiyazu/Cross-Muse workspace_id=xmuse \
  god_id=<god-id> thread_id=<thread-id> blueprint_id=<blueprint-id> \
  feature_id=<feature-id> lane_id=<lane-id> actor_id=<actor-id> \
  content='<content>' query='<query>' repo=iiyazu/Cross-Muse pr=<pr-number> \
  expected_head=<current-head-sha>
/release export natural target_ref=blueprint:<blueprint-id> ttl=300
/release export god-runtime ttl=300 output=xmuse/work/release_readiness/god-runtime-continuity.json
/release export provider fresh_inbox=<fresh-inbox-id> resume_inbox=<resume-inbox-id> runtime_backend=ray transport=codex-app-server
/release export memoryos repo_id=iiyazu/Cross-Muse workspace_id=xmuse god_id=<god-id> thread_id=<thread-id> blueprint_id=<blueprint-id> feature_id=<feature-id> lane_id=<lane-id> actor_id=<actor-id> content='<content>' query='<query>'
/release export github repo=iiyazu/Cross-Muse pr=<pr-number> \
  expected_head=<current-head-sha> base=main \
  check=quality-gates,contract-smoke-gates,real-runtime-integration-gate
```

`/release refresh` calls `refresh_live_gate_status` and writes the live-gate
status blocker artifacts under `xmuse/work/release_readiness/artifacts`.
`/release pack` calls `capture_release_evidence_pack` and writes the operator
handoff pack plus nested readiness/audit reports. `/release pack key=value`
can pass the same release-root-scoped GitHub snapshot handoff fields as the
CLI, for example `github=artifacts/github-truth.json` and
`github_head=<current-head-sha>`, and the same internal review fields, for
example `review=internal-review.json` and `review_head=<current-head-sha>`.
It can also pass `baseline=production-baseline.json` to attach the S0
production baseline artifact through the same release-root path guard.
It can pass `stage=goal/S1.result.json` to attach goal-stage harness evidence
through the replay `stage_evidence` section, again using only release-root
scoped paths and the audited operator action path.
`/release candidates` calls
`inspect_release_evidence_candidates` and reads durable `chat.db`,
`god_sessions.json`, `god_cli_selections.json`, `god_cli_registrations.json`,
the peer latency trace table, redacted MemoryOS env presence, and
operator-supplied GitHub target fields to show whether the operator has enough
inputs for the export actions. Natural transcript candidates separately report
transcript export readiness and selected-GOD runtime readiness; `export_ready`
is true only when both are ready. Missing selected runtime rows, stale/non-peer
GOD sessions, transcript GODs absent from selected runtime continuity, missing
MemoryOS task inputs, and missing GitHub `repo`/`pull_request_number` fields
are visible before `/release attempt` runs. It does not create artifacts. The
TUI action result also renders compact candidate readiness lines such as:

```text
natural[<conversation-id>]=blocked transcript=ready runtime=blocked peer_gods=0 blockers=selected_god_runtime_missing
```

The action result also shows provider, MemoryOS, and GitHub candidate
readiness; these lines are read-model feedback, not durable state writes.
Natural candidate
rows include
`proof_boundary=candidate_report_is_not_natural_deliberation_proof`, required
transcript schema `xmuse.operator_transcript.v1`, required runtime schema
`xmuse.god_runtime_continuity.v1`, required proof `real_provider_proof`, source
authority, and suggested `attempt_release_evidence` hints. Transcript readiness
and selected-runtime readiness are prerequisites for capture; they do not prove
the natural release gate passed. After the natural release gate is captured, its
artifact can display message/GOD counts, speech-act counts, selected-runtime
presence/readiness, missing session GOD ids, and blocker count in replay/proof
cockpit. Those fields remain read-only audit details. Provider candidate
rows include `proof_boundary=candidate_report_is_not_release_proof`, required
artifact schema `xmuse.real_provider_runtime.v1`, required proof
`real_provider_proof`, source authority, and suggested
`attempt_release_evidence` payload hints. The TUI summary prints provider
`next=` guidance so the operator can move from candidate inspection to an
authorized capture action without mistaking the candidate for release proof.
After a real-provider runtime gate is captured, the release evidence pack and
proof cockpit can display provider id, runtime backend, transport, provider
session id, MCP writeback, restart/resume reuse, turn phases, degraded-turn
count, and blocker count. These fields are read-only audit details; they do not
upgrade fake/manual-gap evidence or replace the gate's status/proof-level
checks.
MemoryOS candidate rows use
`proof_boundary=candidate_report_is_not_live_memoryos_proof`, required schema
`xmuse.memoryos_lite_trace.v1`, required proof `live_service_proof`, redacted
env/payload source authority, and `attempt_release_evidence` hints. They do not
include env values or task `content`/`query` text in payload hints, and they do
not prove the live MemoryOS service responded.
After a live MemoryOS gate is captured, replay/proof cockpit can display
namespace, session id, trace-event count, event kinds, estimated tokens,
source-ref count, blocker count, and live-service proof flag. These fields are
read-only audit details and cannot upgrade contract/fake/manual-gap traces.
GitHub candidate rows use
`proof_boundary=candidate_report_is_not_github_server_truth_proof`, required
gate kind `github_server_truth`, required proof
`server_side_enforcement_proof`, and `attempt_release_evidence` hints for
`repo`, `pull_request_number`, optional expected head, base branch, and
required checks. They only prove target payload completeness; they do not call
GitHub, do not write a server-truth artifact, and cannot emit `pr_merged` or
merge truth.
Fresh GitHub server-truth captures also preserve PR state, draft flag,
mergeability, and merge-state values from the read-only PR API. The proof
cockpit renders these fields as operator context so a draft/open PR cannot be
confused with merge truth.
When `xmuse-release-evidence-pack` converts a raw GitHub snapshot, the pack
also includes a top-level `github_truth` summary with gate/raw artifact refs,
head match, PR state, check counts, enforcement source, review/merge truth
state, and gap reason. This summary is handoff context only; release readiness
still comes from the generated GitHub gate and the server-side merge proof
requirements.
The pack also includes a `release_gates` digest and `proof_level_summary`
derived from the release readiness report. The proof cockpit can render this
digest so operators can scan gate status without opening the readiness JSON,
but the digest is not a replacement authority.
`/release attempt` calls `attempt_release_evidence`, reuses the candidate
report, and then invokes the same release evidence export actions only for
candidate inputs that are export-ready. It writes
`release-evidence-attempt.json` under `xmuse/work/release_readiness` and may
write the raw evidence plus matching gate artifacts for successful export
attempts. Missing MemoryOS configuration, missing peer latency traces, missing
natural GOD speech acts, missing selected GOD runtime continuity, missing
GitHub target fields, missing runtime metadata, fake/local labels, and blocked
live captures remain blocked `manual_gap` attempt rows; the attempt action does
not start absent services or upgrade weak evidence.
Blocked attempt rows carry the candidate `next_action`, and the TUI renders
compact lines such as `attempt[live_memoryos]=blocked next=... blockers=...`.
This is operator guidance only; it does not change the gate status or proof
level.
`/release export natural`, `/release export god-runtime`,
`/release export provider`, `/release export memoryos`, and
`/release export github` call the matching release evidence export
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
