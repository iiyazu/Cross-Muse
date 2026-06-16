# XMuse Goal Behavior Contract

更新日期: 2026-06-15

本文档定义 Codex 执行 xmuse 长 `/goal` 时的固定行为。它约束开发过程，
不改变 xmuse 产品运行时权限模型。

最高优先级规则:

```text
Tests are verification, not authority.
TUI is projection, not authority.
Evidence pack is aggregation, not production.
A layer is closed only when its upstream authority and proof producer exist.
The /goal prompt is desired state; durable artifacts/status are observed state.
```

## Core Principle

Codex 的行为必须从:

```text
写测试 -> 让测试红 -> 写最小代码让测试绿 -> 宣称完成
```

改为:

```text
读 ledger / 现状
-> 锁定 L 层依赖
-> 定义 authority/proof contract
-> 实现最小生产切片
-> 写 targeted regression / contract tests
-> 自审伪闭环
-> 更新 evidence / gap ledger
-> 只声明被 proof 覆盖的能力
```

允许测试，但禁止测试驱动架构。测试必须验证真实 authority、runtime path、
failure mode 和 evidence boundary；测试不得构造一个 fixture/mock 小世界来替代
生产路径。

Anti-TDD 是整个 goal 的全局行为规范，不是测试阶段的局部建议。详细硬规则见
`docs/xmuse/anti-tdd-abuse-policy.md`。若不强制
dependency-first / anti-TDD 纪律，长 `/goal` 的总工作量预期会增加 25%-50%，
主要来自“测试绿但 runtime 未闭合”的回滚、证据重写和伪闭环修正成本。因此每个
阶段都必须先确认 L 层依赖、authority owner、producer/consumer path 和 proof
boundary，再决定是否需要 targeted tests。

## Desired/Observed Closure Discipline

Treat every long `/goal` like a small reconcile loop:

- `/goal` describes desired state: target wave/layer, upstream conditions,
  authority owner, proof required, forbidden claims, and validation gates.
- Durable artifacts, stores, status records, and server APIs describe observed
  state.
- Tests, logs, worker reports, TUI panels, release packs, and CI are evidence or
  projections; they are not authority and must not write truth backward into the
  desired state.

If observed state cannot satisfy a desired condition, record
`manual_gap`, `blocked`, or `refactor_required`. Do not infer closure from
adjacent evidence.

Every production slice should make the current condition explicit. Use names
like:

- `RecoveryArtifactPresent`
- `RecoveryAllowsProgress`
- `ValidatedExecutionCandidatePresent`
- `IndependentReviewVerdictPresent`
- `ReleaseHandoffEvaluated`
- `ServerTruthPending`

Conditions must be idempotent: rerunning the same reconciliation should not
duplicate artifacts, erase lineage, or silently upgrade proof.

## Proof Levels

| Proof level | Meaning | Forbidden overread |
|---|---|---|
| `contract_proof` | Schema, contract, store, resolver, parser, or fail-closed behavior is proven without live external runtime | Must not claim live provider, live MemoryOS, peer-GOD, or server truth |
| `local_runtime_proof` | Local production path ran with local artifacts and deterministic runtime evidence | Must not claim server-side truth or live external service proof |
| `opt_in_live_proof` | Explicitly configured live service/provider produced evidence with trace/artifact ids | Must not claim GitHub merge/review truth unless server API proves it |
| `server_side_truth` | GitHub or other server authority confirms checks, reviews, merge, or equivalent server state | Must not infer from local git, local tests, or CI alone |
| `manual_gap` | Required proof is unavailable, unresolved, or intentionally not exercised | Must not be deleted or downgraded without new proof |

Proof levels are monotonic and source-bound. They may move only when a new
upstream authority exists:

```text
manual_gap -> contract_proof -> local_runtime_proof -> opt_in_live_proof -> server_side_truth
```

Do not upgrade proof because local tests pass, CI passes, a worker says the work
is done, or a release/TUI surface looks complete. If the stronger producer,
live trace, or server API proof does not exist, keep the lower proof level and
preserve the gap.

