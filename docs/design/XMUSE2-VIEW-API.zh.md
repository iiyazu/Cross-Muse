# xmuse 2 侧栏接口约定 v0.1（v0：D2 实现；v0.1 第 8 节：协作拓扑 T0–T5）

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
- **`unread` 和 `ack`**：`unread` 数的是投给该成员、还没读也没 ack 的消息，包括 `#room` 里不点名的广播（这类不唤醒、`for_me` 为 false），所以 `unread` 可以大于 `for_me` 的条数；hub 的通知（`kind: "system"`）不算，各家一样。成员加入之后才发出的广播才投给它，加入前的不算。hub 起回合的成员（OpenCode）被唤醒时，送进回合的消息就算已读，侧栏还没 ack 它的 `unread` 就已经降了；回合进行中新到的消息照样算未读。`ack` 只作用于投给读者自己的消息，别的 id 忽略，响应里的 `acked` 是实际生效的条数。Claude 成员收到的 hub 通知也是投递，ack 时一并计入 `acked`，但不算在 `unread` 里；所以侧栏不要拿 `acked` 和 `unread` 对账，要确认清空就看 ack 后的 `unread`。
- **长轮询提前返回**：回合开始、结束、成员上下线、审批变化都会让 `version` 变，所以 `wait` 不到时间就返回 200 是正常的，不一定有新消息。
- **`version`**：hub 每次请求后、以及长轮询等待期间每 0.5 秒，对视图涉及的表取指纹，变了就加一；持久化，hub 重启后继续增长。`since` 大于当前 version 时返回全量。

待定（v0.1 再议）：
1. OpenCode TUI 要用 `--server --session` 连到 hub 起的 serve，视图里还没有这两个值（serve 有密码，只能给成员自己的令牌看）。
2. `members[].status` 对 Claude/dsh 侧栏成员只能反映"在线/离线/有待唤醒"，回合是否在跑 hub 不知道；需要的话由侧栏上报。

## 8. v0.1：协作拓扑（里程碑 XMUSE2-TOPO 的 T0–T5，2026-10-12）

本节在 v0 的基础上**只做加法**，v0 的接口照旧可用。用户在 10-12 定了几条：
- 本机加入不要邀请码；
- 主控负责接活和分派；
- 成员可以自己建私有小群；
- 审查者核验在正式使用时默认开启；
- 私信默认不外传，要外传需用户批准；
- 主控按结果标签决定是否唤醒。

实现按下面的模块划分，新逻辑尽量写进新模块，共用文件里只加挂接点：

| 模块 | 内容 |
|---|---|
| `registry.py` | 本机登记表和侧栏凭据 |
| `threads.py` | 小群 |
| `dispatch.py` | 主控分派、结果标签、合并唤醒 |
| `evidence.py` | 证据核对、审查者核验 |
| `share.py` | 私信分享 |
| `route.py` | 按职责路由 |

### 8.1 本机加入（T0）

- **本机登记表**：
  - 位置：Windows 下是 `%LOCALAPPDATA%\xmuse\hubs.json`，其他系统是 `${XDG_STATE_HOME:-~/.local/state}/xmuse/hubs.json`。
  - 格式：`{"hubs": [{"room_id", "name", "dir", "url", "host", "pid", "started_at"}]}`。
  - hub 启动时按 `room_id` 写入或更新自己那一条，正常退出时删除。读的人要丢掉 `pid` 已经不在的条目。写入方式是先写临时文件再原子改名，同时要容忍几个 hub 并发写。
- **侧栏凭据**：
  - 和登记表放在同一目录，文件名 `sidebar.key`，32 字节随机数，十六进制保存，权限 600。不存在时由第一个启动的 hub 生成。
  - 侧栏插件读取它，放在请求头 `x-xmuse-sidebar: <key>` 里发出。agent 进程的环境里不提供它。
  - hub 的 shell 策略（allowlist 和 blocklist-experiment 都算）拒绝任何引用 `sidebar.key` 的命令。这只是同一 OS 用户下的约束，挡住的是 agent 无意或常规地自行加入，挡不住刻意的绕过。设计稿里要写明这一点。
