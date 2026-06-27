# xmuse Document Status

Updated: 2026-06-27

This file is the document map for the next xmuse development handoff. It
separates current entrypoints from retained historical material so a new session
does not restart old L8-L11, closure-ledger, Path-A, or pre-M7 planning frames.

## Status Labels

| Status | Meaning |
|---|---|
| `default-read` | Read by default for the next natural groupchat A2A goal. |
| `current-contract` | Active product, authority, runtime, or CI contract. |
| `current-policy` | Active engineering behavior, GitHub, archive, or operations policy. |
| `retained-by-test` | Historical or compatibility document kept at its path because tests, code, or evidence strings reference it. |
| `reference-only` | Useful historical context, not an active goal entrypoint or proof source. |
| `archived` | Moved under `docs/xmuse/archive/**`; do not read by default. |

Archived or `reference-only` documents are never proof for a new PR head. If
they are reused, re-verify the current code path and cite them only as context.

## Default Read Set

For the next new `/goal` session, read only:

| Document | Status | Role |
|---|---|---|
| `AGENTS.md` | `default-read` | Repo/package/runtime constraints. |
| `docs/xmuse/README.md` | `default-read` | Document entrypoint and current calibration. |
| `docs/xmuse/document-status.md` | `default-read` | This status map. |
| `docs/xmuse/natural-groupchat-a2a-goal.md` | `default-read` | Vision, calibration, architecture direction. |
| `docs/xmuse/natural-groupchat-a2a-behavior.md` | `default-read` | Authority-first loop behavior, CI/GitHub, parallel tracks. |
| `docs/xmuse/natural-groupchat-a2a-task-plan.md` | `default-read` | Track A/B/C/D task plan. |
| `docs/xmuse/natural-groupchat-a2a-goal-prompt.md` | `default-read` | Concise prompt for `/goal`. |
| `docs/xmuse/goal-copilot-behavior-policy.md` | `default-read` | Read-only copilot/Track D rules. |
| `docs/xmuse/mainline-contracts.md` | `default-read` | Product authority contracts. |
| `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md` | `default-read` | Detailed design source. |
| `/home/iiyatu/clowder-ai` | `default-read` | Natural groupchat reference only. |

## Current Product And Authority Contracts

| Document | Status | Notes |
|---|---|---|
| `docs/xmuse/acceptance-spine.md` | `current-contract` | Durable human-demand acceptance spine. |
| `docs/xmuse/mainline-contracts.md` | `current-contract` | Product mainline and authority boundaries. |
| `docs/xmuse/github-server-side-gate.md` | `current-contract` | GitHub server-side check/review/merge truth boundary. |
| `docs/xmuse/github-review-merge-contract.md` | `current-contract` | PR template, CODEOWNERS, merge-ready contract. |
| `docs/xmuse/memoryos-lite-runtime-compatibility.md` | `current-contract` | MemoryOS Lite compatibility and opt-in live proof boundary. |
| `docs/xmuse/memoryos-governance-contract.md` | `current-contract` | MemoryOS namespace/governance rules; sidecar only unless live proof exists. |
| `docs/xmuse/memoryos-file-separation.md` | `current-contract` | xmuse / MemoryOS file and dependency boundary. |
| `docs/xmuse/mcp-permission-model.md` | `current-contract` | MCP permission model. |
| `docs/xmuse/schema-migration-strategy.md` | `current-contract` | Schema migration strategy. |
| `docs/xmuse/shared-contract-fixtures.md` | `current-contract` | Shared fixture contracts. |
| `docs/xmuse/解耦开发协议.md` | `current-contract` | Layer/event boundary protocol. |

## Current Policies, Operations, And CI

| Document | Status | Notes |
|---|---|---|
| `docs/xmuse/code-quality-and-archive-policy.md` | `current-policy` | Reuse/refactor/archive policy. |
| `docs/xmuse/parallel-development-runbook.md` | `current-policy` | Parallel session coordination. |
| `docs/xmuse/goal-copilot-behavior-policy.md` | `current-policy` | Read-only copilot/Track D behavior. |
| `docs/xmuse/goal-stage-harness.md` | `current-policy` | Stage/evidence vocabulary. |
| `docs/xmuse/production-operations.md` | `current-policy` | Operational commands and expectations. |
| `docs/xmuse/provider-matrix.md` | `current-policy` | Provider support matrix. |
| `docs/xmuse/config-matrix.md` | `current-policy` | Configuration surface. |
| `docs/xmuse/release-checklist.md` | `current-policy` | Release claim boundary. |
| `docs/xmuse/contract-smoke-gates.md` | `current-contract` | CI contract smoke gates. |
| `docs/xmuse/peer-chat-runtime-gate.md` | `current-contract` | Peer-chat runtime focused gate. |
| `docs/xmuse/real-runtime-integration-gate.md` | `current-contract` | Real runtime integration gate contract. |
| `docs/xmuse/quality-gates-and-provider-matrix.md` | `current-contract` | Quality gate/provider mapping. |
| `docs/xmuse/broad-suite-baseline-debt.md` | `current-contract` | Known broad-suite debt ledger. |

