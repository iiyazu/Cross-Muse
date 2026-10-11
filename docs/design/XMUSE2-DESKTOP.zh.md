# xmuse 2 桌面版设计稿（草稿，等用户审阅）

2026-10-11，r7。目标：用户打开 xmuse.exe → 开房间 → 邀请各家 agent → agent 在用户指定的会话里执行一条 join 命令完成双向绑定 → agent 互相 @ 的消息既在各家原生界面里出现，也在 xmuse 面板里汇总；审批在 xmuse 面板里做；之后加记忆查看和编辑。

## 1. 已定（用户 10-11）

| 项 | 决定 |
|---|---|
| hub 运行位置 | **Windows 原生**（不再依赖 WSL） |
| Claude 桌面版 | 第一版接受"不能推送"；但调研发现 Claude Code 的 mod（插件函数钩子）能做到推送和侧栏，见 §4.1，所以第一版就按能推送设计 |
| agent 单独 OS 用户 | 暂时搁置（安全模型里如实写明缺口） |

## 2. 用户流程

1. 打开 xmuse.exe。首次运行时检测各家是否安装（claude、opencode、dsh），缺的只提示，不强制。
2. **开房间**：选一个工作目录（房间 = 一个工作区，对应现在的一个 hub 状态目录），起名。
3. **邀请**：在房间里点"邀请"，选 provider（Claude / OpenCode / dsh）和角色（规划者、执行者、复核、自由），得到一个一次性邀请码（6–8 位，10 分钟过期，只能用一次），以及一条可以复制的命令：
   - Claude：`/xmuse join K7Q2-9F`
   - dsh：`/xmuse join K7Q2-9F`
   - OpenCode：`/xmuse-join K7Q2-9F`（形式以 OpenCode 插件能注册的命令为准，见 §4.2）
4. 用户在**自己想要的那个会话**里执行这条命令。插件把"邀请码 + 本会话 id"交给 hub，hub 校验后完成绑定，面板上这个成员变成"在线"。
5. 之后：用户在面板或任一家会话里 @ 某个成员，hub 负责投递和唤醒；被 @ 的 agent 在自己的原生界面里看到消息并处理；回复同样回到 hub。面板显示全局时间线。
6. agent 需要审批时（OpenCode 的 shell 命令、对齐条目的确认、恢复被限额暂停的 agent），审批出现在面板的审批队列里，用户在面板上批。

## 3. 架构

```
xmuse.exe（Tauri 外壳 + 网页前端）
   │  启动、监控、重启
   ▼
hub（Windows 原生 Python，打包成单个可执行文件；每个房间一个进程，沿用现在"一个工作区一个 hub"）
   │  127.0.0.1 HTTP（现有 /v1/tools、/v1/relay） + 新增 /v1/ui（只读）和 /v1/operator（审批等）
   ├── Claude：mod（侧栏、横幅、/xmuse join、定时拉取、$.prompt.submit 唤醒）+ 现有 MCP 垫片
   ├── OpenCode：每个实例一个 `opencode serve`（现有）+ OpenCode 插件（join 命令、toast）
   └── dsh：现有插件包（中继长轮询 + 绑定）+ 新增前端侧栏
```

- **前端一份，多处复用**：同一个网页前端，在 xmuse.exe 里是主窗口，在 dsh 里嵌进侧栏，在 Claude 的 mod 侧栏里用原生元素重画一个精简版（mod 里没有 DOM，不能嵌网页，见 §4.1）。
- **房间和 hub 的关系**：第一版每个房间一个 hub 进程，exe 管理它们的启停，hub 代码基本不动。多个房间合并到一个 hub 进程是以后的优化，不在本稿范围。

## 4. 各家适配

### 4.1 Claude（Code CLI 和桌面版 Code 标签）——用 mod

依据：本机 Claude Code 2.1.295 的 mod 接口（`plugin-authoring` 技能自带的类型声明）。接口是早期版本，会随版本变化，以类型文件为准。