- **`POST /v1/join`（v0.1）**：
  - 不带 `code` 时：必须带 `x-xmuse-sidebar`，请求体是 `{"dir" 或 "room_id", "vendor", "session_id", "name?", "role?", "description?", "client_info?"}`。
  - `dir` 和 hub 的工作区不一致时，返回 `400 wrong_dir`。`dir` 的比较和 v0 相同：Windows 写法和 `/mnt/c` 写法视为同一个目录。
  - 带 `name` 时：
    - 该成员已存在、vendor 相同、还没绑定会话，就接管它；
    - 已经绑定了，返回 `409 member_exists`。
  - 不带 `name` 时：成员 id 从 vendor 名开始取一个没被占用的。
  - 凭据缺失或不对，返回 `401 bad_sidebar_key`。
  - 返回值和 v0 相同：`{"member_id", "member_token", "operator_token", "room"}`。
  - 带 `code` 的旧路径照旧可用。
- **`POST /v1/rooms`**：从 v0.1 起也必须带 `x-xmuse-sidebar`，否则返回 `401 bad_sidebar_key`。
- **`GET /v1/rooms`**：新增。必须带 `x-xmuse-sidebar`，返回本 hub 的房间概况 `{"room", "members": [{id, vendor, role, online}]}`。用在侧栏"房间列表"里显示成员；房间列表本身从登记表读。
- **成员令牌**调用 join、rooms、`member_add`、`member_edit` 一律返回 `403`。所有 `xmuse_*` 工具都不提供加入或加人的能力。每次加入、添加成员，都要往 `#room` 写一条事件。

### 8.2 新增的 act（除特别说明外，只有操作令牌能用）

| act | 参数 | 返回 | 说明 |
|---|---|---|---|
| `member_add` | `vendor`（`claude` / `opencode` / `dsh`），`model?`，`role?`，`description?`，`name?` | `{"member_id"}` | 登记一个由 hub 起回合的成员，效果等同于 `xmuse agent add`，有消息时 hub 起它的回合。vendor 不支持返回 `400 bad_vendor` |
| `member_edit` | `member`，`role?`，`description?`，`model?` | `{"ok": true}` | 改角色、职责描述、模型 |
| `thread_new` | `id`（`#名字`），`members: [..]`，`title?` | `{"thread"}` | 建私有小群，用户自动在内。已存在返回 `409 thread_exists` |
| `thread_add` / `thread_remove` | `thread`，`member` | `{"ok": true}` | 只对私有小群有效；对公开群返回 `400 public_thread` |
| `share_mark` | `message_id`，`to?` | `{"ok": true}` | 把一条用户私信标成可分享：`to` 为空表示可以分享给任何人（见 8.6） |
| `wake_host` | — | `{"ok": true}` | 不等合并，立即唤醒主控（见 8.4） |

**成员令牌和 `xmuse_send`**：发到一个还不存在的 `#名字` 时，可以带 `members: [..]` 建私有小群，发送者和用户自动在内。成员只能退出自己所在的私有小群（工具 `xmuse_leave_thread {thread}`），不能拉别人进来。

### 8.3 小群（T2）

- **公开群**：`#名字` 第一次被发消息时自动建立，所有成员都在内，和 v0 相同。
- **私有群**：由 `thread_new` 或带 `members` 的 send 建立，只有名单里的成员和用户。
- 非成员对私有群：
  - 不投递，主动消息和被动消息都没有；
  - `xmuse_thread`、`xmuse_context` 读不到；
  - scope 为 `thread:#x` 的对齐条目，不进非成员的唤醒包。
- 视图里的 `threads[]` 加 `"private": bool`。
- 成员令牌的视图里，`threads` 和 `timeline` 只包含它所在的线程，`#room` 例外，一直包含。v0 里成员令牌能看到全部时间线，v0.1 收紧了。
- 操作令牌（用户）照旧能看到全部。
- 加人：沿用 v0 的处理，新成员下次被唤醒时，补发这个线程的对齐快照。

### 8.4 主控分派（T0）和结果标签

- **用户不点名的话交给主控**：用户（操作令牌，或者 via 为 cli）`say` 时：
  - 没有 `to`，或者 `to` 是 `#room`、公开群，并且没有点名任何人——只唤醒主控，其他人只收被动投递；
  - 响应里加 `"routed_to": "<主控 id>"`。

  点了名的消息照旧。
- **主控的身份说明**：主控的唤醒包里，身份段要写明它是主控，职责是：分析、拆分，用 handoff 派给合适的成员，验收；除非用户点名要它做，否则自己不写代码。这只是 xmuse 给它的角色说明，不改 agent 本身。
- **`xmuse_done` 新增 `outcome`**：取值 `completed | needs_alignment | blocked | progress`，不填视为 `completed`。消息上会记录：
  - `outcome`，最终生效的标签；
  - `outcome_by`：`"member"` 表示用执行者填的，`"hub"` 表示被 hub 改判过；
  - `outcome_reason`，改判理由，hub 改判时才有。
