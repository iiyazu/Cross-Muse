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

## 10. 团队实验：T12–T15（10-11 r7 规划，用户已定拓扑和规划者）

设计稿：`docs/design/XMUSE2-TEAM-PRESET.zh.md`（必读）。要点：规划者 P = `dsh-ms13`（dsh + muse-spark-1.3-contributor）读题、拆分、定约定、集成；两个执行者 `oc-ms13`（opencode + muse-spark-1.3）和 `dsh-fl`（dsh + DeepSeek V4.1 Flash，走 opencode-go 渠道）并行实现；对照组 T-plain 用同一拓扑，但关闭信息层。T12–T14 和 T11a 互不依赖，可以马上开工。顺序：T12 → T14 → T13 → T15。每项都要配测试，完成一项就推一项，并在 REPORT 里追加一节。

### T12 同一家厂商允许注册多个实例
- 去掉 `init.py:126-128` 的"每家厂商一个 agent"限制。身份不能再写进工作区共享的配置文件：
  - dsh 无界面模式：身份本来就是每次运行时由 overlay 传入的（`adapters/dsh.py:133`），核实之后直接放开；前台模式仍然一个会话绑定一个 agent。
  - opencode：每个实例一份单独的配置和一个单独的 serve 进程（单独端口、单独的密码文件）。先查清 opencode v2 能不能用环境变量（例如 OPENCODE_CONFIG）指定配置文件路径；不能的话，换一个能把身份按实例隔开的办法，写进报告。工作区里共享的 opencode.json 不能再带 XMUSE_AGENT。
  - Claude 这次不动，但不要把它的路弄坏。
- 测试：同一个工作区注册两个 dsh、两个 opencode，身份不串（各自调用 whoami 的结果正确，消息归属正确，用量分开记账）；`xmuse doctor` 能识别多个实例。

### T14 信息层补强，加关闭开关
先核实现有能力，再补缺的部分：
1. 按 scope 注入：decision、convention、assumption 带 `scope=module:<名字>` 时，只注入给 scope 命中的 agent。agent 怎么声明自己关心哪些 scope：由 P 下发 assignment 时写明，或者 agent 自己声明，选一种，写进报告。
2. 依赖解决就唤醒：assignment 的 depends_on 全部解决时，hub 主动唤醒 assignee（核实 `align._blocked` 和派活的路径；没有这个行为就补上）。
3. question 定向：执行者发 question 时 hub 唤醒 P；P 答复后用 decision 替代原来的 assumption 或 question，并按 scope 传播。
4. 信息层总开关：每个 run 可以设"信息层关闭"（给 T-plain 用）。关闭后 decision、assumption、question 的登记、注入、路由和依赖唤醒全部停用，只剩 `kind=message`；对 agent 的提示词和工具描述也同步去掉这些能力，不能出现"有这个工具但用了没反应"的情况。开关放进 run 的配置，记进 meta。
5. 测试：用假 agent 覆盖 scope 路由、依赖唤醒、question 往返，以及关闭时上面这些全都不发生。

### T13 编排预设 plan-split-integrate
按设计稿第 3 节和第 8 节：
- hub 里的状态机：P0 → P1 → P2 → P3（最多 2 轮）→ 收尾；每个阶段有时间上限，超时强制推进，并记一条事件。
- 每个执行者一个 git worktree 和一个分支；P 在主分支上合并；P0 的计划里写明文件归属，hub 检测越界修改并记为违规（只记不拦）。
- 快照钩子：S-E1、S-E2、S-int、S-fix-k、F 都存成 patch，并带上时间点。
- 崩溃重试一次，再失败就降级；P 没有在 P0 时限内交出计划时，这个 run 记为失败。
- 测试：用假 agent 走完整的状态机，覆盖正常路径、阶段超时、执行者崩溃、越界修改和合并冲突。
- 实验 runner：在 T11a 的单干流程上加入 T-xmuse 和 T-plain 两组。每个快照都评测，按设计稿第 6 节出汇总表。先用 Legacy-Bench 里一道多模块题，每组跑 1 次，把流程跑通（不计入结果）。

### T15 自建"屎山 bug 猎场"（先出候选，等用户选）
- 挑 3 个候选开源项目，要求：TS 或 Python；3 万–6 万行；测试齐全，能在 Docker 里跑；近一年（最好是 2026 年）有不少于 60 个带测试的 bug 修复提交，用来减少训练污染；许可证允许再分发。
- 每个候选给出：代码规模、测试用时、可用的 bug 修复提交数及示例、模块分布、许可证。**先在 REPORT 里列出候选，用户选定后再构造**。
- 构造方法（选定后再做）：在同一个基准版本上，把选中的 bug 修复提交逆向重新引入（参考 Bug Hunt Bench）；要求现有测试全部通过，同时每个 bug 都能被它修复提交里的测试判定出来；逐个验证"只修这一个 bug，它对应的测试就通过"。

