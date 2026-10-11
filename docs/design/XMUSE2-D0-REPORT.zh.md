# xmuse 2 侧栏方案 D0 实测报告

2026-10-11，r7。对应设计稿 `docs/design/XMUSE2-DESKTOP.zh.md`（a1952a8）§4 的"需要实测/待实测"清单。只验证可行性，没有改仓库里的任何产品代码；探针源码在 `experiments/d0-probes/`。

约定：**能 / 不能 / 部分** 是结论；"证据"给命令和输出的关键几行；"没测到"单列；拿不准的标"未确认"。

## 0. 环境与版本（先看这个，后面多处依赖它）

| 项 | 值 |
|---|---|
| Windows | 11 Home 10.0.26200；WSL2 Ubuntu-24.04；`C:\Users\user\.wslconfig` 里 `networkingMode=nat`（**不是** mirrored） |
| Claude Code（桌面版自带，Windows 原生） | 2.1.295，`...\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.295\d2e29494ec83\claude.exe` |
| Claude Code（WSL） | 2.1.296，`~/.npm-global/bin/claude`；已登录 claude.ai |
| Claude Code（winget，Windows） | 2.1.123，没有 mod 接口（`plugin` 子命令里没有 test，也没有函数钩子） |
| OpenCode | **只有 WSL 里有**：`~/.opencode/bin/opencode` v2.0.26（旁边还有 v1.18.34 的 .bak）。Windows 侧没有用户安装的 opencode；只在 Open Design 应用里捆了一个 `0.0.0-codex/...` 的 opencode.exe，不是用户的 |
| dsh | `C:\Users\user\AppData\Local\Programs\DeepSeek Harness`，version 文件 `44.0.0`；用户 profile 在 `C:\Users\user\.dsh\profiles\desktop`，已有 dsh-claude-style / dsh-pixel-maid / xmuse-dsh-bundle |
| Windows Python | `py -0p`：3.14.6（在 Open Design 应用目录里）、3.11（太旧，hub 要 >=3.12） |
| Windows Node | v24.14.0 |

**两个会影响全盘的环境事实**：

1. WSL2 NAT 下，Windows 能用 `127.0.0.1` 访问 WSL 里的服务（localhost 转发），**WSL 里的程序不能用 `127.0.0.1` 访问 Windows 里的服务**。证据见 A1。
2. Windows 侧两个 `claude.exe`（2.1.123 和桌面版自带的 2.1.295）从命令行 `-p` 都是 `Not logged in · Please run /login`，`claude auth status` 为 `"loggedIn": false`；WSL 的 claude 是 `"loggedIn": true`。我是通过 WSL 互操作启动的 Windows 程序，**不能排除这是互操作环境造成的**（未确认），但 hub 迁到 Windows 原生后要直接启动 `claude.exe -p`，这一点必须在用户的 Windows 终端里确认（见手动核对 U11）。

---

## A. Claude Code mod

方法：探针 `experiments/d0-probes/claude-probe/`（`claude plugin validate` 通过：`√ Validation passed`；`claude plugin test`：4 pass 0 fail）。需要模型的运行用 WSL 的 2.1.296 + `--model claude-haiku-5-5`（每次 1–2 个极短回合）；不需要模型的（http、session id）用桌面版自带的 Windows 原生 2.1.295 跑。另用伪终端驱动了一次交互式 TUI。

校验器的几条硬规则（写 D3 时会碰到）：`$` 只能传给**文件顶层的函数声明**（不能传给闭包里的 const 箭头函数）；`$.state` 的键必须在 `types/index.d.ts` 里用 `interface PluginState` 声明并在 plugin.json 的 `types` 指到；`Markdown` 要用 `text` 属性，不是 children；模块里没有 `fs`/`process`，所有外部操作走 `$`。

### A1. `$.http.fetch` 访问 127.0.0.1 —— **能（有网络位置前提）**

证据（`claude-probe.log` 里记录的 `http.fetch`）：

```
Windows 原生 claude 2.1.295（-p）：
 http://127.0.0.1:18080/ping            -> status 200, 7 ms   (Windows 侧 node 服务)
 http://127.0.0.1:18081/ping-wsl        -> status 200, 8 ms   (WSL 侧 node 服务，经 localhost 转发)
 http://localhost:18080/ping-localhost  -> status 200, 3 ms
 POST http://127.0.0.1:18080/post（带 x-xmuse-session 头和 JSON 体）-> 200，服务端收到头和体；UA 为 Bun/1.4.3
WSL claude 2.1.296（-p 和交互 TUI）：
 http://127.0.0.1:18081/...             -> 200
 http://127.0.0.1:18080/ping-win-from-wsl -> HooksError: $.http.fetch(...) failed: ECONNREFUSED
```

