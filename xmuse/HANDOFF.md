# xmuse 项目交接文档

更新日期: 2026-06-03 HKT
仓库路径: `/home/iiyatu/projects/python/memoryOS`
当前分支: `feat/ray-gods-chat-minimal`
环境: WSL2/Linux。涉及 Codex/xmuse 历史时只看 WSL 侧 `xmuse/history/`。

## 当前状态

xmuse 是 MemoryOS 仓库内演进的自主软件开发平台原型。当前方向已经从旧的
provider/platform/autonomous-recovery 运行目标，转向更直接的最终形态:

```text
Ray 管理的持久化 GOD 群聊
-> 人类/GOD 对等讨论并产出 mission blueprint
-> LangGraph 或原生 workflow 拆为 feature 和 lane graph
-> 并行 agentic workers 执行
-> review / rework / merge / takeover
-> Textual TUI 展示群聊、compact cards 和 worklist
-> dashboard 作为灰盒 drill-down
```

当前运行态应视为停止状态。不要基于旧文档中的 `runner active`、`max-concurrent
96`、C-class live queue 等描述继续操作；那些是 2026-06-01 的历史运行快照。

Outer GOD 统合验收已写入:

```text
xmuse/work/parallel_session_flags/S0.integration.ready.json
```

当前验证状态:

```text
2026-06-02 minimal user-vision closed-loop smoke: passed
  chat conversation -> feature plan -> graph-set -> projection -> TUI worklist
  runtime_backend=ray, langgraph_backend=langgraph, ray_adapter=fake-ray shadow dispatch
2026-06-02 live RayGodActor lifecycle smoke: passed after hardening
  root cause was missing default `ray[default]` project dependency in Ray
  packaged worker env plus untestable actor lifecycle code. RayGodActor now
  starts a child process, posts a chat message, and shuts down cleanly.
2026-06-02 feature_lanes.json cleanup: live projection lanes=0
  archived previous 66 lanes under xmuse/history/cleaned_feature_lanes/
current focused Ray/LangGraph/projection/TUI gate: 34 passed
current Ray/LangGraph adapter gate: 16 passed
S0-S8 focused integration gate: 422 passed, 1 warning
full tests: 3228 passed, 1 skipped, 9 warnings in 1008.69s
post-orchestrator-lane-flow platform gate: 256 passed
post-orchestrator-lane-flow ruff: All checks passed
post-dashboard-details extraction gate: 148 passed, 7 warnings
post-chat-store cleanup gate: 64 passed
post-takeover-action-refs extraction gate: 96 passed
post-chat-api-models-extraction focused gate: 38 passed
post-mcp-server-extraction focused gate: 47 passed
post-persistent-review-extraction focused gate: 53 passed
post-planning-event-models extraction focused gate: 20 passed, 1 warning
post-read-contracts extraction focused gate: 86 passed
post-takeover-models expanded gate: 97 passed
memoryos/xmuse file separation focused gate: tests/xmuse + memoryos boundary passed
memoryos/xmuse split test migration: root-level tests/test_xmuse_*.py = 0,
  tests/xmuse test files = 167
standalone xmuse export smoke: built xmuse-0.1.0 wheel from manifest copy,
  xmuse/chat_api.py packaged, xmuse_core/__init__.py packaged,
  runtime_state_files=0
actual sibling export: /home/iiyatu/projects/python/xmuse built successfully,
  runtime_state_files=0
ruff changed python files: All checks passed
git diff --check: passed
xmuse runtime processes: none detected
```

## 当前权威入口

| 路径 | 用途 |
|---|---|
| `docs/xmuse/README.md` | 当前 xmuse 文档入口和分层索引 |
| `docs/xmuse/解耦开发协议.md` | GOD 群聊、workflow、契约层、dashboard 的解耦开发协议 |
| `docs/xmuse/parallel-development-runbook.md` | 多 Codex session 并行开发运行手册 |
| `docs/xmuse/code-quality-and-archive-policy.md` | 代码复用、重写、归档和测试质量规则 |
| `docs/xmuse/memoryos-file-separation.md` | xmuse / MemoryOS 文件、依赖和运行根分离规则 |
| `docs/xmuse/session-prompts/` | 各模块 Codex session 初始化 prompt |
| `xmuse/CODEX_GOAL_HANDOFF.md` | 后续 Codex/outer GOD goal 的执行上下文 |
| `xmuse/FRONTEND_API.md` | TUI/前端可消费 API 摘要 |
| `xmuse/FRONTEND_CONTEXT.md` | 前端/TUI 背景和旧 Open Design 说明 |

