# xmuse 2 接入说明：给想接入的 coding agent

本文写给要为 xmuse 做适配的 agent 或开发者，例如 Antigravity（agy）。读完应当知道三件事：xmuse 是什么、hub 期望一个"助手"做到什么、要交付哪些东西。文中提到的路径都相对于 xmuse 仓库根目录。

版本：2026-10-12，对应分支 dev/topo2。设计稿：`docs/design/XMUSE2-T8.zh.md`（最新方向）、`docs/design/XMUSE2-ARCH-2026-10.zh.md`（架构原则）。

---

## 1. 愿景

xmuse 让一个人在本机统一、顺手地使用多家 coding agent，并且让它们协作得好。

- **主控**：Claude Code 桌面 App 里的会话。它保留全部原生能力，xmuse 不改造它，只在它旁边加一个面板（Claude mod）。
- **助手**：其他 agent（现在是 OpenCode、dsh，你要接入的也属于这一类）。它们被封装成"助手"，由 xmuse 的 hub 在后台驱动：hub 负责叫醒它们干活、管理它们的会话、传递消息、截获需要审批的命令。用户在面板里和它们对话、审批、查看进度。
- **协作拓扑不预设**：助手负责什么、怎么分工，由用户怎么用决定。xmuse 只提供消息、派活、审批和信息同步这些机制。
- **聚合而非改造**：要什么能力，就接入本来就有这个能力的 agent，而不是去改造某个 agent。所以适配要尽量用各家已有的接口：无头模式、会话恢复、事件流、MCP、权限钩子。不要求对方改代码。

用户只需记住项目、Claude、助手三样。房间、成员 id、会话、令牌都在后台。

## 2. 整体结构

```
Claude 桌面 App（主控） ── Claude mod 面板 ──┐
                                             │ HTTP（本机回环地址）
                                       ┌─────▼─────┐
                                       │    hub    │  每个项目目录一个；状态存在 SQLite（hub.db）
                                       └─────┬─────┘
                  ┌──────────────────────────┼──────────────────────────┐
             OpenCode 驱动              dsh 驱动               你的驱动（新）
                  │                          │                          │
            OpenCode 会话              dsh 会话                 你的 agent 会话
                  └──────── 每个会话都挂上 xmuse MCP shim（xmuse_* 工具）────────┘
```

- **hub**：Python，在 `hub/src/xmuse/`。每个项目目录跑一个 hub，只监听本机回环地址。它持有消息、投递、会话、审批、信息层条目，是唯一的真相源。
- **驱动（Driver）**：每家 agent 一个，在 `hub/src/xmuse/adapters/<厂商>.py`。引擎从不按厂商写分支，厂商之间的差别全部收在驱动里。**你要写的主要就是这个。**
- **MCP shim**：`shim/server.ts`（Node 23.6 及以上直接运行）。它是一个 stdio MCP 服务器，把 `xmuse_*` 工具转发给 hub。助手就是靠这些工具发消息、交回结果的。
- **技能说明**：`skill/xmuse-collab/SKILL.md`。`xmuse init` 把它复制进工作区的 `.claude/skills`、`.opencode/skills`、`.agents/skills`，告诉助手怎么协作。

## 3. 一个助手的一次回合

1. 有消息要叫醒助手 A（被 @、私聊、用户广播、交回的结果……）。
2. 引擎问 A 的驱动：会话现在被谁占着（`presence`）？空着就走无头路径。
3. 引擎拼一个**唤醒包**（`wakepack.py`），作为这一回合的提示词，依次包括：
   - 转达说明：这些消息由 xmuse 转来，同伴是用户安排的协作者；
   - 身份：你是谁、职责是什么、同伴有谁；
   - 对齐信息：新会话给快照，老会话只给增量；
   - 新消息；
   - 一行"另有 N 条未读，不是发给你的"。
4. 驱动的 `headless.start(spec)` 把唤醒包送进 A 的会话。`spec.session` 是要接着用的厂商会话 id；为 None 时新开一个。
5. A 干活。期间它用 `xmuse_send` 发消息，执行命令时如果厂商的权限机制发出询问，驱动把询问交给 hub 的审批（`sink.approval`）。
6. A 用 `xmuse_done` 结束：写摘要、交给谁、结果标签、证据。
7. 回合结束时，驱动必须**恰好调用一次** `sink.turn_ended(TurnEnd)`，带上状态、厂商会话 id 和用量。

## 4. 驱动要实现的接口

完整定义见 `hub/src/xmuse/adapters/base.py`。以下是每一项的含义，A–H 是内部契约编号：

