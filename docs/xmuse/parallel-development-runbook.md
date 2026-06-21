# xmuse 并行开发运行手册

更新日期: 2026-06-20

## 目的

本手册用于在多个 Codex session 中并行开发 xmuse，同时保持《解耦开发协议》的边界。
目标是让多数 session 能独立推进、独立测试、低冲突合并，而不是让多个 agent 共同
争抢同一条端到端执行链。

## `/goal` 模式下的从属边界

当本手册被 Codex `/goal` runtime loop 使用时，它从属于
`docs/xmuse/real-runtime-loop-behavior-policy.md`。不要用 S0-S8 batch 来选择或扩大
任务范围；单个 `/goal` 必须先选择一个 `active_boundary`。

并行 session 只能作为该 boundary 之下的 bounded observe / diagnose / review /
verify / candidate lane。每个 session 必须有 allowed files、expected artifact、
无重叠写入范围和 no-auto-merge 约束；只有主 `/goal` 可以导入候选结果、改变
`active_boundary`、提交 PR/merge，或改写 durable authority。

## 总原则

1. 先冻结接口，再并行实现。
2. 每个 session 只拥有一个模块和明确 allowed files。
3. 执行层采用中心化 xmuse coordinator；其他 session 不直接写 lane status。
4. 每层必须能用 fake/stub 单独测试。
5. 集成、跨层 E2E、状态写入语义由 S0 Integration session 统一把关。
6. 能复用既有代码资源就复用；若评估不适合复用，必须说明原因并隔离旧实现。

## 必读上下文包

每个 Codex session 启动前必须读取:

```text
docs/xmuse/解耦开发协议.md
docs/xmuse/real-runtime-loop-behavior-policy.md
docs/xmuse/code-quality-and-archive-policy.md
xmuse/HANDOFF.md
xmuse/CODEX_GOAL_HANDOFF.md
```

按模块再读取:

```text
xmuse/chat_api.py
xmuse/dashboard_api.py
xmuse/platform_runner.py
src/xmuse_core/chat/*
src/xmuse_core/structuring/*
src/xmuse_core/platform/*
src/xmuse_core/providers/*
```

## 共享接口包

并行 session 之间只通过以下接口对接。

### Contract Fixture 路径

S0 统一维护 contract fixture，其他 session 只消费或在允许范围内追加模块 fixture。
默认路径:

```text
tests/fixtures/xmuse/contracts/events/
tests/fixtures/xmuse/contracts/artifacts/
tests/fixtures/xmuse/contracts/read_envelopes/
tests/fixtures/xmuse/contracts/cards/
```

命名规则:

- 文件名使用 `<event-or-artifact-name>.v<version>.json`。
- fixture 必须包含 stable id、version、created_at 或 updated_at、source refs。
- 若 session 需要新增字段，先在本地 fake/stub 中兼容旧 fixture，并向 S0 输出 `needs-S0-contract-review`。

### 事件

| 事件 | 所属层 | 说明 |
|---|---|---|
| `blueprint.approved` | Layer 1 -> 2a | approved blueprint 进入拆解 |
| `planning.started` | 2a | planning run 创建 |
| `feature_plan.ready` | 2a -> 2b | feature plan 通过审查 |
| `planning.failed` | 2a | 拆解失败 |
| `graph_set.ready` | 2b -> 2c | graph-set 可执行 |
| `graph_set.failed` | 2b | graph 生成失败 |
| `lane.ready` | 2c | lane 可调度 |
| `lane.updated` | 2c -> read models | lane 状态变化 |
| `lane.blocked` | 2c -> TUI/dashboard/GOD | lane 阻塞 |
| `review.verdict` | review gate | 审查结果 |
| `takeover.requested` | review/runner | 需要接管 |
| `run.terminal` | 2c | run 完成 |

所有事件默认 at-least-once，消费者必须按 idempotency key 幂等。

### Artifact

