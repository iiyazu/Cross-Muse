# XMuse Code Review Contract

更新日期: 2026-06-14

本文档定义 xmuse 生产闭环相关改动的 review 要求。它补充
`docs/xmuse/goal-behavior-contract.md`，重点审查 false closure，而不只是代码风格。

## Review Stance

Review findings must prioritize:

1. Authority boundary violations.
2. Proof-level inflation.
3. Runtime path bypasses.
4. Missing negative/fail-closed behavior.
5. TDD abuse or fixture overfitting.
6. Regression risk, security risk, and concurrency/persistence risk.

Passing tests are evidence, not completion. A green test run does not prove
provider invocation, MemoryOS live trace, review truth, or GitHub merge truth.

## Required Inputs

Before review, inspect:

- `git status -sb`
- target diff
- `docs/xmuse/production-closure-gap-ledger.md`
- affected contracts/stores/runtime paths
- tests changed in the same task
- evidence artifacts or manual-gap records

Review summary must identify:

```yaml
target_layers: ["L2"]
proof_level_claimed: contract_proof
authority_objects_touched: ["ProviderAccount", "GodProfile", "RoomSelectedGodBinding"]
projection_surfaces_touched: ["provider board"]
runtime_paths_touched: ["L3 authorship resolver", "L4 invocation resolver"]
server_truth_claimed: false
manual_gaps_preserved: []
```

## False-Closure Checklist

Ask these questions for every production-closure diff:

1. Did this change close an upstream authority gap, or only add downstream
   projection?
2. Is every new truth claim backed by durable store, runtime artifact, or server
   truth?
3. Is any fixture/mock being described as live proof?
4. Does any TUI/read model mutate authoritative state directly?
5. Does any provider inventory bypass `RoomSelectedGodBinding`?
6. Does any L5 capture claim imply L4 invocation without artifact lineage?
7. Does any lane execution bypass L7 laneDAG authority or L8 recovery?
8. Does any worker output become review truth without independent review?
9. Does any release evidence claim `pr_merged` without GitHub server-side merge
   proof?
10. Should this be direct refactor instead of another patch/test stack?

Any "yes" answer is a blocking finding unless the diff explicitly records
`manual_gap`, `contract_proof`, or `refactor_required` and preserves forbidden
claims.

## Layer-Specific Review Focus

| Layer | Review focus | Blocking false claim |
|---|---|---|
| L1 | Approved writers, durable authority, projection boundaries | Projection or actor memory treated as state authority |
| L2 | ProviderAccount, GodProfile, RoomSelectedGodBinding | Provider inventory or raw CLI string treated as peer-GOD identity |
| L3 | Durable room events and actor/binding lineage | Contract fixture treated as natural groupchat proof |
| L4 | Provider invocation artifact producer | Imported artifact or request body treated as live invocation |
| L5 | Artifact capture into durable `speak` event | Capture proof described as invocation proof |
| L6 | Freeze source event lineage | Clean fixture freeze treated as live deliberation closure |
| L7 | Frozen blueprint to laneDAG authority | `feature_lanes.json` treated as execution authority |
| L8 | Runner/supervisor recovery enforcement | Recovery classifier exists but runner can bypass it |
| L9 | Independent review decision and patch-forward lineage | Worker self-report or local tests treated as review truth |
| L10 | MemoryOS/release/GitHub truth separation | CI success treated as review/merge truth |
| L11 | Cockpit projection and native CLI bridge | Raw terminal output treated as durable GOD speech |

## TDD Abuse Review

A review must flag TDD abuse when:

- Tests were written before the target authority/proof path was identified.
- New tests assert final closure states not produced by runtime.
- Tests construct final artifacts that production code should emit.
- Mocks bypass selected GOD binding, provider invocation, recovery enforcement,
  or review truth.
- Snapshot/UI tests dominate without protecting authority/proof boundaries.
- Evidence-pack fields are added without upstream producers.
- Final report says "tests pass" where it should say `contract_proof`,
  `manual_gap`, or `local_runtime_proof`.

Required response:

- Stop adding tests.
- Identify missing producer/consumer path.
- Convert speculative tests into manual-gap documentation or delete them.
- Implement the smallest real path, then add targeted tests.

## Worker Output Is Candidate Evidence

OpenCode, Codex subagents, and other workers may produce candidate patches,
candidate artifacts, and audit summaries. They do not produce final truth.

Review must verify:

- scope was not exceeded;
- runtime/cache state was not committed;
- package boundaries remain intact;
- claimed proof level matches evidence;
- no live/server truth is inferred from worker self-report;
- Codex independently ran or checked the required gates.

## GitHub Truth Boundary

GitHub truth must come from GitHub server state, not local git state.

- Local clean worktree is not PR review truth.
- Local test or CI success is not merge truth.
- `ready_for_replay` is not `ready_to_merge`.
- `pr_merged` requires server-side merge proof.
- Draft/open/unmerged PR state must remain a forbidden-claim boundary until
  refreshed server truth says otherwise.

## Review Output Format

Use this format:

```text
Blocking findings:
- [file:line] finding and proof boundary.

Non-blocking concerns:
- risk or follow-up.

Tests and evidence checked:
- commands or artifacts reviewed.

Forbidden claims preserved:
- claims that remain invalid.

Verdict: accept / revise
```

If there are no blocking findings, say that clearly and still list residual
risk or unverified live/server proof.
