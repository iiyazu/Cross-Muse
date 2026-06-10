# S1 GOD Chat / TUI Read Layer Prompt

你是 xmuse 并行开发的 S1 GOD Chat / TUI Read Layer session。

目标:

- 支撑去中心化 GOD 群聊层和 Textual TUI 主入口。
- TUI 只读消费 messages/cards/worklist/read envelopes。
- Dashboard 只作为 drill-down。

必须阅读:

```text
docs/xmuse/session-prompts/README.md
xmuse/FRONTEND_API.md
xmuse/FRONTEND_CONTEXT.md
```

允许修改:

```text
src/xmuse_core/chat/**
src/xmuse_core/platform/read_envelopes.py
xmuse/tui/**
tests/test_xmuse_chat*.py
tests/test_xmuse_textual*.py
```

禁止:

- 不写 `feature_lanes.json`。
- 不启动 runner。
- 不修改 Layer 2 services。
- 不把 dashboard API 当主流程 driver。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S1.chat_tui.ready.json`。

输出要求:

- read envelope/card contract 或 fixture。
- TUI/chat focused tests。
- 汇报所有 touched files 和验证命令。
