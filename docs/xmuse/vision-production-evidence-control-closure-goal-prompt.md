# Vision Production Evidence-Control Closure Goal Prompt

Use this concise prompt for the next production-grade `/goal`. The detailed
task list, acceptance criteria, evidence schema, and behavior rules are in:

```text
docs/xmuse/vision-production-evidence-control-closure-plan.md
```

```text
Goal: Execute xmuse Vision Production Evidence-Control Closure.

Repository:
- /home/iiyatu/projects/python/xmuse

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/provider-matrix.md
- docs/xmuse/memoryos-governance-contract.md
- docs/xmuse/mcp-permission-model.md
- docs/xmuse/production-operations.md
- docs/xmuse/vision-production-evidence-control-closure-plan.md
- /mnt/c/tmp/deep-research-report_09.md

Runtime target:
- Run as an 8 hour production-grade closure task.
- This is not a demo. Use currently configured live environments.
- If full closure does not fit, land the strongest validated production slice
  and record the next production slice explicitly.

Objective:
Move xmuse toward production-grade evidence and control closure: GOD/CLI manual
registration and selection, TUI as the full operator surface through official
authorized actions, production Auth/RBAC for writes, configured live
MemoryOS/GitHub/provider gates, natural GOD transcript boundaries, and release
readiness that rejects fake/local proof as production evidence.

Priority order:
1. Establish baseline: branch, dirty state, xmuse/__init__.py absence,
   configured live env, GitHub auth, MemoryOS, Ray/Codex/OpenCode, and current
   release blockers.
2. Advance GOD/CLI registration and selection. Product direction: users must be
   able to register/select which CLI acts as GOD from the TUI/frontend. No CLI,
   including OpenCode, may be promoted to peer-GOD by assertion.
3. Make TUI a full operation surface. Mutations must go through Chat
   API/MCP/platform operator-action contracts with capability checks,
   idempotency, audit, and source authority. TUI must not edit projections,
   graph stores, review records, MemoryOS bindings, or GitHub truth directly.
4. Harden Auth/RBAC. Chat API and MCP mutating writes must require configured
   tokens, roles/capabilities, and fail closed under
   XMUSE_DEPLOYMENT_PROFILE=production when write tokens are missing.
5. Attempt configured live gates: MemoryOS Lite trace, GitHub server truth,
   Ray/Codex GOD runtime, OpenCode health/bounded runtime, and natural GOD
   transcript evidence. Configured gate failures are release blockers, not
   cosmetic gaps.
6. Aggregate release readiness with tests, ruff, package boundary, internal
   review, live/server/provider evidence, blocker artifacts, and proof
   contamination audit.
7. Update docs/walkthrough/evidence. If validation passes, commit, push, and
   create or update a draft PR. Never auto-merge.

Hard constraints:
- Use uv run for pytest, ruff, scripts, and Python entrypoints.
- Preserve unrelated worktree changes. Do not use git reset --hard.
- Do not create xmuse/__init__.py.
- Do not commit runtime state: *.db, *.sqlite3, *.jsonl, feature_lanes.json,
  xmuse/work/, xmuse/history/, or xmuse/logs/.
- xmuse_core must not import runtime xmuse/ or memoryos_lite.
- MemoryOS remains REST-first.
- feature_lanes.json, TUI, dashboard, cards, and Ray actors are not durable
  authority.
- pr_merged requires GitHub server-side merge proof.
- Internal review proof may count for single-maintainer internal review truth,
  but not as GitHub server-side enforcement.
- Fake/local/contract evidence can support tests but cannot satisfy production
  live gates.
- OpenCode remains bounded unless durable registration, capability, persistence,
  MCP/writeback, review, and provider proof exist.
- Manual peer-GOD registration requires real_provider_proof, non-empty
  proof_refs, persistent sessions, MCP/writeback, and state-write permission.
  Recording proof_refs is not the same as satisfying the real-provider release
  gate.
- If invoking OpenCode, use opencode-go/deepseek-v4-flash with --variant max as
  required by repo docs.

Required action paths:
- TUI /god register -> register_god_cli with register_god_cli capability.
- TUI /god select -> select_god_cli with select_god_cli capability.
- TUI /release refresh -> refresh_live_gate_status with release_gate capability.
- TUI /release pack -> capture_release_evidence_pack with release_gate
  capability.
- TUI /lane retry and /lane abort -> retry_lane/abort_lane with workflow_write
  capability and current-state guards.
- TUI /freeze -> freeze_blueprint with chat_freeze_blueprint capability and the
  existing deliberation freeze contract.
- TUI direct Chat API writes must forward XMUSE_CHAT_API_KEY,
  XMUSE_TUI_OPERATOR_ID, XMUSE_TUI_OPERATOR_ROLE, and
  XMUSE_TUI_OPERATOR_CAPABILITIES when auth is configured.

Evidence protocol:
- Record each stage with stage_id, action, status, proof_level,
  source_authority, source_refs, target_refs, commands, test_results,
  artifacts, blocked_reason, owner, and next_action.
- Use uv run xmuse-live-gate-status-capture for live gate status/blocker
  artifacts. It records or converts evidence; it does not create live proof by
  itself.
- Use uv run xmuse-release-evidence-pack for the operator handoff pack. It
  aggregates readiness and proof-contamination reports; it does not create live
  proof by itself.
- Continue only to independent stages when a configured live gate blocks.

Validation:
- Run focused pytest for every changed surface.
- Always run:
  uv run ruff check .
  git diff --check
  uv run pytest tests/xmuse/test_package_boundaries.py -q

Completion:
Finish with implementation status, changed files, validation results, release
readiness decision, proof captured, remaining release blockers, commit/push
status, and draft PR status. Do not mark production closure complete while live
MemoryOS, natural GOD transcript, real provider runtime, or GitHub merge truth
remain uncaptured.
```
