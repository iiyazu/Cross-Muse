# G8(b) 故障注入设计 — 门1待批（DRAFT）

状态：设计稿，等用户批准后才实施（铁律门1：设计批了才动 plan 文件；门2：跑 r7 前另需批准 + key 由用户单独给）。
动议范围：只改 r7 `~/handover/plan-handover.json` 第 1 阶段任务文本。
不碰：seed 仓库、`xmuse/`、`src/xmuse_core/`、driver、measure.py、r7 脚本、任何产品语义。

## 1. 背景

P2 1x1（开关关一次、开一次）卡在 G8：idle-flush 已按冻结要求 revert，
窗口只在门禁失败 / 复核反对 / 累计 12 条消息时送出。按当前 plan，
第 1、2 阶段预计只有约 8–11 条符合条件的活动且无门禁失败，
开关开的那组在重启前很可能一条记忆都没有 —— 1x1 测不出任何东西。

用户已批方向（交接包 §5 附带项 4）：G8 走哪条路径由用户选。
本设计对应路径 (b)：改 plan，让第 1 阶段产生一次门禁失败。
(a) 照跑、(c) 不跑仍是备选，见 §7。

## 2. 改动（精确到行）

文件：r7 `~/handover/plan-handover.json`（git 之外，见 §6 版本记录方式）。
只改 `modules[0].task`，在原文末尾加一句话。其他 4 处（title、两个
follow-up、module 结构）一字不动。

原文（第 1 阶段 task）：

> Add `invoice_total(lines: list[tuple[float, int]]) -> str` to
> src/ledger/reports.py. It returns the formatted grand total of all lines
> (price times quantity, summed), formatted like the other report functions.
> Add a test for it next to the existing tests. Commit, then report done.

改为（追加一句）：

> Add `invoice_total(lines: list[tuple[float, int]]) -> str` to
> src/ledger/reports.py. It returns the formatted grand total of all lines
> (price times quantity, summed), formatted like the other report functions.
> It must be Decimal-precise: `invoice_total([(2.675, 1)])` must equal
> `'2.68'`. Add a test for it next to the existing tests. Commit, then
> report done.

## 3. 为什么这一定（几乎一定）产生一次门禁失败

- seed 现状（r7 `~/handover/seed` 已核实）：`reports.py` 的四个旧函数全用
  `format_amount(float)`；`format_amount` 做 `f"{round(value, 2):.2f}"`。
- 数值事实（Arch 本地 python3 实测，纯计算无 quota）：
  `round(2.675, 2)` → `2.67`（二进制浮点 2.675 存的是 2.67499…），而
  `Decimal(str(2.675))` 半向上取整 → `'2.68'`。
- 行为推演：owner 按任务前半句“和其他 report 函数一样格式化”最顺手写出
  `format_amount` 版本，自带测试断言 `'2.68'`（任务后半句要求）→ 门禁
  （pytest）红 → `board.verification failed` → `gate_failure` 窗口立即
  flush（阈值见 `room_module_memory.py:29/32/33/41`，失败不等 12 条）→
  on-arm 产生第 1 条 lesson（“float 丢分，改用 to_decimal_str”类）。
  owner 随后改用 Decimal（phase-2 的词汇已在房间历史外等着）→ 门禁绿 →
  阶段继续。
- 计数：phase-1 即使不计进度汇报，`1 条人类任务 + 1 次失败 verification`
  已触发 flush；与“8–11 条不到 12 条”的旧推断不再相关。

## 4. 对实验其余部分的影响（已核对）

- phase-2（人类纠正 + 迁移 invoice_total）：若 phase-1 已在修复中迁完，
  phase-2 退化为“复核确认 + 报告 done”，不报错（follow-up 只是发人类消息，
  driver 不校验内容）。度量 `invoice_migrated` 照常为真。
- phase-3（重启后加 refund_total）与主指标
  `refund_uses_format_amount`：不受 task 文本影响；off-arm 与 on-arm 跑的是
  同一份 plan，臂间可比（开关关时行为逐字不变是合同保证）。
- quota 影响：每臂至多 +1～2 个返工轮次（一次失败 + 一次修复验证），
  无新增 phase、无新增 sidecar 调用。
