# pipeline 接口约定（SPEC）

本文件是**唯一**的接口契约。所有模块必须严格照此实现；约定一旦变化，先改
`pipeline/types.py` 和本文件，再改实现模块。

## 0. 模块划分（对应三条工作切片）

| 文件 | 职责 | 建议负责人 |
|---|---|---|
| `pipeline/types.py` | 共享数据结构 + 错误类型（**冻结契约，已完成**） | 全体（改动需协商） |
| `pipeline/parse.py` | 任务定义文本 → `Plan` | 切片 A：解析 |
| `pipeline/schedule.py` | `Plan` → `Schedule`（校验、分层、拓扑顺序、环） | 切片 B：调度 |
| `pipeline/log.py` | `Schedule` + 步骤记录 → 确定性执行日志 | 切片 C：日志格式 |

`pipeline/__init__.py` 已经把公开名字导出好；**不要改名、不要改导出清单**。

## 1. 错误类型（`pipeline/types.py`）

```
PipelineError(ValueError)
├── PlanError(PipelineError)      # 定义文本不合法（切片 A）
├── GraphError(PipelineError)     # 依赖图不合法（切片 B）
│   └── CycleError(GraphError)    # 图里有环
└── LogError(PipelineError)       # 调度结果和步骤记录配不起来（切片 C）
```

- `PlanError(message, line=0)`：`line` 是输入文本中的 **1-based 行号**；问题不在某一行时用 `0`。
  属性：`message: str`、`line: int`；`str(exc) == f"line {line}: {message}"`。
- `GraphError(message, nodes=())`：`nodes` 是相关节点名的 tuple，**升序、去重**（可以传未排序的，
  构造时要规范化）。属性：`message: str`、`nodes: tuple`；`str(exc) == message`。
- `CycleError(message, cycle=())`：`GraphError` 的子类，多一个 `cycle` 属性。
  `cycle` 是环上的节点名，**旋转到以字典序最小的成员开头**，方向不变，首尾不重复
  （`("a", "b", "c")` 而不是 `("a", "b", "c", "a")`）；`nodes` 是 `sorted(set(cycle))`。
- `LogError(message)`：`str(exc) == message`。
- 四种错误都必须是 `PipelineError` 的子类，`PipelineError` 必须是 `ValueError` 的子类。

## 2. 数据结构（`pipeline/types.py`，全部是 frozen dataclass）

```
Node(name: str, deps: tuple = ())
Plan(nodes: tuple = ())
Schedule(order: tuple = (), levels: tuple = ())
Step(node: str, status: str, detail: str = "")
```

- 字符串一律是 `str`；`Node.deps` 的元素、`Plan.nodes` 的元素、`Schedule.order` /
  `Schedule.levels[k]` 的元素都是节点名。
- `Step.status` 只允许 `"ok"`、`"failed"`、`"skipped"`（校验在 `render_log` 里做，
  构造 `Step` 时不拦）。
- 所有 dataclass 都不可变；给出参对象一律只读。

## 3. 任务定义文本格式

一行一个节点：

```
# 注释行
compile:
lint:
test: compile, lint
package: test
```

- 行的两端先 `strip()`；strip 后为空、或以 `#` 开头（`#` 前只允许空白）的行：整行忽略，
  但**行号照数**。`#` 出现在别处按普通字符处理（结果是名字/依赖名不合法）。
- 其余行语法：

  ```
  node := name ws* ":" ws* deps?
  deps := name (ws* "," ws* name)*
  name := [A-Za-z_][A-Za-z0-9_]*
  ```

  `name` 是 ASCII 标识符，**大小写敏感**（`Build` 和 `build` 是两个不同的节点）。
- `name:`、`name: `、`name:` 后只有空白 → 没有依赖。
- 空文本、全是注释/空行 → `Plan(nodes=())`，**不是错误**（和 minisql 的空语句约定相反）。
- 下列都是 `PlanError`（`line` 指出问题所在行）：
  - 没有 `:`，或 `:` 前不是合法名字；
  - 依赖名不是合法标识符（含 `a: b c` 这种少写逗号、`a: b,` 这种悬空逗号、`a: ,b`）；
  - 同一行里同一个依赖出现两次（保留首次出现的顺序没有意义，直接报错）；
  - **自依赖**（`a: a`）：行内就能发现，归解析层；
  - 同一个节点名定义两次（跨行）。
- 输入不是 `str` → `TypeError`。

## 4. `parse.py`

### `parse_plan(text: str) -> Plan`

- 按 §3 解析，返回冻结的 `Plan`。
- `Plan.nodes` 是**书写顺序**；每个 `Node.deps` 是**依赖书写顺序**的 tuple。
- 重复节点名报错时，`line` 是**后出现**的那一行（先出现的那行不报错）。
- 未知依赖（依赖了还没定义的节点）**不在这里报错**：允许前向引用（可以先写
  `test: compile` 再写 `compile:`），完整性由调度层负责。

