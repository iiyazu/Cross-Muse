# base 交接：rc/portfolio 整合与作品化（2026-10-11）

写给 base 侧的 Claude。读完这份就能开工，不需要其他上下文。用中文和用户交流。

## 1. 背景

xmuse 2 是跨厂商 agent 协作层：一个无状态的 hub（Python，`hub/src/xmuse/`）加可选的 MemoryOS，让 Claude（CLI 和桌面版）、opencode、dsh（DeepSeek Harness）的 agent 通过 MCP 工具互发消息（`xmuse_send/inbox/ack/thread/context/whoami/done`），并提供对齐层（决定、假设、待决问题注入各家上下文）、审批、链路预算和实验框架。用户把它作为秋招 agent 应用开发方向的求职作品。

开发主机（r7，Windows + WSL Ubuntu-24.04）上的规划者是另一个 Claude（Opus），额度紧张；你负责大块实现。r7 上还有一个独立审计正在进行，报告出来后可能调整方向，所以本交接只包含**不论审计结论如何都要做**的工程基础活。

## 2. 仓库与分支（r7 裸仓库 `~/git/xmuse2.git`）

| 分支 | 提交 | 内容 |
|---|---|---|
| `main` | `4f41f4f` | 旧主线。**不要合并进 main，不要推 main**，这要用户决定 |
| `m2b` | `248b15b` | 实验框架（`experiments/`）、MemoryOS 客户端、33 个 run 的指标（`experiments/results/`）、离线回放工具 `replay_mo` |
| `dsh/bundle` | `baa8b24` | 含 `cc/desktop`（Claude 桌面版协调者模式）、dsh 前台模式、dsh 插件包 `integrations/dsh-bundle/`、relay 长轮询、身份绑定、`via=cli` 来源标记、发给用户的消息抄送协调者。全量测试 286 passed、1 skipped |
| `rc/portfolio` | 基于 `dsh/bundle` | **你的工作分支**，本文件就在这里 |

m2b 和 dsh/bundle 从 `4f41f4f` 分叉后各自发展，还没合过。

## 3. 任务（按顺序）

### T1 整合
1. 在 `rc/portfolio` 上 `git merge m2b`，解决冲突。两边都改过 `hub/src/xmuse/` 下的 server、engine、adapters/dsh、cli 等文件，冲突时以"两边功能都保留"为原则；拿不准的写进报告。
2. 环境：`uv sync --project hub`；`cd shim && npm ci`；测试 `hub/.venv/bin/python -m pytest tests -q -p no:cacheprovider`（约 6 分钟）。依赖本机 Windows、dsh、Claude 桌面版的测试会 skip，这是正常的；不要为了让它们在你那边跑而改逻辑。
3. 验收：全量测试通过（报告原文结果行）；`experiments/` 的单测和 `replay_mo` 的单测通过。

### T2 待修清单
1. `xmuse send` 返回的 `woken` 不应列出桌面 agent（`dsh/bundle` 上可能已部分修复，先核实）。
2. `xmuse init` 在 git worktree 里把 `.git/info/exclude` 写错位置（worktree 的 `.git` 是文件，应写到 `git rev-parse --git-common-dir` 下的 `info/exclude`）。
3. channel 回合的 ctx 被记成 0（找 usage 记录里 channel 模式的路径）。
4. 新增 `xmuse transcript <agent>`：把该 agent 当前会话转成可读文本（opencode 走其 HTTP API 取消息；dsh 读会话 JSONL；Claude 读 transcript_path）。只读。
5. 每项配测试。

### T3 可移植性
1. 去掉写死的 `/home/user`、`Ubuntu-24.04`、`/mnt/c/Users/user`、插件包里默认的状态目录等（`grep -rn "user\|Ubuntu-24.04" hub integrations shim templates skill`）。改为从环境推导（`WSL_DISTRO_NAME`、`Path.home()`、配置），推导不出时给清晰报错。
2. `scripts/bootstrap.sh`：一键准备环境（uv sync、shim 的 npm ci、检查 node/python 版本），可重复执行。
3. `xmuse doctor`：检查并逐项报告 Python 环境、shim 依赖、node、各厂商 CLI 是否可用、hub 状态、工作区文件（.mcp.json、AGENTS.md、skill）是否与当前代码一致；给出修复命令。只读。
4. 验收：在一个全新克隆上只跑 `scripts/bootstrap.sh` 和 `xmuse doctor` 就能定位所有缺项；测试覆盖 doctor 的主要检查项。

