# ledger 接口约定（SPEC）

本文件是**唯一**的接口契约。所有模块必须严格照此实现；约定一旦变化，先改 `ledger/types.py`
和本文件，再改实现模块。

## 0. 模块划分（对应三条工作切片）

| 文件 | 职责 | 建议负责人 |
|---|---|---|
| `ledger/types.py` | 共享数据结构 + 错误类型（**冻结契约，已完成**） | 全体（改动需协商） |
| `ledger/parse.py` | 交易文本 → `Transaction` 列表 | 切片 A：解析 |
| `ledger/rules.py` | 规则匹配 + 按类目/币种汇总 | 切片 B：执行 |
| `ledger/report.py` | 汇总结果 → 确定性文本报表 | 切片 C：格式化 |

`ledger/__init__.py` 已经把公开名字导出好；**不要改名、不要改导出清单**。

## 1. 错误类型（`ledger/types.py`）

```
LedgerError(ValueError)
├── ParseError(LedgerError)
└── RuleError(LedgerError)
```

- `ParseError(message, line)`：`line` 是输入文本中的 **1-based 行号**；token 不在某一行里时用 `0`。
  属性：`message: str`、`line: int`；`str(exc) == f"line {line}: {message}"`。
- `RuleError(message)`：规则集本身不可用。
- 两种错误都必须是 `ValueError` 的子类。

## 2. 数据结构（`ledger/types.py`，全部是 frozen dataclass）

```
Transaction(line: int, date: datetime.date, description: str, amount: int, currency: str)
Rule(name: str, pattern: str, category: str)
CategoryTotal(category: str, currency: str, net: int, count: int)
Report(rows: tuple[CategoryTotal, ...], unmatched: tuple[Transaction, ...])
```

**单位约定（关键）**：`amount` / `net` 一律是**有符号整数分**（cent），永远不是浮点数。
`3.50` → `350`；`-0.05` → `-5`；`+1200.00` → `120000`。
**币种约定**：`currency` 是恰好 3 个大写 ASCII 字母（`USD`、`EUR`、`CNY`），大小写敏感。

## 3. 输入文本格式

一行一笔交易，字段用 `|` 分隔，顺序固定为 `date|description|amount|currency`：

```
# 2026-02 账本
2026-02-01|coffee beans|-3.50|USD
2026-02-01|salary|+1200.00|USD

2026-02-03|rent|-800|USD
```

- 以 `#` 开头的行、以及 strip 后为空的行：整行忽略（但**行号照数**）。
- 每行必须恰好切出 **4** 个字段；多一个少一个都是 `ParseError`（所以描述里不能出现 `|`）。
- 每个字段先 `strip()` 再解析。
- `date`：严格 `YYYY-MM-DD`，且必须是真实存在的日历日。
- `description`：strip 后非空。原样保留（内部空格保留，两端不保留）。
- `amount`：见下。
- `currency`：严格 3 个大写 ASCII 字母。

## 4. `parse.py`

### `parse_amount(token: str, line: int = 0) -> int`

把金额字面量转成**整数分**。

- 语法：`[+-]?` + 一个或多个数字 + 可选的 `.` + 1 到 2 位数字。
  合法：`3`、`3.5`、`3.50`、`-0.05`、`+1200.00`、`0.00`、`-0`。
  非法：`3.505`（3 位小数）、`.5`、`5.`、`1,000`、`1e3`、`-`、``（空）、`+ 5`、` 5 ` 之外的空串。
- 输入两端的空白先 `strip()`；字段内部不允许空白。
- **禁止用浮点数中转**：不得出现 `float(token) * 100` 这类写法（`1.15` 会算成 `114`）。
- 不合法 → `ParseError`，`line` 用传入的 `line`。

### `parse_ledger(text: str) -> list[Transaction]`

- 返回 `list`，顺序与输入文件顺序一致。
- `line` 是 1-based 行号（注释行和空行也占行号）。
- 任何字段不合法 → `ParseError`，`line` 是该字段所在行号。
- 空文本 / 全是注释 → 返回 `[]`。