- measure.py：无需改动。它已读 `room_module_memories`（kind:status 计数）、
  `room_board_verifications`（status 计数）与 `memory.md` —— G8 成功判据
  可直接从 `*.measure.json` 读出（见 §5）。

## 5. 成功判据（跑完后检查，不在跑前假设）

- on-arm：`memories` 非空（至少 1 条 lesson/active），且重启前已有
  （`room_module_memory_runs` 有 `done` 行；必要时 sqlite 查
  `first_seq/last_seq` 落在重启前）。
- off-arm：`memories` 为空（开关关不断言行为变化，只断言无记忆写入）。
- 若 on-arm 仍无记忆（例如 owner 第一次就写对 Decimal）：本轮记为
  “G8 未触发”，结论按路径 (a) 记录，不硬解释。这是设计内已接受的降级，
  不是失败（见 §7）。

## 6. 版本与审计记录方式（NEEDS-REVIEW：plan 文件不在 git）

- `plan-handover.json` 在任何仓库之外（r7 `~/handover/`，Arch 本地与两个
  worktree 全无此文件，已全局 find 确认）。实施时：改前
  `cp plan-handover.json plan-handover.json.bak-YYYYMMDD`，改后记录
  `sha256sum` 到进度行；恢复只需拷回备份。
- 是否需要把 plan 复制一份进 `ms13/p2-full` 做评审留痕，由用户定。
  默认建议：不进（与现有做法一致：seed 是独立 pin 住的 repo，plan 是
  handover 现场文件；设计本文档即评审依据）。

## 7. 备选路径（用户二选一时用）

- (a) 照跑：不改任何文件，把“on-arm 重启前有无记忆”本身记为结果。
  花费与 (b) 相同，信息量较小。
- (c) 不跑：等 idle-flush（或“阶段结束送窗”）有产品层决定再说。
  本设计不预设 (c) 的任何产品改动。

## 8. r7 运行准备自查表（run 前逐项打勾，不跑）

脚本核对（2026-10-0X 只读核实，均无需改动）：

- `r7_run_1x1.sh`：读 `--plan "$H/plan-handover.json"`（§2 的改动自动生效）；
  先跑 `off` 再跑 `on`；`on` 起 sidecar（随机 key、不落盘、跑完按 pid 杀），
  落 `runs/off.json`、`runs/on.json`、`runs/*.log`、`runs/sidecar.log`；
  已存在 `runs/<arm>` 目录则跳过（重跑前需先处理旧目录，删目录先报批）。
- `r7_gate_check.sh`：G1–G7 只读检查；注意 G1 会把 `~/handover/xm`
  ff 到 `origin/feat/handover-eval` 最新 —— 本设计不依赖任何分支提交，
  不受影响。
- `measure.py`：读 `result-repo` + `chat.db`，AST 判定三字段；
  输出 `*.measure.json`。无需改动。

门槛（门2批准 + key 到位后，跑前重验）：

- [ ] `ssh r7 'bash ~/handover/r7_gate_check.sh'` 7 行 PASS
- [ ] `sha256sum ~/handover/plan-handover.json` 与进度行记录一致（§2 已实施）
- [ ] `~/handover/runs/` 为空或旧结果已按批处理（删前报批，门4）
- [ ] 端口 8320 空闲、无残留 sidecar（只按 pid 杀，不按路径匹配）
- [ ] tmux 会话名 `handover`，命令：`tmux new -s handover 'bash ~/handover/r7_run_1x1.sh'`
- [ ] 跑后收 `runs/off.measure.json`、`runs/on.measure.json`，按 §5 判读

NEEDS-REVIEW（run 前需确认，不在本设计内下结论）：

- driver 对 verification-failed 是否按“返工继续”而非“整轮 abort”处理。
  依据现状：这是 driver 既有行为（off-arm 同样依赖），1x1 设计未改；
  若用户要求书面确认，跑前在 r7 对 `board_brownfield_eval.py` grep
  一次 verification 失败分支即可（只读）。
- 本设计假设 owner 自带测试会断言 `'2.68'`（任务文本明确要求）。
  若某臂 owner 没写该断言而门禁全绿通过，G8 仍未触发 → 按 §5 降级记录。
