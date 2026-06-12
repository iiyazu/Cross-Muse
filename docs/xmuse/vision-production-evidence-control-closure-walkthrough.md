# Vision Production Evidence-Control Closure Walkthrough

Updated: 2026-06-12

This artifact records the first implementation slice for
`docs/xmuse/vision-production-evidence-control-closure-plan.md`.

It does not claim full production closure. It moves production control from
documents into testable contracts for GOD/CLI selection, TUI operator action
execution, action audit, and release readiness evaluation.

## Current Production Baseline

Observed during this run:

- Branch: `vision-closure-deliberation-tui`.
- `xmuse/__init__.py` remains absent.
- `gh auth status` succeeds for GitHub user `iiyazu` with ssh git protocol.
- `codex --version` returns `codex-cli 0.139.0`.
- `opencode --version` returns `1.17.3`.
- `uv run python` can import Ray: `ray_import=ok:2.55.1`.
- The `ray` shell command is not on PATH.
- `uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100`
  reports Chat API and MCP as unreachable, runner process missing, and cleanup
  status clean.
- The current shell has no configured MemoryOS Lite URL/flag, Ray backend env
  bundle, DeepSeek/OpenCode API key, or TUI operator capability env.

These facts mean live production gates are not satisfied in the current shell.
They are release blockers or operator setup gaps, not fake-runtime successes.

## Implemented Slice

### GOD/CLI Registry

New module:

```text
src/xmuse_core/providers/god_cli_registry.py
```

The registry makes GOD participant selection explicit:

- `codex.god` is exposed as the built-in peer-GOD-capable CLI boundary.
- `opencode.deepseek_flash_worker` remains bounded: code writing and
  deliberation only.
- OpenCode allowed speech acts remain `propose`, `ask`, and `challenge`.
- Manual peer-GOD registration requires persistent sessions, MCP writeback,
  state-write authority, and `real_provider_proof`.
- Selecting a CLI for peer-GOD work returns an explicit allowed/blocked
  selection result.

`build_god_cli_inventory()` is exported through
`src/xmuse_core/platform/provider_read_contracts.py` so read surfaces can show
registered GOD CLI choices.

### Operator Action Contract And Audit

New module:

```text
src/xmuse_core/platform/operator_actions.py
```

The first production operator action is:

```text
select_god_cli
```

It requires the `select_god_cli` capability. Without that capability, the result
is `denied`. If the operator selects a bounded CLI such as OpenCode for peer-GOD
authority, the result is `blocked`.

Every handled action writes an audit row to:

```text
xmuse/work/operator_actions/operator-actions.jsonl
```

This is ignored runtime state. It is useful for operator audit but is not a
durable authority replacement.

### TUI Control Surface

The TUI now has a production-control route:

```text
/god select <cli_id>
```

Adapter behavior:

- `XmuseAdapter.run_operator_control_action(...)` routes the request through
  `OperatorActionService`.
- TUI operator capabilities come from
  `XMUSE_TUI_OPERATOR_CAPABILITIES`.
- Without `XMUSE_TUI_OPERATOR_CAPABILITIES=select_god_cli`, `/god select` is
  denied instead of mutating state.
- TUI command events now accept `operator_action_contract` and
  `operator_evidence_action` as recorded surface authorities.

This is intentionally not a direct projection write. Selection goes through a
contract service and emits audit evidence. The current production-control path
also exposes the action through Chat API:

```text
POST /api/chat/operator/actions
GET /api/chat/operator/god-cli-selections/{conversation_id}
```

The API reads operator identity from `X-XMuse-Operator-Id` and operator
capabilities from `X-XMuse-Operator-Capabilities`. A successful `select_god_cli`
call persists the selected CLI in:

```text
xmuse/god_cli_selections.json
```

That file is runtime state. It records the selected CLI per conversation with
`source_authority=operator_action_contract`, `proof_level=contract_proof`, and
the audit id that authorized the write. The TUI adapter now attempts this Chat
API path first and falls back to the same local contract service only when the
API is unavailable. If Chat API explicitly rejects the request, the TUI surfaces
that rejection and does not perform a local write.

### Bootstrap Session Authority

The default Chat API conversation path creates durable bootstrap peer sessions
and bootstrap fork lineage. That lineage is production evidence, not a UI leak.
The public read model now treats it as baseline evidence while preserving
workspace isolation for cards, worklist summaries, and lane health.

`GodSessionRegistry` now rejects duplicate durable sessions for the same
`conversation_id` and `participant_id`. This keeps peer lineage and provider
binding resolution deterministic after restart and prevents manual session
registration from silently shadowing an existing bootstrapped peer.