| 需要的能力 | mod 里的做法 |
|---|---|
| 侧栏 | `$.ui.open({ id, title })` 打开面板，`ui.render` 钩子在 `{ component: 'Pane' }` 上画；桌面版 Code 标签里停靠在对话旁边。只能用宿主提供的元素（Box、Text、Button、Markdown、Input……），不能嵌网页 |
| 输入框上方横幅 | `ui.render` 钩子挂在 `{ component: 'AbovePrompt' }`：显示"2 条 @ 你的消息未处理"之类 |
| toast / 状态栏 / 系统通知 | `$.ui.toast`、`$.ui.status`、`$.ui.notify` |
| 访问 hub | `$.http.fetch("http://127.0.0.1:<端口>/...")`（经宿主发请求；组织的网络策略可能拦截，需实测） |
| 定时拉取 | `session.start` 里起 `$.clock.every`；hub 端提供长轮询或游标接口 |
| **推送唤醒** | `$.prompt.submit({ text })`：会话空闲时起一个新回合，模型读到的是"xmuse 插件发来一条消息"，来源清楚。**不用** `asUser`，避免把 agent 的话伪装成用户的话 |
| 正在运行的回合里插入消息 | `$.session.append`（用户角色、`isMeta`，模型下一步就能读到）。只用于"有新的 @"这类提示，不用于传递审批结果 |
| join 命令 | `session.start` 里 `$.command.register({ name: 'xmuse' })`，`command.run` 钩子处理 `join <码>`、`status`、`leave` |
| 会话 id | 从 mod 的会话信息里取（实现时以类型文件为准），连同邀请码交给 hub |
| 安装 | 用户在终端执行 `/plugin install xmuse --marketplace <owner>/<repo>`（用户级安装，桌面版 Code 标签的本地会话也会加载）；开发期用 `CLAUDE_CODE_PLUGIN_DIRS` |

需要实测的点：桌面版 Code 标签里侧栏的停靠和尺寸；`$.http.fetch` 到 127.0.0.1 是否放行；`$.prompt.submit` 在桌面版里起回合的表现；mod 拿到的会话 id 和 hub 侧记录的能否对上。

### 4.2 OpenCode

- 唤醒和投递：沿用现在的做法，每个实例一个 `opencode serve`，hub 用它的 prompt API 加 SSE。
- **待实测**：用户在 OpenCode TUI 或桌面版里打开的会话，能否连到 hub 启动的那个 serve 实例上，从而在用户正在看的界面里看到投递的消息。如果不能，就改为 join 时由插件把会话所在的 serve 地址报给 hub。
- 插件：OpenCode 的插件能挂事件钩子、在 TUI 弹 toast；能否注册斜杠命令、能否在桌面版加侧栏，**未确认**。第一版目标：join 命令（不行就退回成 MCP 工具 `xmuse_join`）和 @ 提示的 toast。

### 4.3 dsh

- 绑定和投递：现有插件包的中继（`/xmuse bind`）改成邀请码形式：`/xmuse join <码>`。中继长轮询和"按会话强制身份"都已经有了。
- 侧栏：插件包加前端部分（dsh 插件可以往网页界面注入脚本，本机的 dsh-pixel-maid 就是这样），画一个可以收起的抽屉，内容是 xmuse 面板的精简版。数据走插件宿主侧的同源路由转发 hub，令牌只在宿主进程里，不进浏览器。
- hub 改为 Windows 原生之后，dsh 不再需要 WSL 互操作，现在 `wsl.exe` 参数转义、UNC 路径写入、沙箱拒绝 WSL 这几类问题一并消失。

## 5. 邀请和绑定协议

| 步骤 | 内容 |
|---|---|
| 创建邀请 | 面板调用 `/v1/operator/invite {room, vendor, role, name?}` → `{code, expires_at}`。码一次性，默认 10 分钟过期 |
| join | 插件调用 `/v1/join {code, vendor, session_id, client_info}` → hub 校验码、vendor 匹配、没过期没用过 → 创建 agent（或把已有成员绑到新会话）→ 返回 agent 令牌 |
| 令牌存放 | 只给插件进程（mod 的 `$.store`、dsh 插件宿主、OpenCode 插件），**不进模型上下文**，不写进工作区 |
| 身份强制 | 绑定后，这个 agent 的所有调用都要带 `x-xmuse-session`，和绑定的会话不一致就拒绝（dsh 现在的做法推广到三家） |
| 换会话 | 同一成员可以重新 join 到别的会话（要新邀请码），后一次生效，hub 记一条通知 |
| 离开 | `leave` 或面板上"移出"：解绑，未投递的消息保留 |

## 6. 面板（xmuse.exe 主窗口）

- **房间列表**：每个房间的成员数、在线数、未处理的 @、待审批数。
- **房间内**：
  - 成员：provider、模型、角色、在线/运行/空闲/暂停、本小时 token 和上限；
  - 时间线：按话题分组，@ 高亮，可以按成员或"只看 @ 我"过滤；用户在这里发消息（来源记为"用户（经 xmuse 面板）"）；
  - 对齐条目：当前有效的 decision、assumption、question、convention、assignment，替换关系；
  - 审批队列：OpenCode 的 shell 命令、对齐条目确认、限额暂停的恢复；
  - 预设运行：阶段、倒计时、快照、冲突和越界事件。
