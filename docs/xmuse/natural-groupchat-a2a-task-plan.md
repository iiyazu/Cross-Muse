# Natural Groupchat Task Plan

Updated: 2026-06-30

This is the compact task reference for
`docs/xmuse/natural-groupchat-a2a-goal-prompt.md`. It intentionally omits PR
ledgers and one-off runtime transcripts. Historical details belong in archived
evidence or GitHub server facts refreshed at runtime.

The design-source reference for the current Track A correction is
`docs/superpowers/specs/2026-06-30-natural-groupchat-kernel-design.md`.

## Minimum Success

This is a staged long goal. It succeeds by reaching the deepest honest boundary
without weakening authority:

- A1 kernel closure: one `chat.db` conversation with architect, review, and
  critic participants routes at least human -> agent -> agent through durable
  `groupchat_worklist`, linked `chat_inbox_items`, structured callback/writeback,
  and depth/dedup/ping-pong guard proof;
- A2 decision closure: the same groupchat path produces durable proposal,
  objection or clearance, review verdict, approved decision, or blocker refs;
- A3-A5 development closure: an A2 decision flows through dispatch, execution,
  result writeback, PR/exact-head CI/guarded merge/main CI when applicable;
- durable blocker: the selected stage stops with source refs, producer,
  consumer, proof level, failure boundary, and next authority boundary.

Support progress does not count as core-chain completion.

## Execution Gate

Before implementation, record:

```text
stage
track_a_stage
primary_track
support_tracks
primary_authority_boundary
support_authority_boundaries
core_chain_progress_target
support_progress_target
producer
consumer
condition
proof_level
failure_boundary
blocked_boundary
timebox
next_primary_action
continue_or_stop_condition
```

Cadence:

1. Refresh live `origin/main`, open PRs, and CI from GitHub server facts.
2. Run the largest reachable chain for the selected stage before patching.
3. Patch or refactor only the first durable blocker.
4. Verify with runtime replay or focused contract tests for the touched
   authority boundary.
5. Use small domain-scoped PRs; merge only after exact-head CI and guarded
   operator approval.
6. Update docs only for milestone, boundary, or blocker changes.

## Track A Ladder

```text
A1 Natural Groupchat Kernel
-> A2 Groupchat Decision Closure
-> A3 Dispatch To Execution Harness
-> A4 Result Writeback To Groupchat
-> A5 Unattended Groupchat Development Loop
```

### A1 Natural Groupchat Kernel

Deliver:

- `groupchat_chains` with conversation id, policy id, root message id,
  scan cursor, status, status reason, and timestamps;
- `groupchat_worklist` with source message, target participant/role, route
  kind, status, depth, dedup key, linked inbox item, completed message, claim
  state, terminal reason, and timestamps;
- linked chat_inbox_items as delivery truth for accepted worklist items;
- `GroupchatWorklistScheduler` for route candidate normalization, guard
  acceptance, enqueue, claim, completion, block, fail, cancel, and cursor
  progress;
- fixed architect/review/critic roster for the first production-shaped kernel;
- deterministic local router for unmentioned human messages;
- policy defaults: `max_depth=3`, human targets <=2, agent targets <=1,
  `max_items_per_tick=1`, ping-pong warn after 2 and block after 4.

Acceptance:

- human -> architect -> critic or review routes through durable worklist and
  linked inbox state;
- provider or deterministic test double writes a durable chat message through
  structured callback/writeback;
- worklist completion requires `completed_message_id`;
- duplicate route, depth limit, missing target, callback missing, and
  ping-pong blocked states are durable and diagnosable;
- provider stdout, local tests, MemoryOS, and frontend projection cannot
  complete worklist items.

Non-goals:

- PR creation;
- guarded merge or main CI;
- MemoryOS continuity;
- frontend UX completeness;
- main/child conversation orchestration;
- multi-lane scheduling;
- execution harness replacement.

### A2 Groupchat Decision Closure

Deliver:

- durable proposal candidate from architect;
- durable critic objection or clearance;
- durable review verdict;
- approved decision or blocker refs consumable by A3;
- projection of unresolved questions or blockers without writing truth.

Acceptance:

- decision closure is stored in authority surfaces, not inferred from raw text;
- unresolved objections block approval;
- A3 consumes only approved decision refs or explicit blocker refs.

### A3 Dispatch To Execution Harness