网络矩阵（curl 实测）：WSL→WSL 通；WSL→Windows `127.0.0.1` **不通**（curl exit 7）；Windows→Windows 通；Windows→WSL `127.0.0.1`/`localhost` 通。没有任何组织网络策略拦截（没有设置 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`）。

结论与影响：mod 的 `$.http.fetch` 是由**运行 claude 的那个进程**发出的。Windows 桌面版/Windows 原生 claude 能访问 Windows 原生 hub；**在 WSL 里跑的 claude（用户现在 hub 适配器用的就是它）访问不到 Windows 原生 hub 的 127.0.0.1**。改法见"对设计稿的修改建议 #1"。

没测到：长轮询（25 s）在 `$.clock.every` 回调里的预算/超时限制（类型文档说 `$.http.fetch` 在读完 body 后才返回，没有流式，所以走长轮询而不是 SSE；预算上限未确认）；`https` 和组织的 web-fetch 策略。

### A2. `session.start` 里的 `$.clock.every` 在 `-p` 下是否运行 —— **能（-p 里实测了；交互里也实测了）**

证据：`-p` 会话（约 7 s）里 300 ms 的定时器记了 16 次 tick（`"ticks":14`、`"ticks":16` 在 `session.end` 记录里）；交互 TUI（1000 ms 周期）在 40 s 的会话里持续触发直到被杀。Windows 原生 `-p` 的短会话（"OK"回合约 0.5 s）里 tick 在 `session.end` 之后还触发了一次，无害。

没测到：数小时的长会话里的定时器稳定性；热重载时"旧环境的定时器被丢弃"的行为（文档说明，未实测）。

### A3. `$.prompt.submit` 语义 —— **能；不用 asUser 时模型读到固定的英文框架**

证据（`session.append` 钩子记录的、实际写入会话的那一行）：

```
origin: {"kind":"plugin","name":"xmuse-probe"}
text: "The xmuse-probe plugin sent a message:\nXMUSE-PUSH-TEST room=demo from=alice: ...\n\nThis is how Claude Code surfaces a prompt a plugin submits between turns — it starts this turn in the user's place. Address the message above."
```

- 模型照框架回答："The sentence that introduces this message is: "The xmuse-probe plugin sent a message:""。
- 加 `asUser: true`：写入的就是裸文本，`origin` 仍是 `{"kind":"plugin","name":"xmuse-probe","asUser":true}`（hook 和审计能分清来源），模型读不到来源。
- **空闲时起回合：交互式 TUI 实测通过**。会话空闲 14 s 后 `$.prompt.submit` 触发，终端出现 `› Prompt from the xmuse-probe plugin` 加正文，模型回 `PONG`（`turn.complete` 记录在 push 后约 1.3 s）。
- `-p` 下：在第一回合结束之前提交，会在第一回合后接着起第二回合，进程等它结束（输出里有两个 `result`）；**在最后一回合之后才提交（如 `/xmuse push` 命令里）会随进程退出被丢弃**。
- 调用方自己的 `prompt.submit` 钩子看不到它（文档说"通过除调用方外的所有钩子"，实测调用方的钩子没记录）。
- 回合进行中的提示：`$.session.append`（user 角色、isMeta）只在类型文档里确认，**没有实测**。

没测到：桌面版里 `$.prompt.submit` 起回合的表现（桌面版 Code 标签是 headless 会话，由宿主驱动；未确认）；回合进行中提交（文档：排队，等空闲后起新回合，不并入运行中的回合）。

### A4. 会话 id —— **能；与 transcript 文件名、hub 适配器记录的是同一个**

证据（同一次运行里四个来源逐字相同）：

```
$.session.id()                 = 37087a31-9b84-4f07-8c99-4e3494c956f1
classic.SessionStart.session_id= 37087a31-9b84-4f07-8c99-4e3494c956f1
stream-json 的 session_id       = 37087a31-9b84-4f07-8c99-4e3494c956f1
transcript_path                = /home/user/.claude/projects/-mnt-c-Users-user-dsh-work-d0-out/37087a31-....jsonl
```

类型文档：`$.session.id()` "the transcript file's name"。hub 的 claude 适配器 `hub/src/xmuse/hook.py:41` 记录的是 hook 载荷的 `session_id`，即上面第二行，所以 mod 的 `$.session.id()` 能直接作为 `join` 的 `session_id` 与 hub 现有记录对上。

注意：reference.md 说 `/clear` 会触发 `session.end`（`reason:'clear'`）且之后**没有** `session.start`，id 会变（`/clear` 新开 transcript）。mod 要每次调用时重读 `$.session.id()`，并监听 `session.end` 的 clear 做重新 join 或提示。**这一点未实测**。

### A5. `$.command.register` + `command.run` —— **能，`-p` 下也能**

证据：

```
$ claude -p "/xmuse join K7Q2-9F"        -> result: "xmuse-probe: xmuse join code=K7Q2-9F session=daf2fdcc-..."
command.run 钩子收到 args:"join K7Q2-9F", origin:{"kind":"sdk"}, presentation:{"isFullscreen":false,"columns":80}
交互 TUI 里敲 "/xmuse status"            -> 输出 "xmuse-probe: xmuse status ok session=3f056d32-... args=[]"，origin:{"kind":"composer"}
```

- 命令名就是 `/xmuse`（不带插件名前缀），输出行前面自动加 `xmuse-probe:`。
- 命令直接答话，**不起模型回合、不花钱**；`exitCode` 可设置，`-p` 的进程退出码跟着变。
- 命令输出（`<local-command-stdout>`）会写入 transcript，模型下一回合读得到——所以邀请码如果出现在命令输出里会进模型上下文，`join` 的返回文本只写"已绑定"，别回显码。
- 桌面版里 `/plugin install` 这条斜杠命令不可用（reference.md："a local session the desktop app starts for its Code tab answers that the command is not available there"），但 `claude plugin install/marketplace add` 这些**命令行子命令**存在（`claude plugin --help` 在 2.1.123 上列出了 install、marketplace、update、validate；2.1.295 上我实际用了 validate 和 test，reference.md 也提到 `claude plugin marketplace add <folder>`），装好的用户级插件在桌面版本地会话里也会加载，见 A7。

### A6. 侧栏 Pane、AbovePrompt、Input/Select 元素 —— **部分：树校验通过、TUI 实际停靠通过；桌面版的实际停靠没法在我这里验，列入手动核对**

`claude plugin test`（`probe.test.ts`，4 个用例全过）：

- Pane（`Select` + `Input` + 两个 `Button` + `Markdown` + `Text`）在 `terminal` 和 `desktop` 两个 surface 上都通过校验，`ui.select / ui.input / ui.press` 的处理函数都被调用并改了 `$.state`（presses 计数、room 名更新）；
- AbovePrompt 条在两个 surface 上通过；
- `mobile` 的元素表**没有 Input/Select**：它们被画成空 Box（不报错，但没有输入能力）；`vscode` 有 Input/Select 没有 `Client`。
- 桌面表的元素：Box、Text、Button、Input、Select、Svg、Link、Code、Markdown、Client（`Client` 是模块内再画同一批元素，不是网页）。**没有表格、标签页、树控件**：时间线要靠 Markdown 或 Text 列表，审批队列靠 Button 行。

真实 TUI（WSL 2.1.296，伪终端 200×50，全屏布局）：`$.ui.open` → `isPlaced:true`，Pane 的 `placement` 为 `dock`，`bodyColumns` 89；屏幕上能看到 `xmuse room: none`、`provider: Claude ▾`、`room: room name`、`[ Invite ] [ Approve ]`、`presses: 0`、Markdown 渲染的 `timeline / - @claude hello / - @dsh ok`。

限制（类型文档）：`$.ui.open` **非用户触发**（定时器、`session.start`）的 Pane 只在终端宽度 ≥144 列才摆出来（用户命令/按钮触发的任意宽度，docked 需 ≥110 列），否则 `{isPlaced:false}`；桌面版是否上报"能摆 Pane"取决于宿主，类型文档写着"older desktop 不摆"。`-p` 一律摆出。

没测到：Claude 桌面版 Code 标签里 Pane 的实际位置/宽度/是否可见（U1–U3）。

### A7. 桌面版 Code 标签的本地会话是否加载用户级安装的 mod —— **能（按文档；未在桌面版里实测）**

依据 `reference.md`：

- "Sharing a mod"：`/plugin install <mod> --marketplace <owner>/<repo>` 是终端的命令；"**A mod installed from a terminal at the user scope loads in that local session too, and its `ui.render` hooks draw for the `desktop` surface.**"
- "Developing one"：`CLAUDE_CODE_PLUGIN_DIRS`"names the same folders where no flag can be given (a session the desktop app or an SDK host starts)"，取自进程环境或 `~/.claude/settings.json` 的 `env` 块；监视热重载在无头会话里需要 `CLAUDE_CODE_PLUGIN_DIR_WATCH=1`。
- 桌面版 Code 标签的本地会话用的是 `C:\Users\user\.claude`（`installed_plugins.json` 里已有 user 范围的 feature-dev、frontend-design），所以终端里 `claude plugin marketplace add <路径>` + `claude plugin install xmuse@<marketplace>`（user 范围）后桌面版应当加载。
- 本会话（Claude 桌面版的当前会话）还有第三条路：把 mod 放进该会话的 mods 文件夹，引擎会弹"Enable hot reloading for this session?"，用户同意后加载。**我没有往那个文件夹写东西。**

---

## B. OpenCode

### B1. 版本

- WSL：`~/.opencode/bin/opencode --version` → `opencode v2.0.26`（另有 `opencode2` 包装脚本同样是 2.0.26，和 `opencode.v1.18.34.bak`）。
- Windows 侧：没有 `opencode` 在 PATH 上；用户目录 `C:\Users\user\.config\opencode\opencode.json`、`.local\share\opencode\opencode.db` 存在但没有对应可执行文件（可能是旧安装的残留，未确认）。Open Design 应用里捆了一个 `opencode.exe`（版本串 `0.0.0-codex/amr-image-runtime-fixes-202606100846`），不是用户的。
- 所以设计稿 §8"直接启动 `opencode.exe`"：**这台机器上没有 Windows 版 OpenCode**。

### B2. 插件 API —— **能做命令、toast、侧栏；能发 HTTP、跑定时器（TUI 插件，OpenCode 2.x 的新接口）**

重要：官方文档站（opencode.ai/docs/plugins、/docs/server）写的是 **v1 接口**（`@opencode-ai/plugin`，`tui.showToast` 这类），2.x 已换成另一套。本机 `~/.config/opencode/node_modules/@opencode-ai/plugin` 装的是 1.18.34（v1 类型），**对 2.0.26 不适用**（社区 issue 也说 v1 插件在 2.x 加载失败：`Invalid V2 TUI plugin module`）。2.x 的类型在 npm 包 `@opencode/plugin@2.0.26`（`latest` 标签），我拉下来读了 `dist/tui/context.d.ts`，并用真实 2.0.26 TUI 验证：

| 能力 | 2.x TUI 插件接口（`import { Plugin } from "@opencode/plugin/tui"`；`Plugin.define({id, setup(ctx)})`） | 实测 |
|---|---|---|
| 侧栏 | `ctx.ui.slot({ append: "sidebar.content", render })`；槽位表 `SlotMap`：`sidebar.content`、`sidebar.footer`、`prompt.footer(.status/.file)`、`session.composer.top`、`session.panel`、`home.footer`、`app`；另有 `ctx.ui.panel.open(name,{presentation:"panel"\|"fullscreen"})`（会话里的面板）、`ctx.ui.router.register(page)`（整页） | **实测通过**：会话页右侧栏出现 `xmuse room: demo / members: claude dsh opencode / session: ses_ed4da68c` |
| 斜杠命令（带参数） | `ctx.keymap.layer(() => ({ commands:[{ id, title, slash:{name:"xmuse", arguments:true}, run(input){} }] }))` | **实测通过**：在输入框敲 `/xmuse abc 123`，`run` 收到 `"abc 123"`（不含命令名），**没有**被当作 prompt 发给模型（API 里没有对应的 user 消息） |
| toast | `ctx.ui.toast.show({title,message,variant,duration,sessionID?})` | **实测通过**：5 s 后弹 `hello toast from plugin`，斜杠命令回调里弹出 `slash got: abc 123` |
| 弹窗/表单 | `ctx.ui.dialog.prompt/select/confirm/alert`（也可 `show(render)` 自定义） | 只读了类型，未实测 |
| HTTP | 插件跑在 TUI 的 Bun 进程里，全局 `fetch` 可用；`ctx.client` 是 OpenCode SDK 客户端 | **实测**：`fetch` 到 `http://127.0.0.1:18081/oc-tui` 成功 |
| 定时器 | `setInterval/setTimeout` 可用；`ctx.storage.store/memory` 可持久化 | **实测**：每 2 s 一次 tick 打到回显服务 |
| 事件订阅 | `ctx.data.on(type, handler)`、`ctx.data.listen` | 只读了类型 |

