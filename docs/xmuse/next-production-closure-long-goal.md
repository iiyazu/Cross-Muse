# Next Production Closure Long Goal

更新日期: 2026-06-15

本文固化下一轮长 `/goal` 的任务边界。行为规范以
`docs/xmuse/goal-behavior-contract.md` 为准；实时 proof 状态以
`docs/xmuse/production-closure-gap-ledger.md` 为准；Wave 顺序以
`docs/xmuse/production-closure-wave-map.md` 为准。

本轮按 reconcile 纪律执行：`/goal` 只描述 desired state，durable
artifacts/status/server API 才是 observed state。每个切片必须声明 target
condition、authority owner、stable source/target refs、owner lineage、proof
level、manual gaps 和 inherited `forbidden_claims`。缺 artifact/schema/owner
时 fail closed；重复失败或 proof 解析复制扩散时触发 `refactor_required`，不得继续
patch stacking。

## Goal

推进下一轮生产闭环长目标，采用中等粒度任务在 goal 中自主划分，但不得改变依赖顺序。

当前目标不是继续扩 TUI/cockpit，也不是做 release readiness 宣称；目标是把 Wave D / L9
推进到一条诚实的执行/审查/patch-forward/release-evidence lineage：

```text
L6 freeze
-> L7 lane contract
-> L8 recovery proof/decision
-> local execution candidate
-> independent review verdict
-> accepted / reworked / rejected state
-> patch-forward lineage
-> L10 release evidence handoff
```

只有当 L9 lineage 已经由真实合同、store、artifact 和 fail-closed gate 支撑时，才允许
做一个小的 Wave E / L10 aggregation slice。L11 cockpit/overnight 不在本轮主目标内，
除非只是展示 `manual_gap` 或 `contract_proof`。

Current cursor:

- L9 review intake/closure can consume a validator-passing candidate generated
  through a bounded platform-runner dispatch loop and emit
  `xmuse.god_room_lane_review_chain_proof.v1` on the graph-status-gated API
  path. `xmuse.local_execution_candidate.v1` now distinguishes
  `producer=platform_runner_dispatch` from `producer=manual_cli_capture`; only
  platform-runner-dispatch candidates can make the bounded L9 session ready.
  Manual CLI captures remain generic candidate evidence and must not be
  described as runner-session proof.
