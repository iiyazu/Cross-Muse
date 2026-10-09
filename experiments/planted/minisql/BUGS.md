# minisql 预埋 bug（复核方看不到）

形式是**整文件替换**：`planted/minisql/bug-N/` 下的相对路径和
`reference/minisql/` 一致，`verify.py` 会把参考实现复制到临时目录，再用这里的
文件覆盖过去，然后跑隐藏测试。要求：每个变体至少让 1 个隐藏用例失败。

两个 bug 都**不是**语法错误，代码可以正常 import、公开测试全绿，只有读
`ParseError.position` 或换一种列名写法的隐藏用例才会露馅。两个 bug 也落在
**不同文件**（`parser.py` / `engine.py`），复核方按文件报 bug 时不会互相污染。

---

## bug-1：`ParseError.position` 用了 token 序号，不是字符下标

- **文件**：`minisql/parser.py`（切片 A：解析）
- **类型**：错误定位语义错（token ordinal vs 0-based character offset）
- **改动**：`_Parser.error` 从参考实现的「取当前 token 第 3 个字段（字符偏移），
  没有 token 时取 `len(sql)`」换成 `ParseError(message, self.index)`，即
  `self.index` 这个**token 下标**。
- **为什么真实**：`position` 这个字段名太像「第几个 token / 第几行了」，作者写完
  `_Parser` 之后顺手把解析器的游标 `self.index` 塞进去，是很常见的混淆；
  `ParseError` 的构造签名也不会拦住它。所有语句仍然解析成功，错误也照样抛，
  所以只在「有人真的去读 `position`」时才暴露。SPEC §1 和 README「跨切片的坑」
  都把这条单独列出来了，说明它确实是这个任务约定的薄弱点。
- **影响面**：所有语法错误的 `position`（不是只有一条语句）。
  例：`SELECT * FROM movies WHERE year == 1979` 里错在第二个 `=`（字符 31），
  bug 版本报的是 token 序号 7。
- **公开测试为什么是绿的**：公开测试里只有 `assertRaises(ParseError)` 和
  直接构造 `ParseError("boom", 4)` 的契约测试，没有任何一条读解析出来的
  `position`。
- **抓它的隐藏用例**：
  - `TestParserHidden.test_error_positions_are_character_offsets`（第一条断言
    `== 1979` 就挂；同一个方法里还有 `% 2` 与语句提前结束两种位置）
- **实测**：隐藏测试 `ran 47, failures=1`。

---

## bug-2：列名匹配区分大小写，丢掉了跨切片的「大小写不敏感」约定

- **文件**：`minisql/engine.py`（切片 B：执行）
- **类型**：跨模块约定（列名在执行阶段按大小写不敏感匹配）被简化
- **改动**：`_find_column` 从 `column.lower() == name.lower()` 换成 `column == name`。
- **为什么真实**：参考实现里其实有两次「解析列名」：`_find_column`（返回表的规范
  写法）和 `positions = {name: index ...}`（拿下标）。作者很容易觉得
  `positions` 那张表已经够了，顺手把 `_find_column` 写成直接相等比较——单看
  这一行完全像是「按名字找列」。公开测试的每条 SQL 都严格照表定义写列名
  （`id`、`title`、`year`、`score`），所以公开测试发现不了。
- **影响面**：选择列表、`WHERE`、`ORDER BY` 三处列名解析；
  输出列名的「用表定义写法」这条约定也一并失效（匹配不到直接抛
  `ExecutionError`）。
- **抓它的隐藏用例**：
  - `TestEngineHidden.test_columns_use_the_table_spelling`
    （`SELECT ID, Title FROM MOVIES` 期望成功并返回 `("id", "title")`）
  - `TestEngineHidden.test_where_column_is_case_insensitive`
    （`WHERE YEAR = 1979`）
- **实测**：隐藏测试 `ran 47, errors=2`。

---

## 覆盖情况

| 变体 | 切片 | 公开测试会不会先发现 | 主要隐藏用例 |
|---|---|---|---|
| bug-1 | parser | 不会（公开只断言抛不抛） | `TestParserHidden.test_error_positions_are_character_offsets` |
| bug-2 | engine | 不会（公开 SQL 都照表定义写列名） | `TestEngineHidden.test_columns_use_the_table_spelling`、`test_where_column_is_case_insensitive` |

`format.py` 这一片没有预埋 bug，用来当对照：复核方如果只盯着「有没有 bug」，
把没问题的切片也报成 bug，可以在复核检出率之外再算一个误报率。