服务端插件（另一个入口 `server.ts`/`index.ts`，`import { Plugin } from "@opencode/plugin"`）：`ctx.command.transform(editor => editor.add({name, description, execute(inv)}))` 注册自定义命令，另有 `tool`、`event.subscribe`、`session`、`rpc` 等域。**没有实测**（服务端命令会出现在 `/api/command` 里，当前列表为 `init, review`）。

加载方式（实测）：TUI 插件写在 **`cli.json` 的 `"plugins": ["<目录或包>"]`**（schema https://opencode.ai/v2/cli.json，`~/.config/opencode/cli.json` 或 `$XDG_CONFIG_HOME/opencode/cli.json`），**不是** `opencode.json` 的 `plugin`；一个插件目录里 `tui.tsx` 是 TUI 入口、`server.ts`/`index.ts` 是服务端入口（`Host.resolve` 按 `server`、`tui`、`rpc` 找）。JSX 用 `/** @jsxImportSource @opentui/solid */`，`<box>`、`<text>` 是 OpenTUI 元素。踩到的坑：`import { define }` 会报 `Export named 'define' not found in module 'opentui:runtime-module:@opencode%2Fplugin%2Ftui'`，要 `import { Plugin }` 再 `Plugin.define`；加载失败只在 `--print-logs` 里有一行 WARN，界面没有提示。