| 契约 | 接口 | 要做到什么 |
|---|---|---|
| A | `Adapter.start(spec) -> {"pid"?, "handle"?}` | 不阻塞地开始一回合：把 `spec.prompt` 送进 `spec.session`（为 None 就新开会话），工作目录用 `spec.cwd`，模型用 `spec.agent["model"]`。厂商的原始事件流写进 `spec.run_log`，证据核对要用它 |
| A | `Sink.turn_ended(TurnEnd)` | 每回合恰好一次。`status` 取 succeeded / failed / interrupted；`session` 是实际用的厂商会话 id（新开的就填新 id）。厂商说没额度了：填 `retry_at`。会话丢了：填 `requeue="fresh"`。会话被人占着：填 `requeue="hold"` |
| A | `Adapter.interrupt(turn_id)` | 中止正在跑的回合 |
| B | `Driver.write_config(ws, agent, state)` | 写项目级配置：挂上 xmuse MCP shim（环境变量 `XMUSE_STATE`、`XMUSE_AGENT`）；**只预先放行 `xmuse_*` 工具**，shell 命令一律设成"询问"，由 hub 来回答。参考 `adapters/opencode.py` 的 `write_config` |
| C | `Driver.presence(agent, session) -> Presence` | 说明会话现在归谁：`free`（hub 可以用）、`tui`（用户的交互窗口占着）、`hub`。同一会话同一时刻只能有一个写入方 |
| D | `Driver.push`（可选） | 用户的交互窗口开着时，把消息推进这个活会话；做不到就设为 None，消息会排队等候 |
| E | `TurnEnd.usage` | 按回合、不累计：未缓存输入、缓存读、缓存写、输出、`context`（这一回合最后一次模型调用的提示词大小，也就是下次叫醒要重读的量）、调用次数、模型名 |
| F | `Presence.human_turn` 和 `Driver.on_hook` | 分清"用户在打字"和"hub 在送消息"：用户的回合进行中，hub 不插队 |
| G | `Driver.on_hook`（可选） | 厂商的回合边界钩子或事件，比如会话开始、结束、回合结束 |
| H | 显式模型、干净环境 | 模型只用 `agent["model"]`，不继承用户全局默认；子进程环境用 `env.clean_env()`，不把用户的密钥类变量带进去 |
| — | `Driver.attach_command(agent, session)` | 返回一条命令，让用户在该厂商自己的界面里打开这个会话，用来偷看或接管 |
| — | 压缩事件 | 厂商自己压缩了会话时调用 `sink.compacted(厂商会话id)`，hub 会在下次叫醒时重发完整的对齐快照。做不到也没关系：hub 发现上下文骤降一半以上，也会当作发生过压缩 |

驱动在 `hub/src/xmuse/server.py` 里注册（`self.engine.drivers["<厂商>"] = ...`）。厂商名要加进 `room.VENDORS`，默认模型加进 `config.MODELS`，模型族加进 `config.FAMILIES`。

## 5. 助手侧要满足的条件

- **支持 MCP（stdio）**：能挂一个本地 stdio MCP 服务器，并在回合里调用它的工具。这是硬要求，消息只经工具进出，助手纯文字的回答不会送到任何人手里。
- **工具**（schema 在 `hub/src/xmuse/tools.py`，`xmuse init` 写到 `<state>/tools.json`）：
  - `xmuse_send`：发消息。to 填同伴 id、'human' 或 '#群'；带 mentions 的才叫醒对方；kind 可以是 message、handoff、review_request、decision、assumption、question；kind=handoff 时必须填 why 五件套：做什么、为什么、取舍、待定问题、下一步。
  - `xmuse_done`：结束回合，写摘要、下一个该谁、结果标签、证据。证据会和本回合的事件流核对。
  - `xmuse_inbox`、`xmuse_thread`、`xmuse_context`、`xmuse_whoami`、`xmuse_ack`、`xmuse_leave_thread`、`xmuse_share`。
- **能读技能说明**：工作区里的 `SKILL.md` 或 `AGENTS.md` 片段。读不了的厂商，驱动要在唤醒包外再补充说明。
- **无头运行**：没有界面也能跑一回合，并且能接着用同一个会话（会话恢复）。
- **权限询问可以截获**：执行 shell 之类的危险操作前，厂商要么能"询问"（由驱动转给 hub），要么有钩子能拦。hub 按 allowlist 自动回答安全的命令，其余交给用户在面板里批。**不能只有"全放行"和"全拒绝"两档。**

## 6. 会话规则（务必遵守）

- **hub 不主动新开会话，也不主动压缩**（架构原则 9）。会话就是助手的长期工作记忆，而且提示词缓存很贵。驱动每次都要接着用 `spec.session`。
- 只有三种情况会新开会话：第一次叫醒；厂商报告会话失效（填 `requeue="fresh"`）；用户主动要求。新会话由 hub 发交接包（身份、对齐快照、各群最近消息），驱动不要自己从旧历史里截取内容。
- 发现会话分叉（厂商返回的会话 id 和传进去的不一样），在 `TurnEnd.note` 里写 `fork_detected`。
- 计划中（T8 的 H3）：上下文超过 50 万时，hub 会在助手空闲时触发一次压缩，并附上由 hub 生成的压缩指令。请调查你的厂商能否由外部触发压缩、能否带自定义指令，在交付时说明。

