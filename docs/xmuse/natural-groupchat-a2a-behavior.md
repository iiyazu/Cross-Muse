# Natural Groupchat Behavior Policy

Updated: 2026-06-30

This policy governs long `/goal` execution for xmuse natural groupchat,
downstream development-chain proof, MemoryOS sidecar work, frontend projection,
and optional audit helpers.

## Loop Contract

Every implementation loop declares:

```text
track_a_stage
primary_track
authority
producer
consumer
condition
proof_level
failure_boundary
forbidden_claims
```

Run the largest reachable real chain for the selected stage before patching
when the boundary is executable. Passing tests alone is never proof that the
chain works.

## Authority Order

Durable xmuse authority:

```text
chat.db / inbox / proposal / review verdict / dispatch queue / GitHub server facts
```

A1 groupchat-local authority to introduce:

```text
chat_messages / groupchat_chains / groupchat_worklist / linked chat_inbox_items / structured callback writeback
```

Projection or diagnostic surfaces:

```text
provider stdout
streamed text
worker summary
frontend card
feature_lanes.json projection
A2A task status before xmuse normalization
skill or subagent output
local tests
MemoryOS recall
```

Text @mentions and local router output are candidate signals only. A route
becomes schedulable authority only after `GroupchatWorklistScheduler` accepts it
into `groupchat_worklist`.

Provider or A2A output must pass through a writeback reconciliation boundary:

```text
provider result / A2A task / MCP callback
-> normalized message or envelope
-> inbox reply linkage
-> proposal/review/dispatch gate
-> read-only projection
```

## Track A Order

Track A is the default primary track:

```text
A1 Natural Groupchat Kernel
-> A2 Groupchat Decision Closure
-> A3 Dispatch To Execution Harness
-> A4 Result Writeback To Groupchat
-> A5 Unattended Groupchat Development Loop
```

A1 proves one `chat.db` conversation can route architect, review, and critic
participants through durable worklist, linked inbox delivery, structured
callback/writeback, and depth/dedup/ping-pong guards. A1 does not dispatch
execution work, create PRs, prove MemoryOS continuity, or prove frontend
completeness.
A1 does not dispatch execution work, create PRs, or prove guarded merge.

A2 proves durable proposal, objection or clearance, review verdict, approved
decision, or blocker refs. Agent text is not enough.

A3-A5 connect approved decisions to the existing execution harness, write
execution/review/GitHub outcomes back into groupchat, and repeat or stop with a
durable blocker.

Track B or Track C may become primary only when it removes a named Track A
blocker, completes the selected A1-A5 stage, or the operator explicitly chooses
support work.

## TDD And Tests

Do not start a loop by writing a red test. First identify the real authority,
producer, consumer, condition, proof level, and failure boundary.

Use tests after evidence clarifies what should be pinned:

- contract tests for parser, adapter, store, scheduler, and projection
  boundaries;
- regression tests for observed runtime failures;
- safety guards for forbidden bypasses;
- package boundary tests.

Tests must not fabricate downstream artifacts and then count the fabrication as
runtime closure.

## Helpers And Audit

Skills, workers, OpenCode, subagents, and copilot audit are process aids only.
They are never proof truth.

The main agent may flexibly enable read-only subagent or copilot audit at
decision points, especially PR-ready review, repeated boundary failure, or
authority-classification uncertainty. Material recommendations must be verified
against durable xmuse authority, GitHub server facts, or repository source
before acceptance.

## GitHub And PRs

Use small main-based PRs scoped by implementation domain. Each PR states:

```text
authority
producer
consumer
validation
forbidden claims
```

Remote CI is server evidence only for the exact PR head SHA and inspected run.
Local tests are local evidence only. The operator performs or explicitly
authorizes final merge behavior.

Do not create umbrella PRs. Split across domains such as groupchat kernel,
decision closure, dispatch/writeback, MemoryOS sidecar, frontend projection, or
copilot audit.

## Track B And C Boundaries

MemoryOS is an opt-in sidecar for continuity. It must not create or mutate
xmuse proposal, review, dispatch, execution, GitHub, or merge truth. If
unavailable, record degraded sidecar state and continue.

Frontend/API/TUI are read projections. They expose timeline, agent cards,
worklist, proposal, dispatch, review verdict, blockers, next action, and detail
refs without writing truth.

## Documentation

Do not turn every merged PR into automatic documentation calibration. Update
current docs only when a milestone changes operating rules, staged closure
status, authority boundaries, forbidden claims, or durable blockers.

`docs/superpowers/specs/2026-06-30-natural-groupchat-kernel-design.md` is the
design-source record for the current Track A correction. Operational behavior is
defined by this `docs/xmuse/` package.

## Stop Conditions

Stop and report when:

- the same complex boundary fails after focused refactor;
- MemoryOS or frontend work displaces Track A without explicit operator choice;
- proof would require provider stdout, local tests, worker output, or audit
  output as truth;
- Ray must be patched again to stay on the main path;
- a PR becomes an umbrella PR;
- forbidden claims would need to be weakened.