## 5. `schedule.py`

### `schedule(plan: Plan) -> Schedule`

1. **类型与唯一性**：
   - 不是 `Plan` 实例 → `GraphError`（消息里写出实际类型，`nodes=()`）。
   - `plan.nodes` 里节点名重复（手写 `Plan` 才会出现，解析层已经拦了）→
     `GraphError`，`nodes=(该名字,)`。
2. **未知依赖**：收集所有在任何 `Node.deps` 里出现、但不在 `plan.nodes` 里的名字，
   **升序去重**；非空 → `GraphError`，`nodes` 就是这组名字，消息里必须包含这些名字。
3. **环**：剥不掉环时抛 `CycleError`。`cycle` 的取法是确定的：
   1. 用 Kahn 分层剥掉所有依赖已满足的节点；剥不掉的节点集合记作 `R`；
   2. `R` 里的起点按名字升序尝试；每个节点展开时，依赖也按**名字升序**访问；
   3. 深度优先走到「已经在当前路径上」的节点时停止，环 = 当前路径上从该节点到最后的一段；
   4. 把环旋转到以字典序最小的成员开头（方向不变）。
   只有一个节点的自依赖（手写的 `Plan`）就是这个规则的退化情形：`cycle == ("a",)`。
4. **分层**：
   - `level(节点) = 0`（没有依赖），否则 `1 + max(level(每个依赖))`（**最长路径**，不是最短路径）。
   - `levels[k]` 是 `level == k` 的所有节点名，**按名字升序**（这是平局规则）。
   - 同一层里的节点两两之间没有依赖边，可以并发跑。
5. **顺序**：`order` **必须**等于 `levels` 展平（`levels[0] + levels[1] + ...`），
   逐元素相同；它不是另一次独立拓扑排序的结果。
6. 空 `Plan` → `Schedule(order=(), levels=())`。
7. 不修改入参；同一份 `Plan` 调度两次结果相同。
8. 手写 `Plan` 里同一节点重复写同一个依赖**不报错**（调度按集合语义处理）；
   解析层已经禁止这种写法。

## 6. `log.py`

### `render_log(schedule: Schedule, steps: Iterable[Step]) -> str`

按 `schedule.order` 渲染执行日志，**每步一行**。

1. **校验 `schedule`**（不是 `Schedule` 实例 → `LogError`）：
   - `schedule.levels` 展平后，同一个节点不能出现在多个/同一层里；
   - `set(schedule.order)` 必须恰好等于 `levels` 展平后的节点集合（不重不漏）：
     `order` 的顺序**由 `order` 自己决定**，`render_log` 不要求它等于展平顺序
     （那是 `schedule()` 的约定），只要求两边覆盖同一批节点；
   - 违反 → `LogError`。
2. **校验 `steps`**（任意可迭代对象，元素必须是 `Step`，否则 `LogError`）：
   - 同一个 `node` 出现两次 → `LogError`；
   - `node` 不在 `schedule.order` 里 → `LogError`；
   - `schedule.order` 里有节点没有对应的 `Step` → `LogError`；
   - `status` 不是 `ok` / `failed` / `skipped` → `LogError`；
   - `detail` 不是 `str`，或含有 `\n` / `\r` → `LogError`（每步一行是硬约定）。
3. **渲染**，按 `schedule.order` 的顺序，序号从 **1** 开始、**不补零**：
   - 行：`{i}. L{level} {status} {node}`；
   - `level` 是该节点在 `schedule.levels` 里的下标；
   - `detail` 非空时追加 `": " + detail`；`detail` 前后空白**原样保留**。
4. 行用 `\n` 连接，**结尾不带换行**；空 `Schedule` + 空 `steps` → `""`。
5. 纯函数：不修改 `schedule` 和 `steps` 的元素。

## 7. 示例（端到端）

```
compile:
lint:
test: compile, lint
package: test
```

`parse_plan` → `Plan(nodes=(Node("compile", ()), Node("lint", ()),
Node("test", ("compile", "lint")), Node("package", ("test",))))`

`schedule` → `Schedule(order=("compile", "lint", "test", "package"),
levels=(("compile", "lint"), ("test",), ("package",)))`

`render_log`，步骤 `compile=ok`、`lint=ok`、`test=failed("2 tests failed")`、
`package=skipped`：

```
1. L0 ok compile
2. L0 ok lint
3. L1 failed test: 2 tests failed
4. L2 skipped package
```

平局规则的反例（同层按名字升序，而 `order` 就是层展平）：

```
a:
b: a
c:
```

`levels == (("a", "c"), ("b",))`，`order == ("a", "c", "b")`。
注意 `("a", "b", "c")` 虽然也是一个合法拓扑序，但**不是**本 SPEC 的 `order`。

环的例子：

```
a: b
b: c
c: a
```

`schedule` 抛 `CycleError`，`cycle == ("a", "b", "c")`，`nodes == ("a", "b", "c")`。
