# Natural Groupchat A2A Behavior Policy

Updated: 2026-06-29

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

Approved dispatch authority refs may be copied into saved lane graphs,
`feature_lanes.json` projection, lane context bundles, and execution prompts so
workers and read-only consumers can trace which durable queue/proposal/review
authority they are consuming. This context still is not lane execution proof.
Actual lane execution proof remains in durable execution status/evidence paths,
not in prompt text or dispatch acknowledgement refs.

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

During long goal execution, the main agent may flexibly enable read-only
subagent or copilot audit for implementation and review quality. Audit output
is candidate input only; the main agent must verify material recommendations
against durable xmuse authority, GitHub server facts, or repository source
before accepting them.

If a skill instruction conflicts with this policy's authority-first runtime
rules, preserve the xmuse proof boundary and record the conflict.

OpenCode invocation, when used, remains:

```text
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Do not use helper output as review truth, GitHub truth, merge truth, or
production proof.

## GitHub And CI/CD

Use main-based small PRs. PR count is dynamic, but each PR must be
domain-scoped and must state:

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

Do not create umbrella PRs. If separate domains emerge, split by domain:

- A2A SDK/security boundary;
- prompt/context kernel;
- natural handoff/worklist;
- provider invocation/writeback reconciliation;
- review/dispatch authority;
- MemoryOS sidecar;
- frontend read API.

## Documentation Calibration And Throughput

Do not turn every merged PR into an automatic current-main documentation PR.
Tracked docs may record `calibrated_through` or `last_observed_baseline` facts,
but they must not imply that a static file is live GitHub truth. Live truth is
always refreshed from GitHub server facts at the start of a loop.

Documentation-only PRs are appropriate when they change operating rules,
authority boundaries, task scope, forbidden claims, or milestone-level status.
They are not required merely because the previous documentation PR moved
`main` to a new merge commit.

Goal-doc tests should validate durable documentation contracts, evidence shape,
and forbidden-claim boundaries. They should not force a self-refresh loop by
requiring the latest `origin/main` SHA to appear in tracked docs after every
merge. If exact SHAs are recorded, name them as observed baselines, not as a
permanent claim that the file equals the current remote head.

Implementation throughput has priority over calibration churn. Prefer:

- one domain-scoped implementation PR with exact-head CI and guarded merge;
- milestone documentation refresh after a meaningful capability or policy
  change;
- a short final report that names the live GitHub facts inspected in that
  loop.

## Goal Throughput Discipline

Each loop must declare one primary Track before doing implementation work:

- Track A: natural groupchat real chain to PR/CI/guarded merge;
- Track B: MemoryOS sidecar/context continuity;
- Track C: frontend API/UX read projection.

Track A is the default primary Track until a real natural groupchat chain can
create a small xmuse PR, observe exact-head CI, and reach guarded merge or an
explicit operator blocker. Track B or Track C may become primary only when the
loop names the Track A blocker it removes or the milestone it directly
completes.

After PR #294, one docs-only A/B/C chain has reached PR, exact-head CI,
guarded merge, main CI, and final-action approval. The next primary Track A
work should therefore increase harness capability rather than repeat the same
docs sentinel:

- first make the integrated replay and evidence summary repeatable;
- then improve durable diagnosis for the first stalled boundary;
- then run one low-risk real-code lane through the same authority chain;
- only then expand to multi-lane or multi-PR execution.

Another docs-only sentinel counts as core-chain progress only when it proves a
repeatability, diagnosis, or regression boundary that #294 did not already
prove.

Each loop may have support Tracks, but support work must not displace the
primary Track. The loop report must separate:

```text
core-chain progress
support progress
primary authority boundary
support authority boundary
blocked boundary
next primary action
```

Use one primary authority boundary per implementation PR. If a proposed change
touches multiple producer/consumer boundaries, split it unless the split would
break the runtime proof.

Do not count support surfaces as core-chain completion. MemoryOS sidecar,
frontend projection, copilot/subagent audit, local tests, and docs updates are
support progress unless the loop proves they directly unblock the real
groupchat-to-PR chain. Green CI, successful local tests, or richer projection
payloads must not be summarized as natural groupchat production readiness.

Documentation-only PRs should normally follow two or three implementation PRs,
or an explicit policy/authority-boundary change. If a documentation PR happens
sooner, its PR body must state why delaying it would risk incorrect execution.

Subagent or copilot audit should be sampled at decision points, not used as a
constant parallel self-approval loop. Good triggers are PR-ready review,
repeated complex boundary failure, or uncertainty about authority
classification.

## Worktree Hygiene

Use a clean main-based worktree for new development. Dirty historical worktrees
remain reference-only unless explicitly promoted after inspection.

Before starting a new implementation slice, check for state hazards that can
distort truth refresh or merge behavior:

- an old worktree occupying the local `main` branch;
- prunable temporary worktrees from tests or runtime probes;
- stale branch worktrees that look newer than `origin/main`;
- runtime state files that would be mistaken for source evidence.

Cleanups must be non-destructive unless the operator explicitly authorizes
removal. Prefer listing hazards first, then pruning only prunable worktrees or
clearly disposable runtime artifacts.

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

Approved dispatch handoff refs may be ingested into the optional sidecar for
continuity. The producer remains `chat.db/chat_dispatch_queue`, the consumer is
MemoryOS sidecar, the condition is explicit MemoryOS configuration, and the
failure boundary is degraded sidecar ingest without blocking dispatch. Sidecar
ingest output is never proposal, review, dispatch, merge, or lane execution
truth.

MemoryOS recall context may attach namespace-scoped continuity refs such as
`memory://conversation/<id>/context/memoryos-sidecar` to the peer prompt,
latency supporting context, and frontend read projection. These refs prove only
that optional sidecar context was assembled for a turn; they do not become
proposal, review, dispatch, merge, lane execution, GitHub, or production truth.
Degraded recall may record an attempt ref, but it must not emit assembled
context continuity refs.

Frontend work in this goal is API/UX contract first: timeline, agent cards,
worklist, review/dispatch, blockers, next action, and collapsible detail
payloads. Frontend projection does not create truth.

## Stop Conditions

Stop and report when:

- the same complex failure repeats after a focused refactor;
- MemoryOS or frontend work displaces the natural groupchat chain;
- proof would require provider stdout as truth;
- Ray must be patched again to stay on the main route;
- a PR turns into an umbrella PR;
- forbidden claims would need to be weakened.
