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

## T3 可移植性（2026-10-11）

**提交**：`0152899`

**做了什么**
- 新增 `hub/src/xmuse/host.py`，统一推导两件事：
  - WSL 发行版：先看 `XMUSE_WSL_DISTRO`，再看 `WSL_DISTRO_NAME`。
  - Windows 家目录：先看 `XMUSE_WIN_HOME`，再用 `cmd.exe` 取 `%USERPROFILE%`，经 `wslpath` 转换。
  - 推导不出就报错，并写明该设哪个变量。原先的 `Ubuntu-24.04` 和 `/mnt/c/Users/$USER` 默认值都去掉了，`base.to_win`、`claude._distro`、`dsh._distro` 以及 dsh 的 exe/clijs/home 都改为调用它。dsh 的 exe 和 home 在 config.json 里显式配置时，仍以配置为准。
- dsh 插件包：
  - 删掉内置的 `\\wsl.localhost\Ubuntu-24.04\home\user\...` 默认值。没配 `config.state` 时，自检和工具调用都给出明确提示，并指向 `xmuse doctor`。
  - `sync.sh` 的默认目标改为推导；`cordis.patch.yml` 和 README 里的路径改成占位符。
  - 新增一条 node 测试。
- `scripts/bootstrap.sh`：检查 uv、node、npm → `uv sync --python 3.12` → shim `npm ci` → `xmuse doctor`。可以重复执行。
- `xmuse doctor`（只读）：
  - 检查 Python 版本和依赖、node 和 shim 依赖、WSL 推导结果、各厂商 CLI（只在已配置的 agent 用到时判 FAIL）、hub 是否在跑和陈旧的 hub.json、tools.json、skill、AGENTS.md 的 xmuse 段，以及每个 agent 的 .mcp.json 或 opencode.json（是否指向本 agent、本状态目录、本 checkout 的 shim）。
  - 有前台 dsh agent 时，打印插件 `config.state` 应填的 UNC 路径。
  - 每个问题都附修复命令；有 FAIL 时退出码为 1。
- conftest 固定了 host 推导结果（`WSL_DISTRO_NAME=Ubuntu-Test`，`XMUSE_WIN_HOME` 指向临时目录），这样在普通 Linux CI 上跑结果一样。原来断言默认值是 `Ubuntu-24.04` 的测试，改为断言"必须报错，设了覆盖变量后生效"。

**验收：全新克隆**（`/tmp` 原生盘。克隆的是已推送的 rc/portfolio，再叠加本地 T3 文件）
- `scripts/bootstrap.sh` 一次跑通：uv 自动下载了 CPython 3.12.14，npm ci 成功，doctor 输出 `0 failed, 2 warnings`。两条 warn 是：本机 Arch 的 WSL interop 取不到 Windows 家目录（提示只有 dsh 需要它）；当前不在任何工作区。
- 再执行 `xmuse init` 和 `agent add c1 --vendor claude`，doctor 全 ok，只剩 "hub: not running"，修复命令是 `xmuse --ws … hub start`。

**测试结果原文**
```
302 passed, 1 skipped in 146.70s (0:02:26)
```
插件包（`cd integrations/dsh-bundle && npm test`）：
```
ℹ tests 27
ℹ pass 27
ℹ fail 0
```

**没做 / 拿不准**
- `grep` 剩下的唯一命中是 host.py 报错信息里的示例 `XMUSE_WSL_DISTRO=Ubuntu-24.04`，这是有意保留的。`tests/fixtures/*.jsonl` 里的 `/home/user` 是录制数据，没改。`spikes/`、`e2e/` 不在 T3 范围，留给 T7。
- 在 r7（interop 正常、装了 dsh）上没跑过 doctor，dsh 那几项只有单测覆盖。
- 插件包没有自动推导 state：它跑在 Windows 侧，不知道是哪个工作区。现在的做法是 doctor 打印出值，由用户填进去。

## T4 门面（草稿，未对外发布；2026-10-11）

**提交**：`05bbca3`（实验报告）、`c4478aa`（README、README.en、CI）

**做了什么**
- **实验报告**：`docs/design/XMUSE2-M2B-EXP-REPORT.zh.md` 按审计 C 节改写，并补了三节。
  - **长会话组**：5 个 run，含 long-L-2 的残留数据。指标用仓库自带的 `experiments/metrics.py` 重新算，结果存进 `experiments/results/metrics-long-all/`。
  - **T1 回放**：数据来自 r7 上的 `~/dsh-tasks/runs/t1-replay/report.md/report.md`，那份报告没进仓库。我只读了它，汇总数是逐表加出来的。
  - **MemoryOS 运维**：数据来自 long-L-mo-1、long-L-mo-2 的 `memoryos.log` 和指标。
  - 复核组补上了 review-ledger-bug1-1（6/6），指标在 `metrics-review-all/`。
- **按审计改的措辞**：
  - 删掉 minisql 的 p≈0.03，改为 3/7 对 0/6、单侧 p≈0.12，并写明审计列的五个问题；
  - 删掉"有利于对齐层的信号"；
  - 注入占比改说"便宜，不等于有效"；
  - 写明后 21 个 run 不算跨模型；
  - rot 和复核注明有天花板效应、没有基线；
  - "无人工干预"改成"完成或失败都不需要人插手"，并列出两个例外。
- **README.md（中文）和 README.en.md**：一句话定位、要解决的问题、mermaid 架构图、快速开始（bootstrap → init → agent add → doctor → hub start）、关键设计、实验摘要（分"支持"和"不支持"两部分）和局限、目录结构。信任模型按审计照实写成"防误操作，不防恶意 agent"。许可证写的是"待定"。
- **`.github/workflows/ci.yml`**：两个 job。一个跑 hub 测试（uv、Python 3.12、node 22、shim `npm ci`），另一个跑 dsh 插件包的 `npm test`。没有推到 GitHub。

**测试结果原文**（模拟 CI：/tmp 下的全新克隆加未提交的文件，Python 3.12.14，去掉 `WSL_DISTRO_NAME` 等 WSL 变量和 /mnt 下的 PATH）
```
FAILED tests/test_claude_engine.py::test_stop_interrupts_running_turn_and_cancels_queue
1 failed, 301 passed, 1 skipped in 98.49s (0:01:38)
ℹ pass 27
ℹ fail 0
```
- 失败的是第 203 行的断言（`canceled_deliveries == 1 and interrupted_turns == [1]`），只在这次全量里出现过。之后单独跑 3 次、并行跑 6 份，都没有复现。原因没查清，归为负载下偶发，和 T2 里 sweep 用例的情况类似。**需要 r7 在原生盘上多跑几次确认。**
- 原生盘上全量用时 98 s，达到 2 分钟目标。

**没做 / 拿不准**
- **LICENSE 没加**：交接要求先问用户，我已在对话里问了，等回复。
- 实验报告第九节的 MemoryOS token 列取的是 metrics 输出里最后一个阶段的数，看起来是整个 run 的累计值，没有逐条核实。
- 我数出的 T1 回放 curate 调用是 22 次（3 次 502），审计写的是 25 次。报告里以 22 为准，并注明了差异。
- README 的快速开始命令，我在 /tmp 的全新克隆上跑通了 bootstrap、init、agent add 和 doctor；`hub start` 以后的步骤（会真的唤醒 agent、花 token）没有跑。
- README 目录表里写了 `spikes/`、`e2e/` "计划移到 archive/"，这要等 T7 做完才成立。

## T5 信任边界（2026-10-11）

**提交**：`7ba4ec6`（提交信息里写的"49 个绕过"有误，实际是 50 个）

