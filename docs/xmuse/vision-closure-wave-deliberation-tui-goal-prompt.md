# Vision Closure Wave Deliberation TUI Goal Prompt

Use this concise prompt for the next `/goal`. Detailed tasks and behavior rules
live in `docs/xmuse/vision-closure-wave-deliberation-tui-plan.md`.

```text
Goal: Execute xmuse Vision Closure Wave - Deliberation TUI.

Authoritative repo:
- /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/vision-runtime-evidence-closure.md
- docs/xmuse/memoryos-lite-runtime-compatibility.md
- docs/xmuse/github-server-side-gate.md
- docs/xmuse/vision-closure-wave-deliberation-tui-plan.md
- /mnt/c/tmp/deep-research-report_07.md

Objective:
Turn the Textual TUI into the product front door for xmuse's vision loop:
GOD deliberation -> blueprint freeze readiness -> feature/lane/laneDAG
execution -> MemoryOS trace -> GitHub truth. Implement the detailed plan as
vertical slices with focused tests and docs.

Priority:
1. Confirm current truth map and avoid repeating already closed GitHub work.
2. Add a provider-agnostic TUI vision read model.
3. Build deliberation cockpit.
4. Build blueprint freeze panel.
5. Build laneDAG / review / patch-forward execution cockpit.
6. Build MemoryOS trace drawer.
7. Build GitHub truth panel.
8. Upgrade Provider Board into GOD runtime overview.
9. Produce walkthrough evidence and update docs.

Hard constraints:
- Use `uv run` for tests, lint, typecheck, and scripts.
- Do not create `xmuse/__init__.py`.
- Do not commit runtime state, DBs, sqlite files, jsonl files,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- `feature_lanes.json`, TUI cards, and dashboard data are projections, not
  authority.
- `xmuse_core` must not import runtime `xmuse/` or `memoryos_lite`.
- Default CI stays no-secrets and no-live-service.
- MemoryOS remains REST-first.
- Codex remains the production groupchat GOD provider boundary; OpenCode stays
  bounded/secondary in this wave.
- Do not label contract, fake, local, or synthetic evidence as live,
  server-side, natural, or real-provider proof.
- Do not render merge readiness as `pr_merged`.
- Preserve unrelated worktree changes and avoid destructive git commands.

Validation:
- Run focused pytest for every changed TUI/read-model/contract path.
- Include existing TUI state/adapter/navigation tests.
- Include deliberation, laneDAG, MemoryOS Lite interop, and GitHub truth tests
  when those surfaces are touched.
- Run `uv run ruff check .`.

Completion:
Complete only after implementation, focused validation, docs/walkthrough
updates, proof-level notes, fresh review, and a final report listing changed
files, validation results, remaining manual gaps, and next recommended
iteration.
```