旧 `docs/superpowers/specs/` 和 `docs/superpowers/plans/` 保留原路径，因为测试、
历史 lane graph 和 handoff 会引用这些文件。它们现在是实现历史，不是唯一的当前
入口。

## 清理状态

已隔离到 `xmuse/history/cleanup_20260601T163850Z/`:

- `xmuse/frontend/`: 旧 browser frontend 和构建产物。
- `logs/`、`read_models/`、`audit_events.json`: 根目录运行态输出。
- `xmuse/planning_events.sqlite3`、`xmuse/planning_runs.sqlite3`、
  `xmuse/state_history.json`: 运行态数据库/快照。
- `scripts/gods_chat_minimal.py`、`scripts/ray_gods_chat_demo.py`: demo 脚本。

保留在主库:

- `xmuse/tui/`: 当前 Textual TUI 方向。
- `src/xmuse_core/agents/ray_god_actor.py`: Ray GOD actor 原型，仍需生产化审查。
- `docs/superpowers/`: 历史文档，保留路径以免破坏引用。

## 当前代码分层事实

### 结构独立与代码质量状态

本轮 Outer GOD 统合后，`src/xmuse_core` 与 `src/memoryos_lite` 的直接代码依赖正在
收束:

- `src/memoryos_lite/**` 不应 import `xmuse_core` 或 `xmuse`；边界测试在
  `tests/memoryos/test_xmuse_boundaries.py`。
- recovery primitive 已在 V8 回收到
  `src/xmuse_core/self_evolution/recovery.py`；xmuse 不再通过该模块 import
  `memoryos_lite.recovery`。
- `XMUSE_ROOT` 已成为 xmuse 入口的 runtime root override。`chat_api`、
  `dashboard_api`、`mcp_server`、`platform_runner` 和 `tui` 默认仍兼容当前
  `./xmuse`，但可通过 `XMUSE_ROOT=/path/to/xmuse-runtime` 脱离 MemoryOS 仓库根。
- legacy master loop 默认 lanes/config/session/log 路径、auto discovery 去重路径、
  runner supervisor runtime 文件、self-evolution checkpoint/runner 和 skill context
  默认路径也已接入 `XMUSE_ROOT` 或 `default_xmuse_root`。
- xmuse 专属依赖 `textual` 已从 MemoryOS 主依赖移到 `xmuse` optional extra；
  `ray` 保留原 extra，同时也包含在 `xmuse` extra 中。
- MemoryOS 根 `pyproject.toml` 当前只导出 `memoryos` / `memoryos-lite` scripts；
  不再导出 `xmuse-*` scripts。原因是 `memoryos-lite` wheel 不包含 `xmuse/**` 或
  `xmuse_core/**`，在根包导出 xmuse console scripts 会生成不可用入口。
- 已新增 standalone xmuse export contract:
  `docs/xmuse/split-export-manifest.json` 定义复制根和 runtime-state 排除模式，
  `docs/xmuse/xmuse-package.pyproject.toml` 定义独立 xmuse package metadata，
  `scripts/export_xmuse.py` 是可重复导出工具。
  当前 combined repo 仍刻意不创建 `xmuse/__init__.py`，以保留 `xmuse/` 作为
  runtime/application namespace 的旧边界；独立 wheel 由 hatchling 显式 packages
  配置打包 `xmuse/**` 和 `src/xmuse_core/**`。export smoke 已验证该工具能导出
  `/tmp/xmuse-export-tool-check`、排除 152 个 runtime/state 项并 build wheel；actual sibling focused tests 15 passed，且不把
  runtime JSON/DB/history/work/lane_graphs 打进 wheel。
- 当前已生成实际 sibling export `/home/iiyatu/projects/python/xmuse`，并验证
  `uv build --wheel --out-dir /home/iiyatu/projects/python/xmuse/dist /home/iiyatu/projects/python/xmuse`
  成功；该 wheel 不含 runtime JSON/DB/history/work/lane_graphs。
- xmuse package boundary 测试已移到 `tests/xmuse/test_package_boundaries.py`；
  当前 root-level `tests/test_xmuse_*.py` 已清零，`tests/xmuse/` 有 167 个 xmuse
  test 文件。后续新增 xmuse 测试必须继续放在 `tests/xmuse/`。
- `tests/xmuse/test_tui_navigation.py` 已完成迁移；此前 Textual pilot 超时通过
  隔离 fixture runtime root 并 mock adapter/network refresh 路径解决。