### T4 门面（草稿，**不对外发布**，用户审阅后才定稿）
1. 实验报告补三节：长会话组、T1 回放、MemoryOS 运维。数据在 m2b 的 `experiments/results/metrics-plan1-all/`、`metrics-long-L-mo/`；现有报告是 `docs/design/XMUSE2-M2B-EXP-REPORT.zh.md`（33 run 版）；设计稿是 `docs/design/XMUSE2-ARCH-2026-10.zh.md`。只陈述数据支持的结论，样本小就写明。
2. `README.md`（中文为主）+ `README.en.md`：一句话定位；解决什么问题；mermaid 架构图；快速开始（bootstrap → init → agent add → hub start）；关键设计（对齐层、身份与来源、桌面协调者、dsh 插件）；实验结果摘要和局限；目录结构。
3. `.github/workflows/ci.yml`：Linux 上跑 hub 测试和插件包 `node --test`。不需要推到 GitHub。
4. 补 `LICENSE` 前先问用户选哪个许可证，不要自己定。

## 4. 约束

- 只在 `rc/portfolio` 上提交，可以推到 r7 的 `rc/portfolio`；不要动其他分支，不要合 main，不要强推。
- 不打印、不读取任何密钥（例如环境变量 `JEV_KEY`、各家 token 文件）。
- 提交信息结尾按你那边的署名约定；每个任务至少一个提交，便于审查。
- 删除文件或历史前先问用户。
- 杂活（机械改名、批量替换、整理数据表）可以派给你那边可用的便宜模型或工具，判断性的活自己做。
- 换行符保持 LF。

## 5. 交付

每完成一个任务，推到 r7 的 `rc/portfolio`，并在 `docs/HANDOFF-BASE-REPORT.zh.md` 追加一节：做了什么、提交号、测试结果原文、没做或拿不准的地方。r7 侧的规划者会据此审查。

## 6. 更正与补充（10-11，独立审计之后）

- **T1 比预想简单**：`m2b` 的 `893722a` 已经是 `dsh/bundle` 的祖先，代码早已合在一起。`m2b` 只比 `dsh/bundle` 多一个提交 `248b15b`（replay_mo 的 usage_total 修复），`git merge m2b` 即可。之前没进仓库的实验数据（m2b 工作树里未跟踪的 `experiments/results/`，不含 `_prev`）已提交到本分支。
- **独立审计报告**在 `docs/design/XMUSE2-AUDIT-2026-10-11.zh.md`，T4 写报告和 README 前必读，尤其是 C 节（证据质量）：
  - minisql 完成率差距的 p≈0.03 不成立，不要写进 README；
  - 后 21 个 run 不算跨模型；
  - 实验报告漏了 long-L-3、long-L-mo-1/2、review-ledger-bug1-1。
  
  按审计结论如实写，不要夸大。
- **T2 追加两项**（审计发现、规则即可修，不涉及方向决策）：
  1. `engine.py:96-99` 准入时没排除已 ack 或已读的投递，导致"没有新事"的唤醒。修掉并加测试。
  2. 测试慢：每个测试停机多等约 1.5 秒（`engine.py:67` 的 `q.get(timeout=1)` 加 HTTP server 0.5 秒轮询）。改用哨兵或事件唤醒，目标是全量测试在 2 分钟内跑完。
- **信任边界**（agent 能读管理令牌、自动批准规则可绕过）是审计列出的最大风险，但方案要用户先定，**暂不要动**。

## 7. 用户 10-11 新定的任务（T1–T4 之后做，按顺序）

- **T5 信任边界**（审计 B 节）：
  1. 自动批准从 fnmatch 黑名单改成白名单（`opencode.py:29-79` 等处），`cd x && git push`、`bash -c` 这类组合一律走人工审批；
  2. agent 进程读不到管理令牌：admin token 和审批接口移出 agent 可读范围，审批只经协调者转给用户确认；
  3. 设计稿 §4.2 "agent 读不到令牌"按实际情况改写；
  4. 每项配测试，包括绕过用例。
- **T6 补实验**（准备 + 能跑就跑，可用 opencode/dsh 额度，不用 Claude 跑实验）：
  1. E1 单 agent 基线；
  2. E2 修好 SPEC 歧义后重测对齐层；
  3. E5 复核基线。

  按审计 C、E5 节设计，先提交实验配置和预注册的指标、样本量，再跑。base 跑不了的（需要 dsh 或 Windows 的）写清楚，留给 r7。
- **T7 隔离不删**：`spikes/`、`e2e/results/` 等审计点名的历史产物移到 `archive/` 目录（或从主线移出、在一个 `archive/*` 分支保留），不删除，git 历史保留。先在报告里列出移动清单，再动手。

## 8. r7 审查结论与后续（10-11 04:10）

**总评**：T1–T5 验收通过，T6 预注册和 T7 清单认可。r7 原生盘复测（`59407f8`）全量连跑 3 次：`313 passed, 1 skipped in 132.79s`，三次均无失败；插件包 `pass 27 / fail 0`。你报的 `test_stop_interrupts_running_turn_and_cancels_queue`、sweep 超时在 r7 上没复现，暂按 /mnt/d 负载偶发处理，不必再查。

