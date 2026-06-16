# XMuse Production Closure Wave Map

更新日期: 2026-06-15

本文是长 `/goal` 的实施路线图。通用行为规范以
`docs/xmuse/goal-behavior-contract.md` 为准；实时状态和 proof 边界以
`docs/xmuse/production-closure-gap-ledger.md` 为准。本文只回答下一轮该沿着哪条
依赖链推进、Codex 与 OpenCode 各自能做什么、验收时不能过读什么。

当前判断:

- Wave A / L1-L2 已有 contract proof。除非发现 authority 漂移，不要重做。
- Wave B / L3-L5 已有 bounded/opt-in provider speech、capture、replay 证据。
- Wave C / L6-L7 已将 durable event lineage 带入 freeze、laneDAG、status 合同。
- Wave D / L8-L9 是当前焦点。L8 已有
  `xmuse.local_runner_recovery_proof.v1`，L9 已有
  graph-status-bound `xmuse.local_execution_candidate.v1` 默认 runtime
  producer/capture/validation，review intake 可自动发现 validator-passing
  runner-emitted candidate，review closure API 可在同一 graph-status-gated
  closure path 自动写出 `xmuse.god_room_lane_review_chain_proof.v1` handoff
  artifact；正向 API proof 现在使用 bounded platform-runner dispatch loop 产出
  local execution candidate，而不是手写成功 artifact。Candidate artifact 现在携带
  `producer`，只有 `platform_runner_dispatch` 能让 bounded L9 session ready；
  `manual_cli_capture` 仍可作为 generic candidate evidence，但不能证明 runner
  session。L10 candidate report 已有
  focused proof 能消费 API-generated review-chain artifact 作为 source-ref
  aggregation，且不升级为 review/server truth。review-chain proof 现在也可通过
  独立第二步 API 从已写盘 review closure 再生成，并携带 bounded local
  execution/review session detail；该 detail 现在会重新加载并验证 patch-forward、
  failed-lane patch-forward verdict、patch-lane intake、patch-lane verdict
  上游 artifacts，并校验 intake/verdict/candidate refs 的 session 语义
  cross-link；同时校验 patch-forward laneDAG link 和 patch-lane runtime
  contract 的 failed lane、patch lane、verdict/evidence refs、dependency、
  required checks、patch output refs；缺失/不匹配/overclaim 会降级为
  `manual_gap`。该 session evidence 现在也显式记录 patch-forward artifact
  的 source gaps/forbidden claims，并把 `patch_lane_not_executed`、
  `patch_lane_not_reviewed` 与下游 patch-lane candidate/intake/verdict 证据
  对应为 resolved gaps；`release_evidence_not_linked` 仍保留给 L10。它还会
  比较终端 patch-lane verdict 的 `reviewer_id` 与被引用 local execution
  candidate 的 `worker_id`，缺失 reviewer identity 或 reviewer/worker 相同都会
  降级为 `manual_gap`。这仍是 `contract_proof` / `not_server_truth`。
  L10 MemoryOS candidate 与 runtime-closure consumers 现在还会对
  `xmuse.god_room_lane_review_chain_proof.v1` 执行 bounded-session consumer
  gate：缺失 `local_execution_review_session`、session 未处于
  `bounded_session_ready`、session artifact validation 未通过、graph/candidate/
  reviewer boundaries 未 verified、或 session candidate refs 与 handoff/lineage
  refs 不一致时，chain proof 不能进入 source-ref aggregation。
  L9/L10 shared direct review-closure handoff gate 现在也会重新加载每个
  platform-runner candidate 引用的 runner-session artifact；缺失、不匹配、
  empty-candidate、stale candidate 或 proof-inflated session 不能通过旧
  review-closure 路径直接 seed L10 source refs。GOD-room runtime closure
  evidence 现在也会对 direct `god_room_review_closure` 输入重新派生同一
  handoff gate，未 gate-ready 时不把 review-closure source refs 注入聚合。
  Review-chain `chain_ready` 现在也要求 bounded session 的
  `runner_recovery_lineage_boundary` verified；缺少 L8 recovery proof lineage、
  recovery proof `artifact_ref` 不可读、recovery source refs 不可读，或
  recovery lineage 不指向 failed lane 时只能保持 `manual_gap`。
  bounded session 现在还带有
  `xmuse.local_execution_review_session_scope_boundary.v1`，把 graph、failed
  lane、patch lane、runner-emitted local execution candidate、L8 recovery
  artifact、review intake/verdict、patch-forward artifact 和 source refs 绑定
  成同一个 scope；platform runner 现在还会为每次 bounded invocation 写出
  `xmuse.runner_session.v1`，candidate artifacts 携带
  `runner_session_id`/`runner_session_ref`，review-chain proof 通过
  `xmuse.runner_session_boundary.v1` 重新加载并验证 session completed、run id、
  runner id、candidate refs 和 graph scope。Dispatch task failures now mark the
  runner session `session_failed` / `manual_gap` instead of allowing failed
  in-flight tasks to be overreported as completed local runtime proof. Local
  execution candidate capture failures after dispatch also keep the runner
  session `session_failed` / `manual_gap`, so dispatch success without a real
  candidate artifact cannot satisfy bounded-session readiness. Completed runner
  sessions with no candidate artifact refs also remain `manual_gap`, so an idle
  or empty bounded invocation cannot be overread as local execution proof.
  Runner-session artifacts now also carry worker-evidence bundle refs produced
  by the same platform-runner invocation, and the review-chain
  `runner_session_boundary` compares those refs with each candidate's
  `feature_evidence_bundle:*` source refs. A candidate that cites a bundle not
  recorded by its runner session keeps the chain proof at `manual_gap`, which
  narrows artifact-splicing risk without upgrading worker bundles to review
  truth. The runner-session artifact writer now uses same-directory temp-file
  replacement, runner shutdown logs session-finish capture failures without
  masking cleanup, and platform runner consumes the public recovery-dispatch
  helper instead of an underscore-prefixed orchestrator helper.
  Platform-runner candidate capture now also requires graph-native status
  lineage to be `reviewing`; READY/RUNNING dispatch-return artifacts become
  `manual_gap` with `graph_native_worker_evidence_not_submitted` and are not
  counted by the runner session as local runtime proof. Platform runner now has
  a bounded worker-evidence producer handoff that can advance a dispatched lane
  to REVIEWING through `FeatureEvidenceBundle` only when provider binding,
  planning-run, blueprint, acceptance, and required-check prerequisites are
  present; missing prerequisites preserve the `manual_gap`. The emitted
  candidate now cites the matching `feature_evidence_bundle:*` ref, and review
  intake auto-discovery consumes that producer handoff by checking the current
  `FeatureGraphStatusStore` record plus `FeatureGraphArtifactStore` bundle
  before adding the candidate as reviewer input. Missing or stale bundle
  lineage preserves `worker_candidate_evidence_missing`. Review verdicts now
  fail closed unless discovered bundle refs are explicitly cited, patch-forward
  artifacts carry the source verdict bundle citation, and the bounded
  review-chain session gate requires
  `xmuse.worker_evidence_bundle_citation_boundary.v1`. This is contract/API
  handoff proof only. Patch-forward lanes now get independent graph-set/status
  authority: the patch lane runtime contract uses the patch lane as its feature
  id, the patch-forward API adds a patch feature graph initialized to READY,
  and the existing platform-runner worker-evidence producer can advance that
  patch lane to REVIEWING and emit a matching `FeatureEvidenceBundle`. The
  review/chain path must cite that bundle, while graph-wide accounting treats
  the original failed lane as superseded only after the patch terminal lane
  validates. It also carries
  `xmuse.graph_wide_lane_accounting_boundary.v1`，
  从 graph-set artifact、`FeatureGraphStatusStore` 和 platform-runner
  candidate lineage 证明 completed lanes 已被候选证据覆盖，缺 graph-set/status
  authority、ready/active/blocked residue、未覆盖 completed lane 或缺失/不完整/
  不匹配 runner-session artifact 时保持 `manual_gap`。缺 session artifact
  refs/source refs 时 L10 consumer gate 会拒绝。下一步是使用该 runner-session
  boundary 和 graph-wide accounting 去驱动更宽的 live runner/review session，
  但不能过读为 broad live worker execution/review 或 server truth。
  L8 platform-runner candidate selection now receives the xmuse root explicitly
  and cannot silently bypass durable lane recovery because the orchestrator
  object lacks a private `_root` attribute. Projection lanes use `lane_local_id`
  for recovery-artifact lookup while preserving dispatch identity. This is
  local runner recovery authority hardening, not overnight-safe proof. Stale
  dispatched-lane repair now writes a durable `lane_recovery_artifact` after the
  CAS-guarded transition to `exec_failed` succeeds, records the artifact ref on
  lane metadata, and the next candidate-selection pass consumes it as a
  non-retry recovery block; failed CAS repairs do not leave recovery artifacts.
  Graph-bound pidless dispatched lanes are also repaired into
  `dispatch_no_worker_pid` non-retry recovery artifacts; projection-only
  pidless lanes remain manual authority gaps. This closes stale worker and
  graph-bound pidless-dispatch redispatch-loop bypasses only at local runtime/
  contract boundary.
  Orchestrator gate failure now writes a durable `lane_recovery_artifact` after
  the lane reaches `gate_failed`. The artifact is sourced from
  `platform_orchestrator_gate_runner`, derives its decision through
  `evaluate_lane_recovery` from lane budget/failure evidence, and records retry
  or `refactor_required` decisions plus manual gaps/forbidden claims. This
  closes the normal gate-failure producer gap only at contract/local authority
  boundary; it is not live long-running runner proof, review truth, server
  truth, or overnight-safe recovery.
  Review patch-forward now writes a durable `lane_recovery_artifact` for the
  original failed lane after the patch-forward verdict appends the patch lane.
  The artifact is sourced from
  `platform_orchestrator_review_patch_forward`, carries review verdict,
  evidence, gate report, budget, and patch-lane refs, and records a non-retry
  `suspended` decision so a same-path redispatch of the original lane is blocked
  by the existing recovery dispatch gate. This is recovery authority production
  for the original lane only; it does not prove patch-lane execution/review,
  independent review truth, live runner proof, server truth, or release
  readiness.
  Review rejection retry exhaustion now writes a durable
  `lane_recovery_artifact` for the failed original lane with
  `source_authority=platform_orchestrator_review_rejection` and
  `decision=refactor_required`. A same-path redispatch of that rejected lane is
  blocked by the existing recovery dispatch gate. This is repeated-review
  failure recovery authority only; it is not independent review truth, broad
  live runner proof, server truth, or release readiness.
  Merge failure after review now also writes durable recovery artifacts for
  graph-bound lanes: reworkable merge conflicts record retry-allowed recovery
  evidence before redispatch, retry exhaustion records `refactor_required`, and
  non-reworkable merge failures record non-retry `suspended` recovery evidence
  that blocks same-path redispatch. This is merge-failure recovery lineage only;
  it is not GitHub merge truth, independent review truth, server truth, or
  release readiness.
  Review retry exhaustion in reconcile now writes durable recovery artifacts:
  exhausted `review_timeout`/`review_no_verdict` records
  `refactor_required`, and exhausted `review_infra_unavailable` records a
  non-retry `suspended` decision while active backoff remains non-terminal.
  The same dispatch recovery gate blocks same-path redispatch of the exhausted
  lane. This is retry-budget recovery authority only; it is not independent
  review truth, broad live runner proof, server truth, or overnight-safe
  recovery.
  Retry-eligible first/early review-GOD failures now also write durable
  `lane_recovery_artifact` records from `reconcile_status_changes` before the
  lane is moved back to `gated`. These artifacts use
  `source_authority=platform_orchestrator_review_retry`, carry a retry-allowed
  `retry` decision, preserve `manual_gap` when graph/lane authority is missing,
  and remain non-blocking for the dispatch recovery gate. This is contract/local
  recovery producer proof only; it is not independent review truth, broad live
  runner proof, server truth, or overnight-safe recovery.
  Overnight supervisor stage start now has a recovery preflight gate that scans
  durable `lane_graphs/*.recovery.json` artifacts from the runtime root. A
  non-retry recovery decision or invalid recovery artifact writes blocked
  supervisor evidence and refuses to start the stage, preserving
  `manual_gap`/forbidden claims instead of claiming overnight-safe recovery.