- The chain proof can also be regenerated through a separate second-step API
  that reloads the durable review closure artifact and now exposes bounded
  `local_execution_review_session` detail. That detail now re-loads and
  validates the closure's patch-forward, failed-lane patch-forward verdict,
  patch-lane intake, and patch-lane verdict artifacts, including semantic
  cross-links between intake execution refs, terminal verdict evidence refs,
  closure-selected candidate refs, and the patch-forward source verdict. It
  also validates the patch-forward laneDAG link and patch-lane runtime contract
  for failed lane, patch lane, verdict/evidence refs, dependency refs, required
  checks, and patch output refs. The bounded session evidence also records the
  patch-forward artifact's source gaps/forbidden claims and explicitly
  separates source gaps resolved by validated patch-lane candidate/intake/verdict
  evidence from retained gaps such as `release_evidence_not_linked`. It also
  checks terminal reviewer independence by comparing the patch-lane verdict
  `reviewer_id` with cited local execution candidate `worker_id`s; self-review
  or missing reviewer identity keeps the chain proof `manual_gap`. It also now
  validates the patch-lane review-intake graph-status boundary: intake
  `source_authority` must include `feature_graph_status_store` and
  `lane_dag_artifact`, intake `source_event_lineage` must be non-empty, and the
  embedded feature graph status must remain `reviewing` with matching lineage.
  It also cross-checks cited local execution candidate graph-status lineage
  against that review-intake feature graph status snapshot, so a candidate that
  is valid in isolation but carries detached graph-set/feature-graph/status or
  source-event lineage keeps the chain proof `manual_gap`.
  It now also reconciles review-closure `cited_candidate_artifact_refs` against
  actually resolved valid local execution candidate lineage artifact refs, and
  the shared L9/L10 handoff gate rejects unresolved or undeclared candidate
  artifacts before release-evidence source-ref aggregation.
  It also validates review-closure embedded
  `cited_candidate_artifact_lineage` against freshly resolved candidate lineage,
  so stale or forged embedded lineage keeps the handoff at `manual_gap`.
  L10 MemoryOS candidate and runtime-closure consumers now also reject a
  `chain_ready` review-chain proof unless it carries a verified bounded
  `local_execution_review_session`, validated session artifacts, verified
  graph/candidate/reviewer boundaries, and candidate refs that match handoff
  and lineage refs.
  The bounded session also now requires a verified
  `runner_recovery_lineage_boundary`: missing L8 recovery proof lineage,
  unreadable recovery proof artifact refs, missing or unreadable durable source
  refs, missing failed-lane target refs, or missing review/server/overnight
  proof gaps keeps the chain proof `manual_gap`.
  It also now carries `xmuse.local_execution_review_session.v1` plus
  `xmuse.local_execution_review_session_scope_boundary.v1`, binding graph,
  failed lane, patch lane, producer-verified runner-emitted local execution
  candidate refs, L8 recovery refs, review intake/verdict refs, patch-forward
  refs, and session source refs. L10 candidate/replay consumers reject
  `chain_ready` artifacts whose bounded session lacks session artifact/source
  refs or whose candidate producers are not `platform_runner_dispatch`.
  It now also carries `xmuse.graph_wide_lane_accounting_boundary.v1`, which
  loads the graph-set artifact and `FeatureGraphStatusStore`, checks expected
  feature-graph status records, rejects ready/active/blocked residue, and
  requires completed lanes to be covered by validated platform-runner candidate
  lineage. Missing graph-set/status authority or uncovered completed lanes keep
  the chain proof and L10 bounded-session gate at `manual_gap`.
  It now also carries `xmuse.runner_session_boundary.v1`: platform runner emits
  `xmuse.runner_session.v1` under `work/runner_sessions/`, each
  platform-runner candidate cites `runner_session_id` and `runner_session_ref`,
  and the chain proof reloads the session artifact to verify completed session
  status, candidate refs, run id, runner id, and graph scope. Missing,
  incomplete, empty-candidate, mismatched, or proof-inflated runner-session
  artifacts fail closed. This is local runner session-boundary proof only.
  The shared direct review-closure handoff gate used by L9 and L10 also reloads
  each platform-runner candidate's runner-session artifact before allowing
  direct L10 source-ref aggregation, and GOD-room runtime closure evidence now
  re-derives that same gate for direct `god_room_review_closure` inputs before
  seeding review-closure source refs. The older review-closure path cannot
  bypass bounded runner-session authority or stale/missing candidate artifacts.
  Runner-session artifacts now also record worker-evidence bundle refs produced
  by the same platform-runner invocation, and the L9 review-chain
  runner-session boundary checks those refs against candidate
  `feature_evidence_bundle:*` source refs. Candidate/bundle/session mismatch
  keeps the chain proof `manual_gap`; this is L9 artifact-splicing hardening,
  not live review truth.
  Missing, mismatched, non-merge/non-patch-forward, invalid link/contract,
  reviewer identity conflict, uncovered graph-wide lane accounting, invalid
  runner-session boundary, or proof-inflated session refs fail closed. This
  remains bounded local runner/API handoff proof at
  `contract_proof` / `not_server_truth`; the next slice is to use the
  runner-session boundary plus graph-wide accounting to drive broader live
  runner/review evidence without claiming broad live worker execution/review or
  server truth.
- L10 release evidence candidates can consume the API-generated review-chain
  artifact only as source-ref aggregation while preserving
  `candidate_report_is_not_live_memoryos_proof`, and only after the bounded
  local execution/review session consumer gate passes.
- Release evidence pack replay can index the same artifact only as
  `contract_proof` / `not_server_truth` GOD-room runtime closure aggregation;
  missing GitHub/server truth keeps the replay section `manual_gap`.
- L8 platform-runner candidate selection now uses an explicit xmuse root for
  durable recovery-artifact lookup rather than relying on an orchestrator
  private `_root` attribute. This removes a silent runner-candidate recovery
  bypass and keeps projection lane recovery lookup on stable `lane_local_id`
  without changing dispatch identity. It remains local recovery authority
  hardening, not overnight-safe proof.
