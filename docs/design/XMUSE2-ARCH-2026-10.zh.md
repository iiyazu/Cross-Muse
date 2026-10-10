# xmuse 2：参考调研与架构设计（2026-10-09）

> 状态：用户已同意设计。10-09 晚先按 M0 修订（修订前存为 `.XMUSE2-ARCH-2026-10.pre-m0.bak`），之后按 **M0-dsh 和 M1** 再修订（这次没有留修订前的副本；改动范围见文末"修订记录"）。
> 依据：用户 10-09 定下的方向、本文第 2、3 节的调研，以及三份实测报告：`XMUSE2-M0-REPORT.zh.md`、`XMUSE2-M0-DSH-REPORT.zh.md`、`XMUSE2-M1-REPORT.zh.md`。代码在 `~/dev/xmuse2`，M1 已合并到本地 `main`（`1523440`）。

---

## 0. 一页结论

**产品定位**：xmuse 是**装在各家 agent 里的协作插件**，不是把 agent 装进来的平台。

- 各家 agent（Claude Code、OpenCode、dsh）照常在自己的终端里运行，原生能力和权限系统都保留。
- xmuse 给它们提供四样东西：身份、私聊、群聊、协作上下文。
- MemoryOS 是**协作信息层**：把对话沉淀成决定、接口约定、分工和未决问题，agent 按需取用，不用每次都读全部群聊。
- 可靠性是第二优先级，交给标准 git 流程。

**调研得出的五个关键判断**：