- Wave E / L10-L11 必须等 L8-L9 lineage 诚实闭合后再声明 cockpit/overnight 能力。

推进顺序固定为:

```text
Wave A: L1-L2 authority root
-> Wave B: L3-L5 GOD room speech runtime
-> Wave C: L6-L7 deliberation-to-execution authority
-> Wave D: L8-L9 execution safety
-> Wave E: L10-L11 aggregation/operator surface
```

## OpenCode Involvement

OpenCode/DeepSeek 可以直接修改工作树生成 candidate patch，但只在 Codex 给出明确
scope、allowed files、acceptance gate 和 forbidden actions 后允许。候选 patch
不是最终事实；Codex 必须独立审查 diff、runtime state、package boundary、tests、
proof-level 声明和 ledger 更新。

适合 OpenCode 的工作:

- 全仓 grep、调用链 inventory、候选 bypass 表格。
- boilerplate、schema 字段传播、重复 fixture 更新。
- 有明确验收 gate 的局部 candidate patch。
- read-only review 或非权威审计摘要。

OpenCode 禁止:

- 提交、推送、更新 PR、改仓库设置、读写 secrets。
- 写 runtime state 或提交 `.goal-runs/`、DB、jsonl、`feature_lanes.json`。
- 决定 authority、peer-GOD、review truth、GitHub truth、MemoryOS live proof。
- 把自身输出、local tests 或 worker self-report 当作最终 review truth。

