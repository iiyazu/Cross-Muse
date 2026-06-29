# Natural Groupchat Goal Prompt

Use this prompt directly with `/goal`.

```text
Goal title:
xmuse natural groupchat kernel and development-chain closure.

Repo:
/home/iiyatu/projects/python/xmuse

Objective:
Start from a clean origin/main truth refresh. Track A is kernel-first:
A1 Natural Groupchat Kernel -> A2 Groupchat Decision Closure -> A3 Dispatch To
Execution Harness -> A4 Result Writeback To Groupchat -> A5 Unattended
Groupchat Development Loop.

Track A ladder:
A1 Natural Groupchat Kernel
-> A2 Groupchat Decision Closure
-> A3 Dispatch To Execution Harness
-> A4 Result Writeback To Groupchat
-> A5 Unattended Groupchat Development Loop

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/document-status.md
- docs/xmuse/natural-groupchat-a2a-goal.md
- docs/xmuse/natural-groupchat-a2a-behavior.md
- docs/xmuse/natural-groupchat-a2a-task-plan.md
- docs/xmuse/mainline-contracts.md
- docs/superpowers/specs/2026-06-30-natural-groupchat-kernel-design.md
- /home/iiyatu/clowder-ai as natural groupchat reference only

Static baselines:
- last_observed_baseline:
  5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d after PR #279 and PR #259
  dispatch proof split 53dbeb9ace749510e9cb0f82f73cbd4df11ec190.
- post_abc_closure_baseline:
  07630131dcb6e26c8dc09dcf41690381e5cd0ee6 from PR #294, run
  track-abc-integrated-memoryos-degraded-20260629-01, conversation
  conv_c7528fbf03b84755b8d4eb65166aa0a1, final action
  final-cce17cc5e0e7, PR CI run 28332878486, main CI run 28332906024, GitHub
  gate evidence github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49.
These are static orientation facts, not live GitHub truth.

Operating contract:
- Each loop declares authority, producer, consumer, condition, proof level,
  failure boundary, and forbidden claims.
- A1 authority is chat_messages, groupchat_chains, groupchat_worklist, linked
  chat_inbox_items, and structured callback/writeback.
- Text @mentions and router output are candidate signals only; schedulable
  authority starts when GroupchatWorklistScheduler accepts groupchat_worklist.
- A2 requires durable proposal, objection or clearance, review verdict,
  decision, or blocker refs.
- A3-A5 use the existing execution harness. PR/CI/guarded merge is downstream
  proof, not A1 completion.
- A2A SDK is interop. MemoryOS is sidecar. Frontend is projection. Ray is
  optional legacy.
- Skills, workers, local tests, provider stdout, and subagent audit are
  diagnostics or candidate input only.

Minimum success:
Reach the deepest honest boundary without weakening authority: A1 kernel
closure, A2 decision closure, A3-A5 development-chain closure, or a durable
blocker with source refs and next authority boundary.

PR discipline:
Use domain-scoped main-based PRs only when code or current docs change. Each PR
needs exact-head CI before guarded merge, and main CI observation after merge.

Do not claim:
production-ready natural groupchat, live MemoryOS truth, frontend complete,
GitHub review truth, provider stdout truth, Ray-backed production proof, or
autonomous merge.
```
