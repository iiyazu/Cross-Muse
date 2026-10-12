# xmuse dsh bundle 0.1.0（中继版）

dsh 桌面端原生插件（Host 插件，纯 ESM，不需要构建）。把 dsh 里的一个会话接成 xmuse 的前台 agent：
hub 里发给它的消息会自动出现在这个会话里，会话用 `xmuse_*` 工具回复。

## 它做什么

- 斜杠命令 `/xmuse`：
  - `bind <agent-id>`：先 `POST /v1/relay/bind {session_id}`，**hub 接受后**才在本地记录并启动该 agent 的中继循环
    （agent 不存在、不是前台 agent、hub 没起都会直接报错，本地不留任何记录）。每个 agent 只有一个会话：
    同一个 agent 再绑到别的会话，后一次生效（hub 在 `xmuse log` 里发一条通知，命令返回里写 `replaced: ...`）；
    同一会话改绑别的 agent，旧循环停止。
  - `unbind`：停止循环（游标保留），并 `POST /v1/relay/unbind` 清掉 hub 上的绑定；hub 没起时本地照样解绑，
    返回里会写 `hub NOT told`（hub 仍认为该会话是 agent，直到它被别的会话重绑或你重试）。
  - `status`：启动自检、hub 状态、工具来源，以及每个绑定的中继状态：`polling`（长轮询中）/ `idle` / `error` / `stopped`，
    游标、最近投递时间、最近错误。
  - `ping`：诊断用，往当前会话投递一条 `source.kind='xmuse'` 的 follow-up，不经过 hub。
- 中继循环（Host 侧，每个绑定 agent 一个）：
  1. 用该 agent 的 token 长轮询 hub `POST /v1/relay/poll {cursor, wait_s:25}`；
  2. 有消息时，把 hub 渲染好的 `text` 用与 ping 相同的路径投进绑定会话
     （`sessionController.resolveAgent` → `agent.followup(createUserMessage({source:{kind:'xmuse'}}))` → `sessions.flush`）；
  3. `flush` 成功后才推进游标，再 `POST /v1/relay/delivered {delivery_ids, session_id}`，成功后把游标写进 `bindings.json`；
  4. 出错（hub 没起、会话找不到、flush 失败、delivered 失败）按 1s→2s→…→30s 退避重试，不会丢消息；
     delivered 上报失败时只重试上报，不会把同一条文本投两次。
  - 使用 `node:http`（不用 fetch），所有回调 try/catch，循环自己吞掉异常，解绑 / 插件卸载时立即中止在途请求。
- 身份强制（hub 侧绑定）：hub 记着每个前台 agent 绑定的唯一 dsh 会话。绑定之后，该 agent 的 `/v1/tools/*`、
  `/v1/relay/poll`、`/v1/relay/delivered` 必须带请求头 `x-xmuse-session: <绑定的会话 id>`，否则返回
  `not_bound_session`（"this agent is bound to dsh session X; run /xmuse bind in the session that should act as <agent>"）。
  bundle 从**工具实际运行的会话**取这个 id，所以未绑定的会话、或别的会话读到 token 直接调 hub，都过不了。
  poll 收到 `not_bound_session`（说明别的会话重绑了这个 agent）会放弃本地绑定并停止循环。
  dsh 重启或 hub 数据库重置后，恢复的绑定会在第一次轮询前重新向 hub 声明。
  限度：同一 OS 用户的进程能读 token 文件，这挡不住有意的冒充，只是让误操作和即兴发挥的模型不能静默地以别人的身份行事，
  并留下痕迹（绑定通知；管理员 `xmuse send` 记为 `human (via cli)`）。
  还没有绑定的前台 agent（例如没装 bundle，只用 `xmuse tool --agent <id>`）不受限；一旦绑定，`xmuse tool` 会被拒绝。
- 原生模型工具：hub 的 9 个工具（不含协调者专用的 `xmuse_approve`）全部注册到每个会话（`agent/created` 时），`xmuse_whoami / send / inbox / ack / thread /
  leave_thread / context / done / share`。参数 schema 优先读 hub 状态目录的 `tools.json`（`xmuse init` 写出），读不到用 bundle 里的
  `tools.json` 副本（由 Python 测试对照 `tools.py` 保证一致）。调用时才查绑定；未绑定会提示让用户先 `/xmuse bind`。
  工具描述开头写明"只用于用户 `/xmuse bind` 过的会话"，减少未绑定会话乱调用。
- 持久化：绑定和游标都在 bundle 目录的 `bindings.json`（C 盘可写，`sync.sh` 不会覆盖）。0.0.x 的旧格式会自动读入。
- 配置只有 `state`（hub 状态目录，`cordis.patch.yml` 里；没有内置默认值，`xmuse doctor` 会打印应填的 `\\wsl.localhost\...` 路径）。插件读 `hub.json`（端口）、`tokens/<agent>`、`tools.json`；token 不进配置也不进日志。

## 安装 / 升级（用户自己操作）

1. 源码在本仓库 `integrations/dsh-bundle/`。运行 `bash sync.sh [目标目录]` 同步，默认目标是 Windows 用户目录下的
   `dsh-work\xmuse-bundle`（由 `%USERPROFILE%` 推导，或设 `XMUSE_WIN_HOME`；不含 test、node_modules；`bindings.json` 保留）。