规范调用仍是:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

## Wave A - L1-L2 Authority Root

状态: 已有 contract proof。后续只做漂移审计或上游 blocker 修复。

L1 最小切片:

- `xmuse.authority_boundary_audit.v1`
- 覆盖 TUI/API/runner/supervisor/review/release/memory/GitHub mutating path。
- 标记 `ok`、`manual_gap` 或 `refactor_required`。

L2 最小切片:

- `xmuse.selected_god_binding_resolution.v1`
- 证明 `ProviderAccount`、`GodProfile`、`RoomSelectedGodBinding` 被 L3 authorship
  和 L4 invocation attempt 实际消费。

OpenCode 可做: path inventory、provider inventory 使用点扫描、裸 CLI/model 字符串
扫描、serializer/test boilerplate。

Codex 必须决定: authority 分类、GOD 身份、OpenCode 是否仍为 bounded worker、
proof level。

禁止声明: provider inventory 中出现某 CLI 就代表 peer-GOD 或 selectable GOD。

## Wave B - L3-L5 GOD Room Speech Runtime

目标: selected GOD -> provider invocation artifact -> durable speak event -> replay。

L3 切片:

- 每个 room event 携带 actor、binding/source、proof_level。
- 区分 `operator_action`、`provider_invocation`、`imported_fixture`。

