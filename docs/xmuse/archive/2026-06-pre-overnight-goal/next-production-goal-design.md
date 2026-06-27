# Next Production Goal Design

Updated: 2026-06-20.

This document anchors the next long xmuse `/goal`: converge xmuse toward a
production-grade natural agents groupchat platform and a rigorous
demand-to-execution loop.

Behavior rules:

```text
docs/xmuse/real-runtime-loop-behavior-policy.md
docs/xmuse/real-god-chatgroup-fullchain-loop-decomposition.md
docs/xmuse/goal-copilot-behavior-policy.md
```

## Objective

Build the maximum reachable real chain:

```text
human demand
-> durable agents groupchat
-> natural Codex/OpenCode discussion
-> durable decision or proposal
-> blueprint / graph / lane bridge
-> isolated execution
-> independent review
-> final-action hold or scoped PR/merge when GitHub server truth permits
```

The demand may target xmuse itself. Improving xmuse is valid product work when
the real groupchat drives the decision, execution, review, and PR flow.

## Priority

Use this order:

1. Complexity convergence and production-path isolation.
2. Natural agents groupchat platform.
3. Blueprint execution harness.
4. MemoryOS long-term memory.
5. UX and performance.

Phase 1 through Phase 3 are the minimum success standard. Phase 4 and Phase 5
are extra standards that should be pursued when the minimum path is stable and
the work is not drifting.

## Principles

- Durable authority is truth.
- Agents are peers with identity, session, prompt profile, and writeback
  contract, not temporary worker calls.
- Prompt construction is a first-class runtime contract.
- Groupchat produces decisions; execution harness consumes decisions.
- Projection and UI never create truth.
- Fake, demo, and legacy paths may remain only when isolated from production
  authority.
- MemoryOS is opt-in and must degrade durably when unavailable.
- Prefer deletion, quarantine, or redesign over compatibility layers that hide
  broken authority boundaries.

## Phase 0: Truth Refresh

Purpose: establish repository, GitHub, provider, process, port, runtime-state,
and documentation truth before mutating behavior.

Exit signal:

- current branch, HEAD, status, and server facts are known;
- provider availability for Codex and OpenCode is known;
- MemoryOS is probed only for availability, not assumed live;
- stale services and runtime roots are either cleared or explicitly owned;
- the first causal hypothesis is stated.

## Phase 1: Production-Path Isolation

Purpose: separate production authority from fake/demo/legacy paths.

Classify current paths as:

- `production-authority`;
- `production-producer`;
- `production-consumer`;
- `projection-only`;
- `test-fixture`;
- `demo-only`;
- `legacy-quarantined`;
- `delete-candidate`.

Minimum exit signal:

- a short boundary table exists;
- production authority order is explicit;
- no fake producer can create production truth;
- at least one high-risk fake/demo/legacy path is isolated, downgraded, or
  marked for deletion;
- no production-readiness claim is made.

## Phase 2: Natural Agents Groupchat Kernel

Purpose: make peer-chat a durable natural groupchat.

Initial roster:

- human;
- Codex architect;
- Codex executor;
- OpenCode reviewer.

OpenCode invocation remains:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Required member binding:

- role/name;
- provider kind and CLI command/model;
- system prompt profile;
- prompt layer versions and budget;
- session identity and restore policy;
- memory policy;
- writeback contract.

Prompt construction contract:

- `XmusePromptBuilder` composes deterministic ordered prompt layers.
- `ContextAssembler` builds bounded sanitized context from durable chat state,
  roster state, local context capsules, and optional MemoryOS refs.
- Builder output must be inspectable as ordered layers.
- Raw provider stdout, unbounded history, and read-model projections must not
  become authority.

Required prompt layers:

1. xmuse governance L0.
2. Member identity.
3. Roster and capability context.
4. Local conversation context capsule.
5. Tool and writeback instructions.
6. Optional MemoryOS refs after Phase 4 proof.

Minimum exit signal:

- one real conversation includes the four initial members;
- Codex/OpenCode peer replies are durable messages with matching
  callback/MCP/writeback traces;
- restart restores roster and session binding;
- a dynamic member event is durable;
- a restarted or newly added member consumes the local context capsule;
- durable progress events are visible through Chat API or a read model;
- at least one handoff and one non-linear multi-turn discussion occur;
- groupchat produces a durable proposal.

## Phase 3: Blueprint Bridge And Execution Harness

Authority order:

```text
docs/spec blueprint = input material
groupchat decision/proposal = decision authority
graph-set / lane graph = execution authority
feature_lanes.json = queue/projection only
execution worktree = candidate artifact
review artifact = review authority
GitHub server = PR/check/merge authority
```

Minimum exit signal:

- a durable groupchat proposal bridges to graph/lane authority;
- lane source refs trace back to conversation/proposal;
- isolated execution produces a candidate;
- gate runs and records a result;
- independent review produces a verdict and cites candidate artifacts;
- lane reaches final-action hold or classified rejection.

## Phase 4: MemoryOS Opt-In Adapter

MemoryOS is not required for Phase 2. If available, it may promote selected
context capsules and durable decisions into auditable memory refs. If
unavailable, record durable degraded state and continue the Phase 1-3 chain.
Do not claim `live_memoryos` without a real trace/artifact id.

## Phase 5: UX And Performance

UX consumes Phase 2 durable progress events. It must not write authority.

Default UI shape:

- agent card summaries;
- details collapsed by default;
- click to expand details;
- visible waiting/running/degraded states;
- proposal/lane/review state visible without exposing full chain-of-thought.

## Parallel Execution

Use parallelism to reduce waiting and context pressure, not to create multiple
truth authorities.

Dependency gates:

```text
Phase 0 truth refresh
-> Phase 1 complexity audit
-> Track A: Phase 2 groupchat kernel
   -> Phase 3 blueprint execution harness

Track B: Phase 4 MemoryOS
  waits for Track A context capsule contract

Track C: Phase 5 UX/performance
  waits for Track A durable progress-event contract
```

Track A owns the minimum success path. Track B and Track C may perform
read-only discovery early, but production implementation waits for the upstream
contracts they consume.

Coordination rules:

- isolate runtime shards by `XMUSE_ROOT`, ports, worktrees, logs, and
  `.goal-runs/<date>/<loop-id>/`;
- merge PRs serially even when CI observation runs in parallel;
- split branches by implementation domain;
- allow dynamic PR count only while each PR remains small and domain-scoped;
- if two tracks expose the same complex boundary, stop parallel patching and
  redesign the shared contract.

## Stop Conditions

Stop or ask for direction when:

- the same complex boundary repeatedly fails after the allowed patch/redesign
  threshold;
- work drifts away from Phase 1-3;
- continuing would weaken authority or proof boundaries;
- a required non-degradable external authority is unavailable;
- PR/domain scope becomes umbrella-shaped;
- server truth blocks PR verification or merge;
- the user asks to pause.

## Final Report

Report phases completed/blocked, exact runtime commands, durable artifacts,
current boundary table, confirmed/falsified hypotheses, PRs, MemoryOS
trace/degraded state, UX/performance changes, failures, manual gaps, forbidden
claims not made, and the next boundary or redesign target.
