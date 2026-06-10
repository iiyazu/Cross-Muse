# xmuse Shared Contract Fixtures

更新日期: 2026-06-02

S0 冻结的共享契约 fixture 位于:

```text
tests/fixtures/xmuse/contracts/
```

这些 fixture 是并行 session 的最小对齐面，不是生产 store 的替代实现。模块 session
可以消费它们或在本 session 内使用 fake/stub，但新增跨层字段必须交给 S0 review。

每个 fixture 必须能被 contract test 证明包含:

- stable id: event 使用 `event_id`，artifact 使用 `artifact_id`，read envelope 使用
  `envelope_id`，card 使用 `intent_id`，session interface manifest 使用 `manifest_id`。
- version: 事件使用 aggregate `version`，其他 fixture 使用顶层 `version`。
- source refs: 事件使用 payload `source_refs`，其他 fixture 使用顶层 `source_refs`。
- `created_at`、`updated_at` 或 `generated_at` UTC timestamp。

## Fixture 组

| 目录 | 作用 |
|---|---|
| `events/` | at-least-once 事件、idempotency key、producer/consumer session、artifact refs |
| `artifacts/` | blueprint、feature plan、graph-set、lane graph 的稳定 artifact refs 和 lineage |
| `read_envelopes/` | TUI/dashboard 可读的只读 envelope |
| `cards/` | 群聊 compact card 的 artifact refs 和 dashboard drill-down refs |
| `interfaces/` | S1-S8 allowed inputs/outputs、ready flag、禁止写入边界 |

## Fixture 清单（生产级 inventory）

### Event Fixtures

| event_type | 文件 | 用途 |
|---|---|---|
| `blueprint.approved` | `events/blueprint.approved.v1.json` | 蓝图审批通过，触发 planning |
| `planning.started` | `events/planning.started.v1.json` | 规划开始 |
| `planning.failed` | `events/planning.failed.v1.json` | 规划失败 |
| `feature_plan.ready` | `events/feature_plan.ready.v1.json` | 特性计划就绪，触发 graph generation |
| `graph_set.ready` | `events/graph_set.ready.v1.json` | 图集就绪，触发 execution |
| `graph_set.failed` | `events/graph_set.failed.v1.json` | 图集生成失败 |
| `lane.ready` | `events/lane.ready.v1.json` | Lane 就绪 |
| `lane.updated` | `events/lane.updated.v1.json` | Lane 状态更新 |
| `lane.blocked` | `events/lane.blocked.v1.json` | Lane 阻塞 |
| `review.verdict` | `events/review.verdict.v1.json` | 审查裁定 |
| `takeover.requested` | `events/takeover.requested.v1.json` | 接管请求 |
| `takeover.resolved` | `events/takeover.resolved.v1.json` | 接管解决 |
| `run.terminal` | `events/run.terminal.v1.json` | Run 终止 |
| `blueprint.gap_found` | `events/blueprint.gap_found.v1.json` | 蓝图缺口发现 |

### Artifact Fixtures