1. **最接近的开源先例是 Clowder AI（Cat Café）**。它已经验证了这条技术路线：各家 CLI 子进程加 `--resume`、MCP 回传让 agent 主动发言、@ 路由、跨模型复核、共享记忆。它的教程把事故写得很坦白，这些教训可以直接拿来用。但它已经长到 6704 个 TS 文件、仓库 1.3 GB，**要学的是它早期的设计，不是它现在的体量**。
2. **唤醒在三家各有一条路，但都不一样**（M0 已实测）：
   - Claude Code：channels（research preview）能把消息推进空闲的交互会话，约 1.4 秒；无界面用 `-p --resume`。**两条路不能同时用在同一个会话上**：TUI 开着时无界面写入会静默分叉，所以 hub 必须持有会话租约；
   - OpenCode 2.0.21：后台服务的 `POST /api/session/{id}/prompt`（本身异步）加 SSE `GET /api/event`。服务端用持久化收件箱串行化所有输入，hub、人、TUI 同时写也不分叉，是三家里最干净的；
   - dsh（替代原定的 agy，agy 无界面 MCP 只能全局放行、并发会静默覆盖）：`--profile headless --json --session-id` 续接，并发写时**明确拒绝**后到者；不用改 dsh 源码。但只有 Windows 版，工作区必须是 `C:\` 原生路径，也没有本地推送通道。
3. **MCP 的 stdio 工具是三家共同的最小公分母**。服务器主动发起的请求不能依赖：MCP 2026-07-28 规范已经把 sampling 标为弃用，核心改成了无状态。
4. **Agent Skills（SKILL.md）可以跨三家使用**。协作规范（交接格式、出口检查）可以写成技能，而不是塞进每家的系统提示词。
5. **商业产品（Grok Bot、ChatGPT Dots）和社区实践在同一点上一致**：开放群聊会让 agent 互相抢话、烧 token；**点名协作**和**小阵容**更有效。这和 xmuse 自己的评测（点名模式轮次 28 → 8，质量持平）以及 M3 结论（整理后的笔记本 2/3 照做，原文召回 0/3）相互印证。

**架构一句话**：一个本地守护进程 `xmuse-hub`（Python，复用 xmuse 和 MemoryOS 的资产），加上每家 agent 一个很薄的插件（MCP stdio 工具、一个技能、钩子）。hub 负责：
- 持久化消息；
- 按"一个收件人同时只跑一个回合"的规则投递和唤醒；
- 在唤醒时注入由 MemoryOS 整理的协作上下文；
- 可选：基于 git worktree 的验证和合并。

---

## 1. 愿景与约束（用户 10-09 确定）

| 项 | 内容 |
|---|---|
| 第一优先 | 本地多个独立 agent 的协作层：交流顺畅，各自保留原生能力；xmuse 是各家 agent 的插件，不做统一界面；像 Grok Bot 那样能私聊、能群聊 |
| 协作信息层 | MemoryOS 提高信息同步效率、降低协作成本，要比无脑群聊好 |
| 第二优先 | 可靠：编排和实现分开，集成交给标准 git 流程。现有 xmuse 过度设计 |
| agent | 从 Claude Code、OpenCode、dsh、agy 中选容易实现、实验需要的数量（只有这几家有额度）。本文选 **Claude Code、OpenCode、dsh** 三家（M0 后由 agy 改为 dsh），理由见 §3.2 |
| 自主性 | agent 能在用户不在场时**自主推进** |
| 时间 | 等新原型，不用现有系统录 demo |
| 复用 | 能复用 xmuse 的资产就复用；复用效果不好就直接重写 |

---

## 2. 参考项目调研

### 2.1 总览

| 项目 | 是什么 | 和 xmuse 的关系 | 借鉴 | 避免 |
|---|---|---|---|---|
| **Clowder AI / Cat Café**（zts212653） | 开源的多 agent 协作平台，Claude、Codex、Gemini、OpenCode 都通过 CLI 接入；教程完整复盘了建设过程 | **最接近的先例** | 用 CLI 不用 SDK；MCP 回传作为"嘴巴"；同一语义只留一条触发路径；深度上限和可取消；出口检查；Session Chain；Why-First 交接；A2A 投递内核的五条原则 | 统一的 Web 界面（与"插件"定位相反）；后期的体量膨胀 |
| **Grok Bot**（xAI） | 云端常驻的命名 agent 团队，有私聊、群聊和审批；编码交给 Cursor | 外形最像，但单一厂商、在云端 | 最小阵容；点名优于开放群聊；审批只放在有后果的动作上；记忆不是事实来源；用证明判断完成 | 共享电脑、没有隔离；模型评判模型 |
| **ChatGPT Dots**（OpenAI，9 月 29 日 DevDay） | 常驻 agent，各自有云端电脑和记忆 | 同类商业产品 | 和 Grok Bot 一样：常驻、目标驱动 | 公开资料里没有看到内置的多 dot 协作 |
| **mcp_agent_mail**（Dicklesworthstone） | 给编码 agent 用的"邮件系统"：身份、收件箱、话题、全文检索、建议性的文件预留 | 消息层的直接参考 | 数据模型（每个收件人单独记录已读和确认）；`fetch_inbox(since, unread_only)`；文件预留加 pre-commit 守卫；git 存可读的归档、SQLite 做索引；"发现不等于授权" | **只能轮询**，没有唤醒，agent 不会自己醒来 |
| **beads**（Steve Yegge） | 基于 git 的 agent 任务跟踪，`bd ready` 列出没有被阻塞的工作 | 任务权威 | 分工：任务状态放在任务系统，对话和决定放在消息系统，用同一个 ID 串起来 | 不必引入，但这个分工原则要采用 |
| **Claude Code agent teams** | 一个 lead 会话创建多个队友，每人一个收件箱（JSON 文件），用 SendMessage 通信 | 官方的单厂商团队 | 收件箱加点对点消息的最小模型 | 只限 Claude，实验特性；`/resume` 恢复不了进程内的队友 |
| **Claude Code channels** | MCP 服务器通过 `notifications/claude/channel` 把事件推进**正在运行的**会话；可以带回复工具和权限转发 | **Claude 这一家的唤醒方案** | 推送事件、发送者门控、权限请求转发到 hub | research preview；自定义 channel 要加 `--dangerously-load-development-channels`；`-p` 模式下无效 |
| **vibe-kanban、claude-squad、Conductor、git-worktree-runner 等** | 每个任务或 agent 一个 git worktree 加一个分支 | 可靠性层的参考 | worktree 隔离、按分支合并 | 都是"人分派任务给 agent"，没有 agent 之间的协作 |
| **A2A 协议**（Linux Foundation，v1.0） | 企业级跨服务的 agent 互通：Agent Card、任务生命周期 | 概念参考 | 只借概念：能力卡片、任务状态 | 对本地 CLI 来说太重，基本没有本地 CLI 实现它 |

### 2.2 Clowder 和 Cat Café 的教训（逐条对应到 xmuse 2）

| # | 教训（出处） | xmuse 2 的落地方式 |
|---|---|---|
| C1 | SDK 只支持 API Key，用不了订阅；CLI 内置 OAuth、能力完整（第 1 课） | 一律通过各家 CLI 接入，额度来自订阅 |
| C2 | 动态挂载 MCP 最干净；不支持的那几家，只好在提示词里教 agent 用 curl 调 HTTP（第 5 课） | 三家现在都支持在项目级或全局配置 MCP。hub 在 agent 的工作目录里写入项目级配置，不污染全局；需要临时挂载时，各家怎么做在 M0 验证 |
| C3 | **CLI 输出是 agent 的"内心独白"，`post_message` 才是"嘴巴"**；agent 自己决定说什么、对谁说（第 5 课） | 消息只通过 `send` 工具产生，hub **从不解析 agent 的最终输出** |
| C4 | **两条触发路径导致无限乒乓**：一条是回传时检测 @，一条是结束时检测 @；会重复触发、没有深度上限、取消不了（第 4 课 P0 事故） | **只有一条触发路径**：显式调用 `send`。不做文本里的 @ 解析。每条因果链都有深度上限，每次运行都登记到可以取消的表里 |
| C5 | 抑制规则太多导致"该 @ 的时候不 @"，链条断裂；改用"出口检查"加正面触发点（第 4 课） | 技能里写出口检查："到我这里结束了吗？不是的话，下一个该谁动？"规则以正面触发为主 |
| C6 | 投递内核：一个持久化队列；准入是唯一的切换点；事件驱动地排空队列；每次运行只有一个终态；每个事实只有一个所有者（A2A 协议） | hub 的投递语义直接采用（§4.4） |
| C7 | Session Chain：上下文写满就封存会话、开一条新的，新会话用搜索工具查旧会话，"不要猜"（第 8 课） | 唤醒时注入启动包；agent 用 `thread`、`context` 工具检索历史，不靠全量灌入 |
| C8 | Why-First 交接五件套：What、Why、Tradeoff、Open Questions、Next Action（ADR-002） | 作为 `send(kind=handoff)` 的结构化字段，同时也是 MemoryOS 整理时的高价值输入 |
| C9 | 线程归属：任何有状态的对象都必须显式绑定线程，否则会跨线程串（第 8 课） | 所有记录都显式带 `thread_id` 和 `agent_id` |
| C10 | 三层知识：热层是索引，温层是聚合，冷层是原文；状态只在一处记录（第 10 课） | 和 MemoryOS 分层一致：决定和约定是温层，消息原文是冷层 |
| C11 | Mock 测试全过，但从来没有真正调用过 API（第 1 课） | 每个里程碑都必须用真实 CLI 跑一遍 |

---

## 3. 技术栈分析

### 3.1 协议和扩展点

| 技术 | 现状（2026-10） | 在 xmuse 2 中的用途 |
|---|---|---|
| **MCP 工具（stdio）** | 三家都支持。dsh 的 MCP 客户端只消费工具（不用 Resources 和 Prompts），服务器崩溃后不自动重连，工具名和 Claude 同形（`mcp__<server>__<tool>`） | **唯一的模型侧接口**：agent 通过工具发消息、读收件箱、查上下文 |
| MCP 2026-07-28 规范 | 核心改为无状态，去掉了 initialize 握手；Tasks 移到扩展；**Sampling、Roots、Logging、HTTP+SSE 传输都被标为弃用** | 不依赖服务器主动发起的请求，也不依赖 sampling。工具要能幂等重试 |
| Claude `claude/channel` 扩展 | research preview；推送事件、回复工具、权限转发。M0 实测：只在交互会话里生效（`-p` 忽略开发标志）；每次启动都要确认一次；会话正忙时消息排队到回合结束；推送到调工具约 1.4 秒 | Claude 交互会话的唤醒通道 |
| **Agent Skills（SKILL.md）** | 开放标准，三家都能读取，安装路径不同 | 协作规范写成技能 `xmuse-collab`：交接格式、出口检查、何时私聊、何时群聊。一份内容，三处安装 |
| 钩子 | Claude：SessionStart、UserPromptSubmit、Stop、PreCompact 等；OpenCode：服务事件流已够用，插件事件作为备选；dsh：经 `dsh-hooks-claude-code` 桥接，SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop，钩子脚本必须放在工作区内 | agent 正在干活时，在回合边界插入"你有 N 条新消息"；用 Stop 或 idle 事件让 hub 知道这个 agent 空了 |
| OpenCode 服务 API | v2.0.21 实测：路径都带 `/api/` 前缀。`POST /api/session/{id}/prompt`（`delivery: steer\|queue`，准入后即返回，`prompt_async` 在 v2 里不存在）；`GET /api/event` 是 SSE，回合结束看 `session.execution.succeeded\|failed\|interrupted`（没观察到 `session.idle`）；`permission.asked` 加 `POST …/permission/{id}/reply` 可远程审批 | OpenCode 的唤醒、完成检测和审批转发 |
| ACP | OpenCode 支持（`opencode acp`），xmuse 已有 ACP transport | 备选，不作为主路径 |
| A2A | v1.0，面向企业服务 | 不采用 |

### 3.2 三家 agent 的能力和唤醒方式（M0、M0-dsh、M1 实测）

实测版本：Claude Code 2.1.295、OpenCode 2.0.21、dsh 0.2.0-rc.2（Windows 版）；agy 1.3.2 已弃用。完整能力表和证据见 `XMUSE2-M0-REPORT.zh.md` §2、`XMUSE2-M0-DSH-REPORT.zh.md` §2。

| | Claude Code | OpenCode 2.0.21 | dsh 0.2.0-rc.2 |
|---|---|---|---|
| 无界面送消息进已有会话 | ✅ `-p --resume <id> --output-format stream-json`，回合结束 = `result` 事件后进程退出 | ✅ `POST /api/session/{id}/prompt` + SSE，回合结束 = `session.execution.*` | ✅ `dsh --profile headless --json --session-id <id> --patch <覆盖文件>`，NDJSON，回合结束 = `turn_end{completed\|error}`；未知会话立即报错 |
| MCP 回发，只放行 xmuse 工具 | ✅ `--allowedTools mcp__xmuse__*`（未信任的工作区会忽略项目 `permissions.allow`，必须传参数，M1） | ✅ 项目 `opencode.json` 的 `permissions` 规则；改成 `ask` 可由 hub 远程审批；hub 启动时查服务模型目录，模型不在目录里就报错停下（不花 token） | ✅ 一次性 `--patch` 覆盖文件里只挂 xmuse；无界面下 MCP 工具直接执行，边界就是这份白名单 |
| 交互界面开着时另一路写同一会话 | ❌ **静默分叉**，不加锁也不报错 | ✅ **服务端串行化**（持久化收件箱），人的输入以 `steer` 插队，hub 用 `queue` 排队 | ✅ **明确拒绝**：后到者收到 `already owned by an active write handle`；进程被杀后租约自动释放 |
| 唤醒空闲的交互会话 | ⚠️ channels，约 1.4 秒；要开发标志，每次启动确认；桌面 Code 页收不到 | ✅ 往 TUI 正在用的会话发 `prompt`，1–4 秒 | ⚠️ 没有 TUI 和 CLI 推送；桌面网关的 WebSocket RPC 支持 `queue`/`steer`，要另写客户端（M1b 之后） |
| 每回合 token | ✅ | ✅ | ✅（缓存写恒为 0；崩溃后续接时重跑的回合不计入用量） |
| 原生界面旁观、介入、检测人工 | ⚠️ `--resume` 能打开和介入，但无界面推进时不刷新；`UserPromptSubmit` 钩子能区分人和 channel | ✅ TUI 连服务实时可见；hub 的消息带 `metadata`，人打的不带 | ⚠️ 没有 TUI，人只能在 dsh 桌面 App 里看；会话日志里人打的字带 `source.rpcId`，hub 送的不带；钩子（SessionStart、UserPromptSubmit、Stop）可用 |
| 运行环境 | WSL | WSL | **只有 Windows 版**，工作区必须是 `C:\` 下的原生路径（`\\wsl.localhost` 下写文件和钩子都会失败）；每次启动约 3 秒固定开销（带 `ELECTRON_RUN_AS_NODE` 时实测；M0 的 10 秒是未带时的值） |
| 模型家族 | Anthropic（M1 用 Opus 5.5） | 由 provider 决定（M1 用免费的 muse-spark；M1b 起用 `opencode-go/muse-spark-1.3-contributor`） | DeepSeek（M0 用 `deepseek-official/deepseek-v4-flash`） |
| 单次唤醒（处理 token） | 对话 4 万（M0）；xmuse 回合 6 万–7 万，编码中位数约 15.6 万（M1） | 对话 2 万（M0）；xmuse 回合 4 万–7.4 万，编码中位数约 14.4 万（M1） | 新建约 0.7 万，对话约 1.4 万，小改文件 3.2 万–4 万（M0-dsh）；xmuse 下对话约 6.5 万、编码 12 万–44 万（M1b） |

**唤醒适配器**：

| | 人在场（你正在用它的原生界面） | 自主（你不在场） |
|---|---|---|
| Claude | channel：垫片声明 `claude/channel`，hub 经垫片推送；完成信号用 Stop 钩子 | `claude -p --resume <id> --output-format stream-json --model <显式> --allowedTools …`，干净环境启动；**前提是租约证明没有 TUI 持有该会话**，否则改走 channel 或排队 |
| OpenCode | 同右，一条路 | `POST /api/session/{id}/prompt`，`delivery:"queue"`、`metadata:{xmuse:…}`；完成信号是 SSE `session.execution.*` |
| dsh | 暂无推送：人在桌面 App 里看会话日志；网关客户端以后再做 | 上面那条 headless 命令，`env -i` 加 `DSH_TELEMETRY_DISABLED=1`（必须经 `WSLENV` 透传）再加 `ELECTRON_RUN_AS_NODE=1`（否则桌面 App 开着时 exe 把参数交给已运行的 App、0 退出无输出；M0-dsh 的遥测关闭实际未生效），cwd 是该会话建立时的原生路径（续接要求 cwd 字符串完全一致）。被拒绝时退避重试（首次 ≥10 秒） |

**会话租约**（实测结论，四种行为都见到了）：
- Claude 静默分叉：`SessionStart`（`source=startup/resume`）钩子上报"TUI 持有会话 X，pid=…"，`SessionEnd` 释放，hub 无界面运行时自己持有租约。兜底是分叉检测：**同一父节点下出现两条用户输入才算分叉**，并行工具调用产生的多个子节点不算（M1 修正）。
- OpenCode 串行化：不需要锁。"人在场时不打扰"看 SSE 里不带 `metadata.xmuse` 的输入。
- dsh 明确拒绝：hub 维护一张薄的忙闲表，以 dsh 的拒绝为准；连续被拒 N 次转人工。
- agy 静默覆盖：已弃用。

**OpenCode 的 code mode**（M1 发现）：模型可能用 `execute` 工具包一层 JS 再调 MCP 工具；如果只定义函数不调用，xmuse 调用一次都不会执行。技能里写明"用顶层 await"；hub 对"正常结束但没发出任何 xmuse 消息"的回合发 notice。

**为什么是这三家**：
- OpenCode 的推送和串行化最干净；
- Claude 有官方推送通道，钩子最完整；
- 第三个模型家族原选 agy，但它在无界面模式下 MCP 只能全局放行、并发会静默覆盖；用户 10-09 改选 dsh。dsh 的 A–H 契约除了推送和旁观都满足，不用改 dsh 源码，单次唤醒最便宜；代价是只有 Windows 版、工作区必须是原生路径、没有 TUI。

**三家共用工作区**（用户 10-09 决定，方案 A）：M1b 和 M2 的工作区放在 `C:\` 下，WSL 里的 Claude 和 OpenCode 通过 `/mnt/c/...` 访问，dsh 用原生路径。M3 改为每个 agent 一个 git worktree：dsh 的放在 `C:\`，另两家的放在 WSL 里，靠 git 合并。

---

## 4. 架构设计

### 4.1 设计原则

1. **插件，不是平台**：agent 的会话、工具、权限都属于它自己的 CLI；xmuse 只负责协作。
2. **每个事实只有一个所有者**：消息和投递状态归 `hub.db`；会话内容归各家 CLI；代码归 git；整理出的记忆归 hub（来自 MemoryOS 的计算结果）。
3. **只有一条触发路径**：唯一的触发源是 `send` 工具调用。不解析输出，不做隐式 @。
4. **事件驱动，每个收件人同一时刻只有一个回合**：投递、准入、终态都在持久化事务里提交。
5. **点名唤醒，群聊不全员唤醒**：群消息对每个成员都可见，但只叫醒被点名的人和这个话题的负责人；其他成员在下次醒来时，以摘要的形式看到。
6. **确定性信息优先，记忆其次**：hub 确定知道的东西（谁负责什么、门禁命令、未读的点名消息）直接给出；MemoryOS 只补充需要整理的部分。
7. **能重算的才放派生库**：消息原文、整理出的决定、审批记录都归 `hub.db`；MemoryOS 只是无状态的计算服务。这对应审计报告里的方案 B。
8. **防失控上限没有例外**：每条因果链有深度上限；每个 agent 有回合数和 token 的安全上限（防无限乒乓，不是开发预算）；随时可以全部取消。
9. **不接管各家的上下文**（用户 10-10 决定，取代 M1 的"超过 12 万自动轮换"）：现在各家模型的上下文窗口基本都在 100 万左右，hub 频繁开新会话交接会削弱长任务、大任务的能力。
   - hub **永不自动 compact 或新开**任何会话。上下文何时 compact、何时新开，由各家 CLI 自己的机制和用户决定；用户主要在和哪家交互，就由用户控制那家的会话。
   - xmuse 和 MemoryOS 负责的是**信息对齐**：按任务角色，给每个 agent 维护精简有效的通用信息和特定信息，并随任务进度同步更新（§4.5）。
   - 需要同一 agent 新开会话时（用户决定、厂商强制，或会话失效时由 hub 兜底，比如未知会话、分叉），**直接用这份维护信息交接**，不从旧历史里截取。
   - 代价：会话越长，单次唤醒越贵（M0：同一会话加两篇长文后，单次唤醒从 4.5 万涨到 8.9 万）。这一点接受，只由 §4.4 的安全上限兜底，M2 实测。
10. **真正的敌人是 context rot，不是长度**：被推翻的信息在后面又复活。对策是决定落库并带版本，旧版本标作废；给 agent 的永远只有现行有效的条目。

### 4.2 组件

```text
 ┌──────────── Claude Code ────────────┐ ┌──────── OpenCode ────────┐ ┌────────── dsh ──────────┐
 │ 原生会话 / 工具 / 权限               │ │ 原生会话（后台服务）      │ │ 原生会话                 │
 │ xmuse 插件：MCP 工具 + channel       │ │ xmuse 插件：MCP 工具      │ │ xmuse 插件：MCP 工具     │
 │           技能 xmuse-collab + 钩子   │ │   技能 + 权限规则         │ │ 一次性 --patch 覆盖文件  │
 └──────────────┬──────────────────────┘ └────────────┬─────────────┘ └────────────┬────────────┘
                │ channel / -p --resume                   │ /api/.../prompt + SSE      │ headless --session-id
                ▼                                         ▼                            ▼
 ┌──────────────────────────────── xmuse-hub（本地回环，单进程）──────────────────────────────┐
 │ Registry   agent、家族、能力卡片、会话 ID、在线状态                                          │
 │ Mail       私聊和群聊话题，消息持久化在 hub.db（幂等键、因果关系、Why-First 字段）           │
 │ Delivery   每个收件人一个队列；准入事务；会话租约；深度上限；预算；取消                      │
 │ Wake       各家适配器：Claude channel、Claude resume、OpenCode API、dsh headless             │
 │ Context    唤醒时组装启动包：身份、新增点名消息、话题摘要、相关决定；调用 MemoryOS          │
 │ Work（P2） git worktree 和分支；门禁；请另一家族复核；人工批准后合并                        │
 └───────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                         │ /curate（推送端）  /recall（拉取端）   无状态
                                         ▼
                            MemoryOS：把话题窗口提炼成决定、约定、分工、
                            未决问题和教训；检索用 BM25 + FastEmbed + RRF
