# Vision Runtime Evidence Closure Goal Prompt

Use this concise prompt for `/goal`. Detailed tasks and behavior rules live in
`docs/xmuse/vision-runtime-evidence-closure-plan.md`.

```text
Goal: Execute xmuse Vision Runtime Evidence Closure after 2fdb299.

Authoritative repo: /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/self-iteration-runtime-closure.md
- docs/xmuse/broad-suite-baseline-debt.md
- docs/xmuse/vision-runtime-evidence-closure-plan.md
- /mnt/c/tmp/deep-research-report_06.md

Objective:
Move the 2fdb299 self-iteration closure from local contract/fake proof toward a stricter runtime evidence pipeline.

Implement the plan document end to end:
1. Put self-iteration proof into default CI.
2. Split fake/local merge readiness from real GitHub merge facts.
3. Verify or precisely document GitHub server-side gate evidence.
4. Separate deterministic replay from real multi-GOD deliberation evidence.
5. Add explicit opt-in live MemoryOS Lite evidence.
6. Prepare real Ray/Codex/MCP runtime soak evidence capture.
7. Update docs, debt, and tracking issues.

Hard constraints:
- Use `uv run` for tests, lint, typecheck, and scripts.
- Do not create `xmuse/__init__.py`.
- Do not commit runtime state, DBs, sqlite, jsonl, `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- `xmuse_core` must not import runtime `xmuse/` or `memoryos_lite`.
- Default CI stays no-secrets and no-live-service.
- MemoryOS remains REST-first.
- Do not describe contract, fake, local, or synthetic evidence as live/server-side/real-provider proof.
- Do not use destructive git commands.
- Preserve unrelated user worktree changes.

Validation:
- `uv run ruff check .`
- focused pytest for changed contracts
- `uv run mypy ...` for changed typed core modules
- package boundary tests when imports/integrations are touched
- existing #13-#34 contract gates must not regress

Completion:
Complete only after implementation, validation, docs/debt updates, commit, push, and GitHub issues #35-#41 or equivalent tracked issues contain evidence comments and are closed or explicitly blocked with reason.
```