- L8 stale-dispatch repair now writes a durable `lane_recovery_artifact` only
  after the worker-loss CAS transition succeeds, records the artifact ref back
  to lane metadata, and proves the next runner candidate-selection pass consumes
  that artifact as a non-retry recovery block. Graph-bound pidless dispatched
  lanes now produce `dispatch_no_worker_pid` recovery artifacts on the same
  CAS-guarded path. This prevents same-path stale worker and graph-bound
  pidless-dispatch redispatch loops at local runtime/contract boundary only; it
  is not live long-running supervisor or overnight-safe proof.
- L8 orchestrator gate failure now writes a durable `lane_recovery_artifact`
  after an `executed -> gate_failed` transition. It uses the lane budget and
  gate failure evidence with `evaluate_lane_recovery`, so first gate failures
  can remain retry-allowed while repeated gate failures become
  `refactor_required`. This is local contract authority production only, not
  review truth, server truth, live long-running runner proof, or overnight-safe
  recovery.
- L8 review patch-forward now writes a durable `lane_recovery_artifact` for the
  original failed lane after the patch-forward verdict appends the patch lane.
  The artifact carries review verdict/evidence refs, gate report, budget refs,
  and patch-lane lineage, records a non-retry `suspended` recovery decision,
  and is consumed by the existing dispatch recovery gate if the original lane
  tries to re-enter the same path. This is local contract authority production
  only; it does not prove patch-lane execution/review, review truth, server
  truth, or release readiness.
- L8 review rejection retry exhaustion now writes a durable
  `lane_recovery_artifact` for the failed original lane with
  `source_authority=platform_orchestrator_review_rejection` and
  `decision=refactor_required`. The same dispatch recovery gate blocks the
  original lane from re-entering the same path. This is local contract recovery
  authority only; it does not create independent review truth, broad live runner
  proof, server truth, or release readiness.
- L8 merge failure after review now writes durable recovery artifacts for
  graph-bound lanes. Reworkable merge conflicts record retry-allowed recovery
  evidence before redispatch, retry exhaustion records `refactor_required`, and
  non-reworkable merge failures record non-retry `suspended` recovery evidence.
  This is local contract recovery authority only; it does not create GitHub
  merge truth, independent review truth, server truth, or release readiness.
- L8 review retry exhaustion in reconcile now writes durable recovery artifacts:
  exhausted `review_timeout`/`review_no_verdict` records
  `refactor_required`, and exhausted `review_infra_unavailable` records a
  non-retry `suspended` decision while active backoff remains non-terminal.
  The same dispatch recovery gate blocks same-path redispatch of the exhausted
  lane. This is local contract recovery authority only; it does not create
  independent review truth, broad live runner proof, server truth, or
  overnight-safe recovery.
- L8 retry-eligible first/early review failures now write durable
  `lane_recovery_artifact` records during `reconcile_status_changes` before the
  lane is moved back to `gated`. These artifacts use
  `source_authority=platform_orchestrator_review_retry`, carry a retry-allowed
  `retry` recovery decision, preserve `manual_gap` when graph/lane authority is
  missing, and remain non-blocking for the dispatch recovery gate. This is
  local contract recovery authority only; it does not create independent review
  truth, broad live runner proof, server truth, or overnight-safe recovery.
- L8 overnight supervisor stage start now runs a durable recovery preflight gate
  over runtime `lane_graphs/*.recovery.json` artifacts. Non-retry recovery
  decisions such as `refactor_required`, or invalid recovery artifacts, write
  blocked supervisor evidence and prevent the stage from starting while
  preserving `manual_gap` and forbidden claims. This closes the supervisor
  preflight bypass at contract boundary only; it is not overnight-safe proof.
- L9 runner-session boundary now preserves dispatch task failures as
  `session_failed` / `manual_gap` instead of allowing failed in-flight dispatch
  tasks to be overreported as completed local runtime proof. Downstream bounded
  session consumers still require a completed session with real candidate refs.
- L9 runner-session boundary also preserves local execution candidate capture
  failures after dispatch as `session_failed` / `manual_gap`, so a dispatched
  lane without a captured `xmuse.local_execution_candidate.v1` artifact cannot
  satisfy bounded-session readiness.
- L9 runner-session boundary keeps completed sessions with no candidate
  artifact refs at `manual_gap`; `session_completed` alone is not local
  execution proof.
