# xmuse dsh 侧栏（抽屉）0.2.0

dsh 桌面版里的 xmuse 侧栏：页面右缘一个可收起的抽屉，直连 hub 的视图模型
（`docs/design/XMUSE2-VIEW-API.zh.md` v0），成员、时间线、发消息、审批、
对齐条目、开房间和邀请都在这里做。在哪家侧栏开房间哪家就是主控；
其他成员的侧栏同样能看到全部信息、做审批。

同目录 `README.zh.md` 是中继版（`/xmuse bind` + `xmuse_*` 工具） 的说明，
中继功能原样保留；本文只讲侧栏。

## 它做什么

- **抽屉**：右缘蓝色竖标签 "xmuse"（有未读/@/待审批时变红并计数），点开是
  360px 抽屉：房间名 + 我的身份、成员列表（状态、在线、职责描述、未读、
  暂停）、话题/私聊筛选、时间线（按线程分组、`@我` 高亮、可加载更早、
  全部标已读）、发送框（选收件人 `#话题`/`dm`/`成员`）、审批队列
  （批准一次 / 总是 / 拒绝；除 shell 外还有对齐提案 kind=alignment 和被暂停成员 kind=resume，同样点这三个按钮）、对齐条目摘要（最近 20 条）、邀请表单
  （选 provider 和角色、填职责描述，显示邀请码和可复制的 `/xmuse join` 命令）。
- **未加入房间时**：抽屉只显示"开房间"（工作目录 + 房间名）和"加入"
  （邀请码）两个表单。
- **刷新**：前端长轮询 `GET /xmuse/view?since=<version>&wait=25`
  （宿主原样转发 hub `GET /v1/view`；无变化 hub 挂起，超时回 `204`，
  前端立即再问）。刷新按钮回到 `since=0` 拿全量。
- **安全**：成员令牌和操作令牌只存在宿主进程侧的 `sidebar.json`
  （bundle 目录，和 `bindings.json` 放一起，`sync.sh` 不覆盖、
  不入库）；浏览器拿不到任何令牌，所有 `Authorization` 头都是宿主加上去的。
  宿主路由与 `/api` 一样先过 `connection.requestRejection` 栅栏
  （`dsh web` 可能绑 `0.0.0.0`，局域网直连这些路由会被 403 挡掉；
  没有该服务时退化成只放行回环 Host）。
- **斜杠命令**（`index.js` 的 `/xmuse` 处理函数，旧 `bind` 原样兼容）：
  - `join <邀请码>`：调 hub `POST /v1/join`（vendor 固定 `dsh`，
    session 取当前会话），成功存侧栏令牌：`joined the room as "…"`.
    码一次性、10 分钟过期、vendor 不符都会把 hub 的错误原文报给用户
    （`410` 过期 / `409` 用过 / `403` vendor 不符）。
  - `room new <名字> [工作目录]`：调 hub `POST /v1/rooms`，
    工作目录缺省用插件配置 `roomDir`（再缺省用进程当前目录），
    调用者成为主控。hub 已有房间时会报 `room_exists`。
  - `leave`：调 hub `POST /v1/leave` 并清本地令牌；hub 挂了也清本地，
    返回里写明 `hub NOT told`。
  - `status` 里多一行 `sidebar: bound as "…" | no room … (routes at /xmuse/*)`。
- **文件**：`index.js`（+4KB：侧栏接线和三个子命令）、`sidebar-host.js`
  （新建：栅栏、转发、令牌存取、rooms/join/leave，可脱离 dsh 单测）、
  `client.js`（新建：前端单文件，无 import、无资产、DOM-only、
  `window.__ModuleLoader__.load`，由 `GET /xmuse/sidebar.js` 下发）。

## 安装 / 配置（用户自己操作）

1. 和中继版一样：`bash sync.sh [目标目录]`（默认 `%USERPROFILE%\dsh-work\xmuse-bundle`），
   同步内容不含 `test/`、`bindings.json`、`sidebar.json`（运行态保留）。
2. dsh 桌面端 **插件 → 添加插件**（本地路径安装是链接方式），然后**重启 dsh**
   （链接方式不用重装，但要重启才加载新代码；前端 `client.js` 也是重启后生效）。
3. 配置只有 `state`（hub 状态目录，`cordis.patch.yml` 里，和中继版同一个；
   没有内置默认值，`xmuse doctor` 会打印应填的 `\\wsl.localhost\…` 路径）。
   侧栏读 `hub.json`（端口）+ 自写的 `sidebar.json`（令牌）；`roomDir`
   可选（`room new` 省略工作目录时的缺省值）。
