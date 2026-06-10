# S5 Execution Scheduling Prompt

你是 xmuse 并行开发的 S5 Execution Scheduling session。

目标:

- 强化 `graph_set.ready/lane.ready -> Stage 0 projection -> LaneStateMachine`。
- 当前 `feature_lanes.json` 是执行事实源；不要假设已经 cutover。
- 状态写入必须通过 `LaneStateMachine` 或封装的 state-machine service。

必须阅读:

```text
docs/xmuse/session-prompts/README.md
src/xmuse_core/structuring/projection.py
src/xmuse_core/platform/projection/**
src/xmuse_core/platform/state_machine.py
```

允许修改:

```text
src/xmuse_core/structuring/projection.py
src/xmuse_core/platform/projection/**
src/xmuse_core/platform/state_machine.py
src/xmuse_core/platform/orchestrator.py
tests/xmuse/test_*projection*.py
tests/xmuse/test_*state_machine*.py
tests/xmuse/test_platform_orchestrator.py
```

禁止:

- 不改 TUI/chat。
- 不让 subagent 直接 `update_lane_status`。
- 不引入多 runner 抢写。
- 不把 `feature_lanes.json` 当最终设计权威。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询以下 flag:
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S2.coordinator.ready.json`
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S4.graph.ready.json`
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S6.subagent.ready.json`
- 依赖未齐时，只允许写本地计划或测试草案，不修改 production scheduling/status 路径。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S5.execution.ready.json`。

输出要求:

- projection idempotency tests。
- lineage/projection_revision tests。
- state transition guard tests。
