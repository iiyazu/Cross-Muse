# xmuse Documentation Entry

Updated: 2026-06-29

This directory is the current xmuse documentation entrypoint. It is intentionally
an index, not a runtime ledger. Long PR histories, local run transcripts, and
sentinel artifacts belong in status or archive documents.

## Read First

For the current natural groupchat production goal, read:

| Document | Purpose |
| --- | --- |
| `docs/xmuse/document-status.md` | Current document map, baselines, and cleanup boundaries |
| `docs/xmuse/natural-groupchat-a2a-goal.md` | Current vision, baseline, A2A/Ray/MemoryOS boundaries |
| `docs/xmuse/natural-groupchat-a2a-behavior.md` | Authority-first behavior policy and execution discipline |
| `docs/xmuse/natural-groupchat-a2a-task-plan.md` | Track A/B/C task plan and durable stop conditions |
| `docs/xmuse/natural-groupchat-a2a-goal-prompt.md` | Minimal `/goal` prompt |
| `docs/xmuse/mainline-contracts.md` | Product north-star and mainline authority contracts |

External references:

- `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md`
  is design-source context only.
- `/home/iiyatu/clowder-ai` is a natural groupchat implementation reference,
  not xmuse authority.

## Baseline Snapshot

Static documentation baselines are recorded so a future goal can orient quickly,
but they are not live GitHub truth.

- `last_observed_baseline`:
  `5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d` after PR #279. This records the
  older support-chain calibration, including the PR #259 dispatch proof split.
- `post_abc_closure_baseline`:
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6`, produced by PR #294 from run
  `track-abc-integrated-memoryos-degraded-20260629-01`, conversation
  `conv_c7528fbf03b84755b8d4eb65166aa0a1`, final action
  `final-cce17cc5e0e7`, PR head
  `9be3b17190380171756bd8375fcb946247217d7c`, PR CI run `28332878486`, main
  CI run `28332906024`, and GitHub gate evidence
  `github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49`.
  Proof level: one docs-only A/B/C integrated closure.

Every execution loop must refresh `origin/main`, open PRs, and CI status from
GitHub server facts before acting.

## Current Product Mainline

`docs/xmuse/mainline-contracts.md` keeps the north-star:

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS
```

`blueprint freeze 是去中心化 GOD deliberation 与中心化 execution/review 的边界`。
`feature_lanes.json` is a live queue/projection, not authority.

For the current natural groupchat work, the practical runtime route is:

```text
natural groupchat
-> A2A SDK interop / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / exact-head CI / guarded merge
```

Authority rules:

- `chat.db`, inbox, proposal, review verdict, dispatch queue, final action, and
  GitHub server facts are authority.
- A2A SDK is an interop boundary, not proposal/review/dispatch/merge authority.
- MemoryOS is a sidecar for context continuity, not truth creation.
- Frontend/API/TUI are read projections and must not create truth.
- Ray is optional legacy runtime support, not the default natural groupchat path.
- Provider stdout, local tests, and worker summaries are diagnostics unless a
  durable authority surface records them.

## Contract And Gate Docs

These top-level documents are still current because tests, CI contracts, or
operator flows reference them:

| Document | Purpose |
| --- | --- |
| `docs/xmuse/contract-smoke-gates.md` | No-secrets contract smoke CI gate |
| `docs/xmuse/peer-chat-runtime-gate.md` | No-secrets peer-chat runtime focused gate |
| `docs/xmuse/deep-research-03-next-goal.md` | Contract-vs-runtime proof split used by CI docs tests |
| `docs/xmuse/real-runtime-integration-gate.md` | No-secrets real runtime integration gate contract |
| `docs/xmuse/broad-suite-baseline-debt.md` | Known broad-suite baseline gaps |
| `docs/xmuse/memoryos-lite-runtime-compatibility.md` | MemoryOS Lite public compatibility contract |
| `docs/xmuse/github-server-side-gate-live-evidence-2026-06-25.md` | Latest committed GitHub server-side evidence snapshot |
| `docs/xmuse/github-server-side-gate.md` | GitHub server-side gate contract |
| `docs/xmuse/github-review-merge-contract.md` | PR template, CODEOWNERS, and merge-ready contract |
| `docs/xmuse/release-checklist.md` | Release claim boundary |

## Policy Docs

| Document | Purpose |
| --- | --- |
| `docs/xmuse/code-quality-and-archive-policy.md` | Reuse, refactor, archive, and state-write quality rules |
| `docs/xmuse/parallel-development-runbook.md` | Parallel session coordination after interfaces are frozen |
| `docs/xmuse/goal-copilot-behavior-policy.md` | Optional read-only copilot behavior |
| `docs/xmuse/goal-stage-harness.md` | Standard stage/evidence vocabulary |
| `docs/xmuse/production-operations.md` | Operational commands and expectations |
| `docs/xmuse/provider-matrix.md` | Provider support matrix |
| `docs/xmuse/config-matrix.md` | Configuration surface |
| `docs/xmuse/解耦开发协议.md` | Layer and event boundary protocol |

## Archive Rules

Historical material lives under:

```text
docs/xmuse/archive/
```

Rules:

1. Do not treat archived evidence as proof for a new PR head.
2. Do not restart old L8-L11, overnight-readiness, Path-A, or closure-ledger
   framing from archive content.
3. If an archived implementation detail is reused, cite it as reference and
   re-verify the current code path.

Older self-iteration, vision-runtime, and OpenCode-in proof-closure documents
live under `docs/xmuse/archive/2026-06-proof-closure-legacy/`. They remain
testable historical contract material, not current `/goal` entrypoints.

Old `docs/superpowers/specs/` and `docs/superpowers/plans/` remain historical
implementation records because tests and lane history may reference their
paths. They are not the current entrypoint.