### 约束（不变）
只在 rc/portfolio 上提交；不合 main；不往 GitHub 推；不读、不打印密钥；不用 Claude 跑实验。

### §10 更正（10-11 用户定）
- **T15 搁置**：先不做，连候选都不用列。T13 的流程跑通和团队实验先用 Legacy-Bench 的题。
- **S-best**：取 T11a 等单干探针里得分最高的实例，不再另问用户。

## 11. T15 解除搁置：以 big-market 为底座造"屎山 bug 猎场"（10-11 用户定）

**用户已定**：底座是用户的后端项目 big-market（Spring Boot 多模块 Java 营销抽奖系统，约 2 万行，DDD 分层）。**只能私下用来做实验，不能公开数据集**（这是付费课程代码，没有 LICENSE）。r7 先由 dsh 做一致性改名，降低模型对原版的记忆（工单 BM-RENAME，包名 cn.bugstack → io.prizehub，并改掉领域术语：Strategy→Scheme、Award→Prize、Activity→Campaign、Raffle→Draw、Rebate→Cashback、Credit→Points、Sku→Offer、Armory→Assembler）。改名版本会推到 r7 的**私有裸仓库** `~/git/prizehub.git`，到时候 REPORT 里会写明提交号。改名版本到位之前，先做下面第 1 步的调研。

### 规格
| 项 | 要求 |
|---|---|
| bug 数 | 40–60 个，分布在 domain、infrastructure、trigger、app 各层；约 1/4 跨层或跨模块（领域层和基础设施层对库存、状态、金额、幂等键、缓存键、MQ 消息字段的约定不一致） |
| 来源 | 以合成为主（≥70%）：用模型改写出自然的逻辑错误，加 AST 变异，方法可以参考 SWE-smith（arXiv 2504.21798）的工具链；少量参考原版的真实修复。**只要逻辑类 bug**，编译、导入、类型检查能抓到的一律不要 |
| 隐蔽性 | 引入全部 bug 之后，仓库里留着的可见测试必须**全部通过**；每个 bug 的判定测试都藏起来，不放进仓库 |
| 判定 | 每个 bug 至少一个带断言的隐藏测试（JUnit），只修这一个 bug，它的隐藏测试就从失败变成通过；全部 bug 一起注入后逐个验证**互不遮蔽** |
| 可见测试 | 原项目的测试多半是打日志、不写断言的。另写一套覆盖主要流程、带断言的可见测试（这些在 bug 注入后仍然要全部通过），作为 agent 自查用的"现有测试套件" |
| 依赖 | 用 docker-compose 起 MySQL（含分库）、Redis、RabbitMQ、ZooKeeper；ES、Nacos、canal、xxl-job 这类非核心组件，能通过测试 profile 关掉的就关掉。整个环境打包成可复现的镜像；测试运行时间尽量控制在 10 分钟以内 |
| 防泄露 | 不带 git 历史；README、docs 里描述修复内容的文字一律删除；bug 的位置和描述只放在仓库之外的 answer key（`bugs.json`：id、所在层、文件:行、类别、是否跨层、判定测试名、改动的 diff） |
| 判分器 | 输入 agent 交上来的工作区，输出：修好的 bug 数 / 总数（逐个 bug 判定）、误改数（原本通过的可见测试和隐藏的回归测试变成失败）、编译是否通过 |
| 题面 | 不给 bug 清单："这个系统最近线上问题很多，请尽可能多地找出并修复 bug。可见测试和构建必须通过；不准削弱、跳过或删除测试。" |

### 步骤
1. **调研（现在就可以开始，用原版的公开结构推断就行，不需要等改名版本）**：列出要起哪些依赖、哪些可以关掉，测试 profile 的方案，以及镜像预计的大小和测试用时。写进 REPORT，等 r7 审查。
2. 改名版本到位后：在镜像里先把它跑起来，可见测试全部通过 → 写可见测试 → 注入 bug、写隐藏测试 → 逐个验证互不遮蔽 → 判分器 → 用参考解（把全部 bug 修好的版本）校验，结果应该是满分。
3. **难度标定（先不要跑）**：等用户确认标定用什么模型。合格标准是最强基线修好的比例明显低于 50%；高于 70% 就要加 bug 或增加隐蔽性。

