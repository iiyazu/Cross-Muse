# Natural Groupchat A2A Behavior Policy

Updated: 2026-06-27

This policy governs the next long `/goal` for natural agents groupchat,
A2A-based interop, MemoryOS sidecar work, and frontend API readiness.

## Operating Rule

Each loop must name:

```text
target behavior
authority
producer
consumer
condition
proof level
failure boundary
forbidden claims
```

Run the largest reachable real chain before patching when the runtime boundary
is executable. Passing tests alone is never proof that the chain works.

The long unattended window is a throughput budget, not a fixed time schedule.
Do not slice the goal into rigid hour blocks. Advance by proof-bearing loops and
stop at a clean merge, durable blocker, or handoff point.

Each loop must be one of:

| Loop type | Purpose | Required output |
|---|---|---|
| Runtime loop | Run the largest reachable real chain | New maximum stage or first durable failure boundary |
| Fix/refactor loop | Change one classified producer/consumer boundary | Focused diff plus validation |
| Convergence loop | Re-run the largest real chain after a change | Proof that the chain advanced or a durable blocker |
| Fan-in loop | Merge/rebase/coordinate clean PRs | Exact-head CI, guarded merge, main CI observation |

## Authority Order

Durable xmuse authority remains:

```text
chat.db / inbox / proposal / review verdict / dispatch queue / GitHub server facts
```

Projection-only or diagnostic surfaces:

```text
provider stdout
streamed text
worker summary
frontend card
feature_lanes.json projection
A2A task status before xmuse normalization
skill or subagent output
```

Provider or A2A output must pass through one writeback reconciliation boundary:

```text
provider result / A2A task / MCP callback
-> normalized message/envelope
-> inbox reply linkage
-> proposal/review/dispatch gate
-> read-only projection
```

## TDD Constraint

Do not start a loop by writing a red test. First identify the real producer,
consumer, authority object, and observed failure boundary.

Tests are allowed after runtime evidence shows what should be pinned:

- contract tests for parser/adapter boundaries;
- regression tests for observed runtime bugs;
- safety guards for forbidden bypasses;
- package boundary tests.

Tests must not construct fake artifacts that production runtime should create
and then treat that as closure.

## Superpowers And Worker Constraint

Use skills, subagents, OpenCode, or other helpers only when they materially
improve the current decision or implementation. They are never proof truth.

If a skill instruction conflicts with this policy's authority-first runtime
rules, preserve the xmuse proof boundary and record the conflict.

OpenCode invocation, when used, remains:

```text
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Do not use helper output as review truth, GitHub truth, merge truth, or
production proof.

## GitHub And CI/CD

Use main-based small PRs. PR count is dynamic and should follow the real domain
shape, not a rigid budget. Each PR must be domain-scoped and must state:

```text
authority
producer
consumer
validation
forbidden claims
```

Remote CI is server evidence only for the exact PR head SHA and run inspected.
Local tests are local evidence only. The operator performs final merge or
explicitly authorizes merge behavior.

When merge automation is authorized for a run, the merge path is:

```text
PR exact-head CI success
-> gh pr merge --match-head-commit <head_sha>
-> fetch origin
-> observe main CI for the merge commit
```

Do not delete feature branches unless separately authorized. Do not claim main
CI success until the run for the merge commit is completed successfully.

Do not create umbrella PRs. If separate domains emerge, split by domain:

- A2A SDK/security boundary;
- prompt/context kernel;
- natural handoff/worklist;
- provider invocation/writeback reconciliation;
- review/dispatch authority;
- MemoryOS sidecar;
- frontend read API.

## Patch And Refactor Threshold

Use a focused refactor immediately when it is simpler than another patch.

Triggers:

- same complex boundary fails twice;
- a fix would add another compatibility branch;
- prompt/context fragments are scattered;
- routing/callback/scheduler/provider paths duplicate state;
- Ray compatibility blocks the main route;
- writeback reconciliation remains split across ad hoc paths.

Every refactor states:

```text
old path replaced
new producer
new consumer
unchanged authority
proof command or runtime replay
```

## MemoryOS And Frontend Boundaries

MemoryOS is an opt-in sidecar for recall, summaries, decisions, blockers, and
artifact refs. It must not mutate xmuse authority stores directly. If
unavailable, omit recall and continue.

Frontend work in this goal is API/UX contract first: timeline, agent cards,
worklist, review/dispatch, blockers, next action, and collapsible detail
payloads. Frontend projection does not create truth.

## Parallel Track Rules

Recommended unattended topology:

| Track | Role | Writes code? | Authority boundary |
|---|---|---|---|
| A | Natural groupchat real chain and PR/CI/merge coordination | Yes | `chat.db`, inbox, proposal, review, dispatch, GitHub facts |
| B | MemoryOS sidecar and context continuity | Yes | Consumes xmuse artifacts; never replaces authority |
| C | Frontend API / UX read projection | Yes | Read-only projections over durable stores |
| D | Copilot audit | No, except appending review-board entries | Advisory only |

Track A owns the main proof path. Tracks B and C may progress while Track A is
waiting for provider, runtime replay, CI, or merge, but they must not modify the
same authority boundary concurrently. If two tracks touch the same boundary,
serialize them. After each merge to main, refresh or rebase surviving tracks
before continuing.

The copilot track is read-only. It may inspect files, diffs, artifacts, PRs, and
CI state, then append concise recommendations to the shared review board. The
main track must verify any recommendation before acting on it.

## Stop Conditions

Stop and report when:

- the same complex failure repeats after a focused refactor;
- MemoryOS or frontend work displaces the natural groupchat chain;
- proof would require provider stdout as truth;
- Ray must be patched again to stay on the main route;
- a PR turns into an umbrella PR;
- dynamic PR growth stops matching domain boundaries and starts hiding a
  single unresolved architecture failure;
- the next task is low-value polish relative to replaying or stabilizing the
  real chain;
- forbidden claims would need to be weakened.
