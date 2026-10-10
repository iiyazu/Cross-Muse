# base 汇报：rc/portfolio

base 侧 Claude（Opus 5.5）。环境：Windows 主机上的 Arch WSL，克隆在 `/mnt/d/Dev/xmuse2`（NTFS 经 9p 挂载，I/O 比 r7 原生盘慢，测试耗时偏高）；Python 3.13.15（uv），node v26.10.0。

## T1 整合（2026-10-11）

**做了什么**
- 第一次合并做在旧的 `f4d6000` 上，无冲突。收到 §6 更正后，丢弃这个未推送的合并，在 `938863e` 上重做：`git merge --no-ff origin/m2b`，无冲突。
- m2b 只带进了 `248b15b` 的两个文件：`experiments/replay_mo.py`、`tests/test_replay_mo.py`。和 §6 说的一致：m2b 的其余部分早已是 dsh/bundle 的祖先。
- 环境：`uv sync --project hub`、`cd shim && npm ci` 都成功。

**提交**：`bc6982b`（merge m2b）

**测试结果原文**（合并后、T2 改动之前，加了 `-x`）：
```
FAILED tests/test_mail.py::test_handoff_keeps_why_first_fields - IndexError: ...
1 failed, 145 passed in 215.98s (0:03:35)
```
- 原因是测试自身的竞态，和合并无关：引擎线程准入时把投递标为已读，测试随后用默认的 `unread_only` 读 inbox。在 /mnt/d 上稳定复现；r7 更快，所以没暴露。同类的还有 `test_inbox_orders_mentions_first_and_marks_read` 和 `test_wakepack.py::test_equal_state_renders_byte_identical`。三处都在 T2 修了：测试里先暂停收件 agent，没改断言。
- `experiments/` 和 `replay_mo` 的单测在 T2 的全量结果里，全部通过。

**没做 / 拿不准**
- 没有在 `bc6982b` 上不加 `-x` 再跑一遍全量。上面的竞态在 T2 之后都消失了，结果见 T2。

## T2 待修清单（2026-10-11）

**提交**：`b577c4e`

| 项 | 结论 / 做法 | 测试 |
|---|---|---|
| 1 `woken` 列出桌面 agent | dsh/bundle 上已修（`mail.py` 返回时剔除桌面 agent）。补测试固定行为：DM 给协调者时 `woken == []`，且不会启动回合 | `test_via.py::test_woken_never_lists_the_desktop_coordinator` |
| 2 worktree 里 `.git/info/exclude` 写错 | 改为写到 `git rev-parse --git-common-dir` 下；没有 git 时退回解析 `.git` 文件里的 `gitdir:` 和 `commondir` | `test_init_cli.py::test_init_in_a_linked_worktree_writes_the_common_exclude`（用 `git status --ignored` 验证 git 确实忽略了这些文件） |
| 3 channel 回合 ctx=0 | **根因有实证**：只读查询 r7 `xmuse2-dog` 的 hub.db，turn 3（claude_channel）记的是 context=0、calls=0；但 transcript 里这一回合的 assistant 记录时间是开始后 2.13 s 和 4.51 s，Stop hook 在 4.59 s 到达。单次调用的回合，记录在 Stop 之后才落盘。做法：读不到记录时在后台线程里最多等 3 s 再记账，hook 本身不阻塞 | `test_units.py::test_channel_stop_waits_for_late_transcript_flush` |
| 4 `xmuse transcript <agent>` | 新模块 `transcript.py`，只读。Claude 读 `~/.claude/projects/<cwd>/<sid>.jsonl`，流式重复的块只取一次；dsh 读 `sessions/*/<sid>/session.v4.jsonl.zstd`，跳过 system-reminder 和运行时上下文注入；OpenCode 经 hub 新增的 `/v1/admin/oc_messages` 调 `GET /api/session/{id}/message`（分页），因为服务器密码只有 hub 持有。`--path` 可以直接读文件，`--clip` 控制每条的截断长度 | `tests/test_transcript.py`（三家解析器各一个，另有一个 CLI 端到端） |
| 5（§6 追加）多余唤醒（审计 B2-3） | 准入前两条规则：已 ack 的投递直接置 done；已读、且本 agent 之后在同一线程发过消息的，也置 done。**已读但没回应的照常唤醒**，因为审计说链断比多花 token 代价高 | `test_claude_engine.py::test_mail_already_handled_mid_turn_wakes_nobody`、`::test_read_but_unanswered_mail_still_wakes` |
| 6（§6 追加）测试慢 | `Hub.shutdown` 往引擎队列放 `("stop",)` 哨兵；`serve_forever(poll_interval=0.05)`。`test_stop_interrupts_running_turn_and_cancels_queue` 收尾时也停掉第二个 agent，不再等假 agent 睡满 30 s | 全量耗时见下 |

**测试结果原文**
- 工作区全部改动（含 T3 的半成品），`/mnt/d`：
  ```
  297 passed, 1 skipped in 141.87s (0:02:21)
  ```
- 只含 T2 的暂存快照（`git checkout-index` 导出到 /tmp，`PYTHONPATH` 指向快照）：
  ```
  FAILED tests/test_wakepack.py::test_equal_state_renders_byte_identical - Asse...
  1 failed, 295 passed, 1 skipped in 123.76s (0:02:03)
  ```
  这是第三处同类竞态，修好后 `tests/test_wakepack.py` 连跑 3 次都是 `20 passed`，然后才提交。修好后没有在快照上重跑全量。

**没做 / 拿不准**
- B2-3 的第 3 条（2–5 秒去抖、合并连发）没做：它会给每次唤醒都加上延迟，属于取舍，请 r7 定。
- "已读且之后回应过"的判定用的是同一线程里、`read_at` 之后有本 agent 发的消息，不看回应内容是否针对这条。偏保守：误判的结果是多唤醒一次，不会断链。
- `test_units.py::test_sweep_interrupts_turns_past_the_timeout` 在一次高负载的全量里超时一次（11.29 s，等待上限 10 s），单独跑 2 次都在 1.6 s 内通过。怀疑是 SIGINT 后 5 s 才升级到 SIGTERM 的路径在负载下太紧，没有深挖。
- 2 分钟目标：/mnt/d 上约 140 s。r7 原生盘上应该更快，但我没在 r7 上跑。
- OpenCode transcript 的字段是按 r7 上 opencode v2.0.21 的 `/openapi.json` 写的（起了一个一次性服务器、空目录、没有模型调用，只读取 schema）。没有在真实会话上试过。
- 桌面版 Claude 的 transcript 在 Windows 侧，路径推不出来时会提示用 `--path` 指定。