- L9 platform-runner candidate capture now fail-closes candidates whose
  graph-native status lineage has not reached `reviewing`. READY/RUNNING
  dispatch-return artifacts are written as `manual_gap` with
  `graph_native_worker_evidence_not_submitted` and are not counted as runner
  session local-runtime candidate refs. Platform runner now has a bounded
  graph-native worker-evidence producer handoff that can scope the READY claim
  to the dispatched lane, persist a `FeatureEvidenceBundle`, and advance
  `FeatureGraphStatusStore` to REVIEWING before candidate capture, but only
  when provider binding, planning-run, blueprint, acceptance, and required-check
  prerequisites are present. Missing prerequisites preserve the `manual_gap`.
  This does not make worker output review truth or server truth.
- L9 review-intake auto-discovery now consumes that worker-evidence producer
  handoff. A `platform_runner_dispatch` local execution candidate is
  auto-added as reviewer input only when its current graph-status lineage still
  matches `FeatureGraphStatusStore` and a matching `FeatureGraphArtifactStore`
  `FeatureEvidenceBundle` for the same runner session/provider binding/
  completed lane exists and is cited by the candidate source refs. Missing or
  stale bundle lineage keeps the intake at `worker_candidate_evidence_missing`.
  Review verdicts now fail closed unless discovered bundle refs are explicitly
  cited, patch-forward artifacts carry the source verdict bundle citation, and
  the bounded review-chain session gate requires
  `xmuse.worker_evidence_bundle_citation_boundary.v1`. Patch-forward lanes now
  have independent graph-set/status authority and can produce a patch-lane
  graph-native worker-evidence bundle through the existing platform-runner
  producer path; verdicts and chain proof must cite that bundle. The terminal
  patch-lane verdict bundle refs now flow into the review-chain citation
  boundary, and L10 can carry those verified bundle refs as source refs in
  MemoryOS candidate hints, runtime closure replay refs, and release-linkage
  refs. This remains contract/API handoff and aggregation proof only, not broad
  live execution/review or server truth.
- L9/L10 review-chain source-ref aggregation now also carries gate-ready
  review-closure `source_event_lineage` refs through the shared handoff path.
  MemoryOS candidate hints, runtime closure replay refs, and review-chain
  release-linkage refs can include `god-room-event:*` and
  `provider_response_artifact:*` as provenance only. This does not create live
  MemoryOS, independent review truth, GitHub truth, merge truth, or production
  release readiness.
- L10 review-chain release-linkage source refs are emitted only after the
  review-chain proof is actually linked through runtime-closure replay source
  refs, bounded session gate, and current review-closure handoff. A manual-gap
  linkage must not copy unrelated GOD-room/provider refs from the same replay
  section.
- L10 MemoryOS candidate reports revalidate runtime-closure artifacts that
  carry review-closure or review-chain lineage before using their `source_refs`
  as MemoryOS payload hints. Provider-only runtime replay refs remain candidate
  hints, but stale review candidate/session lineage must keep the runtime
  closure candidate not-ready.
- L9/L10 direct review-closure handoff now rejects missing, invalid,
  mismatched, empty-candidate, stale candidate, or proof-inflated
  runner-session artifacts before L10 MemoryOS/runtime-closure source refs can
  be seeded from that closure.
- L10 release evidence pack treats a supplied GOD-room review-closure artifact
  without a matching review-chain proof as an expected L9 handoff gap. Runtime
  closure replay records `review_chain_proof.status=manual_gap`,
  `expected=true`, and `god_room_review_chain_proof_artifact_missing` instead
  of silently omitting the missing chain proof. Legacy packs without GOD-room
  review-closure input remain unaffected. This is aggregation gap visibility
  only; it does not create release linkage, review truth, server truth,
  MemoryOS live proof, or pack readiness.

## Autonomous Task Slices

Codex 应在 goal 内自主划分中等粒度任务，建议从以下 slices 开始，并根据代码事实调整：

1. **Truth refresh and path inventory**
   - 刷新 git、PR、CI、ledger、当前 contracts/tests。
   - 梳理 local execution、review intake/verdict、patch-forward、review closure、
     release evidence handoff 的真实路径。

