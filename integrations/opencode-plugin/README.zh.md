# xmuse 侧栏：OpenCode TUI 插件

OpenCode 2.x 的 TUI 插件，在会话页右侧栏显示 xmuse 房间。接口约定见
`docs/design/XMUSE2-VIEW-API.zh.md`（v0 第 7 节、v0.1 第 8 节；8.8 与前文不一致时以 8.8 为准）。

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

## 命令（输入框里 `/xmuse …`，带参数，不会发给模型）

| 命令 | 说明 |
|---|---|
| `/xmuse status` | 房间名、版本、成员/审批数（toast 显示） |
| `/xmuse room new <名字>` | 开房间（当前目录），自己成为主控 |
| `/xmuse invite <provider> <角色> <职责描述>` | 建一次性邀请码（10 分钟），弹对话框显示 `邀请码 + /xmuse join …` |
| `/xmuse join <码>` | 用邀请码加入，绑定当前会话 |
| `/xmuse leave` | 离开房间，清掉本地令牌 |
| `/xmuse say <to> <文字>` | 发消息（to：成员 id、`#话题`、线程 id 如 `dm:a+b`） |
| `/xmuse approve [id] [once\|always\|reject]` | 审批：不带参数时对话框选条目再选决定（share 审批显示私信摘录） |
| `/xmuse more` | 加载 20 条更早的时间线 |
| `/xmuse ack` | 确认所有 @ 我的消息（清未读，显示 hub 生效条数） |
| `/xmuse wake` | 现在叫醒主控（`wake_host`，放出压住的结果） |
| `/xmuse rooms` | 本机房间列表（登记表 + 在线情况） |
| `/xmuse join-local [序号\|room_id]` | 一键加入本机房间（不带参数时对话框选） |
| `/xmuse add [厂商 角色 描述]` | 添加成员（`member_add`，缺的走对话框问） |
| `/xmuse edit <成员> [role\|desc] [值]` | 改角色/职责描述（`member_edit`） |
| `/xmuse host <成员>` | 设为主控（`transfer_host`） |
| `/xmuse pause\|resume\|remove <成员>` | 暂停 / 恢复 / 移出 |
| `/xmuse dm <成员> <文字>` | 打开私聊（发一条私信） |
| `/xmuse new-group [#群] [成员..]` | 新建私有群（`thread_new`） |
| `/xmuse group-add <群> <成员>` | 把成员拉进私有群（`thread_add`） |
| `/xmuse group-rm <群> <成员>` | 把成员移出私有群（`thread_remove`） |

侧栏显示：成员列表（在线/状态/未读/近1小时唤醒数/职责）、群列表（私有群🔒）、
最新 8 条时间线（@ 我的打 `▶`）、done 的结果标签（hub 改判、未核实、分享自、已路由）、
主控等待（在等谁、压住几条、何时自动唤醒）、
审批队列（`[id] 摘要`，分享审批另分区并显示私信摘录）、对齐条目摘要。被 @ 时弹 toast（`xmuse @我`）。

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