| Artifact | 当前位置 | 规则 |
|---|---|---|
| chat/conversation | `xmuse/chat.db` | Layer 1 权威 |
| planning events | `xmuse/planning_events.sqlite3` | event 权威 |
| planning runs | `xmuse/planning_runs.sqlite3` | planning lifecycle 权威 |
| feature plans | `xmuse/feature_plans/` | 2a 输出 |
| graph sets/lane graphs | `xmuse/lane_graphs/` | 2b 输出 |
| lane projection/status | `xmuse/feature_lanes.json` | Stage 0 runner-visible execution projection；coordinator/state-machine guarded |
| read envelopes/cards | read model/card stores | TUI/dashboard 契约 |

## 推荐 Session 划分

### S0 Integration / Contract Owner

职责:

- 冻结事件 schema、artifact refs、fixture。
- 审核每个 session 是否越界。
- 维护并行开发状态表。
- 最终合并和跨层验证。

允许修改:

- `docs/xmuse/*`
- `tests/test_xmuse_*contract*.py`
- `tests/fixtures/xmuse/contracts/**`

禁止:

- 不直接实现业务模块。
- 不把未验证的 session 输出合入主线。

### S1 GOD Chat / TUI Read Layer

职责:

- 群聊、participants、cards、worklist read envelope。
- TUI 消费 fixtures 和 read envelopes。

允许修改:

- `src/xmuse_core/chat/*`
- `src/xmuse_core/platform/read_envelopes.py`
- `xmuse/tui/*`
- chat/TUI focused tests

禁止:

- 不写 `feature_lanes.json`。
- 不启动 runner。
- 不修改 Layer 2 services。

### S2 Coordinator Core

职责:

- 明确 native xmuse coordinator API 和 lifecycle。
- 把 `platform_runner.py` / `PlatformOrchestrator` 的 coordinator 边界收束为可测服务。
- 管理 dead-letter/degraded 升级路径。

允许修改:

- `xmuse/platform_runner.py`
- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/runner_supervisor.py`
- coordinator/dead-letter tests

禁止:

- 不重写 chat/TUI。
- 不把 Ray/LangGraph 设为必需依赖。
- 不绕过 `LaneStateMachine` 写状态。

### S3 Blueprint Decomposition

职责:

- `blueprint.approved -> planning.started -> feature_plan.ready/planning.failed`。
- fake planner/reviewer contract。
- planning run 幂等。

允许修改:

- `src/xmuse_core/structuring/blueprint_execution/*`
- `src/xmuse_core/structuring/feature_plan_*`
- `src/xmuse_core/agents/planning_god_adapters.py`
- focused tests

禁止:

- 不生成 graph-set。
- 不投影 lane。
- 不启动 runner。

### S4 Lane Graph Generation

职责:

- `feature_plan.ready -> graph_set.ready/graph_set.failed`。
- feature dependency graph。
- per-feature lane DAG。
- graph-set artifact refs。

允许修改:

- `src/xmuse_core/structuring/feature_graph_builder.py`
- `src/xmuse_core/structuring/feature_plan_store.py`
- `src/xmuse_core/structuring/models.py`
- graph/decomposition tests

禁止:

- 不调度 worker。
- 不改 runner status。
- 不写 `feature_lanes.json`，除非通过 projection service 测试 fixture。

### S5 Execution Scheduling

职责:

- `graph_set.ready/lane.ready -> Stage 0 projection -> LaneStateMachine`。
- ready-set、projection lineage、state transition guard。

允许修改:

- `src/xmuse_core/structuring/projection.py`
- `src/xmuse_core/platform/projection/*`
- `src/xmuse_core/platform/state_machine.py`
- selected orchestrator tests

禁止:

- 不改 TUI/chat。
- 不让 subagent 直接 `update_lane_status`。
- 不引入多 runner 抢写。

### S6 CLI Subagent / Skills Contract

职责:

- 定义 coordinator 调用 CLI subagent 的输入输出 schema。
- 定义 worker evidence、failure/blocker 分类、skill prompt contract。
- fake CLI harness tests。

允许修改:

- `src/xmuse_core/providers/*`
- `src/xmuse_core/platform/prompts/*`
- `xmuse/skills/*`
- provider/worker goal contract tests

禁止:

- 不创建新的自治 GOD 执行链。
- 不让 subagent 写 durable store。

### S7 Dashboard Drill-Down

职责:

- run health、dead-letter、graph-set、lane detail、takeover context drill-down。
- degraded/read-model 展示。

允许修改:

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/read_contracts.py`
- `src/xmuse_core/platform/run_health.py`
- dashboard/read-model tests

禁止:

- dashboard 不作为 workflow driver。
- 不新增 lane mutation 主路径。

### S8 Ray / LangGraph Adapters

职责:

- Ray actor backend 和 LangGraph workflow backend 的 adapter/shadow/replay。
- 不接管业务状态。

允许修改:

- `src/xmuse_core/agents/ray_*`
- `src/xmuse_core/structuring/*langgraph*`
- runtime backend tests

禁止:

- 不让 Ray actor 内存成为权威。
- 不让 LangGraph node 直接写 lane status。
- 不让 native path 依赖 Ray/LangGraph import。

## 并行批次

推荐启动顺序:

```text
Batch 0:
  S0 Integration / Contract Owner

Batch 1:
  S1 GOD Chat/TUI Read Layer
  S3 Blueprint Decomposition
  S4 Lane Graph Generation
  S6 CLI Subagent/Skills Contract
  S7 Dashboard Drill-Down

Batch 2:
  S2 Coordinator Core
  S5 Execution Scheduling

Batch 3:
  S8 Ray/LangGraph Adapters
  S0 cross-layer integration
```

理由:

- S0 先冻结接口，减少后续返工。
- S1/S3/S4/S6/S7 文件边界相对独立，适合先并行。
- S2/S5 触碰 runner/orchestrator/state machine，冲突风险高，等接口稳定后推进。
- S8 依赖 coordinator/workflow 边界稳定，先做 shadow/replay，不做主路径。

## Worktree 建议

每个 session 使用独立 worktree:

```bash
git worktree add ../memoryOS-s0-contract -b xmuse/s0-contract
git worktree add ../memoryOS-s1-chat-tui -b xmuse/s1-chat-tui
git worktree add ../memoryOS-s3-blueprint -b xmuse/s3-blueprint
git worktree add ../memoryOS-s4-graph -b xmuse/s4-graph
git worktree add ../memoryOS-s6-subagent -b xmuse/s6-subagent
git worktree add ../memoryOS-s7-dashboard -b xmuse/s7-dashboard
```

S2/S5 等 Batch 2 再创建，避免过早抢改 runner/state machine。

## 阻塞 Fallback 策略

当 session 被另一个 session 的输出阻塞时，不扩大 allowed files，也不临时改对方模块。
按以下顺序处理:

1. 使用 S0 contract fixture 或本 session 内 fake/stub 继续开发可独立验证的部分。
2. 若缺少接口字段，先用向后兼容的 optional 字段或 adapter，不破坏已有 fixture。
3. 在最终汇报中输出 `boundary-escalation`，说明被阻塞的接口、期望生产者、当前 fake/stub。
4. 标记 `needs-S0-contract-review`，由 S0 决定是否修改共享契约。
5. 若 fake/stub 无法覆盖核心行为，则停止该子任务，只交付已验证的独立部分。

## Session 输出要求

每个 session 最终必须汇报:

```text
1. 修改文件
2. 是否遵守 allowed files
3. 新增/更新的 contract 或 tests
4. 运行过的验证命令和结果
5. 未解决风险
6. 是否需要 S0 集成处理
```

## 合并规则

1. S0 先合并 contract/fixture。
2. 模块 session 合并前必须 rebase 最新 S0 contract。
3. 有冲突时优先保留 shared contract 和当前主路径生产代码；若当前主路径违反《解耦开发协议》，由 S0 标记 migration conflict 后再决定迁移。
4. 若旧实现与新边界冲突，按《代码质量与归档策略》移入 `xmuse/archive/` 或 `xmuse/legacy/`，再接入新实现。
5. 不允许为了过测试把跨层逻辑堆进单文件。
