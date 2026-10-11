# minisql 接口约定（SPEC）

本文件是**唯一**的接口契约。所有模块必须严格照此实现；约定一旦变化，先改
`minisql/types.py` 和本文件，再改实现模块。

## 0. 模块划分（对应三条工作切片）

| 文件 | 职责 | 建议负责人 |
|---|---|---|
| `minisql/types.py` | 共享数据结构 + 错误类型（**冻结契约，已完成**） | 全体（改动需协商） |
| `minisql/parser.py` | SQL 文本 → `Select` 语法树 | 切片 A：解析 |
| `minisql/engine.py` | `Select` + `Table` → `ResultSet` | 切片 B：执行 |
| `minisql/format.py` | `ResultSet` → 定宽文本表 | 切片 C：格式化 |

`minisql/__init__.py` 已经把公开名字导出好；**不要改名、不要改导出清单**。

## 1. 错误类型（`minisql/types.py`）

```
MiniSQLError(ValueError)
├── ParseError(MiniSQLError)        # 语法/词法错误
└── ExecutionError(MiniSQLError)    # 语义错误（未知列、类型不可比……）
```

- `ParseError(message, position)`：`position` 是 **0-based 的字符下标**（指向出错的那个
  字符；出错位置在语句末尾时用 `len(sql)`）。属性：`message: str`、`position: int`；
  `str(exc) == f"at {position}: {message}"`。
- `ExecutionError(message)`。
- 两种错误都必须是 `ValueError` 的子类。

## 2. 数据结构（`minisql/types.py`，全部是 frozen dataclass）

```
Condition(column: str, op: str, value: object = None)
OrderKey(column: str, descending: bool = False)
Select(columns: tuple, table: str, where: tuple = (), order_by: tuple = (), limit: int|None = None)
Table(columns: tuple, rows: tuple)
ResultSet(columns: tuple, rows: tuple)
```

- 列值只允许三种：`int`、`str`、`None`。**不允许 `float`**（评分、金额之类一律用 `int`）。
- `Table.rows` 的每个元素是与 `Table.columns` **等长**的 tuple。
- `ResultSet.rows` 的每个元素是与 `ResultSet.columns` 等长的 tuple。
- `Condition.op` 只会是这 7 个值之一：`"="`、`"!="`、`"<"`、`"<="`、`">"`、`">="`、
  `"IS NULL"`、`"IS NOT NULL"`（共 8 个）。`<>` 在解析阶段就**规范化成 `"!="`**，
  下游永远看不到 `"<>"`。
- 除 `IS NULL` / `IS NOT NULL` 外，`Condition.value` 是 `int` 或 `str`，不会是 `None`；
  这两个 op 的 `value` 恒为 `None`。

## 3. 语法（大小写不敏感的关键字）

```
statement := SELECT select_list FROM ident [WHERE cond (AND cond)*]
             [ORDER BY order_key (, order_key)*] [LIMIT integer] [";"]

select_list := "*" | ident (, ident)*
cond        := ident op value
             | ident IS [NOT] NULL
op          := "=" | "!=" | "<>" | "<" | "<=" | ">" | ">="
value       := integer | string
order_key   := ident [ASC | DESC]
```

词法：

- 标识符：`[A-Za-z_][A-Za-z0-9_]*`。关键字（`SELECT FROM WHERE AND ORDER BY ASC DESC
  LIMIT IS NOT NULL`）不能当标识符用。
- 整数：`[+-]?[0-9]+`（没有算术，所以 `-5` 是一个字面量）。
- 字符串：单引号包裹，内部两个连续单引号 `''` 表示一个字面单引号；不允许跨行；没有闭合
  → `ParseError`，`position` 指向**开头的那个单引号**（不是 `len(sql)`；这条优先于上面
  “出错位置在语句末尾时用 `len(sql)`”的通用规则）。
- 空白（含换行、制表）可出现在任意 token 之间。
- 语句末尾允许有一个 `;`，之后必须结束。
- 其他字符 → `ParseError`，`position` 指向该字符。

语义约定：

- `SELECT *` 只能单独出现；`SELECT *, a` 是语法错误。
- 列名、表名在 `Select` 里按 SQL 原文保留大小写；`Table` 里也一样。**大小写不敏感的
  匹配发生在执行阶段**（见 §5）。
