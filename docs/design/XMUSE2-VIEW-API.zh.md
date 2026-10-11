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

## 7. v0 实现说明（D2，2026-10-12）

约定没写、由 hub 实现定下的细节。侧栏照此处理，假 hub（`tools/mock-hub`）与此不同的地方以真 hub 为准：

- **`me`**：成员令牌 `{"kind": "member", "id": <成员>}`；操作令牌 `{"kind": "operator", "id": <它所属的成员>}`，`for_me` 和 `unread` 按这个成员算；CLI 的管理令牌 `{"kind": "admin", "id": "human"}`，说的话记 `via: "cli"`。
- **`POST /v1/rooms` 不带 `member_id`** 时成员 id 取 vendor 名（`claude`、`opencode`、`dsh`），假 hub 用的是 `host`。房间建成后再调返回 `409 room_exists`；`dir` 与 hub 的工作区不一致返回 `400 wrong_dir`（Windows 写法和 `/mnt/c/...` 写法视为同一目录）。用 `xmuse init` 建的工作区第一次被读时自动有房间，主控是它的桌面协调者，这时只能凭邀请码加入。
- **邀请码**：格式 `XXXX-XX`（不含 0/O/1/I/L），大小写不敏感，有效期由配置 `invite_ttl` 定，默认 600 秒。不认识的码 `404 unknown_code`。邀请带 `name` 且该成员已存在、同 vendor、还没绑定会话时，加入即接管它（例如 `xmuse agent add` 预先登记的成员），否则 `409 member_exists`，码不作废。命令行：`xmuse invite <vendor> [--role] [--description] [--name]`。
- **成员的运行方式**：经侧栏加入的 Claude 成员和 dsh 成员由用户自己的会话承载，hub 不起回合；OpenCode 成员由 hub 起它自己的 `opencode serve`。同一目录已有 Claude 成员时，新加入的 Claude 成员不写 `.mcp.json`，只用 mod 自带的工具。
- **会话绑定**：成员令牌的请求一旦绑定就必须带 `x-xmuse-session`，`/v1/rebind` 例外（只凭成员令牌）。`/v1/leave` 之后不再要求会话头。
- **时间线**：hub 的通知 `kind: "system"`、`from: "hub"`；房间事件（开房间、加入、移除、转让主控）在 `#room`。`via` 由桌面协调者转述时为 `"coordinator"`。私聊线程 id 为 `dm:<两个 id 按字典序用 + 连接>`，`say` 的 `to` 可以直接写这个线程 id。
- **审批队列**：除 `shell` 外，待用户确认的对齐提案（`id` 为 `E12` 这样的条目号，`kind: "alignment"`）和被暂停的成员（`id` 为 `resume:<成员>`，`kind: "resume"`）也在里面，都可以用 `approve` 处理（`once`/`always` 视为同意）；对齐提案也可以用 `align`。
- **移除**：`remove` 保留历史，令牌立即失效，不再收消息；主控不能被移除（`409 is_host`），先 `transfer_host`。
- **`version`**：hub 每次请求后、以及长轮询等待期间每 0.5 秒，对视图涉及的表取指纹，变了就加一；持久化，hub 重启后继续增长。`since` 大于当前 version 时返回全量。

待定（v0.1 再议）：
1. OpenCode TUI 要用 `--server --session` 连到 hub 起的 serve，视图里还没有这两个值（serve 有密码，只能给成员自己的令牌看）。
2. `members[].status` 对 Claude/dsh 侧栏成员只能反映"在线/离线/有待唤醒"，回合是否在跑 hub 不知道；需要的话由侧栏上报。
