# pipeline —— 带依赖的任务 DAG（M2 对照实验任务）

一个人写不完的小项目：**解析 → 调度 → 执行日志格式**三段，每段一个模块，段与段之间
靠一份冻结的任务定义、一张 `Schedule` 和一套错误约定对接。接口约定全部写在
[SPEC.md](SPEC.md)，公开测试在 `tests/test_public.py`。

## 你的任务

把 `pipeline/` 下三个模块按 SPEC.md 实现完整：

- `pipeline/parse.py`：`parse_plan`
- `pipeline/schedule.py`：`schedule`
- `pipeline/log.py`：`render_log`

`pipeline/types.py` 是冻结契约（数据结构 + 错误类型），已经写好，**默认不要改**。
确实要改约定时，先在群里说清楚，并同步改 `SPEC.md`。

## 分工建议（2–3 个 agent）

推荐按模块切三条互不重叠的切片，每条切片只改自己那一个文件：

1. **切片 A（解析）**：`parse.py`。难点是 `PlanError.line` 的 1-based 语义（空行和注释行
   也占行号）、大小写敏感的标识符、同一行重复依赖、自依赖、跨行重复定义。
2. **切片 B（调度）**：`schedule.py`。难点是未知依赖要一次收全、环检测的确定性
   （`CycleError.cycle` 的起点和方向都有约定）、`level` 是**最长路径**、
   同层按名字升序、`order` 必须等于层展平。
3. **切片 C（日志格式）**：`log.py`。难点是每步一行的硬约束、序号不补零、
   `detail` 里的换行要报错、`steps` 的顺序无关但节点集合必须和 `order` 对齐。

只有两个人：A 做 `parse.py`，B 做 `schedule.py` + `log.py`。
三个人时，第三人兼验收：对着 SPEC.md 每条写一次性反例脚本，把结论发群里；
**探针脚本不要提交进仓库**。

## 约定（跨切片的坑，开工前先对齐）

- `PlanError.line` 是 **1-based** 行号，空行和注释行也占行号。
- 空定义文本是**合法的空计划**，不是错误（和 minisql 的空语句相反）。
- 未知依赖在**调度层**报 `GraphError`，不是解析层的 `PlanError`；允许前向引用。
- 自依赖在**解析层**就是 `PlanError`；手写 `Plan` 里的自依赖到调度层才变成 `CycleError`。
- `CycleError.cycle` 旋转到字典序最小的成员开头，首尾不重复。
- `order` 必须等于 `levels` 展平，同层按**名字升序**。
- 日志里 `detail` 不含换行，序号从 1 开始、不补零，结尾不加换行。

## 怎么跑

```
python -m unittest discover -s tests -v
```

公开测试现在**全部失败**（骨架是 `raise NotImplementedError`）。让它们全绿是最低标准；
公开测试没有覆盖 SPEC.md 的每一条，验收方会用额外的边界用例来查。

## 仓库

```
git init
git add .
git commit -m "pipeline: implement SPEC.md"
```

`.gitignore` 已经忽略 `__pycache__/`。不要修改 `tests/test_public.py`，不要提交临时脚本。