```

**插件形态**：每家都用同一个很薄的 MCP stdio 垫片。它通过回环 HTTP 连到 hub，只做转发。
- 工具 schema 只在 Python 里定义，`xmuse init` 把它写成 `tools.json` 给垫片读（M1 实现：垫片 99 行）。
- 在 Claude 下，垫片在 `127.0.0.1:0` 上监听，向 hub 注册端口、一次性 nonce、会话 ID 和 Claude 的 pid；hub 用带 nonce 的 POST 推送。只有交互 CLI（`CLAUDE_CODE_ENTRYPOINT=cli`）才声明 `claude/channel`，无界面进程不声明。
- dsh 的"插件"是 hub 每次运行生成的一次性 `--patch` 覆盖文件：显式模型、只挂 xmuse 的 MCP、用 `disabled` 行关掉不需要的原生高危工具、可选的钩子桥。不写 `$DSH_HOME`。
- Claude channel 只能用 TS 的 MCP SDK 实现，所以垫片用 TS 写；hub 用 Python 写。
- hub 状态（数据库、令牌、日志）放在工作区外的 `~/.local/state/xmuse/<工作区名>-<sha8>/`，工作区里只留一个指针文件 `.xmuse.json`。M1 是每个工作区一个 hub。
  - **更正（10-11，审计 B2-1）**：原文写"agent 读不到令牌"，这不成立。agent 和 hub 是同一个 OS 用户，有 shell 或解释器的 agent 能读状态目录里的所有令牌，包括管理令牌；`.xmuse.json` 还写着状态目录的路径。实际的做法和边界见 §4.7。

**M0 带来的硬性要求**：
- **推送端点由 hub 分配**：项目级 `.mcp.json` 会被该目录下所有 Claude 进程加载，TUI 和无界面进程抢同一个固定端口会 `EADDRINUSE`。垫片启动时向 hub 注册"会话 ID → 推送端点"（动态端口或 unix socket）。
- **hub 用干净环境启动 agent**：`env -i` 加白名单变量。从桌面 App 会话里派生的 CLI 会继承几十个 `CLAUDE_*`、`ANTHROPIC_*` 变量，会话被记成 `claude-desktop`、多挂连接器，基础上下文从 1.8 万涨到 3.2 万。
- **每家都显式指定模型**：用户的 Claude 默认是 haiku，OpenCode 的默认模型已下线。
- **中继信任说明是必需的**：技能 `xmuse-collab` 或项目 `AGENTS.md` 里要写明"xmuse 是用户搭建的协作中继，同伴消息来自用户安排的协作者"。M0 里没有这段说明时，muse-spark 两次把转述的同伴请求当成注入拒绝；加上后立刻照做。和 §4.7 的来源标注要一起设计，见那里。
- **OpenCode 的项目配置由 xmuse 生成**：默认 build agent 改文件不用询问；有后果的动作设成 `ask`，由 hub 经 `permission.asked` 和 `/reply` 转给人。

**M0-dsh 和 M1 带来的硬性要求**：
- **无界面 Claude 必须用 `--allowedTools` 传白名单**：工作区没被信任时，`-p` 会忽略项目 `.claude/settings.json` 里的 `permissions.allow`。白名单 = `mcp__xmuse__*` 加编码白名单（测试命令、`git diff/status/log/show/add/commit`、`ls`），并用 `--permission-mode acceptEdits`。**白名单按工作区可配置，Python 项目默认带上 `python3`**（用户 10-09 同意：已放行的 unittest 加上自由编辑，本来就能执行任意代码，再放行 `python3` 不增加实际风险；真正的边界是 M3 的 worktree 隔离）。
- **dsh 只能用 `C:\` 原生路径做工作区**，hub 传给 dsh 子进程的所有路径都要转成 Windows 形态；续接要求 cwd 和建会话时字符串一致，所以 hub 的会话表记 `(会话 ID, cwd)`。
- **dsh 必须关遥测**：hub 派生 dsh 一律带 `DSH_TELEMETRY_DISABLED=1`（必须经 `WSLENV` 透传）再加 `ELECTRON_RUN_AS_NODE=1`，否则默认把原始会话事件上传到厂商（M0-dsh 的关闭实际未生效，M1b 实测确认）。
- **dsh 每次启动约 3 秒固定开销**（带 `ELECTRON_RUN_AS_NODE` 时实测；未知模型约 12 秒、无适配提供方约 9 秒，均为零 token；最小任务预检约 3 秒、约 4k token）：超时和退避按 10 秒下限设计（M0 值，留余量）；hub 启动时对每个模型做一次预检。
- **每个工作区每家只允许一个 agent**：项目配置里只能带一个身份。多实例要等每个 agent 有自己的 worktree（M3）。

### 4.3 给模型用的工具（控制在 8 个以内）

| 工具 | 作用 |
|---|---|
| `xmuse_whoami` | 我是谁、属于哪个项目，我的角色和负责范围，在线的同伴有哪些（同伴的能力卡片） |
| `xmuse_send(to, body, thread?, kind?, why?, mentions?)` | 发私聊（`to=agent`）或在群聊话题里发言（例如 `to=#task`，用 `mentions` 点名；回复发在消息来源的那个话题里）。`kind` 取值 message、handoff、review_request、decision、assumption、question（assumption 为 M2 新增，见 §4.5.1）；`kind=handoff` 时必须填 Why-First 五件套。**文档和技能里不要写 `#group` 这类占位符**，模型会照抄成真话题名（M1） |
| `xmuse_inbox(unread_only=true)` | 我的未读消息，点名的排在前面 |
| `xmuse_ack(ids, outcome?)` | 确认已处理；可以带上结论，比如复核结果 |
| `xmuse_thread(id, query?)` | 读取话题，或在话题里检索（相当于 Session Chain 的 `session_search`） |
| `xmuse_context(topic?)` | 从协作信息层取当前有效的决定、约定、分工和未决问题，返回结构化结果。M1 是确定性实现（按话题列出最近的决定、交接、未答问题和负责人），M2 改为读 MemoryOS 的提炼结果 |
| `xmuse_done(summary, next)` | 声明"这一轮到我这里结束了"，`next` 是出口检查的结论（下一个该谁动）。M2 起出口检查加一项：本回合有没有别人会依赖的决定或假设，有就申报（§4.5.1） |
| （P2）`xmuse_work(action)` | 申请 worktree、跑门禁、请求复核、申请合并 |

