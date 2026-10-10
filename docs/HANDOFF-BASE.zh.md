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