## 5. `rules.py`

### `match_rule(description: str, rules: Sequence[Rule]) -> Rule | None`

- 按 `rules` 的给定顺序逐条尝试，返回**第一条**匹配的规则；都不匹配返回 `None`。
- `pattern` 的语义（自定义，不是 `fnmatch`）：
  - `*` 匹配任意长度（含 0）的字符；
  - `?` 匹配恰好 1 个字符；
  - **其他所有字符都是字面量**，包括 `.`、`[`、`]`、`(`、`\`。也就是说 `a.b` 只匹配
    字面的 `a.b`，不匹配 `axb`；`[ab]` 只匹配 `[ab]` 三个字符。
- 匹配**大小写不敏感**，且必须是**整串匹配**（隐式锚定 `^...$`）：
  `coffee` 不匹配 `coffee beans`；`coffee*` 才匹配。

### `apply_rules(transactions: Sequence[Transaction], rules: Sequence[Rule]) -> Report`

- 先校验规则集，不合法抛 `RuleError`：
  - `name`、`category`、`pattern` 中任意一个是空字符串；
  - 两条规则的 `name` 相同。
- 按 `transactions` 的给定顺序处理；每条交易用 `match_rule` 找第一条命中的规则。
  - 命中：落到 `(category, currency)` 桶里，`net += amount`，`count += 1`。
  - **没有命中**：放进 `Report.unmatched`，顺序为输入顺序，**不要**塞进 `rows`，
    也不要有 `"uncategorized"` 之类的伪类目。
- `Report.rows` 按 `(currency, category)` 升序排序，是 `tuple`。
  同一个 `category` 的不同币种**必须分开**两行，`net` 不能跨币种相加。
- `Report.unmatched` 是 `tuple`，输入顺序。
- 不修改入参（`transactions` / `rules` 只读）。
- 空 `transactions` → `Report(rows=(), unmatched=())`。

## 6. `report.py`

### `format_amount(cents: int, currency: str) -> str`

- 输出 `<金额> <币种>`，例如 `350, "USD"` → `"3.50 USD"`。
- 负数带前导 `-`，正数**不**带 `+`；整数部分不留前导零。
- 小数位固定 2 位。`5` → `"0.05 XXX"`；`-5` → `"-0.05 XXX"`；`0` → `"0.00 XXX"`；
  `-123456` → `"-1234.56 XXX"`。
- **注意负数取整方向**：不能直接对负数做 `//` 和 `%`（`-5 // 100 == -1`，`-5 % 100 == 95`）。

### `render_report(report: Report) -> str`

- 先按 `report.rows` 的顺序，每行一个类目：

  ```
  {category}: {format_amount(net, currency)} ({count})
  ```

  例：`food: -3.50 USD (1)`。注意币种由 `format_amount` 带出来，**不要**在行首再写一遍。
- 再按 `report.unmatched` 的顺序，每行一条未匹配交易：

  ```
  ? {date.isoformat()} {description} {format_amount(amount, currency)}
  ```

  例：`? 2026-02-01 salary 1200.00 USD`。
- 各部分之间用 `\n` 连接；**结尾不带换行**；空 `Report` → `""`。
- 该函数是纯格式化：不排序、不再计算。

## 7. 示例（端到端）

输入：

```
2026-02-01|coffee beans|-3.50|USD
2026-02-01|salary|+1200.00|USD
2026-02-03|rent|-800|USD
2026-02-04|coffee beans|-2.50|EUR
```

规则：`Rule("food", "*coffee*", "food")`、`Rule("housing", "rent", "housing")`。

`render_report(apply_rules(parse_ledger(text), rules))` 的结果：

```
food: -2.50 EUR (1)
food: -3.50 USD (1)
housing: -800.00 USD (1)
? 2026-02-01 salary 1200.00 USD
```

（顺序是 `rows` 的顺序：先按币种 EUR < USD，再按类目 food < housing。）
