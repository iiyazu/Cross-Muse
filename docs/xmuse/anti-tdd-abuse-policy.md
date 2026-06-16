# XMuse Anti-TDD-Abuse Policy

更新日期: 2026-06-16

本文固化 xmuse 长 `/goal` 的 anti-TDD 行为规范。它补充
`docs/xmuse/goal-behavior-contract.md`，优先级高于任何 “test first” 风格的局部
习惯。

## Core Rule

xmuse development is not test-driven-first. It is dependency-first,
authority-first, contract-first, and evidence-first.

```text
Tests are verification, not architecture authority.
Green tests are evidence, not completion.
The /goal prompt is desired state; artifacts/status are observed state.
```

Codex 可以使用 TDD，但不得让 TDD 变成自证闭环。测试只能验证真实生产路径；测试
不能定义架构、替代 runtime producer、伪造 authority，或把 fixture/mock 小世界当作
生产闭环。

## Before Tests

在写或修改测试前，必须先识别：

1. target L layer and upstream dependencies;
2. authority owner / durable store / server truth source;
3. real production producer-consumer path;
4. proof level: `contract_proof`, `local_runtime_proof`, `opt_in_live_proof`,
   `server_side_truth`, or `manual_gap`;
5. claims that remain forbidden.
6. desired condition and observed artifact/status condition, when the task is a
   closure/reconcile slice;
7. stable `source_refs`, `target_refs`, and owner lineage expected from the
   production path.
8. admission checks that should reject missing refs, missing owner lineage,
   proof inflation, deleted `manual_gaps`, or deleted `forbidden_claims`.

如果上述信息不清楚，先读 ledger、contracts、stores、runtime path 和 existing tests；
不要先写 speculative tests。

## Acceptable TDD

TDD 只在以下条件同时满足时合格：

- behavior is externally observable or a public/low-level contract;
- production path is understood;
- test protects a real bug, boundary, contract, or failure mode;
- test would still be valuable under a different correct implementation;
- test does not mock away the authority/proof path under review.

适合先写或同步写 targeted tests 的任务：

- bug reproduction;
- parser/serializer/contract boundary;
- fail-closed negative case;
- public API behavior;
- regression around a previously proven failure.

## TDD Abuse

以下任一情况都视为 TDD abuse：

1. Tests are written before authority/proof path is identified.
2. Tests assert closure states not backed by production producers.
3. Tests construct artifacts that runtime should produce.
4. Mocks bypass selected GOD binding, provider invocation, recovery enforcement,
   independent review, GitHub truth, or MemoryOS truth.
5. Evidence-pack fields are added without upstream producers.
6. TUI/read models expand while upstream authority remains missing.
7. Final report says "tests passed" where it should say proof level and
   remaining `manual_gap`.
8. Snapshot/text assertions lock incidental output while leaving authority
   boundaries untested.
9. Tests are modified, skipped, loosened, or deleted only to make the run green.
10. Tests assert desired state directly instead of verifying observed durable
    artifacts/status conditions.
11. Tests pass by deleting or omitting inherited `forbidden_claims`.
12. Tests use unscoped filenames, pane ids, worker summaries, or opaque strings
    where production closure requires lane/graph-scoped refs.
13. Tests verify candidate artifacts but never verify an independent verdict
    that cites those candidates before review truth is claimed.
14. Tests assert `ready`, `closed`, `passed`, or release handoff truth without
    checking condition names, source refs, target refs, owner lineage, and
    inherited gaps.
15. Tests mock or bypass the producer in the default closure chain:
    `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff`.
16. Tests treat MemoryOS Lite traces, plans, or summaries as the authority for
    L8/L9 recovery, execution-candidate validity, review truth, or handoff
    truth.

## Required Response To TDD Abuse

If TDD abuse is detected:

1. Stop adding tests.
2. Identify the missing authority or production producer.
3. Convert speculative tests into `manual_gap` documentation or remove them.
4. Implement or refactor the smallest real producer-consumer path.
5. Add targeted regression/contract tests only after that path exists.
6. Update the ledger with honest proof boundaries.
7. Preserve inherited `forbidden_claims`; remove one only when new upstream
   live/server proof explicitly justifies it.
8. If repeated failures or duplicated proof parsing triggered the abuse, create
   or implement a bounded `refactor_required` slice before adding more tests.

Repeated failure or demo-grade production code must trigger direct refactor,
not another stack of tests and patches.

If the same proof parsing, handoff evaluation, condition classification, or
failure handling appears in two or more production consumers, stop growing tests
around each copy. Refactor the shared boundary first, then add focused tests for
the consolidated producer/consumer path.

## Closure Test Shape

For closure/reconcile work, a good test verifies the observed state produced by
the real path:

- desired condition is defined by the goal or contract;
- production code emits durable artifact/status with stable refs;
- owner lineage and inherited `forbidden_claims` are present;
- missing schema/artifact/owner fails closed to `manual_gap`, `blocked`, or
  `refactor_required`;
- rerun is idempotent and does not duplicate artifacts or alter immutable
  lineage.

Avoid tests that only assert a final boolean such as "ready", "closed", or
"passed". A final boolean without proof refs and owner lineage is not closure
evidence.

For controller-style closure, tests should validate the transition and
admission checks rather than define architecture:

- `Recovery` may produce or block `ExecutionCandidate`;
- `ExecutionCandidate` remains candidate evidence until `ReviewClosure` cites
  it;
- `ReviewClosure` may feed `ReleaseHandoff`, but worker output and local tests
  do not become review truth;
- `ReleaseHandoff` may aggregate only upstream artifacts and must preserve
  `ServerTruthPending` until server-side truth exists;
- MemoryOS Lite may receive provenance refs but must not decide the transition.

## Completion Standard

Completion requires all of the following:

- requested behavior is implemented;
- authority/proof path is real and fail-closed;
- relevant targeted tests pass;
- diff review finds no fixture special-casing, proof inflation, weakened tests,
  or projection-as-authority;
- ledger records the actual proof level and remaining `manual_gap`;
- final report states forbidden claims that still remain forbidden.

Passing tests alone is never sufficient.