L4 切片:

- `xmuse.god_room_provider_speech_response.v1`
- 从 selected binding 触发。
- 记录 command/model/variant、prompt/output refs、timing、exit status、raw archive。
- missing config、missing CLI、timeout、nonzero exit 必须 fail closed。

L5 切片:

- L4 artifact -> digest check -> durable speak event -> L3 replay proof。
- request-body-only/direct response 保持 `manual_gap`。

OpenCode 可做: subprocess wrapper candidate、stdout/stderr archive helper、negative
tests、replay lookup helper、字段传播。

Codex 必须决定: invocation proof 与 capture proof 的边界。

禁止声明: capture proof 等于 live provider invocation proof；fixture 等于 natural
groupchat。

## Wave C - L6-L7 Deliberation-To-Execution Authority

目标: durable deliberation -> frozen blueprint -> authoritative laneDAG。

L6 切片:

- freeze artifact 保留 assumptions、blockers、rejected alternatives、source refs、
  decision/source-event lineage。
- fixture freeze 只能是 `contract_proof`。
- provider-backed/natural multi-GOD freeze 必须有上游 L3-L5 lineage。

L7 切片:

- laneDAG / graph-set / lane runtime contract 成为 dispatch/review 的 authority。
- `feature_lanes.json` 只做 projection。
- detached laneDAG artifact 不能单独成为 execution authority。

