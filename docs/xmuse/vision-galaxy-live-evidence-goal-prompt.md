# Vision Galaxy Live Evidence Goal Prompt

Use this concise prompt for the next `/goal`. Detailed tasks and behavior rules
live in `docs/xmuse/vision-galaxy-live-evidence-plan.md`.

```text
Goal: Execute xmuse Vision Galaxy Live Evidence Pack.

Authoritative repo:
- /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md
- docs/xmuse/vision-runtime-evidence-closure.md
- docs/xmuse/memoryos-lite-runtime-compatibility.md
- docs/xmuse/github-server-side-gate.md
- docs/xmuse/vision-galaxy-live-evidence-plan.md
- /mnt/c/tmp/deep-research-report_07.md

Objective:
Produce the next xmuse vision evidence wave: connect natural multi-GOD
deliberation, frozen blueprint, feature/lane/laneDAG execution, review and
patch-forward evidence, MemoryOS trace, provider runtime evidence, and GitHub
truth into one auditable evidence pack. Do not overstate proof.

Priority:
1. Establish current truth map and preserve unrelated worktree changes.
2. Export or fixture-label a replayable multi-GOD deliberation transcript.
3. Trace frozen blueprint refs into feature/lane/laneDAG execution evidence.
4. Capture provider runtime/session evidence with strict boundary labels.
5. Capture or explicitly gap MemoryOS REST trace continuity.
6. Refresh GitHub checks/review/merge/server-side truth without confusing
   readiness with fact.
7. Produce docs/xmuse/vision-galaxy-live-evidence-pack.md and update docs index.

Hard constraints:
- Use `uv run`; never bare pytest/ruff.
- Do not create xmuse/__init__.py.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  feature_lanes.json, xmuse/work/, xmuse/history/, or xmuse/logs/.
- TUI/dashboard/cards/feature_lanes are projections, not authority.
- xmuse_core must not import runtime xmuse/ or memoryos_lite.
- Default validation stays no-secrets and no-live-service.
- MemoryOS remains REST-first.
- Codex remains the production primary GOD provider boundary.
- OpenCode remains bounded unless persistent peer-GOD semantics are proven.
- If invoking OpenCode, use exactly:
  opencode --model opencode-go/deepseek-v4-flash:max run ...
- Never label contract/fake/local evidence as live, server-side, natural, or
  real-provider proof.
- Never render merge readiness as pr_merged.

Validation:
- Run focused pytest for every changed surface.
- Include package boundary and mainline contract tests when contracts/docs move.
- Run uv run ruff check .
- Run git diff --check.
- Request a fresh review before final completion.

Completion:
Complete only after the evidence pack, focused validation, proof-level/manual
gap notes, fresh review, and a final report listing changed files, validation
results, remaining gaps, and the next recommended iteration.
```
