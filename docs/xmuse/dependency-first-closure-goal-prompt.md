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
- Prioritize Goal A / Wave A: L1-L2 authority root.
- Close or materially advance durable ProviderAccount, GodProfile, and
  RoomSelectedGodBinding authority.
- Prove L3/L4 consume selected binding, or record manual_gap where the runtime
  path is not yet implemented.
- Do not expand L11 cockpit/TUI except to preserve explicit manual_gap or
  contract_proof labels.

Required process:
1. Truth refresh: inspect git status, branch, HEAD, recent commits, PR/CI if
   available, ledger snapshot, and existing contracts/tests.
2. Layer plan: record target layers, upstream blockers, authority owner,
   allowed writers/readers, forbidden authorities, negative cases, proof level,
   files, tests, and docs.
3. Production slice: implement the smallest real contract/store/resolver/runtime
   path with fail-closed behavior and evidence output.
4. Targeted tests: add focused contract/runtime/negative tests after the
   authority path is clear. Do not use tests to invent architecture.
5. Self-review: audit false closure, TDD abuse, projection authority, provider
   inventory bypass, capture-vs-invocation proof, worker truth, GitHub truth,
   and repeated-failure refactor needs.
6. Ledger: update production-closure-gap-ledger.md only for claims actually
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
