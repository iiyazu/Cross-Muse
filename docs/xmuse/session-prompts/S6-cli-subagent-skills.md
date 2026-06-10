# S6 CLI Subagent / Skills Contract Prompt

你是 xmuse 并行开发的 S6 CLI Subagent / Skills Contract session。

目标:

- 定义 coordinator 调用 CLI subagent 的输入输出 schema。
- 将可复用执行规范沉淀为 skills/prompt contracts。
- subagent 是工具，不是自治 GOD。

必须阅读:

```text
docs/xmuse/session-prompts/README.md
src/xmuse_core/providers/**
src/xmuse_core/platform/prompts/**
xmuse/skills/**
```

允许修改:

```text
src/xmuse_core/providers/**
src/xmuse_core/platform/prompts/**
xmuse/skills/**
tests/xmuse/test_worker_goal_contract.py
tests/xmuse/test_provider*.py
```

禁止:

- 不创建新的自治 GOD 执行链。
- 不让 subagent 写 durable store。
- 不直接修改 runner/orchestrator 状态机。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S6.subagent.ready.json`。

输出要求:

- subagent invocation schema。
- worker evidence output schema。
- blocker/failure 分类。
- fake CLI harness tests。