2. **L9 production chain**
   - 连接 graph-status-gated lane 到 local execution candidate、independent review
     verdict、patch-forward artifact 和 review closure。
   - local execution candidate 必须来自 graph-status-bound
     `xmuse.local_execution_candidate.v1` producer/validator，优先使用 platform
     runner 默认产物；`--local-execution-candidate-output-dir` 仅用于覆盖
     runtime evidence 目录。review intake 可以自动发现 conversation/lane/graph
     scope 均匹配且 `producer=platform_runner_dispatch` 的 validator-passing
     runner-emitted candidate 作为 reviewer input；该 candidate 的 graph-native
     status lineage 必须已经是 `reviewing`。不得再用任意 JSON 文件、
     manual CLI capture 或 opaque worker ref 冒充 runner-session candidate
     evidence。
   - review-chain proof 必须验证 review closure 的
     `graph_status_source_authority`、非空 `source_event_lineage`、以及 terminal
     feature graph status snapshot 与 closure lineage 一致；缺失或不一致时保持
     `manual_gap`，不能交给 L10 作为 ready handoff。
   - 使用已有 L6/L7/L8 lineage，不重造 parallel demo。

3. **Fail-closed gates**
   - 缺失或无效的 graph status、recovery decision/proof、candidate evidence、
     review verdict、patch-forward sidecar 或 release handoff 必须 fail closed。
   - repeated failure 或 demo-grade production path 进入 direct refactor，而不是继续叠
     patch/test。

4. **L10 aggregation, only after L9**
   - 只把 L9 lineage 作为 release evidence aggregation source ref。
   - review closure 必须包含至少一个 reviewer-cited、xmuse root 下可解析的
     `xmuse.local_execution_candidate.v1` artifact；只有 opaque worker ref 或
     invalid candidate artifact 时必须 fail closed。
   - 不把 release evidence、local tests、CI、worker report、recovery proof 升级为
     review/server/GitHub truth。

5. **Evidence and ledger**
   - 更新 `production-closure-gap-ledger.md` 中本轮真实改变的 claim。
   - 保留未证明的 `manual_gap` 和 forbidden claims。

6. **Independent review and validation**
   - 使用 OpenCode/DeepSeek 做 bounded inventory、candidate patch 或 read-only review。
   - Codex 独立审查所有 diff、proof level、runtime state、tests、ledger。

## Authority And Proof Rules

本轮默认 proof 边界：

- L8 recovery proof 可以作为 lineage/enforcement evidence。
- L9 independent review verdict 才能支撑 review chain claim。
- L10 release evidence 只能聚合 upstream artifacts。
- GitHub review/merge truth 必须来自 server-side truth。

禁止把以下内容当作 authority：

- worker output 或 OpenCode 自评；
- local tests；
- CI success；
- `feature_lanes.json`；
- TUI/dashboard/read model；
- release evidence pack；
- MemoryOS plan artifact；
- recovery artifact 本身。

## OpenCode Use

OpenCode 可直接修改工作树生成 candidate patch，但必须由 Codex 先限定 scope、
allowed files、acceptance gate 和 forbidden actions。

唯一允许调用形态：

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

适合交给 OpenCode：

- path inventory、grep、调用链表；
- schema/fixture/字段传播 candidate patch；
- low-intelligence local execution candidate；
- read-only false-closure review。

禁止交给 OpenCode：

- 最终 authority 判断；
- review truth 判断；
- proof-level 升级；
- GitHub/Merge/MemoryOS live truth 判断；
- commit、push、PR 更新。

## Acceptance

本轮完成时至少应满足：

- L9 chain 的一个中等粒度 production slice 已经由真实路径消费 upstream authority。
- fail-closed negative cases 覆盖本轮新增的 authority/proof boundary。
- L10 若被触碰，只做 aggregation，不生产 upstream truth。
- ledger 精确记录 proof level、manual gaps 和 forbidden claims。
- OpenCode 输出被当作 candidate，不被当作最终 truth。

## Forbidden Claims

除非本轮实际产生对应 live/server proof，否则不得声明：

- peer-GOD；
- natural groupchat closure；
- live MemoryOS trace；
- GitHub review truth；
- GitHub merge truth；
- `ready_to_merge`；
- `pr_merged`；
- overnight readiness；
- TUI/cockpit production closure。

## Validation

必须运行：

```bash
uv run pytest <focused tests> -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```

若改动 core/runtime package boundary，还必须运行：

```bash
uv run pytest tests/xmuse/test_package_boundaries.py -q
```
