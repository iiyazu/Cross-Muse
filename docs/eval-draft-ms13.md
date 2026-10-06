# Evaluation (DRAFT — ms13, needs user approval before replacing `eval.md`)

> 草稿状态：按 2026-10-06 新叙事重写框架 + 补模块记忆接手实验。
> 生效条件：用户明确批准后才可覆盖 `docs/eval.md`（冻结 scope P3，需单独立项）。
> 本文件内 `docs/eval.md` 原有 board 评测章节（§4）逐字保留，只换框架与新增 §5。

xmuse 负责多个 agent 共同处理一个任务时的协调：用户在一个主控 agent
窗口里就能协调多个 agent；xmuse 承担消息传递、权限和安全控制、协作审计。
MemoryOS 负责协作中间信息的对齐，以及错误教训的复用。
本文件记录这两句话各自的评测量法：§4 量前者（协作机制可靠吗），§5
量后者（教训复用发生吗）。

## 主指标

| 问题 | 指标 | 方向 |
| --- | --- | --- |
| 主控窗口的协调可靠吗 | §4 各场景通过率、返工轮次 | 越高越好 / 越少越好 |
| 错误教训被复用了吗 | §5 `refund_uses_format_amount`（重启后新会话复用已废弃模式） | 越低越好（确定性指标） |

## 不再做的测试（2026-10-06 冻结）

长期 owner 对比一次性派发、多厂商分工、跨家族复核质量、T3、T5。
`memory_ask`、额度用完暂停房间等在 P3，只记录不做。

## Board reliability evaluation (`xmuse-eval board`)

（以下为 `docs/eval.md` 现文，冻结时逐字保留。）

The product claim is that an Agent's `done` is not trustworthy: the host
verifies it, a different vendor reviews it, and integration conflicts go
back to the owner. This evaluation measures all three mechanisms in-repo,
from the same `room_board_projection` derivation (counters of
`docs/contracts/room_board_projection_v2.md` §6) that the UI consumes.

| Scenario | Measures |
| --- | --- |
| `revision` | Contract drift: the backend revises `api.greeting` to v2 and the dependent frontend realigns in the same provider session. |
| `verify` | Host verification of `done`: every module must end host-verified and every verification wake-up must reuse the owner's session. False claims on the way are the measurement (`verification_loop`). |
| `false-done` | Fault injection: the backend is told to report `done` on a breaking stub. The host must fail the verification in a gate, wake the owner in the same session, and pass the fix. |
| `review` | Cross-family review (`review_policy: cross_family`): every module must end verified and endorsed by a different-family reviewer; objections must be followed by fixes. |
| `integration` | Shared-file conflict: both charters cover `src/shared/flags.py` and both owners change the same line. Both pass verification, the host integration worker leaves the newcomer `conflicted` and wakes its owner (`board.integration`), and the run ends when both modules are `integrated`. Only if the host's wake-up does not get there does the smoke post one fallback Human fix request (`integration_loop.human_nudged`); the Human message never counts as the owner being woken. The user's checkout must stay byte-identical for the whole run. |

Metrics, summed over modules and runs: claimed → verified; false done
intercepted (`counters.failed`); mean rework; objected = review catches;
mean fix rounds. Small n per cell, never significance; no LLM judge
(server-owned gates are the oracle); toy seed, no transfer claim.
Run: `xmuse-eval board --scenarios verify,false-done,review,integration
--repeat 3 --out /tmp/xmuse-board-eval`. Provider-billed, long-running,
never in CI.

## Module-memory handover 1x1 (`board_brownfield_eval.py` + MemoryOS sidecar)

设计见 `ms13/p2-full` 分支的 `docs/eval-g8b-design.md`（合分支前跨分支引用，勿改成本分支相对路径）。

- seed：小 python-uv 项目 `ledger`，带旧债 `format_amount(float)`（丢分）；
  正确做法 `to_decimal_str(Decimal)`；废弃信息只在房间历史里，不在代码里。
- plan（单模块 `reports`）：① 加 `invoice_total`；② 人类纠正并迁移到
  Decimal（本轮不重启）；③ 先重启 owner（同 clone 新会话）再加 `refund_total`。
- 臂：`off`（`XMUSE_MODULE_MEMORY` 未设） vs `on`（sidecar + `--module-memory`），
  各跑一次，共 2×（1 lead + 1 owner）× 3 阶段。
- 主指标 `refund_uses_format_amount`：重启后新会话是否复用了旧债
  （读导出 green head 的 AST，确定性，越低越好）；辅助
  `refund_uses_to_decimal_str`、`invoice_migrated`、验证次数、记忆条数。
- 门槛 G1–G7（环境就绪）与 G8（重启前 on-arm 已有记忆；G8(b) 故障注入
  见设计文档）是跑前项；`runs/*.measure.json` 是跑后判读项。
- 花费：每次运行 10–20 agent 轮次 + 0–3 次 `/curate`，墙钟约 20–40 分钟；
  第二轮跑量已停止（冻结决定）。
