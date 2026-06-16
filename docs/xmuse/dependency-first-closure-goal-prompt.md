# Dependency-First Closure Goal Prompt

更新日期: 2026-06-15

Use this as the concise prompt for the next long `/goal`.

```text
/goal

Continue xmuse production closure using dependency-first, authority-first,
evidence-first behavior. Tests verify production paths; tests do not define
architecture.

Treat /goal as desired state and durable artifacts/status as observed state.
Work as an idempotent reconcile loop: target condition -> observed durable
state -> authority-owned producer/consumer path -> fail-closed gap or proof.

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/goal-behavior-contract.md
- docs/xmuse/anti-tdd-abuse-policy.md
- docs/xmuse/next-production-closure-long-goal.md
- docs/xmuse/production-closure-gap-ledger.md
- docs/xmuse/production-closure-wave-map.md
- docs/xmuse/code-review.md
- docs/xmuse/github-git-behavior-policy.md
- docs/xmuse/development-goal-worker-delegation-policy.md
- docs/xmuse/goal-stage-harness.md

Target:
- Execute docs/xmuse/next-production-closure-long-goal.md.
- Use medium-grained autonomous task slices inside the goal.
- Preserve Wave order. Do not redo L1-L2 unless authority drift is found.
- Current focus: Wave D / L9 execution-review-patch-forward-release lineage.
- Touch Wave E / L10 only as honest aggregation after L9 lineage exists.

Required process:
1. Refresh truth: git status/branch/HEAD/log, PR/CI if available, ledger,
   contracts, tests.
2. Slice the work autonomously at medium granularity, but keep upstream
   authority before downstream evidence/UI.
3. For each slice, identify authority owner, forbidden authorities, proof level,
   negative cases, manual gaps, forbidden claims, stable source/target refs,
   and owner lineage.
4. Implement the smallest real production path with fail-closed behavior and
   evidence output.
5. Use OpenCode/DeepSeek only as bounded worker/reviewer:
   `opencode run --model opencode-go/deepseek-v4-flash --variant max ...`.
   Candidate patches are allowed; Codex remains final judge.
   When Codex quota risk is high, run stages through
   `scripts/goal_stage_runner.py` with Codex model fallback enabled as described
   in `docs/xmuse/goal-stage-harness.md`.
6. Add targeted tests after the authority/proof path is clear.
7. Enforce docs/xmuse/anti-tdd-abuse-policy.md: tests verify real production
   paths and must not replace authority/proof producers.
8. Preserve proof monotonicity and append-only forbidden_claims; do not remove
   a forbidden claim without matching upstream live/server proof.
9. Self-review false closure and update the ledger only for changed claims.
10. Follow docs/xmuse/github-git-behavior-policy.md: do not push new work into
   PR #43 unless explicitly instructed; prefer small scoped PRs.

Validation:
- uv run pytest <focused tests> -q
- uv run ruff check .
- git diff --check
- test ! -e xmuse/__init__.py
- package boundary tests if core/runtime boundary changed

Final report:
- internal slices completed;
- authority/proof path changed;
- OpenCode stages used and how Codex verified them;
- tests/checks run;
- ledger changes;
- remaining manual_gaps and forbidden claims.

Do not claim peer-GOD, natural groupchat closure, live MemoryOS, GitHub
review/merge truth, ready_to_merge, pr_merged, overnight readiness, or TUI
production closure without corresponding live/server proof. Do not commit or
push unless explicitly instructed.
```