- **之后**：记忆（MemoryOS）查看、编辑、撤销，每条标明来源和依据。

## 7. 安全模型

| 风险 | 处理 |
|---|---|
| agent 冒充用户在面板上发消息或审批 | 面板在 xmuse.exe 里，agent 一般够不到（不像 Claude 的内置浏览器面板，agent 自己能操作）。operator 接口只对 exe 开放：exe 启动 hub 时生成一个只有它知道的 operator 令牌，不落盘 |
| 开了 computer use 的 agent 能操作整个桌面 | 高风险操作（批准白名单外的 shell 命令、`always` 类审批、改房间成员）要过 **Windows Hello**（`UserConsentVerifier`），需要人本身在场。普通消息不需要 |
| 同一 OS 用户能读 agent 令牌文件 | 已知缺口，和现在一样（agent 单独 OS 用户已搁置）。令牌改存 Windows 凭据管理器（DPAPI）能挡住"顺手读文件"，挡不住有意的同用户进程 |
| mod 用 `$.prompt.submit` 唤醒 | 不用 `asUser`，模型和记录里都标明"xmuse 插件发来的消息"；消息正文里写明原始发送者 |
| 只绑定 127.0.0.1 | hub 和面板都只监听本机回环地址 |

## 8. hub 迁到 Windows 原生要改什么

- 路径和状态目录：`%LOCALAPPDATA%\xmuse\<房间>-<hash>\`；去掉所有 `wsl.exe`、UNC 路径、`to_win` 一类的转换。
- 启动各家：直接启动 `claude.exe`、`opencode.exe`、dsh 的 `cli.js`（不再经 WSL）。
- 进程管理：POSIX 信号、`setsid`、进程树判断（"调用来自用户自己的终端"）要换成 Windows 的做法（Job Object、父进程链）；审批改由面板承担后，"控制终端"这条判断可以退役。
- 测试：现在的 337 个测试在 Linux 上跑。要加 Windows CI（GitHub Actions 的 windows-latest），依赖 pty 的测试改写或标记为只在 POSIX 跑。
- 打包：hub 用 PyInstaller 或嵌入式 Python 打成一个目录，随 exe 分发。
- 实验 T15 仍在 WSL 里的 hub 上跑，迁移在独立分支上做，不影响实验。

## 9. 分阶段计划和验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| D0 实测 | 三家的待实测点：Claude mod 的侧栏、fetch 到 127.0.0.1、`$.prompt.submit`、会话 id；OpenCode TUI/桌面版能否看到 serve 投递的消息、插件能否注册命令；dsh 侧栏注入 | 每项给出"能 / 不能 / 替代方案"和证据 |
| D1 hub 原生化 | §8 | Windows 上全量测试通过；三家在 Windows 原生 hub 下各完成一次端到端收发 |
| D2 协议和面板 | 邀请和 join 协议（§5）；`/v1/ui` 只读接口加 SSE；网页面板（§6，先不含记忆）；`xmuse ui` 在浏览器里打开 | 三家各用 join 绑定成功；面板实时显示时间线和成员状态 |
| D3 各家侧栏 | Claude mod（侧栏、横幅、推送唤醒、join 命令）；dsh 抽屉；OpenCode toast 和 join | 三家同时在线，互相 @，各自原生界面和面板都能看到；截图和录屏用于作品集 |
| D4 exe 和审批 | Tauri 打包；hub 进程管理；审批队列；Windows Hello | 新机器上安装 exe 后 10 分钟内开房间并邀请两家；高风险审批必须过 Windows Hello |
| D5 记忆 | MemoryOS 接入面板：查看、编辑、撤销 | 另起设计稿 |

D0 不写产品代码，先把不确定的点测清楚再定 D2、D3 的细节。

## 10. 待用户决定

1. 房间是否就是工作区（一个房间一个工作目录）？还是允许一个房间里的 agent 各自在不同目录工作？
2. 面板发出的消息记为"用户（经 xmuse 面板）"，和 CLI 发的"human (via cli)"并列，可以吗？
3. 前端技术：Tauri（体积小，需要 Rust 工具链）还是 Electron（体积大，生态熟）？本稿默认 Tauri。
