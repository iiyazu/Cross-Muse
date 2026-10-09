# ledger 预埋 bug（复核方看不到）

形式是**整文件替换**：`planted/ledger/bug-N/` 下的相对路径和
`reference/ledger/` 一致，`verify.py` 会把参考实现复制到临时目录，再用这里的
文件覆盖过去，然后跑隐藏测试。要求：每个变体至少让 1 个隐藏用例失败。

两个 bug 都**不是**语法错误，代码可以正常 import、公开测试里有一部分照样是绿的，
只有覆盖边界或跨币种场景的隐藏用例才会露馅。

---

## bug-1：金额解析走二进制浮点，分为单位被截断

- **文件**：`ledger/parse.py`（切片 A：解析）
- **类型**：数值精度 / 单位换算错误（off-by-one cent）
- **改动**：`parse_amount` 的最后一步从「字符串拆分 + 整数运算」换成
  `return int(float(text) * 100)`。
- **为什么真实**：`float("1.15") * 100 == 114.99999999999999`，`int()` 直接截断成
  `114`。作者通常会先写 `round()`，但只要有人为了「避免银行家舍入」把 `round` 去掉、
  或者改成 `int()`，就会踩中。`3.50`、`-800` 这类**看起来正常**的值不受影响，
  所以它在公开测试里大概率是绿的。
- **影响面**：所有金额，最终报表的合计也会差一分。
- **抓它的隐藏用例**：
  - `TestParseAmountHidden.test_exact_cents_never_through_float`（`1.15 → 115`、`0.29 → 29`）
  - `TestParseAmountHidden.test_large_amount_is_exact`
  - `TestContractsHidden.test_end_to_end`（`mystery -1.15` 那行会渲染成 `-1.14`）

---

## bug-2：汇总桶漏了币种，跨币种金额相加

- **文件**：`ledger/rules.py`（切片 B：执行）
- **类型**：聚合键不完整 / 跨模块约定（`(category, currency)` 二元键）被简化
- **改动**：`apply_rules` 的桶键从 `(transaction.currency, hit.category)` 改成
  `hit.category`；累加时沿用第一个交易的币种。
- **为什么真实**：单币种场景下两种写法完全等价，公开测试的样例只有 USD/EUR 混合时
  才暴露。作者在「先把功能跑通」阶段很容易把币种当成展示层的事，忘了它同时是
  聚合维度。排序代码还在，所以行序看起来是合理的。
- **影响面**：多币种报表的所有合计与行数都是错的（币种被第一个交易「吞掉」）。
- **抓它的隐藏用例**：
  - `TestRulesHidden.test_currencies_never_mixed`（期望 EUR 与 USD 两行，实际合并成一行）
  - `TestRulesHidden.test_rows_sorted_by_currency_then_category`（行数从 4 变 3）
  - `TestContractsHidden.test_end_to_end`（EUR/USD 两个 food 被合并）

---

## 覆盖情况

| 变体 | 切片 | 公开测试会不会先发现 | 主要隐藏用例 |
|---|---|---|---|
| bug-1 | parse | 不会（公开样例的金额都不触发） | `test_exact_cents_never_through_float` |
| bug-2 | rules | 不会（公开样例只有单币种同类目合计） | `test_currencies_never_mixed` |

`report.py` 这一片没有预埋 bug，用来当对照：复核方如果只盯着「有没有 bug」，
把没问题的切片也报成 bug，可以在复核检出率之外再算一个误报率。