OpenCode 可做: fixture freeze call-site 扫描、`feature_lanes.json` 读写点扫描、
dispatch/review 入口 inventory、机械字段传播。

Codex 必须决定: 哪些路径是 authority，哪些只是 compatibility/projection。

禁止声明: clean fixture freeze 代表 natural deliberation closure。

## Wave D - L8-L9 Execution Safety

状态: 当前焦点。

L8 已有:

- `xmuse.local_runner_recovery_proof.v1`
- 证明 local runner candidate selection 可因 durable recovery artifact 阻止 dispatch。
- proof level 最高只能按实际证据标为 `local_runtime_proof`，不能 overread 为
  overnight-safe 或 server truth。

L8 下一类切片:

- recovery enforcement path matrix:
  runner candidate selection、orchestrator dispatch、review intake、
  patch-forward scheduling、supervisor loop。
- 每条路径证明 blocked/refactor_required lane 不能继续同路径 dispatch/retry。

L9 当前默认切片:

```text
L6 freeze
-> L7 lane contract
-> L8 recovery proof/decision
-> bounded worker candidate
-> independent review verdict
-> accepted/reworked/rejected
-> patch-forward lineage
-> release evidence link
```

下一轮应优先消费 `xmuse.local_runner_recovery_proof.v1`，把它作为 review/release
evidence 的 recovery enforcement lineage，而不是 review truth、server truth 或
merge truth。
Review closure and release-evidence aggregation should also fail closed unless
the merge verdict cites at least one valid graph-status-bound
`xmuse.local_execution_candidate.v1` artifact resolvable from the xmuse root;
opaque worker refs alone are not enough. Platform runner emits these artifacts
  by default under runtime `work/local_execution_candidates` after successful
  dispatch; `--local-execution-candidate-output-dir` only overrides the directory.
