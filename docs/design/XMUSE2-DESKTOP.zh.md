# xmuse 2 侧栏方案设计稿（草稿，等用户审阅）

2026-10-11，r7。第三版：并入 D0 实测结论（`docs/design/XMUSE2-D0-REPORT.zh.md`，探针在 `experiments/d0-probes/`）和用户在桌面版里做的 U1–U6 核对。不做独立 exe，也不做网页面板：xmuse 只以各家桌面端或 TUI 里的**侧栏**出现。

## 1. 已定（用户 10-11）

| 项 | 决定 |
|---|---|
| 定位 | 本地多个独立 agent 的信息对齐中间层，替代用户在各平台之间复制粘贴、手动对齐。产品优先，不做评测框架 |
| 形态 | 只做侧栏（方案 A）；"一个窗口管所有 agent"的统一控制台（方案 B，基于 ACP）只作为远期可选前端记一笔，不排进计划 |
| 主控 | 在哪一家的侧栏里开房间，那一家就是这个房间的主控（开房间、邀请、成员管理）；其他成员的侧栏同样能看全部信息、做审批 |
| 房间 | 一个房间 = 一个工作目录 |
| 消息来源 | 侧栏发出的消息记为"用户（经 <provider> 侧栏）" |
| hub 运行位置 | Windows 原生（网络前提见 §8.1） |
| agent 单独 OS 用户 | 暂时搁置（安全模型里如实写明缺口） |

## 2. 用户流程

1. 用户在任意一家（Claude 桌面版、OpenCode TUI、dsh 桌面版）打开 xmuse 侧栏，点"开房间"，选工作目录、起名。这一家的这个会话成为**主控**，它自己也是房间里的一个成员。
2. 主控侧栏里点"邀请"，选 provider 和角色，填一段职责描述（见 §5），得到一次性邀请码（10 分钟过期，只能用一次）和一条可复制的命令，如 `/xmuse join K7Q2-9F`。
3. 用户在**想要的那个会话**里执行这条命令（或在那家侧栏里点"加入"并粘贴邀请码），绑定完成，所有侧栏上这个成员变成"在线"。
4. 之后：用户在任一侧栏或会话里 @ 某个成员，hub 负责投递和唤醒；被 @ 的 agent 在自己的原生界面里看到消息并处理。每个侧栏都显示整个房间的时间线。
5. 审批出现在所有侧栏的审批队列里，用户在任意一个侧栏上批，批完其他侧栏同步消失。

## 3. 架构

```
各家侧栏（薄渲染层：只负责画和把按钮操作转成请求）
  Claude mod 侧栏 ── OpenCode TUI 插件侧栏 ── dsh 插件抽屉
          │ HTTP：/v1/view（视图模型，长轮询）、/v1/act（操作）、/v1/join
          ▼
hub（Windows 原生 Python 后台进程，每个房间一个；不依附于任何一个侧栏或会话）
```

- **hub 独立于侧栏**：主控会话关掉，房间照常运行；任何成员的侧栏都可以接着管理。"主控"只表示房间在哪开的、默认由谁当协调者，可以在侧栏里移交。
- **hub 怎么启动**：开房间时由主控的插件拉起；之后任何一家侧栏连不上 hub 时都可以再拉起（同一房间用锁文件保证只有一个 hub 进程）。不需要常驻窗口，也不需要开机自启。
- **三家共用一个视图模型**：hub 提供结构化的 `/v1/view`（成员、时间线、对齐条目、审批队列、预设运行状态），每家侧栏只用自己的界面元素把它画出来。规则和业务逻辑都在 hub。
- **命令行保留**：`xmuse` CLI 继续用于脚本和排错，和侧栏走同一套接口。

## 4. 各家侧栏（D0 已验证）

### 4.1 Claude（桌面版 Code 标签和 Code CLI）——mod

依据：Claude Code 2.1.295 的 mod 接口（插件函数钩子），接口是早期版本，会随版本变化，以类型声明文件为准。