### B3. TUI 与 serve 的关系 —— **能：用户的 TUI 可以连到 hub 起的 serve，hub 投递的消息会出现在该 TUI 会话里**

方法：在 WSL 里用独立 XDG 目录（`/tmp/ocx`）起 `opencode serve --hostname 127.0.0.1 --port 14096`（`OPENCODE_SERVER_PASSWORD` 随机，没打印），用 `/api/session` 建会话，同时用 pty 起 `opencode --server http://127.0.0.1:14096 --session <id>`（TUI；客户端也读 `OPENCODE_SERVER_PASSWORD`），12 s 后用 hub 同样的 API 投 prompt：

```
POST /api/session/ses_ed4da68c1ffeyM1B6lftPhBMV1/prompt
  {"text":"XMUSE-DELIVERY-TEST hello from hub","delivery":"queue","metadata":{"xmuse":{"turn":1}}}   -> 200
SSE /api/event 里的类型：server.connected, session.created, session.inbox.enqueued, session.inbox.delivered,
                         session.execution.started, session.execution.failed, user ...
TUI 屏幕文本：... d0 attach test ... XMUSE-DELIVERY-TEST hello from hub ... Session failed ... Model unavailable ...
```

投递的文字出现在了 TUI 里（模型调用失败是预期的：临时 XDG 里没有授权，所以**没有花钱**，只验证了"同一个会话、同一份收件箱"）。无密码访问返回 401。`opencode --help` 里 `--server <url>` 和 `--standalone` 并列（默认连"后台服务" `opencode service`，用户的那个）；hub 里 `adapters/opencode.py:482` 已经在生成 `opencode --server <base> --session <id>` 的 attach 命令，和实测一致。

细节：v2.0.26 的 `serve` 也带 web 界面（`serve --help`: "Start the v2 API and web server"）、`opencode pair` 能打印给浏览器/App 的一次性连接链接；浏览器界面**有没有插件扩展点**未确认（TUI 插件只在 TUI 里生效）。

### B4. 结论 —— **OpenCode 能做侧栏（TUI 里），不必降级成"只能当成员"**

- 侧栏：`sidebar.content` 槽 + `/xmuse` 斜杠命令 + toast + 对话框，足够做基本层和管理层；数据靠插件进程里的 `fetch` 轮询 hub（见网络前提 #1：OpenCode TUI 在 WSL，hub 在 Windows 的话 `127.0.0.1` 够不着）。
- 成员加入：同样可以用 `/xmuse join <码>`（TUI 插件命令）；也可以保留 MCP 工具 `xmuse_join`。
- 限制：只有 TUI 有侧栏；这台机器上没有 OpenCode 桌面应用，**桌面版/浏览器版有无扩展点未确认**；`sidebar.content` 只在会话页出现，不在首页（首页有 `home.footer`、`app` 槽）。

---

## C. dsh

### C1. 宿主侧、前端、请求路径