2. 首次安装：dsh 桌面端 **插件 → 添加插件**，路径填 `%USERPROFILE%\dsh-work\xmuse-bundle`（`sync.sh` 最后会打印实际路径）（本地路径安装是链接方式）。
3. **升级插件包**：再跑一次 `sync.sh`，然后**重启 dsh**（链接方式不需要重装，但要重启才会加载新代码）。重启后绑定和游标自动恢复，
   循环自动重新开始轮询。
4. **升级 dsh 本身**：`package.json` 的 `peerDependencies` 声明支持 `>=0.2.0-rc.2 <0.3.0`，只在 0.2.0-rc.2 上实测过。dsh 升级后：
   - 重启 dsh，在会话里执行 `/xmuse status`，确认自检里的 services、hub state、tools 都正常；
   - 0.2.x 范围内有不兼容，或者升到 0.3 及以上：看自检和 dsh 日志里 `xmuse:` 开头的报错。插件用到的接口有 `commands`、`agents`、
     `sessions`、`tools`、`sessionController`（`index.js` 的 `inject`）。修好后改 `peerDependencies` 的范围，并重跑 `npm test`。

## 把试用工作区的 dsh-1 切到前台模式（用户自己操作，我没有执行）

hub 需要是带前台模式（`cc/desktop`）加中继端点（`dsh/bundle`）的版本，然后在 WSL 里：

```
xmuse --ws /mnt/c/Users/<你>/xmuse-desk agent add dsh-1 --vendor dsh --desktop
```

然后**重启 hub**（新端点和 `delivered` 字段需要新代码；`agent add` 会重写 AGENTS.md 里 dsh-1 的前台段落，token 不变）。
前台 agent 引擎不会唤醒，消息只通过中继（或 `xmuse watch --once`）送达。

## 端到端清单

前置：hub 已按上面重启；dsh 已重启并加载 0.1.0；工作区（如 `C:\Users\<你>\xmuse-desk`）里开一个 dsh **新会话**（Standard 模式）。

1. 在该会话输入 `/xmuse bind dsh-1`，然后 `/xmuse status`：应看到 `tools: 8 from hub state tools.json`，
   绑定表有 `<session> -> dsh-1`，`relay: polling`。（命令结果卡片要在会话有过第一条消息之后才会显示，这是 dsh UI 行为。）
   再确认：未绑定的另一个 dsh 会话里模型调用 `xmuse_*` 工具只会得到"This session is not bound"，
   终端 `xmuse tool --agent dsh-1 whoami` 返回 `not_bound_session`；`xmuse log` 里有 `dsh-1 is now bound to dsh session …` 的 hub 通知。
2. claude-d（桌面协调者）发：`xmuse_send(to="dsh-1", body="…一个小任务…", on_behalf_of="human")`
   或在终端 `xmuse send dsh-1 "…"`（后者在日志和唤醒文本里显示为 `human (via cli)`，
   claude-d 应先向你确认再执行重要请求）。
3. 几秒内 dsh 会话里出现一张"收到执行请求"卡片（`source.kind='xmuse'`），内容以 `[xmuse] Messages relayed by xmuse…` 开头，
   带 `<xmuse from=… thread=… kind=…>` 块；会话被唤醒并开始处理。`xmuse status` 里 dsh-1 的 `pending` 不再增加，
   消息状态为 `delivered`（不再是 queued）。
4. 会话完成后用 `xmuse_send(to="claude-d", …)` 回复（必要时 `xmuse_done`）。
5. claude-d 的 Monitor（`xmuse watch`）被唤醒，`xmuse_inbox` 读到 dsh-1 的回复。
6. 收尾检查：`/xmuse status` 里游标前进、`last delivery` 有时间、`last error` 为 `-`；`/xmuse unbind` 后再发一条消息，
   dsh 会话里**不应**再出现新卡片（消息留在 hub 里排队）。
7. 异常演练（可选）：停 hub → `/xmuse status` 应显示 `relay: error`，日志里有 `xmuse: relay dsh-1: …`；hub 恢复后自动继续，
   不需要重新绑定。

## 开发

```
cd integrations/dsh-bundle
node --check index.js
npm test        # = node --import ./test/register.mjs --test test/bundle.test.mjs
```

测试用 fake ctx、fake hub（本地 HTTP 服务），并通过 `test/hooks.mjs` 把 `@deepseek-ai/*` 三个导入指向 `test/stubs/`。
工具 schema 与 hub 的一致性由仓库根的 `tests/test_relay.py::test_dsh_bundle_tool_schemas_match_tools_py` 检查；改了
`hub/src/xmuse/tools.py` 要重新生成 `tools.json`（测试失败信息里有命令）。

## 已知不确定项

- 没有 `.d.ts`。`defineTool` 的 `parameters` 按 dsh-tools 的作者 DSL 写（属性级 `required: true`、object 必须显式
  `additionalProperties`），转换函数 `toDsl` 依据 asar 里的 `schema.js`，但 7 个工具的真实注册要在 dsh 里重启后确认（`/xmuse status`
  无报错、模型能看到工具）。
- `flush` 失败时 follow-up 可能已经进入会话队列，重试会再投一次（至少一次语义）；`delivered` 上报失败则不会重投。
- 会话被关闭后循环仍在跑：`resolveAgent` 失败就按退避重试，直到会话可恢复或用户 `unbind`。