| artifact_type | 文件 | 用途 | 对应 surface |
|---|---|---|---|
| `blueprint` | `artifacts/blueprint.v1.json` | 蓝图 artifact | S3 Blueprint, S7 Dashboard |
| `feature_plan` | `artifacts/feature_plan.v1.json` | 特性计划 artifact | S3 Blueprint, S4 Graph |
| `feature_evidence_bundle` | `artifacts/feature_evidence_bundle.v1.json` | Feature worker 证据包 | S5 Execution, S7 Dashboard |
| `feature_graph_blocked_review_plan` | `artifacts/feature_graph_blocked_review_plan.v1.json` | 阻塞审查计划 | S5 Execution |
| `feature_graph_patch_forward_gate_result` | `artifacts/feature_graph_patch_forward_gate_result.v1.json` | Patch-forward 门禁结果 | S5 Execution |
| `feature_graph_patch_forward_merge_guard_decision` | `artifacts/feature_graph_patch_forward_merge_guard_decision.v1.json` | Patch-forward merge guard 决策 | S5 Execution |
| `feature_graph_patch_forward_merge_guard_handoff` | `artifacts/feature_graph_patch_forward_merge_guard_handoff.v1.json` | Patch-forward merge guard 交接 | S5 Execution |
| `feature_graph_patch_forward_plan` | `artifacts/feature_graph_patch_forward_plan.v1.json` | Patch-forward 计划 | S5 Execution |
| `feature_graph_review_status_transition_plan` | `artifacts/feature_graph_review_status_transition_plan.v1.json` | 审查状态转换计划 | S5 Execution |
| `feature_graph_rework_packet` | `artifacts/feature_graph_rework_packet.v1.json` | Rework packet（feature graph 级） | S5 Execution |
| `feature_graph_status` | `artifacts/feature_graph_status.v1.json` | Feature graph 状态 | S5 Execution, S7 Dashboard |
| `feature_graph_status` | `artifacts/feature_graph_status_running_claim.v1.json` | Feature graph 运行中 claim | S5 Execution |
| `feature_graph_status_event` | `artifacts/feature_graph_status_event.v1.json` | Feature graph 状态事件 | S5 Execution, S7 Dashboard |
| `feature_graph_status_event` | `artifacts/feature_graph_provider_binding_degradation_event.v1.json` | Provider binding 降级事件 | S5 Execution |
| `feature_graph_takeover_decision` | `artifacts/feature_graph_takeover_decision.v1.json` | 接管决策 | S5 Execution |
| `feature_graph_takeover_followup_review_application` | `artifacts/feature_graph_takeover_followup_review_application.v1.json` | 接管后续审查应用 | S5 Execution |
| `feature_graph_takeover_handoff` | `artifacts/feature_graph_takeover_handoff.v1.json` | 接管交接 | S5 Execution |
| `feature_graph_takeover_outcome` | `artifacts/feature_graph_takeover_outcome.v1.json` | 接管结果 | S5 Execution |
| `feature_graph_takeover_plan` | `artifacts/feature_graph_takeover_plan.v1.json` | 接管计划 | S5 Execution |
| `feature_graph_takeover_review_handoff` | `artifacts/feature_graph_takeover_review_handoff.v1.json` | 接管审查交接 | S5 Execution |
| `feature_graph_worker_claim_plan` | `artifacts/feature_graph_worker_claim_plan.v1.json` | Worker claim 计划 | S5 Execution |
| `feature_graph_worker_evidence_submission_plan` | `artifacts/feature_graph_worker_evidence_submission_plan.v1.json` | Worker evidence 提交计划 | S5 Execution |
| `feature_review_verdict` | `artifacts/feature_review_verdict.v1.json` | Feature 级审查裁定 | S5 Execution, S7 Dashboard |
| `graph_set` | `artifacts/graph_set.v1.json` | 图集 artifact | S4 Graph, S7 Dashboard |
| `lane_graph` | `artifacts/lane_graph.v1.json` | Lane graph artifact | S4 Graph, S5 Execution |
| `provider_session_binding` | `artifacts/provider_session_binding.v1.json` | Provider session binding 记录 | S5 Execution, S8 Adapters |
| `rework_packet` | `artifacts/rework_packet.v1.json` | Rework packet（初始版） | S5 Execution |
| `rework_packet` | `artifacts/feature_graph_rework_packet.v1.json` | Rework packet（feature graph 绑定版） | S5 Execution |

### Compact Card Fixtures

| card_type | 文件 | 用途 |
|---|---|---|
| `feature_plan_ready` | `cards/feature_plan_ready.v1.json` | 特性计划就绪卡片 |
| `run_progress` | `cards/run_progress.v1.json` | 运行进度卡片 |
| `lane_blocked` | `cards/lane_blocked.v1.json` | Lane 阻塞卡片 |
| `review_verdict` | `cards/review_verdict.v1.json` | 审查裁定卡片 |
| `takeover_requested` | `cards/takeover_requested.v1.json` | 接管请求卡片 |

### Read Envelope Fixtures

| envelope_type | 文件 | 用途 |
|---|---|---|
| `tui_worklist` | `read_envelopes/tui_worklist.v1.json` | TUI 工作列表只读 envelope |

### Interface Fixtures

| 文件 | 用途 |
|---|---|
| `interfaces/xmuse_parallel_sessions.v1.json` | S1-S8 并行 session I/O manifest |

## Session I/O

| Session | 输入 | 输出 |
|---|---|---|
| S1 Chat/TUI | chat store、execution cards、TUI worklist envelope | conversation events、compact cards、TUI read rendering |
| S2 Coordinator | `blueprint.approved`、`graph_set.ready`、lane events、dead-letter records | coordinator lifecycle API、degraded/dead-letter escalation |
| S3 Blueprint | `blueprint.approved`、blueprint artifact | `planning.started`、`feature_plan.ready`、`planning.failed`、feature plan artifact |
| S4 Graph | `feature_plan.ready`、feature plan artifact | `graph_set.ready`、`graph_set.failed`、graph-set/lane-graph artifacts |
| S5 Execution | `graph_set.ready`、`lane.ready`、coordinator API、subagent contract | `lane.ready`、`lane.updated`、`lane.blocked`、`run.terminal`、projection lineage |
| S6 Subagent | lane context bundle、acceptance criteria、provider policy | worker goal/result schema、blocker classification、skill prompt contract |
| S7 Dashboard | read envelopes、artifact refs、run health、dead-letter records | read-only drill-down endpoints and degraded/error shapes |
| S8 Adapters | S0 fixtures、coordinator API、blueprint workflow artifacts | Ray backend adapter, LangGraph shadow/replay adapter, native parity tests |

## Boundary Rules

- `feature_lanes.json` remains the Stage 0 execution fact source, but no module session may hand-edit it.
- TUI and dashboard consume read envelopes/cards; they do not drive workflow state.
- Ray and LangGraph adapters consume artifact/event refs; they do not own durable state.
- CLI subagents return structured evidence to the coordinator; they do not write lane status.