Deliver:

- approved A2 decision creates or blocks a dispatch queue entry;
- execution harness receives source refs and authority boundary;
- groupchat layer does not write lane status directly.

Acceptance:

- dispatch authority is `chat.db/dispatch_queue` or the current durable dispatch
  store;
- `feature_lanes.json` remains projection/live queue only;
- workers receive enough refs to trace proposal, review, and decision authority.

### A4 Result Writeback To Groupchat

Deliver:

- execution started, execution evidence, review verdict, final action,
  GitHub gate evidence/gap, and main CI observations are written back into the
  conversation when they exist;
- groupchat can continue from durable result refs.

Acceptance:

- provider stdout and worker summaries are diagnostics only;
- GitHub claims cite exact head SHA, check names, run ids, and server facts;
- final-action approval without accepted GitHub gate evidence remains blocked
  or manual-gap state.

### A5 Unattended Groupchat Development Loop

Deliver:

- repeated demand -> discussion -> decision -> dispatch -> execution ->
  writeback -> next decision cycles;
- durable blocker when human input is required.

Acceptance:

- no human routing is needed for ordinary next-step selection;
- loop stops rather than fabricating truth when authority is missing.

## Track B And C

Track B MemoryOS:

- sidecar recall and ingest are optional;
- degraded sidecar state does not block Track A;
- MemoryOS refs are continuity refs, not proposal, review, dispatch, execution,
  GitHub, or merge truth.

Track C frontend/API/UX:

- read-only projection exposes timeline, participants, worklist, proposal,
  decision, dispatch, blockers, final action, GitHub gate/gap, and MemoryOS
  sidecar state when present;
- `write_capabilities` stays empty for peer-chat UX projection;
- projection gaps are explicit blockers or missing-field diagnostics, not truth.

## Baseline Summary

Static baselines:

- `last_observed_baseline`:
  `5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d` after PR #279 and PR #259
  dispatch proof split `53dbeb9ace749510e9cb0f82f73cbd4df11ec190`.
- `post_abc_closure_baseline`:
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6`, PR #294, run
  `track-abc-integrated-memoryos-degraded-20260629-01`, conversation
  `conv_c7528fbf03b84755b8d4eb65166aa0a1`, final action
  `final-cce17cc5e0e7`, PR head
  `9be3b17190380171756bd8375fcb946247217d7c`, exact-head CI run
  `28332878486`, main CI run `28332906024`, GitHub gate evidence
  `github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49`.

Known downstream harness facts from the prior long goal:

- docs-only A/B/C integrated closure reached PR/CI/guarded merge/main CI;
- one low-risk code lane reached proposal, review, dispatch, execution, PR,
  exact-head CI, guarded merge, and main CI;
- local multi-lane runtime proof showed lane-specific success/failure isolation;
- MemoryOS remained degraded sidecar state, not live authority;
- frontend projection exposed read-only status and blockers without write
  capabilities.

These facts are useful but do not prove A1/A2 kernel closure.
They are not live GitHub truth; refresh server facts before acting.

## Validation

Focused validation should match the touched boundary:

- A1: store, router, scheduler, guard, callback/writeback, and integration
  tests around `groupchat_chains` and `groupchat_worklist`;
- A2: proposal, objection/clearance, review verdict, decision/blocker store
  tests;
- A3/A4: dispatch, execution evidence, final action, GitHub gate, and writeback
  tests;
- B/C: MemoryOS sidecar contract tests and read-only projection tests;
- docs: `uv run pytest -q tests/xmuse/test_natural_groupchat_goal_docs.py`.

## Stop Conditions

Stop and report when:

- the same selected-stage boundary fails after a focused refactor;
- progress would require stdout, local tests, worker output, or audit output as
  truth;
- MemoryOS or frontend work displaces Track A without operator choice;
- a PR becomes cross-domain;
- live GitHub facts cannot be collected for a GitHub claim;
- forbidden claims would need to be weakened.

## Final Report Shape

Report:

- selected A1-A5 stage;
- maximum real chain reached;
- authority, producer, consumer, condition, proof level, and failure boundary;
- PR/CI/merge facts only when tied to exact GitHub server evidence;
- Track B/C state as skipped, degraded, contract proof, live proof, projection
  proof, or blocked;
- durable blockers and next authority boundary;
- forbidden claims not made.