- `LIMIT` 只接受非负整数字面量；`LIMIT -1` 是 `ParseError`。
- `x = NULL` 之类是 `ParseError`（提示改用 `IS NULL`）。
- 缺少 `FROM`、缺少表名、`ORDER BY` 后没列名、`LIMIT` 后不是整数、多出无法消化的
  token → 都是 `ParseError`。
- 空语句 / 全是空白 → `ParseError`，`position == 0`。
- 输入不是 `str` → `TypeError`。

## 4. `parser.py`

### `parse(sql: str) -> Select`

按 §3 解析，返回冻结的 `Select`。`where` 是 `tuple[Condition, ...]`（多个条件用 `AND`
连接，顺序即书写顺序）；`order_by` 是 `tuple[OrderKey, ...]`，`descending` 默认为
`False`；`limit` 是 `int` 或 `None`。

## 5. `engine.py`

### `execute(stmt: Select, table: Table) -> ResultSet`

1. **校验表**：`table.rows` 里任何一行长度与 `table.columns` 不一致 → `ExecutionError`。
2. **列名解析**：所有出现列名的地方（选择列表、`WHERE`、`ORDER BY`）都按
   **大小写不敏感**匹配 `table.columns`；匹配不到 → `ExecutionError`。
   - `columns == ("*",)` → 选中全部列，顺序同 `table.columns`。
   - 显式列名 → 顺序同 SQL；重复列名不去重；**输出列名用 `table.columns` 里的规范写法**
     （`SELECT NAME FROM t`，表里定义的是 `name`，则 `ResultSet.columns == ("name",)`）。
3. **过滤**：所有 `WHERE` 条件按 `AND` 语义。值的比较规则：
   - 左侧值是 `None`：除 `IS NULL` / `IS NOT NULL` 外，一律**不命中**（不是抛错）。
   - 左右类型不同（`int` vs `str`）→ `ExecutionError`。
   - 同类值按 Python 原生比较：`int` 比大小，`str` 按字典序。
4. **排序**：按 `order_by` 做多键排序。每行先按第一个键排，第一个键相等再看第二个键……
   - `ASC` 时 `None` 排在**所有值之前**；`DESC` 是同一个顺序的**完全反转**（`None` 排最后）。
   - 排序是**稳定**的：所有键都相等的行保持它们在 `table.rows` 里的先后顺序。
   - `order_by` 为空 → 保持源顺序。
   - 排序过程中出现不可比较的值（同一列里 `int` 和 `str` 混用）→ `ExecutionError`。
5. **截断**：`limit` 非 `None` 时只保留前 `limit` 行；`limit=0` → `ResultSet.rows == ()`。
6. 返回 `ResultSet(columns=<第 2 步解析出的规范列名 tuple>, rows=<投影后的 tuple>)`。
   不修改 `stmt` 和 `table`。

## 6. `format.py`

### `format_table(result: ResultSet) -> str`

定宽文本表，**逐字节稳定**：

1. 单元格渲染：`None` → `"NULL"`；`int` → `str(v)`；`str` → 原样。
2. 第 i 列宽度 = `max(len(列名), 该列所有渲染后单元格的最大长度)`（没有数据行时只看列名）。
3. 第一行是表头（`ResultSet.columns` 的原文），第二行是分隔行，之后每行一条数据。
4. 一行内的单元格用 `" | "` 连接；除**最后一列外**，每个单元格用空格右填充到该列宽度；
   最后一列不填充（所以行尾没有多余空格）。
5. 分隔行：每列写 `"-" * 宽度`，列与列之间用 `"-+-"` 连接。
6. 各行李连接，**结尾不带换行**。
7. `ResultSet.columns == ()` → 返回 `""`。

示例：`ResultSet(columns=("id", "title"), rows=((1, "Alien"), (2, "Arrival")))`

```
id | title
---+--------
1  | Alien
2  | Arrival
```

（`id` 列宽 2，`title` 列宽 7；最后一行不含结尾换行。）

## 7. 端到端示例

```
table = Table(columns=("id", "title", "year", "score"),
              rows=((1, "Alien", 1979, 85), (2, "Arrival", 2016, 79),
                    (3, "Solaris", 1972, 71), (4, "Stalker", None, 100)))

sql = "SELECT title, score FROM movies WHERE score >= 79 ORDER BY score DESC LIMIT 2"
```

`execute(parse(sql), table)` 的结果：

- `columns == ("title", "score")`
- `rows == (("Stalker", 100), ("Alien", 85))`