- 新增 `src/xmuse_core/observability.py`，xmuse 平台代码不再直接 import
  `memoryos_lite.observability`。
- `tests/xmuse/test_package_boundaries.py` 约束 `xmuse_core` 的
  `memoryos_lite` 依赖只能通过明确适配层进入。
- dashboard read-only 模型已从 `xmuse/dashboard_api.py` 抽到
  `src/xmuse_core/platform/dashboard_read_models.py`。
- dashboard lane graph derived-state 计算已抽到
  `src/xmuse_core/platform/dashboard_graph_state.py`。
- coordinator incident 汇总已从 `src/xmuse_core/platform/run_health.py` 抽到
  `src/xmuse_core/platform/coordinator_incidents.py`。
- runtime process discovery / process inventory / warning evidence 已从
  `src/xmuse_core/platform/run_health.py` 抽到
  `src/xmuse_core/platform/run_processes.py`；`run_health.py` 保留旧 API 兼容导出。
- conversation-scoped lane 解析已从 `PeerChatService` 抽到
  `src/xmuse_core/chat/lane_scope.py`，供 chat/dashboard/TUI scope 语义复用。
- `RunTerminalAggregator` 已从 `src/xmuse_core/platform/review_plane.py` 抽到
  `src/xmuse_core/platform/review_aggregation.py`；`review_plane.py` 保留兼容导出。
- review merge guard 类型已从 `src/xmuse_core/platform/review_plane.py` 抽到
  `src/xmuse_core/platform/review_merge_guards.py`；`review_plane.py` 保留兼容导出。
- `SelfEvolutionController` public 方法已保持 facade delegate，复杂逻辑下沉到私有
  helper/runtime。
- lane graph duplicate/dependency/DAG 校验已抽到
  `src/xmuse_core/structuring/graph_validation.py`，降低 `structuring/models.py`
  的职责和体积。
- review/evidence Pydantic 模型已抽到
  `src/xmuse_core/structuring/review_models.py`，`structuring.models` 保留兼容导出。
- Review GOD takeover context/evidence/decision Pydantic 模型已抽到
  `src/xmuse_core/structuring/takeover_models.py`，`structuring.models` 保留兼容导出。
- provider inventory / provider selection-record read contract 已抽到
  `src/xmuse_core/platform/provider_read_contracts.py`，`read_contracts.py` 保留兼容导出。
- READ_CONTRACT_TOOL_SCHEMAS 和 tool inventory 分类逻辑已抽到
  `src/xmuse_core/platform/read_tool_inventory.py`，`read_contracts.py` 保留兼容导出。
- `src/xmuse_core/platform/read_contracts.py` 已从 1324 行降到 996 行，退出当前
  1000+ 行巨大文件清单。
- `PlanningEventStatus` / `PlanningEvent` 已抽到
  `src/xmuse_core/structuring/planning_event_models.py`，`structuring.models` 保留兼容导出。
- `src/xmuse_core/structuring/models.py` 已从 1017 行降到 944 行，退出当前
  1000+ 行巨大文件清单。
- persistent Review GOD prompt/context/session-id helper 已抽到
  `src/xmuse_core/platform/execution/persistent_review_context.py`。
- persistent Review GOD receive/apply/verdict/degraded delivery 逻辑已抽到
  `src/xmuse_core/platform/execution/persistent_review_delivery.py`。
- persistent Review GOD session Protocol 和 configured peer attempt contract 已抽到
  `src/xmuse_core/platform/execution/persistent_review_session.py`。
- `src/xmuse_core/platform/execution/review_god.py` 已从 1308 行降到 997 行，退出当前
  1000+ 行巨大文件清单。
- MCP content / JSON-RPC response helper 已抽到
  `src/xmuse_core/platform/mcp_responses.py`，`xmuse/mcp_server.py` 保留兼容别名。
- MCP search text flattening / query terms helper 已抽到
  `src/xmuse_core/platform/mcp_search.py`，`xmuse/mcp_server.py` 保留兼容别名。
- `xmuse/mcp_server.py` 已从 1024 行降到 992 行，退出当前 1000+ 行巨大文件清单。
- chat REST request Pydantic models 已抽到 `src/xmuse_core/chat/api_models.py`，
  `xmuse/chat_api.py` 保留兼容导出。
