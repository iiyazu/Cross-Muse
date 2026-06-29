# xmuse Outer GOD Integration Goal

更新日期: 2026-06-02

## 目标

Outer GOD 在 S0-S8 并行开发 session 完成后，接管最终统合与生产级验收。目标不是简单合并
代码，而是把 xmuse 收束为符合当前 north-star 的 Stage-1 平台:

```text
Ray 驱动的持久化 GOD 去中心化群聊
-> 人类/GOD 对等讨论并产出 mission blueprint
-> blueprint 拆为 feature plan
-> feature plan 拆为 per-feature lane graph / graph-set
-> 中心化 coordinator / CLI harness 并行调度 worker
-> review / rework / merge / takeover
-> TUI 展示群聊、compact cards、worklist
-> dashboard 作为灰盒 drill-down
```

## 必读文档

Outer GOD 开始前必须阅读:

```text
docs/xmuse/session-prompts/README.md
docs/xmuse/解耦开发协议.md
docs/xmuse/parallel-development-runbook.md
docs/xmuse/code-quality-and-archive-policy.md
docs/xmuse/shared-contract-fixtures.md
xmuse/HANDOFF.md
xmuse/CODEX_GOAL_HANDOFF.md
xmuse/FRONTEND_API.md
xmuse/FRONTEND_CONTEXT.md
xmuse/FRONTEND_IMPLEMENTATION_GUIDE.md
```

若文件不存在，记录缺失项并继续基于现有文档推进。

## Superpowers 要求

必须使用:

- `superpowers:using-superpowers`: goal 开始时。
- `superpowers:test-driven-development`: 写生产代码前。
- `superpowers:systematic-debugging`: 遇到失败、回归、测试异常时。
- `superpowers:brainstorming` 或 `superpowers:writing-plans`: 统合设计、缺口梳理、跨模块计划。
- `superpowers:requesting-code-review`: 跨模块改动完成后；不可用时记录 `review_unavailable` 并做人工 diff review。
- `superpowers:verification-before-completion`: 最终声称完成前。

## 行为边界

- 不查看 Windows/Open Design 前端目录。
- 不使用 `git reset --hard`、`git checkout --`、强制覆盖等破坏性操作。
- 不回滚用户或其他 session 的无关改动。
- 不启动 xmuse runtime，除非所有 focused tests 通过后进入 final smoke gate。
- 不把 `feature_lanes.json` 当长期设计权威；它只是 Stage 0 projection / live queue 兼容层。
- 不让 Ray/LangGraph 成为 native path 必需依赖。
- 不把 dashboard/TUI/workflow/runner 的跨层逻辑堆进单文件。

## 阶段 0: 等待并行 Session 完成

共享 flag 目录:

```text
/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/
```

Outer GOD 启动时必须创建该目录:

```bash
mkdir -p /home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags
```

进入统合前应等待或处理以下 ready flags:

```text
S0.contract.ready.json
S1.chat_tui.ready.json
S2.coordinator.ready.json
S3.blueprint.ready.json
S4.graph.ready.json
S5.execution.ready.json
S6.subagent.ready.json
S7.dashboard.ready.json
S8.adapters.ready.json
```

规则:

- ready flag 只表示可进入验收，不等于可信完成。
- 若某 session 长期未完成，先检查其代码和 tests 状态；能局部修复则修复，不能则记录 integration blocker。
- 不因 flag 缺失就停止全部工作；可先验收无依赖模块。
- 若某个 session 产物已被 Outer GOD 代码级验收并修复到生产级，但原 session 未写 ready flag，Outer GOD 可写入 `outer_god_verified` 的替代 ready flag 内容，并在最终汇报中标明原因。

## 阶段 1: 事实审计

对每个模块做代码级审计，而不是只看文档或 ready flag。

### S1 GOD Chat / TUI

检查:

- conversation / workspace isolation。
- participant / GOD identity。
- GOD-to-GOD `@mention`、inbox、read model。
- TUI 只读消费 messages / cards / worklist。
- dashboard drill-down 链接清晰，不反向驱动 workflow。

### S8 Ray GOD Runtime

检查:

- Ray actor 是否能承载持久 GOD session。
- actor 生命周期、启动、关闭、crash/restart 边界。
- actor 间通信是否通过明确消息、事件、artifact ref，而不是隐式共享内存。
- Ray 不成为业务状态权威。

### S3 Blueprint Decomposition

检查:

- `blueprint.approved -> planning.started -> feature_plan.ready/planning.failed`。
- replay / idempotency。
- feature plan 是否包含 acceptance criteria、source refs、blueprint refs。

### S4 Lane Graph

检查:

- `feature_plan.ready -> graph_set.ready/graph_set.failed`。
- 每个 feature 对应 lane DAG。
- DAG 无环、依赖干净、可并行释放 ready heads。
- graph-set artifact 有 stable id、version、source refs。

### S5 Execution Scheduling

检查:

- `graph_set.ready/lane.ready -> Stage 0 projection`。
- projection idempotency、`projection_revision`、lineage。
- 状态写入必须经 `LaneStateMachine` 或封装 service。
- `feature_lanes.json` 仅为 Stage 0 projection / compat。

### S2 Coordinator

检查:

- coordinator 是 planning / graph generation / scheduling / worker harness 的中心控制面。
- dead-letter / degraded path。
- rework / failure 携带足够上下文回到 review / coordinator。
- 没有新建多个自治 GOD 执行链。

### S6 CLI Harness

检查:

- worker goal contract。
- worker evidence output。
- blocker / failure 分类。
- subagent 不直接写 durable store。
- provider / model policy 可配置，适合后续 Codex / OpenCode 接入。

### S7 Dashboard

检查:

- dashboard read-only。
- run health、dead-letter、read-model status、graph-set / lane detail、takeover / rework context。
- dashboard 不驱动 workflow。

## 并行输出冲突仲裁

多个 session 修改同一文件时，Outer GOD 按以下顺序仲裁:

1. 以 `docs/xmuse/解耦开发协议.md` 和共享 contract fixtures 为最高约束。
2. 保留当前主路径生产代码，除非它违反协议或测试证明回归。
3. 同一模型或 schema 的字段冲突时，优先保留带 stable id、version、source refs、backward compatibility 的方案。
4. 同一行为的重复实现只能保留一个主路径；另一个若仍有调用者，移入 `xmuse/legacy/` 并加 adapter；若无调用者，移入 `xmuse/archive/`。
5. 不以 ready flag 先后决定谁说了算；以契约、测试、调用路径、架构边界决定。
6. 每个被仲裁的冲突必须在最终汇报中记录: 文件、冲突双方、保留方案、隔离方案、验证命令。

## 阶段 2: 生产级统合修复

发现以下问题时必须修复，不允许只保留 demo:

- 模块只有测试草案，没有生产实现。
- 测试 skip-safe 但没有真实 adapter MVP。
- ready flag 陈旧或验证命令不覆盖真实代码。
- 模块间接口字段不一致。
- 旧路径和新路径并存导致调用不清。
- dashboard / TUI / workflow / runner 出现反向依赖。
- Ray / LangGraph 被 native path 强依赖。
- execution scheduling 绕过 `LaneStateMachine`。
- worker / review / rework 缺少 context bundle。
- `feature_lanes.json` 被继续当作设计权威。

修复原则:

- 能复用现有代码就复用。
- 旧代码职责混杂、违反协议、无调用者时，移入 `xmuse/archive/`。
- 仍有调用者但将被替换的旧代码，移入或标注 `xmuse/legacy/`，保留 adapter 和删除条件。
- 不为测试通过牺牲架构边界。

## 阶段 3: 端到端能力验收

必须证明以下链路在代码层可运行，或被真实 fake integration 覆盖。

### 链路 A: GOD 群聊到 Blueprint

- 创建 conversation / workspace。
- 注册或加载 GOD participant。
- human / GOD message 可写入和读取。
- `@mention` / inbox 可工作。
- blueprint artifact 可由讨论结果产生或进入 approved 状态。

### 链路 B: Blueprint 到 Feature Plan

- `blueprint.approved` 触发 planning。
- 产出 `feature_plan.ready` 或 `planning.failed`。
- replay 幂等。

### 链路 C: Feature Plan 到 Lane Graph