## Retained Historical Paths

These documents are not current goal entrypoints. Keep their paths because
tests, code, evidence records, or older contracts still reference them.

| Document | Status | Why retained |
|---|---|---|
| `docs/xmuse/deep-research-03-next-goal.md` | `retained-by-test` | Referenced by `tests/xmuse/test_real_runtime_integration_gate.py`. |
| `docs/xmuse/vision-runtime-evidence-closure.md` | `retained-by-test` | Referenced by tests and debt ledger. |
| `docs/xmuse/vision-runtime-evidence-closure-plan.md` | `retained-by-test` | Referenced by tests and README assertions. |
| `docs/xmuse/vision-runtime-evidence-closure-goal-prompt.md` | `retained-by-test` | Referenced by tests and README assertions. |
| `docs/xmuse/self-iteration-runtime-closure.md` | `retained-by-test` | Referenced by tests and `xmuse_core.self_iteration.runtime_closure`. |
| `docs/xmuse/self-iteration-runtime-closure-plan.md` | `retained-by-test` | Referenced by code and retained closure artifact. |
| `docs/xmuse/opencode-in-long-runtime-evidence-closure.md` | `retained-by-test` | Referenced by GitHub server truth tests. |
| `docs/xmuse/opencode-in-long-runtime-evidence-plan.md` | `retained-by-test` | Referenced by retained evidence closure. |
| `docs/xmuse/github-server-side-gate-live-evidence-2026-06-21.md` | `retained-by-test` | Historical evidence snapshot. |
| `docs/xmuse/github-server-side-gate-live-evidence-2026-06-25.md` | `retained-by-test` | Latest retained GitHub server-side evidence snapshot. |
| `docs/xmuse/acceptance-gated-live-capture-evidence-2026-06-21.md` | `retained-by-test` | Historical acceptance-gated evidence snapshot. |
| `docs/xmuse/acceptance-gated-runner-evidence-2026-06-21.md` | `retained-by-test` | Historical runner evidence snapshot. |

## Reference-Only Top-Level Material

These documents are useful context but should not be read by default for the
next goal.

| Document | Status | Notes |
|---|---|---|
| `docs/xmuse/outer-god-integration-goal.md` | `reference-only` | Older integration goal, still referenced by `xmuse/CODEX_GOAL_HANDOFF.md`. |
| `docs/xmuse/path-a-foundation-first-roadmap.md` | `reference-only` | Older Path-A roadmap. |
| `docs/xmuse/post-patha-global-audit-synthesis.md` | `reference-only` | Older Path-A audit synthesis. |
| `docs/xmuse/post-patha-release-readiness-audit.md` | `reference-only` | Older release readiness audit. |
| `docs/xmuse/real-god-chatgroup-fullchain-loop-decomposition.md` | `reference-only` | Superseded by `natural-groupchat-a2a-*` docs. |
| `docs/xmuse/real-runtime-loop-behavior-policy.md` | `reference-only` | Superseded for the next goal by `natural-groupchat-a2a-behavior.md`. |
| `docs/xmuse/legacy-architecture-debt-audit.md` | `reference-only` | Legacy audit; use for cleanup planning only. |
| `docs/xmuse/self-development-closure-audit.md` | `reference-only` | Older audit. |
| `docs/xmuse/rc-closure-baseline-2026-06-21.md` | `reference-only` | Older RC baseline. |
| `docs/xmuse/tui-slash-command-handoff.md` | `reference-only` | TUI slash command context. |
| `docs/xmuse/v6-legacy-coupling-inventory.md` | `reference-only` | Legacy inventory referenced by legacy audit. |
| `docs/xmuse/session-prompts/` | `reference-only` | Historical parallel session prompts; not the next goal entrypoint. |
| `docs/xmuse/split-export-manifest.json` | `reference-only` | Split export manifest. |
| `docs/xmuse/xmuse-package.pyproject.toml` | `reference-only` | Package template reference. |

## Newly Archived Material

The following redundant old goal/prompt/roadmap docs were moved to:

```text
docs/xmuse/archive/2026-06-pre-overnight-goal/
```

| Archived document | Former role |
|---|---|
| `deep-research-02-next-goal.md` | Old deep-research conversion goal. |
| `deep-research-conversion-roadmap.md` | Old deep-research roadmap. |
| `deep-research-execution-tasks.md` | Old deep-research task expansion. |
| `next-production-goal-design.md` | Superseded production goal design. |
| `opencode-in-long-runtime-evidence-goal-prompt.md` | Superseded OpenCode-in goal prompt. |
| `production-closure-tasks.md` | Superseded closure task ledger. |
| `self-iteration-runtime-closure-goal-prompt.md` | Superseded self-iteration goal prompt. |
| `xmuse-production-strengthening-goal-prompt.md` | Superseded production strengthening prompt. |
| `v10-ci-candidate-audit.md` | Old CI candidate audit. |
| `v11-depth-hardening-inventory.md` | Old depth hardening inventory. |
| `v6-session-vs-shared-memory-boundary.md` | Old V6 boundary note. |
