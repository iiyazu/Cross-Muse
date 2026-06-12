# Vision Operator-Closed Overnight Loop Goal Prompt

Use this concise prompt for the next 8 hour `/goal`. Detailed tasks and behavior
rules live in `docs/xmuse/vision-operator-closed-overnight-loop-plan.md`.

```text
Goal: Execute xmuse Vision Operator-Closed Overnight Loop.

Runtime budget:
- Target approximately 8 hours.
- Work autonomously within the constraints below.
- If blocked by auth, live services, provider availability, or GitHub admin
  state, emit a manual_gap artifact and move to the next high-value task.

Authoritative repo:
- /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md
- docs/xmuse/vision-galaxy-live-evidence-plan.md
- docs/xmuse/vision-operator-closed-overnight-loop-plan.md
- /mnt/c/tmp/deep-research-report_08.md

Objective:
Move xmuse from a read-only TUI visibility wave toward an operator-closed
overnight loop. The cockpit should trigger or import evidence-oriented actions,
inspect laneDAG blockers and lineage, supervise long-running work with
checkpoints, and produce auditable artifacts without overstating live proof.

Priority:
1. Establish the current truth map and preserve unrelated worktree changes.
2. Add TUI or slash-command actuation for evidence actions:
   transcript export/load, GitHub truth refresh/load, MemoryOS trace
   refresh/load, and blocker/source-ref navigation.
3. Improve laneDAG drill-down: dependencies, gates, review verdicts,
   patch-forward lineage, merge blockers, and source refs.
4. Add an overnight supervisor contract or harness: heartbeat, stage journal,
   checkpoint/resume, issue queue, self-review, failure classification, and
   manual_gap fallback.
5. Add an opt-in live soak harness for transcript, MemoryOS, provider, and
   GitHub evidence. Default tests must remain no-secrets and no-live.
6. Produce or update docs/evidence artifacts and README entries.

Hard constraints:
- Use uv run for pytest, ruff, mypy, scripts, and Python entrypoints.
- Do not create xmuse/__init__.py.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  feature_lanes.json, xmuse/work/, xmuse/history/, or xmuse/logs/.
- TUI/dashboard/cards/feature_lanes are projections, not authority.
- xmuse_core must not import runtime xmuse/ or memoryos_lite.
- MemoryOS remains REST-first.
- Codex remains the production primary GOD provider boundary.
- OpenCode remains bounded unless persistent peer-GOD semantics are proven.
- If invoking OpenCode, use exactly:
  opencode run --model opencode-go/deepseek-v4-flash --variant max ...
- Never label contract/fake/local evidence as live, server-side, natural, or
  real-provider proof.
- Never render readiness as completed fact, especially merge_ready as
  pr_merged.
- Preserve unrelated worktree changes and avoid destructive git commands.

Self-review cadence:
- Every 45-60 minutes or at each stage boundary, check whether the work still
  serves the overnight operator loop, whether proof labels are honest, whether
  projections stayed projections, and whether runtime/package-boundary rules
  still hold.

Validation:
- Run focused pytest for every changed surface.
- Include package boundary tests if imports or package boundaries move.
- Run uv run ruff check .
- Run git diff --check.

Completion:
Complete only after implementation, focused validation, docs/evidence updates,
proof-level/manual_gap notes, and a final report listing changed files,
validation results, remaining gaps, and the next recommended iteration. PR
preparation is allowed only after the core loop is validated; if GitHub auth is
unavailable, record the gap without claiming a PR exists.
```