参照 mcp_agent_mail 的经验，工具要少而粗，小模型也能用对。Claude 默认延迟加载 MCP 工具（先经 ToolSearch），每个会话第一次调 xmuse 工具多一轮往返、约多 1 万 token，所以工具描述要短；关掉延迟加载在单次唤醒上实测更贵，多回合的总账留到 M2 再测。

**对话回合的固定开销**（M1）：一次 xmuse 回合至少 2–4 次模型调用（加载技能、Claude 的 ToolSearch、`xmuse_send`、`xmuse_done`），每次都重读基础上下文，所以对话唤醒是单次对话的 1.5–3 倍。M2 可试：启动包里直接带技能要点；`xmuse_send` 加 `done=true` 合并出口检查。

### 4.4 投递语义（借鉴 Clowder A2A 和 xmuse kernel）

1. **持久化**：`send` 写入 `messages`，并为每个收件人写一条 `deliveries`（queued → admitted → done、failed 或 canceled），同一个事务、带幂等键。
2. **准入**：一个收件人当前没有在运行的回合，且会话租约空闲时，hub 把它所有排队的点名消息**合并成一个回合**，通过对应的唤醒适配器送达。准入是唯一的切换点。
   - 租约各家不同（§3.2）：Claude 靠 `SessionStart`/`SessionEnd` 钩子上报 TUI 占用，hub 无界面运行时自己持有，分叉检测只数"同一父节点下的两条用户输入"；OpenCode 由服务端串行化，不需要锁；dsh 以它的 `already owned` 拒绝为准，同一回合内在适配器里退避重试（10 秒起翻倍，默认 4 次），用完转人工（暂停 agent、通知人）。
   - **人工介入是准入条件之一**：检测到人在操作（Claude 的 `UserPromptSubmit` 里不是 `<channel` 开头的输入；OpenCode 里不带 `metadata.xmuse` 的输入；dsh 的 `SessionStart`/`UserPromptSubmit`/`Stop` live 钩子（M1c；hub 自有 prompt 忽略，日志级 `source.rpcId` 读取留作桌面桥未挂载时的兜底）时，暂停往这个会话做无界面投递，只走人在场的通道或排队。
3. **完成**：回合结束时 hub 关闭这个回合，然后立刻检查队列。完成信号按家选：Claude 无界面是 `result` 事件后进程退出，Claude 交互是 Stop 钩子；OpenCode 是 SSE `session.execution.succeeded|failed|interrupted`；dsh 是 `turn_end{completed|error}` 加进程退出。只用事件驱动，外加一个低频的兜底扫描（M1 默认 15 秒）。
   - **回合正常结束但没发出任何 xmuse 消息时，hub 在话题里发 notice**，否则人不会知道链断了（M1：OpenCode code mode 里定义了函数却没调用）。
4. **上限**：每条因果链（从一条人类消息出发）的唤醒次数有上限，超出时暂停这条链并通知人。这些上限只防失控（无限乒乓），不防长任务。M1 的默认值：

   | 参数 | 默认值 |
   |---|---|
   | 链唤醒上限 / 链 token 上限 | 12 次 / 2,000 万 |
   | 每个 agent 每小时回合 / token 上限 | 40 个 / 3,000 万 |
   | 回合超时 | 30 分钟 |
   | 启动包带话题最近 N 条 | 8 |

   - M1 的"会话轮换阈值 12 万"按原则 9 取消，代码在 M2 删除。会话变长后单次唤醒会变贵，token 类上限可能需要上调，由 M2 的长会话实验给出数值。

   - **厂商限额拒绝不算失败**：消息重新排队，链的唤醒次数退回，agent 暂停到厂商给的重置时刻，并通知人；到时由兜底扫描自动继续（M1 真机遇到 Claude 5 小时额度用尽）。
   - **崩溃恢复**：dsh 提交前被杀的回合，续接时会被重跑，其中的工具调用会再执行一次，而且这部分 token 不出现在用量里。所以 xmuse 工具必须幂等：`send` 的自动去重按血缘 collapse（同回合重试、或被杀回合在无人接手时的后续回合重放；succeeded 后的重复是新消息，M1c），崩溃后首次续接的成本按未知处理。
5. **取消**：`xmuse stop [--agent|--thread]` 取消所有排队的投递，并中断正在运行的回合。
6. **群聊**：消息写给所有成员，但只唤醒被点名的人和话题负责人。其他人在下次醒来时，从启动包的摘要里看到它。

### 4.5 MemoryOS 协作信息层（"比无脑群聊好"的核心）

- **输入**：话题窗口（消息原文加 Why-First 字段），复用 `/curate` 的提炼图：抽取 → 校验逐字引文 → 修复 → 按 topic_key 和版本汇总。
- **输出**（存在 `hub.db`，归宿主所有）：
  - 决定和约定，比如接口、命名、规则；
  - 分工，谁负责什么；
  - 未决问题，以及该由谁回答；
  - 教训。
- **使用方式**：
  - 唤醒时，启动包里只放**和这个 agent 相关**的条目，加上新增的点名消息，不灌入全部群聊；
  - agent 需要更多信息时，再用 `xmuse_context` 或 `xmuse_thread` 去查。
- **通用信息和特定信息怎么分**（10-10 对齐，已定）：
  - **大块内容不出会话**：工具输出、中间推理永远留在 agent 自己的会话里。跨边界的只有 agent 主动发出的 `send`/`done`，每条自带 `kind`、`mentions`、`thread`。分类看**出处**（信封），不读内容。
  - **信封和信纸**：`kind`、`mentions`、`thread` 是信封，机器读；正文原样透传，大白话随便写。只有 `kind=handoff` 要求 Why-First 五件套。
  - **两道门**：MCP schema 是结构门，非法就拒收；内容约定靠复核方检查和 `/curate` 的校验，技能只做事前约定、不拦截。
  - **@ 去中心化**：任何 agent 都可以点名任何一方，不需要主策批准；但唤醒由 hub 审批（租约排队、安全上限、按血缘去重）。送达（hub 持久化、唤醒、ack）和沉淀（MemoryOS 召回、提炼）是两步。
- **信息变更的同步**：B 改了影响 C 的约定时，落一条新版 decision，旧版标作废，再给 C 定向推送差量；C 在下一个回合带着差量包生效。C 正在跑的回合默认不打断，加急叫停权只归主策。派发要支持 `depends_on` 依赖边（M2 补）。
- **交接包**：同一 agent 新开会话时（原则 9），由 hub 从维护信息拼交接包：身份和角色、该 agent 相关的现行决定和约定、分工、未决问题、未读点名消息。不从旧历史截取。先在 hub 侧拼，跑顺后再考虑收进 MemoryOS 的查询接口。
- **MemoryOS 的边界**（10-10 重审，已定）：
  - 三条红线：不碰协作状态（在线、该唤醒谁）；热路径零 LLM；不自动仲裁矛盾。
  - 判断规则：需要协作状态的归 hub；只和内容打交道的 MemoryOS 可以做；走热路径的必须零 LLM。
  - M2 要加的接口：`/recall` 加可选的 `thread_id`、`role` 提示（确定性加权）；`/curate` 支持按话题作用域提炼。
