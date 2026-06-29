# S8 Ray / LangGraph Adapters Prompt

你是 xmuse 并行开发的 S8 Ray / LangGraph Adapters session。

目标:

- Ray 只作为 runtime backend。
- LangGraph 只作为 workflow backend。
- 先做 adapter/shadow/replay，不接管业务状态。

必须阅读:

```text
docs/xmuse/archive/2026-06-session-prompts-legacy/README.md
src/xmuse_core/agents/ray_god_actor.py
src/xmuse_core/agents/god_session_layer.py
src/xmuse_core/structuring/blueprint_execution/**
```

允许修改:

```text
src/xmuse_core/agents/ray_*
src/xmuse_core/agents/*session*
src/xmuse_core/structuring/*langgraph*
tests/test_xmuse_ray*.py
tests/test_xmuse_langgraph*.py
```

禁止:

- Ray actor 内存不作为权威状态。
- LangGraph node 不直接写 lane status。
- native path 不依赖 Ray/LangGraph import。
- 不替换 Stage 0 coordinator 主路径。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询以下 flag:
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S2.coordinator.ready.json`
  - `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S3.blueprint.ready.json`
- 依赖未齐时，只允许写 adapter 设计草案或 skip-safe 测试草案，不让 native path 依赖 Ray/LangGraph。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S8.adapters.ready.json`。

输出要求:

- fake Ray backend 或 skip-safe tests。
- LangGraph shadow/replay artifact trace tests。
- 关闭 adapter 后 native path 不变。