- 产出 graph-set。
- per-feature lane DAG 正确。
- ready heads 可并行计算。

### 链路 D: Lane Graph 到 Execution Scheduling

- graph-set ready lanes 可投影到 Stage 0 queue。
- projection 幂等。
- 状态写入通过 state machine。
- worker goal contract 可生成完整 context bundle。

### 链路 E: Dashboard / TUI Visibility

- TUI 能看到 chat / worklist / cards。
- dashboard 能 drill down 到 run health / dead-letter / read model / lane detail。
- 两者均不破坏 workflow 主路径。

### 链路 F: Ray GOD Actor 生命周期

- Ray actor backend 可在可用 Ray 环境中创建、检查状态、关闭。
- 无 Ray 环境时 native GOD/session path 仍可 import 和运行。
- actor crash/restart 或 degraded 状态有明确 evidence。
- actor 通信不绕过 chat/inbox/event/artifact ref 契约。
- actor 内存不作为业务状态权威。

## 阶段 4: 验证命令

至少运行存在的测试文件。不要把不存在的路径当失败；若某测试文件缺失，记录为 missing-test
并判断是否需要新增。推荐先构造存在性安全的测试列表:

```bash
tests=()
for pattern in \
  'tests/xmuse/test_shared_contract_fixtures_contract.py' \
  'tests/xmuse/test_parallel_contract_fixtures.py' \
  'tests/xmuse/test_textual_read_layer.py' \
  'tests/xmuse/test_chat_envelopes.py' \
  'tests/xmuse/test_blueprint_execution*.py' \
  'tests/xmuse/test_feature_plan*.py' \
  'tests/xmuse/test_feature_graph_builder.py' \
  'tests/xmuse/test_feature_graph_projection.py' \
  'tests/xmuse/test_platform_runner.py' \
  'tests/xmuse/test_runner_supervisor.py' \
  'tests/xmuse/test_platform_orchestrator.py' \
  'tests/xmuse/test_worker_goal_contract.py' \
  'tests/xmuse/test_provider*.py' \
  'tests/xmuse/test_dashboard_health.py' \
  'tests/xmuse/test_ray*.py' \
  'tests/xmuse/test_langgraph*.py'
do
  matches=( $pattern )
  for match in "${matches[@]}"; do
    [ -e "$match" ] && tests+=( "$match" )
  done
done
uv run pytest "${tests[@]}" -q
```

并运行:

```bash
uv run ruff check <touched files>
git diff --check
```

若运行 runtime smoke:

- 只在所有 focused tests 通过后执行。
- 明确启动命令。
- 只做必要 smoke。
- smoke 后关闭进程。
- 不留下 stale runtime 状态。

## 阶段 5: 文档与交接

更新:

```text
xmuse/HANDOFF.md
xmuse/CODEX_GOAL_HANDOFF.md
docs/xmuse/ 中必要架构文档
```

必须说明:

- 当前真实架构。
- GOD 群聊层如何工作。
- Ray actor backend 是否为主路径或 adapter path。
- `blueprint -> feature -> lane graph -> execution scheduling` 主路径。
- coordinator / harness 如何约束 worker。
- dashboard / TUI 分工。
- `feature_lanes.json` 当前地位。
- 如何验证。
- 剩余缺口。

## 完成条件

只有同时满足以下条件才可 complete:

1. S0-S8 全部被 Outer GOD 复核；ready flag 可以来自原 session，也可以来自 Outer GOD 验收后写入的 `outer_god_verified` 替代 flag。
2. 所有关键 focused tests 通过。
3. 已修复或明确隔离非生产级实现。
4. 端到端链路 A-F 有真实代码或 fake integration 覆盖。
5. Ray / LangGraph / native path 边界被测试保护。
6. dashboard / TUI / workflow / runner 分层清楚，无反向驱动。
7. 文档更新完成。
8. 写入最终 flag:

```text
/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.integration.ready.json
```

## 最终汇报

最终汇报必须包含:

1. S0-S8 状态表。
2. 实际修复内容。
3. 端到端链路验收结果。
4. 测试命令与结果。
5. 是否启动 runtime，是否已关闭。
6. 剩余风险。
7. 当前 xmuse 离最终愿景还差什么。