- **对照实验**（作品的核心证据）：同一个任务、同样三家 agent，比较三组：
  - A：全员群聊，每条消息都唤醒所有人；
  - B：点名唤醒，但不提供协作信息层；
  - C：点名唤醒，加上协作信息层的启动包。

  指标：任务是否完成、轮次、token 消耗、需要人介入的次数、约定是否被遵守。
- **复核检出率**（M1 后新增）：M1 里 OpenCode 当复核方 4 次全部批准，因为 Claude 的实现本身没有 bug，所以看不出它会不会漏掉问题。M2 加"预埋 bug"的任务：在实现里放入已知 bug，直接统计各家当复核方时的检出率。

#### 4.5.1 对齐信息的规模控制（10-10，吸收业界做法，调研见 `XMUSE2-ALIGN-RESEARCH-2026-10-10.zh.md`）

**目标**：会话本身的长度归各家和用户管（原则 9）；xmuse 保证两件事：自己往会话里加的内容累计几乎不增长，每个 agent 在任何时刻拿到的对齐视图只随**未完成的工作**增长，不随历史增长。会话长到 50–60 万时，xmuse 注入的累计量应当只是零头。

**膨胀来源**：①每次唤醒重发完整快照（最大风险：重复，而且旧快照留在历史里和新快照互相矛盾，本身就制造 rot）；②对齐库只增不减；③消息正文过长被原样转发。

**1. 来源以申报为主，提炼为辅**（Cognition、Magentic-One）
- 多 agent 冲突的根源是动作里暗含的决定没共享出去。agent 用 `send(kind=decision|assumption|question)` 主动申报；`xmuse_done` 的出口检查加一项"本回合有没有别人会依赖的决定或假设"。hub 把申报确定性地写进对齐库，不需要 LLM。
- 新增 `kind=assumption`：明确标成假设，后续由负责人确认（转为 decision）或推翻。
- `/curate` 是补充：从自由文本里找漏报的条目，只能**提议**，由话题负责人或人确认后才生效。

**2. 条目存储：双时间、永不删除、显式作废**（Zep/Graphiti、Mem0、Collaborative Memory）
- 每条记录：类型（decision、convention、assignment、assumption、question、lesson）、作用域（通用、角色、话题、agent）、一句话陈述（保留限定语）、引用（来源消息 ID）、来源（谁、何时）、`valid_at`（何时决定）、`recorded_at`（hub 何时得知）、`invalid_at`、`supersedes`、状态（active、superseded、resolved、archived）。
- 不删除。当前视图 = `invalid_at 为空` 且状态为 active。
- **作废只能由显式动作触发**：新决定写明 `supersedes`，或负责人把问题标为已解决。不做 LLM 自动仲裁（Mem0 的 LLM 冲突仲裁会误删仍然需要的条目）；`/curate` 只能标"疑似冲突"。

**3. `/curate` 只输出逐条差量**（ACE）
- 输出形如"新增 / 取代 X / 解决 Y"的逐条编辑，永不整体重写摘要，以免"上下文坍缩"。
- 条目要短，但不能为了短而丢掉限定语（ACE 说的"简短偏差"，也是 Mem0 误判冲突的根源）。
- 某一层超出上限时才离线合并去重（MemoryOS 的 FastEmbed 用来找重复），合并结果仍然是逐条编辑，需要确认。

**4. 每个 agent 的视图：确定性的读取策略，分层带上限**（Letta 记忆块、Collaborative Memory、beads）
- 视图 = 通用核心 + 本角色层 + 它是成员或被点名的话题层 + 指派给它的条目。hub 知道角色和成员关系，热路径零 LLM；只有视图超出预算时，才用 `/recall`（带 `thread_id`、`role` 提示）排序截断。
- 分层上限（初值，M2 验证）：

  | 层 | 内容 | 上限 |
  |---|---|---|
  | 通用核心 | 项目级约定、分工、教训 | 约 40 条、2k token；超了由 `/curate` 离线合并 |
  | 角色层 | 本角色相关的约定 | 约 20 条、1k |
  | 话题层 | 所在或被点名话题里的现行决定、假设、未决问题 | 每个话题约 15 条 |
  | 指派给我的 | 分工、该我回答的问题、`depends_on` 是否已解除 | 不设上限，随完成清空 |

- **任务关闭即衰减**（beads）：话题或任务关闭后，它的特定条目归档，不再进入任何视图；只有显式提升（`/curate` 提议、负责人或人确认）的约定和教训才进通用层。
- **已就绪工作**视图（beads 的 `bd ready`）：按 `depends_on` 算出依赖已解除的指派。

**5. 注入：会话开头给快照，之后只追加差量**（Manus、Google ADK、Anthropic）
- hub 为每个 `(agent, 会话)` 记水位：这个会话已经见过对齐库的哪个版本。
- 每次唤醒只注入水位之后的变化：新增条目和**作废通知**（例如"作废：D-7 v1『接口用 int』，现为 v2『接口用 Decimal 字符串』"）。作废通知用来压住上下文里仍然存在的旧版本，这是长会话里防 rot 的关键。我们不拥有各家 CLI 的上下文，不能像 Letta 那样原地改写，只能追加。
- 完整快照只在三种情况下发：**新会话、检测到厂商 compact、交接**。这三种情况会清零水位。
- 启动包和差量包由**确定性的编译管线**组装（ADK 的做法：处理器有名字、顺序固定、可单测）。格式保持稳定（顶部不放时间戳、键序固定），以命中前缀缓存。别家的发言加来源标注（"[来自 X]"），避免被当成自己的输出。
- 大块内容走引用：条目只带一句话和引用，细节由 agent 用 `xmuse_thread(ref)` 按需取；`send` 正文设长度上限（初值 4k 字符），更大的产物写进仓库文件，消息里只引用路径。

**6. 接入各家的 compact**（不由 hub 触发，只响应）
依据：M2 的探测报告 `XMUSE2-M2-COMPACT-PROBE.zh.md`；实现见 H4b。

- **Claude**：用 `SessionStart` 钩子的 `compact` 匹配器，自动和手动 compact 都会触发。
  - 钩子运行 `xmuse hook compact`：当场打印快照，并把水位写成当前版本。快照即时重新注入，下次唤醒只发差量。
  - 现行文档写明，钩子的 stdout 会进入上下文，所以之前担心的"文档说法矛盾"已不存在，但还没有真机验证。
  - `PreCompact` 只能阻止压缩，不能注入；`PostCompact` 和 stream-json 的 `compact_boundary` 作为备用信号。
- **OpenCode（2.x）**：SSE 事件 `session.compaction.ended` → 清零水位，`session.compaction.failed` 不清零，这一条已实测。
  - 设计稿原先写的 `session.compacted` 和 `experimental.session.compacting` 是 v1 接口，2.0.26 里已不存在，不再使用。
  - 往厂商的压缩摘要里注入对齐信息：2.x 的 `ctx.session.hook("compaction")` 可以做到，但样本小，插件接口也不稳定，所以作为**可选项，不依赖它**，M2 不做。
- **dsh**：没有确定性信号。
  - headless `--json` 会丢掉压缩事件（`json-stream.ts:313`）；`SessionStart(source=compact)` 虽然写在类型定义里，但不会触发。
  - 目前靠下面的通用兜底判断。已向 dsh 提需求，请它在 `--json` 里输出 `compaction/end`（`DSH-FR-COMPACTION-EVENT.zh.md`）。这是 dsh 从推断转为确定信号的唯一途径。
- **三家通用兜底**：回合结束时，如果上下文降到上次的 `compact_drop_ratio`（默认 0.5）以下，就判定为发生了压缩，清零水位。拿不准时宁可多发一次快照，漏发的代价更高。

**7. 注入预算**（初值，M2 验证）

| 场景 | 预算 |
|---|---|
| 每次唤醒的差量 | ≤ 2k token；超出时只发摘要加"用 `xmuse_context` 查全量" |
| 快照（新会话、compact 后、交接） | ≤ 8k–15k token |
| 单条 `send` 正文 | 4k 字符 |

**8. 成本：提供条件，不控制**
- hub 记录每个会话的上下文规模和单次唤醒成本；超过某个规模时，在话题里提示一句，例如"dsh-1 会话 48 万，单次唤醒约 X，交接包已就绪"，由人决定。
- token 花得多和效果好强相关（Anthropic：BrowseComp 上 token 用量解释了 80% 的性能差异），目标是不浪费，不是越少越好。

**M2 的验证指标**：
1. 注入占比：xmuse 注入的 token 占每次唤醒总处理 token 的比例，目标 ≤ 5%。
2. 视图曲线：随任务推进，每个 agent 的现行视图先涨后平，不随历史线性增长。
3. rot 测试：中途推翻一条决定，检查各 agent 之后是否全部按新版本行事；长会话组和新会话组都测。
4. 申报率：复核时发现的暗含决定里，有多少是事先申报过的。

#### 4.5.2 与"代码即记忆"的边界（10-10，用户同意）

有一种观点认为，coding agent 不需要记忆：代码本身就是最完整的证据，再维护一套记忆是二次冗余。这个判断对单 agent 成立，对 subagent 也成立，因为派发方已经替它带好了上下文。xmuse 2 和这个观点不冲突，原因有三条：

