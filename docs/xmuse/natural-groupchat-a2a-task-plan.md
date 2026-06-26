# Natural Groupchat A2A Task Plan

Updated: 2026-06-26

This plan is the detailed task reference for
`docs/xmuse/natural-groupchat-a2a-goal-prompt.md`.

## Minimum Success

Reach one of these terminal states:

- a real natural groupchat chain creates a small xmuse PR, observes CI, and
  reaches operator merge or explicit operator blocker;
- or the chain stops at a durable blocker that names the next authority
  boundary and preserves source refs.

## Phase 0 - Truth Refresh

Run and record:

```text
git status -sb
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
gh pr view 193 --json number,state,headRefName,headRefOid,baseRefName,mergedAt,mergeCommit,url
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,isDraft,mergeStateStatus,url
```

Exit with:

- clean worktree selected;
- #193 verified merged, because A2A SDK foundation is now a main prerequisite;
- dirty historical worktrees marked reference-only;
- current provider availability recorded;
- first real runtime chain selected.

## Phase 1 - Security And Authority Preflight

Deliver:

- A2A bridge/server disabled by default;
- write paths local-only or token-gated;
- read-only Agent Card separated from task/send write path;
- A2A SDK task status cannot approve, dispatch, review, or merge directly.

Validation:

- missing token rejected for write path;
- valid token accepted for write path;
- read-only card behavior matches configured policy;
- no stdout or SDK status can bypass xmuse durable authority.

## Phase 2 - Agent Interop Kernel

Deliver:

- agent profile/card read model;
- official SDK model boundary available from main;
- layered prompt builder:
  `xmuse L0 + role identity + roster + task + bounded transcript + state refs`;
- context assembler with restart-stable refs;
- provider-native session binding and same-session serialization;
- canonical handoff task envelope.

Validation:

- Chat API can create a durable groupchat where each participant has identity,
  capability, provider/session state, and prompt/context payload.

## Phase 3 - Natural Handoff And Provider Invocation

Deliver:

- line-start mention or explicit target becomes durable handoff item;
- code-block mention stripping, target validation, self-filtering, dedupe, and
  ping-pong guard;
- outbound A2A/provider adapter for invocation;
- provider task/artifact normalization;
- writeback reconciliation into `chat.db` and inbox linkage.

Validation:

- real Codex participant reads inbox and produces durable proposal or blocker;
- main path does not use Ray as default route.

## Phase 4 - Review, Dispatch, Execution Closure

Deliver:

- structured review verdict remains review authority;
- P1/P2 findings block with evidence refs;
- P3 may allow dispatch only when explicitly non-blocking;
- approval/blocked state has source refs;
- dispatch/execution consumes xmuse authority, not stdout;
- one small PR is created from the chain;
- CI is observed through GitHub server facts;
- operator merge or explicit blocker is recorded.

Validation:

- PR/CI/merge state is tied to exact head SHA and run metadata;
- no GitHub review truth, ready-to-merge, or autonomous merge claim is made.

## Phase 5 - MemoryOS Sidecar

Only proceed after the natural groupchat chain has advanced.

Deliver:

- opt-in ingest of summaries, decisions, blockers, and artifact refs;
- recall into context assembler;
- degraded mode when unavailable.

Validation:

- contract proof with fake/local adapter;
- live proof only when live MemoryOS is actually available.

## Phase 6 - Frontend API / UX Contract

Do not attempt full frontend implementation.

Deliver read-only API payloads for:

- conversation timeline;
- agent cards;
- inbox/worklist;
- review/dispatch state;
- blocker/next action;
- artifact/source refs;
- card summary plus collapsible detail payload.

Validation:

- frontend can consume payloads without reading internal stores directly.

## Phase 7 - Documentation And Final Report

Update only the concise current docs unless a historical artifact needs a
pointer:

- `docs/xmuse/README.md`;
- `docs/xmuse/natural-groupchat-a2a-goal.md`;
- `docs/xmuse/natural-groupchat-a2a-behavior.md`;
- this file;
- `docs/xmuse/release-checklist.md` only if release claims change.

Final report includes:

- maximum real chain reached;
- demand attempted or completed;
- PR/CI/merge state;
- A2A progress by phase;
- MemoryOS state: skipped, degraded, contract proof, or live proof;
- frontend API changes, if any;
- whether Ray was used in the main path;
- durable blockers and next authority boundary;
- exact forbidden claims not made.
