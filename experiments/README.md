# experiments —— xmuse 2 的对照实验种子与验收框架

这个目录是 M2 对照实验的**任务材料 + 验收工具**：三个需要多 agent 分工的小项目
（每个都带公开测试、隐藏测试、预埋 bug 和「中途被推翻的约定」），以及一个不依赖
任何第三方库的验证器 `verify.py`。

> **runner**：`run.py <场景> <编号>`（场景在 `scenarios/*.env`，用法见 `run.py` 文件头），
> 结果写到 `results/<场景>-<编号>/`，指标用 `metrics.py` 算。`verify.py` 不启动任何 agent。
> 默认阵容只用 opencode 和 dsh；claude agent 必须在 `AGENTS` 里显式写模型（`claude-1:claude:claude-haiku-5-5`），否则 runner 直接报错。

---

## 1. 三个种子任务

| 任务 | 三条切片 | 跨切片约定（最容易踩的） | 公开 / 隐藏测试 | rot |
|---|---|---|---|---|
| `ledger` | `parse.py` 解析 → `rules.py` 汇总 → `report.py` 报表 | 金额一律**有符号整数分**；`(币种, 类目)` 二元桶 | 13 / 39 | 金额改成十进制字符串；未匹配交易改成 `uncategorized` |
| `minisql` | `parser.py` 解析 → `engine.py` 执行 → `format.py` 定宽表格 | `ParseError.position` 是 0-based 字符下标；列名大小写不敏感匹配 | 14 / 47 | `NULL` 排序位置翻转；结果格式改成 TSV |
| `pipeline` | `parse.py` 定义文本 → `schedule.py` 分层调度 → `log.py` 日志格式 | `order` 必须等于 `levels` 展平；`CycleError.cycle` 的起点与方向 | 10 / 44 | 同层平局改成书写顺序；日志改成按层分段 |

三个任务的形状是刻意不同的，用来观察 agent 在不同「跨切片约定」下的表现：

- `ledger` 的约定是**数值/单位**（整数分）；
- `minisql` 是**错误定位与匹配语义**（字符下标、大小写、`NULL`）；
- `pipeline` 是**顺序与格式**（拓扑顺序、平局规则、每步一行）。

每个任务都能塞进一次会话（一个人一两百行），但**一个人写不完**：三条切片各有自己的
边界，公开测试只覆盖 happy path，隐藏测试专打跨切片约定。

## 2. 目录和文件

```
experiments/
├── README.md                        # 本文件
├── verify.py                        # 验收器：跑全部检查，见 §3
├── seeds/<task>/                    # 发给 AGENT 的 SEED 仓库（rot 之前的老约定）
│   ├── README.md                    #   任务说明 + 分工建议 + 跨切片的坑
│   ├── SPEC.md                      #   唯一的接口契约（数据结构、错误、语义）
│   ├── .gitignore                   #   忽略 __pycache__/、*.py[cod]、虚拟环境
│   ├── <pkg>/                       #   骨架：只有签名，函数体 raise NotImplementedError
│   │   ├── types.py                 #   冻结契约（数据结构 + 错误类型），已完成
│   │   └── ...                      #   三条切片各一个文件
│   └── tests/test_public.py         #   公开测试：骨架上能跑、且全部失败
├── reference/<task>/<pkg>/          # 参考实现：公开测试和隐藏测试全过
├── hidden/test_hidden_<task>.py     # 隐藏验收测试：跑完才拷进去，agent 看不到
├── planted/<task>/                  # 预埋 bug（复核方看不到）
│   ├── BUGS.md                      #   每个 bug 的类型、位置、抓它的隐藏测试方法名
│   ├── bug-1/<pkg>/<file>.py        #   整文件替换，路径与 reference 一致
│   └── bug-2/<pkg>/<file>.py        #   两个 bug 永远在不同文件
├── rot/<task>.md                    # 中途被推翻的约定：新约定正文、时机、检查方法
│   post_rot_test_<task>.py          #   检测器：在参考实现上必须失败，改对了才通过
├── reference-rot/<task>-rot<n>/<pkg>/   # 按新约定改过的参考实现（n = 1, 2，各自独立基于 reference）：
│                                    #   只放与 reference 不同的文件，用法是叠在 reference/<task>/<pkg> 上
├── rot-affects/<task>-rot<n>.txt    # 该 rot 按设计会弄挂的隐藏用例（Class.method，一行一个），由 rot_affects.py 生成
└── rot_affects.py                   # 生成/核对上面的清单：`python3 rot_affects.py [--check]`
```

两点说明：

- **`BUGS.md` 放在 `planted/<task>/`**，不在 `seeds/<task>/`（H5 规划稿里写的是后者）：
  按 ledger/minisql 已经落地的布局走，种子仓库里不留任何「这是预埋 bug」的痕迹。
- `rot/<task>.md` 里同时记了**判分口径**：`followed` / `partial` / `ignored`，
  以及每条护栏用例（在参考实现上本来就过，用来抓「改过头」）。