| 能力 | 做法 | D0 结果 |
|---|---|---|
| 侧栏 | `$.ui.open({ id, title })`，`ui.render` 钩子画 `Pane` | ✅ 桌面版实测：停靠在对话旁边（`placement=dock`），宽度可拖动，带放大和关闭；下拉、输入框、按钮、Markdown 都能交互 |
| 元素限制 | 只有 Box、Text、Button、Input、Select、Markdown 等，没有表格和标签页 | 时间线用 Markdown 画；分区用折叠按钮代替标签页 |
| 输入框上方横幅 | `AbovePrompt`：未处理的 @、待审批数 | 终端版已验证；桌面版待核对（U2 未单独确认） |
| 访问 hub | `$.http.fetch("http://127.0.0.1:<端口>/...")` | ✅ 桌面版实测访问 Windows 侧 127.0.0.1 返回 200（41 ms）；没有流式，刷新用长轮询 |
| 定时 | `session.start` 里起 `$.clock.every` | ✅ |
| **推送唤醒** | `$.prompt.submit({ text })`，不用 `asUser`；模型读到固定框架 "The <插件名> plugin sent a message: …"，正文里写明原始发送者 | ✅ 桌面版实测：**从定时器里提交**能在会话空闲时起回合；**从斜杠命令的处理函数里提交不会起回合**。实现时一律由轮询循环提交 |
| 回合进行中的提示 | `$.session.append`（用户角色、`isMeta`），只用于"有新的 @"这类提示 | 未实测 |
| 命令 | `$.command.register({ name: 'xmuse' })`：`room new`、`invite`、`join <码>`、`status`、`leave` | ✅ 桌面版实测，带参数，不起模型回合 |
| 会话 id | `$.session.id()` | ✅ 与 transcript 文件名、hub 记录的 session_id 是同一个。`/clear` 会换 id，mod 要在 `session.start` 时向 hub 重新声明绑定 |
| 侧栏何时出现 | 用户触发（点按钮或命令）时一定打开；非用户触发的 `$.ui.open` 在窄终端里不摆 | 实现时由 `/xmuse` 命令或横幅上的按钮打开 |
| 安装 | 桌面版没有 `/plugin install` 斜杠命令：终端里 `claude plugin marketplace add` + `claude plugin install`（用户级，桌面版本地会话会加载），或 `CLAUDE_CODE_PLUGIN_DIRS` | 安装程序负责 |

### 4.2 OpenCode——TUI 插件，可以当主控

- **侧栏**：OpenCode 2.x 的 TUI 插件（`@opencode/plugin/tui`，在 `cli.json` 的 `plugins` 里配置）有 `sidebar.content` 槽、带参数的斜杠命令（不会被当成 prompt）、toast、对话框、定时器、HTTP。D0 在 WSL 的 opencode v2.0.26 上实测通过。**官网文档写的是旧版 v1 接口，不能照抄。**
- **投递**：用户自己的 TUI 用 `opencode --server <url> --session <id>` 连到 hub 启动的 `opencode serve`，hub 经 `/api/session/{id}/prompt` 投递的消息会出现在这个 TUI 里（D0 实测）。join 时插件把会话 id 和 serve 地址报给 hub。
- **范围**：侧栏只在 TUI 里；OpenCode 桌面版和网页版有没有扩展点未确认。

### 4.3 dsh——插件抽屉

- **绑定和投递**：现有插件包的中继（`/xmuse bind`）改成邀请码形式 `/xmuse join <码>`；长轮询和"按会话强制身份"已经有了。
- **侧栏**：插件包加前端部分。宿主侧用 `ctx.inject(['webServer'], ...)` 注册带前缀的路由，转发到 hub（D0 用假宿主实测通过）；路由必须加 `connection.requestRejection` 栅栏，因为 `dsh web` 可能绑定 `0.0.0.0`。前端是单个文件（`window.__ModuleLoader__.load`），不能 import、不能带资产，资产走宿主路由。令牌只在宿主进程里。
- **待核对**：抽屉在真实 dsh 里的加载、遮挡和"覆盖 / 挤出空间"两种模式（U9、U10）。
- hub 改为 Windows 原生后，dsh 不再需要 WSL 互操作。

