# S2 Coordinator Core Prompt

你是 xmuse 并行开发的 S2 Coordinator Core session。

目标:

- 把 Stage 0 native xmuse coordinator 边界收束清楚。
- 当前 coordinator 主要由 `xmuse/platform_runner.py` 承载。
- `PlatformOrchestrator` 是 lane execution / review / merge / status transition 的主要执行控制面。
- coordinator 统一驱动 2a/2b/2c，不新建多个自治 GOD 执行链。

必须阅读:

```text
docs/xmuse/archive/2026-06-session-prompts-legacy/README.md
xmuse/platform_runner.py
src/xmuse_core/platform/orchestrator.py
```

允许修改:

```text
xmuse/platform_runner.py
src/xmuse_core/platform/orchestrator.py
src/xmuse_core/platform/runner_supervisor.py
src/xmuse_core/platform/run_health.py
tests/xmuse/test_platform_runner.py
tests/xmuse/test_platform_orchestrator.py
tests/xmuse/test_runner_supervisor.py
```

禁止:

- 不重写 chat/TUI。
- 不引入 Ray/LangGraph 为 native path 必需依赖。
- 不绕过 `LaneStateMachine`。
- 不启动多个 runner 抢写同一 `feature_lanes.json`。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S2.coordinator.ready.json`。

输出要求:

- coordinator lifecycle / dead-letter / degraded path tests。
- 明确哪些行为仍保留在 runner，哪些抽成 service。
- focused verification command。