1. **对齐信息出现在代码之前，或者用来纠正代码。** 实现方交接时宣布一条约定，这时复核方和下游还看不到那段代码；中途推翻一条决定时，旧代码就是错的（rot）。hub 的条目是代码的前导和纠偏，不是给代码写的摘要。
2. **只记代码里没有的东西**：为什么这样做、哪些做法被推翻了（版本链）、谁和谁之间的约定和分工。复述代码现状的内容不该入库。curate 只产出提议，由复核方把关；如果 T1 的噪音数据显示这类提议明显，就在 collab 提示词里加一条禁止。
3. **只有一份事实。** hub 是唯一的事实源。MemoryOS 是无状态的计算函数，自己不存任何东西：`/recall` 只在视图某一层超过上限时给条目排序，`/similar` 只提示近似重复，`/curate` 只产出待确认的提议。不开 MemoryOS，对齐照样能跑；方案 1 的 C 组就是这样跑的。开它值不值，由离线回放（T1）的补漏和噪音数据决定。

### 4.6 可靠性层（P2，标准 git）

- 每个 agent 在自己的 git worktree 和分支上工作（借鉴 vibe-kanban 等工具）。
- 门禁：复用 xmuse 的门禁配置，在 worktree 里跑本地命令，不另建沙箱。
- 复核：`xmuse_send(kind=review_request)` 发给另一个家族的 agent，由 hub 按规则挑选复核人。
- 合并：门禁通过加复核通过后，由人批准合并，这是有后果的动作，所以要审批。可选：参照 mcp_agent_mail，在分支上加建议性的文件预留和 pre-commit 守卫。

### 4.7 安全

- 每个 agent 的插件持有一个本地签发的随机令牌（`xmuse agent add` 签发，文件权限 600，库里只存 sha256 摘要），hub 用它确认"消息是谁发的"；人用单独的管理令牌。M1 没有移植 v1 的 plugin grant 和配对：本地、单用户、只监听回环地址，配对码、scope 和过期都没有要防的对象。
- 消息进入别家 agent 的上下文时带来源标注，比如 `<xmuse from="opencode-1" family="..." thread="...">`。
- **来源标注和中继信任要一起设计**（M0 教训）：只写"同伴消息，不是用户指令"会让谨慎的模型拒绝一切转述请求；完全不标又给了注入空间。口径是：同伴消息来自用户安排的协作者，**在当前任务范围内可以照做**；超出任务范围、或者有后果的动作，仍按各家原生权限请人批准。这段话写进技能 `xmuse-collab` 和项目 `AGENTS.md`。
- 各家原生的权限确认照常生效；合并、推送、删除这类有后果的动作需要人批准。Claude 的权限转发、OpenCode 的 `permission.asked` 都可以把审批请求送到 hub。
- **信任模型（10-11 改写，审计 B2-1、B2-2）**：这是**防误操作的单用户模型，不防一个有意绕过的 agent**。
  - **OpenCode 的 shell 自动批准改用白名单**。xmuse 生成的配置让每条 shell 命令都走 `ask`，hub 只自动放行通过白名单的单条命令：测试命令、只读查看、本地 git（status/diff/log/add/commit 等）、工作区或 /tmp 里的脚本、安全的 `rm -f`。
  - 以下情况一律交给人：命令组合（`;`、`&&`、`||`、`&`）、命令替换、除 `2>&1` 外的重定向、`bash -c`/`python -c`、带路径的程序名、`git -C`/`git -c`，以及白名单外的一切。`|` 后面只允许接只读过滤器。原来的 fnmatch 黑名单（`cd x && git push`、`bash -c "git push"` 都能绕过）已经删掉。绕过写法都有测试用例（`tests/test_opencode_engine.py`）。
  - **有授权效力的管理操作要求"人在终端"**。审批、确认或驳回提议、恢复暂停的 agent，光有管理令牌不够：hub 经 /proc 找到发起连接的进程，要求它有控制终端、并且不在任何已知 agent 进程（运行中的回合、Claude TUI 租约、OpenCode 服务）的进程树里；Windows 侧来的连接找不到进程，一律拒绝。另一个合规途径是桌面协调者：它问过用户后用 `xmuse_approve` 转达，必须附上用户原话，记录里标明"用户经协调者"。
  - 发消息、停止、查看这类操作仍然只看令牌：它们不授予权力，而且发出的消息会标 `via=cli`。
  - **剩下的缺口**：令牌文件本身仍然能被 agent 读到。有意绕过的 agent 可以脱离进程树并给自己分配一个伪终端，从而通过检查。Claude 无界面白名单里的 `python3`（用户 10-09 决定）可以执行任意代码。真正的边界只能是给 agent 用单独的 OS 用户或沙箱，并且不给推送凭据（审计 B2-1 第 2、3 点），这需要用户决定。
- Claude channel 按发送者门控：只接受带 hub 下发 nonce 的推送。
- dsh 无界面模式下 MCP 工具直接执行、没人可以审批，所以安全边界是覆盖文件：只挂 xmuse 的 MCP，原生高危工具用 `disabled` 行做减法（实际清单：`tool-web`、`tool-subagent*`、`tool-workflow`、`tool-plugin-manager`、`tool-jobs`；文件读写和 PowerShell 保留——它们跑在 dsh 的 workspace-write 沙箱里，需要审批的动作在无界面下直接失败）。中继信任说明对 dsh 同样必需。

---

## 5. xmuse 和 MemoryOS 资产的复用

| 资产 | 处理 | 理由 |
|---|---|---|
| `chat.db` 里身份、幂等、因果的写法 | **参照着重写**（hub.db，约 10 张表） | 原来的 kernel 绑定了旧协议里的租约、观察和批次，整块引入代价太大 |
| `room_mcp_contract` 工具 schema 和入口校验 | 参照 | 入口校验加上类型检查（审计报告 §5.3 的教训） |
| plugin grant 和配对（`room_plugin_grants`、`xmuse-workroom pair`） | **未移植**（M1 决定） | 本地单用户场景下，随机令牌加摘要就够了，见 §4.7 |
| 5 个插件的宿主接入骨架 | **复用骨架**，重写功能 | 宿主接入方式都已经探明；只读状态面板改成给模型用的工具 |
| `room_agy_transport`（agy 的 stream-json 和会话恢复） | **降级为备选**（M0 后） | 第三家改为 dsh；只在重新启用 agy 时才用 |
| `room_acp_transport`、Codex 相关 | 搁置 | M0 证明 OpenCode v2 服务 API 比 ACP 合适（持久化收件箱、事件、权限应答都有）；Codex 不在这次的三家里 |
| **M0 的验证脚本**（`~/dev/xmuse2/spikes/`） | **M1 的首选起点** | 已在真机上跑通，见 §5.1 S 类 |
| `room_module_memory`（窗口、游标、memory.md 渲染）、`memoryos_http_client` 的 `/curate` 部分 | **复用** | 协作信息层直接在它上面扩展 |
| MemoryOS `/curate` 图、召回（v3 + v2） | **复用**；第一阶段精简后改成无状态 `/recall` | 方案 B |
| 门禁配置（`room_execution_profiles`） | 复用（P2） | 门禁命令 |
| 看板、owner 克隆、集成引擎、执行子系统、Room kernel 的投递协议、房间召回的 outbox | **搁置**（留在旧版本，不迁移） | 由标准 git 和新的投递语义取代 |
| Web 前端 | 搁置 | 插件形态不需要统一界面；以后可以做一个只读总览 |

### 5.1 复用清单（10-09 实测行数和耦合程度）

计划新写的约 1 万行（产品加测试）里，约 3,000–4,500 行可以从现有资产移植或改写。M0 后 agy 驱动降为备选，M0 的验证脚本补上了更直接的唤醒原型。

**M1 的实际情况**：M1 几乎全部从 S 类（M0 验证脚本）演化而来，A 类的 grant 和配对没有移植，B 类的守护进程和 TS 片段也没用上，产品只有约 2,250 行。v1 资产真正的复用点集中在 M2（`room_module_memory`、`scripts/eval/`、MemoryOS）和 M3（门禁、git 辅助函数）。dsh 的 S 类原型在 `spikes/dsh/`，对齐文档是 `XMUSE2-M1-DSH-ALIGN.zh.md`。

| 类别 | 资产（现有行数） | 可移植的量 | 用在哪 |
|---|---|---|---|
| **S M0 验证脚本，直接演化** | `spikes/oc-turn.py`、`oc-events.py`（OpenCode v2 一回合加 SSE）；`claude-run.sh`（Claude 无界面续接）；`probe-mcp/server.ts`（MCP 工具加 channel，即垫片雏形）；`cc-tree.py`（分叉检测）；`cleanenv.sh`（干净环境）；`hooks/claude-hook.py`（钩子输入格式）；`ledger.py`（各家 usage 解析） | 视为 M1 唤醒适配器、垫片和用量记账的原型 | M1（已用） |
| S | `spikes/dsh/`：`dsh-run.sh`（覆盖文件生成、路径转换、干净环境加关遥测）、NDJSON 解析、拒绝退避、会话日志读取 | dsh 适配器约 150–250 行 | M1b |
| ~~A~~ 未用 | `chat/room_plugin_grants.py`（764）+ `xmuse/workroom_pair.py`（322） | 0（M1 改用简化令牌） | — |
| A | `chat/room_module_memory.py`（790）+ `xmuse/room_module_memory_worker.py`（95）+ `xmuse/memoryos_http_client.py` 里的 curate 和 health 部分（约 150） | 500–700 | M2 话题窗口、游标、版本链、渲染 |
| A | `scripts/eval/`（3,978：run_eval、metrics、judge、report、tasks） | 800–1,500 | M2 对照实验框架 |
| A | `chat/room_execution_profiles.py`（557） | 250–400 | M3 门禁命令 |
| A→B | `tests/xmuse/fixtures/fake_agy.py`（444） | 只借结构（M0 后降级）：M1 的假 agent 改为按 M0 录下的 Claude stream-json 和 OpenCode SSE 事件重放 | M1 测试 |
| A | `xmuse/room_mcp_server.py` 里的 `_validate_tool_call` 和 `_schema_violation`，以及 `room_mcp_contract.py` 的 schema 写法 | 约 150 | M1 hub 入口校验（补上类型检查） |
| A | `chat/room_owner_clones.py` 里的 git 辅助函数 | 100–200 | M3 worktree |
| 备选（M0 后） | `chat/room_agy_transport.py`（1,122，依赖 12 个 xmuse_core 模块） | 150–250：`resolve_agy_model`、`agy_turn_error_code`、会话 ID 捕获、stream-json 事件解析。M0 核对：事件外形一致，但 `result.usage` 是会话累计值、新增 `denied_actions` | 只在重新启用 agy 时 |
| B | `xmuse/workroom*.py`、`runtime/processes.py`（约 2,400） | 200–300：守护进程启停、就绪检测、setsid | M1 hub 命令行 |
| B | `integrations/claude-code`、`integrations/opencode` 手写的 TS（约 7,600，含测试） | 300–500：只允许回环地址的客户端、退避重试、文本清洗、配对流程、插件打包 | M1 垫片和插件 |
| B | `agents/god_session_*`（约 1,500） | 只借概念 | 会话 ID 持久化 |
| C 作为服务复用 | MemoryOS `/curate` 提炼图和召回（核心约 3,800） | 不用写 | M2，已经计入估算 |