## 5. 成员和协作功能

| 功能 | 说明 | 借鉴 |
|---|---|---|
| 成员职责描述 | 每个成员一段职责描述（负责的领域、擅长什么）；规划者和其他成员按描述委派、@ 对的人 | Grok Bot 的命名 Bot 加职责描述 |
| 私人和共享分开 | 每个 agent 的上下文和记忆归它自己；共享层是对齐条目（decision、assumption、question、convention、assignment）和交接 | Grok Bot、dots 的做法 |
| 规则化审批 | 每类动作设"允许 / 需批准 / 禁止"，在侧栏里配置；侧栏有活动视图（谁在做什么） | dots 的 Custom Rules 和 Activity View |
| 可回放的事件日志 | 消息、回合、工具调用、对齐条目按时间线回放 | Muse Code 的事件日志 |
| 编排预设 | 中心化调度（现有 plan-split-integrate）、辩论、去中心化认领、守门员（专门审批其他成员的对外动作） | Muse 的 Sentinel |
| 长期记忆 | 跨房间、跨会话的用户偏好和约定，在侧栏里查看、编辑、撤销 | 另起设计稿 |

## 6. 邀请和绑定协议

| 步骤 | 内容 |
|---|---|
| 开房间 | 侧栏调用 `/v1/rooms {dir, name, vendor, session_id}`（hub 不在时插件先拉起 hub）→ 创建房间，调用者成为第一个成员和主控 |
| 创建邀请 | `/v1/act invite {vendor, role, description, name?}` → `{code, expires_at}`；任何成员的侧栏都能发起（用户操作） |
| join | `/v1/join {code, vendor, session_id, client_info}` → hub 校验码、vendor 匹配、没过期没用过 → 创建成员，返回成员令牌 |
| 令牌存放 | 只给插件进程，**不进模型上下文**，不写进工作区 |
| 身份强制 | 绑定后这个成员的所有调用都要带 `x-xmuse-session`，和绑定的会话不一致就拒绝 |
| 换会话 | 同一成员可以用新邀请码 join 到别的会话，后一次生效；Claude `/clear` 换 id 时由 mod 自动重新声明（同一插件实例持有的令牌，不需要新邀请码） |
| 离开 | `leave` 或侧栏上"移出"：解绑，未投递的消息保留 |

## 7. 安全模型

| 风险 | 处理 |
|---|---|
| agent 自己批准自己的请求 | 侧栏按钮只有人点得到。侧栏的操作请求带**操作令牌**（只在插件进程里）；agent 的工具调用只能用**成员令牌**，hub 拒绝成员令牌做审批和管理 |
| 开了 computer use 的 agent 能操作整个桌面 | 高风险操作（批准白名单外的 shell 命令、`always` 类审批、移出成员、移交主控）由 **hub 自己弹出 Windows Hello**，需要人本身在场 |
| 同一 OS 用户能读插件存放的令牌 | 已知缺口（单独 OS 用户已搁置）。令牌改存 Windows 凭据管理器能挡住"顺手读文件"，挡不住有意的同用户进程；高风险操作有 Windows Hello 兜底 |
| 消息来源 | 侧栏消息记为"用户（经 <provider> 侧栏）"；Claude 唤醒不用 `asUser`，模型读到"xmuse 插件发来的消息"，正文写明原始发送者 |
| 网络 | hub 只监听本机回环地址（§8.1） |

## 8. hub 迁到 Windows 原生（D1）

### 8.1 网络前提（待用户决定，U12）

