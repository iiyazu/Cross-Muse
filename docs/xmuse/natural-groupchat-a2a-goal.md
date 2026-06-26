# Natural Groupchat A2A Goal

Updated: 2026-06-26

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

- `origin/main` is calibrated at PR #192 / `bd540de`.
- PR #193 (`codex/a2a-sdk-foundation`) is merged into `origin/main` at merge
  commit `d429e691be51ef5c9aa7ab34a5670f290b37e7a3`.
- The next long goal should start from a clean `origin/main` worktree after
  truth refresh.
- Dirty historical worktrees may be read as references only. They are not main
  capability.

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
