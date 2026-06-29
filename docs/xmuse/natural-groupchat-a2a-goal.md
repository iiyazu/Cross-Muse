# Natural Groupchat Goal

Updated: 2026-06-30

This is the current `/goal` entrypoint. It supersedes older L8-L11,
closure-ledger, Path-A, pre-M7, runtime-log, and PR-led framing for this goal.

## Read First

- `AGENTS.md`
- `docs/xmuse/README.md`
- `docs/xmuse/document-status.md`
- `docs/xmuse/natural-groupchat-a2a-behavior.md`
- `docs/xmuse/natural-groupchat-a2a-task-plan.md`
- `docs/xmuse/natural-groupchat-a2a-goal-prompt.md`
- `docs/xmuse/mainline-contracts.md`
- `docs/superpowers/specs/2026-06-30-natural-groupchat-kernel-design.md`
- `/home/iiyatu/clowder-ai` as natural groupchat reference only

The 2026-06-30 kernel design has been internalized here. The spec remains a
design-source reference, not a separate operator entrypoint.

## Objective

xmuse's primary vision is:

1. a decentralized natural agent groupchat harness that reduces central-agent
   bias;
2. a strict development-chain harness that consumes durable groupchat decisions
   and proves work through proposal, review, dispatch, execution, GitHub, and
   merge authority.

Track A is therefore kernel-first, not PR-first:

```text
A1 Natural Groupchat Kernel
-> A2 Groupchat Decision Closure
-> A3 Dispatch To Execution Harness
-> A4 Result Writeback To Groupchat
-> A5 Unattended Groupchat Development Loop
```

A1/A2 prove the groupchat itself. A3-A5 prove the downstream development chain.
Do not report PR/CI/guarded merge progress as A1 completion.

## Current Baseline

Static docs baselines help orientation but are not live truth:

- `last_observed_baseline`:
  `5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d` after PR #279 and the PR #259
  dispatch proof split `53dbeb9ace749510e9cb0f82f73cbd4df11ec190`.
- `post_abc_closure_baseline`:
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6` from PR #294, run
  `track-abc-integrated-memoryos-degraded-20260629-01`, conversation
  `conv_c7528fbf03b84755b8d4eb65166aa0a1`, final action
  `final-cce17cc5e0e7`, exact-head CI run `28332878486`, main CI run
  `28332906024`, and GitHub gate evidence
  `github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49`.

Those facts prove useful downstream harness milestones, including one docs-only
A/B/C integrated closure. They do not prove A1/A2 groupchat kernel closure,
production readiness, live MemoryOS authority, frontend completeness, GitHub
review truth, or fully autonomous merge.

Every execution loop must refresh `origin/main`, open PRs, and CI status from
GitHub server facts before acting.

## A1 Authority

A1 proves one `chat.db` conversation can host architect, review, and critic
participants through durable routing and writeback:

```text
chat_messages
-> groupchat_chains
-> groupchat_worklist
-> linked chat_inbox_items
-> structured callback/writeback
-> completed_message_id
```

`GroupchatWorklistScheduler` owns route normalization, guard acceptance, claim
and status transitions, depth, dedup, ping-pong policy, and completion. It
reuses `PeerChatScheduler`, provider service, and inbox delivery. It must not
replace the execution harness.

Text @mentions and local router output are candidate signals only. A route
becomes schedulable authority only after policy accepts it into
`groupchat_worklist`.

## A2 Decision Closure

A2 turns discussion into durable decision refs:

```text
discussion chain
-> architect proposal candidate
-> critic objection or clearance
-> review verdict
-> approved decision or durable blocker
```

An agent saying "approve" in text is not sufficient. Proposal, objection or
clearance, review verdict, decision, and blocker refs must live in authority
stores that A3 can consume.

## Downstream Chain

After A2, the existing harness remains the external execution path:

```text
approved groupchat decision
-> dispatch queue
-> execution harness
-> review/final action
-> PR and exact-head CI when applicable
-> guarded merge or explicit operator blocker
-> result writeback into groupchat
```

A2A SDK is interop, not xmuse authority. MemoryOS is a sidecar. Frontend/API/TUI
are read projections. Ray is optional legacy support, not the default natural
groupchat kernel.

## Clowder-AI Use

Borrow only primitives that make natural groupchat real:

- bounded context assembly;
- mention parsing and code-block stripping;
- one invocation/worklist path with dedupe and loop guards;
- per-session serialization;
- delivery/writeback reconciliation before projection.

Do not copy clowder-ai Redis authority, full UI, rich message stack, or
main/child task-distribution orchestration. xmuse already owns the external
execution harness role.

## Forbidden Claims

Do not claim:

- production-ready natural groupchat;
- A1 completion from PR/CI/merge evidence;
- live MemoryOS authority;
- frontend complete;
- GitHub review truth;
- provider stdout, local tests, worker summaries, or subagent output as proof
  truth;
- Ray-backed production proof;
- autonomous merge without explicit operator authority.
