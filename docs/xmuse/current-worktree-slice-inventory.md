# Current Worktree Slice Inventory

更新日期: 2026-06-16

本文记录当前 `vision-closure-deliberation-tui` worktree 的拆分边界。它不是
closure proof，也不是 PR #43 的 merge/readiness 证明。当前 worktree 处于
已验证且干净状态；后续不得继续把新生产功能默认堆入 PR #43。

## Current Local Truth

- Current branch: `vision-closure-deliberation-tui`
- Current HEAD: `b154021111400863098f11ed98eeb24d6fad9311`
- Worktree state: clean
- Remote CI truth: only applies to remote head `b154021111400863098f11ed98eeb24d6fad9311`
- Local changes are clean and at the verified HEAD
- PR #43 handling: historical umbrella context only; do not add new scope unless
  explicitly instructed

## Split Rule

Before any commit/push, split the dirty worktree into scoped PR candidates. Each
candidate must have one authority/proof path, focused validation, explicit proof
level, manual gaps, and forbidden claims.

Do not use test count, CI success, release evidence, or PR body text as review
truth or merge truth.

## Candidate PR Slices

### Slice 0 - Goal/Git Behavior Policy

Purpose:

- Establish dependency-first, anti-TDD-abuse, OpenCode delegation, and small-PR
  GitHub behavior.

Likely files:

- `AGENTS.md`
- `docs/xmuse/README.md`
- `docs/xmuse/anti-tdd-abuse-policy.md`
- `docs/xmuse/github-git-behavior-policy.md`
- `docs/xmuse/goal-behavior-contract.md`
- `docs/xmuse/development-goal-worker-delegation-policy.md`
- `docs/xmuse/production-closure-wave-map.md`
- `docs/xmuse/next-production-closure-long-goal.md`
- `docs/xmuse/dependency-first-closure-goal-prompt.md`

Proof level: documentation/governance only.

Forbidden claims:

- production runtime closure
- CI verified dirty worktree
- PR #43 merge readiness

Suggested validation:

- `uv run ruff check .`
- `git diff --check`
- `test ! -e xmuse/__init__.py`

### Slice 1 - L8 Recovery Producer And Enforcement

Purpose:

- Produce durable recovery artifacts for gate failure, review retry, review retry
  exhaustion, review rejection, merge failure, stale/pidless dispatch, and
  supervisor preflight recovery blocking.

Likely files:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/platform/runner_recovery_proof.py`
- `src/xmuse_core/platform/overnight_operator_supervisor.py`
- `xmuse/overnight_operator_supervisor.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `tests/xmuse/test_platform_runner.py`
- `tests/xmuse/test_overnight_operator_supervisor.py`

Proof level: contract/local runtime proof only, depending on the sub-slice.

Forbidden claims:

- independent review truth
- broad live runner enforcement
- server truth
- overnight-safe recovery

Suggested validation:

- `uv run pytest tests/xmuse/test_platform_orchestrator.py -q`
- `uv run pytest tests/xmuse/test_platform_runner.py -q`
- `uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q`

Current extraction status:

- Too large for one small PR. Current tracked diff across likely Slice 1 files is
  roughly 2,990 added/deleted lines before untracked/contextual docs.
- Split before commit/push. Do not create a single "L8 recovery" PR with all of
  these files unless the user explicitly accepts the size.

Recommended sub-slices:

#### Slice 1a - Recovery Artifact Foundation And Gate Failure Producer

Purpose:

- Introduce the shared durable `lane_recovery_artifact` writer/dispatch-block
  helper needed by orchestrator paths.
- Produce a retry/refactor recovery artifact after normal gate failure.

Likely files:

- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`

Suggested validation:

- `uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "gate_failure_writes_retry_recovery_artifact or repeated_gate_failure_writes_refactor_required_recovery_artifact or dispatch_lane_blocks_non_retry_recovery_decision"`

Proof boundary:

- Contract/local authority producer only; no review truth, server truth, or
  overnight-safe recovery.

Extraction-ready boundary in the current dirty tree:

- `src/xmuse_core/platform/orchestrator_lane_flow.py`
  - imports required only for this foundation:
    `json`,
    `LaneFailureEvidence`,
    `LaneRecoveryDecision`,
    `LaneRecoveryDecisionType`,
    `LaneRuntimeBudget`,
    `evaluate_lane_recovery`,
    `lane_recovery_artifact_path`
  - keep existing `_lane_recovery_dispatch_block_metadata` behavior and expose
    `build_lane_recovery_dispatch_block_metadata`
  - extract `_record_gate_failure_recovery_artifact`
  - extract shared helpers used by this producer:
    `_lane_runtime_budget`, `_lane_gate_failure_attempt`,
    `_lane_recovery_forbidden_claims`, `_text_list`, `_dedupe_texts`,
    `_relative_artifact_ref`
  - update `dispatch_lane` to call
    `build_lane_recovery_dispatch_block_metadata`
  - update `on_lane_executed` gate-failure branch to call
    `_record_gate_failure_recovery_artifact` after the `gate_failed`
    transition succeeds
- `tests/xmuse/test_platform_orchestrator.py`
  - import `load_lane_recovery_decision`
  - extract tests:
    `test_dispatch_lane_blocks_non_retry_recovery_decision`
    if absent in the target base,
    `test_gate_failure_writes_retry_recovery_artifact`,
    `test_repeated_gate_failure_writes_refactor_required_recovery_artifact`

Do not extract in Slice 1a:

- `record_review_retry_recovery_artifact`
- `record_review_retry_exhaustion_recovery_artifact`
- `record_review_rejection_recovery_artifact`
- `_record_patch_forward_recovery_artifact`
- `record_merge_failure_recovery_artifact`
- platform-runner stale/pidless repair
- overnight supervisor preflight

Clean-base dependency check:

- HEAD `654b418c52cc1487193561f65e0521a5a82f0452` already has
  `_lane_recovery_dispatch_block_metadata`,
  `load_lane_recovery_decision`, and the dispatch recovery-block read path.
- Slice 1a therefore only needs the writer-side foundation and gate-failure
  hook listed above. It does not require the review retry, review verdict,
  merge-failure, platform-runner repair, supervisor, L9, or L10 slices.
- If extracted onto a clean branch, keep the first PR scoped to this writer
  foundation and gate-failure producer; do not carry unrelated hunks from the
  current dirty `orchestrator_lane_flow.py`.

#### Slice 1b - Review Retry And Retry-Exhaustion Recovery Producers

Purpose:

- Write retry-allowed recovery artifacts for retry-eligible review failures.
- Write non-retry `refactor_required` / `suspended` artifacts when review retry
  budget is exhausted.

Likely files:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`

Suggested validation:

- `uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "review_retry_count_increments_on_reconcile_recovery or reconcile_recovers_review_timeout_by_rerunning_review or review_retry_exhaustion_writes_refactor_recovery_artifact or review_infra_exhaustion_writes_suspended_recovery_artifact or review_infra_unavailable_circuit_breaker_respects_backoff or review_infra_unavailable_circuit_breaker_closes_after_backoff"`

Proof boundary:

- Review recovery contract proof only; retry-allowed artifacts must not block
  retry, and exhaustion artifacts must not become independent review truth.

#### Slice 1c - Review Verdict / Patch-Forward / Merge Recovery Producers

Purpose:

- Write durable recovery artifacts when review rejection exhausts retries,
  patch-forward suspends the failed lane, or merge failure requires retry,
  refactor, or suspension.