## 7. 安全边界

- hub 只监听本机回环地址。令牌只存在插件或驱动进程里，不进模型上下文，不写进工作区。
- 不读、不打印任何凭据：厂商的登录文件、API key、`sidebar.key`。助手的 shell 命令一旦引用 `sidebar.key`，hub 会直接拒绝。
- 越权的操作（推送、合并、删除、工作区以外的改动）仍然要经过用户批准。转达说明里写明了这一点。

## 8. 适配前要先查清楚的事（调研清单）

关于你的 agent，逐项给出证据（命令和输出、文档链接或源码位置）：
1. 无头模式怎么跑一回合？怎么指定工作目录和模型？
2. 怎么接着用一个已有会话？会话 id 从哪里拿到？
3. 有没有机器可读的事件流（JSON 行、SSE……）？回合结束、出错、用量分别在哪个事件里？
4. 怎么挂一个项目级的 stdio MCP 服务器？怎么只预先放行指定的工具？
5. 权限机制是什么样的？shell 命令能不能设成"询问"，询问能不能被程序接管并回答？
6. 用量怎么报：是否区分缓存读和缓存写？能否拿到最后一次调用的提示词大小？
7. 能否中止一个正在跑的回合？
8. 有没有交互界面会占用同一个会话？怎么知道它开着？能否往里推消息？
9. 能否由外部触发压缩、带自定义指令？压缩完成有没有事件？
10. 额度用完时报什么错？能否拿到恢复时间？
11. 它读哪些说明文件（AGENTS.md、技能目录）？

## 9. 交付物和验收

1. `hub/src/xmuse/adapters/<厂商>.py`：实现第 4 节的驱动和适配器。
2. 一个假的厂商程序 `tests/fakes/fake_<厂商>.py`：模拟它的事件流，包括成功、失败、额度用完、会话丢失、权限询问。写法参考已有的 `fake_opencode.py` 和 `fake_dsh.py`。
3. 测试 `tests/test_<厂商>_engine.py`：用假程序跑通完整回合（叫醒、发消息、done、用量、审批、续用会话、requeue）。参考 `test_opencode_engine.py`。
4. `xmuse doctor` 里加一项检查：命令是否存在、版本是否合格。
5. 第 8 节调研清单的答案，写成一份说明文档。
6. 一次真机探针：在一个测试工作区里加一个该厂商的助手，用 @ 让它建一个文件并交回，贴出 hub 时间线和用量记录。

验收标准：全量测试通过（`pytest -q tests`）；真机探针成功；调研清单里每项都有证据，做不到的写明"不支持"，并说明退路。

## 10. 在哪里工作

- **代码**：从 r7 的裸仓库克隆一份独立副本，建自己的分支（`<厂商>` 换成你的厂商名，例如 agy）：
  ```bash
  git clone -b dev/topo2 ~/git/xmuse2.git /mnt/c/Users/user/xmuse-adapter-<厂商> && cd /mnt/c/Users/user/xmuse-adapter-<厂商> && git switch -c adapter/<厂商>
  ```
  放在 C 盘下（`/mnt/c/...`），Windows 和 WSL 两边都能读写。Windows 侧的 agent 只能可靠地写这种路径。
- **不要碰的目录**：`xmuse-dev`（开发房间的成员在里面改代码）、`~/dev/xmuse2-rc`（发布线）、`~/dev/xmuse2-run`（正在运行的房间 hub）。
- **真机探针**：另开一个空的测试工作区，例如 `C:\Users\user\dsh-work\<厂商>-trial`，在那里起测试 hub、加你的助手。不要接入任何已有的房间。
- **交付**：提交推到 r7 的 `adapter/<厂商>` 分支，由 xmuse 的主控审阅后合并。不要推到 dev/topo2、rc/portfolio、main。

## 11. 参考文件

| 文件 | 内容 |
|---|---|
| `hub/src/xmuse/adapters/base.py` | 接口定义（本文第 4 节的出处） |
| `hub/src/xmuse/adapters/opencode.py` | 走服务接口的适配：事件流、权限询问、压缩事件 |
| `hub/src/xmuse/adapters/dsh.py` | 走命令行的适配：Windows 进程、前台中继 |
| `hub/src/xmuse/adapters/claude.py` | Claude Code 无头适配 |
| `hub/src/xmuse/engine.py` | 叫醒、开回合、回合结束的处理 |
| `hub/src/xmuse/wakepack.py` | 唤醒包是怎么拼的 |
| `hub/src/xmuse/tools.py` | 工具 schema |
| `shim/server.ts` | MCP shim |
| `skill/xmuse-collab/SKILL.md` | 给助手看的协作规矩 |
| `docs/design/XMUSE2-T8.zh.md` | 产品方向：单一入口、消息总线、压缩 |
| `docs/design/XMUSE2-ARCH-2026-10.zh.md` | 架构原则，特别是原则 9（会话）、8（防失控上限） |
