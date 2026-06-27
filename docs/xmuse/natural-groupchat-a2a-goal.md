# Natural Groupchat A2A Goal

Updated: 2026-06-27

This is the current `/goal` entrypoint for the next xmuse production push. It
supersedes older L8-L11, closure-ledger, walkthrough, and runtime-log driven
planning docs for this goal.

## Source Inputs

Read these first:

- `AGENTS.md`
- `docs/xmuse/README.md`
- `docs/xmuse/natural-groupchat-a2a-behavior.md`
- `docs/xmuse/natural-groupchat-a2a-task-plan.md`
- `docs/xmuse/mainline-contracts.md`

Optional local references when present:

- `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md`
- `/home/iiyatu/clowder-ai` as implementation reference, not as authority

If an optional local reference is absent, continue from repo-local
`docs/xmuse/*` and treat the missing path as non-blocking.

## Latest Calibration

As of this update:

- `origin/main` is calibrated at PR #242 /
  `c1d19ad2ae9bd8b22742376c98968073a508329c`.
- PR #193 (`codex/a2a-sdk-foundation`) and A2A hardening PR #234-#242 are
  merged.
- PR #242 (`codex/a2a-natural-real-chain`) makes native GOD sessions the
  default peer-chat path. Ray remains optional legacy infrastructure and is
  not the default natural groupchat kernel.
- Main CI run `28292323481` was observed successful on merge commit
  `c1d19ad...`.
- The next long goal should start from a clean `origin/main` worktree after
  truth refresh.
- Dirty historical worktrees, including branches with useful natural
  groupchat assets, may be read as references only. They are not main
  capability.

The next run is an unattended throughput goal. A 10h sleep window is a capacity
signal, not a fixed schedule. The goal should keep advancing valuable loops
while proof boundaries remain strong, then stop at a clean merge/report point.

## Objective

Make xmuse use its own natural agents groupchat to carry a small real xmuse
change through:

```text
Chat API human demand
-> durable natural groupchat
-> real provider participant
-> proposal or fail-closed blocker
-> structured review verdict
-> approved or blocked state
-> dispatch / execution
-> PR
-> CI observation
-> operator merge or explicit blocker
```

The goal is not to declare production-ready natural groupchat. The goal is to
advance the maximum real chain and leave precise durable blockers where it
cannot advance.

Use multiple independent worktrees when that increases throughput without
mixing authority boundaries:

```text
Track A: natural groupchat real chain, PR/CI/merge coordination
Track B: MemoryOS sidecar and context continuity
Track C: frontend API / UX projection
Track D: read-only copilot audit
```

Track A owns the main proof path. Track B and Track C are sidecars and
projections; they must not create proposal, review, dispatch, or GitHub truth.
Track D is advisory only.

## Architecture Direction

Default route:

```text
natural groupchat
-> official a2a-sdk provider / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / CI / operator merge
```

Do not use Ray as the default natural groupchat kernel. Ray may remain a
legacy compatibility adapter, but it should not consume the main repair budget.

A2A is an interop boundary, not xmuse authority. Every important A2A event must
be normalized into durable xmuse state before proposal, review, dispatch, or
merge gates consume it.

This practical proposal/review/dispatch route is the route for small real
xmuse demands in this goal. It does not replace the mainline requirement that
larger execution flows preserve blueprint freeze, lane graph, and review
lineage.

MemoryOS is an optional sidecar for recall, summaries, decisions, blockers, and
artifact refs. It becomes live evidence only when a live trace id or artifact
exists. If unavailable, the chain should degrade without blocking Track A.

Frontend work in this goal is read API / UX contract work. Timeline cards,
agent cards, worklist state, blocker panels, and collapsible details are
projections over durable stores; they do not create truth.

## Unattended Execution Model

Do not plan by fixed hours. Plan by value loops:

```text
run largest real chain
-> classify durable boundary
-> fix or refactor one boundary
-> focused validation
-> PR / exact-head CI / guarded merge when clean
-> main CI observation
-> replay largest real chain
-> continue, parallelize, or stop
```

Continue while the maximum real chain advances, the next boundary has clear
authority/producer/consumer, PRs remain domain-scoped, and CI/GitHub facts are
available. Stop when the next work would become umbrella scope, low-value
polish, proof-boundary weakening, or repeated patching of a complex boundary.

## Clowder-AI Extraction

Borrow only the small primitives that make natural groupchat real:

- layered `SystemPromptBuilder`;
- bounded `ContextAssembler`;
- line-start A2A mention parsing with code-block stripping;
- one invocation/worklist path with dedupe and loop guards;
- per-session mutex;
- delivery/writeback reconciliation before projection;
- remote-agent shape informed by A2A, implemented through official SDK where
  public wire behavior is needed.

Do not copy clowder-ai Redis authority, full UI, broad queue stack, or rich
message system unless xmuse actually needs it.

## Forbidden Claims

Do not claim:

- production-ready natural groupchat;
- live MemoryOS authority;
- fully autonomous merge;
- GitHub review truth;
- provider stdout review truth;
- full multi-provider parity;
- frontend complete;
- Ray-backed production proof;
- full closure.