读了 `C:\Users\user\.dsh\local-plugins\dsh-pixel-maid\`、`profiles\desktop\node_modules\dsh-claude-style\`（含 `docs/architecture.md`）和 `integrations/dsh-bundle/`。

- **包形态**：`package.json` 的 `main`/`exports["."]` 指宿主侧（Node ESM，导出 `name`、`apply(ctx, config)`），`exports["./client"]` 指前端 `lib/client.js`；`"dsh": { "bundle": { "patch": "./cordis.patch.yml" }, "client": { "inject": [], "platform": "web" } }`。`cordis.patch.yml` 是 `- insert: [{id, name, config}]`，`config` 会作为 `apply` 的第二个参数。profile 的 `package.json` 里 `dependencies` 用 `link:` 指到插件目录，`dsh.profile.bundles` 列出名字（界面"插件 → 添加插件"会做这件事）。
- **宿主侧注册 HTTP 路由**：`ctx.inject(['webServer'], scope => scope.webServer.register({ kind:'prefix', path:'/xxx', handler:(req,res)=>{} }))`，返回一个撤销函数，放进 `ctx.effect` 里随插件卸载撤销。要通过 `inject()`（`dsh-claude-style/host/index.js` 的注释：直接取 `ctx.webServer` 在热重载重应用时会抛 `cannot get property "webServer" without inject`）。也可用 `ctx.get('agents')`、`ctx.get('connection')` 宽松读取服务。xmuse 现有包 `inject = ['commands','agents','sessions','tools','sessionController']`。
- **请求栅栏**：插件路由不在宿主 `/api` 的 Host/Origin 栅栏里，`dsh-claude-style` 的做法是先调 `ctx.get('connection').requestRejection(req)`（拒绝则回 401/403），没有该服务时回退成"只放行回环 Host、无跨站标记、Origin 与 Host 一致"。`dsh web` 绑 `0.0.0.0` 时局域网能直接访问这些路由，所以**必须**加栅栏（`dsh-drawer-probe` 里照做了，且验证了 Host 为外部域名时返回 403）。
- **前端怎么注入**：`lib/client.js` 是**单个文件、没有 import、没有资产 URL**，写成 `window.__ModuleLoader__.load({ id, factory: () => { var module={exports:{}}; ... exports.apply = function(ctx){...}; exports.inject=[]; exports.name=...; return module.exports } })`；`apply(ctx)` 里直接操作页面 DOM（pixel-maid：`document.body.appendChild(root)`，root 里 `attachShadow({mode:'closed'})`，`position:fixed` 固定在右下角），用 `ctx.effect(() => cleanup)` 注册卸载。大文件资源（字体、图片）走宿主路由，不能内联以外的方式。claude-style 的架构文档（D1、D11、D19）说明了这些约束，也提供了稳定的宿主定位点 `[data-slot="conversation.input.permission"]` 之类。
- **前端请求宿主路由**：普通 `fetch('/pixel-maid/status')`（同源相对路径，带会话 cookie；桌面壳经 `forwardWebRequest` 转到回环 Host）。

### C2. 宿主侧路由转发到 127.0.0.1 的 hub —— **能**

宿主侧是 Node（`node:http` 直接可用，没有沙箱限制；现有 xmuse 包就是用 `http.request({host:'127.0.0.1', port,...})` 长轮询 hub 的，令牌从 `tokens/<agent>` 读，不给浏览器）。实测：`dsh-drawer-probe/test/host-proxy.mjs` 用假宿主 ctx 加载 `lib/index.js`，用 Windows 原生 node 24 跑：

```
GET  /xmuse-probe/ping                       -> 200 {"ok":true,"hubUrl":"http://127.0.0.1:18080"}
GET  /xmuse-probe/view?since=0 (x-xmuse-session: sess-123) -> 200，hub 端日志收到 GET /v1/view?since=0，session 头原样转发
POST /xmuse-probe/act {"act":"say","text":"hi"}  -> 200，hub 端收到 POST /v1/act 和原样的体
GET  ... (Host: evil.example.com)            -> 403 refused
目标换成 WSL 里的服务 http://127.0.0.1:18081（Windows 宿主 -> WSL，localhost 转发） -> 同样 200
```

没测到：真实 dsh 宿主里的 `webServer.register` 和 `inject`（假宿主按 claude-style 的用法写的，未在真实 dsh 里加载，列入 U9）。

### C3. 抽屉探针

源码：`experiments/d0-probes/dsh-drawer-probe/`（`lib/index.js` 宿主侧路由转发；`lib/client.js` 右缘 "xmuse" 竖标签 + 340 px 抽屉，关闭的 shadow root，`z-index` 取很大，每 2 s 轮询 `/xmuse-probe/view`，输入框发 `POST /xmuse-probe/act`，"overlay/push" 切换：push 模式给 `<body>` 加 `margin-right:340px` 让出位置；展开状态记在 localStorage）。`node --check` 两个文件通过。**没有安装**。

安装、重启、通过标准见"用户手动核对清单"U9–U10。固定定位加 shadow root 会不会被宿主界面遮挡/遮住输入框，**需要用户在真实界面上看**。

---

## D. hub 在 Windows 原生运行的初步摸底

方法：把仓库的 `hub/ tests/ shim/ bin/ scripts/ templates/ skill/ integrations/ experiments/` 复制到 `C:\Users\user\dsh-work\d0\winhub\`（不含 `.git`、`.venv`、`archive`），用 `py -3.14 -m venv .venv`，`pip install -e hub pytest pytest-timeout`（依赖只有 `zstandard` 一个；hub 要求 Python>=3.12，Windows 上可用的是 3.14.6，**位置在 Open Design 应用的数据目录里，不是用户安装的 Python**；3.11 太旧）。`import xmuse` 成功，`xmuse` 包可编辑安装，hub 本身 5496 行 Python。没有改仓库里任何 hub 代码。

### D1. 测试结果

- `python -m pytest tests -q -x`：**第一个收集阶段就停**，`ERROR collecting tests/test_desktop.py`，`ModuleNotFoundError: No module named 'termios'`（`test_desktop.py` → `test_init_cli.py` → `import pty`）。
- 不带 `-x`（`--continue-on-collection-errors --timeout=60`，耗时 3 分 52 秒）：

```
69 failed, 224 passed, 1 skipped, 9 errors in 232.05s (0:03:52)
```

加上因收集失败而没跑的 38 个（`test_desktop` 25 + `test_init_cli` 7 + `test_trust` 6），总数约 337，和"337 个测试"吻合。**224 个已经直接通过**（db、mail、align、binding、metrics、memoryos 等核心逻辑在 Windows Python 上不用改就能跑）。

### D2. 失败按原因归类

| 原因 | 数量（个） | 文件 | 怎么判断的 |
|---|---|---|---|
| **POSIX 专属模块**：测试里 `import pty` / `fcntl`（`termios` 缺失） | 38（收集失败，未跑） | test_desktop 25、test_init_cli 7、test_trust 6 | 收集期 `ModuleNotFoundError: termios / fcntl` |
| **假 CLI 当可执行文件启动**：测试夹具里的 `fake_claude.py`/`fake_dsh.py`/`fake_opencode_serve.py` 靠 shebang 直接 exec，Windows 上 `[WinError 193] %1 不是有效的 Win32 应用程序`；引擎里 turn 一律 `failed`、`claude_calls()` 为空（`IndexError`）、或等待超时 | 59 | test_claude_engine 21、test_dsh_engine 19、test_wakepack 12、test_instances 2、test_presence 2、test_units 2、test_opencode_engine 1（其中 7 个是"timeout waiting for ..."） | 12 个失败文本里直接有 `WinError 193`；其余（`'failed' == 'succeeded'`、`IndexError`、超时）是同一个原因的后果，**逐个未确认**，但同一夹具、同一失败模式 |
| **外部程序缺失**：`WinError 2`（找不到 `python3`/`bash` 等；测试 setup 里启动 hook 脚本、MemoryOS） | 8 | test_presence 6（setup 错误）、test_experiments_run 2 | `FileNotFoundError: [WinError 2]`；具体缺哪个程序**未确认** |
| **环境变量清理砍掉 Windows 必需变量**：`env.clean_env()` 只保留白名单，不含 `SYSTEMROOT`，node 子进程直接崩溃 `Assertion failed: ncrypto::CSPRNG(nullptr, 0)`（stdout 空 → `JSONDecodeError`） | 4 | test_shim 4 | 单测复现，崩溃栈在 `node::InitializeOncePerProcess`；"缺 SYSTEMROOT"是根据 `clean_env` 白名单和 Node 在 Windows 上的已知行为推断，**未单独验证** |
| **路径/换行/编码语义**：转录路径用 `HOME` 而 Windows 用 `USERPROFILE`（测试写进了真实的 `C:\Users\<你>\.claude\projects\`，被拒 `PermissionError`）；doctor 的"shim 路径不是本 checkout 的"；`transcript_path` 断言；CLI 输出 `\r\n` 与中文 `你好` | 4 | test_transcript 1、test_doctor 1、test_units 1、test_foreground 1 | 逐个读了断言信息 |
| 合计 | 75 + 3 个收集失败的文件 = 78（= 69 failed + 9 errors） | | |

生产代码里需要改的点（`grep` 的计数）：POSIX 专属调用——`killpg`、`start_new_session`、`os.kill`、`signal.SIGTERM/SIGKILL`、`signal.signal` 等共 22 处，散布在 `cli.py(5)`、`adapters/dsh.py(4)`、`adapters/claude.py(4)`、`server.py(2)`、`adapters/opencode.py(2)`、`init.py(2)`、`peer.py(2)`、`doctor.py(1)`；`wsl.exe`/`to_win`/`/mnt/`/UNC 相关 44 处，在 `adapters/dsh.py(16)`、`adapters/claude.py(7)`、`host.py(6)`、`init.py(4)`、`adapters/base.py(4)`、`doctor.py(4)`、`cli.py(2)`、`hook.py(1)`。

### D3. D1 工作量估计

我的估计（凭上面的数字，不确定度大）：

| 工作 | 估计 |
|---|---|
| 进程管理换 Windows 做法（Job Object/`CREATE_NEW_PROCESS_GROUP`、`taskkill /T`、`CTRL_BREAK_EVENT`、父进程链判断，替换 22 处） | 1–1.5 天 |
| 去掉 `wsl.exe`/`to_win`/UNC（44 处，状态目录改 `%LOCALAPPDATA%`，hook 命令不再套 wsl.exe）；`env.clean_env` 保留 `SYSTEMROOT/USERPROFILE/APPDATA/TEMP` 等 | 1–1.5 天 |
| 测试夹具：fake CLI 改成 `sys.executable fake_x.py` 或 `.cmd` 包装；`pty`/`fcntl` 的 3 个文件改写或标 POSIX-only；路径/换行断言修正 | 1.5–2 天 |
| 三家端到端各一次（claude 登录、OpenCode 的位置、dsh）与排错 | 1.5–2 天 |
| Windows CI（GitHub Actions windows-latest） | 0.5 天 |

合计约 **5.5–7.5 个工作日**（一个人），不含安装程序（Python 运行时分发是个独立问题：需要 3.12+，Windows 现成的只有 Open Design 里捆的 3.14，不应依赖它）。核心逻辑层已经 224 通过，风险集中在进程管理和"各家 CLI 在 Windows 上的启动方式/登录状态"（见环境事实 #2）。

---

## 对设计稿的修改建议

按重要性排序：

1. **（§3 架构图、§8、§4.1/4.3）WSL NAT 下 Windows 原生 hub 对 WSL 里的 agent 不可达。** 用户的 Claude CLI（hub 适配器目前就用 WSL 的 claude）和 OpenCode（只装在 WSL）都在 WSL，它们的 `$.http.fetch` / 插件 `fetch` 访问不到 Windows 的 `127.0.0.1`。方案要三选一并写进设计稿：(a) 把 `.wslconfig` 改成 `networkingMode=mirrored`（改全局配置，用户决定；我没动）；(b) hub 额外监听 WSL 虚拟网卡地址（需要 Windows 防火墙规则和 token，削弱"只监听 127.0.0.1"）；(c) 把 agent 也迁到 Windows（OpenCode 的 Windows 版这台机器上没有，Windows 版 claude 命令行目前未登录）。另：§8 "直接启动 `claude.exe`、`opencode.exe`" 要加一句前提——Windows 上 `claude` 已登录、有 `opencode.exe`。
2. **（§4.3）OpenCode 能做完整侧栏，不需要降级成"不能当主控"。** 2.x 的 TUI 插件有 `sidebar.content` 槽、`/xmuse` 带参数斜杠命令、toast、对话框，实测通过；TUI 能连 hub 的 serve（`--server` + `OPENCODE_SERVER_PASSWORD`），投递会出现在用户那个 TUI 里。要改的是：写清楚是 **2.x 的 `@opencode/plugin/tui`、`cli.json` 的 `plugins` 配置**（文档站是旧接口，别照抄）；侧栏只在 TUI（桌面/网页版是否有扩展点未确认）；`join` 走 TUI 插件命令即可。
3. **（§4.1、§9 D3）Claude 侧栏要写成"用户触发后才一定出现"，并把桌面版是否摆放 Pane 列为 D3 的首个验收点。** 非用户触发的 `$.ui.open` 在终端宽度 <144 列时不摆；桌面版宿主是否上报"能摆 Pane"我没法验证。另外：桌面版不能用 `/plugin install`，要用命令行 `claude plugin marketplace add` + `claude plugin install`，或 `CLAUDE_CODE_PLUGIN_DIRS`（改用户设置）；`$ui` 元素只有文本/按钮/输入/选择/Markdown，没有表格和标签页，"时间线"要用 Markdown 渲染。
4. **（§4.1 表格）更准确的写法**：推送唤醒不用 `asUser`，模型读到的固定框架是 `The <插件名> plugin sent a message:\n<正文>\n\nThis is how Claude Code surfaces a prompt a plugin submits between turns — it starts this turn in the user's place. Address the message above.`（英文，正文里写明原始发送者）；`$.prompt.submit` 在 `-p` 里最后一回合之后提交会丢；`$.http.fetch` 没有流式，刷新用长轮询；会话 id 用 `$.session.id()`，与 hub 记录的 `session_id` 同一个，但 `/clear` 会换 id（需处理）。
5. **（§4.2）dsh 侧栏的写法补三点**：路由注册要走 `ctx.inject(['webServer'], ...)`；路由必须加 `connection.requestRejection` 栅栏（`dsh web` 可能绑 `0.0.0.0`）；前端是单文件 `__ModuleLoader__.load`，不能 import、不能带资产，资产走宿主路由。令牌留在宿主侧这一点可行（现有包已经这样）。
6. **（§8）工作量与前提**：补上 D1 估计（约 5.5–7.5 天）、POSIX/`wsl.exe` 点位数、`clean_env` 需要保留 Windows 系统变量、测试夹具需改成 `sys.executable` 启动；Python 3.12+ 的运行时要随安装程序带（Windows 现成的只有 Open Design 里的 3.14，不可靠）；"CLI 审批的 ctty 判断可以退役"之外，`start_new_session/killpg/os.kill/signal` 要整体换。
7. **（§10）** 两个待决问题用户已定，设计稿可更新：房间 = 一个工作目录；消息记为"用户（经 <provider> 侧栏）"。