`forbidden_claims` are append-only guardrails. A downstream artifact must carry
forward inherited forbidden claims unless a matching upstream live/server proof
explicitly removes the claim. Never delete `ready_to_merge`, `pr_merged`,
`github_review_truth`, `live_memoryos`, `worker_output_is_review_truth`, or
similar boundaries just to make an evidence pack look more complete.

## Artifact Ref And Owner-Lineage Rules

Every new production artifact or status condition that participates in closure
must be machine-readable and lane/graph scoped. It must include stable refs
instead of summary-only prose.

Required where applicable:

- `source_refs`: upstream artifacts, events, traces, or server objects consumed;
- `target_refs`: lane, graph, review, release, or room objects affected;
- `owner_lineage`: authority owner, allowed writer, and producer path;
- `candidate_refs`: execution candidate artifacts offered for review;
- `cited_candidate_refs`: candidate refs consumed by an independent verdict;
- `forbidden_claims`: inherited and newly relevant forbidden claims;
- `manual_gaps`: missing proof that must remain visible.

Prefer stable scoped refs such as:

```text
lane:{lane_id}
internal_review:{review_id}
god-room-review-closure:{graph_id}:{failed_lane_id}:{terminal_lane_id}
```

Opaque strings, human-only summaries, unscoped filenames, terminal panes,
provider sessions, and TUI row ids are not closure refs. If the owner lineage is
unclear, the artifact is candidate evidence or `manual_gap`, not truth.

## Required Goal Phases

Every long `/goal` must follow these phases.

### Phase 0 - Truth Refresh

Before coding, inspect:

- `git status -sb`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git log --oneline -5`
- PR state if available
- CI state if available
- current `docs/xmuse/production-closure-gap-ledger.md`
- existing docs/contracts/tests for the target layer

Working notes and final report must include:

```yaml
current_head: 0123456789abcdef0123456789abcdef01234567
target_branch: vision-closure-deliberation-tui
target_layers: ["L2"]
known_blockers: ["L2 binding is not yet durable authority"]
manual_gaps: ["L4 live provider invocation proof remains unavailable"]
forbidden_claims: ["peer_god_live_proof", "provider_invocation_live_proof"]
```

### Phase 1 - Layer Targeting

Do not attempt to close L1-L11 in one goal. Choose a bounded target and keep
downstream work honest.

Use wave-first closure order. Do not spend equal effort across L1-L11; advance
the earliest wave whose upstream proof is strong enough and whose next slice
materially increases production closure.

| Wave | Layers | Purpose |
|---|---|---|
| A | L1-L2 | Authority root: who may write truth; who is a GOD; who is only a provider/worker |
| B | L3-L5 | GOD room speech runtime: selected GOD -> provider invocation -> durable event -> replay |
| C | L6-L7 | Deliberation-to-execution authority: room events -> blueprint freeze -> authoritative laneDAG |
| D | L8-L9 | Execution safety: runner/recovery enforcement -> review truth -> patch-forward lineage |
| E | L10-L11 | Aggregation/operator surface: MemoryOS/GitHub truth -> TUI/cockpit/overnight soak |

L11 is a terminal integration layer. It must not be used to justify upstream
shortcuts. Provider invocation controls belong in L11 only after L2-L5 are
honestly closed or explicitly displayed as `manual_gap` / `contract_proof`.

Current wave cursor must be re-evaluated from the ledger at the start of every
goal. As of the L8 runner recovery proof slice, Wave A has contract proof,
Wave B has bounded/opt-in provider speech proof, Wave C carries lineage through
freeze/laneDAG/status contracts, and Wave D is the active production focus. The
default next target is L9 review/release lineage that consumes L8 recovery
proof without upgrading worker output, local tests, or recovery artifacts into
review/server truth.

Use `docs/xmuse/production-closure-wave-map.md` as the implementation map for
per-layer next slices, Codex/OpenCode division of labor, acceptance proof, and
forbidden claims. This contract defines behavior; the wave map guides execution.

## Wave Closure Rules

### Wave A - L1-L2 Authority Root

Goal:

- Close who can write truth, which store owns it, which actor is a GOD, and
  which actor is only a provider or worker.

Minimal next slices:

- L1: `xmuse.authority_boundary_audit.v1` inventory for mutating paths:
  `path_id`, component, `mutates_state`, `writes_to`,
  `reads_from_projection`, `projection_used_as_authority`, decision, reason,
  and source files.
- L2: `xmuse.selected_god_binding_resolution.v1` proving
  `RoomSelectedGodBinding` is consumed by L3 authorship and L4 invocation
  attempts.

OpenCode may produce candidate inventories, grep reports, serializer/test
boilerplate, and migration lists. Codex must decide authority classification,
peer-GOD status, and proof level.

Acceptance:

- Every audited mutating path has an owner and decision.
- Projection-as-authority is marked `manual_gap` or `refactor_required`.
- Provider inventory never becomes GOD identity.
- Missing account/model/CLI/proof config fails closed.

Forbidden claims:

- Do not claim all runtime status authority is fully centralized.
- Do not claim OpenCode or any CLI is peer-GOD because it appears in inventory.

### Wave B - L3-L5 GOD Room Speech Runtime

Goal:

- Close the chain selected GOD -> L4 provider invocation artifact -> L5 durable
  room event capture -> L3 replay proof.

Minimal next slices:

- L3: authored event binding proof that every room event carries actor,
  binding/source, and proof-level classification.
- L4: `xmuse.god_room_provider_speech_response.v1` from selected binding,
  with command/model/variant, prompt/output refs, timing, exit status, and
  fail-closed outcomes.
- L5: L4 artifact -> durable event capture -> replay proof with digest and
  lineage checks.

OpenCode may build subprocess wrappers, stdout/stderr/raw-archive helpers,
negative tests, replay lookup helpers, and schema propagation. Codex must decide
invocation/capture proof semantics and prevent proof inflation.

Acceptance:

- Provider-backed events require L4/L5 lineage.
- Imported fixtures remain `contract_proof`.
- L4 artifacts do not directly write durable room events.
- L5 capture cannot be described as fresh L4 invocation proof.

Forbidden claims:

- Do not claim natural peer-GOD groupchat closure.
- Do not claim live provider invocation from capture-only evidence.

### Wave C - L6-L7 Deliberation-To-Execution Authority

Goal:

- Close durable room event lineage -> blueprint freeze -> laneDAG/graph-set
  authority.

Minimal next slices:

- L6: freeze proof classifier so fixture freezes, provider-backed freezes, and
  future natural multi-GOD freezes are separated.
- L7: lane authority consumption proof that dispatch/review consumes laneDAG,
  graph-set, and lane runtime contract instead of projection state.

OpenCode may find fixture freeze call sites, `feature_lanes.json` reads/writes,
dispatch/review entry points, and mechanical schema propagation. Codex must
decide whether a path is authoritative or only compatibility/projection.

Acceptance:

- Freeze artifacts include source-event lineage, assumptions, blockers,
  rejected alternatives, and source refs.
- Fixture-only freeze is `contract_proof`.
- `feature_lanes.json` remains projection.
- Detached laneDAG artifacts do not become execution authority alone.

Forbidden claims:

- Do not claim natural deliberation closure from clean fixtures.
- Do not claim full blueprint-to-execution authority until dispatch/review
  consume the authoritative lane contract.

### Wave D - L8-L9 Execution Safety

Goal:

- Close recovery enforcement, review truth, independent verdicts, and
  patch-forward lineage.

Minimal next slices:

- L8: recovery enforcement path matrix for runner candidate selection,
  orchestrator dispatch, review intake, patch-forward scheduling, and
  supervisor loop. Each path must prove blocked lanes cannot proceed, retry
  budgets are respected, `refactor_required` blocks same-path patching, and
  `manual_gap` is preserved.
- L9: validated execution candidate and review truth chain: L6 freeze -> L7
  lane contract -> L8 recovery decision -> lane-scoped execution candidate ->
  independent review verdict citing that candidate -> accepted/reworked/rejected
  state -> patch-forward lineage -> bounded L10 handoff/replay evidence link.

OpenCode may execute bounded low-intelligence lanes, generate candidate patches,
produce candidate test/report artifacts, and run read-only reviews. Codex is
the review owner and final verdict authority.

Acceptance:

- Every execution path reads durable recovery artifacts where required.
- Worker output is candidate evidence only.
- Review truth requires the same lane to have both a validated execution
  candidate and an independent review verdict that cites it.
- Patch-forward artifacts and release evidence cite the lane/recovery/review
  lineage.
- Local tests are not review truth.

Forbidden claims:

- Do not claim overnight-safe recovery from local runner proof.
- Do not claim end-to-end execution/review closure until one GOD-room-originated
  lane is proven through execution, review, patch-forward, and release evidence.
- Do not treat recovery artifacts, worker output, local tests, or candidate
  artifacts alone as review truth.

### Wave E - L10-L11 Aggregation And Operator Surface

Goal:

- Aggregate only upstream proof, then expose it through cockpit/overnight
  surfaces without inventing truth.

Minimal next slices:

- L10: honest replay bundle refresh containing provider speech or manual gap,
  freeze, laneDAG, execution/review, MemoryOS trace or governed plan gap,
  GitHub CI truth, GitHub review truth or blocker, and merge truth or blocker.
- L11: native CLI bridge contract only: selected L2 binding starts real CLI,
  raw terminal output is archived, operator input gets source refs, L4/L5
  lineage is required before durable speech is claimed, and pane registry
  remains projection.

OpenCode may draft evidence schemas, GitHub truth JSON shape, trace mapping,
clowder-ai reference summaries, raw archive helpers, and read-only TUI viewers.
Codex must decide readiness, merge truth, MemoryOS live proof, and authority
classification.

Acceptance:

- Release evidence only aggregates upstream artifacts.
- MemoryOS plan is not live MemoryOS trace.
- CI success is not review/merge truth.
- Draft/open/unmerged PR state preserves no `pr_merged`.
- Raw terminal output does not become durable GOD speech without L4/L5 lineage.

Forbidden claims:

- Do not claim `ready_to_merge`, `pr_merged`, live MemoryOS, complete cockpit,
  or overnight readiness without matching live/server proof.

### Phase 2 - Authority Design

Before implementation, write an authority table for each target layer:

```text
Layer:
Authority owner:
Allowed writers:
Allowed readers:
Projection surfaces:
Forbidden authorities:
Failure mode:
Proof required:
```

Example:

```text
Layer: L2 GOD Identity / Provider Binding
Authority owner: ProviderAccount, GodProfile, RoomSelectedGodBinding
Allowed writers: explicit registry/operator contract only
Allowed readers: L3 authorship resolver, L4 provider invocation resolver, read models
Projection surfaces: provider board, TUI selection view
Forbidden authorities: provider inventory, env scan, TUI temporary selection, raw CLI string
Failure mode: unresolved account/model/CLI -> manual_gap or refactor_required
Proof required: durable binding consumed by L3 authorship and L4 invocation
```

### Phase 3 - Production Slice Implementation

The minimum production slice is:

- schema / dataclass / contract
- store or authority resolver
- API/operator action or runtime hook
- fail-closed path
- evidence artifact
- docs/ledger update

If the slice is a reconcile-style closure, also include:

- explicit desired condition;
- observed status condition;
- idempotent producer/consumer behavior;
- stable source/target refs;
- owner lineage and inherited forbidden claims.

Insufficient slices:

- test fixture only
- mock-only behavior
- documentation-only closure claim
- TUI-only panel
- release pack field without upstream artifact

Repeatedly failing or demo-grade paths should be directly refactored or
replaced at the failed boundary instead of patched again.

Trigger `refactor_required` instead of more patching when:

- the same failure class recurs on the same feature/stage/test cluster;
- schema parsing or proof classification is copied into three or more places;
- condition branches are added only to route around a missing authority owner;
- tests must mock recovery enforcement, review truth, GitHub truth, or
  MemoryOS truth to make the path pass;
- a downstream surface needs new truth fields but no upstream producer exists.

### Phase 4 - Targeted Tests

Tests come after the authority/proof path is understood. Use the smallest tests
that prove the implemented slice.

Expected test types:

- contract tests for schema and fail-closed behavior
- runtime tests proving real path consumes authority objects
- negative tests proving bad inputs become `manual_gap` or `refactor_required`
- projection tests proving TUI/read models do not claim authority
- regression tests protecting previous evidence semantics

Forbidden test patterns:

- Future-behavior tests for production paths that do not exist yet.
- Fake shims that make imagined architecture green.
- Snapshot-heavy UI tests that do not protect authority/proof boundaries.
- Mocks that bypass selected GOD binding, provider invocation, recovery
  enforcement, or review truth.
- Tests that construct final release packs directly instead of passing through
  upstream artifacts.

### Phase 5 - Evidence Export

Every production slice must produce an evidence summary:

```json
{
  "target_layers": ["L2"],
  "proof_level": "contract_proof",
  "conditions": {
    "desired": ["ValidatedExecutionCandidatePresent"],
    "observed": ["ServerTruthPending"]
  },
  "authority_objects": ["ProviderAccount", "GodProfile", "RoomSelectedGodBinding"],
  "source_refs": ["lane:example-lane"],
  "target_refs": ["god-room-review-closure:example:failed:terminal"],
  "owner_lineage": {
    "authority_owner": "FeatureGraphStatusStore",
    "allowed_writer": "orchestrator_reconcile"
  },
  "runtime_path_touched": true,
  "projection_only": false,
  "manual_gaps": [],
  "forbidden_claims": [
    "peer_god_live_proof",
    "natural_groupchat_closure",
    "provider_invocation_live_proof"
  ],
  "validation": [
    "uv run pytest tests/xmuse/test_example.py -q",
    "uv run ruff check ."
  ]
}
```

### Phase 6 - Self-Review / Anti-False-Closure Audit

The final review must be independent of the implementation path. Use read-only
reviewer/explorer subagents for substantial work when useful, but Codex remains
the final writer and verifier.

Review questions:

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

### Phase 7 - Ledger Update And Claim Boundary

Update `docs/xmuse/production-closure-gap-ledger.md` after every production-slice
commit that changes a layer. Keep claims tied to current branch/head/PR/CI
facts. Preserve `manual_gap` whenever live/server proof is missing. Do not
downgrade evidence boundaries to make a layer look complete.

Final report must state:

- behavior changed
- target layers and proof level
- tests/checks run
- evidence artifacts or manual gaps
- claims still forbidden
- remaining blockers

## Goal Types

### Goal A - L1-L2 Authority Root

Target:

- Authority and GOD/provider binding root.

Completion definition:

- Mutating TUI/API/runner paths use approved contracts/stores.
- `ProviderAccount`, `GodProfile`, and `RoomSelectedGodBinding` are durable
  authority.
- Provider inventory/env scan/TUI selection cannot directly become speaker
  truth.
- Unresolved account/model/CLI/proof config fails closed.

Anti-abuse rule:

- Do not stop at dataclass tests. Prove L3/L4 resolvers consume the binding.

### Goal B - L3-L5 Provider-Backed Room Speech

Target:

- Selected GOD -> provider invocation artifact -> durable `speak` event.

Completion definition:

- L4 emits `xmuse.god_room_provider_speech_response.v1`.
- Artifact includes actor identity, command/model/variant, prompt refs, output
  refs, timing, exit status, and proof level.
- L5 accepts only server-loaded artifact evidence.
- Request-body-only/direct response stays `manual_gap`.
- Replay proves `speak_event_id` exists and matches lineage.

Anti-abuse rule:

- Do not treat imported fixtures as live invocation. Do not describe L5 capture
  proof as L4 invocation proof.

### Goal C - L6-L7 Blueprint Freeze And LaneDAG Authority

Target:

- Durable deliberation -> frozen blueprint -> authoritative laneDAG.

Completion definition:

- Freeze artifact preserves assumptions, blockers, rejected alternatives, source
  refs, and decision lineage.
- Fixture-only freeze is marked `contract_proof`.
- LaneDAG source is a frozen blueprint.
- Dispatch/review consume authoritative lane runtime contract.
- `feature_lanes.json` remains projection only.

Anti-abuse rule:

- A clean freeze fixture is not natural deliberation closure. A detached laneDAG
  artifact is not execution authority.

### Goal D - L8-L9 Execution / Recovery / Review

Target:

- Lane execution, recovery, independent review, and patch-forward lineage.

Completion definition:

- Runner/supervisor/dispatch/review consume L7 lane authority.
- Repeated failure or demo-grade path enters `refactor_required`.
- Retry budget exhaustion suspends or creates `manual_gap`.
- Worker output is candidate evidence only.
- Independent review decides accepted, reworked, or rejected.
- Patch-forward lineage enters release evidence input.

Anti-abuse rule:

- Do not only test a recovery classifier. Prove runner/supervisor cannot bypass
  recovery decisions. Local tests or worker self-report are not review truth.

### Goal E - L10-L11 Aggregation / Operator Surface

Target:

- Aggregate evidence without inventing server truth, then expose it through
  cockpit/overnight surfaces without bypassing upstream proof.

Completion definition:

- Release evidence pack aggregates upstream artifacts only.
- Live MemoryOS is claimed only when configured service returns trace id.
- GitHub review, checks, and merge truth are separate.
- `pr_merged` comes only from server-side merge proof.
- `ready_for_replay` is not `ready_to_merge`.
- `NativeCliSessionBridge` starts real selected CLI from L2 binding.
- `MachineEventBridge` emits L4 artifact or downgrades to `raw_archive_only`.
- `GodRoomProjectionBridge` projects only L3/L5 durable speech.
- Native pane registry is projection, not authority.
- Operator input records source refs.
- Overnight run has budget ledger, recovery decisions, replay bundle, review
  evidence, and honest blockers.

Anti-abuse rule:

- Do not set release decision to ready through tests and call it merge
  readiness. Do not treat MemoryOS plan artifact as live trace. Do not first
  expand TUI panels. Raw terminal output, pane registry state, and provider
  process session are not durable GOD room speech.

## TDD Abuse Detector

Canonical anti-TDD rules live in `docs/xmuse/anti-tdd-abuse-policy.md`. This
section is the short operational detector used during `/goal` self-review.

A goal is TDD-abusive if any are true:

1. More than one-third of changed files are tests before production authority is
   identified.
2. New tests assert closure states not backed by implemented production path.
3. Tests construct artifacts that should be produced by runtime.
4. Tests mock away selected GOD binding, provider invocation, recovery
   enforcement, or review truth.
5. Final report says "passed tests" where it should say "contract proof only".
6. Implementation adds fields to evidence packs without upstream producers.
7. Implementation expands TUI/read models without fail-closed authority checks.

If detected:

- Stop adding tests.
- Write a layer authority note.
- Identify the missing production producer.
- Treat the issue as a goal-wide process failure, not as a local test cleanup.
- Convert speculative tests into manual-gap documentation or remove them.
- Implement the smallest real producer/consumer path.
- Add targeted regression tests after that path exists.

## Autonomy Boundaries

Codex may autonomously:

- Find real gaps near the target layer.
- Split a large target into patch-forward lanes.
- Close an upstream blocker first.
- Create `refactor_required` instead of continuing patch stacking.
- Spawn read-only explorer/reviewer subagents.
- Update ledger `manual_gap` records.

Codex must not autonomously:

- Change L1-L11 dependency order.
- Treat downstream projection as upstream proof.
- Upgrade a worker/CLI to peer-GOD.
- Rewrite `proof_level` to make release packs ready.
- Delete `manual_gap` without new live/server proof.
- Use more tests as a substitute for a production runtime path.
