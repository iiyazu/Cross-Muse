# Natural Groupchat A2A Task Plan

Updated: 2026-06-27

This plan is the detailed task reference for
`docs/xmuse/natural-groupchat-a2a-goal-prompt.md`.

The next run is an unattended throughput goal. The sleep window is capacity for
multiple proof-bearing loops, not a fixed time schedule. Advance by dependency,
value, and clean closure points.

## Minimum Success

Reach one of these terminal states:

- a real natural groupchat chain creates a small xmuse PR, observes exact-head
  CI, merges with a head-SHA guard, and observes main CI for the merge commit;
- or the chain stops at a durable blocker that names the next authority
  boundary and preserves source refs.

Secondary success:

- MemoryOS sidecar reaches degraded or live evidence without replacing xmuse
  authority; or
- frontend API / UX read payloads make the real chain explainable without
  direct store reads.

If Track A is blocked, B/C may still produce domain-scoped PRs, but they must
not redefine Track A's proof boundary.

## Track Topology

Use a clean `origin/main` base for each write track unless a track explicitly
depends on a merged predecessor.

```text
Track A: natural groupchat real chain / PR / CI / merge
Track B: MemoryOS sidecar / context continuity
Track C: frontend API / UX projection
Track D: read-only copilot audit
```

Track A coordinates fan-in and merge order. Track D writes no code and creates
no PRs. Current dirty worktrees are reference-only.

## Phase 0 - Truth Refresh And Track Split

Run and record:

```text
git status -sb
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
gh pr view 193 --json number,state,headRefName,headRefOid,baseRefName,mergedAt,mergeCommit,url
gh pr view 242 --json number,state,headRefName,headRefOid,baseRefName,mergedAt,mergeCommit,url
gh run list --branch main --limit 5 --json databaseId,headSha,status,conclusion,displayTitle,createdAt,url
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,isDraft,mergeStateStatus,url
```

Exit with:

- clean worktree selected;
- #193 and #242 verified merged;
- dirty historical worktrees marked reference-only;
- current provider availability recorded;
- first real runtime chain selected;
- A/B/C write tracks and D copilot board selected.

Track split guidance:

- A starts from clean `origin/main` and runs the largest real chain.
- B starts from clean `origin/main` unless it needs a merged A field.
- C starts from clean `origin/main` unless it needs a merged A read model.
- D uses the same repo in read-only mode and appends only to the shared review
  board.

## Phase 1 - Track A Real Chain Replay

Run before patching:

```text
Chat API human demand
-> durable natural groupchat
-> native GOD session provider turn
-> A2A/provider handoff if selected
-> proposal or fail-closed blocker
-> structured review verdict
-> approval or blocked state
-> dispatch / execution
-> PR / CI / guarded merge, if the chain reaches that far
```

Capture:

- conversation id;
- participant ids, roles, provider/session bindings;
- inbox item ids and reply linkage;
- proposal id or blocker id;
- review trigger/verdict refs;
- dispatch entry and execution refs, if reached;
- PR number, head SHA, CI run, merge commit, if reached;
- first durable failure boundary.

Exit with either a new maximum stage or a classified boundary:

```text
authority:
producer:
consumer:
condition:
proof_level:
failure_mode:
forbidden_claims:
```

## Phase 2 - Track A Boundary Closure

Deliver:

- one focused fix or refactor for the classified boundary;
- no parallel patching of the same authority boundary;
- regression/contract tests only after the runtime boundary is understood;
- PR scoped to the domain that owns the boundary.

Validation:

```text
uv run pytest FOCUSED_TESTS -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```

Runtime validation:

- rerun the largest real chain;
- prove the chain moved farther, or write a durable blocker.

## Phase 3 - Track B MemoryOS Sidecar

Deliver:

- MemoryOS availability probe;
- degraded mode when unavailable;
- opt-in ingest of summaries, decisions, blockers, and artifact refs when
  available;
- recall refs into context assembly without replacing transcript or stores.

Validation:

- unavailable MemoryOS does not block Track A;
- live MemoryOS is claimed only with live trace/artifact refs;
- MemoryOS never mutates proposal, review, dispatch, or GitHub truth.

## Phase 4 - Track C Frontend API / UX Projection

Do not attempt full frontend implementation. Deliver read-only payloads for:

- conversation timeline;
- agent cards and provider/session state;
- inbox/worklist;
- proposal/review/dispatch state;
- blockers and next action;
- artifact/source refs;
- card summary plus collapsible detail payload.

Validation:

- frontend can consume payloads without reading internal stores directly;
- projection never marks review, dispatch, merge, or MemoryOS truth.

## Phase 5 - Fan-In, CI/CD, And Merge

For every PR:

```text
domain-scoped diff
focused local validation
remote exact-head CI success
head-SHA guarded merge when authorized
main CI observation for the merge commit
```

PR count is dynamic. Create as many small PRs as the domain split requires, but
do not use multiple PRs to hide one unresolved architecture failure. If a PR
starts to become an umbrella, split or stop.

After each merge:

- fetch `origin/main`;
- rebase or rebuild surviving tracks on current main;
- rerun the largest real chain before expanding scope.

## Phase 6 - Replay / Soak / Stability

Use remaining unattended capacity to run proof-bearing replays, not low-value
polish. Look for:

- session continuity or identity mismatch;
- writeback timeout or stdout fallback;
- stale review trigger;
- dispatch queue stuck state;
- CI flakes or stale head mismatch;
- B/C projection drift from durable authority.

Fix only issues that block or materially stabilize the real chain. If a
complex boundary repeats after refactor, stop with a durable blocker.

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
- A/B/C/D track outcomes;
- A2A progress by boundary;
- MemoryOS state: skipped, degraded, contract proof, or live proof;
- frontend API changes, if any;
- whether Ray was used in the main path;
- durable blockers and next authority boundary;
- exact forbidden claims not made.
