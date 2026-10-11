# xmuse 假 hub（mock-hub）

按 `docs/design/XMUSE2-VIEW-API.zh.md`（约定 v0）实现的内存假 hub，无依赖，只监听 `127.0.0.1`。D2 真 hub 完成前，三家侧栏（Claude mod / OpenCode / dsh）都用它开发和测试。重启即清空。

## 启动

```bash
node tools/mock-hub/mock-hub.mjs --port 43117            # 空 hub，等插件 POST /v1/rooms 开房间
node tools/mock-hub/mock-hub.mjs --seed coord            # 预先建好房间，主控是 coord；stdout 打印一行 `seed {...}` 带它的令牌
node tools/mock-hub/mock-hub.mjs --state-dir /tmp/room   # 同时写 /tmp/room/hub.json = {"port":..}
```

参数：`--port`（默认 43117，0 = 随机）、`--seed <主控 id>`、`--state-dir <目录>`、`--invite-ttl <秒>`（默认 600）、`--quiet`。冒烟测试：`node tools/mock-hub/smoke.mjs`。

## 已实现的约定接口

`GET /v1/view`（长轮询，`version`，`since=0` 全量，无变化 `204`）、`GET /v1/timeline`、`POST /v1/act`（say / ack / approve / invite / remove / pause / resume / transfer_host / align）、`POST /v1/rooms`、`/v1/join`、`/v1/rebind`、`/v1/leave`；成员令牌与操作令牌分离（成员令牌只能 say、ack），绑定会话不符返回 `409 not_bound_session`；邀请码一次性、过期 `410`、用过 `409`、vendor 不符 `403`。操作令牌发的 `say` 记为 `from=human`、`via="<vendor> sidebar"`。`for_me` 和 `unread` 按读者（令牌所属成员）算；操作令牌的读者是它所属的成员。

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