WSL 现在是默认的 NAT 网络：Windows 能访问 WSL 里的服务，**WSL 里的程序访问不到 Windows 的 127.0.0.1**（D0 实测 `ECONNREFUSED`）。用户的 Claude CLI 和 OpenCode 都装在 WSL 里，hub 搬到 Windows 后它们会连不上。三选一：

| 方案 | 说明 |
|---|---|
| **改成 mirrored 网络（推荐）** | `.wslconfig` 设 `networkingMode=mirrored`，Windows 和 WSL 共用回环地址。改全局配置，要 `wsl --shutdown`，等 base 的 T15 跑完再改 |
| hub 额外监听 WSL 虚拟网卡 | 要开防火墙规则，不再是"只监听本机" |
| agent 全部迁到 Windows | Windows 上没装 OpenCode；Windows 版 claude 命令行是否已登录待核对（U11） |

### 8.2 要改的地方

- 路径和状态目录：`%LOCALAPPDATA%\xmuse\<房间>-<hash>\`；去掉 `wsl.exe`、UNC 路径、`to_win` 一类的转换（生产代码里约 44 处）。
- 进程管理：`start_new_session`、`killpg`、`os.kill`、`signal` 等 POSIX 专属调用约 22 处，换成 Job Object、父进程链等 Windows 做法。审批改由侧栏加操作令牌承担后，"调用来自用户自己的终端"这条判断退役。
- `clean_env` 要保留 Windows 系统变量（如 `SYSTEMROOT`），否则 node 子进程会崩。
- 启动 WSL 里的 agent：Windows 上的 hub 经 `wsl.exe` 启动它们（Windows → WSL 方向没有沙箱问题）。
- 测试：D0 在 Windows 的 Python 3.14 上全量跑：69 失败、9 报错，另有 3 个文件（38 个用例）因 pty、fcntl 收集不到。主因是测试用的假程序靠 shebang 启动（Windows 不认），改成 `sys.executable` 启动；依赖 pty 的测试改写或只在 POSIX 跑。加 Windows CI。
- 分发：安装程序带 Python 3.12+ 运行时（本机现成的 3.14 在别的应用目录里，不可靠），装好 hub 并注册三家插件。
- **工作量估计**：5.5–7.5 个人日（不含安装程序）。
- T15 实验仍在 WSL 里的 hub 上跑，迁移在独立分支上做。

## 9. 分阶段计划和验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| D0 实测 | ✅ 完成（报告和 U1–U6 核对）；剩余 U7–U11 由用户在方便时核对 | — |
| D1 hub 原生化 | §8（先定 §8.1 网络方案） | Windows 上全量测试通过；三家在 Windows 原生 hub 下各完成一次端到端收发 |
| D2 协议和视图模型 | 房间、邀请、join（§6）；`/v1/view`、`/v1/act`；操作令牌和成员令牌分离；成员职责描述 | 用 CLI 和测试驱动走通开房间 → 邀请 → join → 收发 → 审批 |
| D3 Claude 侧栏 | mod：成员、时间线、发消息、审批、开房间、邀请；轮询循环推送唤醒；`/clear` 重新声明 | Claude 桌面版里开房间、邀请、审批都能做；被 @ 时空闲会话自动起回合 |
| D4 OpenCode 和 dsh 侧栏 | OpenCode TUI 插件侧栏；dsh 抽屉 | 三家同时在线，互相 @，各自侧栏实时一致；截图和录屏用于作品集 |
| D5 安装和 Windows Hello | 安装程序；高风险操作的 Windows Hello；规则化审批和活动视图 | 新机器上装好后 10 分钟内开房间并邀请两家；高风险审批必须过 Windows Hello |
| 之后 | 可回放的事件日志；辩论、去中心化、守门员预设；长期记忆 | 各自另起设计稿 |

## 10. 待用户决定

1. §8.1 网络方案（推荐 mirrored，等 T15 跑完再改）。
2. 剩余核对 U7–U11（步骤见 D0 报告"用户手动核对清单"），可以在 D1 进行期间做。