4. 升级：再跑一次 `sync.sh` + 重启 dsh。`sidebar.json` 跨重启保留，
   自检（`/xmuse status`）里 `sidebar: bound as "…"` 即恢复。

## 人工核对清单（用户在真实 dsh 里做，我不能装插件也不能重启）

对应 D0 报告 U9/U10，逐项在抽屉里确认：

1. **出现**：dsh 窗口右缘中部有蓝色竖标签 "xmuse"；点开右侧出现抽屉，
   关掉再刷新页面，收起/展开状态保持（localStorage）。
2. **两种模式**：header 里点 "mode: overlay" 切成 "mode: push"。
   - overlay：抽屉盖在页面上，输入框的发送按钮可点；
   - push：页面主体整体左移 360px，不错位。
3. **遮挡**：展开抽屉，分别打开会话页、设置页、模型选择器、权限弹层，
   记录抽屉在弹层之上还是之下；缩窄窗口到 800px 以下，抽屉仍可收起。
   不满足的记下来（决定要不要改成宿主 dock 位或只保留一种模式）。
4. **开房间**：抽屉里（或会话里 `/xmuse room new <名字>`）开房间，
   应看到房间名 + "我是 …"；`/xmuse status` 里 `sidebar: bound as "…"`。
5. **邀请→加入**：抽屉邀请表单选 provider/角色、填职责描述，
   生成邀请码和可复制命令；在目标会话执行 `/xmuse join <码>`，
   该成员在所有侧栏变"在线"；码再用一次应报错。
6. **收发**：任一侧栏发 `@某成员` 消息，`@我` 的那条高亮，
   tab 变红并计数；"全部标已读"后计数清零；"加载更早的"能翻出 50 条以前的消息。
7. **审批**：造一条审批（或等 hub 推），三个按钮分别点一次看效果：
   批完其他侧栏同步消失。
8. **外部访问**：同一局域网另一台机器访问 `http://<本机>:<dsh端口>/xmuse/status`
   应被拒绝（403/refused），回环访问正常。
9. 卸载：插件页移除即可；`sidebar.json` 留在 bundle 目录（删掉即清令牌）。

## 开发

```
cd integrations/dsh-bundle
node --check index.js sidebar-host.js client.js
npm test   # bundle.test.mjs（28，中继回归）+ sidebar.test.mjs（3，见下）
```

`sidebar.test.mjs` 起一个真 `tools/mock-hub` 子进程（随机端口，
`--state-dir` 读 `hub.json`），把 `sidebar.handle` 挂到本地 HTTP 服务上验证：
`rooms → view（since=0 全量 + 长轮询被写操作唤醒）→ act say（from=human via="dsh sidebar"）
→ timeline 分页 → approve → view 无泄漏（响应里无 `mt_/ot_`）→ 外部 Host 403
→ sidebar.js 下发 → 第二个成员 join → @主控 for_me → leave`；
另测 `/xmuse join | room new | leave` 三个子命令（含一次性码重用失败、
已有房间时 `room_exists` 透回）；另做 `client.js` 的语法 + 覆盖面断言
（单文件、无 import、无 innerHTML、含各表单/按钮标记）。

注意：本机 Windows 沙箱里 `node --test` 起子进程会被 `EPERM` 拦掉，
这是沙箱边界不是测试失败；沙箱里用
`node --import ./test/register.mjs test/<名>.test.mjs` 单文件直跑验证，
`npm test` 留给正常环境（CI/用户机器）。

## 已知不确定项

- 真实 dsh 宿主里的 `webServer.register` / `ctx.inject(['webServer'])`
  / `dsh.client` 前端加载三处都没在真实 dsh 里跑过（D0 只用假宿主验证），
  以清单第 1–3 项为准；跑不起来先看 dsh 日志里 `xmuse:` 开头的报错。
- `package.json` 的 `dsh.client: {inject: [], platform: web}` 和
  `exports["./client"]` 是照探针包抄的声明，真实文件名以
  `GET /xmuse/sidebar.js` 下发的 `client.js` 为准。
- 高风险审批（`risk: high`）在 D5 前当 `normal` 处理（约定 v0 要求）。
- 抽屉只在 dsh 桌面版 Web 页里；dsh 其它端（如果有）有没有扩展点未确认。
