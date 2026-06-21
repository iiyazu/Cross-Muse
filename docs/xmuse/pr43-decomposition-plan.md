# PR #43 Retirement And Decomposition Plan

## Retirement Plan

- Archive: PR #43 remains a historical umbrella/integration archive only.
- Preserve: keep branch `vision-closure-deliberation-tui`; do not merge, mark ready, or delete it.
- First replacement branch: `codex/minimal-closure-spine-foundation`, based on `origin/main`.
- Open now: one small PR for the minimal closure spine foundation.
- Backlog only: producer/consumer integration, GitHub truth observation, MemoryOS opt-in trace adapter, TUI projection, natural GOD groupchat/provider invocation.
- Do not preserve full PR #43 history in any replacement PR.

## First Slice Boundary

- Authority: local closure spine contract object emitted by `src/xmuse_core/platform/closure_spine.py`; it is not server truth.
- Producer: `evaluate_minimal_closure_spine`.
- Consumer: focused contract tests and future release/review consumers; projections cannot create truth.
- Condition: `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff` preserves stable refs, owner lineage, `manual_gaps`, and `forbidden_claims`.
- Proof level: `contract_proof` only.
- Failure mode: fail closed to `manual_gap`, `blocked`, or `refactor_required`; no review truth, merge truth, live MemoryOS, or full closure claim.

## Backlog

### P0: Minimal closure spine foundation

- Purpose: encode the smallest shared closure chain contract.
- Base: `origin/main`.
- Forbidden claims: all listed below remain forbidden.
- Validation gate: focused spine tests, package boundary tests, ruff, diff check, no `xmuse/__init__.py`.
- Waits for: none.
- Status: replacement PR to be opened or branch pushed.

### P1: Real producer/consumer path

- Purpose: let one lane produce a candidate and review closure contract without proof inflation.
- Base: first replacement PR after merge, or a clearly stacked branch if unmerged.
- Forbidden claims: review truth, merge truth, ready-to-merge, server-side truth.
- Validation gate: producer-owned artifact plus independent consumer verdict that cites it.
- Waits for: P0.

### P2: GitHub truth observation

- Purpose: separate CI/check/review/merge truth and fail closed on stale head/check mismatch.
- Base: `origin/main` after P0, or stacked only if it consumes P0 contracts.
- Forbidden claims: GitHub review truth, merge truth, ready-to-merge, pr_merged unless read from GitHub authority.
- Validation gate: observed head/check/review fields and stale-head negative cases.
- Waits for: P0.

### P3: MemoryOS opt-in trace adapter

- Purpose: keep MemoryOS as opt-in trace/provenance only.
- Base: `origin/main` after relevant closure contract exists.
- Forbidden claims: live_memoryos unless a real trace id/artifact exists.
- Validation gate: adapter preserves source refs and fails closed without live trace evidence.
- Waits for: P0 and any required producer refs.

### P4: TUI/cockpit projection

- Purpose: display upstream closure state without creating truth.
- Base: after upstream proof path exists.
- Forbidden claims: dashboard/TUI truth, review truth, merge truth.
- Validation gate: projection consumes read envelopes only and preserves manual gaps.
- Waits for: P1 or P2, depending on displayed state.

### P5: Natural GOD groupchat/provider invocation

- Purpose: prove identity/binding and speech artifact chain before natural deliberation claims.
- Base: after provider identity and artifact contracts exist.
- Forbidden claims: natural_peer_god_groupchat and live provider proof until real invocation artifacts exist.
- Validation gate: selected provider binding, speech artifact chain, and fail-closed missing-proof cases.
- Waits for: P0 plus provider identity work.

## Forbidden Claims Preserved

- `github_review_truth`
- `ready_to_merge`
- `pr_merged`
- `live_memoryos`
- `worker_output_is_review_truth`
- `local_tests_are_review_truth`
- `server_side_truth`
- `full_l8_l10_closure`
- `full_l1_l11_closure`
- `overnight_readiness`
- `natural_peer_god_groupchat`
