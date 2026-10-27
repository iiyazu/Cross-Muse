# xmuse 面板（Claude Code mod，T8）

xmuse 2 的协作界面：Claude 桌面会话当主控，其余 agent 是助手，协作室显示在 Claude Code 右侧的面板里。

- **左侧会话栏**（IM 式，可折叠成只剩头像；面板窄时自动折叠）：最上面是大群（#room），下面每位成员一个头像，点开就是你和它的私聊（`dm:` 线程，第一条消息时由 hub 建立，只有你们两个看得到），最后是"全部"（所有线程，含成员之间的私聊）。每项带未读数。
- **成员菜单**：在私聊里点右上角"操作 ▾"：头像、状态、执行耗时、排队数；上下文进度条和"压缩"；模型名（点开可换，下一轮生效）；停止、暂停/恢复、移出房间（点两次确认）。
- **信息流**（最新在上）：消息气泡（回复、设为决定、复制、撤回）；执行中成员的草稿气泡；新到的消息逐段显现。非消息信息分三层：错误、警告、受阻的完成报告用彩色框；正常完成报告用浅底加色条；命令、批准、加入等用居中一行淡色小字。
- **审批卡片**固定在顶部；**执行条**可以"■ 停止"；输入区可以 @ 补全成员；顶部可以添加助手（OpenCode / dsh / agy），开关自动叫醒。
- 没有房间时显示"开房间"按钮；加入过的房间在电脑重启后会自动拉起 hub。

## 安装

在终端会话的提示符里输入（桌面 App 的 Code 页签不支持这条命令；在终端里装成 user 作用域后，桌面会话也会加载）：

```
/plugin install xmuse --marketplace <本目录的路径或 git 地址>
```

安装前检查：`claude plugin validate <本目录>`。

## 本机信息从哪里来（代码里没有任何本机路径）

- **登记目录**（hubs.json、sidebar.key、install.json）：第一次用 `wsl.exe -e sh -s` 问默认发行版
  `$WSL_DISTRO_NAME` 和 `${XDG_STATE_HOME:-$HOME/.local/state}/xmuse`（与 hub 的 `registry.py` 同一规则），
  拼成 `//wsl.localhost/<发行版><目录>` 存进插件的 store；之后只要这个目录读得到就直接用。
- **hub 的 Python、发行版、PATH**：每个 hub 启动时写进登记目录的 `install.json`。面板拉起 hub 时用它；
  新机器上还没有这个文件时，提示先手动启动一次 hub。
- **令牌**：操作令牌和成员令牌存在插件的 store。hub 重启换了端口时只换地址、保留令牌；桌面 App 重启换了会话时，
  用成员令牌 `/v1/rebind` 把成员转到新会话。
- **头像**：登记目录下的 `avatars/<成员 id>.png`，或厂商的 `claude.png`、`opencode.png`、`google.png`
  （也认 `gemini.png`、`agy.png`）、`deepseek.png`（也认 `dsh.png`）。PNG 会嵌进 SVG，单个文件要小于约 60KB
  （96×96 足够）；太大时面板会提示一次。

## 开房间、自动拉起 hub

1. 查 hubs.json 里有没有服务这个目录、而且连得上的 hub（重启后残留的旧条目会被跳过）。
2. 没有就 `wsl.exe -d <发行版> -e bash -l -s`，脚本从标准输入传入（`hooks/logic.ts` 的 `hubStartScript`）：
   开房间时先 `xmuse init <目录>`；然后用 `systemd-run --user` 起临时单元 `xmuse-hub-<目录哈希>-<时间>`，
   单元里直接跑 `xmuse hub run`（XMUSE_STATE 指向房间状态目录，输出追加到它的 `logs/hub.log`）。
   wsl.exe 一返回，它留下的后台进程就会被杀掉，所以不用 setsid/nohup；没有 systemd 用户实例时才退回 setsid。
   `xmuse init` 会在项目里写 `.xmuse.json`、改 CLAUDE.md 等（hub 自己的规矩）。
3. 最多等 60 秒（hub 启动时要先检查各家模型），再用侧栏密钥 `POST /v1/rooms` 建房，本会话成为成员和主控。
4. 回包 `brief_missing` 为真时，面板提示"还没有项目简介"，按钮让 Claude 读项目写简介，并调用 `xmuse_brief` 保存。

**自动拉起**：加入过的房间目录记在 store 里。重启电脑后打开面板，如果这个目录的 hub 没在运行，面板会自动启动一次
（只跑 hub，不 init，也不建房），然后正常加入。失败时红色错误卡片上有"启动 hub"按钮。

## 压缩

- 成员卡片的上下文条：超过 40 万变黄，超过 50 万（hub 的自动压缩线）变红。压缩后到下次回复前显示"已压缩"。
- OpenCode 成员空闲时可以"压缩"：由 hub 执行（`act compact`），压缩指令也由 hub 生成，完成后在私聊里通知。
- 本会话的 Claude 也可以"压缩"（`$.session.compact`）。不管是按钮、`/compact` 还是自动压缩，`session.compact`
  钩子都会从 `GET /v1/compact_instructions` 取 hub 的压缩要求，接在用户自己的 `/compact` 文字后面（冲突时以用户的为准）；
  最多等 5 秒，hub 没响应就按原样压缩。
- dsh 和 agy 没有可由外部触发的压缩，不显示按钮。

## 注册的工具和命令

- `mcp__xmuse__xmuse_send`：以本会话成员身份发消息。
- `mcp__xmuse__xmuse_brief`：保存项目简介（参数 `text`）。
- `/xmuse`：打开面板。

## 开发

- `hooks/dev.ts` 是开发开关。本目录里 `DEV` 为 `false`，路径全空。开发时把本目录复制到会话的 mod 目录
  （`~/.claude/dev-mods/<会话 id>/xmuse/`）热加载，那里另放一份 `dev.ts`：`DEV = true`，并填上本机文件
  （房间目录覆盖、加载标记、焦点诊断、头像目录）。改完再把除 `dev.ts` 以外的文件拷回本目录。
- 自测：`node hooks/logic.selftest.mjs`，输出 `ok` 和 `ok2` 即通过（Node 22.6 以上，导入时去掉类型）。
- 类型检查：引擎加载过本插件后会在 `.claude-plugin/types/` 写入类型（已加入 .gitignore），之后在本目录
  `tsc -p . --noEmit`。
- 约束：`$` 只能传给本文件顶层声明的函数；纯逻辑放在 `hooks/logic.ts`（不用 `$`，可单独测试）。
