# Codex / outer GOD 交接文档

更新日期: 2026-06-03 HKT
仓库: `/home/iiyatu/projects/python/memoryOS`
分支: `feat/ray-gods-chat-minimal`

## 当前 goal

本轮 goal 是 Outer GOD 生产级统合: 复核 S0-S8 并行 session 产物，按
`docs/xmuse/archive/2026-06-roadmaps-and-audits/outer-god-integration-goal.md` 验收 Stage-1 闭环，并继续推进代码结构治理。
当前已写入 `xmuse/work/parallel_session_flags/S0.integration.ready.json`，focused gate
和全量测试均已通过；最新一次 focused gate 为 `422 passed, 1 warning`，全量测试为
`3228 passed, 1 skipped, 9 warnings in 1008.69s`，orchestrator lane-flow 平台 gate 为
`256 passed`。后续结构治理又完成 dashboard details、chat store、takeover action refs
拆分；对应 focused gates 分别为 `148 passed, 7 warnings`、`64 passed`、`96 passed`。
2026-06-02 已清理 live `xmuse/feature_lanes.json` 残留 lanes，当前 lanes=0；旧 66 条
投影归档到 `xmuse/history/cleaned_feature_lanes/`。同日最小用户愿景闭环 smoke 通过:
chat conversation -> feature plan -> graph-set -> projection -> TUI worklist，
`runtime_backend=ray`，`langgraph_backend=langgraph`，Ray adapter shadow dispatch 成功。
随后已修复 live `RayGodActor` lifecycle smoke: 根因是 Ray worker packaged env 未安装
`ray` 默认依赖，以及 actor lifecycle 代码不可直接单测。`ray[default]` 已进入默认项目依赖，
`RayGodActor` 已拆出可测试 core，live smoke 现在能启动子进程、写 chat message、关闭后
确认不再 alive。
注意: 代码质量治理已把当前 tracked 生产 Python 主路径大文件压出 1000+ 清单；
剩余 1000+ 项是前端 API 文档和 work 区生成脚本，是否继续处理需按文档/脚本属性单独判断。

当前不运行 xmuse 自治链。除非用户明确要求，不启动 `platform_runner.py`、
`mcp_server.py`、`chat_api.py` 或 `dashboard_api.py`。

2026-06-02 文件层分离继续推进:

- `src/memoryos_lite/**` 不再直接 import `xmuse_core` 或 `xmuse`。
- `xmuse_core.self_evolution.recovery` 是 xmuse-owned recovery primitive；
  V8 后不再 import `memoryos_lite.recovery`。
- `XMUSE_ROOT`/`default_xmuse_root` 已覆盖主要 xmuse 入口、legacy master loop 默认
  runtime 文件、auto discovery 去重、runner supervisor、self-evolution checkpoint/
  runner 和 skill context 默认目录。
- MemoryOS 根 `pyproject.toml` 当前只导出 `memoryos` / `memoryos-lite` scripts；
  不再导出 `xmuse-*` scripts。`memoryos-lite` wheel 不包含 `xmuse/**` 或
  `xmuse_core/**`，因此 xmuse console scripts 必须等独立 xmuse package metadata
  接管。
- root-level `tests/test_xmuse_*.py` 已清零；当前 xmuse 测试统一位于
  `tests/xmuse/`，共 167 个 test 文件。
- `tests/xmuse/test_tui_navigation.py` 已完成迁移；此前 Textual pilot 超时通过
  隔离 fixture runtime root 并 mock adapter/network refresh 路径解决。
- 已新增 standalone xmuse export contract:
  `docs/xmuse/split-export-manifest.json` 定义复制根和 runtime-state 排除模式，
  `docs/xmuse/xmuse-package.pyproject.toml` 定义独立 xmuse package metadata，
  `scripts/export_xmuse.py` 是可重复导出工具。
  当前 combined repo 仍刻意不创建 `xmuse/__init__.py`，以保留 `xmuse/` 作为
  runtime/application namespace 的旧边界；独立 wheel 由 hatchling 显式 packages
  配置打包 `xmuse/**` 和 `src/xmuse_core/**`。
