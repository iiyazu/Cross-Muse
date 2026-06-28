# Natural Groupchat A2A Goal

Updated: 2026-06-28

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
- `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md`
- `/home/iiyatu/clowder-ai` as implementation reference, not as authority

## Latest Calibration

As of this update:

- `origin/main` is calibrated at merge commit
  `e2a2e2742ff452bc8e306fb6efdd525231d22bff`.
- The latest merged PR is #252 (`Clarify A2A review verdict approval
  boundary`), merged 2026-06-28 with exact PR head
  `1fc647e6d19689071c92cb763594494eb171ca86`.
- Current server-side main CI evidence:
  - PR #242 `c1d19ad2ae9bd8b22742376c98968073a508329c`: run
    `28292323481` success.
  - PR #244 `65910e683eb6f8c70ed5428ac77c0e971ff0aa99`: run
    `28307269298` success.
  - PR #245 `328e79a9b153843069146826192dc9ac2cc115d6`: run
    `28308325362` success.
  - PR #246 `176d26272cb118c62ab424053d77bd6a1a44a5a5`: run
    `28309007290` success.
  - PR #247 `a94ebb33c751a02b13e00de06d53a0fd56649405`: run
    `28309375745` success.
  - PR #248 `a752432b73a5d7a6cdd735d9776141f0d2ebc3a1`: run
    `28309677170` success.
  - PR #249 `159b851435b735ac828eca0637b601907c306cef`: run
    `28310645567` success.
  - PR #250 `38306251fa1a820b35ce3ca46e877e9e04f1679c`: run
    `28310900258` success.
  - PR #251 `10d9f89900646e5b364424e01dc931383983084c`: run
    `28311466358` success.
  - PR #252 `e2a2e2742ff452bc8e306fb6efdd525231d22bff`: run
    `28311860691` success.
- Recent domain-scoped progress:
  - #244 advanced the natural peer-callback proposal handoff path.
  - #245 added opt-in MemoryOS sidecar recall/degraded-mode support.
  - #246 added frontend read-only peer-chat UX projection.
  - #247 added read-only goal copilot audit guardrails.
  - #248 refreshed the current goal documentation package.
  - #249 made GitHub server truth require exact PR head check-run evidence
    before merge proof can emit `pr_merged`.
  - #250 refreshed current goal docs against the newer main truth.
  - #251 projected sanitized MemoryOS sidecar support metadata through the
    read-only peer-chat UX projection.
  - #252 made A2A `dispatch_allowed` review verdict writeback name
    `chat.db/proposal_approval` as the next authority boundary, while dropping
    provider-supplied boundary claims.
- The next long goal should start from a clean `origin/main` worktree after
  truth refresh.
- Dirty historical worktrees may be read as references only. They are not main
  capability.
- PR #243 is an older broad docs package and is behind current main. Treat it
  as reference-only unless it is explicitly rebased and revalidated.

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
- Ray-backed production proof.