## 3. `verify.py` 的用法

```
python experiments/verify.py                 # 三个任务全跑（21 项检查）
python experiments/verify.py -t pipeline     # 只跑一个任务（可重复 -t）
python experiments/verify.py -v              # 失败时把子进程输出打出来
```

- 工作方式：每个检查把 `reference/`（或 `seeds/`）和测试拷进一次性临时目录，
  在临时目录里跑 `sys.executable -m unittest discover`；种子仓库里不会留下
  `__pycache__` 或临时文件。子进程带 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`。
- 环境变量 `M2X_VERIFY_TMP`：把临时树指到一个受限沙箱允许写的位置（默认用系统临时目录）。
- 退出码：0 = 全部通过；1 = 有检查失败（或一个检查都没跑）。
- 没上架的任务会被跳过并打印 `[SKIP] ...`（`TASKS` 全集在 `verify.py` 顶部；
  `pipeline` 曾经就是靠这一条跳过的）。

每个任务跑 **7 项检查**，外加每个 rot 的 **3 项轮换检查**（见表后）：

| 检查 | 期望 | 为什么 |
|---|---|---|
| reference 过公开测试 | 通过 | 参考实现确实符合 SPEC |
| reference 过隐藏测试 | 通过 | 隐藏测试不是无法满足的 |
| 骨架过公开测试 | **失败** | 任务没有被预先解掉 |
| 骨架过隐藏测试 | **失败** | 同上 |
| bug-1 被隐藏测试抓到 | **失败** | 预埋 bug 是活的（≥1 条隐藏用例挂） |
| bug-2 被隐藏测试抓到 | **失败** | 同上，且和 bug-1 不在同一个文件 |
| rot 检测器在原约定上失败 | **失败** | rot 用例编码的是新约定，不是空转 |

轮换检查（`<task>-rot<n>`，n = 1, 2）：轮换参考实现过对应的 post-rot 用例；`rot-affects/<task>-rot<n>.txt`
与它在隐藏测试上实际失败的用例一致；去掉清单里的用例后，隐藏测试在它上面全过。

### 加一个新任务

1. 写 `seeds/<task>/`（README、SPEC、骨架、`tests/test_public.py`、`.gitignore`）；
2. 写 `reference/<task>/<pkg>/`，跑公开测试到全绿；
3. 写 `hidden/test_hidden_<task>.py`，参考实现上全过；
4. 把两个预埋 bug 放进 `planted/<task>/bug-1`、`bug-2`（不同文件）并写 `BUGS.md`；
5. 写 `rot/<task>.md` 和 `post_rot_test_<task>.py`，确认检测器**可满足**
   （至少用一份手工改过的实现验证过它真的能通过）；
6. 在 `verify.py` 的 `TASKS` 里加一行，跑 `python experiments/verify.py`。

约定了但没写进 SPEC 的东西，隐藏测试**不许**考——`SPEC.md` 是唯一契约。

## 4. 实验组

同一个任务、同样的多家 agent，分四组对照（§4.5 的 A/B/C，加 H5 的长会话组）：

| 组 | 唤醒方式 | 对齐层 | 目的 |
|---|---|---|---|
| **A** | 全员群聊：每条消息都唤醒所有成员 | 无 | 基线：最吵、最贵，看对齐质量的上限 |
| **B** | 点名唤醒（`mentions` / `handoff`） | 无 | 省掉噪音之后，缺不缺协作信息 |
| **C** | 点名唤醒 | 有（启动包 + 差量注入 + 申报） | 完整方案：对齐信息层值不值它自己的 token |
| **长会话** | 同 C | 有 | 会话跑到**数十万 token** 时（含 compact），对齐是否还成立、单次唤醒成本涨到多少 |

长会话组的关键是两件事：rot 测试是否仍然全过（rot 不发生），以及
`context_tokens` 变大之后每次唤醒的成本曲线（注入量应当只是零头）。

## 5. 指标定义

所有 per-turn 数据来自 hub 的 `turns` 表（`agent_id`、`mode`、`input`、`cache_read`、
`cache_write`、`output`、`context`，M2a 起还有 `align_tokens`、`align_mode`），
消息来自 `messages`，对齐条目来自 `entries` / `entry_events`。

| 指标 | 定义 | 数据来源 |
|---|---|---|
| **完成率** | 公开测试 + 隐藏测试都通过的任务数 / 该组任务数（每个任务至少 5 次）。**注入过 rot 的 run**：公开测试通过 + 隐藏测试中**不在** `rot-affects/<task>-rot<n>.txt` 里的用例全过 + rot 遵守为 `followed`（旧约定的隐藏用例按设计会挂，不计入）；`metrics.json` 同时给出原始 `hidden` 与 `hidden_unaffected`（过/总） | 复跑 `tests/test_public.py` 与 `hidden/test_hidden_<task>.py`（`-v`，逐用例结果存 `hidden-tests.json`） |
| **轮次** | 一次 run 的 `turns` 行数；按 agent、按 `mode`（chat/code）拆开看 | `turns` |
| **token** | `Σ(input + cache_read + cache_write + output)`，按 agent / 按组汇总 | `turns` |
| **人介入次数** | 人类消息数 − 1（首条任务消息不算介入）；公告类 notice 单独列出 | `messages`（`check.py` 的 `human_interventions` / `notices`） |
| **注入占比** | `align_tokens / 该回合总输入 token`；报告按 run 的合计与每回合中位数/最大值，目标 **≤ 5%** | `turns.align_tokens`、`turns.align_mode`（snapshot/delta/none） |
| **视图曲线** | 每次唤醒时刻，该 agent 现行视图的**条目数**随轮次变化；期望先涨后平、不随历史线性增长 | hub 的视图计算（通用 40 / 角色 20 / 话题 15 的分层上限） |
| **rot 遵守** | rot 之后，该 agent 的产出在 `rot/post_rot_test_<task>.py` 上的表现：`followed`（全过）/ `partial`（部分过）/ `ignored`（全挂） | `rot/post_rot_test_*.py` |
| **申报率** | 复核（人工 + `/curate`）找出的「别人会依赖的决定/假设」中，事先以 `entries` 申报过的比例（`kind ∈ {decision, assumption}`，`author` 是该 agent） | `entries` / `entry_events` + 复核清单 |
| **复核检出率** | 复核方**正确指出**的预埋 bug 数 / 该任务预埋 bug 总数；同时记误报率（把没埋 bug 的切片也报成 bug） | `planted/<task>/BUGS.md` + 复核意见 |

补充口径：

- **注入占比**的分母是「该回合总输入 token」（`input + cache_read + cache_write`），
  不是只算新输入——缓存命中也是模型要处理的上下文。指标里同时给出 `align_mode` 分布，
  否则 snapshot 回合的尖峰会把均值带偏。
- **视图曲线**按 `(agent, 任务阶段)` 画；同一个 agent 在两个任务之间的条目数不可比。
- **rot 遵守**按 `(agent, rot)` 判，再和 `check.py` 的 `human_interventions` / `notices`
  对齐，就能看出一次「推翻约定」有没有真的传达到每个 agent。
- **复核检出率**只看预埋 bug 是否被明确指出（说清楚在哪、为什么错），
  「感觉这里可能有问题」不算检出；`format.py` / `log.py` 这类**没埋 bug** 的切片
  用来算误报率。

## 6. 一轮实验怎么跑（等 runner）

预期形态（细节等 hub 的 M2a 完成后定）：

```
输入：  场景 env（SEED=ledger|minisql|pipeline、IMPL、REVIEW、GOAL、组别 A/B/C/长会话）
        + rot 注入脚本（在第 N 轮之后发一条「决定（supersedes：…）」消息）
