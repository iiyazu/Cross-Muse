# Natural Groupchat A2A Behavior Policy

Updated: 2026-06-28

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
