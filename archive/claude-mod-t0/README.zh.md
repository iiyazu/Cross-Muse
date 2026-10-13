# xmuse 的 Claude 侧栏（Claude Code mod）

> **已归档（2026-10-13）**：10-12 方向调整为"Claude 主控 + mod 面板"，本侧栏由 `integrations/xmuse-panel/` 取代，只留作参考，不再维护。下文的路径 `integrations/claude-mod` 现为 `archive/claude-mod-t0`。

插件名 `xmuse`。在 Claude Code（终端版和桌面版 Code 标签页）里给当前会话加一个 xmuse 侧栏：看房间成员、时间线、审批、对齐条目，开房间、发邀请、加入房间；别的成员 @ 你时，空闲的会话会被自动唤醒，用 xmuse 工具回复。

对接 hub 的接口只按 `docs/design/XMUSE2-VIEW-API.zh.md`（约定 v0）。真 hub（D2）完成前用假 hub `tools/mock-hub/mock-hub.mjs` 开发和测试。

## 文件

| 路径 | 内容 |
|---|---|
| `.claude-plugin/plugin.json` | 插件清单和用户配置项（`hubUrl`、`stateDir`、`pollWaitSeconds`） |
| `hooks/hooks.json`、`hooks/register.tsx` | 全部钩子：会话开始起轮询、`/xmuse` 命令、侧栏、横幅、`say` 工具 |
| `src/format.ts`、`src/state.ts` | 纯函数：时间线和成员的 Markdown、横幅文字、唤醒提示、去重 |
| `types/index.d.ts` | `$.state` 契约和视图类型 |
| `xmuse.test.ts` | `claude plugin test` 用例 |
| `e2e/run-e2e.mjs` | 假 hub 加真实 `claude -p`（haiku）的端到端脚本 |

## 安装

开发期（不进正式环境）：

```bash
claude --plugin-dir /path/to/xmuse/integrations/claude-mod
```

或者设环境变量 `CLAUDE_CODE_PLUGIN_DIRS=/path/to/xmuse/integrations/claude-mod`，再启动 `claude` 或桌面版。

正式安装要走 marketplace（`claude plugin marketplace add` 加 `claude plugin install xmuse`）；仓库里还没有 marketplace 清单，D5 的安装程序再补。

装好后重启会话。桌面版在 Code 标签页里新开一个会话即可。

## 配置

| 配置项 | 含义 | 默认 |
|---|---|---|
| `hubUrl` | hub 地址 | 空：先找 `stateDir/hub.json`，再找 `<项目>/.xmuse/hub.json`，都没有就用 `http://127.0.0.1:43117` |
| `stateDir` | 房间状态目录（里面有 `hub.json`，内容是 `{"port": ...}`） | 空 |
| `pollWaitSeconds` | 一次 `/v1/view` 长轮询最多挂多久（1–30 秒） | 15 |
| `registryDir` | 本机登记表目录（里面有 `hubs.json` 和 `sidebar.key`） | 空：先找 `XMUSE_REGISTRY_DIR`，再按平台默认（Windows 是 `%LOCALAPPDATA%\xmuse`） |

`/xmuse hub <url>` 可以在本机覆盖 hub 地址，只接受回环地址（`127.0.0.1`、`localhost`、`[::1]`）；`/xmuse hub clear` 清除覆盖。

## 命令

| 命令 | 作用 |
|---|---|
| `/xmuse room new <名字>` | 开房间，本会话成为主控，打开侧栏 |
| `/xmuse invite <provider> <角色> <职责描述>` | 生成邀请码（10 分钟有效），码和可复制的命令显示在侧栏「房间」和提示条里，不进对话 |
| `/xmuse join <邀请码>` | 把本会话绑定为房间成员 |
| `/xmuse rooms` | 列出本机登记表里的房间 |
| `/xmuse join-local <房间名或 room_id>` | 一键加入本机房间（不用邀请码，`sidebar.key` 只在插件进程里读） |
| `/xmuse add <厂商> <模型\|-> <角色> <描述>` | 添加成员（hub 起它的回合） |
| `/xmuse group new #id [成员 …]` | 新建私有群 |
| `/xmuse wake-host` | 现在叫醒主控（不等合并） |
| `/xmuse status` | 房间名、我是谁、是否主控、成员和在线数、未读和待审批 |
| `/xmuse open` | 打开侧栏 |
| `/xmuse leave` | 离开房间，删除本目录的绑定 |
| `/xmuse rebind` | 会话 id 变了（如 `/clear` 之后）时把成员重新绑到当前会话；后台循环发现变化也会自动做 |
| `/xmuse hub [<url> \| clear]` | 查看或覆盖 hub 地址 |

## 怎么工作

