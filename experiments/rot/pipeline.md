# pipeline 的 rot 方案（任务中途由人推翻的约定）

实验做法：给 AGENT 的 SEED 是 `seeds/pipeline/`，SPEC.md 里写的是**旧约定**。
在指定的时机，人在群里（或通过 runner 的注入消息）发一条新的决定，推翻其中一条约定。
之后所有 agent 的产出按新约定验收。

检测器：`rot/post_rot_test_pipeline.py`（每个 rot 一组用例）。
在原始参考实现上这组用例**必须失败**（`verify.py` 会验证这一点），
只有真正按新约定改过的实现才会让它通过。八个用例里有两条是「护栏」用例
（`test_rot1_dependencies_are_still_respected`、`test_rot2_empty_schedule_is_still_empty`），
它们在参考实现上本来就过，用来抓「改过头」——判分时要和另外六条区分开。

**检测器可满足性**（已用一次性改过的参照验证，探针不提交）：

| 只遵守 | 通过 |
|---|---|
| 什么都不改（参考实现） | 2/8（两条护栏） |
| 只做 ROT-1 | 5/8（ROT-1 四条全过，ROT-2 三条判别用例仍挂） |
| 只做 ROT-2 | 5/8（镜像） |
| 两个都做 | 8/8 |

ROT-1 的日志用例刻意写成**格式无关**（只比较步骤行的先后），所以 ROT-2 改了行格式之后
它仍然成立；否则「两个 rot 都遵守」反而过不了，检测器就自相矛盾了。

---

## ROT-1：同层平局规则从「名字升序」改成「定义文本里的书写顺序」

**推翻的约定**：`SPEC.md` §5.4 / §5.5 的「`levels[k]` 里的节点按**名字升序**；
`order` 是 `levels` 展平」。

**新约定（注入消息的正文，直接给 agent）**：

> 决定（supersedes：同层按名字升序）——从这一轮起，同一层里的节点按它们在
> **任务定义文本里出现的先后**排列，不再按名字升序。`order` 仍然是 `levels` 展平，
> 所以 `order` 的顺序也跟着变；跨层的先后关系不变。
> 名字只用来保证确定性，不再是平局规则。

**推翻时机**：切片 B（`schedule.py`）第一轮完成、公开测试全绿、复核方已经按旧约定
复核过一轮之后。此时 `sorted(...)` 这个写法已经在 `schedule.py` 里，考的是能不能把
「层内顺序」和「层间顺序」分开改对，而不是把 `sorted` 换成 `reversed`。

**检查方法**：

| 用例名 | 检查什么 |
|---|---|
| `RotOneWrittenOrderTies.test_rot1_levels_follow_the_written_order` | 定义文本 `zeta / alpha / mid: zeta` → `levels == (("zeta", "alpha"), ("mid",))` |
| `RotOneWrittenOrderTies.test_rot1_order_follows_the_written_order` | `order` 仍是层展平，且等于 `("zeta", "alpha", "mid")` |
| `RotOneWrittenOrderTies.test_rot1_log_follows_the_written_order` | 日志步骤行的先后是 `zeta → alpha → mid`（只看顺序，不看行格式） |
| `RotOneWrittenOrderTies.test_rot1_dependencies_are_still_respected` | 护栏：`mid` 仍然在第 1 层、只有两层 |

**易错点（用来区分「真改了」和「看起来改了」）**：

- 只把 `levels` 改了、`order` 还在用另一次排序 → 第 2 条挂（这正是预埋 bug-2 的形状）；
- 顺手改成「按名字**降序**」而不是书写顺序 → 第 1 条挂；
- 为了让日志跟着变，把 `order` 改成从 `levels` 之外重算 → 第 2 条挂；
- 把层间顺序也一起改了（比如按书写顺序做全局拓扑）→ 第 1、4 条挂。

---

## ROT-2：执行日志从「每行自带 `L<k>` 前缀」改成「按层分段」

**推翻的约定**：`SPEC.md` §6.3 的行格式 `{i}. L{level} {status} {node}[: detail]`。

**新约定（注入消息的正文）**：

> 决定（supersedes：日志每行自带 `L<k>` 前缀）——从这一轮起，日志按层分段：
> 每个层级先输出一行 `--- L<k> ---`，后面跟着这一层的步骤行；
> 步骤行格式改为 `{i}. {status} {node}`，`detail` 非空时仍然追加 `": " + detail`。
> 序号从 1 开始、**跨层连续**、不补零；空计划仍然输出空串，结尾仍然不带换行；
> `detail` 不含换行这条硬约定不变。

**推翻时机**：第二轮结束时（任务接近收尾、复核方已经批准过一轮）。
考的是收尾阶段还能不能把一条纯格式约定改干净——尤其是「序号跨层连续」这条，
按层各从 1 开始编号是最容易犯的错。

**检查方法**：

| 用例名 | 检查什么 |
|---|---|
| `RotTwoLevelHeaders.test_rot2_level_headers_and_plain_step_lines` | `--- L0 ---` / 两条步骤行 / `--- L1 ---` / 一条步骤行，序号 1–3 连续 |
| `RotTwoLevelHeaders.test_rot2_step_lines_drop_the_level_prefix` | 去掉 `---` 行后，步骤行是 `1. ok build` 这种，没有 `L0` |
| `RotTwoLevelHeaders.test_rot2_a_single_level_still_gets_a_header` | 只有一个层时也要输出层头 |
| `RotTwoLevelHeaders.test_rot2_empty_schedule_is_still_empty` | 护栏：空 `Schedule` 仍然输出 `""`（不是一行 `--- L0 ---`） |

**易错点**：

- 忘了层头，只删了 `L<k>` 前缀 → 第 1、3 条挂；
- 序号按层重新从 1 开始 → 第 1、2 条挂；
- 空 `Schedule` 也输出一个层头 → 护栏用例挂；
- 把 `detail` 里的换行放过（想「反正一行放不下」）→ 隐藏测试
  `TestLogHidden.test_detail_must_be_one_line` 那一类约定被破坏，属于改过头。

---

## 两个 rot 的判分口径

对每个 agent、每个 rot：

- `followed`：该 rot 对应的全部用例（含护栏）通过；
- `partial`：至少一条通过、至少一条失败（局部对齐或改过头，最有信息量的一档）；
- `ignored`：全部失败（或者根本没改）。

ROT-1 落在 `schedule.py`（层内顺序），ROT-2 落在 `log.py`（行格式）；
`parse.py` 这一片在两个 rot 里都不用动，用来当对照：复核方如果把「没被 rot 波及的切片」
也报成需要改的地方，可以在 rot 遵守率之外再算一个误报率。

把这三种状态和 `check.py` 的 `human_interventions` / `notices` 对齐，就能看出
一次「推翻约定」有没有真的传达到每个 agent。
