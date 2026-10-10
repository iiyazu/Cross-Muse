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