- V8 后独立 xmuse repo 已位于 `/home/iiyatu/projects/python/xmuse`。
  `pyproject.toml`、`uv.lock`、wheel `METADATA` 和 sdist `PKG-INFO` 不再含
  `memoryos-lite` 或本地 `../memoryOS` dependency。export smoke 应以 xmuse repo
  作为 `--repo-root`，不再以 MemoryOS repo 作为 source。
- 最新文件层分离 gate:
  `uv run pytest tests/memoryos/test_xmuse_boundaries.py tests/xmuse -q`
  -> `2194 passed, 9 warnings in 177.85s`。

## 当前方向

```text
GOD 群聊层 + Textual TUI
-> mission blueprint
-> feature plan
-> per-feature lane graph / graph-set
-> 并行 worker/review/rework/takeover
-> compact cards / read models
-> dashboard drill-down
```

Ray Core 和 LangGraph 的定位:

- Ray Core: 当前是默认 runtime intent/read-model backend；`RayGodActor` live lifecycle
  smoke 已通过，但 actor 内存仍不能作为 durable state 权威。
- LangGraph: blueprint -> feature -> lane graph -> execution 的优先 workflow backend；
  仍不能直接写 lane status。
- 二者都不能直接拥有 xmuse 业务状态；权威状态仍在 durable store/artifact 中。

## 必读文档

| 路径 | 用途 |
|---|---|
| `docs/xmuse/README.md` | 当前 xmuse 文档入口 |
| `docs/xmuse/解耦开发协议.md` | 四层解耦和事件/artifact 契约 |
| `docs/xmuse/parallel-development-runbook.md` | 多 Codex session 并行开发分工与批次 |
| `docs/xmuse/code-quality-and-archive-policy.md` | 代码复用/重写/隔离和质量规则 |
| `docs/xmuse/session-prompts/` | S0-S8 session 初始化 prompt |
| `xmuse/HANDOFF.md` | 项目交接和当前事实 |
| `xmuse/FRONTEND_API.md` | TUI/前端 API 摘要 |
| `xmuse/FRONTEND_CONTEXT.md` | 前端/TUI 背景 |

历史 spec/plan 保留在 `docs/superpowers/`，不要为了“清爽”移动仍被测试或 graph
引用的路径。

## 清理约束

已归档:

```text
xmuse/history/cleanup_20260601T163850Z/
```

该目录包含旧 browser frontend、根目录运行态输出、planning sqlite/state 快照和 demo
脚本。`xmuse/history/` 被忽略，归档用于本机追溯，不作为提交内容。

保留:

- `xmuse/tui/`: 当前前端方向。
- `src/xmuse_core/agents/ray_god_actor.py`: Ray actor backend，live lifecycle smoke 已通过。
- `docs/superpowers/`: 历史文档和测试引用。

## 后续开发规范

1. 先以 `docs/xmuse/解耦开发协议.md` 稳定跨层契约。
2. 若要开多个 Codex session，先按 `docs/xmuse/parallel-development-runbook.md`
   启动 S0，再启动 Batch 1。
3. 所有 session 必须遵守 `docs/xmuse/code-quality-and-archive-policy.md`。
4. GOD 群聊/TUI、workflow、契约层、dashboard 可以并行开发。
5. TUI 不直接写 runner 状态。
6. workflow 不绕过 graph-set artifact 直接手写 flat lanes。
7. dashboard 不作为主流程驱动器。
8. `feature_lanes.json` 当前仍是 Stage 0 执行事实源；不要直接手改。
9. 新代码按模块落地，不把 Ray/LangGraph/TUI 逻辑堆进单个大文件。
10. 能复用既有代码资源就复用；评估不适合复用的冲突实现移到 history/legacy/archive。

## 结构治理进度

已完成:

- `src/xmuse_core/observability.py` 成为 xmuse 自有观测适配层。
- `tests/xmuse/test_package_boundaries.py` 约束 `xmuse_core` 不直接 import
  `memoryos_lite`。
- `tests/memoryos/test_xmuse_boundaries.py` 约束 `memoryos_lite` 不反向 import
  `xmuse_core` 或 `xmuse`。
- `src/xmuse_core/platform/dashboard_read_models.py` 承载 dashboard read-only
  dead-letter/read-model status 逻辑。
- `src/xmuse_core/platform/dashboard_graph_state.py` 承载 dashboard lane-graph
  derived-state 计算，`xmuse/dashboard_api.py` 不再内联这段 lineage/status 聚合逻辑。
- `src/xmuse_core/platform/coordinator_incidents.py` 承载 coordinator incident 汇总。
- `src/xmuse_core/platform/run_processes.py` 承载 runtime process discovery /
  process inventory / warning evidence，`run_health.py` 保留兼容导出但不再内联进程扫描。
- `src/xmuse_core/chat/lane_scope.py` 承载 conversation-scoped lane 解析，`PeerChatService`
  复用该模块而不是在服务类里内联 graph/feature scope 规则。
- `src/xmuse_core/platform/review_aggregation.py` 承载 `RunTerminalAggregator`，
  `review_plane.py` 保留兼容导出但不再内联 run-level terminal aggregation。
- `src/xmuse_core/platform/review_merge_guards.py` 承载
  `IncompleteLineageTerminationError` / `LineageMergeReport`，`review_plane.py`
  保留兼容导出但不再内联这些 merge guard 类型。
- `src/xmuse_core/structuring/review_models.py` 承载 review/evidence Pydantic
  模型，`structuring.models` 保留兼容导出但不再内联这些模型。
- `src/xmuse_core/structuring/takeover_models.py` 承载 Review GOD takeover
  context/evidence/decision Pydantic 模型，`structuring.models` 保留兼容导出但不再
  内联这些模型。
- `src/xmuse_core/platform/provider_read_contracts.py` 承载 provider inventory /
  provider selection-record read contract，`read_contracts.py` 保留兼容导出。
- `src/xmuse_core/platform/read_tool_inventory.py` 承载 READ_CONTRACT_TOOL_SCHEMAS
  和 tool inventory 分类逻辑，`read_contracts.py` 保留兼容导出。
- `src/xmuse_core/platform/read_contracts.py` 已从 1324 行降到 996 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/structuring/planning_event_models.py` 承载 `PlanningEventStatus`
  和 `PlanningEvent`，`structuring.models` 保留兼容导出。
- `src/xmuse_core/structuring/models.py` 已从 1017 行降到 944 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/platform/execution/persistent_review_context.py` 承载 persistent
  Review GOD prompt/context/session-id helper。
- `src/xmuse_core/platform/execution/persistent_review_delivery.py` 承载 persistent
  Review GOD receive/apply/verdict/degraded delivery 逻辑。
- `src/xmuse_core/platform/execution/persistent_review_session.py` 承载 persistent
  Review GOD session Protocol 和 configured peer attempt contract。
- `src/xmuse_core/platform/execution/review_god.py` 已从 1308 行降到 997 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/platform/mcp_responses.py` 承载 MCP content / JSON-RPC response
  helper，`xmuse/mcp_server.py` 保留兼容别名。
- `src/xmuse_core/platform/mcp_search.py` 承载 MCP search text flattening / query
  terms helper，`xmuse/mcp_server.py` 保留兼容别名。
- `xmuse/mcp_server.py` 已从 1024 行降到 992 行，退出当前 1000+ 行巨大文件清单。
- `src/xmuse_core/chat/api_models.py` 承载 chat REST request Pydantic models，
  `xmuse/chat_api.py` 保留兼容导出。
- `xmuse/chat_api.py` 已从 1122 行降到 970 行，退出当前 1000+ 行巨大文件清单。
- `src/xmuse_core/platform/coordinator_control.py` 承载 coordinator control /
  incident summary / blueprint automation coordination，`xmuse/platform_runner.py`
  保留兼容导入。
- `xmuse/platform_runner.py` 已从 1189 行降到 987 行，退出当前 1000+ 行巨大文件清单。
- `src/xmuse_core/platform/review_evidence_bundle.py` 承载 review evidence bundle
  assembly，`ReviewPlaneController` 保留兼容方法。
- `src/xmuse_core/platform/review_plane.py` 已从 1295 行降到 688 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/chat/peer_cards.py` 承载 peer chat card assembly。
- `src/xmuse_core/chat/peer_proposals.py` / `src/xmuse_core/chat/peer_types.py`
  承载 proposal emission 与 peer chat result/error 类型；`peer_service.py` 保留
  兼容导出。
