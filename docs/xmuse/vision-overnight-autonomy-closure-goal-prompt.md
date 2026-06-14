# Vision Overnight Autonomy Closure Goal Prompt

Use this concise prompt for the next long `/goal`. Detailed tasks and behavior
rules live in:

```text
docs/xmuse/vision-overnight-autonomy-closure-plan.md
```

```text
Goal: Execute xmuse Vision Overnight Autonomy Closure.

Repository:
- /home/iiyatu/projects/python/xmuse

Read first:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/development-goal-worker-delegation-policy.md
- docs/xmuse/goal-stage-harness.md
- docs/xmuse/vision-production-evidence-control-closure-plan.md
- docs/xmuse/vision-production-evidence-control-closure-walkthrough.md
- docs/xmuse/vision-overnight-autonomy-closure-plan.md
- /mnt/c/tmp/deep-research-report_10.md
- /mnt/c/tmp/outer-muse.md

Runtime target:
- Run as an 8-10 hour production-grade long goal.
- If full closure does not fit, land the strongest validated production slice
  and record the next production slice explicitly.
- If blocked by auth, live services, provider availability, GitHub admin state,
  or unavailable credentials, emit a manual_gap/blocker artifact and continue
  only to independent stages.

Objective:
Turn the current production evidence/control base into a repeatable overnight
autonomy loop: durable GOD runtime continuity, natural multi-GOD transcript
evidence, feature-graph-first execution, supervisor heartbeat/checkpoint
fallback, MemoryOS governance/replay, fresh GitHub truth, TUI proof cockpit,
and release evidence pack without overstating proof.

Priority order:
1. Establish current truth: git status, current head, PR #43 state, latest CI,
   xmuse/__init__.py absence, configured live resources, and proof map. Do not
   assume report_10 or old walkthrough facts are current server truth.
2. Prepare stage manifests/evidence envelopes so every bounded stage produces
   result.json and honest proof labels.
3. Advance GOD runtime continuity and natural transcript evidence. Selected
   GODs must expose CLI/provider/session/capability/heartbeat/proof state.
   OpenCode remains bounded unless peer-GOD proof is independently captured.
4. Advance feature-graph-first execution: feature owner/ready-set contracts,
   laneDAG dependencies, patch-forward lineage, and no double-authority writes.
5. Integrate the overnight supervisor loop: heartbeat, stage journal,
   checkpoint/resume, issue queue, self-review, failure classification, retry
   budget, and manual_gap fallback with simulated long-run tests.
6. Advance MemoryOS governance and replay: personal/task/shared/global memory
   policy, tombstone/redaction discipline, REST-first live trace path, and a
   replay bundle linking transcript, blueprint, MemoryOS trace, GitHub truth,
   long-run summary, and readiness artifacts.
7. Re-capture fresh GitHub server truth for the current PR/head when auth
   allows. Keep review truth, enforcement truth, merge truth, and pr_merged
   separate. Old captures are stale unless validated for current head.
8. Advance TUI proof cockpit/control: proof badges, evidence panels, replay
   export/readiness views, and operator actions through Chat API/MCP/platform
   contracts only.
9. Attempt configured live gates and write release evidence pack/readiness and
   proof-contamination outputs. Configured failing gates are release blockers.
10. Update docs/walkthrough/evidence. If validation passes, commit, push,
    update PR #43 body, and inspect GitHub Actions. Do not auto-merge.

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
and server evidence captured, release readiness decision, remaining blockers,
GOD/OpenCode boundary state, TUI authority paths, MemoryOS replay/governance
state, PR #43 status, commit/push status, and GitHub Actions status. Do not
mark overnight autonomy closed while natural transcript, MemoryOS, provider,
GitHub truth, or supervisor proof remains uncaptured or only stale.
```