**做了什么**
1. **自动批准改成白名单**（`adapters/opencode.py`）
   - 生成的 `opencode.json` 让每条 shell 命令都走 ask，hub 用 `command_auto_ok` 判断。
   - 只自动放行这些单条命令：测试（`python -m pytest/unittest`、`pytest`）、工作区或 /tmp 里的 `.py` 脚本、只读工具（ls/cat/grep/find 但不带 -exec 和 -delete、sed 但不带 -i 等）、本地 git（status/diff/log/show/add/commit 等，不允许 `-C`/`-c`）、安全的 `rm -f`、`mkdir -p` 相对路径；`x | head` 这类后面只接只读过滤器的管道。
   - 其余一律交给人：`; && || &`、反引号、`$(`、`${`、`<(`、除 `2>&1` 外的重定向、带路径的程序名、`bash -c`、`python -c`、`env/exec/nohup/timeout/xargs` 包装，以及白名单外的一切。
   - 原 fnmatch 黑名单已删除。
2. **有授权效力的管理操作要求有人在场**（新模块 `peer.py`，`server.require_human`）
   - 涉及 `approve`、`align`（确认或驳回提议）、`resume` 三个接口。
   - hub 通过 /proc/net/tcp 加 /proc/*/fd 找到连接对端的进程，要求它有控制终端，并且祖先进程里没有已知的 agent 进程（运行中回合的 pid、Claude TUI 租约 pid、OpenCode 服务 pid）。
   - Windows 侧来的连接找不到对端进程，一律拒绝。
   - 这个开关是 `Hub(..., human_check=True)` 的构造参数，不放在 config.json 里，因为 agent 能改配置文件。
   - send、stop、log 这类操作仍然只看令牌：它们不授予权力，发出的消息会标 `via=cli`。
3. **审批经协调者转给用户确认**
   - 新增第 8 个工具 `xmuse_approve(id, decision, user_said)`，只有桌面协调者能用，必须附上用户原话。
   - 每次决定都会在线程里发通知，写明谁决定的（"用户经 dog（原话）"或"用户（终端）"）；已经决定过的审批不能再改。
   - "asks permission" 的通知里写明了这两条途径。
4. **设计稿**：§4.2 加了更正，"agent 读不到令牌"不成立；§4.7 新增"信任模型"一段，写明现在的做法和剩下的缺口。README（中、英）同步更新。
5. **测试**
   - `tests/test_opencode_engine.py`：50 个绕过写法都不会被自动放行，19 个常用命令仍会放行；验证 opencode 配置对所有 shell 命令都走 ask。
   - `tests/test_trust.py`（6 个用例）：在独立子进程里发起管理调用。
     - 没有控制终端：拒绝；
     - 有伪终端但在"agent"进程树里（把测试进程登记为 TUI 租约）：拒绝；
     - 有伪终端且不在 agent 进程树里：放行；
     - 操作类调用仍然放行；
     - 协调者转达审批成功，并且有记录；
     - 非协调者调用 `xmuse_approve` 被拒绝。
   - 原来断言 7 个工具、黑名单规则、`python3 -c` 自动放行的测试都已按新行为修改。

**测试结果原文**
```
310 passed, 1 skipped in 143.88s (0:02:23)
```
插件包：`ℹ pass 27`、`ℹ fail 0`

**没做 / 拿不准（需要用户决定）**
- **"管理令牌移到 agent 读不到的地方"没有字面做到**：agent 和 hub 是同一个 OS 用户，放在哪里都读得到。现在的做法是让令牌单独不够用（见第 2 条）。有意绕过的 agent 可以用 `setsid` 脱离进程树，再用 `script` 分配一个伪终端，从而通过检查。真正的边界是给 agent 用单独的 OS 用户或沙箱，并且不给推送凭据（审计 B2-1 第 2、3 点）。这会改变安装方式，需要用户拍板。
- Claude 无界面白名单里的 `Bash(python3:*)` 没动：这是用户 10-09 的决定，它可以执行任意代码。
- dsh 插件包会把 `xmuse_approve` 也注册给 dsh 会话（dsh 调用会被 hub 拒绝），多占一点工具描述的 token。也可以在插件包里过滤掉，没做。
- 白名单在真实 opencode 上的效果没有跑过：现在所有 shell 都会先 ask，再由 hub 回复。这会给每条命令多一次往返，并且依赖 OpenCode v2 规则 `{"action":"shell","resource":"*","effect":"ask"}` 的语义，这一点只按 schema 和现有用法推断，**需要在 r7 上用一次真实运行确认**。
- 写着"人在终端"的检查依赖 Linux /proc。在 WSL2 上，协调者（Windows 侧）以用户身份做管理操作只能走 `xmuse_approve`，CLI 的 `xmuse approve` 要在 WSL 终端里执行。

## T7 移动清单（先列清单，T6 的 run 跑完后再动手）

原则：用 `git mv`，**不删除任何文件**，git 历史保留；根目录只留现在还在用的代码和数据。

| 现在的位置 | 移到 | 文件数 | 说明 |
|---|---|---|---|
| `spikes/`（整个目录：`runs/` 275、`dsh/` 13、`ws-template/` 10、`notes/` 7、各种探针脚本和日志） | `archive/spikes/` | 331 | M0/M1 的探针和录制。代码里只有 `adapters/claude.py` 的两处注释提到它（"ported from spikes/…"），会改成新路径 |
| `e2e/` 除 `check.py` 外的全部（`results/` 230、`seeds/` 15、`scenarios/` 7、`hidden/` 3、`run.sh`、`batch.sh`、`aggregate.py` 等脚本） | `archive/e2e/` | 264 | M1 的端到端记录和脚本，已被 `experiments/` 取代 |
| `e2e/check.py` | `experiments/check.py` | 1 | **还在用**：`experiments/run.py` 每个 run 都调用它算 summary.json。移动后同步改 run.py 的路径 |

不动的：
- `experiments/results/`：实验报告引用的数据；
- `docs/design/`、`tests/fixtures/`（测试在用）；
- `.gitignore` 里的 `e2e/state-*/`：只是忽略规则，改成 `archive/e2e/state-*/`。

动手后的验收：全量测试通过；`experiments/test_experiments_run.py` 通过；`grep -rn "spikes/\|e2e/"` 在代码里没有失效引用；`archive/README.md` 说明这些是什么、为什么保留。

## T6 补实验（2026-10-11）

**提交**
- `917e9e2`：预注册 `docs/design/XMUSE2-T6-PREREG.zh.md`，加上 runner 支持（S 组、SPEC 覆盖文件、provenance）。**在任何 T6 run 之前提交并推送。**
- `93d213b`：开跑后发现的问题和修复（偏离记录 1），见下文。
- `c190c39`：base 侧的结果数据。

**准备了什么**
- `experiments/overlays/spec-v2/`：把 minisql 的"未闭合字符串报开引号位置"和 ledger 的"金额只接受 ASCII 数字"写进 SPEC，这正是 M2b 里两个"猜题"失败项。隐藏测试不变。
- 场景：`<seed>-S`（E1 单 agent）、`<seed>-B2` / `<seed>-C2`（E1 对照臂、E2a）、`review-<seed>-bug<n>-self`（E5 SELF）。
- 计划：`plans/t6-e1-S.txt`、`t6-e1-B2.txt`、`t6-e2a.txt`、`t6-e5-self.txt`、`t6-e5-cross.txt`。
- 每个 run 的 `meta.json` 现在都带 `provenance`：hub 提交号、有没有未提交改动、每个 agent 的模型、OpenCode 版本、审批策略。

**开跑后的偏离（已写进预注册）**
- 第一次开跑约 8 分钟后，两个 run 卡住了：T5 的白名单把 agent 写探针脚本用的 heredoc 和 `python3 -c` 转给人审批，而实验没人值守。我中止了两条线（只按 PID 结束实验进程，没动用户自己的 OpenCode 服务），两个 run 作废（移到 `results/_prev/`，没提交）。
- 修复：新增只供实验用的 `XMUSE_SHELL_POLICY=blocklist-experiment`，由 runner 经环境变量交给 hub，不经过配置文件，语义就是 M2b 时期的黑名单，并记进每个 run。默认仍是白名单。
- 顺带修了一个 **T3 回归**：`xmuse hub start` 用 `clean_env` 启动 hub 时会丢掉 `WSL_DISTRO_NAME`。T3 之前有 `Ubuntu-24.04` 默认值掩盖了这个问题，T3 之后 hub 内部的 `host.distro()` 会报错。现在会透传 WSL 变量。有测试。

**base 侧跑完的结果**（OpenCode `opencode-go/muse-spark-1.3-contributor`、OpenCode v2.0.21、hub `59407f8`、策略 blocklist-experiment）

| 臂 | run | 结果 | 每个 run 的 token | 回合 |
|---|---|---|---|---|
| E1 S（单 agent 实现加自审，spec-v2） | 9 | **完成 9/9**（Wilson 95% CI 0.70–1.00）；rot 9/9 followed；未受 rot 影响的隐藏测试全过 | 均值 833,515（范围 646,645–1,048,376） | 每个 run 2 回合（第 1 回合实现加自审，第 2 回合处理 rot） |
| E5 SELF（OpenCode 复核预埋 bug） | 6 | **检出 6/6**（Wilson 95% CI 0.61–1.00），误报 1 条 | 均值 252,688 | 1 |

**能说什么、不能说什么**
- **E1 还没有对照**：预注册的比较对象是 B2（OpenCode 实现、dsh 复核，同样用 spec-v2），需要 dsh，只能在 r7 跑，**还没跑**。在那之前，S 的 9/9 只能单独看。
  - 和 M2b 的 A/B/C 比没有意义：SPEC 版本不同（M2b 的失败几乎全是那两个歧义项），dsh 的模型也不同。
  - 但可以先记下一个值得 B2 回答的现象：去掉歧义后，一个 agent 两个回合、约 83 万 token 就全部完成；M2b 里多 agent 组每个 run 约 300 万 token、8–10 个回合。
- **E5 看起来有天花板**：SELF 6/6，M2b 里 dsh 复核也是 6/6（那 6 个 run 只作参照、不计入）。如果 r7 的 CROSS 臂也是 6/6，这个任务就区分不出"换一家复核"的价值，需要更难的预埋 bug（多个 bug、跨模块的 bug、不给 SPEC），这要另做设计。

**留给 r7 的（需要 dsh，base 跑不了）**
```bash
experiments/batch.sh experiments/plans/t6-e1-B2.txt      # 9 run，E1 对照臂
experiments/batch.sh experiments/plans/t6-e2a.txt        # 12 run，minisql B2 对 C2 各 6
experiments/batch.sh experiments/plans/t6-e5-cross.txt   # 6 run，dsh 复核
```
- r7 的 `E2E_WS_ROOT` 用默认值（`/mnt/c/...`，dsh 需要 C 盘路径）。
- dsh 用什么模型由 r7 定，会自动记进 provenance。runner 默认就是实验策略，不用另外设置。
- **E2b**（"只有一方知道"的约定）只写了设计，没有准备种子。

**测试结果原文**（T6 改动后的全量）
```
313 passed, 1 skipped in 143.69s (0:02:23)
```
插件包：`ℹ pass 27`、`ℹ fail 0`

## T7 隔离不删（2026-10-11）

**提交**：`78f2e0e`。按 r7 §8 第 6 条，现在就动手，不等 T6。

**做了什么**（按上面的清单，用 `git mv`，**没有删除任何文件**）
- `spikes/` → `archive/spikes/`（331 个文件）。
- `e2e/` 除 `check.py` 外 → `archive/e2e/`（264 个文件）。
- `e2e/check.py` → `experiments/check.py`，`run.py` 改为 `EXP / "check.py"`。
- `git status`：596 个 R（重命名），0 个 D。空的 `e2e/` 目录已去掉。
- 引用同步：`adapters/claude.py` 的两处注释、`.gitignore`（同时把 `experiments/results/_prev/` 加进忽略）、README 中英文的目录表。
- 新增 `archive/README.md`：说明这两个目录是什么、为什么保留。

**验收**
- 全量测试：
  ```
  313 passed, 1 skipped in 146.16s (0:02:26)
  ```
- `experiments/check.py` 在 `results/minisql-S-1` 上重跑，输出和当时记录的 `summary.json` 一致（唯一的差别是我手填的 seconds 参数）。
- `git grep "e2e/\|spikes/"` 在代码里（不含 archive、docs、实验结果、测试录制）只剩新路径。

**没做 / 拿不准**
- `docs/design/` 里的历史文档仍然写着 `spikes/…`、`e2e/…` 的旧路径，没有改：它们是当时的记录。
- `archive/` 里录制文件中的 `/home/user/...` 路径保持原样。

## T8 小修（r7 审查后追加；2026-10-11）

**提交**：``a25089b``

| 项 | 做法 | 测试 |
|---|---|---|
| 1 白名单漏洞 | `sed` 只放行 `sed -n 'N[,M]p' 相对路径…` 这一种形式；git 去掉 `restore`，并拒绝 `--output`、`--open-files-in-pager`、`-O`（含 `-Ovim` 这类写法）、`--ext-diff`、`--textconv`；`rg` 拒绝 `--pre*`；`sort` 拒绝 `-o`（包括组合标志里的，例如 `-uo`）和 `--output`、`--compress-program`；`tree -o`；`find -fprint*`、`-fls*`。管道后面的过滤器同样检查（`ls \| sort -o x` 会被拦） | `BYPASSES` 新增 25 条，共 75 条全部拦下；`ALLOWED` 新增 5 条常用写法（`git log --oneline`、`grep -o`、`sort -u`、`sed -n 5p`、`rg -n`），全部仍然放行 |
| 2 家族按模型推导 | `config.family(vendor, model)`：模型名含 claude→anthropic、deepseek→deepseek、muse-spark→opencode，另有 gpt/gemini/qwen/glm/kimi，都不匹配时按外壳。`agent add` 和重新 add 时写入；hub 启动时修正旧库里的值（10-11 之前 dsh 跑 muse-spark 被标成 deepseek） | `test_units.py::test_family_follows_the_model_not_the_shell`（含 whoami 和旧库修正） |
| 3 插件包 | `peerDependencies` 改为 `>=0.2.0-rc.2 <0.3.0`；README 新增"升级 dsh 本身"一节（自检、看日志、改范围、重跑测试）。另外按 r7 回复第 3 条：dsh 会话不注册 `xmuse_approve`（插件包过滤掉；随包的 tools.json 仍是 hub 的完整 8 个） | node 测试新增 1 条：hub 列出了这个工具，dsh 会话里也没有 |
| 4 `woken` 和前台 agent | `send` 的返回里，`woken` 不再列出前台 dsh agent，改为单独的 `pushed`（由插件包推送）；`pushed` 只在非空时出现，旧的返回格式不变 | `test_foreground.py::test_engine_never_wakes_foreground_agent` |

**测试结果原文**
```
314 passed, 1 skipped in 143.93s (0:02:23)
```
插件包：`ℹ pass 28`、`ℹ fail 0`

**没做 / 拿不准**
- `sed` 现在只放行一种写法，agent 用 `sed 's/…//' file`（不带 -i，只输出）查看替换效果时也会转人工。
- `xmuse_send` 工具的描述里没有提到 `pushed`，模型是从返回值里看到的。

## T6 结果（r7 臂回来后；2026-10-11 07:20）

r7 在 07:13 跑完了 27 个 run（`t6-e1-B2`、`t6-e2a`、`t6-e5-cross`），**数据还在 r7 的工作树里，没有提交**（`~/dev/xmuse2-rc/experiments/results/`）。下面的数是我通过 ssh 只读取的 r7 `metrics-t6-*/metrics.md`；统计按预注册：Newcombe 95% CI，Fisher 只作参考。完整的表在 `docs/design/XMUSE2-T6-PREREG.zh.md` 的"结果"一节。

| 比较 | 计数 | 差值 | 95% CI |
|---|---|---|---|
| E1 S 对 B2（完成率） | 9/9 对 9/9 | 0 | −0.30 至 +0.30 |
| E2a C2 对 B2（minisql） | 6/6 对 5/6 | +0.17 | −0.25 至 +0.56 |
| E5 SELF 对 CROSS（检出率） | 6/6 对 6/6 | 0 | −0.39 至 +0.39 |

- 主指标都碰到天花板或者差 1 个 run，置信区间都跨 0。按预注册只描述，不下结论。
- 次指标的差别都在成本上：
  - E1：单 agent 每个 run 约 83 万 token、2 个回合；多 agent 约 410 万 token、8 个回合，约 4.9 倍。
  - E5：OpenCode 复核约 25 万 token、1 条误报；dsh（deepseek-v4-flash）复核约 75 万 token、4 条误报。
- E2a：去掉 SPEC 歧义后，12 个 run 的"开引号"一项全部通过，和预注册写下的预期一致。唯一没完成的 B2-13 原因是 rot 遵守为 partial。
- 混杂：base 臂和 r7 臂的 hub 提交不同（`59407f8` 对 `b97919c`），OpenCode 版本也不同（v2.0.21 对 v2.0.26）。

**待办（r7）**：把 27 个 run 的结果目录和 `metrics-t6-*` 提交到 rc/portfolio。提交后我这里的数字可以直接对照。
## T10a SWE-Bench Pro 环境（2026-10-11，base）

**主机与磁盘**
- base：Windows 主机 + Arch WSL，工作区 `/home/goodman/dev/xmuse2` 落在 `/dev/sdd`（1007G）。
- 开工前检查：Windows 侧 C: 322GB free、D: 1090GB free；WSL `/` 900GB avail。结论：BENCH_DIR 和 Docker 数据目录都放在有足够空间的原生大盘上（WSL `/dev/sdd`），24 镜像约 40–60GB + 20% 余量无压力，不停工。
- Docker：client 29.8.1 / server 29.8.1，`Docker Root Dir: /var/lib/docker`，overlayfs。`docker run hello-world` 通过，当前用户已在 `docker` 组、免 sudo；`/etc/docker/daemon.json` 只有 `max-concurrent-downloads: 8`，**没有改 data-root，没有用 sudo**。

**BENCH_DIR**：`/home/goodman/bench`
- 数据集 `swebench-pro-verified/`：`swebench_pro_verified.jsonl`（731 行，sha256 = `9eeac2c01fcbf25fd8db4254a23b9e0d306eb659e9c14dd1308b9fda10faf6d8`，与要求一致）+ `README.md`。Apache-2.0，无需申请访问。
- 评测脚本 `SWE-bench_Pro-os`：提交号 `66f9276`（v2.0.0），**与 r7 用的版本一致，无差异**。
- 抽样：`python3 sample.py BENCH_DIR 24 20261011` → `pool 657/731 (<= 400 changed lines)`，`diff` 对比 `BENCH_DIR/pilot/ids-24-20261011.txt` 与仓库同名文件**完全一致**。

**24 个镜像**（`jefzda/sweap-images:<dockerhub_tag>`；Size 列为 `docker images` 显示值，十进制 GB；合计约 112.3GB）：

| 题（短 tag） | 大小 | 拉取耗时 |
|---|---|---|
| nodebb 0f788b | 3.29GB | 1540s（旧慢网） |
| nodebb 18c45b | 3.27GB | 首轮 WiFi 切换断流失败，事后补拉 53s |
| ansible a7d2a4 | 1.65GB | 119s |
| ansible e9e600 | 1.65GB | 43s |
| ansible 564009 | 1.64GB | 52s |
| element-web 41dfec | 3.84GB | 84s |
| element-web 5e8488 | 3.85GB | 39s |
| flipt f74394 | 6.71GB | 142s |
| flipt 518ec3 | 2.08GB | 20s |
| flipt 756f00 | 2.08GB | 22s |
| vuls fd18df | 4.30GB | 65s |
| vuls 407407 | 6.07GB | 92s |
| teleport db8920 | 7.16GB | 177s |
| teleport 78b0d8 | 7.57GB | 82s |
| openlibrary 9bdfd2 | 4.38GB | 85s |
| openlibrary 3c48b4 | 3.02GB | 62s |
| openlibrary 123e6e | 4.55GB | 80s |
| navidrome ee21f3 | 4.88GB | 116s |
| navidrome 29bc17 | 4.36GB | 64s |
| webclients 7e5452 | 12.5GB | 301s |
| webclients 08bb09 | 15.2GB | 495s |
| qutebrowser f91ace | 2.15GB | 36s |
| qutebrowser 8cd067 | 1.99GB | 37s |
| tutanota fb32e5 | 4.07GB | 92s |

- 拉取策略：逐个 `docker pull`，每拉完看剩余空间（全程远高于 15GB 下限，未触发停拉）。旧 WiFi 实测约 0.8MB/s；换 WiFi 后 14–28MB/s。试过 DaoCloud 镜像加速（本机有用过 `m.daocloud.io` 的痕迹），但 `jefzda/sweap-images` 不在它的白名单被拒，继续直连。完整拉取日志在 base 本机 `~/bench/pilot/pull-24-20261011.log`（未进仓库）。

**参考答案校验**：`bash gold-check.sh BENCH_DIR 24-20261011 "" 2`，`Overall accuracy: 0.9583333333333334`，23/24 为 true。

`eval_results.json` 原文：
```
{"instance_NodeBB__NodeBB-0f788b8eaa4bba3c142d171fd941d015c53b65fc-v0ec6d6c2baf3cb4797482ce4829bc25cd5716649": true, "instance_NodeBB__NodeBB-18c45b44613aecd53e9f60457b9812049ab2998d-v0495b863a912fbff5749c67e860612b91825407c": true, "instance_ansible__ansible-a7d2a4e03209cff1e97e59fd54bb2b05fdbdbec6-v0f01c69f1e2528b935359cfe578530722bca2c59": true, "instance_ansible__ansible-e9e6001263f51103e96e58ad382660df0f3d0e39-v30a923fb5c164d6cd18280c02422f75e611e8fb2": true, "instance_ansible__ansible-5640093f1ca63fd6af231cc8a7fb7d40e1907b8c-vba6da65a0f3baefda7a058ebbd0a8dcafb8512f5": true, "instance_element-hq__element-web-41dfec20bfe9b62cddbbbf621bef2e9aa9685157-vnan": false, "instance_element-hq__element-web-5e8488c2838ff4268f39db4a8cca7d74eecf5a7e-vnan": true, "instance_flipt-io__flipt-518ec324b66a07fdd95464a5e9ca5fe7681ad8f9": true, "instance_flipt-io__flipt-f743945d599b178293e89e784b3b2374b1026430": true, "instance_flipt-io__flipt-756f00f79ba8abf9fe53f3c6c818123b42eb7355": true, "instance_future-architect__vuls-future-architect__vuls-fd18df1dd4e4360f8932bc4b894bd8b40d654e7c": true, "instance_gravitational__teleport-db89206db6c2969266e664c7c0fb51b70e958b64": true, "instance_future-architect__vuls-407407d306e9431d6aa0ab566baa6e44e5ba2904": true, "instance_internetarchive__openlibrary-9bdfd29fac883e77dcbc4208cab28c06fd963ab2-v76304ecdb3a5954fcf13feb710e8c40fcf24b73c": true, "instance_internetarchive__openlibrary-3c48b4bb782189e0858e6c3fc7956046cf3e1cfb-v2d9a6c849c60ed19fd0858ce9e40b7cc8e097e59": true, "instance_internetarchive__openlibrary-123e6e5e1c85b9c07d1e98f70bfc480bc8016890-v2733ff199fb72f0d033a30dc62cb0a4742e3a7f4": true, "instance_navidrome__navidrome-ee21f3957e0de91624427e93c62b8ee390de72e3": true, "instance_gravitational__teleport-78b0d8c72637df1129fb6ff84fc49ef4b5ab1288": true, "instance_navidrome__navidrome-29bc17acd71596ae92131aca728716baf5af9906": true, "instance_protonmail__webclients-7e54526774e577c0ebb58ced7ba8bef349a69fec": true, "instance_qutebrowser__qutebrowser-f91ace96223cac8161c16dd061907e138fe85111-v059c6fdc75567943479b23ebca7c07b5e9a7f34c": true, "instance_qutebrowser__qutebrowser-8cd06741bb56cdca49f5cdc0542da97681154315-v5149fcda2a9a6fe1d35dfed1bade1444a11ef271": true, "instance_protonmail__webclients-08bb09914d0d37b0cd6376d4cab5b77728a43e7b": true, "instance_tutao__tutanota-fb32e5f9d9fc152a00144d56dd0af01760a2d4dc-vc4e41fd0029957297843cb9dec4a25c7c756f029": true}
```

**失败的 1 题**：`instance_element-hq__element-web-41dfec…-vnan`。日志（`pilot/gold-out-24-20261011/<id>/gold_stdout.log`，stderr 为空）显示 2 个 jest suite 失败、106 通过：`BasicMessageComposer › should replaceEmoticons properly`，以及 `SendWysiwygComposer › Should render … isRichTextEnabled is at true`（`Exceeded timeout of 5000 ms`，suite 用时 147s；另一失败 suite 用时 74s）。**判定为环境问题（负载抖动），不是题目或参考答案问题**，依据：
- 同仓库另一题（`element-web-5e8488`，同镜像家族）一次通过；
- 该题用单 worker 独跑重测一次：`Overall accuracy: 1.0`，`{"…41dfec…": true}`，harness 计时 49s；
- 失败形态是 jest 默认 5s 超时 + 被拖慢的 suite（双 worker 并发跑重型 jsdom 本来就挤）。
有效结论：**参考答案 24/24 通过**（全量跑 23/24 + 单跑补 1/1）。没有改题目或测试。

**单题评测耗时（不含拉镜像；镜像已预拉）**：全量 24 题双 worker 墙钟约 20 分钟；单题 solo 重跑 harness 计时 49s；element-web 同仓另一题 jest 内部计时 146s。官方脚本不记录逐题 harness 耗时，以上为实测墙钟。

**剩余磁盘空间**：`/dev/sdd` 811GB avail（已用 146G，其中 24 镜像约 112GB）。

**约束遵守**：没碰密钥令牌，没用 Modal；只推 r7 的 `rc/portfolio`，没碰 GitHub；评测容器都是一次性的（harness 起停），没删非本机镜像；24 镜像保留本机供后续评测；没跑 agent，没改 xmuse 代码。

**事故记录**：排查失败题时用 ID 子串单跑了一次，harness 把 `pilot/evalin/goldin-24-20261011.jsonl` 和 `gold-out-24-20261011/eval_results.json` 覆盖成了单题版。已用 `gold-check.sh` 同源逻辑重生成两个输入文件（24 条），并按 harness 当时打印的原文逐值重建 `eval_results.json`（24 条、23 true）；各题子目录除 41dfec 外原样未动，41dfec 恢复为全量跑的失败版，solo 通过版另存 base 本机 `~/bench/pilot/rerun-41dfec-solo/`。上面贴的 JSON 与 harness 输出一致。

## T12 同一家厂商多个实例（2026-10-11）

**提交**：`d0c5668`

**先核实**：opencode v2.0.21 支持用 `OPENCODE_CONFIG` 指定配置文件路径。
- 二进制里有 `OPENCODE_CONFIG`、`OPENCODE_CONFIG_CONTENT`、`OPENCODE_CONFIG_DIR`、`OPENCODE_CONFIG_PROJECT_DISABLE` 四个变量。
- `opencode debug config` 走后台服务，看不到调用方的环境变量，所以改为直接起 `opencode serve` 探测：带 `OPENCODE_CONFIG` 启动时，`GET /api/config` 列出的来源里同时有实例配置（`XMUSE_AGENT=probe-a`）和工作区的 `opencode.json`（权限规则），两者合并生效。
- 改完后又用真实 opencode 起两个实例：`oc-a loaded XMUSE_AGENT: ['oc-a']`、`oc-b loaded XMUSE_AGENT: ['oc-b']`，端口不同，结束后没有残留进程。整个过程只读配置，没调用模型。

**做法**
| 厂商 | 改动 |
|---|---|
| opencode | 每个实例一个目录 `<state>/oc/<agent>/`，里面是 `opencode.json`（只有 xmuse MCP 和 `XMUSE_AGENT`）和 `oc.pass`；每个实例单独起一个 `opencode serve`（单独端口、单独密码、`OPENCODE_CONFIG` 指向自己的配置），日志写到 `logs/opencode-<agent>.log`。工作区共享的 `opencode.json` 只留权限规则，不再带身份。驱动按 agent 把回合分派到它自己的服务；审批按 agent 路由，因为会话 id 只在单个服务内唯一（测试里两个服务都从 `ses_fake1` 开始编号）。`xmuse transcript` 和 `xmuse attach` 也按 agent 找服务。hub 运行中新加的 agent，第一次派活时再起它的服务 |
| dsh 无界面 | 核实：身份本来就由每次运行的 overlay 传入（`XMUSE_AGENT` 写在一次性 patch 文件里），直接放开。工作区的 `.dsh/hooks.json` 只有一份，所以桌面端的在场检测只跟第一个注册的 dsh agent；后加的 dsh agent 不覆盖它，只走无界面模式。前台模式不变，仍是一个会话绑一个 agent |
| Claude | 不动，仍限一个（`.mcp.json` 只能写一个身份）；第二个 Claude agent 仍然报 `already has a claude agent` |

- `xmuse doctor`：新增 `instances` 一行，列出每家的实例数和 id；每个 opencode 实例分别检查自己的配置（身份、状态目录对不对），工作区 `opencode.json` 里如果还带着身份（T12 之前的布局）就判 FAIL；dsh 实例标明谁持有桌面在场钩子。
- 测试替身：新增 `tests/fakes/fake_opencode_serve.py`，由 hub 当子进程启动，和真实服务一样只从 `OPENCODE_CONFIG` 加工作区 `opencode.json` 得到身份，并校验 hub 发来的密码。

**测试**：`tests/test_instances.py`（3 条）
- 两个 opencode 实例各起一个服务：端口和密码都不同；各自的 whoami 结果是自己；消息发送者正确；各自只跑了发给自己的回合；用量按 agent 分开记账。
- 审批发给提出审批的那个实例（按 agent，也按会话兜底）。
- 同一工作区注册两个 opencode、两个 dsh、一个 Claude：身份不串；dsh 的 overlay 各自带自己的 id；第二个 Claude 被拒；doctor 识别出 `claude x1, dsh x2, opencode x2`，旧布局判 FAIL。

**测试结果原文**（无终端：`setsid … < /dev/null`）
```
317 passed, 1 skipped, 1 warning in 158.74s (0:02:38)
```
插件包：`ℹ pass 28`、`ℹ fail 0`

**没做 / 拿不准**
- 人在工作区里直接运行 `opencode`（不经过 hub 的服务）时，不再带任何 xmuse 身份；接入正在运行的实例要用 `xmuse attach <id>` 给出的命令。
- 一个工作区只能有一个 dsh agent 接收桌面端的在场钩子。团队实验全部是无界面模式，不受影响。
- 旧状态目录里的 `oc.pass` 和工作区旧 `opencode.json` 不会自动清理；重新 `agent add` 一次就会改写成新布局，doctor 会提示。

## T14 信息层补强和关闭开关（2026-10-11）

**提交**：`ec1cdfa`

**先核实现有能力**
| 项 | 原来 | 补了什么 |
|---|---|---|
| 1 按 scope 注入 | scope 只有 global、thread、role:<角色>；注入（快照、增量、xmuse_context）按 agent 所在的 scope 过滤 | 新增 `module:<名字>`（`all` 作为 global 的别名） |
| 2 依赖解决就唤醒 | `align._blocked` 只用于视图里的 `ready` 列表；handoff 一发出去，被点名的人就被唤醒，不管依赖有没有解决 | 补上"依赖未解决不派活、解决了就唤醒" |
| 3 question 定向 | question 只按 mentions 唤醒；答复没有任何路由 | 补上：唤醒规划者，答复唤醒提问者 |
| 4 总开关 | `alignment=off`（M2b 的 B 组）只关注入和 curate，declare、handoff 仍然登记 | 新增 `info_layer=off`，比 `alignment=off` 更彻底；B 组的旧语义不变，所以和 T6 的 B2 仍然可比 |

**做法**
1. **module scope 的订阅：选"P 下发 assignment 时写明"**。handoff 带 `scope="module:a,b"`，写进 assignment 的新列 `entries.modules`。
   - 一个 agent 订阅的 module = 它作为 assignee 或作者（即规划者）持有的、未拒绝也未归档的 assignment 里的 module。所以 P 能看到它下发过的所有 module。
   - 带 module scope 的条目只注入给订阅了这个 module 的 agent，外加条目的作者（执行者登记了一条影响别人模块的 assumption，自己也能看到它后来的去向）。
   - decision、assumption、question 一次只能写一个 module。
   - 不选"agent 自己声明"：多一个工具或参数，而且执行者可能漏报；文件归属本来就是 P0 计划的一部分。
2. **依赖唤醒**：handoff 带 `depends_on`，并且依赖未解决时，给 assignee 的投递记为新状态 `blocked`，不唤醒（返回 `blocked: [...]`）。
   - 之后任何条目变化都会调用 `align.release`：xmuse_send、xmuse_done 的 declares、人工 confirm（`xmuse align confirm`）、关闭线程。依赖已解决的投递改回 `queued`（链已到上限的改为 `held`），返回 `released: [...]`，engine 随即唤醒。
   - `xmuse stop` 也会取消 `blocked` 的投递。
3. **question 往返**：
   - 发出 question 时，hub 额外唤醒提问者当前 active assignment 的作者（即 P），不需要点名。
   - P 用 decision `supersedes` 这个 question 时，如果没写 scope，就沿用被替代条目的 scope，于是按原来的 module 传播；同时唤醒 question 的作者。`resolves` 一个 question 也唤醒它的作者。
   - 增量包里，"被替代"一行会带上新条目的原文，前提是提问者不在新条目的 scope 里。否则答复只在 P 能看到的 module 里，提问者看不到答复内容。
4. **总开关 `info_layer`**：hub 配置项，默认 `on`；runner 用场景变量 `INFO_LAYER` 设置，并记进 `meta.json → hub_config`。关闭后：
   - **工具**：hub 启动时按配置重写 `<state>/tools.json`。`xmuse_send` 的 kind 只剩 `message`，去掉 scope、supersedes、resolves、depends_on、why；`xmuse_done` 去掉 declares；不提供 `xmuse_context`。hub 用同一份工具表校验调用，带这些参数会得到 unknown argument。
   - **提示词**：skill 和 AGENTS.md 的 xmuse 段在模板里用 `<!-- info:on|off|end -->` 标出两种写法。hub 启动和 `xmuse init` 时按配置渲染，标记行本身不会写进去。关闭时文本里不出现 decision、assumption、Why-First、xmuse_context、depends_on、review_request、declares。dsh 前台中继的结尾提示也去掉了 xmuse_context。
   - **其它路径**：`mail.send` 对所有人（包括 CLI 和协调者）拒绝非 `message` 的 kind 和上述字段；不注入、不 curate、不按 scope 或 question 路由、不释放依赖。只按 mentions 唤醒。
   - `xmuse doctor` 按当前配置检查 tools.json、skill 和 AGENTS.md，关闭时会注明。

**测试**：`tests/test_info_layer.py`（6 条，用假 agent：4 个 Claude 回合立即结束，测的是路由）
- scope 路由：module 条目只到订阅者、作者和 P，不到无关的 agent。替代时沿用 module；作者在增量里看到替代它的原文。
- 依赖唤醒：被 question 卡住的 handoff 不唤醒、不起回合；答复之后被释放并起回合，`ready` 非空。另外覆盖了 resolve 释放和关闭线程释放。
- question 往返：不点名也唤醒 P；P 的答复唤醒提问者，并且沿用 module scope；没有 assignment 的人发 question，仍按 mentions 唤醒。
- 关闭：tools.json、skill、AGENTS.md 都不含这些能力；工具、CLI、xmuse_done 的 declares 三条路径都被拒；普通消息照常按 mentions 唤醒；条目数为 0，唤醒包里没有对齐段；doctor 判 ok。
- 打开时：渲染结果里没有标记行。
- 旧测试的改动：`test_align` 的报错文本更新了；`test_memoryos` 里 confirm 的返回多了 `released: ["claude-3"]`，这正是依赖唤醒。插件包随包的 tools.json 已重新生成（scope 的描述加了 module）。
- 第一次全量时 `test_units.py::test_wakepack_tags_relay_and_passive_summary` 失败 1 次，单跑通过。原因是测试本身的竞态：claude-1 被 handoff 真的唤醒，把被动消息标成已读，然后 render 才执行。和 T2 修过的几处一样，先暂停收件人再测。

**测试结果原文**（无终端）
```
323 passed, 1 skipped, 1 warning in 151.90s (0:02:31)
```
插件包：`ℹ pass 28`、`ℹ fail 0`

**没做 / 拿不准**
- `convention` 没有单独成为 kind，约定仍然用 `decision` 登记（`_blocked` 里早就把 convention 当 decision 处理）。如果设计稿要求单独计数，需要在 DECLARE 里加一个 kind，工具表也要跟着变。
- 订阅只来自 assignment：P 没有通过 handoff（带 module scope）派活的 agent，看不到任何 module 条目。
- dsh 前台 agent 的 AGENTS.md 段（`xmuse agent add --desktop`）里仍列出 `context` 子命令；团队实验都是无界面模式，没有改。

## T13 编排预设 plan-split-integrate（2026-10-11）

**提交**：hub 部分 `7393b05`；报告 `(this commit)`

**hub 里的状态机**（`hub/src/xmuse/preset.py`；`xmuse run --preset plan-split-integrate --planner P --executors E1,E2 --task-file F [--limits JSON]`，`xmuse run-status`）
| 阶段 | 开始时 hub 做什么 | 怎样结束 | 超时 |
|---|---|---|---|
| P0 | 每个执行者一个 worktree（`<ws>/.xmuse-wt/<id>`，分支 `xmuse/<id>`，从 base 提交开出，复制生成的 xmuse 文件）；执行者设为 cwd=worktree 并暂停；给 P 发规划说明 | P 写好 `.xmuse-plan.json`（`owners` 按执行者列 glob，`acceptance` 列验收清单），并调用 `xmuse_done(stage="plan")`，且这个回合已结束。计划文件无效时退回一次 | 记为失败 run，hub 不代为拆分 |
| P1 | 给每个执行者发阶段说明（自己的文件、怎样问 P、怎样收尾），然后解除暂停：P 在 P0 发的 handoff 和这条说明合进同一个回合 | 所有执行者 `xmuse_done(stage="part")`，且回合都已结束 | 停掉执行者（中断回合、取消排队），照样往下走 |
| P2 | 提交各 worktree → 快照 S-E1、S-E2 → 检查越界修改 → hub 依次把分支 merge 进主工作区；冲突的分支先 abort，留给 P 手动 merge → 给 P 发集成说明（含每个分支的合并结果） | P `xmuse_done(stage="integrated")`；`next` 写 `none` 表示全过，否则写一个负责人 | 停掉 P，进入收尾 |
| P3 | 修复者 = P 在集成阶段发过消息的执行者（加上 `next` 指名的）；把主分支 merge 进他们的 worktree，解除暂停 | 修复者 `xmuse_done(stage="fix")` → hub 合并 → 快照 S-fix-k → 让 P 复查（`P3int`，结束方式同 P2） | 同上；最多 `rounds` 轮（默认 2） |
| F | 暂停执行者，取消剩余投递；只有超时时才中断 P；提交主工作区 → 快照 F | — | 总时限（默认 3600 秒）到了直接进入 F |

- 快照：`git diff --binary <base> <commit>` 存在 `<state>/runs/preset-<id>/<名字>.patch`，事件里记时间、提交号和文件列表。AGENTS.md、CLAUDE.md、计划文件不进快照。
- 越界修改：执行者分支相对 base 改动的文件，不在它（以及它接手的部分）的 glob 里时，记 `violation` 事件，只记不拦。
- 崩溃：本阶段某个 agent 有一个 `failed` 回合 → 记 `crash_retry`，发一条消息再唤醒它一次；第二次 → `degraded`。执行者降级后由另一名执行者接手（`takeover`，接手人要在接手之后重新 `done(stage="part")`），没有人可接手就跳过；P 在 P0 降级则 run 失败，在集成阶段降级则直接收尾。
- 依赖的改动：engine 支持 `settings.cwd`（每个 agent 有自己的工作目录）；`xmuse_done` 新增可选参数 `stage`，写进新列 `messages.stage`；新增表 `preset_runs` 和 `preset_events`。hub 启动时开一个线程，每隔 `preset_tick` 秒（默认 2 秒）轮询推进。
- 顺手修了 T12 的遗留：`agent_pids`（判断是否人工操作时用的进程表）以前只看第一个 opencode 服务，现在看所有实例。

**测试**：`tests/test_preset.py`（11 条）。用脚本化的假驱动：每个 agent 一段 Python 行为，在自己的 cwd 里写文件、通过 HTTP 调 hub 工具。覆盖：
- 正常路径：阶段顺序 P1→P2→F；快照依次是 S-E1、S-E2、S-int、F，文件列表正确；执行者的 cwd 是各自的 worktree；第一个回合同时收到 handoff 和 P1 说明。
- P0 超时失败，执行者从未起过回合。
- 计划文件无效时退回一次。
- P1 超时：中断还没写完的执行者，半成品进入 S-E2。
- 崩溃：两个执行者各重试一次；e2 降级，由 e1 接手；接手后的文件不算越界。
- 越界和冲突：两个越界事件；e2 的分支冲突交给 P，P 手动 merge 并解决冲突。
- P3：修复轮把主分支合进修复者的 worktree，S-fix-1 和复查都执行了，e2 没有被唤醒。
- 信息层关闭（T-plain）也能跑完，条目数为 0。
- P 在 P0 连续崩溃两次，run 失败。
- 通过 CLI 启动，参数错误时报错。

连续跑 3 次都是 `10 passed`（后来加了第 11 条）。

**测试结果原文**（无终端，hub 部分）
```
333 passed, 1 skipped, 1 warning in 150.88s (0:02:30)
```
插件包：`ℹ pass 28`、`ℹ fail 0`（随包 tools.json 已重新生成：xmuse_done 多了 stage）

**实验 runner：搁置**（用户 10-11 指示：不再做适配具体 benchmark 的事）。写到一半的 Legacy-Bench 团队 runner 和一次中断的流程跑通已移出仓库，放在 base 本机 `D:\lbteam\_parked\`（未删）。多 agent 拓扑本身（hub 预设）继续推进。

**没做 / 拿不准**
- **WSL 互操作坏了（阻塞 hub 驱动 dsh）**：Arch 和 Ubuntu-24.04 里 `cmd.exe` 报 `Exec format error`，`/proc/sys/fs/binfmt_misc/` 下没有 `WSLInterop`。恢复需要 root 重新注册（`echo ':WSLInterop:M::MZ::/init:PF' > /proc/sys/fs/binfmt_misc/register`）或在探针结束后 `wsl --shutdown`，两者都留给用户。
- 预设还没有用真实 agent 跑过；设计稿第 6 节里需要大模型判断的指标没有实现；T-silent 没做。

## T15 第 1 步：big-market 底座调研（2026-10-11）

**提交**：本节（只有调研，没有代码）

**怎么调研的**：只读方式查看了 r7 上的原版（Windows `C:\Users\user\backend\bigmarket\big-market`，WSL 下是 `/mnt/c/...`，HEAD `7e31b53`，共 213 个提交）。看了 pom、`application-*.yml`（密码类字段在输出时已打码，没有读取明文）、`docs/dev-ops` 里的 compose 文件、配置类和测试。仓库里没有复制任何东西，也没有构建或启动。

### 规模（只算 `src/main` 的 Java 行数）
| 模块 | main | test |
|---|---|---|
| domain | 6130（strategy 2365、activity 2039、award 608、credit 438、rebate 430、auth 138、task 112） | 0 |
| infrastructure | 4068（7 个 Repository 共 1898 行，ActivityRepository 一个文件 822 行） | 0 |
| trigger | 1773（HTTP 控制器、Dubbo 服务、4 个 RabbitMQ 监听器、3 个 xxl-job 任务） | 0 |
| app | 833（配置类、AOP） | 1411（20 个 `@SpringBootTest`） |
| api / types / querys | 762 / 201 / 55 | 0 |
| **合计（不算 learning-demos）** | **约 1.38 万行**，另有 22 个 MyBatis mapper XML | |
| learning-demos | 3530 | 1464 |

- 和 §11 写的"约 2 万行"有出入：约 2 万这个数要把 learning-demos、测试和 XML 都算进去。`big-market-learning-demos` 是用户自己的学习骨架代码，**建议不放进猎场**。
- 仓库根目录下有 `resume/`、`docs/interview/`、`data/`、`.m2/`（14 MB 本地依赖），这些都要在构造猎场时剔除。
- 环境：Java 目标版本 1.8，Spring Boot 2.7.12，MyBatis；分库分表用 `plus.gaga.middleware:db-router-spring-boot-starter:1.0.4`（2 库 4 表，`big_market` 存配置，`big_market_01/02` 存用户数据）。
- 测试现状：app 的 surefire 配置是 `skipTests=true`；20 个测试类全部是 `@SpringBootTest`、要连真实中间件，带断言的很少（全仓库带 assert 的测试文件 14 个，其中有一部分属于 learning-demos）。这和 §11 的判断一致：可见测试要重新写。
- 历史里有 36 个 `fix:` 提交，可以作为"少量参考原版真实修复"的来源。猎场本身不带 git 历史。

### 中间件：必须起的和可以关的
| 组件 | 代码里怎么用 | 测试 profile 的处理 |
|---|---|---|
| **MySQL 8.0.32**（3 个库） | db-router 和 MyBatis，所有核心流程都要 | **必须起**；用 `docs/dev-ops/mysql/sql/big_market*.sql` 初始化，每个测试类开始前重置数据 |
| **Redis 6.2**（Redisson） | 策略装配、库存扣减、分布式锁、缓存键 | **必须起**；库存和缓存键类的 bug 都在这一层 |
| **RabbitMQ 3.12.9** | 4 个监听器：`activity_sku_stock_zero`、`send_award`、`send_rebate`、`credit_adjust_success`，消息由 task 表补偿发送 | **建议起**：MQ 消息字段约定是 §11 指定的跨层 bug 类别之一。只为启动的话可以不连，监听器连不上只会重试，不会导致启动失败 |
| ZooKeeper 3.9 | 只用于 DCC 动态开关（`degradeSwitch`、`rateLimiterSwitch`），由 `zookeeper.sdk.config.enable` 控制，dev 环境默认已经是 `false`；`@DCCValue` 字段为空时按"关闭"处理；DCCController 用 `@Autowired(required=false)` 注入 | **可以关**（§11 把它列成必须起的，按代码看不需要） |
| Elasticsearch 7.17 + canal | ES 用 JDBC 数据源，只给 querys 和 ERP 查询用户抽奖单；canal 把 MySQL 同步到 ES | **关掉**：Hikari 是懒连接，启动时不会连 ES。ERP 查询那一条路径不放 bug、不测 |
| Nacos + Dubbo | `@EnableDubbo`，3 个控制器同时导出为 `@DubboService`，注册中心是 `nacos://127.0.0.1:8848` | **关掉**：测试 profile 里设 `dubbo.registry.address=N/A`（启动时需要验证） |
| xxl-job | 3 个定时任务：task 补偿发送、SKU 库存、奖品库存，执行器端口 9999 | **不起调度中心**：测试里直接调用 job 方法；执行器注册失败只会打日志 |
| Retrofit 网关 | `AwardPort` 调外部接口（`gateway.config.apiHost`），用于一种奖品的发放 | 用 WireMock 或者桩替代，或者这类奖品不放 bug |
| Prometheus、Grafana、Kibana、phpMyAdmin、redis-commander | 只做监控和管理 | 不起 |

