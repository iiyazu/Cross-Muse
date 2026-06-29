# OpenCode-In Long Runtime Evidence Goal Prompt

Use this concise prompt for the next `/goal`. Detailed tasks and behavior rules
live in `docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md`.

```text
Goal: Execute the xmuse OpenCode-in Long Runtime Evidence Closure iteration.

Authoritative repo:
- /home/iiyatu/projects/python/xmuse

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/goal-stage-harness.md
- docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md
- /mnt/c/tmp/deep-research-long-blueprint.md

Objective:
Run one evidence-closure iteration that moves xmuse from contract/fake proof
toward trustworthy long-runtime proof. Do not broaden product surface. Fix proof
semantics first, make runtime evidence observable, then cautiously expand
OpenCode-in participation under bounded rules.

Execution model:
- Codex remains outer controller, reviewer, and final judge.
- OpenCode-in is a bounded implementation executor for scoped stages.
- Use OpenCode through `scripts/goal_stage_runner.py`; do not bypass the stage
  harness.
- Use fresh adversarial review for completed behavior changes.

Mandatory stage protocol:
Every phase must execute through:

uv run python scripts/goal_stage_runner.py \
  --stage-manifest /abs/path/to/stage-manifest.json \
  --engine opencode \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output .goal-runs/<stage_id>/result.json

Gate rules:
- Advance only when `result.json.status == "ok"`.
- `--dry-run` is preview only and never pass evidence.
- `retry` reruns the same stage within manifest `max_retries`.
- `blocked` stops or skips only to independent stages with a documented blocker,
  owner, and next action.

Autonomy:
- You may split stages, create local stage manifests, choose focused tests,
  update docs for changed behavior, and use fake collectors when live credentials
  are absent.
- You may defer a P1/P2 task only with an explicit blocker and owner.
- You must not mutate external GitHub settings, claim live/server-side proof from
  local files, promote OpenCode beyond bounded secondary authority, or commit
  runtime state.

Priority:
1. Fix merge readiness vs real merge fact semantics.
2. Make MemoryOS Lite trace evidence discoverable and testable.
3. Separate deterministic replay from natural deliberation proof.
4. Pilot OpenCode-in as a bounded deliberation participant.
5. Scaffold GitHub server-side truth collection.
6. Add long-run heartbeat/replay evidence.
7. Update docs, debt, and handoff.
8. Run final validation and adversarial review.

Hard constraints:
- Use `uv run` for all tests, lint, and scripts.
- Do not create `xmuse/__init__.py`.
- Do not commit runtime state, DBs, sqlite files, jsonl files,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- `feature_lanes.json` is projection/queue only, never authority.
- `xmuse_core` must not import runtime `xmuse/` or `memoryos_lite`.
- Default CI stays no-secrets and no-live-service.
- MemoryOS remains REST-first.
- Contract/fake/local evidence must not claim live provider, live MemoryOS,
  natural live deliberation, or server-side GitHub proof.
- `pr_merged` requires server-side GitHub merge truth.

Validation:
- `uv run ruff check .`
- focused pytest for every changed contract/runtime path
- package boundary tests if imports change
- provider policy tests if OpenCode behavior changes
- MemoryOS Lite fake/default tests if trace evidence changes
- GitHub truth tests if merge/readiness models change

Completion:
Complete only after the detailed plan stages are implemented, validated,
documented, and reviewed, or explicitly blocked with owner and next action.

Final response:
- completed stages
- files changed
- proof-level changes
- validation commands and results
- live/server-side evidence captured or missing
- blockers and owners
- next recommended iteration
```