**复用规则**：
1. **移植，不依赖**：把代码复制进 xmuse2 仓库再裁剪，**不要 import `xmuse_core`**。
2. **移植时顺手去掉防御性代码**：按审计报告 §5.3 的标准，删掉信任边界内部的类型检查和吞异常写法。
3. **不移植旧测试**：可以带走测试基础设施（比如假 agent），测试用例按新行为重写。
4. **只通过 HTTP 依赖 MemoryOS**。

**已知的坑**，写进代码或技能里，不要再踩一遍：
- 各家都必须显式指定模型；hub 用干净环境启动 agent（M0）。
- 用 tmux `send-keys` 往 TUI 打字前要等界面就绪，否则输入被吞（M0）。
- （agy 备选）它在 `$HOME` 下找到的 python 会被屏蔽；`uv run` 会改 PATH。
- 工具报错要写出字段名和允许的值（#470）。
- 主机确定知道的信息直接告诉 agent，不要指望它从记忆里学到（#482）。
- 只召回原文不会改变 agent 的行为，整理过的笔记本才会（M3）。
- 守护进程用 setsid 启动；PowerShell 传参会被拆坏，要写成脚本文件。
- Clowder 的事故教训：只留一条触发路径、必须能取消、链条要有深度上限、技能里要写出口检查。

---

## 6. 不做什么

- 不做统一的聊天界面，也不把 agent 嵌进 xmuse 自己的界面。
- 不自建沙箱：用各家原生的权限加 git worktree。
- 不做"全员自由群聊、每条消息都唤醒所有人"，只把它作为实验的对照组 A。
- 不实现 A2A 协议，不依赖 MCP sampling 或服务器主动发起的请求。A2A 管的是远程服务之间的任务委托：三家 CLI 都不是 A2A 服务，它既不解决本地会话的唤醒，也不覆盖多方对话。Clowder 的"A2A"同样只是内部协作链路的泛称，它的外部 agent 全部通过 CLI 适配器接入，真正的 A2A 协议适配器只停留在设计阶段（见 Clowder F050）。以后需要跨机器协作时，在 hub 的边上加一个 A2A 端点即可。
- 不用 ACP 作为主路径。ACP 要求 xmuse 作为 client 拥有并驱动 agent 的会话，正好是 v1 的平台模式；而且各家的支持程度不一。M0 实测：OpenCode 的 v2 服务 API 比它的 ACP 更合适（持久化收件箱、事件流、权限应答都有），ACP 维持备选。
- 文档里的"A2A"一律表示泛称，即 agent 之间的消息，不指 A2A 协议。
- 不做跨机器、多用户。

---

## 7. 里程碑（按代码量和 token 估算，不按人日）

**计量口径**：
- "处理 token"指每次模型调用的完整输入（大部分是缓存读取）加上输出。
- **单次调用的成本约等于当时的上下文大小**。按原则 9，hub 不靠轮换控成本；降本靠两处：一是对话回合的固定开销（§4.3），二是新会话交接时用维护信息，不灌旧历史。
- **不设开发预算，也不估开发消耗**（用户 10-09 指示）。下表只估运行消耗（实验 agent 的唤醒），用于设计实验规模和作品证据。开发会话的实际用量照常记录（M1 约 3,830 万处理 token，绝大部分是缓存读）。