### 测试镜像方案（建议）
- compose 一共 4 个服务：`mysql:8.0.32`、`redis:6.2`、`rabbitmq:3.12.9`，加一个运行测试的容器（`maven:3.9-eclipse-temurin-8`，依赖提前装进本地 Maven 仓库，测试时离线运行，不依赖 Maven Central）。
- 新增一个 `application-bench.yml`：ZooKeeper、ES、Dubbo 注册中心、xxl-job 都关掉，网关指向桩；只用这一个 profile 运行可见测试和隐藏测试。
- 可见测试用 Spring 上下文缓存（同一套配置只启动一次）。数据重置用 `@Sql` 或者一个 truncate 加种子数据的工具类。
- **大小预估**：mysql 约 560 MB，redis 约 110 MB，rabbitmq 约 220 MB，maven+JDK8 约 500 MB，依赖约 150–250 MB，合计约 **1.5–1.7 GB**（ES、ZooKeeper、Nacos 都不起，省掉 1 GB 以上）。
- **时间预估**：Spring 上下文冷启动约 15–30 秒；隐藏测试按 50 个 bug、每个 1–2 个用例算，加上可见测试，共享上下文时单次全量运行 **3–6 分钟**，在 10 分钟以内。"逐个 bug 验证"需要 40–60 次构建加测试，可以只编译受影响的模块，并且只跑这个 bug 对应的测试类，以控制总时间。以上都是估计，没有实测。
- r7 的 WSL 里有 docker 29.9（约 25 GB 内存），但没有 Java 和 Maven，所以构建和测试都要放进容器里做。

