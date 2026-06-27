# Natural Groupchat A2A Goal Prompt

Use this prompt directly with `/goal`.

```text
Goal title:
Unattended production natural agents groupchat throughput with A2A SDK interop.

Repo:
/home/iiyatu/projects/python/xmuse

Primary objective:
Use xmuse's own natural agents groupchat to carry real xmuse demands through
durable discussion, provider/A2A handoff, proposal or blocker, structured
review verdict, dispatch/execution, PR, exact-head CI, head-SHA guarded merge,
and main CI observation. Use the unattended window as throughput capacity, not
as a fixed time schedule.

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/natural-groupchat-a2a-goal.md
- docs/xmuse/natural-groupchat-a2a-behavior.md
- docs/xmuse/natural-groupchat-a2a-task-plan.md
- docs/xmuse/goal-copilot-behavior-policy.md
- docs/xmuse/mainline-contracts.md
- /home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md
- /home/iiyatu/clowder-ai as natural groupchat reference only

Current calibration:
- Start from a clean origin/main worktree after truth refresh.
- PR #193 and A2A hardening PR #234-#242 should be verified as merged.
- Latest calibrated main after PR #242:
  c1d19ad2ae9bd8b22742376c98968073a508329c.
- PR #242 makes native GOD sessions the default peer-chat path; Ray is optional
  legacy and not the main natural groupchat kernel.
- Dirty historical worktrees and archived docs are references only, not main
  capability.

Architecture:
natural groupchat
-> official a2a-sdk provider / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / CI / operator merge

Hard rules:
- A2A SDK is interop, not xmuse authority.
- Durable authority remains chat.db / inbox / proposal / review verdict /
  dispatch queue / GitHub server facts.
- Ray is optional legacy, not the default natural groupchat kernel.
- Do not start loops with TDD. First identify authority, producer, consumer,
  condition, proof level, and failure boundary.
- Use tests after observed runtime evidence to pin contracts/regressions.
- Skills/workers are process aids only, never proof truth.
- Use dynamic small main-based PRs by implementation domain; do not set a fixed
  PR count cap, but do not create umbrella PRs.
- Every PR must pass remote exact-head CI before merge.
- Operator authorization for this run: when a PR is domain-scoped and exact-head
  CI passes, use head-SHA guarded merge, then observe main CI for the merge
  commit. Do not delete branches unless separately authorized.
- If the same complex boundary fails twice, refactor or redesign the boundary
  instead of stacking patches.
- MemoryOS is an optional sidecar, not authority. If unavailable, degrade.
- Frontend work is read API / UX projection only; projections do not create
  truth.

Execution topology:
- Track A: natural groupchat real chain and PR/CI/merge coordination.
- Track B: MemoryOS sidecar and context continuity.
- Track C: frontend API / UX read projection.
- Track D: read-only copilot audit using docs/xmuse/goal-copilot-behavior-policy.md.

Loop model:
run largest real chain -> classify durable boundary -> fix/refactor one boundary
-> focused validation -> PR/CI/merge if clean -> replay largest real chain ->
continue, parallelize, or stop at a clean report point.

Minimum success:
Track A reaches a real PR/CI/guarded-merge/main-CI path for at least one real
xmuse demand, or stops at a durable blocker that names the next authority
boundary with source refs. Track B or C should produce a domain-scoped mergeable
improvement when it does not displace Track A.

Do not claim:
production-ready natural groupchat, live MemoryOS authority, fully autonomous
merge, GitHub review truth, provider stdout review truth, full multi-provider
parity, frontend complete, Ray-backed production proof, or full closure.
```