Review intake can auto-discover validator-passing artifacts from that directory
as reviewer input only when the candidate matches the conversation, lane, and
top-level GOD-room graph scope and declares `producer=platform_runner_dispatch`.
Manual CLI captures remain generic candidate evidence and are not auto-discovered
as runner-emitted session proof. The artifact remains `candidate_only` and
cannot become review truth without independent review.
Review closure API now writes `xmuse.god_room_lane_review_chain_proof.v1` on
the same graph-status-gated closure path and returns both `review_closure` and
`review_chain_proof` artifact refs. A separate review-chain-proof API can also
reload the durable review closure and regenerate the chain proof as a second
operation. The current proof is still contract/API handoff proof with bounded
session detail: the chain proof re-loads patch-forward, patch-lane review
intake, and patch-lane review verdict artifacts from the closure and degrades to
`manual_gap` on missing L8 recovery lineage, dangling refs, scope mismatch,
non-merge terminal verdict, or proof-level inflation. Positive API tests now
use a platform-runner local execution candidate artifact emitted through the
bounded dispatch loop. Review-intake auto-discovery also requires the candidate
to be backed by a matching graph-native worker `FeatureEvidenceBundle` in
`FeatureGraphArtifactStore`; patch-forward candidate refs now prove patch-lane
worker-evidence producer coverage only at contract/API boundary. The terminal
patch-lane verdict's bundle refs now enter the review-chain worker-bundle
citation boundary, and L10 can carry those verified bundle refs as source refs
only. This does not yet prove a broad live worker execution/review session or
server truth.
The API-generated review-chain artifact can be consumed by L10 release evidence
candidate reports only as source-ref aggregation while preserving
`candidate_report_is_not_live_memoryos_proof`; the same artifact can enter the
release evidence pack replay bundle only as GOD-room runtime closure
aggregation, where missing GitHub/server truth keeps the section `manual_gap`.
Verified worker-evidence bundle refs from the chain proof remain aggregation
lineage only; they are not review truth, MemoryOS live proof, or merge truth.
The shared review-closure handoff now also carries review-closure
`source_event_lineage` refs into the chain-proof MemoryOS candidate path,
runtime-closure replay source refs, and review-chain release linkage. These
`god-room-event:*` and `provider_response_artifact:*` refs are replay
provenance only, not live MemoryOS, independent review, or server truth.
Review-chain release linkage now emits source refs only after the chain proof
is actually linked through runtime-closure replay source refs, bounded session
gate, and current review-closure handoff; manual-gap linkage does not copy
unrelated GOD-room/provider refs from the same replay section.
MemoryOS candidate reports now revalidate runtime-closure artifacts that carry
review-closure or review-chain lineage before using their source refs as
MemoryOS payload hints. Provider-only runtime replay refs remain candidate
hints, but stale review candidate/session lineage keeps the runtime-closure
candidate not-ready.
Both consumers now require the shared bounded-session consumer gate before
accepting that review-chain artifact: a hand-written `chain_ready` artifact
without `local_execution_review_session`, verified session artifact validation,
verified runner-recovery/graph/candidate/reviewer boundaries, and matching
candidate refs stays `manual_gap`.
The direct review-closure handoff path now also validates the referenced
candidate and runner-session artifact for each platform-runner candidate before
L10/runtime-closure aggregation can seed source refs from that closure; missing,
mismatched, stale, empty-candidate, or proof-inflated sessions keep the handoff
not-ready.
Release evidence pack now treats a supplied GOD-room review-closure artifact
without a matching review-chain proof as an expected L9 handoff gap:
runtime-closure replay records `review_chain_proof.status=manual_gap`,
`expected=true`, and `god_room_review_chain_proof_artifact_missing` instead of
silently omitting the missing chain proof. Legacy packs without GOD-room
review-closure input remain unaffected. This is aggregation gap visibility
only; it does not create release linkage, review truth, server truth, MemoryOS
live proof, or pack readiness.
The chain proof also exposes patch-forward artifact gap accounting inside the
bounded session evidence: source gaps resolved by validated patch-lane
execution/review artifacts are separated from retained gaps, especially
`release_evidence_not_linked`. This prevents silently dropping upstream
patch-forward gaps while still avoiding a false claim that L10 release export
has happened.
The same bounded session proof now validates terminal reviewer independence by
comparing patch-lane verdict `reviewer_id` with cited local execution candidate
`worker_id`s. A worker self-review or missing reviewer identity keeps the chain
proof `manual_gap`; this is artifact-local review-boundary proof only, not
server-side review truth.
The chain proof also validates that review closure carries
`graph_status_source_authority = feature_graph_status_store`, non-empty
`source_event_lineage`, and a terminal feature graph status snapshot whose
merged status and source-event lineage match the closure. Missing or mismatched
graph-status/source-event lineage keeps the chain proof `manual_gap`, so L10
cannot aggregate a review-chain artifact whose merge claim is detached from the
L7/L9 graph-status authority.
The same session proof now validates the patch-lane review-intake artifact's
own graph-status authority boundary: `source_authority` must include
`feature_graph_status_store` and `lane_dag_artifact`, intake
`source_event_lineage` must be non-empty, the embedded feature graph status must
still be `reviewing`, and that status snapshot must carry the same
source-event lineage as the intake. This makes the bounded local
execution/review session wider without treating the intake, worker candidate,
or local tests as review truth.
The chain proof also cross-checks every cited local execution candidate's
`graph_status_lineage` against that patch-lane review-intake feature graph
status snapshot. Graph-set, feature-graph, status-id, status, or
source-event-lineage mismatch keeps the chain proof `manual_gap`, preventing a
candidate that is valid in isolation from being spliced into the wrong
artifact-local review session.
The same proof now also reconciles review-closure
`cited_candidate_artifact_refs` against the actually resolved valid local
execution candidate lineage artifact refs. Missing declared artifacts or
resolved-but-undeclared candidate artifacts keep the chain proof `manual_gap`,
and the shared L9/L10 handoff gate rejects the same mismatch before any
release-evidence source-ref aggregation.
It also validates closure-embedded `cited_candidate_artifact_lineage` against
freshly resolved local execution candidate lineage. Missing, unexpected, or
mismatched embedded lineage keeps the chain proof and shared handoff gate at
`manual_gap`, so downstream aggregation cannot treat stale closure lineage as
truth.
The same bounded session now includes
`xmuse.runner_session_boundary.v1`, which reloads the platform-runner
`xmuse.runner_session.v1` artifact referenced by each runner-emitted local
execution candidate and verifies completed session status, run id, runner id,
candidate refs, and graph scope. Missing, incomplete, mismatched, or
empty-candidate/proof-inflated runner-session artifacts keep the proof
`manual_gap`.
This proves a local runner session boundary only; it is not review truth,
server truth, or live provider proof. Runner-emitted candidates whose
graph-native status lineage has not reached `reviewing` remain `manual_gap`,
so a dispatch-return artifact still cannot satisfy review-ready lineage by
itself. Platform runner now has a first bounded graph-native worker-evidence
producer handoff before local candidate capture: when the dispatched lane
carries real provider binding metadata, blueprint refs, acceptance criteria,
required checks, and the graph status has planning-run authority, the runner
claims the READY status for that lane, submits a `FeatureEvidenceBundle`
through the existing worker-evidence coordinator, persists it in
`FeatureGraphArtifactStore`, and advances `FeatureGraphStatusStore` to
REVIEWING. Missing prerequisites keep the candidate path at `manual_gap`.
This is local runtime / contract handoff only, not review truth, server truth,
or broad live worker execution proof. The same bounded session also includes
`xmuse.graph_wide_lane_accounting_boundary.v1`, sourced from the graph-set
artifact, `FeatureGraphStatusStore`, and validated platform-runner local
execution candidate lineage. It fail-closes missing graph-set/status authority,
unexpected or missing feature-graph status records, ready/active/blocked lane
residue, and completed lanes without matching `platform_runner_dispatch`
candidate lineage. This widens the handoff toward graph-level accounting while
remaining `contract_proof` / `not_server_truth`.

