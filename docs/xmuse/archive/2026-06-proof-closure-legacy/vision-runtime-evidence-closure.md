# Vision Runtime Evidence Closure

Updated: 2026-06-10

This artifact records the evidence closure work after commit `2fdb299`.

It does not claim full xmuse vision runtime closure. It tightens the evidence
pipeline so future live/runtime claims have the right proof level.

## CI Evidence

Default CI now includes the self-iteration proof in `contract-smoke-gates`.

Workflow targets:

```text
tests/xmuse/test_self_iteration_runtime_closure.py
tests/xmuse/test_vision_runtime_evidence_closure.py
src/xmuse_core/platform/execution/subagent_runtime.py
src/xmuse_core/self_iteration/runtime_closure.py
```

Proof level: `contract_proof`.

## Merge Readiness Versus Merge Fact

Fake/local self-iteration writeback no longer writes `pr_merged`.

Default writeback records:

```text
blueprint_frozen
feature_reworked
review_verdict_finalized
merge_readiness_evaluated
```

`merge_readiness_evaluated` records local/fake gate evaluation. It carries:

```text
real_merge_event: false
proof_level: contract_proof
```

`pr_merged` remains available only for real GitHub server-side merge evidence.

Proof level for fake/default gate writeback: `contract_proof`.

## GitHub Server-Side Evidence

Observed through GitHub connector on 2026-06-10:

```text
repository: iiyazu/Cross-Muse
default_branch: main
visibility: public
authenticated connector permissions: admin, maintain, pull, push, triage
```

Observed for commit `2fdb299`:

```text
workflow_runs: []
combined_statuses: []
```

Observed through local `gh api` on 2026-06-10:

```text
gh api repos/iiyazu/Cross-Muse/branches/main/protection
gh api repos/iiyazu/Cross-Muse/rulesets
gh api repos/iiyazu/Cross-Muse/actions/runs
```

All three commands failed because local GitHub CLI is not authenticated:

```text
gh auth login required, or GH_TOKEN must be populated
```

Current server-side conclusion:

- workflow/job names are locally aligned;
- branch protection is not proven;
- required checks are not proven server-side;
- CODEOWNERS enforcement is not proven server-side;
- latest Actions visibility for `2fdb299` is not proven.

Proof level: `manual_gap` until server-side settings/statuses are retrieved.

Current collector boundary:

```text
GitHubServerSideTruthEvidence
build_github_server_side_truth_gap(...)
can_emit_pr_merged(...)
```

This schema can store authenticated server-side facts when available. In the
default no-secrets path it records a `manual_gap` and does not permit
`pr_merged`.

## Long-Run Replay Summary Boundary

The current self-iteration closure exposes:

```text
build_self_iteration_long_run_replay_summary(...)
SelfIterationLongRunReplaySummary
LongRunEvidenceHeartbeat
```

This is a logical replay artifact for lane evidence, review verdict,
patch-forward lineage, and merge-readiness heartbeat order. It does not create a
background runner or live timing proof. Default proof remains contract/fake
runtime proof unless a separate live provider, live MemoryOS, or GitHub
server-side evidence pack is attached.

## Real Multi-GOD Deliberation Evidence

The deterministic fixture remains contract proof only.

The export contract is:

```text
GodDeliberationReplayExport
```

It records:

- transcript source;
- proof level;
- whether the transcript is natural deliberation;
- speech acts;
- source refs;
- derived frozen blueprint.

The contract rejects:

- deterministic/non-natural exports claiming live or real-provider proof;
- natural deliberation exports without live/real proof level.

Proof level today:

- deterministic fixture: `contract_proof`;
- real/natural multi-GOD transcript: `manual_gap` until exported from runtime.

## Live MemoryOS Lite Evidence

Default CI remains fake/no-live.

The opt-in live path is still guarded by:

```text
XMUSE_LIVE_MEMORYOS_LITE=1
XMUSE_MEMORYOS_LITE_URL=<base-url>
```

The adapter now has trace evidence support:

```text
MemoryOSLiteInteropAdapter.fetch_trace(namespace)
MemoryOSLiteTraceEvidence
```

The contract captures:

- session id;
- trace events;
- source refs from trace metadata;
- estimated token count when present;
- `live_service_proof` label.

Proof level:

- mock/default test: `contract_proof`;
- opt-in live run with a real service response: `live_service_proof`.

## Real Ray/Codex/MCP Runtime Soak

This remains operator-run evidence, not default CI proof.

Minimum operator sequence:

```bash
uv run xmuse-chat-api
uv run xmuse-mcp-server
uv run xmuse-platform-runner
```

Provider/runtime prerequisites:

- configure Codex or OpenCode provider credentials outside committed files;
- start the provider app-server if required by the selected provider;
- set `XMUSE_ROOT` to an isolated runtime root;
- configure MemoryOS Lite live env vars only for the live evidence run.

Expected evidence pack:

- real groupchat transcript export with structured GOD speech acts;
- frozen blueprint id and source refs;
- laneDAG and dispatch decisions;
- subagent runtime contract;
- provider/Ray/Codex execution evidence;
- MCP writeback evidence if auth/RBAC is proven;
- MemoryOS Lite ingest/context/trace artifact;
- restart/resume evidence;
- failure degradation evidence;
- GitHub server-side check/review/merge evidence if a PR is used.

Proof level: `manual_gap` until executed and captured.

## Validation

Focused validation for this closure:

```bash
uv run ruff check .
uv run mypy src/xmuse_core/self_iteration/runtime_closure.py src/xmuse_core/integrations/memoryos_lite_interop.py src/xmuse_core/platform/execution/subagent_runtime.py
uv run pytest -q tests/xmuse/test_self_iteration_runtime_closure.py tests/xmuse/test_vision_runtime_evidence_closure.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_memoryos_event_writeback.py tests/xmuse/test_real_runtime_integration_gate.py tests/xmuse/test_package_boundaries.py
```

Goal completion also requires the existing #13-#34 contract regression set to
stay green.