- `src/xmuse_core/chat/peer_service.py` 已从 1835 行降到 991 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/platform/orchestrator_lane_flow.py` 承载 orchestrator lane
  execution/review flow；`PlatformOrchestrator` 保留兼容 wrappers。
- `src/xmuse_core/platform/orchestrator.py` 已降到 831 行，退出当前 1000+ 行巨大文件清单。
- orchestrator 抽取后已补回旧兼容 patch surface:
  `xmuse_core.platform.orchestrator.WORKTREE_BASE`、`_git_output`、`execution_executor`。
- `src/xmuse_core/platform/dashboard_graph_authority.py` 承载 dashboard graph
  authority / lineage / graph-set helper。
- `src/xmuse_core/platform/dashboard_audit_details.py` 承载 dashboard audit /
  error / state-history read helper。
- `src/xmuse_core/platform/dashboard_details.py` 已从 1549 行降到 985 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/chat/store.py` 已从 1006 行降到 997 行，退出当前
  1000+ 行巨大文件清单。
- `src/xmuse_core/platform/takeover_action_refs.py` 承载 takeover ref/evidence/hash
  helper。
- `src/xmuse_core/platform/takeover_actions.py` 已从 1312 行降到 981 行，退出当前
  1000+ 行巨大文件清单。
- `SelfEvolutionController` public 方法保持小 facade delegate，复杂流程下沉到私有
  helper/runtime 模块。
- `src/xmuse_core/structuring/graph_validation.py` 承载 lane graph
  duplicate/dependency/DAG 校验；后续 review/planning/takeover 模型抽取后，
  `structuring/models.py` 已降到 944 行。
- `LaneGraph` 模型允许 legacy projection 依赖已完成的外部 Stage-0 lane；planner 与
  graph-set projection 仍保留 missing-dependency gate。
- `blocked_for_input` 纳入 lane state normalizer/validator，并修复 stale
  clarification_request 不应阻塞已 merged lane 的聚合边界。
- MemoryOS Lite observability 修复了 `create_session()` ContextVar 泄漏，低预算
  explicit paging 能产生 page、trace 和 embedding metric。
- self-evolution runtime 的 evidence bundle 组装已委托
  `src/xmuse_core/self_evolution/evidence/aggregator.py`，runtime 侧保留兼容 facade。
- `src/xmuse_core/self_evolution/_controller_runtime.py` 已从 1502 行降到 946 行，
  退出当前 1000+ 行巨大文件清单。
- Xmuse error-knowledge maintainer 的 contract/io/source-ref、cluster/draft rendering、
  handoff payload builders 已抽到 `src/xmuse_core/knowledge/`。
- `xmuse/xmuse_error_knowledge.py` 已从 1452 行降到 990 行，退出当前 1000+
  行巨大文件清单。
- legacy `master_loop.py` 的 lane/worktree projection helper、full quality gate helper、
  task/review prompt helper、git/worktree helper、stale-lane state helper、CLI parser 已抽到
  `src/xmuse_core/platform/master_loop_*` 模块。
- `xmuse/master_loop.py` 已从 1490 行降到 990 行，退出当前 1000+ 行巨大文件清单。
- Hermes hardening 的 JSON artifact、active job、eval run、phase gate、merge gate、
  feature-lane summary/status helper 已抽到 `src/xmuse_core/hermes/`。