- `xmuse/chat_api.py` 已从 1122 行降到 970 行，退出当前 1000+ 行巨大文件清单。
- coordinator control / incident summary / blueprint automation coordination 已抽到
  `src/xmuse_core/platform/coordinator_control.py`，`xmuse/platform_runner.py` 保留
  兼容导入。
- `xmuse/platform_runner.py` 已从 1189 行降到 987 行，退出当前 1000+ 行巨大文件清单。
- review evidence bundle assembly 已抽到
  `src/xmuse_core/platform/review_evidence_bundle.py`，`ReviewPlaneController` 保留
  兼容方法。
- `src/xmuse_core/platform/review_plane.py` 已从 1295 行降到 688 行，退出当前
  1000+ 行巨大文件清单。
- peer chat card assembly 已抽到 `src/xmuse_core/chat/peer_cards.py`。
- peer proposal emission 和 peer chat result/error 类型已抽到
  `src/xmuse_core/chat/peer_proposals.py` / `src/xmuse_core/chat/peer_types.py`，
  `peer_service.py` 保留兼容导出。
- `src/xmuse_core/chat/peer_service.py` 已从 1835 行降到 991 行，退出当前
  1000+ 行巨大文件清单。
- orchestrator lane execution/review flow 已抽到
  `src/xmuse_core/platform/orchestrator_lane_flow.py`，`PlatformOrchestrator` 保留
  兼容 wrappers。
- `src/xmuse_core/platform/orchestrator.py` 已降到 831 行，退出当前 1000+ 行巨大文件清单。
- orchestrator 抽取后已补回旧兼容 patch surface:
  `xmuse_core.platform.orchestrator.WORKTREE_BASE`、`_git_output`、`execution_executor`。
- dashboard graph authority / lineage / graph-set helper 已抽到
  `src/xmuse_core/platform/dashboard_graph_authority.py`，`dashboard_details.py` 保留
  兼容导出。
- dashboard audit / error / state-history read helper 已抽到
  `src/xmuse_core/platform/dashboard_audit_details.py`，`dashboard_details.py` 保留
  兼容导出。