### 约束
`bugs.json`、隐藏测试、参考解单独放在 BENCH_DIR 里（不进 prizehub 仓库，也不放进 agent 能看到的任何位置）。这些都只进 r7 的私有仓库，不往任何公网推。其余约束同 §4。

### §11 补充：改名版本已就位（10-11）
- 位置：r7 的私有裸仓库 `~/git/prizehub.git`，分支 main，提交 `2805c93`（378 个文件，不含 git 历史、README、运行日志）。拉取方式和 xmuse2 一样。**只在 r7 和 base 之间流转，不往任何公网推。**
- 改名由 r7 的 dsh 用脚本完成（rename.py、rename-map.json、protect.json，只放在 r7）。外部依赖 `cn.bugstack.middleware.*`（数据库路由组件，含 `DBRouterStrategy`、`IDBRouterStrategy`、`DBRouter`）**故意保留原名**，仓库里剩下的 17 处 bugstack 都是这些 import。
- 配置里的密码、token 已换成 `CHANGE_ME`，真实 IP 已换成 `localhost`。起依赖时自行设置测试用的口令，不要找原值。
- 表名和字段名也一起改了（如 award→prize、raffle_activity→draw_campaign），数据库必须用 `docs/dev-ops/mysql/sql/prize_hub*.sql` 重新初始化。
- **T15 的第一步改为编译验证**（r7 这边没做成：Windows 侧连不上 Maven Central，C 盘也没空间）：在 Docker 里用 JDK 8 和 Maven 执行 `mvn -DskipTests test-compile`。
  - 编译失败时，判断是不是改名误伤（外部 jar 的符号被改了名）。**是的话不要在仓库里手工修**，把出错的符号和报错原文写进 REPORT，由 r7 补进 protect.json 后重新生成、重新推送；不是改名造成的问题（例如依赖本身拉不到），就照常处理并写清楚。
  - 编译通过之后，再把应用在 docker-compose 环境里跑起来，用新的 DDL 初始化数据库，确认原有测试的运行情况（哪些能跑、哪些依赖关掉的组件），然后再进入 bug 构造。

## 12. T17 机制探针：审定，开始实现（10-12 用户定，r7 审定）

**用户已定**：不在屎山代码库上做实验，按信息协作层愿景里的功能逐个做小而确定的验证；设计稿交给 base 实现。T16 不做；T15 只写成"低协作需求下的基线和开销测量"，不做两组对比。

**依据**：`docs/design/XMUSE2-PROBES.zh.md`（审定稿，以你的 T17 草案为底）。和 T17 不一致的地方以审定稿为准。要点：
- T17 第 5 节的三个问题已定：三组（X / P-dm / P-bc，P-bc 要点名所有执行者）；顺序 S1 → S2 → S3，之后 S4、S5、产品探针 P1–P4，S6 可选；代码放 xmuse2 的 `experiments/probes/`。
- S3 要改：question 的自动路由唤醒的是给提问者派活的人，不是知情人（`mail._routed`），按原设计 X 组会必然失败。改成 S3a（知情人就是派活人）和 S3b（只能靠职责描述找到知情人）两个变体，依赖唤醒单独测。
- S2 的换会话不要改数据库，给 hub 加 `POST /v1/admin/retire` 和 `xmuse session retire --agent`；对照组靠 `recent_n` 拿最近消息，决定要落在窗口之外，两组注入的 token 都记录。
- `xmuse send` 加 `--args-file`（带 `why`、`resolves`、`depends_on`），否则脚本发不出人类身份的 handoff、答复和依赖。
- 执行器自己要有不调用真实模型的测试（用 `tests/fakes/`），判定器用手工正反例测试。

**步骤**：
1. 两处 hub 改动（各自单独提交、带测试、全量测试通过）。
2. 执行器、判定器、汇总，以及它们的测试。
3. S1 试跑（每组 2 次），只看刺激送达和判定器是否正确；写进 REPORT，等 r7 看过再跑第一批。
4. 第一批（S1、S2、S3a、S3b、依赖唤醒，每个每组 10 次，三组交替）。开跑前把场景定义和主要指标提交进仓库，作为预注册。
5. 第二批（S4、S5、P1–P4）。