### 可以放 bug 的位置（初步）
- domain：strategy（装配、权重和概率表、责任链和规则树）、activity（额度、日/月账户、SKU 库存）、award、credit、rebate。
- 跨层（约 1/4）：Redis 库存键和扣减（domain 和 infrastructure 之间）、task 表加 MQ 消息字段（domain、infrastructure、trigger 之间）、幂等键（outBusinessNo、bizId）、积分金额（BigDecimal 的精度和正负号）、库存为零的消息和 xxl-job 更新库存。
- 这些要等改名版本到位后，对照代码再定。

**没做 / 拿不准**
- 只做了阅读，没有在镜像里启动过；`dubbo.registry.address=N/A` 能不能启动、ES 懒连接是否成立，都要等第 2 步验证。
- `plus.gaga` 的两个依赖（db-router、business-behavior-monitor-sdk）是否都在 Maven Central 上，还没核实；仓库里自带的 `.m2/`（14 MB）可能就是为这个准备的。
- 难度标定（第 3 步）按 §11 的要求没有跑。
- 猎场的构造（第 2 步）等 r7 推送 prizehub 之后再做；要不要剔除 learning-demos、resume、interview，请 r7 或用户确认。

## T15 第 1 步（改名版）：prizehub 编译验证（2026-10-11）

**提交**：本节（prizehub 仓库没有改动）

- 来源：r7 `~/git/prizehub.git` main `2805c93`（只有 1 个提交，7 个模块，learning-demos 已经去掉），克隆到 base 的 Arch WSL `~/bench/prizehub`（不在任何公开位置）。
- 命令：`docker run --rm -v $PWD:/src -v ~/bench/m2:/root/.m2 -w /src maven:3.9-eclipse-temurin-8 mvn -B -q -DskipTests test-compile`
- 结果原文：除 12 行 `[debug] execute contextualize` 外没有其他输出，`exit=0`。
- 编译出的 main class 文件 356 个，test class 文件 23 个；本地 Maven 仓库 148M。plus.gaga 下的依赖（business-behavior-monitor-sdk middleware ）都能从 Maven Central 拉到，上次调研中"拿不准"的那一项解决了，用不上原仓库自带的 .m2。
- **没有发现改名误伤**：`cn.bugstack.middleware.*` 按原名保留，可以正常解析；其他外部符号也没有报错。protect.json 不需要补充。