---

## 用户手动核对清单

做这些之前先看 `experiments/d0-probes/README.zh.md`。探针都是只读/回显性质，不会改你的 claude/dsh/OpenCode 全局配置，除非步骤里明说。

**U1. Claude 桌面版：侧栏位置（A6，最关键）**
- 做法（任选一种，用完撤销）：①让桌面版里的一个 Claude 会话把 `experiments/d0-probes/claude-probe` 拷进**它自己的 mods 文件夹**（`C:\Users\user\.claude\dev-mods\<会话 id>\claude-probe\`），会弹出 "Enable hot reloading for this session?"，选 Enable（最不动全局配置）；②或在 `~/.claude/settings.json` 的 `env` 里临时加 `CLAUDE_CODE_PLUGIN_DIRS`=探针目录的绝对路径（以及 `CLAUDE_CODE_PLUGIN_DIR_WATCH=1`），开新的桌面版 Code 标签**本地**会话（改用户设置，由你决定）；③或先按 reference.md "Sharing a mod" 在探针目录加 `.claude-plugin/marketplace.json`（我没写），再终端 `claude plugin marketplace add <目录>`、`claude plugin install xmuse-probe@<marketplace>`。探针需要在 `claude-probe` 的同级建 `out/config.json`，内容 `{"openPane":true,"tickMs":1000}`（日志写到同级 `out/claude-probe.log`）。
- 通过标准：会话里看到一个标题为 "xmuse probe" 的窗格，停靠在会话右侧（或输入框上方），内含 provider 下拉、room 输入框、Invite/Approve 按钮、presses 计数和一段 Markdown 时间线；窗格里写的 `surface=desktop placement=dock|inline cols=N` 告诉你桌面版的实际摆放。记录 `placement` 和宽度。

**U2. Claude 桌面版：Input / Select / Button / AbovePrompt（A6）**
- 做法：在 U1 的窗格里，在 provider 下拉选 OpenCode；在 room 输入框输入 `demo-room` 回车；点 Invite、Approve（hotkey a）；看输入框上方有没有 `xmuse: 2 unread @ · 1 approval [Open]` 一行，点 Open。
- 通过标准：下拉值变化；`xmuse room:` 变成 `demo-room`；`presses:` 点 Invite 加 1、点 Approve 加 10；AbovePrompt 条显示；点 Open 能重新打开窗格。哪个元素不响应就记下来。

**U3. Claude 桌面版：`/xmuse` 命令（A5）**
- 做法：输入框敲 `/xmuse join K7Q2`，再 `/xmuse status`。
- 通过标准：输入框的斜杠菜单里能补全 `/xmuse`；回显 `xmuse-probe: xmuse join code=K7Q2 session=<id>`；不起模型回合。

**U4. Claude 桌面版：插件唤醒空闲会话（A3）**
- 做法：会话空闲时敲 `/xmuse push hello`。
- 通过标准：随后自动起一个回合，用户消息位置显示"来自 xmuse-probe 插件"的消息（或类似），模型能读到 `The xmuse-probe plugin sent a message: ...`。记录桌面版里它长什么样。

**U5. Claude 桌面版：mod 能不能访问 Windows 侧 hub（A1）**
- 做法：在另一个终端 `node experiments/d0-probes/http-echo-server.js 18080 127.0.0.1 out\http-server-win.log`（Windows node）；`out/config.json` 改成 `{"urls":["http://127.0.0.1:18080/ping"],"openPane":true}`，重载或开新会话。
- 通过标准：`out/claude-probe.log` 里有 `"ev":"http.fetch","status":200`，回显服务的日志里有请求和 `x-xmuse-session`。

**U6. Claude 桌面版：会话 id 对得上（A4）**
- 做法：看 `out/claude-probe.log` 里 `session.start` 的 `sessionId`，与 `C:\Users\user\.claude\projects\<项目目录>\` 下该会话 transcript 文件名比较；在会话里 `/clear` 之后再 `/xmuse status`。
- 通过标准：两者完全相同；`/clear` 后的 id 是新的（确认设计稿里要处理"换 id"）。

**U7. OpenCode：TUI 侧栏、斜杠命令、toast（B2）**
- 做法（用临时目录，不碰你的全局配置）：WSL 里 `mkdir -p /tmp/ocx/config/opencode /tmp/ocprobe && cp experiments/d0-probes/opencode-probe/* /tmp/ocprobe/`；写 `/tmp/ocx/config/opencode/cli.json` = `{"$schema":"https://opencode.ai/v2/cli.json","plugins":["/tmp/ocprobe"]}`；`XDG_CONFIG_HOME=/tmp/ocx/config opencode --standalone`，进入任一会话，敲 `/xmuse hi`。
- 通过标准：会话页右侧栏出现 `xmuse room: demo / members: ... / session: ses_...`；约 5 秒后弹出 `hello toast from plugin`；`/xmuse hi` 弹出 `slash got: hi`，且不作为 prompt 发给模型。
- 想要永久装：把同样的 `plugins` 项加进 `~/.config/opencode/cli.json`（改用户配置，由你决定）。

**U8. OpenCode：你自己的 TUI 连到 hub 的 serve（B3）**
- 做法：用 `xmuse` 现有 attach 命令（`xmuse attach <opencode agent>` 打印 `opencode --server <url> --session <id>`），在终端里运行（需要 `OPENCODE_SERVER_PASSWORD` 为该实例的密码，hub 状态目录 `oc/<agent>/oc.pass`）；然后 `xmuse send <agent> "hi"`。
- 通过标准：你的 TUI 里立刻出现 hub 投递的消息（和我用 API 投递看到的一样）。

**U9. dsh：抽屉探针（C3，最关键）**
- 做法：①把 `experiments/d0-probes/dsh-drawer-probe` 复制到 `C:\Users\user\dsh-work\dsh-drawer-probe`（不含 node_modules）；②在回显服务端口 18080 起 `node http-echo-server.js 18080 127.0.0.1 out\h.log`（或把 `cordis.patch.yml` 里的 `hubUrl` 改成别的）；③dsh 桌面端 **插件 → 添加插件**，路径填 `C:\Users\user\dsh-work\dsh-drawer-probe`；④**重启 dsh**。
- 通过标准：dsh 窗口右缘中部出现蓝色竖标签 "xmuse"；点开后右侧出现 340 px 抽屉，每 2 秒刷新一次 `HTTP 200 {"ok":true,"pong":true,...}` 和视口大小；输入框输入文字回车后显示 `sent -> {...}`，回显服务日志里有 `POST /v1/act`；点 collapse 能收起，刷新页面后保持收起/展开状态。

**U10. dsh：抽屉有没有被遮挡 / 遮挡了什么（C3）**
- 做法：在 U9 的基础上：展开抽屉，分别打开会话页、设置页、模型选择器、权限弹层；点 header 里的 "mode: overlay" 切成 "mode: push"；缩窄窗口。
- 通过标准：抽屉在弹层之上或之下（记录哪个）；overlay 模式不应让输入框的发送按钮不可点；push 模式下页面主体整体左移不错位；缩窄到 800 px 以下时抽屉仍可收起。不满足的记下来，这决定侧栏要不要改成"挤出空间"或做成宿主的 dock 标签。卸载只要在"插件"页移除。

**U11. Windows 命令行 claude 是否已登录（环境事实 #2）**
- 做法：在 Windows 终端（不是 WSL）运行 `"C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe\claude.exe" auth status`。
- 通过标准：`"loggedIn": true`。如果是 false，hub 迁到 Windows 原生后要直接起 `claude.exe -p` 就需要先在 Windows 登录；我从 WSL 互操作启动时是 false，可能是互操作的假象。

**U12（决策项，不是核对）WSL 网络**：Windows 原生 hub 要被 WSL 里的 claude/OpenCode 访问，需要决定 `networkingMode=mirrored`（改 `.wslconfig`）还是别的方案（见建议 #1）。

---

## 实测过程中留下的痕迹（供清理）

- WSL `~/.claude/projects/-home-user-dev-xmuse2-rc/3f056d32-595a-4e16-ba30-3206b1431f8a.jsonl`（交互 TUI 实测，1 个 haiku 回合）和 `-mnt-c-Users-user-dsh-work-d0-out/` 下几个 `-p` 会话的 transcript；Windows `C:\Users\user\.claude\projects\C--Users-user-dsh-work-d0-out\`（Windows claude 未登录的那次）。没有删除。
- 测试用的 `d0-winhttp`、`d0-wslhttp` 用户级 systemd 单元（回显服务，端口 18080/18081）已在收尾时停止；OpenCode 的临时 serve（14096）已停止；`/tmp/ocx`、`/tmp/ocprobe` 已删除。
- `C:\Users\user\dsh-work\d0\` 里有全部中间文件（含 `winhub\` 复制品和 venv，约 80 MB 以上，不入库）。