### Release Readiness Contract

New module:

```text
src/xmuse_core/platform/release_readiness.py
```

It evaluates release gates with explicit proof-level requirements:

- local validation requires `contract_proof`;
- internal review requires `internal_review_proof`;
- MemoryOS live gate requires `live_service_proof`;
- GitHub server truth requires `server_side_enforcement_proof`;
- GitHub merge truth requires `server_side_merge_proof`;
- real provider gate requires `real_provider_proof`.

The evaluator blocks fake/local proof from satisfying production live gates and
blocks internal review from substituting for GitHub server enforcement.

### Chat API Auth/RBAC

Chat API mutating routes now have an opt-in token and role/capability gate:

```text
XMUSE_CHAT_API_AUTH_TOKEN=<server-token>
XMUSE_CHAT_API_KEY=<client-token>
X-XMUSE-API-Key: <client-token>
X-XMuse-Operator-Role: operator
X-XMuse-Operator-Capabilities: chat_create_conversation,select_god_cli
```

With auth enabled, API key proves caller authentication, but it does not grant
write authority by itself. `viewer` cannot mutate, `admin` can mutate, and
`operator` / `god` must present the required route capability. The TUI forwards
`XMUSE_CHAT_API_KEY` for operator action calls.

`XMUSE_DEPLOYMENT_PROFILE=production` now makes Chat API startup fail closed
when no Chat API write token is configured. Default no-secrets development and
contract-test runs keep the profile unset.

### MCP HTTP Auth/RBAC

MCP JSON-RPC `tools/call` execution now has an opt-in token and
role/capability gate for mutating tools:

```text
XMUSE_MCP_AUTH_TOKEN=<server-token>
X-XMUSE-API-Key: <client-token>
X-XMuse-Operator-Role: operator
X-XMuse-Operator-Capabilities: enqueue_lane
```

With auth enabled, read-only MCP tools such as `list_lanes` remain readable
without a token under the current local trust policy. Mutating tools require a
matching token, an allowed role, and the exact tool capability for non-admin
callers. The gate runs before tool execution and does not replace audit guards
or GOD session identity checks.

The MCP `/health` response now reports:

```text
auth.write_auth_enabled
auth.read_tools_require_token
```

`XMUSE_DEPLOYMENT_PROFILE=production` also makes MCP startup fail closed when
no MCP write token is configured.

### Release Readiness Capture

New command:

```text
uv run xmuse-release-readiness-capture --artifacts-dir <dir> --output <report.json>
```

The command reads JSON release gate artifacts, evaluates them with
`evaluate_release_readiness`, writes a redacted
`xmuse.release_readiness_report.v1` report, and never upgrades fake/local proof
into live/server/provider proof. Token/API-key shaped strings in commands,
refs, and artifact paths are replaced with `<redacted>`.

### Live Gate Status Capture

New command:

```text
uv run xmuse-live-gate-status-capture --output-dir <artifact-dir>
```

The command writes required release-gate artifacts for:

- `live-memoryos`
- `github-server-truth`
- `real-provider-runtime`
- `natural-god-deliberation`

It detects configured or missing live-gate prerequisites from environment key
presence and local probes (`gh auth status`, `codex --version`,
`opencode --version`, and Ray import). It writes only environment key names and
probe results, not secret values.

Configured-but-uncaptured gates are written as `blocked`; missing required
gates are written as `manual_gap`. All generated gates use `proof_level` of
`manual_gap`, so the artifacts can drive release-readiness blockers without
pretending that live MemoryOS, GitHub server truth, real provider runtime, or
natural GOD transcript proof was captured.

A local `/tmp` status capture plus readiness aggregation in this slice produced
`decision=blocked` with four `manual_gap` gates:

- GitHub server truth: configured through `gh auth status`, but server truth
  capture was not run.
- Live MemoryOS: not configured in the current shell.
- Natural GOD deliberation: no natural transcript artifact configured.
- Real provider runtime: Codex/OpenCode/Ray probes are visible, but no real
  provider runtime soak artifact was captured.

### GitHub Server Truth Release Gate

`scripts/github_server_truth_capture.py` now accepts:

```text
--release-gate-output <gate.json>
```

The raw GitHub truth snapshot still returns exit code `0` only when
`can_emit_pr_merged=true`. For draft/unmerged PRs it can return exit code `2`
while still writing a release gate artifact. The release gate artifact is
limited to `github_server_truth`: it may use `server_side_enforcement_proof`
when branch protection/ruleset and required check truth are captured, but it
does not claim review truth, merge truth, or `pr_merged`.

Running the collector against draft PR #43 produced:

- raw GitHub truth: `proof_level=manual_gap`,
  `gap_reason=missing server-side truth: review_truth, merge_truth`;
- release gate: `gate_id=github-server-truth`, `status=ok`,
  `proof_level=server_side_enforcement_proof`;
- release readiness over that single gate: `decision=ready`;
- combined readiness over live status blockers plus PR #43 GitHub gate:
  `decision=blocked`, with GitHub satisfied and MemoryOS, natural transcript,
  and real provider runtime still blocking;
- full production readiness remains blocked by MemoryOS, natural transcript,
  and real provider runtime gates.

Release readiness capture now deduplicates artifacts by `gate_id`, preferring
the strongest non-blocking proof. This lets a later GitHub server truth gate
replace the earlier `xmuse-live-gate-status-capture` GitHub blocker without
letting stale status artifacts contaminate the report.

### Internal Review Release Gate

New command:

```text
uv run xmuse-internal-review-gate-capture \
  --artifact <xmuse.internal_review.v1.json> \
  --expected-head-sha <head-sha> \
  --output <gate.json>
```

The command converts a structured internal review artifact into an
`internal_review` release gate. It emits `internal_review_proof` only when:

- `schema_version` is `xmuse.internal_review.v1`;
- `reviewer` is present;
- `reviewed_head_sha` matches the expected head SHA;
- `decision` is `approved`;
- no open `critical` or `important` findings remain.

Anything else writes a blocked `manual_gap` gate. This artifact is internal
review truth only; it is not GitHub server-side enforcement and does not affect
`pr_merged`.

### Natural GOD Deliberation Release Gate

New command:

```text
uv run xmuse-natural-deliberation-gate-capture \
  --artifact <xmuse.operator_transcript.v1.json> \
  --output <gate.json>
```

The command converts an explicit natural transcript artifact into the
`natural_deliberation` release gate. It emits an `ok` gate only when:

- `schema_version` is `xmuse.operator_transcript.v1`;
- `proof_level` is `real_provider_proof`;
- `natural_deliberation` is `true`;
- at least two distinct GOD participants are present;
- provider/session metadata exists for each GOD participant;
- no unresolved transcript blockers remain.

Deterministic replay and `contract_proof` transcripts write blocked
`manual_gap` gates. A real transcript with unresolved blockers keeps
`real_provider_proof` but remains blocked, so release readiness cannot become
`ready` until the blockers are resolved.

### Real Provider Runtime Release Gate

New command:

```text
uv run xmuse-real-provider-runtime-gate-capture \
  --artifact <xmuse.real_provider_runtime.v1.json> \
  --output <gate.json>
```

The command converts an explicit real-provider runtime soak artifact into the
`real_provider` release gate. It emits an `ok` gate only when:

- `schema_version` is `xmuse.real_provider_runtime.v1`;
- `proof_level` is `real_provider_proof`;
- provider id, provider session id, runtime backend, and transport are present;
- backend/transport are not fake, fixture, local, or stdout fallback paths;
- every turn uses `delivery_mode: mcp_writeback` with no degraded reason;
- every turn has finite ordered stage timings for Ray delivery, provider turn,
  chat post, and trace persistence;
- the artifact contains both fresh and resume turns;
- restart/resume evidence proves the same provider session id was reused;
- no unresolved runtime blockers remain.

Contract/fake proof, fake transports, stdout fallback, missing stage timings,
and missing restart/resume evidence write blocked `manual_gap` gates. A real
soak artifact with unresolved blockers keeps `real_provider_proof` but remains
blocked.

## Proof-Level Summary

