# S3 Blueprint Decomposition Prompt

你是 xmuse 并行开发的 S3 Blueprint Decomposition session。

目标:

- 实现或强化 `blueprint.approved -> planning.started -> feature_plan.ready/planning.failed`。
- 2a 由 xmuse coordinator 调用，不独立启动 runner。
- 同一 `blueprint.approved` 重放必须幂等。

必须阅读:

```text
docs/xmuse/archive/2026-06-session-prompts-legacy/README.md
src/xmuse_core/structuring/blueprint_execution/**
src/xmuse_core/structuring/feature_plan_*
```

允许修改:

```text
src/xmuse_core/structuring/blueprint_execution/**
src/xmuse_core/structuring/feature_plan_*
src/xmuse_core/agents/planning_god_adapters.py
tests/test_xmuse_blueprint_execution*.py
tests/test_xmuse_feature_plan*.py
```

禁止:

- 不生成 graph-set。
- 不投影 lane。
- 不写 `feature_lanes.json`。
- 不启动 runner。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S3.blueprint.ready.json`。

输出要求:

- fake planner/reviewer contract。
- planning.failed reason/artifact refs。
- focused tests 和验证命令。
