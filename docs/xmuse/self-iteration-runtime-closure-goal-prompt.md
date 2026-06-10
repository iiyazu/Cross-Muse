# Self-Iteration Runtime Closure Goal Prompt

Use this short prompt for the next long-running goal. Detailed task and behavior
rules live in `docs/xmuse/self-iteration-runtime-closure-plan.md`.

```text
Execute the xmuse Self-Iteration Runtime Closure plan.

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/mainline-contracts.md
- docs/xmuse/self-iteration-runtime-closure-plan.md

Objective:
Produce one replayable, auditable xmuse self-iteration loop:
human request -> GOD speech-act replay -> frozen blueprint -> feature/lane/laneDAG
-> runnable lane dispatch -> subagent runtime contract -> evidence bundle
-> review decision / patch-forward -> GitHub gate evidence -> MemoryOS writeback
-> replay documentation.

Execution phases:
1. Align GitHub truth evidence for CI, required checks, CODEOWNERS, and PR gate.
2. Build deterministic groupchat -> frozen blueprint replay fixture.
3. Convert blueprint to feature/lane/laneDAG authority sample.
4. Add or strengthen SubagentRuntimeContract and evidence bundle.
5. Prove review pass/fail and patch-forward lane behavior.
6. Prove REST-first MemoryOS writeback with fake default tests and live opt-in boundary.
7. Publish replay artifact and update broad-suite/runtime debt.
8. Create/close issues #28-#34 or equivalent tracked issues with validation evidence.

Hard constraints:
- Use `uv run` for all tests, lint, typecheck, and scripts.
- Do not create `xmuse/__init__.py`.
- Do not commit runtime state: *.db, *.sqlite3, *.jsonl, feature_lanes.json,
  xmuse/work/, xmuse/history/, xmuse/logs/.
- `xmuse_core` must not import runtime `xmuse/` or `memoryos_lite`.
- Default CI must remain no-secrets and no-live-service.
- MemoryOS remains REST-first.
- `feature_lanes.json` is projection/queue only, never authority.
- Do not describe contract proof or fake runtime proof as live runtime proof.

Required validation:
- `uv run ruff check .`
- focused pytest for all changed contracts
- `uv run mypy ...` for changed typed core modules
- package boundary tests when imports/integrations are touched
- existing #13-#27 contract gates must not regress

Completion:
Mark complete only after current evidence proves every phase is implemented,
validated, documented, pushed, and tracked through GitHub issues with comments
showing commit and command evidence.
```
