# Vision Production Evidence-Control Closure Goal Prompt

Use this concise prompt for the next production-grade `/goal`. Detailed tasks
and behavior rules live in:

```text
docs/xmuse/vision-production-evidence-control-closure-plan.md
```

```text
Goal: Execute xmuse Vision Production Evidence-Control Closure.

Runtime target:
- Run as tonight's 8 hour production-grade closure task.
- This is not a demo. Do not stop at contract-only proof when configured live
  environments are available.
- If full closure does not fit in 8 hours, land the strongest validated
  production slice and record the next production slice explicitly.

Authoritative repo:
- /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/provider-matrix.md
- docs/xmuse/memoryos-governance-contract.md
- docs/xmuse/mcp-permission-model.md
- docs/xmuse/production-operations.md
- docs/xmuse/vision-operator-closed-overnight-loop-walkthrough.md
- docs/xmuse/vision-production-evidence-control-closure-plan.md
- /mnt/c/tmp/deep-research-report_09.md

Objective:
Move xmuse into production-grade evidence and control closure. Implement or
advance GOD/CLI registration and selection, full TUI operation through official
authorized contracts, production Auth/RBAC for write surfaces, configured live
MemoryOS/GitHub/provider gates, natural GOD transcript boundaries, and a release
readiness gate that does not accept fake/local proof as production evidence.

Priority:
1. Establish production baseline: branch, dirty state, xmuse/__init__.py
   absence, configured live env, GitHub auth, MemoryOS, Ray/Codex/OpenCode, and
   current proof gaps.
2. Add or advance GOD/CLI registry and manual selection. Product direction:
   the user must be able to register/select which CLI acts as GOD. For this
   round, OpenCode remains bounded unless peer-GOD parity is proven.
3. Make TUI a full operation surface. Mutating actions must go through official
   Chat API/MCP/platform contracts with idempotency and audit; TUI must not
   write projections or internal state directly.
4. Advance production Auth/RBAC: Chat API and MCP mutating writes must require
   token, role/capability, idempotency/audit, and the existing contract guards.
5. Attempt configured live evidence gates: MemoryOS Lite trace, GitHub server
   truth, Ray/Codex GOD runtime, OpenCode health/bounded runtime. Configured
   gate failures are release blockers. Use
   `uv run xmuse-live-gate-status-capture` to record configured/missing gate
   status as blocker artifacts when live proof has not yet been captured.
6. Separate natural GOD transcript evidence from deterministic replay and keep
   unresolved blockers from freezing a blueprint.
7. Add release readiness aggregation: tests, ruff, package boundary, internal
   review, live MemoryOS, GitHub server truth, provider evidence, and proof
   contamination audit. Use `uv run xmuse-release-readiness-capture` to turn
   supplied gate artifacts into a redacted readiness report.
8. Update docs/walkthrough/evidence. If validation passes, commit, push, and
   create a draft PR. Do not auto-merge.

Hard constraints:
- Use uv run for pytest, ruff, mypy, scripts, and Python entrypoints.
- Do not create xmuse/__init__.py.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  feature_lanes.json, xmuse/work/, xmuse/history/, or xmuse/logs/.
- Preserve unrelated worktree changes. Do not use git reset --hard.
- xmuse_core must not import runtime xmuse/ or memoryos_lite.
- MemoryOS remains REST-first.
- feature_lanes.json, TUI, dashboard, cards, and Ray actors are not durable
  authority.
- TUI may operate the workflow only through authorized contracts/APIs.
- Chat API and MCP writes must use configured tokens and
  `X-XMUSE-API-Key`/`X-XMuse-Operator-Role`/`X-XMuse-Operator-Capabilities`
  headers when auth is enabled.
- `XMUSE_DEPLOYMENT_PROFILE=production` must fail closed if Chat API or MCP
  write tokens are missing.
- Internal review proof is allowed for single-maintainer review truth, but it is
  not GitHub server-side enforcement proof.
- pr_merged requires server-side merge proof.
- Fake/local/contract evidence can support tests but cannot satisfy release
  live gates.
- The release-readiness capture command aggregates supplied artifacts; it does
  not create live MemoryOS/GitHub/provider proof by itself.
- The live-gate status capture command records blockers and missing
  prerequisites; it does not satisfy live gates by itself.
- If invoking OpenCode, use opencode-go/deepseek-v4-flash with --variant max as
  required by repo docs.
- Never auto-merge.

Stage protocol:
- Use the production plan as the source of truth.
- Record each stage with evidence envelope fields: stage_id, action, status,
  proof_level, source_authority, source_refs, target_refs, commands,
  test_results, artifacts, blocked_reason, owner, next_action.
- Every configured live gate failure must name the owner, attempted command, and
  next action.
- Continue only to independent stages when a configured live gate blocks.

Validation:
- Run focused pytest for every changed surface.
- Always run:
  uv run ruff check .
  git diff --check
  uv run pytest tests/xmuse/test_package_boundaries.py -q
- Include TUI, provider, MemoryOS, GitHub, MCP/Auth, and goal-stage tests when
  those surfaces change.

Completion:
Complete only after implementation, focused validation, docs/evidence updates,
proof-level notes, release-readiness result, commit/push status, and draft PR
status. Final report must distinguish production proof captured from remaining
manual gaps or release blockers.
```
