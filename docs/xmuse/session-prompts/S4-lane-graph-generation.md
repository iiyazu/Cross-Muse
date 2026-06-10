# S4 Lane Graph Generation Prompt

你是 xmuse 并行开发的 S4 Lane Graph Generation session。

目标:

- 实现或强化 `feature_plan.ready -> graph_set.ready/graph_set.failed`。
- 为每个 feature 生成 lane graph DAG。
- graph-set artifact 必须带 stable id、version、source refs。

必须阅读:

```text
docs/xmuse/session-prompts/README.md
src/xmuse_core/structuring/models.py
src/xmuse_core/structuring/feature_plan_store.py
src/xmuse_core/structuring/feature_graph_builder.py
```

允许修改:

```text
src/xmuse_core/structuring/models.py
src/xmuse_core/structuring/feature_graph_builder.py
src/xmuse_core/structuring/feature_plan_store.py
src/xmuse_core/structuring/decomposition_review.py
tests/test_xmuse_feature_plan*.py
tests/test_xmuse_feature_graph*.py
tests/test_xmuse_decomposition*.py
```

禁止:

- 不调度 worker。
- 不写 execution status。
- 不直接手写 flat lanes 当权威图。

依赖与完成标志:

- 启动后可先阅读文档、检查代码、制定本地计划。
- 正式修改生产代码前，每 10 分钟轮询 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json`。
- 若需要 S3 的真实输出但 flag 未就绪，先使用 S0 contract fixture/fake feature plan，不越界修改 S3。
- 验证完成后，原子写入 `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S4.graph.ready.json`。

输出要求:

- DAG validation tests。
- graph-set artifact contract tests。
- focused verification command。
