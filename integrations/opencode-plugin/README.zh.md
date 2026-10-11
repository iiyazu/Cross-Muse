# xmuse 侧栏：OpenCode TUI 插件

OpenCode 2.x 的 TUI 插件，在会话页右侧栏显示 xmuse 房间。接口约定见
`docs/design/XMUSE2-VIEW-API.zh.md`（v0，§7 真 hub 实现说明为准）。

## 安装

在 `cli.json` 的 `plugins` 里加本目录（TUI 插件入口是 `tui.tsx`）：

```json
{
  "$schema": "https://opencode.ai/v2/cli.json",
  "plugins": ["/path/to/integrations/opencode-plugin"]
}
```

`cli.json` 位置：`~/.config/opencode/cli.json`（或 `$XDG_CONFIG_HOME/opencode/cli.json`）。
注意是 `cli.json` 的 `plugins`，不是 `opencode.json` 的 `plugin`（官网文档是旧 v1 接口，不要照抄）。
依赖 `@opencode/plugin@2.0.26`：首次使用前在本目录跑一次 `npm install`。

## 配置

- hub 地址：环境变量 `XMUSE_HUB_URL`，否则读 `<房间>/.xmuse/hub.json` 的端口，默认 `http://127.0.0.1:43117`。
- 令牌：开房间/加入成功后存在插件自己的 durable 存储（`ctx.storage.store("xmuse-auth")`，
  另备份一份到 `$XDG_STATE_HOME/xmuse-opencode/xmuse.json`，模式 600）。
  **不进模型上下文，不写进工作区，不打印。**

## 命令（输入框里 `/xmuse …`，带参数，不会发给模型）

| 命令 | 说明 |
|---|---|
| `/xmuse status` | 房间名、版本、成员/审批数（toast 显示） |
| `/xmuse room new <名字>` | 开房间（当前目录），自己成为主控 |
| `/xmuse invite <provider> <角色> <职责描述>` | 建一次性邀请码（10 分钟），弹对话框显示 `邀请码 + /xmuse join …` |
| `/xmuse join <码>` | 用邀请码加入，绑定当前会话 |
| `/xmuse leave` | 离开房间，清掉本地令牌 |
| `/xmuse say <to> <文字>` | 发消息（to：成员 id、`#话题`、线程 id 如 `dm:a+b`） |
| `/xmuse approve [id] [once\|always\|reject]` | 审批：不带参数时对话框选条目再选决定 |
| `/xmuse more` | 加载 20 条更早的时间线 |
| `/xmuse ack` | 确认所有 @ 我的消息（清未读） |

侧栏显示：成员列表（在线/状态/未读/职责）、最新 8 条时间线（@ 我的打 `▶`）、
审批队列（`[id] 摘要`）、对齐条目摘要。被 @ 时弹 toast（`xmuse @我`）。
`sidebar.content` 槽只在会话页出现；终端太窄（约 <110 列）时侧栏可能被收起，
把窗口拉宽即可。审批队列里除 `shell` 外还有 `alignment`（对齐提案，id 如 `E12`）
和 `resume:<成员>`（被暂停的成员），都用 `approve` 处理。

## 人工核对清单

1. 用临时配置启动（不碰全局）：`XDG_CONFIG_HOME=/tmp/ocx/config opencode --standalone`，
   进任一会话，右侧栏出现 `xmuse: 未加入房间` + `/xmuse room new` 提示。
2. 起假 hub：`node tools/mock-hub/mock-hub.mjs --port 43117`（另开终端）。
3. TUI 里 `/xmuse room new demo` → toast 显示已开房间；侧栏显示房间名和自己。
4. 另开终端用假 hub 注入口模拟别人：`curl -XPOST 127.0.0.1:43117/_mock/member -d '{"id":"dsh-1","description":"w"}'`，
   再 `_mock/say` 发一条 `@<你的成员id>` → TUI 弹 `xmuse @我` toast，侧栏成员出现未读数。
5. `_mock/approval` 加一条审批 → 侧栏出现 `[A..]`；`/xmuse approve` 走对话框批掉。
6. `/xmuse invite opencode executor 测试` → 对话框显示邀请码和 `/xmuse join …` 命令。
7. 发消息：`/xmuse say #room hello`（用操作令牌，记为用户经 opencode 侧栏）。
8. 检查：`XMUSE_HUB_URL` 日志里无令牌；工作区 `git status` 无新增文件（含令牌文件）。

## 测试

```
cd integrations/opencode-plugin
npm install            # 一次性（@opencode/plugin 2.0.26）
npm test               # node --test：lib 单元测试 + 对 mock-hub 的端到端
```

`test/hub.test.mjs` 自己起 `tools/mock-hub` 子进程（端口 43992），覆盖：
开房间→视图→邀请→加入→@→未读→成员令牌不能审批→审批→ack清零→长轮询唤醒/超时。
TUI 真机验证见上文清单（已在 opencode v2.0.26 + 临时 XDG 目录验证：
插件 setup 成功、侧栏渲染、`/xmuse status` toast）。

## 文件

- `tui.tsx`：插件入口（侧栏槽、斜杠命令、长轮询、toast/对话框）
- `lib/hub.mjs`：hub HTTP 客户端（可注入 fetch，便于测试）
- `lib/view.mjs`：纯函数（解析视图、去重、@检测、侧栏文本）
- `lib/store.mjs`：令牌文件存储（600 权限，只放插件自己目录）
- `test/`：`view.test.mjs`、`hub.test.mjs`