- `xmuse/hermes_hardening.py` 已从 2773 行降到 856 行，退出当前 1000+ 行巨大文件清单。

仍需继续拆分:

```text
xmuse/FRONTEND_API.md
xmuse/work/generate_runtime_first_graph_set.py
```

剩余大文件中，`xmuse/FRONTEND_API.md` 是文档，`xmuse/work/generate_runtime_first_graph_set.py`
属于 work 区生成脚本，是否保留在主树需要单独判断。后续拆分原则: 先抽纯函数/读模型/
route registration，再抽 coordinator workflow service，最后处理状态模型拆分；避免一次性
重写入口导致行为回归。

## 验证建议

结构治理/统合类变更:

```bash
git status --short
uv run pytest tests/memoryos/test_xmuse_boundaries.py tests/xmuse/test_package_boundaries.py -q
uv run pytest tests/xmuse/test_dashboard_read_models.py tests/xmuse/test_coordinator_incidents.py -q
uv run ruff check <touched python files>
git diff --check
```

本轮最终验证:

```text
uv run pytest <S0-S8 focused integration set> -q
-> latest focused gate: 422 passed, 1 warning

uv run pytest tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_platform_runner.py -q
-> post-orchestrator-lane-flow extraction platform gate: 256 passed

uv run ruff check src/xmuse_core/platform/orchestrator.py src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_orchestrator_lane_flow_module.py
-> All checks passed

uv run pytest tests/xmuse/test_dashboard_details_module.py tests/xmuse/test_dashboard_api.py tests/xmuse/test_dashboard_health.py tests/xmuse/test_dashboard_graph_state.py tests/xmuse/test_dashboard_read_models.py -q
-> post-dashboard-details extraction: 148 passed, 7 warnings

uv run pytest tests/xmuse/test_chat_driver.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_peer_chat_mentions.py tests/xmuse/test_peer_chat_turn_budget.py tests/xmuse/test_chat_api.py tests/test_fe_vision_layer1_api.py -q
-> post-chat-store cleanup: 64 passed

uv run pytest tests/xmuse/test_takeover_actions.py tests/xmuse/test_takeover_contracts.py tests/xmuse/test_platform_mcp_tools.py tests/xmuse/test_execution_cards.py -q
-> post-takeover-action-refs extraction: 96 passed

uv run pytest tests -q
-> 3228 passed, 1 skipped, 9 warnings in 1008.69s

uv run pytest tests/xmuse/test_lane_graph_validation.py tests/xmuse/test_lane_graph_planner.py tests/xmuse/test_feature_graph_projection.py -q
-> 24 passed

uv run pytest tests/xmuse/test_dashboard_graph_state.py -q
-> 2 passed

uv run pytest tests/xmuse/test_dashboard_api.py::test_lane_graphs_each_entry_includes_derived_state tests/xmuse/test_dashboard_api.py::test_lane_graph_detail_returns_graph_with_derived_state tests/xmuse/test_dashboard_api.py::test_lane_graph_detail_blocked_for_input_reflected_in_derived_state -q
-> 3 passed

uv run pytest tests/xmuse/test_dashboard_api.py tests/xmuse/test_dashboard_health.py tests/xmuse/test_dashboard_read_models.py -q
-> 143 passed, 7 warnings

uv run pytest tests/xmuse/test_run_processes.py -q
-> 2 passed

uv run pytest tests/xmuse/test_run_health.py -q
-> 23 passed

uv run pytest tests/xmuse/test_chat_lane_scope.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_dashboard_health.py::test_run_health_workspace_filter_ignores_foreign_and_ambiguous_graph_scopes tests/xmuse/test_dashboard_health.py::test_run_health_conversation_filter_ignores_workspace_id_collision -q
-> 13 passed

uv run pytest tests/xmuse/test_review_aggregation_module.py tests/xmuse/test_run_terminal_aggregation.py tests/xmuse/test_review_plane.py tests/test_review_plane_merge_guards.py tests/test_review_plane_merge_safety.py -q
-> 85 passed

uv run pytest tests/xmuse/test_review_merge_guards_module.py tests/test_review_plane_merge_guards.py tests/test_review_plane_merge_safety.py tests/xmuse/test_review_plane_merge_safety.py -q
-> 71 passed

uv run pytest tests/xmuse/test_structuring_review_models.py tests/test_verdict_store_consistency.py tests/test_verdict_store_atomic.py tests/xmuse/test_evidence_bundle_assembly.py tests/xmuse/test_review_plane.py tests/xmuse/test_run_terminal_aggregation.py -q
-> 170 passed

uv run pytest tests/xmuse/test_dashboard_health.py tests/xmuse/test_platform_runner.py::test_health_once_reports_native_persistent_runtime_without_ray tests/xmuse/test_platform_runner.py::test_health_once_uses_shared_read_model_process_semantics tests/xmuse/test_platform_runner.py::test_health_once_reads_projection_and_uses_live_pid_evidence -q
-> 14 passed

uv run pytest <S0-S8 focused integration set> -q
-> post-structuring-review-models extraction: 465 passed, 1 warning

uv run pytest tests/xmuse/test_structuring_takeover_models.py tests/xmuse/test_takeover_contracts.py tests/xmuse/test_takeover_actions.py tests/xmuse/test_platform_mcp_tools.py tests/xmuse/test_execution_cards.py -q
-> post-takeover-models expanded gate: 97 passed

uv run pytest <S0-S8 focused integration set> -q
-> post-takeover-models extraction: 467 passed, 1 warning

uv run pytest tests/xmuse/test_read_tool_inventory_module.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_platform_mcp_tools.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_adapters.py tests/xmuse/test_package_boundaries.py -q
-> post-read-contracts extraction focused gate: 86 passed

uv run pytest <S0-S8 focused integration set> -q
-> post-read-contracts extraction: 472 passed, 1 warning

uv run pytest tests/xmuse/test_structuring_planning_event_models.py tests/xmuse/test_planning_event_store.py tests/xmuse/test_blueprint_execution_service.py -q
-> post-planning-event-models extraction focused gate: 20 passed, 1 warning

uv run pytest <S0-S8 focused integration set> -q
-> post-planning-event-models extraction: 475 passed, 1 warning

uv run pytest tests/xmuse/test_persistent_review_session_contracts.py tests/xmuse/test_persistent_review_delivery_module.py tests/xmuse/test_persistent_review_context_module.py tests/xmuse/test_review_plane_orchestrator_integration.py -q
-> post-persistent-review-extraction focused gate: 53 passed

uv run pytest tests/xmuse/test_platform_runner.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_review_plane_orchestrator_integration.py -q -k 'persistent_review or review_god or platform_runner_rejects_default_review_peer or persistent_review_god'
-> post-persistent-review-extraction platform gate: 54 passed, 202 deselected

uv run pytest <S0-S8 focused integration set> -q
-> post-persistent-review-extraction: 485 passed, 1 warning

uv run pytest tests/xmuse/test_mcp_search_module.py tests/xmuse/test_mcp_responses_module.py tests/xmuse/test_platform_mcp_tools.py -q
-> post-mcp-server-extraction focused gate: 47 passed

uv run pytest <S0-S8 focused integration set> -q
-> post-mcp-server-extraction: 491 passed, 1 warning

uv run pytest tests/xmuse/test_chat_api_models_module.py tests/xmuse/test_chat_api.py tests/test_fe_vision_layer1_api.py -q
-> post-chat-api-models-extraction focused gate: 38 passed

uv run pytest <S0-S8 focused integration set> -q
-> post-chat-api-models-extraction: 494 passed, 1 warning

uv run ruff check <changed python files>
-> All checks passed

git diff --check
-> passed
```

若后续触碰代码，再按 touched modules 运行对应 pytest。不要声称未运行的测试已通过。