- **绑定**：一个工作目录一个绑定（房间 = 一个工作目录），存在插件自己的 `$.store` 里，键是 `binding:<cwd>`。里面有成员令牌和操作令牌。
- **令牌**：两种令牌都只在 `$.store`，不进模型上下文，不写工作区，命令输出里也不打印。操作令牌只用于用户在侧栏和命令里的操作（发消息、审批、邀请等）；后台循环和模型调用的 `say` 工具只用成员令牌。
- **刷新**：会话开始后用 `$.clock.every` 长轮询 `/v1/view?since=<version>&wait=<秒>`。
- **唤醒**：发现新的、发给我的消息，且会话空闲时，从定时器回调里 `$.prompt.submit` 起一个回合（按消息 id 去重）。提示里写明发送者、话题和原文，让 agent 用 xmuse 工具回复。（D0 实测：从定时器提交能唤醒空闲会话，从命令处理函数里提交不能。）
- **横幅**：有 @ 我的未读或待审批时，输入框上方显示 `@ 我的未读 N · 待审批 M`，带打开侧栏的按钮；都没有就不显示。
- **侧栏分区**：时间线、成员、群组、主控、审批、对齐、房间（开房间和邀请表单、邀请码、主控标识）。桌面版没有表格和标签页，时间线和成员列表用 Markdown 渲染，分区用顶部一排按钮切换（审批、时间线带数字角标），话题用下拉框选。成员分区里有成员菜单（暂停/恢复/设为主控/移出/私聊/改角色描述/拉进群）；群组分区新建私有群（锁标记）并可移出群成员；主控分区显示在等谁、压住几条结果和自动唤醒倒计时，加"现在叫醒主控"按钮；时间线里 done 显示结果标签（hub 改判/未核实/分享自）；分享审批显示私信摘录。

## 测试

```bash
cd integrations/claude-mod
claude plugin validate .
claude plugin test .
```

2026-10-11 的结果：`✔ Validation passed`；`4 pass, 0 fail`（join 绑定且不打印令牌；hub 不通时给出说明并返回 1；后台循环画侧栏、显示横幅、只唤醒一次；侧栏发消息用操作令牌、工具用成员令牌）。UI 用例在 `desktop` 和 `terminal` 两个 surface 上各跑一遍。

端到端（需要 WSL 里已登录的 `claude`，只用 haiku，两个很短的回合）：

```bash
node integrations/claude-mod/e2e/run-e2e.mjs
```

它会起一个假 hub，建邀请码，用 `claude -p --plugin-dir` 跑 `/xmuse hub`、`/xmuse join`，再从假 hub 注入一条 coord 发来的 @，等会话被唤醒并用 `say` 回复，最后 `/xmuse leave` 和 `/xmuse hub clear` 清掉绑定。2026-10-11 结果：`E2E OK`（假 hub 收到 claude-1 回给 coord 的 `pong`）。

## 桌面版人工核对清单

这些只能在桌面版里用眼睛看，自动测试覆盖不到。先起假 hub：`node tools/mock-hub/mock-hub.mjs --seed coord`，再按“安装”一节用开发期方式加载插件，在 Code 标签页新开会话。

1. 运行 `/xmuse room new 测试房间`：侧栏停靠在对话旁，宽度可以拖动；「房间」分区显示房间名和“主控”标识。
2. 侧栏「房间」里填表单（provider 选 OpenCode、角色、职责描述）生成邀请：邀请码和可复制的命令出现在侧栏和提示条里，**对话里没有邀请码**。
3. 用假 hub 的注入口发一条 @ 你的消息（见 `tools/mock-hub/README.md`）：几秒内输入框上方出现横幅 `@ 我的未读 1`；会话空闲时自动起一个回合并回复。
4. 注入一条审批请求：横幅出现“待审批 1”；「审批」分区里“批准一次 / 总是 / 拒绝”三个按钮都能点，点完队列清空，时间线里出现审批结果。
5. 「时间线」：消息按话题/私聊分组，@ 我的高亮，“加载更早的”能翻页；从侧栏发一条消息，时间线里来源显示为经 Claude 侧栏发出。
6. 「成员」：状态、在线、职责描述、未读数正确。
7. 运行 `/clear` 后再注入一条 @：仍能收到并唤醒（自动 rebind）。
8. 关掉侧栏后用横幅按钮或 `/xmuse open` 能重新打开。
9. 窄终端（终端版，宽度 < 110 列）：侧栏不自动摆出，`/xmuse open` 给出提示。

## 已知限制

- `$.http.fetch` 没有流式，只能长轮询。
- 侧栏里的 `say` 工具名是 `mcp__xmuse__say`；同一会话如果还挂着 hub 的 xmuse MCP 服务，两边的工具要在 D5 统一。
- WSL 处于 NAT 网络时，Windows 桌面版访问不到 WSL 里的 hub；hub 改 Windows 原生（D1）或 WSL 改 mirrored 网络之后才能直连。
