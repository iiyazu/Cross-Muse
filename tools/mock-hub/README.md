# xmuse 假 hub（mock-hub）

按 `docs/design/XMUSE2-VIEW-API.zh.md`（约定 v0，加第 8 节 v0.1）实现的内存假 hub，无依赖，只监听 `127.0.0.1`。D2 真 hub 完成前，三家侧栏（Claude mod / OpenCode / dsh）都用它开发和测试。重启即清空。

## 启动

```bash
node tools/mock-hub/mock-hub.mjs --port 43117            # 空 hub，等插件 POST /v1/rooms 开房间
node tools/mock-hub/mock-hub.mjs --seed coord            # 预先建好房间，主控是 coord；stdout 打印一行 `seed {...}` 带它的令牌
node tools/mock-hub/mock-hub.mjs --state-dir /tmp/room   # 同时写 /tmp/room/hub.json = {"port":..}
```

参数：`--port`（默认 43117，0 = 随机）、`--seed <主控 id>`、`--state-dir <目录>`、`--invite-ttl <秒>`（默认 600）、`--quiet`。冒烟测试：`node tools/mock-hub/smoke.mjs`。

## 已实现的约定接口

`GET /v1/view`（长轮询，`version`，`since=0` 全量，无变化 `204`）、`GET /v1/timeline`、`POST /v1/act`（say / ack / approve / invite / remove / pause / resume / transfer_host / align）、`POST /v1/rooms`、`/v1/join`、`/v1/rebind`、`/v1/leave`；成员令牌与操作令牌分离（成员令牌只能 say、ack），绑定会话不符返回 `409 not_bound_session`；邀请码一次性、过期 `410`、用过 `409`、vendor 不符 `403`。操作令牌发的 `say` 记为 `from=human`、`via="<vendor> sidebar"`。`for_me` 和 `unread` 按读者（令牌所属成员）算；操作令牌的读者是它所属的成员。

### v0.1（约定第 8 节）

字段名和返回形状对齐真 hub（topo/integrate 上的 registry、threads、share、dispatch、evidence 几个模块）。

- **8.1 本机加入**：
  - 登记表默认关闭，以免测试写进真实用户目录。用 `--registry-dir <目录>`、`XMUSE_REGISTRY_DIR` 或 `--registry`（约定的默认目录）打开；
  - 打开后，启动时登记 `hubs.json`，必要时生成 `sidebar.key`，退出时注销；
  - 支持 `x-xmuse-sidebar` 头、不带 code 的 `POST /v1/join`、`GET /v1/rooms`。
- **8.2 新 act**：`member_add`、`member_edit`、`thread_new`、`thread_add`、`thread_remove`、`share_mark`、`wake_host`。成员令牌调用一律返回 403。
- **8.3 私有小群**：
  - 视图的 `threads[]` 带 `private`；
  - 成员令牌只看得到 `#room`、公开群和自己所在的线程；
  - 别人私有群的对齐条目和审批一并隐藏；
  - 非成员往私有群写，返回 `403 not_a_member`。
- **8.4 主控分派**：
  - 用户不点名的话路由给主控，返回 `routed_to`；
  - done 消息上有 `outcome`、`outcome_by`、`outcome_reason`，hub 会改判；
  - completed 按批次压住，needs_alignment 和 blocked 立即唤醒；
  - 视图有 `view.host_wait` 和 `members[].wakes_hour`。
- **8.5 证据**：done 消息上有 `evidence_status`、`evidence_problems`。证据核对不通过（日志读不到的除外）时，改判为 blocked。
- **8.6 分享**：
  - `approvals[]` 里有 `kind: "share"` 的项，成员令牌看不到；
  - 处理方式 once、always、reject；
  - 批准后投递一条 `via: "shared"`、带 `shared_from` 的消息。

v0.1 新增的注入口如下（用法和参数见 `mock-hub.mjs` 里各 case 的注释，`smoke.mjs` 有完整示例）：

| 注入口 | 作用 |
|---|---|
| `/_mock/send` | 以成员身份发消息，可带 `kind`、`mentions`、`members`（新建私有群）、`notify`。主控发 handoff 时会进入等待列表 |
| `/_mock/leave_thread` | 成员退出私有群 |
| `/_mock/done` | 成员发 done，可带 `next`、`outcome`、`evidence`、`evidence_status`、`evidence_problems` |
| `/_mock/share` | 成员申请分享用户私信，生成一条 share 审批 |
| `/_mock/host_wait` | 直接设置 `view.host_wait`，`{reset: true}` 清空 |

## 注入口（不在约定里，仅假 hub，不需要令牌）

```bash
H=http://127.0.0.1:43117
# 别人发来的 @（from 必须是已有成员，to 是成员 id、#话题或 dm:.. 线程）
curl -s -XPOST $H/_mock/say -d '{"from":"dsh-1","to":"coord","text":"@coord 请看一下 #d3"}'
curl -s -XPOST $H/_mock/say -d '{"from":"dsh-1","to":"#d3","text":"@claude-1 跑一下测试","mentions":["claude-1"]}'
# 审批请求
curl -s -XPOST $H/_mock/approval -d '{"member":"dsh-1","kind":"shell","summary":"npm install","detail":"cd wt && npm install","risk":"normal"}'
# 对齐条目
curl -s -XPOST $H/_mock/align -d '{"kind":"decision","scope":"module:sidebar","author":"coord","text":"按 v0"}'
# 直接建邀请码（免操作令牌）/ 加假成员 / 改状态
curl -s -XPOST $H/_mock/invite -d '{"vendor":"claude","role":"executor","description":"侧栏 D3","name":"claude-1"}'
curl -s -XPOST $H/_mock/member -d '{"id":"dsh-1","vendor":"dsh","role":"executor","description":"worker","status":"running"}'
curl -s -XPOST $H/_mock/status -d '{"member":"dsh-1","status":"idle"}'
# 查看全部内存状态 / 重置
curl -s $H/_mock/state ; curl -s -XPOST $H/_mock/reset
```

## 与约定不一致或自行补充的地方

- 约定未规定线程 id 生成：私聊 `dm:<按字典序排>`（如 `dm:coord+oc-d4`），话题原样（`#d4`）；`to` 为成员 id 时自动落到私聊线程。
- 操作令牌的 `me` 是 `{"kind":"operator","id":<所属成员 id>}`（约定只举了 member 的例子）。
- 系统事件（加入、审批结果）写进时间线，`kind:"system"`，`from:"hub"`，线程 `#room`。
- `POST /v1/rooms` 里没给 `member_id` 时默认 `host`。
- `GET /v1/view` 在 `since` 大于当前 version（hub 重启）时当作全量返回。