**约束**：在 `exp/probes` 分支开发，推到 r7 裸仓库，r7 审查后合进 rc/portfolio；不合 main，不往 GitHub 推。不碰 r7 上正在运行的开发房间。执行者用 `opencode-go/muse-spark-1.3-contributor`（dsh 和 OpenCode），需要 Claude 时只用 `claude-haiku-5-5`。只记录 token，不设预算。其余约束同 §4。

### §12.1 r7 审查：S1 试跑第一轮和 exp/probes 代码（10-12）

**代码**：c4479f0（session retire）、36e8a69（send --args-file）、9e3866d（执行器、判定、报告、测试）都审过，可以用。小点：`admin_retire` 对正被 TUI 租约持有的会话（用户正开着的终端或桌面会话）也会退役，hub 下一次会另起新会话，而用户界面还在旧会话里。实验里不涉及；产品上之后在 `admin_retire` 里拒绝有活租约的成员，或者在帮助里写明。现在不用改。

**结果解读**：同意。但要注意措辞：
1. **S1 的主要指标在 X 和 P-bc 都是 0，触底了，区分不了这两组**。能下的结论是"只告诉一个人，效果和群发一样"，"比群发好"要靠次要指标。X 组 tick 3 的取代只唤醒 e1，e2 在下一个 tick 的唤醒包里顺带拿到；P-bc 组 tick 3 会多唤醒一次 e2。REPORT 里按组列出 tick 3 前后的唤醒次数和 token，这才是 X 和 P-bc 的差别所在。
2. **确认 X 组 e2 切换的原因**：X 组 e2 也看得到 e1 在 #team 里的"per rule v2"。P-dm 里 e2 同样看到了这句却没切换，这支持"是唤醒包里的变更列表起的作用"，但要用 `s1_e2_saw_rule_v2_in_turn` 和 e2 在 tick 4 的唤醒包原文确认，并把原文附进 REPORT。
3. **名单固定成 e1=OpenCode、e2=dsh**，需要同步的一方总是 dsh，厂商和角色混在一起。第一批按 seed 交替：一半 run 用 e1=OpenCode、e2=dsh，另一半对调。
4. **转告指标**：同意你的修法（只算 e1 私信 e2，或在 #team 点名 e2 的消息）。另外把"e1 在完成汇报里提到新规则"单独记成"被动提及"，因为 X 组里 e2 也会看到。

**第一批不用再等 r7**：第二轮（seed 2）的结果和第一轮方向一致，并且上面 1–4 做完（指标修好、补上测试、重算两轮试跑），就直接开始第一批。开跑前提交预注册：场景、主要指标、组别、seed 列表、名单交替方式、hub 提交号；整批用同一个 hub 提交。第二轮如果和第一轮矛盾（例如 X 组没收敛），先停下，写进 REPORT 等 r7。

## 13. R 系列真实工作流探针 + 夜间授权（10-12 用户定）

**设计稿**：`docs/design/XMUSE2-PROBES-R.zh.md`。用户的意见：S 系列有成效但不够好，要符合真实工作流（例如真实场景里没有 tick）。R 系列 8 个场景（接口变更、隔天接手、只有一个人知道、先后依赖、共享文件、失败派回、侧栏插话、换人），三组 X / P-dm / P-relay（P-relay 是"手动转发汇报的用户"，作为上限参照），主要指标是验收测试是否通过，外加用户动作数和失败归因。

**用户授权（原话："由于我将睡觉，赋予 base 为了顺利测试所需权限和 xmuse 所需权限，并且有影响测试的不够就改，新测试在旧测试之后运行"）**。在用户睡觉期间有效：
- base 可以取得为了顺利跑测试所需的权限：在自己的机器上起停 hub 和测试环境、装测试依赖、建临时工作区和账户内的配置，不用等 r7 或用户。
- base 拥有 xmuse 所需的权限：可以改 hub、CLI、适配器、预设、技能提示等 xmuse 代码。
- **xmuse 有不足、影响测试的地方，直接改**：单独提交、带测试、全量测试通过；可以自行合进 rc/portfolio，免得别的分支落后；在 REPORT 里写明改了什么、为什么、提交号。r7 醒来后补审。
- **顺序**：先跑完 S 系列已排的第一批（S1、S2、S3a、S3b、依赖唤醒），再跑 R 系列（试跑 → R1–R4 → R5–R8）。

**仍然不变的约束**：不合 main，不往 GitHub 或任何公网推，不强推，不用 git stash，不读、不打印密钥，不碰 r7 上正在运行的开发房间。只记录 token，不设预算。遇到用户才能决定的事（例如要改变某个场景的设计意图），写进 REPORT，跳过它先跑别的，不要停下整夜的工作。