Likely files:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`

Suggested validation:

- `uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "on_lane_reviewed_patch_forward_writes_recovery_artifact or on_lane_rejected_max_retries_writes_recovery_artifact or on_lane_reviewed_merge_conflict_writes_retry_recovery_artifact or on_lane_reviewed_merge_conflict_retry_exhausted_writes_refactor_artifact or on_lane_reviewed_non_reworkable_merge_writes_suspended_artifact"`

Proof boundary:

- Recovery lineage for failed original lanes only; no patch-lane execution,
  independent review truth, GitHub truth, or release readiness claim.

#### Slice 1d - Platform-Runner Stale/Pidless Dispatch Recovery

Purpose:

- Repair stale or graph-bound pidless dispatched lanes through CAS-guarded
  durable recovery artifacts and prove candidate selection consumes non-retry
  recovery blocks.

Likely files:

- `src/xmuse_core/platform/runner_recovery_proof.py`
- `xmuse/platform_runner.py`
- `tests/xmuse/test_platform_runner.py`

Suggested validation:

- `uv run pytest tests/xmuse/test_platform_runner.py -q -k "repair_stale_dispatched_lanes_marks_dead_worker_exec_failed or candidate_lanes_excludes_non_retry_recovery_decision"`

Proof boundary:

- Local runner recovery authority hardening only; no broad live runner proof or
  overnight-safe proof.

#### Slice 1e - Overnight Supervisor Recovery Preflight

Purpose:

- Block supervisor stage start when durable recovery artifacts contain non-retry
  decisions or invalid artifacts, preserving manual gaps.

Likely files:

- `src/xmuse_core/platform/overnight_operator_supervisor.py`
- `xmuse/overnight_operator_supervisor.py`
- `tests/xmuse/test_overnight_operator_supervisor.py`

Suggested validation:

- `uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q -k "overnight_supervisor_recovery_gate_snapshots_durable_blocks"`

Proof boundary:

- Supervisor preflight contract proof only; still not 8-10 hour overnight-safe
  recovery proof.

### Slice 2 - L9 Local Execution Candidate And Runner Session Boundary

Purpose:

- Keep worker execution evidence as candidate evidence; bind candidates to
  platform-runner session, graph status, worker-evidence bundle, and recovery
  lineage without turning worker output into review truth.

Likely files:

- `src/xmuse_core/platform/local_execution_candidate.py`
- `src/xmuse_core/platform/runner_session.py`
- `src/xmuse_core/platform/feature_graph_claim_coordinator.py`
- `src/xmuse_core/structuring/feature_graph_review_transitions.py`
- `xmuse/platform_runner.py`
- `xmuse/local_execution_candidate_capture.py`
- `tests/xmuse/test_local_execution_candidate.py`
- `tests/xmuse/test_runner_session.py`
- `tests/xmuse/test_feature_graph_claim_coordinator.py`
- `tests/fixtures/xmuse/contracts/artifacts/feature_graph_worker_evidence_submission_plan.v1.json`
- `tests/fixtures/xmuse/contracts/artifacts/feature_graph_review_status_transition_plan.v1.json`

Proof level: contract/API handoff proof only unless a later live run proves more.

Forbidden claims:

- worker output is review truth
- broad live worker execution
- ready_to_merge

Suggested validation:

- `uv run pytest tests/xmuse/test_local_execution_candidate.py tests/xmuse/test_runner_session.py tests/xmuse/test_platform_runner.py -q`

### Slice 3 - L9 Review-Chain Handoff Proof

Purpose:

- Generate and gate `xmuse.god_room_lane_review_chain_proof.v1` from durable
  review closure, patch-forward, patch-lane intake/verdict, candidate, runner
  session, recovery lineage, and graph-wide accounting boundaries.

Likely files:

- `src/xmuse_core/platform/god_room_review_chain_proof.py`
- `src/xmuse_core/platform/god_room_review_handoff.py`
- `xmuse/god_room_review_chain_proof_capture.py`
- `tests/xmuse/test_god_room_review_chain_proof.py`
- related portions of `tests/xmuse/test_chat_api.py`

Proof level: bounded contract/API handoff proof.

Forbidden claims:

- independent review truth
- server truth
- release readiness

Suggested validation:

- `uv run pytest tests/xmuse/test_god_room_review_chain_proof.py tests/xmuse/test_chat_api.py -q`

### Slice 4 - L10 Release / MemoryOS / GitHub Aggregation Consumers

Purpose:

- Let L10 aggregate upstream artifacts only after consumer gates pass, while
  keeping MemoryOS plan, CI truth, GitHub review truth, and merge truth separate.

Likely files:

- `src/xmuse_core/platform/release_evidence_candidates.py`
- `src/xmuse_core/platform/release_evidence_pack.py`
- `src/xmuse_core/platform/github_truth_release_gate.py`
- `src/xmuse_core/platform/god_room_runtime_closure_evidence_capture.py`
- `xmuse/release_evidence_candidates.py`
- `xmuse/release_evidence_pack.py`
- `tests/xmuse/test_release_evidence_candidates.py`
- `tests/xmuse/test_release_evidence_pack.py`
- `tests/xmuse/test_god_room_runtime_closure_evidence_capture.py`

Proof level: aggregation proof only; server-side truth only when fetched from
GitHub/MemoryOS live/server sources.

Forbidden claims:

- live MemoryOS trace without live trace id
- GitHub review truth without server review data
- `pr_merged` without server-side merge proof
- ready_to_merge from CI success alone

Suggested validation:

- `uv run pytest tests/xmuse/test_release_evidence_candidates.py tests/xmuse/test_release_evidence_pack.py tests/xmuse/test_god_room_runtime_closure_evidence_capture.py -q`

### Slice 5 - L3-L7 Public Contract / Chat API Carry-Through

Purpose:

- Preserve actor/source/proof metadata through public chat/API, freeze, laneDAG,
  and graph status contracts. This slice should only be kept if it is required
  by the L8-L10 lineage being split out.

Likely files:

- `src/xmuse_core/chat/api_models.py`
- `xmuse/chat_api.py`
- `src/xmuse_core/structuring/blueprint_execution/lane_dag_service.py`
- `tests/xmuse/test_chat_api.py`
- `tests/xmuse/test_package_boundaries.py`

Proof level: contract/API projection proof.

Forbidden claims:

- natural multi-GOD deliberation closure
- live provider invocation proof
- TUI/cockpit production closure

Suggested validation:

- `uv run pytest tests/xmuse/test_chat_api.py tests/xmuse/test_package_boundaries.py -q`

## Next Operational Cursor

Do not continue feature work on the current heavy branch until the active slice
is explicitly selected and isolated. The preferred next action is to prepare a
small scoped branch or worktree for Slice 1a, followed by Slice 1b. Slice 1 is
the earliest active Wave D dependency, but it is too large as one PR; splitting
it before any commit/push is required.

Recommended first extraction:

```text
Branch/worktree name: wave-d-l8-recovery-gate-foundation
Target: Slice 1a
Plan: docs/xmuse/wave-d-l8-recovery-gate-foundation-extraction-plan.md
Base: current stable base or the explicit stacked base chosen by the user
Validation:
  uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "gate_failure_writes_retry_recovery_artifact or repeated_gate_failure_writes_refactor_required_recovery_artifact or dispatch_lane_blocks_non_retry_recovery_decision"
  uv run ruff check .
  git diff --check
  test ! -e xmuse/__init__.py
```

Recommended second extraction:

```text
Branch/worktree name: wave-d-l8-review-retry-recovery
Target: Slice 1b
Base: Slice 1a branch if the shared recovery helper is not already merged
Validation:
  uv run pytest tests/xmuse/test_platform_orchestrator.py -q -k "review_retry_count_increments_on_reconcile_recovery or reconcile_recovers_review_timeout_by_rerunning_review or review_retry_exhaustion_writes_refactor_recovery_artifact or review_infra_exhaustion_writes_suspended_recovery_artifact or review_infra_unavailable_circuit_breaker_respects_backoff or review_infra_unavailable_circuit_breaker_closes_after_backoff"
  uv run ruff check .
  git diff --check
  test ! -e xmuse/__init__.py
```

If the selected slice depends on unmerged PR #43 content, mark the future PR as
stacked and do not claim standalone merge readiness.
