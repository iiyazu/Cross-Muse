# ledger —— 记账规则引擎（M2 对照实验任务）

一个人写不完的小项目：**解析 → 规则执行 → 报表格式化**三段，每段一个模块，段与段之间
有明确的数据结构和单位约定。接口约定全部写在 [SPEC.md](SPEC.md) 里，公开测试在
`tests/test_public.py`。

## 你的任务

把 `ledger/` 下三个模块按 SPEC.md 实现完整：

- `ledger/parse.py`：`parse_amount`、`parse_ledger`
- `ledger/rules.py`：`match_rule`、`apply_rules`
- `ledger/report.py`：`format_amount`、`render_report`

`ledger/types.py` 是冻结契约（数据结构 + 错误类型），已经写好，**默认不要改**。
如果确实需要改约定，先在群里说明，并同步改 `SPEC.md`。

## 分工建议（2–3 个 agent）

推荐按模块切三条互不重叠的切片，每条切片只改自己那一个文件：

1. **切片 A（解析）**：`parse.py`。难点是金额字面量到整数分、行号、错误分类。
2. **切片 B（执行）**：`rules.py`。难点是自定义通配符语义、整串匹配、按 (币种, 类目) 分桶。
3. **切片 C（格式化）**：`report.py`。难点是负数金额的整数分格式、输出逐字节稳定。

如果只有两个人：A 做 `parse.py`，B 做 `rules.py` + `report.py`。
如果三个人：第三人额外负责验收——写一次性脚本，对着 SPEC.md 每一条规则手工构造反例，
并把结论发在群里；**不要**把探针脚本提交进仓库。

## 约定（跨切片的坑，开工前先对齐）

- 金额一律是**有符号整数分**，禁止浮点数中转。`1.15` 是 `115`，不是 `114`。
- 币种是 3 个大写字母，大小写敏感；不同币种**不能**相加。
- `ParseError.line` 是 1-based 行号，注释行和空行也占行号。
- `pattern` 里只有 `*` 和 `?` 是通配符，`. [ ]` 都是字面量。
- `render_report` 的输出必须逐字节稳定（同一份 Report 渲染两次结果相同，结尾无换行）。

## 怎么跑

```
python -m unittest discover -s tests -v
```

公开测试现在**全部失败**（骨架是 `raise NotImplementedError`）。让它们全部通过是最低标准；
公开测试不覆盖 SPEC.md 的每一条，验收方会用额外的边界用例来查。

## 仓库

```
git init
git add .
git commit -m "ledger: implement SPEC.md"
```

`.gitignore` 已经忽略 `__pycache__/`。不要修改 `tests/test_public.py`，不要提交
临时探针脚本。
