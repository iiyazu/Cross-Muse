# Dependency-First Closure Goal Prompt

更新日期: 2026-06-14

Use this as the concise prompt for the next long `/goal`.

```text
/goal

Implement the next production-closure slice for xmuse using dependency-first,
contract-first, authority-first, evidence-first behavior.

Read and follow:
- AGENTS.md
- docs/xmuse/README.md
- docs/xmuse/goal-behavior-contract.md
- docs/xmuse/code-review.md
- docs/xmuse/production-closure-gap-ledger.md
- docs/xmuse/development-goal-worker-delegation-policy.md
- docs/xmuse/goal-stage-harness.md

Target scope:
- Use the Wave A-E order in goal-behavior-contract.md and the current wave
  cursor in production-closure-gap-ledger.md.
- Do not average effort across L1-L11.
- Current default: Wave D / L9. Consume `xmuse.local_runner_recovery_proof.v1`
  as recovery enforcement lineage in the review/release evidence chain.
- Prove only what the slice produces. Do not upgrade worker output, local tests,
  recovery artifacts, CI, MemoryOS plans, TUI/read models, or release evidence
  aggregation into review/server truth.
- Do not expand Wave E / L10-L11 cockpit or overnight surfaces except to report
  explicit manual_gap / contract_proof boundaries.

Required process:
1. Truth refresh: inspect git status, branch, HEAD, recent commits, PR/CI if
   available, ledger snapshot, and existing contracts/tests.
2. Layer plan: record target layers, upstream blockers, authority owner,
   allowed writers/readers, forbidden authorities, negative cases, proof level,
   files, tests, and docs.
3. Production slice: implement the smallest real contract/store/resolver/runtime
   path with fail-closed behavior and evidence output.
4. OpenCode: use bounded OpenCode/DeepSeek workers only for inventories,
   mechanical candidate patches, low-intelligence lane execution, or read-only
   review. Invoke via goal_stage_runner.py using
   `opencode run --model opencode-go/deepseek-v4-flash --variant max`.
   Codex must independently review all output and remains final judge.
5. Targeted tests: add focused contract/runtime/negative tests after the
   authority path is clear. Do not use tests to invent architecture.
6. Self-review: audit false closure, TDD abuse, projection authority, provider
   inventory bypass, capture-vs-invocation proof, worker truth, GitHub truth,
   and repeated-failure refactor needs.
7. Ledger: update production-closure-gap-ledger.md only for claims actually
   changed, with explicit proof_level and forbidden claims preserved.

Validation:
- Run focused tests first.
- Run uv run ruff check .
- Run git diff --check.
- Run test ! -e xmuse/__init__.py.
- Do not claim broad suite, live MemoryOS, peer-GOD, natural deliberation,
  provider invocation live proof, ready_to_merge, pr_merged, or overnight
  readiness unless the corresponding proof was actually produced.

Final report:
- current_head, target_layers, proof_level;
- behavior changed;
- authority/proof path implemented;
- tests/checks run;
- ledger changes;
- manual_gaps and forbidden claims that remain.
```
