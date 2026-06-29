# S7 Dashboard Drill-Down Prompt

你是 xmuse 并行开发的 S7 Dashboard Drill-Down session。

目标:

- dashboard 保持灰盒 drill-down，不作为 workflow driver。
- 支撑 run health、dead-letter、graph-set、lane detail、takeover context。
- 展示 degraded/read-model 状态。

必须阅读:

```text
docs/xmuse/archive/2026-06-session-prompts-legacy/README.md
xmuse/dashboard_api.py
src/xmuse_core/platform/read_contracts.py
src/xmuse_core/platform/run_health.py
```

允许修改:

```text
xmuse/dashboard_api.py
src/xmuse_core/platform/read_contracts.py
src/xmuse_core/platform/read_envelopes.py
src/xmuse_core/platform/run_health.py
tests/test_xmuse_dashboard*.py
tests/test_xmuse_run_health*.py
```

禁止:

- 不新增 lane mutation 主路径。
- 不直接驱动 workflow。
- 不要求真实 TUI/Ray/LangGraph。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 若 S2/S4 尚未完成，使用 S0 fixture/fake read model，不越界修改 runner/graph 模块。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S7.dashboard.ready.json`。

输出要求:

- dead-letter/degraded fixture。
- dashboard drill-down tests。
- focused verification command。
