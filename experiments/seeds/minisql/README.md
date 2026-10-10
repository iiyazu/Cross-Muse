# minisql —— 极小的 SELECT/WHERE 子集（M2 对照实验任务）

一个人写不完的小项目：**解析 → 内存表执行 → 结果格式化**三段，每段一个模块，段与段之间
靠一棵冻结的语法树和一张内存表对接。接口约定全部写在 [SPEC.md](SPEC.md)，公开测试在
`tests/test_public.py`。

## 你的任务

把 `minisql/` 下三个模块按 SPEC.md 实现完整：

- `minisql/parser.py`：`parse`
- `minisql/engine.py`：`execute`
- `minisql/format.py`：`format_table`

`minisql/types.py` 是冻结契约（数据结构 + 错误类型），已经写好，**默认不要改**。
确实要改约定时，先在群里说清楚，并同步改 `SPEC.md`。

## 分工建议（2–3 个 agent）

按模块切三条互不重叠的切片，每条切片只改自己那一个文件：

1. **切片 A（解析）**：`parser.py`。难点是 token 位置、`ParseError.position` 的 0-based
   语义、字符串转义、关键字的保留、`<>` 规范化成 `!=`。
2. **切片 B（执行）**：`engine.py`。难点是列名大小写不敏感匹配、`None` 的比较语义、
   多键混合 ASC/DESC 的稳定排序、类型不可比时抛 `ExecutionError`。
3. **切片 C（格式化）**：`format.py`。难点是最后一列不填充、分隔行、空结果集。

只有两个人：A 做 `parser.py`，B 做 `engine.py` + `format.py`。
三个人时，第三人兼验收：对着 SPEC.md 每条写一次性反例脚本，把结论发群里；
**探针脚本不要提交进仓库**。

## 约定（跨切片的坑，开工前先对齐）

- 值只有 `int` / `str` / `None`，**不许用 float**。
- `ParseError.position` 是 0-based 字符下标，不是行号也不是 token 序号。
- `<>` 在解析阶段就变成 `!=`；`Condition.op` 里不允许出现 `<>`。
- 列名匹配在执行阶段做，大小写不敏感；输出列名用**表定义**的写法。
- `ASC` 里 `None` 排最前，`DESC` 是它的完全反转；排序必须稳定。
- `format_table` 的最后一列不填充空格，结尾不加换行。

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
git commit -m "minisql: implement SPEC.md"
```

`.gitignore` 已经忽略 `__pycache__/`。不要修改 `tests/test_public.py`，不要提交临时脚本。