| Surface | Current proof | Boundary |
| --- | --- | --- |
| GOD/CLI registry | `contract_proof` | Defines selectable boundaries; does not prove live CLI runtime. |
| `/god select` route | `contract_proof` | TUI action path calls Chat API first; no live operator session proof. |
| Operator action audit | `contract_proof` | JSONL audit row written in test/runtime path; not durable authority. |
| GOD CLI selection store | `contract_proof` | Durable per-conversation selection record; does not prove live CLI runtime. |
| GOD session registry | `contract_proof` | Enforces one durable session per conversation participant; no live runtime proof. |
| Chat API workspace isolation | `contract_proof` | Full Chat API regression passes; no live multi-user soak. |
| Chat API Auth/RBAC | `contract_proof` | Token + role/capability gate tested in-process; no live service proof. |
| MCP Auth/RBAC | `contract_proof` | Token + role/capability gate tested in-process; no live service proof. |
| Production auth startup profile | `contract_proof` | `XMUSE_DEPLOYMENT_PROFILE=production` fails closed without Chat API/MCP write tokens; no live service proof. |
| Release readiness evaluator | `contract_proof` | Blocks proof contamination; no live gate captured. |
| Live gate status capture command | `contract_proof` | Captures configured/missing gate status as `manual_gap` blocker artifacts; does not create live proof. |
| Release readiness capture command | `contract_proof` | Aggregates and redacts supplied gate artifacts; does not capture live services by itself. |
| Internal review release gate command | `contract_proof` | Converts a verified structured internal review artifact into `internal_review_proof`; does not replace GitHub enforcement. |
| Natural GOD deliberation gate command | `contract_proof` | Converts explicit natural transcript artifacts into a `natural_deliberation` gate; deterministic replay and single-GOD artifacts remain blocked. |
| Real provider runtime gate command | `contract_proof` | Converts explicit real-provider runtime soak artifacts into a `real_provider` gate; fake/stdout/local artifacts remain blocked. |
| MemoryOS live gate | `manual_gap` | Env not configured in current shell. |
| Natural GOD transcript evidence | `manual_gap` | No fresh real multi-GOD transcript artifact has been captured in this slice. |
| Ray/Codex/OpenCode live gate | `manual_gap` | Binaries/Ray import exist, but production services/env are not running/configured. |
| GitHub server truth | `server_side_enforcement_proof` | PR #43 branch protection and required checks were captured; review truth and merge truth remain missing, so no `pr_merged`. |

## Validation

Focused validation run during this slice:

```bash
uv run pytest tests/xmuse/test_god_cli_registry.py tests/xmuse/test_operator_actions.py tests/xmuse/test_release_readiness.py -q
uv run pytest tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_selects_god_cli_with_capability tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_denies_without_capability tests/xmuse/test_tui_adapter.py::test_adapter_records_operator_action_tui_command_event tests/xmuse/test_tui_navigation.py::test_chat_screen_help_command_lists_slash_commands tests/xmuse/test_tui_navigation.py::test_chat_screen_god_select_runs_operator_control_action -q
uv run pytest tests/xmuse/test_god_session_registry.py tests/xmuse/test_chat_api.py -q
uv run pytest tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_peer_forks.py -q
uv run pytest tests/xmuse/test_god_cli_selection_store.py tests/xmuse/test_operator_actions.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_provider_read_contracts_module.py -q
uv run pytest tests/xmuse/test_production_hardening.py tests/xmuse/test_chat_api.py -q
uv run pytest tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_prefers_chat_api_contract tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_does_not_fallback_after_api_rejection -q
uv run pytest tests/xmuse/test_mcp_server.py -q
uv run pytest tests/xmuse/test_production_hardening.py tests/xmuse/test_mainline_contract_docs.py -q
uv run pytest tests/xmuse/test_mcp_server.py tests/xmuse/test_production_hardening.py tests/xmuse/test_depth_hardening_contracts.py -q
uv run pytest tests/xmuse/test_mainline_contract_docs.py tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/xmuse/test_production_hardening.py::test_chat_api_production_profile_requires_write_auth_token tests/xmuse/test_production_hardening.py::test_chat_api_production_profile_uses_env_write_auth_token tests/xmuse/test_mcp_server.py::test_mcp_production_profile_requires_write_auth_token tests/xmuse/test_mcp_server.py::test_mcp_production_profile_uses_env_write_auth_token -q
uv run pytest tests/xmuse/test_production_hardening.py tests/xmuse/test_mcp_server.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_mainline_contract_docs.py tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/xmuse/test_chat_api.py -q
uv run pytest tests/xmuse/test_depth_hardening_contracts.py tests/xmuse/test_production_operations_doc.py tests/xmuse/test_quality_gates_phase3.py -q
uv run pytest tests/xmuse/test_mcp_server.py tests/xmuse/test_production_hardening.py -q
uv run pytest tests/xmuse/test_release_readiness_capture.py -q
uv run pytest tests/xmuse/test_release_readiness_capture.py tests/xmuse/test_release_readiness.py -q
uv run pytest tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_production_operations_doc.py tests/xmuse/test_mainline_contract_docs.py -q
uv run pytest tests/xmuse/test_release_readiness_capture.py tests/xmuse/test_release_readiness.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/xmuse/test_release_readiness_capture.py tests/xmuse/test_release_readiness.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_production_operations_doc.py tests/xmuse/test_mainline_contract_docs.py tests/xmuse/test_package_boundaries.py -q
uv run xmuse-release-readiness-capture --help
uv run pytest tests/xmuse/test_live_gate_status_capture.py -q
uv run xmuse-live-gate-status-capture --help
uv run xmuse-live-gate-status-capture --output-dir /tmp/xmuse-live-gate-status
uv run xmuse-release-readiness-capture --artifacts-dir /tmp/xmuse-live-gate-status --output /tmp/xmuse-release-readiness.json
uv run pytest tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_release_readiness_capture.py -q
uv run pytest tests/xmuse/test_internal_review_release_gate.py -q
uv run xmuse-internal-review-gate-capture --help
uv run python scripts/github_server_truth_capture.py --repo iiyazu/Cross-Muse --pull-request 43 --output /tmp/xmuse-pr43-github-truth.json --release-gate-output /tmp/xmuse-pr43-release-gates/github-server-truth.json --base-branch main
uv run xmuse-release-readiness-capture --artifacts-dir /tmp/xmuse-pr43-release-gates --output /tmp/xmuse-pr43-readiness.json
uv run xmuse-live-gate-status-capture --output-dir /tmp/xmuse-combined-release-gates/live_gate_status
uv run python scripts/github_server_truth_capture.py --repo iiyazu/Cross-Muse --pull-request 43 --output /tmp/xmuse-combined-github-truth.json --release-gate-output /tmp/xmuse-combined-release-gates/github-server-truth.json --base-branch main
uv run xmuse-release-readiness-capture --artifacts-dir /tmp/xmuse-combined-release-gates --output /tmp/xmuse-combined-readiness.json
uv run ruff check .
git diff --check
```