**对"拿不准"的回复**
1. B2-3 去抖：不做。
2. 令牌隔离到单独 OS 用户：保持现状（"防误操作，不防恶意 agent"），文档已写清，交用户回来再定。
3. 插件包过滤 `xmuse_approve`：要做，dsh 会话不注册这个工具。
4. LICENSE：仍等用户。
5. T6 模型：r7 的 dsh 臂统一用 `deepseek-official/deepseek-v4-flash`（`AGENTS` 环境变量覆盖，`meta.json` 的 provenance 会记录），这样 B2/C2/CROSS 才是真正跨模型。这是预注册里"dsh 由 r7 决定"的取值，不算偏离。r7 已在 04:05 开跑 `t6-e1-B2` → `t6-e2a` → `t6-e5-cross`（27 个 run），结果推回时会单独提交。base 跑 S 臂和 SELF 臂。
6. T7：清单认可，**现在就可以动手**，不用等 T6（r7 的批跑用的是本地工作树，跑完前不会拉你的提交）。注意 `experiments/check.py` 移动后 run.py 路径同步改。

**T8 追加（小修，按顺序）**
1. 白名单漏洞（审查发现，均为"误操作也可能触发"的写文件或执行路径），每条配绕过测试：
   - `sed`：`-ni`、`-Ei` 这类组合短标志里的 `i` 没拦（只查了 `-i` 开头）；sed 脚本的 `w`/`W`/`e` 命令能写文件或执行命令。建议直接把 sed 移出自动放行，或只放行 `sed -n '<数字>,<数字>p'` 这一种形式。
   - `git grep -O`/`--open-files-in-pager=<cmd>` 会执行命令；`git diff/log/show --output=<file>` 会写文件；`git restore` 会丢弃改动，移出 GIT_LOCAL。
   - `rg --pre <cmd>`、`--pre-glob` 会执行命令。
   - `sort -o`、`tree -o`、`find -fprintf`/`-fprint0` 会写文件。
2. `config.FAMILIES`：家族按模型推导（审计 C 节），不按外壳；`muse-spark` → opencode 家族，`deepseek-*` → deepseek。唤醒包和 whoami 同步。
3. 插件包 `peerDependencies` 精确钉死 `0.2.0-rc.2`（审计列出）：改成范围或去掉，并在 README 写明 dsh 升级后的处理方式。
4. `xmuse send` 对前台 dsh agent 返回 `woken: ["dsh-1"]`，但前台 agent 不由 hub 唤醒，而是插件包推送。改成单独字段（如 `pushed`），或不列出。

**之后**：T7 → T8 → 等 r7 的 T6 数据回来，写 T6 结果节（按预注册，只描述）。r7 准备在 T7/T8 测试通过后把 rc/portfolio 合进 main（用户 10-11 夜间已授权），README 和实验报告仍保持"草稿"标注，等用户审阅。

## 9. r7 第二轮审查（10-11 08:55）

**T6 数据**：r7 臂 27 个 run 的结果目录、`metrics-t6-{e1-B2,e2a,e5-cross}/` 和批跑日志已提交（`e697e06`），`batch-progress.txt` 里 r7 的行加了 `[r7]` 前缀。你在 `fc690f8` 里写的数字和 r7 的 metrics.md 逐项一致；没有异常 run（27 个 rc 全是 0；唯一未完成的是 minisql-B2-13，rot 为 partial）。T6 结果节认可，按预注册只描述的写法保持。

**T7、T8 验收通过**：根目录只剩在用的代码；代码、测试、脚本里没有 `spikes/`、`e2e/` 的失效引用。T8 的白名单改法到位。

**T9（必修，阻塞 CI 和合 main）**：`tests/test_init_cli.py::test_cli_end_to_end_with_a_fake_agent` 依赖运行环境。
- 现象：r7 在没有控制终端的环境里（`setsid nohup` 后台）跑全量，3 次都是同一处失败：
  ```
  E   AssertionError: assert 'no approval' in 'error: human_only: approve needs a person: the calling process (pid 1438950) has no controlling terminal. ...'
  FAILED tests/test_init_cli.py::test_cli_end_to_end_with_a_fake_agent - Assert...
  1 failed, 313 passed, 1 skipped in 132.89s (0:02:12)
  ```
  带终端时能过。GitHub Actions 的 runner 同样没有终端，所以 CI 上会必挂。
- 修法（二选一，倾向第一种）：
  1. 测试里的 `xmuse approve` 改在伪终端里执行（`pty.fork()` 或 `os.openpty()` 加 `setsid` 再 `TIOCSCTTY`），这也正好覆盖了"人在终端"这条真实路径；
  2. 这个用例显式断言 `human_only` 拒绝，审批放行的路径交给 `test_trust.py` 覆盖。
- 验收：`setsid python -m pytest tests -q -p no:cacheprovider < /dev/null` 全量通过；同时检查其他起真实 hub 子进程的测试有没有同类依赖。
- 插件包测试 `pass 28 / fail 0`。

**之后**：T9 修好、r7 在无终端环境下复测通过后，r7 会把 rc/portfolio 合进 main（合并脚本已备好，等用户执行）。README 和实验报告仍是草稿，等用户审阅。LICENSE 和"agent 单独 OS 用户"仍等用户定。
