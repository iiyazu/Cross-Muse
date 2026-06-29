# xmuse Document Status

Updated: 2026-06-29

This file is the durable status index for `docs/xmuse/`. Keep `docs/xmuse/README.md` short; record document classification, baselines, and cleanup boundaries here.

## Baselines

`last_observed_baseline`:

- merge commit `5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d`;
- PR #279, head `f3212bba613693cdbb38249fd746fb760064d3c8`;
- main CI run `28323650818`;
- includes the PR #259 dispatch proof split
  `53dbeb9ace749510e9cb0f82f73cbd4df11ec190`;
- not live GitHub truth.

Post-A/B/C milestone:

- `post_abc_closure_baseline`
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6`;
- PR #294, head `9be3b17190380171756bd8375fcb946247217d7c`;
- exact-head CI run `28332878486`;
- main CI run `28332906024`;
- run `track-abc-integrated-memoryos-degraded-20260629-01`;
- conversation `conv_c7528fbf03b84755b8d4eb65166aa0a1`;
- final action `final-cce17cc5e0e7`;
- GitHub gate evidence
  `github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49`;
- proof level: one docs-only A/B/C integrated closure, not production
  readiness, live MemoryOS authority, repeated unattended operation, or
  complete frontend UX.

Recent cleanup baseline:

- Current main cleanup baseline is `44ea08b` after PR #329.
- Rung4 promoted runtime sentinel code was removed from product code in favor
  of archived evidence because it was only a proof artifact.
- Sentinel evidence archive:
  `docs/xmuse/archive/2026-06-rung-sentinel-artifacts.md`.

## Current Goal Package

These files are the active natural groupchat package:

| Document | Status |
| --- | --- |
| `docs/xmuse/natural-groupchat-a2a-goal.md` | Current goal entrypoint |
| `docs/xmuse/natural-groupchat-a2a-behavior.md` | Current behavior policy |
| `docs/xmuse/natural-groupchat-a2a-task-plan.md` | Current task plan |
| `docs/xmuse/natural-groupchat-a2a-goal-prompt.md` | Current prompt handle |
| `docs/xmuse/mainline-contracts.md` | Product contract entry |
| `docs/xmuse/document-status.md` | Status and cleanup index |

## Top-Level Contract Docs

Keep these at `docs/xmuse/` root while tests or current operator flows point to
them:

- `contract-smoke-gates.md`
- `peer-chat-runtime-gate.md`
- `deep-research-03-next-goal.md`
- `real-runtime-integration-gate.md`
- `broad-suite-baseline-debt.md`
- `memoryos-lite-runtime-compatibility.md`
- `github-server-side-gate-live-evidence-2026-06-25.md`
- `github-server-side-gate.md`
- `github-review-merge-contract.md`
- `release-checklist.md`
- `code-quality-and-archive-policy.md`
- `parallel-development-runbook.md`
- `goal-copilot-behavior-policy.md`
- `goal-stage-harness.md`
- `production-operations.md`
- `provider-matrix.md`
- `config-matrix.md`
- `解耦开发协议.md`

## Archive Or Reference Docs

These files remain useful but should not be default `/goal` context unless the
task explicitly targets them:

- `docs/xmuse/archive/2026-06-roadmaps-and-audits/` contains old Path-A,
  deep-research, post-PathA audit, V6/V10/V11, and early integration-roadmap
  documents.
- `docs/xmuse/archive/2026-06-21-evidence/` contains old RC and
  acceptance-gated evidence snapshots.
- `docs/xmuse/archive/2026-06-rung-sentinel-artifacts.md` contains one-off
  Rung/Track runtime proof artifacts.
- `docs/xmuse/archive/2026-06-runtime-loop-legacy/` contains the older
  production-closure and real-runtime loop policy/decomposition documents
  superseded by the natural groupchat goal package.
- `docs/xmuse/archive/2026-06-proof-closure-legacy/` contains older
  self-iteration, vision-runtime, and OpenCode-in proof-closure documents.
  Some tests and compatibility evidence builders still reference these files,
  but they are no longer default docs-root entrypoints.
- `docs/xmuse/archive/2026-06-runtime-root-legacy/` contains old runtime-root
  handoff files, the archived `INIT.md`, the deprecated single-chain
  `state_machine.json`, and an older production-strengthening goal prompt.

If an archived document becomes active again, first promote it into the current
goal package with fresh verification.

## Code Isolation Notes

- Runtime state files (`*.db`, `*.sqlite3`, `*.jsonl`, `feature_lanes.json`,
  `xmuse/work/`, `xmuse/history/`, `xmuse/logs/`, and `.goal-runs/`) are never
  product source.
- Sentinel artifacts are not product modules. Keep their evidence under
  `docs/xmuse/archive/` or current task-plan status; do not leave one-off
  sentinel code under `src/xmuse_core/`.
- A2A, MemoryOS, Ray, frontend, and copilot code may stay in main only when the
  module is an explicit adapter/projection/sidecar boundary and tests enforce
  that it cannot create xmuse authority.