| 里程碑 | 内容 | 产品代码 | 测试 | 运行消耗（agent 合计） | 完成标准 |
|---|---|---|---|---|---|
| **M0 唤醒验证**（已完成） | Claude、OpenCode、agy 各验证 7 项 | 一次性脚本 `8b35d49` | — | **实测约 207 万**（55 次运行） | 能力表、适配器、租约方案 |
| **M0-dsh**（已完成） | dsh 按 A–H 契约验证 | 一次性脚本 `6662c34`、`bcd4ce2`；dsh 源码零改动 | — | 见 dsh 报告 §5 | `XMUSE2-M0-DSH-REPORT.zh.md` |
| **M1 消息层 MVP**（已完成，本地 `main` `1523440`） | hub、TS 垫片、技能和配置生成；Claude 和 OpenCode 两家 | **实际约 2,250 行**（Python 2,033 + TS 99 + 技能 85 + 脚本约 35） | **实际 1,652 行**，86 个测试 | **实际约 500 万**。编码唤醒中位数约 15 万（10 万–27 万），一个任务 33 万–85 万 | ✅ S1–S3 各 2 次，6/6 自主完成，人介入 0 次；失控保护、人在场、轮换、审批转发都验证过 |
| **M1b dsh 接入**（已完成，合并到 `main` `aff3840`） | dsh 自主模式适配器；三家共用 `C:\` 工作区（方案 A）；`python3` 放行；三家轮流当实现方跑 B1–B4 | **实际 +305/−20 行** | **实际 +318/−6 行**，97 个测试 | **实际约 710 万** | ✅ 三家都当过实现方和复核方，9 次运行全部自主完成，人介入 0 次；租约冲突、崩溃续接、`C:\` 回归都验证过 |
| **M1c M1b 收尾**（已完成，由 dsh 开发，合并到 `main` `2400136`，已推 r7 bare 仓库） | dsh 钩子实时人工检测（`Stop` 不来时超过 `turn_timeout` 自动过期）、日志级兜底；对话唤醒超 5 万记 warning；`send` 跨回合按血缘去重 | **实际 +178/−14 行** | **实际 +169/−10 行**，105 个测试 | **0**（只用假 agent） | ✅ 单测全过；真机三项（桌面钩子、告警频率、真 kill 去重）待 Claude 额度恢复后补测 |
| **M2 协作信息层 + 对照实验** | 启动包和交接包组装、话题整理、`xmuse_context` 读提炼结果；对齐信息的规模控制（§4.5.1：申报入库、双时间条目和显式作废、分层视图、水位和差量注入、接入各家 compact、任务关闭即衰减）；派发 `depends_on`；MemoryOS 改成无状态 `/recall`（加 `thread_id`、`role` 提示），`/curate` 按话题作用域；删除 M1 的自动轮换；实验框架；预埋 bug 任务；长会话 context rot 实验（目标：rot 不发生，同时记录会话变长后的单次唤醒成本）；降低对话回合固定开销 | 600–900 行 + MemoryOS 200–300 行 + 实验框架 500–800 行 | 600–1,000 行 | **2,000 万–5,000 万**（A/B/C 三组 × 每组至少 5 次，任务比 M1 难；加预埋 bug 和长会话两组） | A/B/C 三组的轮次、token、完成率、约定遵守率；各家复核检出率 |
| **M3 git 可靠性层** | 每个 agent 一个 worktree（dsh 的在 `C:\`）、门禁、复核路由、批准后合并、Claude 审批转发，可选文件预留 | 800–1,100 行 | 500–800 行 | **1,000 万–3,000 万**（真实交付 2–4 次） | 一次真实交付走完全程 |
| **合计** | | **约 4,500–6,000 行**（v1 约 10 万行） | 约 3,000–4,500 行 | **约 0.4 亿–1 亿** | |

**规模上限，作为设计约束**：产品代码不超过 7,000 行。超出时先停下来查，是不是又在过度设计。

**做法**：
1. **每个里程碑开一个新会话**，只读设计稿和相关代码。这样缓存命中率高、上下文清爽，开发质量也更好。
2. **实验按需要的样本量来跑**：M1 的单价比估计低一个量级，M2 每组至少 5 次，结果不稳定就加跑。
3. **用 xmuse 2 开发自己**：M2 和 M3 的一部分代码由三家 agent 通过 xmuse 2 协作完成。目的是拿到真实的协作证据。
4. 产品里的"每个 agent 回合数和 token 上限"保留，但它是**防失控的安全机制**（防止无限乒乓），不是开发预算。

**记录**：每个里程碑结束记一次实际值：产品行数、测试行数、运行消耗（每次唤醒的 token，按家、按"对话或编码"分开）。

**作品证据**：M2 的对照实验，加上 M1 和 M3 的真实运行记录。M1 里已有的一条：S2 两次运行中，Claude 当复核方都抓到了 OpenCode 实现里的同一个真 bug（`Decimal` 默认 28 位精度导致大整数往返失败）。演进叙事是：v1 是平台式运行时，真实运行暴露了它的问题，v2 改成插件式协作层。

---

## 8. 风险和未决问题

| 风险 | 影响 | 应对 |
|---|---|---|
| Claude channels 还是 research preview，要开发标志，每次启动都要确认；`-p` 模式无效 | 人在场模式的体验 | 自主模式不依赖它，走 `-p --resume`；channels 只用于人在场时。产品默认由用户自己启动带 channel 的 TUI（`xmuse attach` 给出命令） |
| **已证实**：Claude 的 TUI 开着时无界面写同一会话会静默分叉 | 自主模式的正确性 | 会话租约加分叉检测；M1 人在场测试 0 分叉 |
| **已证实**：桌面 App 的 Code 页能用 xmuse 的 MCP 工具和钩子，但收不到 channel 推送 | Code 页里的会话不能被 hub 唤醒 | 主控放在终端（tmux 里带 channel 的 Claude TUI）；Code 页只做发起者 |
| **dsh 只有 Windows 版**，工作区必须是 `C:\` 原生路径 | hub 在 WSL 里，每次派生 dsh 都要跨系统；三家共用工作区受限 | M1b、M2 用方案 A：工作区放 `C:\`，另两家经 `/mnt/c` 访问（较慢，小任务够用）；M3 改为每个 agent 一个 worktree |
| dsh 没有本地推送通道和 TUI | 人在场时，dsh 的会话只能在它的桌面 App 里看 | 先只做自主模式；网关 WebSocket 客户端等需要时再做 |
| dsh 默认把原始会话事件上传到厂商 | 隐私 | hub 派生 dsh 一律带 `DSH_TELEMETRY_DISABLED=1` |
| dsh 崩溃恢复时会重跑被杀的回合，这部分 token 不可见 | 工具重复执行；用量少记 | xmuse 工具保持幂等；崩溃后首次续接的成本按未知处理 |
| 环境变量污染、默认模型不可靠、channel 固定端口冲突、tmux 输入过早被吞 | 各类真机故障 | 已在 M1 里解决：干净环境、显式模型、动态端点、等界面就绪 |
| 模型拒绝转述的同伴请求；OpenCode code mode 里工具没真正执行；占位符被照抄成话题名 | 协作链静默断掉 | 中继信任说明（§4.7）；技能写明顶层 await；"回合没发消息"时 hub 发 notice；文档不写占位符 |
| 厂商额度用尽 | 自主推进中断 | 消息重新排队，agent 暂停到重置时刻（M1 已实现） |
| M1 的 OpenCode 用的是免费模型 | M1 和之后的数据不能直接对比 | 用户 10-09 决定从 M1b 起改用 `opencode-go/muse-spark-1.3-contributor`；对比时注明模型 |
| M1 的任务偏简单，6 次里 4 次第一版就基本正确 | 看不出复核的价值 | M2 用更难的任务，并加预埋 bug 的任务 |
| 会话越长，每次唤醒越贵 | 运行消耗变大，可能先碰到 token 安全上限 | 按原则 9 接受这个代价，不自动轮换；M2 长会话实验实测成本，必要时上调安全上限 |
| 各家无界面模式到窗口上限时是否自动 compact：OpenCode 实测会；dsh 读源码确认会（阈值是窗口的 80%）；Claude 文档暗示会，未实测 | 不会的话，长会话的回合会直接失败 | 回合失败时，由 hub 用维护信息新开会话兜底（被动兜底，不是主动轮换）；Claude 待真机确认 |
| compact 信号现状：OpenCode 用 `session.compaction.ended`，已实测；Claude 用 `SessionStart(compact)`，只有文档依据；dsh 没有确定性信号 | dsh 的水位清零只能靠推断，可能误判或漏判 | 三家都有"上下文骤降"兜底，拿不准时多发快照；已向 dsh 提需求输出 `compaction/end`；Claude 钩子待真机验证 |
| 被推翻的信息在长会话里复活（context rot） | agent 按过时的约定干活 | 决定带版本、旧版标作废、只给现行有效条目、差量推送（§4.5）；M2 长会话实验检验 |
| 跨 agent 的提示词注入 | 安全 | 来源标注、各家原生权限、有后果的动作要审批；dsh 靠覆盖文件的工具白名单 |

需要用户决定：暂无。

已决定（10-10）：hub 不接管各家上下文，取消 12 万自动轮换，新会话由用户（或厂商）决定，交接用 xmuse 和 MemoryOS 维护的信息（原则 9）。

已决定（10-09）：OpenCode 从 M1b 起用 `opencode-go/muse-spark-1.3-contributor`；Claude 人在场模式由用户自己启动 TUI；Claude 无界面白名单按工作区可配置，Python 项目默认放行 `python3`；三家共用工作区用方案 A（放 `C:\`）；M1 合并到本地 `main`。

---

## 修订记录

- 10-10（和 dsh 讨论"代码即记忆"后，用户同意）：新增 §4.5.2"与'代码即记忆'的边界"。修订前备份 `.XMUSE2-ARCH-2026-10.pre-codemem1010.bak`。
- 10-09 晚（M0 后）：§0、§3、§4.1–§4.4、§4.7、§5、§7、§8 按 M0 报告修订；第三家由 agy 改为 dsh。
- 10-10（业界调研后，用户同意）：新增 §4.5.1"对齐信息的规模控制"；§4.3 `kind` 加 assumption、`xmuse_done` 出口检查加申报；§7 M2 行；§8 加 compact 信号一行。调研笔记 `XMUSE2-ALIGN-RESEARCH-2026-10-10.zh.md`。
- 10-10（M2a 完成后，用户同意）：按 M2 探测报告改写 §4.5.1 第 6 条和 §8 的两行 compact 风险。
  - OpenCode 改用 2.x 的 `session.compaction.ended`，删除 v1 接口名；
  - Claude 的钩子改为当场重新注入快照；
  - dsh 改为靠推断，并已提需求；
  - 新增三家通用兜底。
  - 修改前的备份为 `.XMUSE2-ARCH-2026-10.pre-compact1010.bak`。
- 10-10（对齐文档 `XMUSE2-ALIGN-2026-10-10.zh.md` 和用户决定后）：§4.1 原则 9 改为"不接管各家的上下文"，新增原则 10（context rot）；§4.4 删除轮换阈值；§4.5 新增信息分类、变更同步、交接包、MemoryOS 边界；§7 计量口径和 M2 行；§8 风险表三行。修订前备份 `.XMUSE2-ARCH-2026-10.pre-align1010.bak`。
- 10-10（M1b 后，M1c 交）：§3.2 dsh 开销/唤醒实测、OpenCode 预检；§4.2 遥测透传与启动开销；§4.4 准入人工检测、适配器内退避、崩溃跨回合去重；§4.7 dsh 减法清单；§7 M1b 实际值。
- 10-09 晚（M0-dsh 和 M1 后）：§0 判断 2；§3.1 MCP 和钩子两行；§3.2 整节重写（dsh 列、四种租约行为、code mode、共用工作区方案 A）；§4.2 插件形态和新增硬性要求；§4.3 工具签名和固定开销；§4.4 准入、完成、上限、限额、崩溃恢复；§4.5 复核检出率；§4.7 令牌、nonce、dsh 边界；§5、§5.1 复用的实际情况；§7 里程碑表（M1 实际值、新增 M1b、下调 M2 和 M3）；§8 风险表。

---

## 参考来源

- Clowder AI：https://github.com/zts212653/clowder-ai （README、`docs/architecture/a2a-protocol.zh-CN.md`、`docs/decisions/002-collaboration-protocol.md`）
- Cat Café 教程：https://github.com/zts212653/cat-cafe-tutorials （第 1、4、5、8、10 课）
- Grok Bot 官方文档：https://docs.x.ai/grok-bot/bots 、https://docs.x.ai/grok-bot/overview 、https://docs.x.ai/grok-bot/faq
- Grok Bot Galaxy 现场笔记：https://gist.github.com/CodeSolutionsLLC/b252776f6c8c6e48cdb559df14a58112
- ChatGPT Dots：https://www.layer3labs.io/guides/chatgpt-dots-explained
- MCP Agent Mail：https://github.com/Dicklesworthstone/mcp_agent_mail
- beads：https://pkg.go.dev/github.com/steveyegge/beads@v0.12.0
- Claude Code channels：https://code.claude.com/docs/en/channels-reference.md
- Claude Code agent teams（第三方整理）：https://pasqualepillitteri.it/en/news/249/claude-code-agent-teams-guide-ai-multi-agent
- OpenCode 服务和事件流（第三方）：https://github.com/anomalyco/opencode/issues/11616 、https://docs.rs/crate/opencode-codes/1.18.5/source/README.md
- OpenCode 插件：https://opencode.ai/docs/plugins/
- Antigravity 钩子：https://antigravity.google/docs/hooks ；远程控制：https://antigravity.google/docs/remote-control.md ；MCP：https://antigravity.google/docs/cli/mcp
- MCP 2026-07-28 规范：https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ 、https://blog.mcpservers.org/posts/mcp-spec-2026-07-28
- Agent Skills：https://mcp.directory/blog/cross-agent-skills-cursor-codex-cline-antigravity-gemini-mastra-portability
- A2A：https://linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- worktree 编排工具：https://nevercodealone.de/glossare/ki-tools-2026/git-worktrees-ohne-claude-code-agnostische-ki-agenten-2026
