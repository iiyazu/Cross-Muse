# xmuse 侧栏：OpenCode TUI 插件

> **已归档（2026-10-13）**：10-12 方向调整为"Claude 主控 + mod 面板"，OpenCode 改为由 hub 驱动的助手，各家侧栏这条路线停止，只留作参考，不再维护。下文的路径 `integrations/opencode-plugin` 现为 `archive/opencode-plugin-t0`。

OpenCode 2.x 的 TUI 插件，在会话页右侧栏显示 xmuse 房间。接口按侧栏接口约定
v0 和 v0.1。

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
  加入房间后记住该 hub，下次直连。
- 令牌：开房间/加入成功后存在插件自己的 durable 存储（`ctx.storage.store("xmuse-auth")`，
  另备份一份到 `$XDG_STATE_HOME/xmuse-opencode/xmuse.json`，模式 600）。
  **不进模型上下文，不写进工作区，不打印。**
- 本机凭据：读登记目录（`XMUSE_REGISTRY_DIR`，否则按平台默认）里的凭据文件，
  只在插件进程里读，随 `x-xmuse-sidebar` 头发出。**绝不显示、不记日志、
  不放进给模型看的任何文本。**

## 命令（每个操作一个斜杠命令，`/x` 菜单和命令面板里都能选到；要填成员/群/审批/房间时弹对话框选，不用手打 id）

| 命令 | 说明 |
|---|---|
| `/xmuse-status` | 房间名、版本、成员/审批数（toast 显示） |
| `/xmuse-rooms` | 本机房间列表（登记表 + 在线情况） |
| `/xmuse-join [序号\|room_id\|邀请码]` | 一键加入本机房间（缺参数弹房间选择；`XXXX-XX` 形走邀请码） |
| `/xmuse-new-room [房间名] [成员名]` | 开房间（当前目录），自己成为主控；成员名留空由 hub 起 |
| `/xmuse-add [厂商 角色 描述]` | 添加成员（`member_add`）；名字走对话框问，缺省 `<简称>-<角色>` |
| `/xmuse-host [成员]` | 设为主控（缺参数弹成员选择，显示名字·角色·职责） |
| `/xmuse-edit [成员]` | 改角色/职责描述（对话框选人、选字段、填值） |
| `/xmuse-dm [成员] [文字]` | 私聊（缺参数弹选择/输入框） |
| `/xmuse-say [去向] [文字]` | 发言（去向缺省弹群+成员选择） |
| `/xmuse-group [new\|add\|rm] …` | 新建私有群、拉进群、移出群（缺参数弹菜单） |
| `/xmuse-approve [id] [once\|always\|reject]` | 审批（缺参数弹条目/决定选择；share 审批显示私信摘录） |
| `/xmuse-wake` | 现在叫醒主控（放出压住的结果） |
| `/xmuse-leave` | 离开房间，清掉本地令牌 |
| `/xmuse-more` | 更多：邀请码邀请、暂停/恢复/移出、更早消息、确认已读 |
| `/xmuse <子命令>` | 兼容入口；子命令不认识时列出上面全部命令（不静默、不发给模型） |

侧栏显示（单列纯文字）：顶行房间名和我是谁（主控带 ★主控，不显示内部 version）、
审批置顶（`⚠ 待审批 N 条`，挂 40 分钟也能看到）、成员行（`★ id 角色 · 状态 · 职责/我`，主控 ★、
coordinator 显示"负责人"、空角色显示"成员"、wakes>0 显示"本小时唤醒 N 次"）、
群一行（私有群🔒）、消息行（`线程 发送者→接收者 [标签] 正文`，用户/系统/全体/done 标签行内）。
没内容的区块不显示。被 @ 时弹 toast（`xmuse @我`）。

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
`test/hub-v01.test.mjs` 起带登记目录的 mock（端口随机）：凭据头 401/403、
一键加入与 wrong_dir、member_add/edit、host/pause/resume/remove、
thread_new/add/remove 与错误码、wake_host、share_mark 参数校验。
`test/registry.test.mjs`：登记目录规则、死 pid 过滤、凭据形状校验。
TUI 真机验证见上文清单（已在 opencode v2.0.26 + 临时 XDG 目录验证：
插件 setup 成功、侧栏渲染、`/xmuse status` toast）。

## 文件

- `tui.tsx`：插件入口（侧栏槽、斜杠命令、长轮询、toast/对话框）
- `lib/hub.mjs`：hub HTTP 客户端（可注入 fetch，便于测试；v0.1 本机入口与新增 act）
- `lib/view.mjs`：纯函数（解析视图、去重、@检测、侧栏文本、房间/群/分享审批格式化）
- `lib/store.mjs`：令牌文件存储（600 权限，只放插件自己目录）
- `lib/registry.mjs`：登记表读取与侧栏凭据读取（只在插件进程里，绝不打印）
- `test/`：`view.test.mjs`、`hub.test.mjs`、`hub-v01.test.mjs`、`registry.test.mjs`
