# Vision GOD Room Runtime Closure Goal Prompt

Use this concise prompt for the next long `/goal`. Detailed tasks and behavior
rules live in:

```text
docs/xmuse/vision-god-room-runtime-closure-plan.md
```

```text
Goal: Execute xmuse Vision GOD Room Runtime Closure.

Repository:
- /home/iiyatu/projects/python/xmuse

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/development-goal-worker-delegation-policy.md
- docs/xmuse/goal-stage-harness.md
- docs/xmuse/code-quality-and-archive-policy.md
- docs/xmuse/vision-overnight-autonomy-closure-plan.md
- docs/xmuse/vision-god-room-runtime-closure-plan.md
- /mnt/c/Users/iiyatu/Downloads/deep-research-report_11.md
- /mnt/c/Users/iiyatu/Downloads/mession_01.md

Runtime target:
- Run as an 8-10 hour production-grade long goal.
- If full closure does not fit, land the strongest validated production slice:
  GOD room event contract, speaker runtime, blueprint freeze compiler,
  lane budget/recovery, MemoryOS trace anchors, TUI operator cockpit, and
  replay evidence.
- If blocked by auth, live services, provider availability, GitHub admin state,
  or unavailable credentials, emit a manual_gap/blocker artifact and continue
  only to independent stages.

Objective:
Move xmuse beyond evidence/control readiness by making the GOD room runtime
real: durable speak/question/challenge/handoff/freeze events, replayable
speaker selection, typed blueprint freeze artifact, feature/laneDAG execution
contracts with budget and suspend reasons, MemoryOS trace anchors, TUI operator
cockpit, and honest release/replay evidence.

Priority order:
1. Establish current truth: git status, current head, PR #43 state, latest CI,
   xmuse/__init__.py absence, configured live resources, and proof map. Do not
   assume report_11, mession_01, or old walkthrough facts are current server
   truth.
2. Implement/advance the durable GOD room event contract for speak, question,
   challenge, handoff, and freeze_requested. Events need identity, causality,
   source refs, timestamp, and redaction-safe content.
3. Build the smallest replayable speaker runtime slice with at least three
   GOD participants, one challenge, one handoff, and one freeze request.
4. Build/advance the blueprint freeze compiler from GOD transcript evidence to
   a typed immutable freeze artifact with assumptions, conflicts, rejected
   alternatives, blockers, source refs, and revision behavior.
5. Advance feature/laneDAG runtime contracts from frozen blueprint/graph-set
   authority. Lanes need owner, input, output, dependencies, checks, allowed
   files, rollback constraints, memory anchors, and budget.
6. Add lane/stage budget and recovery behavior: retry budget, suspend reason,
   failure class, review triggers, and refactor_required for repeated failures.
7. Advance MemoryOS multi-GOD trace anchors while preserving REST-first
   governance, redaction, tombstones, and manual_gap when live service is not
   configured.
8. Advance TUI operator cockpit read models/widgets for room, blueprint,
   laneDAG, review queue, MemoryOS trace, replay bundle, and readiness. TUI
   mutations must go through Chat API/MCP/platform operator contracts.
9. Rebuild replay/release evidence and re-capture GitHub truth for the current
   head when auth allows. Keep review truth, enforcement truth, merge truth,
   and pr_merged separate.
10. Update docs/walkthrough/evidence. If validation passes, commit, push,
    update PR #43 body, and inspect GitHub Actions. Do not auto-merge.

Direct refactor rule:
- Repeated failure and demo-grade implementation are production blockers.
- If the same feature/stage/test cluster/runtime path fails twice with the same
  failure class, stop patch stacking and do root-cause analysis.
- If a third retry would be required, or supervisor/stage harness marks
  refactor_required, restructure or replace the failing boundary before retry.
- If production mainline depends on demo-grade code, do not wrap the demo path
  to make gates green. Isolate/archive it and build the contract-backed
  production path with tests.
- OpenCode may help only with bounded mechanical substeps after Codex defines
  the refactor boundary and gates. Codex must independently review the diff and
  evidence.

Hard constraints:
- Use uv run for pytest, ruff, scripts, and Python entrypoints.
- Preserve unrelated worktree changes. Do not use git reset --hard.
- Do not create xmuse/__init__.py.
- Do not commit runtime state: *.db, *.sqlite3, *.jsonl, feature_lanes.json,
  xmuse/work/, xmuse/history/, xmuse/logs/, or .goal-runs/.
- xmuse_core must not import runtime xmuse/ or memoryos_lite.
- MemoryOS remains REST-first.
- feature_lanes.json, TUI, dashboard, cards, Ray actors, and provider
  subprocess memory are not durable authority.
- pr_merged requires GitHub server-side merge proof.
- Internal review proof is not GitHub server-side enforcement.
- Fake/local/contract evidence can support tests but cannot satisfy production
  live gates.
- OpenCode is a bounded worker unless durable registration, capability,
  persistence, MCP/writeback, review, provider proof, and GitHub truth are all
  proven. If invoking OpenCode, use:
  opencode run --model opencode-go/deepseek-v4-flash --variant max ...

Evidence protocol:
- Record each stage/action with stage_id, action, status, proof_level,
  source_authority, source_refs, target_refs, commands, test_results,
  artifacts, blocked_reason, owner, and next_action.
- Use manual_gap for missing live/admin/operator evidence.
- Never label old artifacts, configured inventory, or successful rendering as
  fresh live/server/provider proof.
- Run proof contamination audit before claiming readiness.

Validation:
- Run focused pytest for every changed surface.
- Always run:
  uv run ruff check .
  git diff --check
  uv run pytest tests/xmuse/test_package_boundaries.py -q
  test ! -e xmuse/__init__.py

Completion:
Finish with stages completed/blocked, files changed, validation results, live
and server evidence captured, release readiness/replay decision, remaining
blockers, direct-refactor actions taken or deferred, GOD/OpenCode boundary
state, TUI authority paths, MemoryOS replay/governance state, PR #43 status,
commit/push status, and GitHub Actions status. Do not mark vision closure,
mainline merge closure, or pr_merged without server-side proof.
```