- `src/xmuse_core/platform/dashboard_details.py` 已从 1549 行降到 985 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/chat/store.py` 已从 1006 行降到 997 行，退出当前
  1000+ 行巨大文件清单。
- takeover ref/evidence/hash helper 已抽到
  `src/xmuse_core/platform/takeover_action_refs.py`，`takeover_actions.py` 保留兼容导出。
- `src/xmuse_core/platform/takeover_actions.py` 已从 1312 行降到 981 行，退出当前
  1000+ 行巨大文件清单。
- self-evolution runtime 的 evidence bundle 组装已委托
  `src/xmuse_core/self_evolution/evidence/aggregator.py`，runtime 侧保留兼容 facade。
- `src/xmuse_core/self_evolution/_controller_runtime.py` 已从 1502 行降到 946 行，
  退出当前 1000+ 行巨大文件清单。
- Xmuse error-knowledge maintainer 的 contract/io/source-ref、cluster/draft rendering、
  handoff payload builders 已抽到 `src/xmuse_core/knowledge/`。
- `xmuse/xmuse_error_knowledge.py` 已从 1452 行降到 990 行，退出当前 1000+ 行
  巨大文件清单。
- legacy `master_loop.py` 的 lane/worktree projection helper、full quality gate helper、
  task/review prompt helper、git/worktree helper、stale-lane state helper、CLI parser 已抽到
  `src/xmuse_core/platform/master_loop_*` 模块。
- `xmuse/master_loop.py` 已从 1490 行降到 990 行，退出当前 1000+ 行巨大文件清单。
- Hermes hardening 的 JSON artifact、active job、eval run、phase gate、merge gate、
  feature-lane summary/status helper 已抽到 `src/xmuse_core/hermes/`。
- `xmuse/hermes_hardening.py` 已从 2773 行降到 856 行，退出当前 1000+ 行巨大文件清单。
- `LaneGraph` / projection 边界已区分 legacy 外部依赖和 graph-set 内部 missing
  dependency gate。
- `blocked_for_input` 已进入 lane state normalizer/validator，并修复 dashboard /
  self-evolution 聚合中的 stale clarification_request 边界。
- MemoryOS Lite 修复了 observability ContextVar 泄漏和低预算 explicit paging
  指标/trace 路径。

仍需继续治理的巨大文件:

```text
xmuse/FRONTEND_API.md
xmuse/work/generate_runtime_first_graph_set.py
```

剩余大文件中，`xmuse/FRONTEND_API.md` 是文档，`xmuse/work/generate_runtime_first_graph_set.py`
属于 work 区生成脚本，是否保留在主树需要单独判断。后续拆分原则: 先提取纯 read model、
artifact serialization、route registration、workflow adapter、worker evidence/context
bundle 等低风险边界；不要一次性重写入口文件。

### GOD 群聊层

主要路径:

```text
src/xmuse_core/chat/*
src/xmuse_core/agents/god_session_layer.py
src/xmuse_core/agents/god_session_registry.py
src/xmuse_core/agents/ray_god_actor.py
src/xmuse_core/routing/*
xmuse/chat_api.py
xmuse/mcp_server.py
```

事实:

- `chat.db` 承载 conversation、message、participant、inbox。
- `GodSessionLayer` 是本地 persistent session 旧路径。
- `RayGodActor` 与 `ray_runtime_backend` 仍是 adapter/backend 路径，不是 durable
  state 权威。
- GOD 群聊与 TUI 可以独立推进，但必须通过 message/event/card 对接 workflow。

### blueprint / feature / lane graph workflow

主要路径:

```text
src/xmuse_core/structuring/blueprint_execution/*
src/xmuse_core/structuring/feature_plan_store.py
src/xmuse_core/structuring/projection.py
xmuse/platform_runner.py
```

事实:

- `BlueprintAutomationService` 消费 `blueprint.approved` 并产生 planning run。
- `FeaturePlanningService` 负责 feature plan deliberation。
- feature graph-set / lane graph snapshot 是比 flat projection 更权威的执行图。
- `feature_lanes.json` 仍是 runner 兼容 live queue/syncer，不是权威图。
- `langgraph_adapter` 是 shadow/replay adapter 路径；后续只能作为 workflow backend，
  不能直接拥有状态或写 lane status。

### 层间契约

当前已有雏形:

```text
src/xmuse_core/chat/envelopes.py
src/xmuse_core/chat/execution_cards.py
src/xmuse_core/platform/read_envelopes.py
src/xmuse_core/structuring/planning_event_store.py
```

下一步应优先稳定事件、card、read envelope、artifact ref，而不是让 TUI、dashboard、
workflow 互相读取内部文件。

### Dashboard

主要路径:

```text
xmuse/dashboard_api.py
```

事实:

- dashboard 应是灰盒 drill-down，不是用户主入口。
- 已有 peer-chat、lane graph、feature graph-set、run health、audit/state/lineage
  等读取接口。
- lane graph derived-state 计算已下沉到
  `src/xmuse_core/platform/dashboard_graph_state.py`，dashboard API 只负责路由和响应拼装。
- 新 dashboard 能力应优先保持只读和证据展开。

## 前端/TUI 方向

当前用户前门优先 Textual TUI，而不是 browser frontend。TUI 可以先直接消费本地
store/read envelope，后续逐步收束到稳定 API。

启动参考:

```bash
uv run python -m xmuse.tui
uv run python xmuse/chat_api.py
uv run python xmuse/dashboard_api.py
```

不要依赖 Windows/Open Design 目录。旧 `xmuse/frontend/` 已归档。

## 运行原则

1. 默认不要启动 xmuse runtime；除非用户明确要求。
2. 如果启动，应保持单 runner，不用多个 runner 堆并行。
3. 并行能力应来自 feature graph-set 和 lane DAG，而不是多个互相抢写的进程。
4. Ray actor 内存不是权威状态；崩溃恢复必须靠 durable store。
5. LangGraph 只能编排 workflow，不直接写 lane status。
6. dashboard/TUI 读取 read model/card，不绕过契约写内部状态。

## 多 Codex Session 开发原则

1. 先启动 S0 Integration / Contract Owner，冻结 shared contract。
2. 每个 session 必须读取 `docs/xmuse/parallel-development-runbook.md` 和
   `docs/xmuse/code-quality-and-archive-policy.md`。
3. 每个 session 只允许修改 prompt 中列出的 allowed files。
4. 执行层中心化，由 xmuse coordinator 仲裁状态；subagent 只是受控工具。
5. 能复用既有代码资源就复用；不适合复用的旧实现必须说明原因并隔离。
6. 合并前必须有 focused tests 或明确的验证记录。

## Git 注意事项

- 工作树可能有用户或历史 goal 的脏改动，不要 `git reset --hard`。
- 不要提交运行态产物、日志、数据库、`feature_lanes.json` 的无关变更。
- 78MB 旧 blob 仍在历史里；彻底清理需要 `git filter-repo`，必须由用户单独确认。