输出：  results/<run-id>/   —— log.json（messages/turns/agents）、各 agent 的仓库快照、评审意见
汇总：  python context/check.py <results-dir> <impl> <reviewer> <public> <hidden> <seconds> <rc>
        再按 §5 的公式算指标，落到实验报告
```

`log.json` 里的 `turns`、`messages` 结构就是 `check.py` 现在读的那套；runner 只需要
把 A/B/C 组别翻译成「唤醒规则 + 是否注入对齐包」，再在 rot 时机插一条消息。

## 7. 和 hub 的衔接

对齐层（hub 侧，M2a）和这里的关系：

- hub 负责 `entries` / `entry_events`（双时间、显式作废）、分层视图、水位和差量注入，
  以及 `turns.align_tokens` / `align_mode` 的采集；`experiments/` 只负责任务、测试和判分。
- 本目录的三个任务同时充当两种仪器：
  - **验收仪器**：隐藏测试判「任务做完了没有」；
  - **实验仪器**：预埋 bug 判复核方（检出率 / 误报率），rot 用例判各 agent 是否跟着
    被推翻的约定走。
- 另一批材料（会话侧 e2e）在 `context/`：`context/seeds/{textkit,durations,inventory}`、
  `context/scenarios/{s1–s3,b1–b4}.env`、`context/hidden/`、`context/check.py`，
  还有 `context/XMUSE2-*.zh.md` 的规划与设计稿。它们不属于 `experiments/`，
  但 `check.py` 的口径与本文件 §5 一致。

## 8. 约定（维护须知）

- **只用 Python 3 标准库**；隐藏测试在 Windows 和 WSL 两边的 Python 下都要能跑
  （不要依赖 shell、路径分隔符、locale；`.py` 文件保持 ASCII）。
- 种子仓库带 `.gitignore`（`__pycache__/` 等）；**不要修改 `tests/test_public.py`**，
  不要把一次性探针脚本提交进种子仓库。
- 先改 `SPEC.md` 和 `types.py`，再改实现——`types.py` 是冻结契约。
- 参考实现不许为了让某个检查通过而削弱；检查挂了先怀疑 bug 变体或隐藏测试。