Observed results:

```text
10 passed
8 passed, 1 warning
43 passed, 1 warning
16 passed, 1 warning
63 passed
37 passed, 1 warning
2 passed
20 passed, 1 warning
11 passed, 1 warning
35 passed, 1 warning
18 passed
4 passed, 1 warning
56 passed, 1 warning
29 passed, 1 warning
12 passed, 1 warning
33 passed, 1 warning
4 passed
7 passed
8 passed
28 passed
31 passed
xmuse-release-readiness-capture help rendered
3 passed
xmuse-live-gate-status-capture help rendered
xmuse-live-gate-status-capture wrote 4 gate artifacts under /tmp/xmuse-live-gate-status
xmuse-release-readiness-capture reported decision=blocked for the /tmp live-gate status artifacts
9 passed
4 passed
xmuse-internal-review-gate-capture help rendered
github_server_truth_capture returned 2 for draft PR #43 and wrote a github_server_truth release gate
xmuse-release-readiness-capture reported decision=ready for the single GitHub server-truth gate
xmuse-release-readiness-capture reported decision=blocked for combined live-gate status plus PR #43 GitHub server-truth gates; blockers were live-memoryos, natural-god-deliberation, and real-provider-runtime
All checks passed
git diff --check clean
```

The warning is the existing Starlette/httpx deprecation warning from FastAPI
`TestClient`.

## Remaining Production Gaps

- Chat API and MCP mutating routes now have Auth/RBAC plus a production
  fail-closed startup profile. Read routes still follow the local trust policy,
  and no live operator/TUI service run has exercised the production token bundle.
- Release readiness capture can aggregate supplied artifacts into a redacted
  blocked/ready/not_evaluated report, but live gate artifacts still need to be
  produced by actual MemoryOS, GitHub, and provider runs.
- Live gate status capture can create honest blocker artifacts for missing or
  configured-but-uncaptured live gates, but those artifacts remain `manual_gap`
  proof and cannot satisfy release readiness.
- GitHub branch protection and required check server truth has been captured for
  PR #43, but review truth and merge truth remain missing. This satisfies the
  `github_server_truth` release gate only; it does not permit `pr_merged`.
- Internal review gate tooling exists, but no independent reviewer artifact has
  been produced for the current PR head. A timed independent Codex review
  attempt expired without artifact and is not counted as proof.
- `/god select` now persists selected GOD CLI per conversation, but this is
  still a CLI selection authority only; it does not prove a live provider
  session is running.
- Live MemoryOS Lite was not configured in the current shell.
- Ray/Codex/MCP services were not running during health check.
- OpenCode binary exists, but `DEEPSEEK_API_KEY` is not configured in this
  shell.
- PR #43 exists as a draft PR. GitHub server enforcement truth was captured,
  but the PR is unmerged and has no review truth artifact attached.
- No natural multi-GOD live transcript was captured.
- Release readiness cannot be `ready` until configured live gates produce real
  evidence or named blockers are resolved.

## Next Recommended Slice

1. Bind selected CLI records into the official conversation/bootstrap
   participant flow where role templates need selected runtime providers.
2. Start the configured Chat API/MCP/platform runner bundle and capture a real
   Ray/Codex/MCP health proof.
3. Create or target a draft PR and run GitHub server truth capture against it.