OpenCode 可做: bounded low-intelligence candidate patch、候选测试/报告、read-only
review、L9 path inventory。

Codex 必须决定: independent review verdict、patch 接受/拒收、proof-level、ledger
claim boundary。

禁止声明: local tests、worker self-report、OpenCode 输出或 recovery artifact 本身是
review truth。

## Wave E - L10-L11 Aggregation And Operator Surface

目标: 只聚合上游 proof，再通过 operator surface 展示和控制。

L10 切片:

- honest replay bundle refresh。
- supplied GOD-room review closure without matching review-chain proof must
  appear as explicit `manual_gap` in runtime-closure replay, not as silent
  omission or release readiness.
- 明确区分 provider speech/manual gap、freeze、laneDAG、execution/review、
  MemoryOS trace/manual gap、GitHub CI truth、GitHub review truth/blocker、
  merge truth/blocker。
- `ready_for_replay` 不等于 `ready_to_merge`。

L11 切片:

- `NativeCliSessionBridge` 从 L2 binding 启动真实 selected CLI。
- `MachineEventBridge` 产出 L4 artifact 或降级 `raw_archive_only`。
- `GodRoomProjectionBridge` 只投影 L3/L5 durable speech。
- pane registry 是 projection，不是 authority。
- operator input 必须记录 source refs。

OpenCode 可做: evidence schema draft、GitHub truth JSON shape、trace mapping draft、
clowder-ai reference 摘要、raw archive helper、read-only TUI viewer。

Codex 必须决定: release readiness、merge truth、MemoryOS live proof、cockpit/soak
claim boundary。

禁止声明: CI success 是 review/merge truth；MemoryOS plan 是 live trace；TUI/pane/raw
terminal output 是 durable GOD room speech；draft/open/unmerged PR 有 `pr_merged`。

## Default Next Goal

默认下一轮长 `/goal`:

- target_layers: `["L9"]`
- upstream dependency: L6 freeze lineage, L7 lane contract/status authority, and
  L8 `xmuse.local_runner_recovery_proof.v1`
- proof target: one medium-grained graph-native execution/review/patch-forward
  lineage linked into release evidence as aggregation only, using validated
  platform-runner-emitted local execution candidate artifacts where available
- task document: `docs/xmuse/next-production-closure-long-goal.md`
- forbidden overread: review truth、server truth、merge truth、peer-GOD、live
  MemoryOS、overnight readiness
