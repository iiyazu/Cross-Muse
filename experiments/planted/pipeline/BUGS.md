# pipeline 预埋 bug（复核方看不到）

形式是**整文件替换**：`planted/pipeline/bug-N/` 下的相对路径和
`reference/pipeline/` 一致，`verify.py` 会把参考实现复制到临时目录，再用这里的
文件覆盖过去，然后跑隐藏测试。要求：每个变体至少让 1 个隐藏用例失败。

两个 bug 都**不是**语法错误，代码可以正常 import、公开测试全绿，只有踩到
「重复定义」或「平局顺序」的隐藏用例才会露馅。两个 bug 落在**不同文件**
（`parse.py` / `schedule.py`），复核方按文件报 bug 时不会互相污染。

---

## bug-1：重复节点定义被静默覆盖，没有报 `PlanError`

- **文件**：`pipeline/parse.py`（切片 A：解析）
- **位置**：`parse_plan` 主循环
- **类型**：输入校验缺失（重复定义检测）＋「按 dict 建图」的惯用写法副作用
- **改动**：参考实现用 `by_name` 做「见过就报错」的检测，报错行号是**后出现**的那一行；
  bug 版本改成 `order` + `table` 两张表，`if node.name not in table: order.append(...)`，
  然后无条件 `table[node.name] = node.deps`。于是最后一次定义胜出，重复行被当成没事。
- **为什么真实**：先收集 `name -> deps` 再一次性建 `Plan` 是最自然的写法，作者在
  「先把解析跑通」阶段很容易忘记重复名字是错的；`order` 列表还保证了书写顺序，
  表面上和参考实现没有区别。
- **影响面**：所有重复定义的输入（`a: b` 后面再写一行 `a: c`）；图会用最后一次的依赖，
  调度结果因此可能是错的，而且**不报任何错**。
- **公开测试为什么是绿的**：公开测试只喂合法的、每个节点只定义一次的定义文本；
  重复定义是 SPEC §3 里明确列出的边界，公开测试没覆盖。
- **抓它的隐藏用例**：
  - `TestParsePlanHidden.test_duplicate_node_definition_is_rejected`
    （`a: b\na: c` 期望 `PlanError`、`line == 2`；bug 版本返回 `Plan`，断言直接失败）
- **实测**：隐藏测试 `ran 44, failures=1`；公开测试 10 条全绿。

---

## bug-2：`order` 用另一次最小堆拓扑排序算，不是 `levels` 展平

- **文件**：`pipeline/schedule.py`（切片 B：调度）
- **位置**：`schedule` 的返回值（新增私有 `_topological_order`）
- **类型**：跨模块约定（`order == levels` 展平、同层按名字升序）被另一个「看起来更标准」的
  实现悄悄替换
- **改动**：`levels` 仍然按参考实现的 Kahn 分层算；但 `order` 改成把入度为 0 的节点放进
  `heapq` 最小堆、逐个弹出（经典的 Kahn + 优先队列）。结果仍是**合法拓扑序**，
  但当「较浅层的节点名字排在较深节点之后」时，它和层展平不一致。
- **为什么真实**：拓扑排序的第一反应就是 Kahn + 最小堆；作者很可能先写 `levels`
  给并发用、再顺手写一个 `order` 给执行队列用，没有意识到 SPEC 要求两者严格一致。
  `("a", "b", "c")` 本身是完全合法的拓扑序，粗看没错。
- **影响面**：`order` 与 `levels` 不一致的一切图；`render_log` 按 `order` 渲染，
  执行日志的行序也跟着错。例：`a:`、`b: a`、`c:` 三层图，SPEC 要求
  `levels == (("a", "c"), ("b",))`、`order == ("a", "c", "b")`，
  bug 版本给出 `order == ("a", "b", "c")`。
- **公开测试为什么是绿的**：公开样例 `compile/lint/test/package` 的堆序恰好等于层展平，
  两条路径给出同一结果。
- **抓它的隐藏用例**：
  - `TestScheduleHidden.test_order_is_the_levels_flattened`（`a/c/b` 图，主检测）
  - `TestScheduleHidden.test_ties_are_broken_by_name`（`m/z/a/b` 图，断言 `order`）
  - `TestLogHidden.test_log_follows_the_level_order`（同一图，日志行序也跟着错）
- **实测**：隐藏测试 `ran 44, failures=3`；公开测试 10 条全绿。

---

## 覆盖情况

| 变体 | 切片 | 公开测试会不会先发现 | 主要隐藏用例 |
|---|---|---|---|
| bug-1 | parse | 不会（公开文本没有重复定义） | `test_duplicate_node_definition_is_rejected` |
| bug-2 | schedule | 不会（公开样例的堆序恰好等于层展平） | `test_order_is_the_levels_flattened` |

`log.py` 这一片没有预埋 bug，用来当对照：复核方如果只盯着「有没有 bug」，
把没问题的切片也报成 bug，可以在复核检出率之外再算一个误报率。
