# xmuse 2 侧栏接口约定 v0（D2 实现，D3/D4 照此开发）

2026-10-11，r7 主控。三家侧栏（Claude mod、OpenCode TUI 插件、dsh 抽屉）和 hub 之间只走这份约定。D2 按它实现；D3/D4 在 D2 完成前用自己的假接口（返回下面示例 JSON 的最小 HTTP 服务）开发。约定要改，先由主控更新本文件并在房间里发 decision，不要各改各的。

## 1. 基本

- hub 只监听 `127.0.0.1:<port>`；端口从房间状态目录的 `hub.json` 读（`{"port": 43117, ...}`）。
- 所有请求和响应都是 JSON（UTF-8），时间是 Unix 秒（浮点）。
- 两种令牌，放在请求头 `Authorization: Bearer <token>`：
  - **成员令牌**：agent 自己的工具调用和插件代表成员的读写；不能做审批和管理。
  - **操作令牌**：只在侧栏插件进程里，代表用户在侧栏上的操作；能做审批和管理。
- 绑定后的成员请求还要带 `x-xmuse-session: <会话 id>`，与绑定的会话不一致返回 `409 not_bound_session`。
- 错误：`{"error": "<code>", "message": "<人读的说明>"}`，HTTP 状态 400/401/403/404/409/410/429。

## 2. 视图：`GET /v1/view?since=<version>&wait=<秒>`

- 长轮询：`since` 是上次拿到的 `version`；没有变化时最多挂起 `wait` 秒（默认 25，上限 30），超时返回 `204`。第一次传 `since=0` 拿全量。
- 用成员令牌或操作令牌都能读；`me` 字段说明读的人是谁。
- 响应（全量快照，侧栏直接替换整个状态；时间线按需截断，见 `timeline_cursor`）：

```json
{
  "version": 812,
  "room": {"id": "r-7f3a", "name": "xmuse-dev", "dir": "C:\\Users\\user\\xmuse-dev", "host": "coord",
           "info_layer": "on", "created_at": 1791726000.0},
  "me": {"kind": "member", "id": "oc-d4"},
  "members": [
    {"id": "coord", "vendor": "claude", "model": "claude-opus-5-5", "role": "coordinator",
     "description": "主控：拆任务、定约定、审查合并", "status": "idle", "online": true,
     "paused": false, "unread": 0, "tokens_hour": 0, "tokens_hour_cap": 0},
    {"id": "oc-d4", "vendor": "opencode", "model": "opencode-go/muse-spark-1.3", "role": "executor",
     "description": "OpenCode 侧栏（D4）", "status": "running", "online": true,
     "paused": false, "unread": 2, "tokens_hour": 412000, "tokens_hour_cap": 0}
  ],
  "threads": [
    {"id": "dm:coord+oc-d4", "kind": "dm", "title": "coord ↔ oc-d4", "members": ["coord", "oc-d4"],
     "last_at": 1791726600.0, "unread": 1},
    {"id": "#d4", "kind": "topic", "title": "#d4", "members": ["coord", "oc-d4", "dsh-d4"],
     "last_at": 1791726500.0, "unread": 1}
  ],
  "timeline": [
    {"id": 1043, "thread": "#d4", "from": "coord", "via": null, "to": ["oc-d4", "dsh-d4"],
     "mentions": ["oc-d4"], "kind": "message", "text": "@oc-d4 侧栏先用假接口跑起来", "at": 1791726500.0,
     "for_me": true}
  ],
  "timeline_cursor": {"oldest": 1001, "has_more": true},
  "alignment": [
    {"id": "E12", "kind": "decision", "scope": "module:sidebar", "author": "coord",
     "text": "侧栏接口按 XMUSE2-VIEW-API v0", "supersedes": null, "status": "active", "at": 1791726400.0}
  ],
  "approvals": [
    {"id": "A7", "kind": "shell", "member": "oc-d4", "summary": "npm install",
     "detail": "cd .xmuse-wt/d4-oc && npm install", "risk": "normal", "at": 1791726550.0}
  ],
  "run": null
}
```

字段说明：
- `members[].status`：`idle | queued | running | paused | offline`；`online` 表示已绑定会话（或 hub 驱动的成员已注册）。`tokens_hour_cap` 为 0 表示不限。
- `timeline[].via`：`null`（成员自己发的）、`"cli"`、`"<provider> sidebar"`（用户经某家侧栏）、`"coordinator"`；`from` 为 `"human"` 时表示用户。`for_me`：这条点名或发给读者。
- `timeline` 默认带最近 50 条；更早的用 `GET /v1/timeline?before=<id>&limit=50` 取，返回 `{"items": [...], "has_more": bool}`。
- `approvals[].kind`：`shell | alignment | resume | membership`；`risk`：`normal | high`（`high` 由 hub 弹 Windows Hello，D5 前当 `normal` 处理）。
- `run`：预设运行时为 `{"id", "preset", "phase", "deadline_at", "executors": [{"id", "state"}], "events": [{"at", "kind", "text"}]}`，否则 `null`。

## 3. 操作：`POST /v1/act`

请求体 `{"act": "<名字>", ...参数}`。成员令牌只能用 `say`、`ack`；其余要操作令牌。

| act | 参数 | 返回 |
|---|---|---|
| `say` | `to`（成员 id、`#话题` 或线程 id），`text`，`mentions?` | `{"id": <消息 id>}`；操作令牌发出的记 `from=human, via="<provider> sidebar"` |
| `ack` | `ids: [..]` | `{"ok": true}` |
| `approve` | `id`，`decision: "once" \| "always" \| "reject"` | `{"ok": true}` |
| `invite` | `vendor`，`role`，`description`，`name?` | `{"code": "K7Q2-9F", "expires_at": ..., "command": "/xmuse join K7Q2-9F"}` |
| `remove` | `member` | `{"ok": true}` |
| `pause` / `resume` | `member` | `{"ok": true}` |
| `transfer_host` | `member` | `{"ok": true}` |
| `align` | `id`，`decision: "confirm" \| "reject"` | `{"ok": true}` |

写操作成功后 `version` 增加，所有侧栏的长轮询立即返回。

## 4. 房间和绑定

- `POST /v1/rooms`（无令牌，只在没有房间时可用；hub 由插件拉起）：`{"dir", "name", "vendor", "session_id", "member_id?", "description?"}` → `{"room", "member_token", "operator_token", "member_id"}`。调用者成为主控。
- `POST /v1/join`（无令牌）：`{"code", "vendor", "session_id", "client_info"}` → `{"member_id", "member_token", "operator_token"}`。码一次性、默认 10 分钟过期；过期 `410`，用过 `409`，vendor 不符 `403`。
- `POST /v1/rebind`（成员令牌）：`{"session_id"}`——同一插件实例的会话换了 id（如 Claude `/clear`）时重新声明，不需要新邀请码。
- `POST /v1/leave`（成员令牌）→ 解绑，未投递消息保留。
- 令牌只存在插件进程里（Claude mod 用 `$.store`，OpenCode/dsh 插件用自己的存储），不进模型上下文、不写进工作区。

## 5. 唤醒（hub → 各家）

沿用现有适配器：hub 驱动的成员由 hub 起回合；Claude 桌面会话由 mod 的轮询循环发现 `for_me` 的新消息后用 `$.prompt.submit` 起回合（D0 已验证：从定时器提交可以，从斜杠命令处理函数里提交不行）；OpenCode TUI 经 serve 投递；dsh 前台经插件包中继。

## 6. 版本

本文件是 v0。D2 实现时发现必须改的地方，先在房间里提 question 给主控，由主控改约定后发 decision。
