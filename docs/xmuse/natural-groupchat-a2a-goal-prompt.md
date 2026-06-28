# Natural Groupchat A2A Goal Prompt

Use this prompt directly with `/goal`.

```text
Goal title:
Production natural agents groupchat with A2A SDK interop and xmuse authority.

Repo:
/home/iiyatu/projects/python/xmuse

Primary objective:
Use xmuse's own natural agents groupchat to carry one small real xmuse demand
through durable discussion, provider invocation, proposal or blocker, structured
review verdict, dispatch/execution, PR, CI observation, and operator merge or
explicit durable blocker.

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/natural-groupchat-a2a-goal.md
- docs/xmuse/natural-groupchat-a2a-behavior.md
- docs/xmuse/natural-groupchat-a2a-task-plan.md
- docs/xmuse/mainline-contracts.md
- /home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md
- /home/iiyatu/clowder-ai as natural groupchat reference only

Current calibration:
- Start from a clean origin/main worktree after truth refresh.
- Current known main calibration is
  `fa1cc1e1996be3c18540f574c3513b0cafbea642` after PR #270, but always verify
  live `origin/main` and open PR state before acting.
- PRs #242, #244, #245, #246, #247, #248, #249, #250, #251, #252, #253,
  #254, #255, #257, #258, #259, #260, #261, #262, #263, #264, #265, #266,
  #267, #268, #269, and #270 have merged with successful main push CI as of
  2026-06-28.
- PR #249 hardened GitHub server truth: PR/CI/merge evidence must be tied to
  exact PR head SHA, required check-run names, and per-check-run head SHAs.
- PR #251 exposed sanitized MemoryOS sidecar support metadata through the
  read-only UX projection.
- PR #252 clarified that A2A `dispatch_allowed` review verdict writeback still
  requires `chat.db/proposal_approval` before dispatch, and drops
  provider-supplied boundary claims.
- PR #254 exposed `chat.db/dispatch_queue` as next authority only when proposal
  approval creates a real queue entry.
- PR #255 persisted dispatch gate refs for MemoryOS sidecar/context continuity,
  frontend projection, and read-only copilot audit consumers.
- PR #257 propagated dispatch authority refs into execute-peer
  context/prompt/envelope, kept frontend `source_refs` authority-only, and
  made read-only copilot classify `chat_dispatch_queue:*` as durable authority
  while leaving `mcp_writeback:*` as execution evidence/candidate input.
- PR #258 refreshed current goal docs after #257.
- PR #259 keeps dispatch acknowledgement/evidence refs in `chat_dispatch_queue`
  and prevents `mcp_writeback:*` / `peer_ack:*` from becoming acceptance spine
  lane execution proof.
- PR #260 refreshed current goal docs after #259.
- PR #261 propagates approved dispatch authority refs into saved lane graphs,
  projected execution lanes, lane context bundles, normal execution prompts,
  and persistent execute context; those refs identify queue/proposal/review
  authority consumption and are still not lane execution proof.
- PR #262 refreshed current goal docs after #261.
- PR #263 records approved dispatch handoff continuity into the optional
  MemoryOS sidecar with queue/proposal/review/resolution/artifact refs; sidecar
  ingest degradation remains non-blocking and does not become dispatch or lane
  execution proof.
- PR #264 refreshed current goal docs after #263.
- PR #265 exposes dispatch queue entry-level source refs, frontend authority
  boundary, and projection-only sidecar continuity on the read-only UX
  projection.
- PR #266 clarifies read-only copilot intake boundaries: accepted
  recommendations may use `review_trigger_verdict:*` and `chat_dispatch_queue:*`
  as durable authority, while `mcp_writeback:*` and legacy
  `chat_dispatch_queue#entry=*` remain candidate/evidence refs.
- PR #267 refreshed current goal docs after the B/C/D completion pass.
- PR #268 fixes acceptance-gated short-run read projection after final-action
  GitHub gate resolution: accepted gates project as `merged`; manual gaps
  project as `blocked_for_input` with `blocked_reason`; projection refs point
  back to `chat.db`, dispatch queue, review verdict, final action, and GitHub
  gate evidence/gap authority.
- PR #269 refreshed current goal docs after #268.
- PR #270 marks synthetic acceptance-gated short-run lane projections as
  `integration_mode: noop`, so health does not report ordinary dependent
  release risk for a projection-only gate lane.
- PR #243 is an older behind-main docs package; treat it as reference-only
  unless rebased and revalidated.
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
- Ray is optional legacy, not the default natural groupchat kernel.
- Do not start loops with TDD. First identify authority, producer, consumer,
  condition, proof level, and failure boundary.
- Use tests after observed runtime evidence to pin contracts/regressions.
- Skills/workers are process aids only, never proof truth.
- Flexibly enable read-only subagent or copilot audit when it materially helps
  implementation/review decisions; audit output remains candidate input only.
- Use dynamic small main-based PRs by implementation domain; every PR must pass
  remote CI before merge.
- If the same complex boundary fails twice, refactor or redesign the boundary
  instead of stacking patches.

Minimum success:
Reach a real PR/CI/operator merge path for one small xmuse demand, or stop at a
durable blocker that names the next authority boundary with source refs.

Do not claim:
production-ready natural groupchat, live MemoryOS authority, fully autonomous
merge, GitHub review truth, provider stdout review truth, full multi-provider
parity, frontend complete, or Ray-backed production proof.
```