- **hub 改判**：
  - 执行者填了 `completed`，但 `declares` 里带 decision、assumption 或 question，并且 scope 不只是自己（scope 不是 `member:<自己>`），或者带了 `supersedes`——改判为 `needs_alignment`；
  - 证据核对没通过（见 8.5）——改判为 `blocked`。
- **唤醒主控的规则**：只对结果的接收人是主控时适用，也就是 `next` 是主控，或者这个结果对应主控派出的 handoff。
  - `needs_alignment`、`blocked`、`kind: question`：立即唤醒。
  - `progress`：不唤醒，只被动投递。
  - `completed`：按批次等。
    - "批次"是指主控派出、执行者还没交回的 handoff 集合。这些都交回了就唤醒；
    - 或者从第一条结果到达算起，满 `host_batch_max_s` 秒也唤醒，这是配置项，默认 600。
- **handoff 的 `notify`**：主控派活时可以给 handoff 加 `notify: "now"`，这个任务交回时立即唤醒主控。默认是 `"batch"`。
- **视图新增**：
  - 顶层 `host_wait`：

    ```json
    {"waiting_on": [{"member", "handoff_id", "since"}], "results_held": <条数>, "wake_at": <时间|null>}
    ```

  - `members[]` 加 `wakes_hour`；
  - `timeline[]` 加 `outcome`、`outcome_by`、`evidence_status`（只在 done 消息上有）。

### 8.5 证据（T5）

- **`xmuse_done` 新增 `evidence`**：格式 `[{"kind": "test" | "diff" | "command", "ref": "<命令或文件路径>", "result": "<声称的结果>"}]`，可以不填。
- **hub 核对**：拿这个回合的回合日志（transcript）来对：
  - `test` 和 `command`：这条命令在本回合里确实跑过，退出码或输出和声称的一致；
  - `diff`：这个文件在本回合里确实被写过。
- **结果**记在消息上：
  - `evidence_status`：`verified`（全部对上）、`unverified`（有对不上的）、`none`（没交证据）；
  - `evidence_problems: [..]`，列出对不上的项。
- **回合日志读不到时**（某家的格式不支持），记 `unverified`，`evidence_problems` 写 `"transcript unavailable"`，不改判结果标签。这种情况要在侧栏上能看出来。
- **审查者核验**：配置项 `review_gate`，默认 `true`。
  - 条件：房间里有 role 为 `reviewer` 的成员，执行者的 done 是 `next: none` 且 `completed`，执行者本身不是审查者。
  - 这时 hub 不直接收尾，而是发一条 handoff 给审查者，`kind: "review"`，附上原 done 和证据；审查者 done 之后，这个任务才算完成。
  - 测试场景按需要设 `review_gate: false`。

### 8.6 私信分享（T3）

- 用户私信给成员的内容默认不外传。这是正式使用的默认，实验场景可以在世界说明里写明"可以分享"。
- **工具 `xmuse_share {message_id, to, why}`**：只能分享自己收到的、来自用户的私信。
  - 这条消息已被用户 `share_mark` 过（`to` 为空，或者正好是这个 `to`）：直接投递；
  - 否则生成一条审批：`approvals[]`，`kind: "share"`，`id: "share:<n>"`，`summary` 写"<成员> 想把 #<消息 id> 分享给 <to>"，`detail` 是 `{message_id, to, why, excerpt}`。
- **审批选项**：
  - `once`：这一次；
  - `always`：这条消息以后分享给任何人都不再问；
  - `reject`：拒绝。
- **投递**：批准后，hub 把原文投给 `to`，`via: "shared"`，消息上带 `shared_from: {member, message_id}`。被拒绝时通知申请人。
- **建议**：只建议，不执行，先用规则。队友发 question，或者被分派任务时，如果文本里出现了某条用户私信里的键名或关键词（规则：长度大于等于 3 的标识符、数字常量名），就在收到那条私信的成员下次被唤醒时提示一句："你有一条用户私信（#id）可能与 <谁> 的问题有关，需要的话用 xmuse_share 申请"。不单独为提示唤醒它。

### 8.7 按职责路由（T4）

- **成员**发 `kind: question` 到公开群，并且没有点名任何人时：
  - hub 用问题文本去匹配各成员的 `description` 和 `role`，规则是关键词重叠打分；
  - 只唤醒得分最高、且分数大于 0 的 1 到 2 个成员；
  - 消息上记 `routed_to: [..]` 和 `route_reason`，其他人只收被动投递；
  - 全部没匹配上时照旧，唤醒所有人。
- **用户**不点名的话，按 8.4 交给主控，不走这条。
