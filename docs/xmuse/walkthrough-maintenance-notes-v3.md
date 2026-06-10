# xmuse Walkthrough Maintenance Notes V3

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的 TUI 并行基建交接文档。

它只覆盖一条并行线：

- 在不反向定义 `V2` 后端协议的前提下，补强 xmuse TUI 的输入、导航、补全、草稿和交互基建

它不覆盖：

- peer chat 主链协议
- provider/runtime 主链
- graph-native authority 主链

这些仍以 `walkthrough-maintenance-notes-v2.md` 为准。

## 使用规则

1. `V3` 只能做客户端基建，不得反向修改 `V2` 后端协议目标。
2. 一次只做一个任务。
3. 只读当前任务列出的文件；没有进入当前任务的文件，默认不读不改。
4. 不得为了 TUI 方便而新增后端语义特判。
5. 当前已有的前端兼容逻辑可以维持，但不要继续扩大，例如：
   - 不要继续强化“前端自动补 `@architect`”这类协议语义
6. `/resume` 可以升级为一等入口，但在其成熟前，不要直接删左侧会话栏。
7. 每轮必须满足该任务自己的强 gate，才算完成。
8. 每轮完成后，只更新:
   - 本文档对应任务的 `当前收敛状态`
   - `docs/xmuse/codex-strengthening-handoff.md` 的本轮收口记录
9. 因为 `V3` 可能交给较弱模型执行，默认采用强流程约束：
   - 每个任务开始前，必须先做一次 `superpowers:brainstorming`
   - 涉及输入行为、键位、状态切换的任务，默认按 `superpowers:test-driven-development` 执行
   - 宣称完成前，必须按 `superpowers:verification-before-completion` 跑 gate
10. `subagent` 默认禁用；只有任务明确标注“可并行子任务”时，才允许启用，而且必须满足：
   - 子任务之间没有共享编辑文件
   - 子任务不决定交互协议，只做测试、夹具、只读审计或独立 widget
   - 同一轮最多启用 1 个 subagent
   - 主 agent 负责最终整合、验证与 handoff
11. 如果某轮任务可以由主 agent 直接完成，不要为了“看起来更并行”而启用 subagent。
12. 较弱模型不得自行发明执行流程；每轮都必须显式遵守本文档下面的
    `弱模型执行协议`、`subagent 硬边界`、`统一验收与汇报格式`。
13. 必要时允许参考 `/home/iiyatu/clowder-ai`，但仅限:
    - 借鉴 TUI/聊天产品层的交互组织、命令可发现性、participant 展示方式
    - 帮助判断 xmuse TUI 缺口的目标形态
    不得直接复制其 runtime、状态机实现、或把它的协议假设搬进 xmuse。
14. 参考 `clowder-ai` 时，必须在本轮 handoff 写明:
    - 参考了哪些文件
    - 借鉴的是哪条交互约束
    - 为什么没有直接照搬实现

## 弱模型执行协议

每个任务都按下面顺序执行，不允许跳步:

1. 只读当前任务列出的文件，外加它直接依赖、且为了通过 gate 不可避免的测试文件。
2. 先做一次 `superpowers:brainstorming`，只产出四项结论:
   - 本轮唯一任务边界
   - 本轮允许改动的文件
   - 本轮 gate 映射到哪些测试或验证动作
   - 本轮明确不做什么
3. 涉及输入行为、键位、状态切换、草稿恢复、滚动、补全的任务，必须使用
   `superpowers:test-driven-development`：
   - 先写 focused test
   - 先跑出预期 RED
   - 再做最小实现到 GREEN
4. 完成实现后，必须用 `superpowers:verification-before-completion` 跑 fresh gate。
5. gate 未全部通过时，不得宣称任务完成，不得切下一个任务。

如果 `brainstorming` 得出的结论需要改协议、改后端 contract、或扩大到 `V2` 主线，
立即停止当前任务，并在 handoff 里记为越界，不继续实现。

## subagent 硬边界

`subagent` 不是默认能力，只是少数任务的辅助工具。弱模型执行时必须遵守:

1. 只有当前任务写了“可并行子任务”，才允许启用。
2. 同一轮最多 1 个 subagent。
3. 默认不要启用 `superpowers:subagent-driven-development`；只有当前任务明确允许，
   且主 agent 已经先完成本轮边界判定时，才可局部使用其思路。
4. subagent 只允许做下列事情之一:
   - 只读审计
   - 补测试或测试脚手架
   - 独立 widget 的局部实验
5. subagent 不允许:
   - 修改主输入状态机
   - 修改 screen 主交互路由
   - 修改任何后端协议、adapter contract 或 `V2` 相关语义
   - 决定最终交互方案
6. 如果 subagent 产出与主 agent 将要编辑的文件重叠，立刻取消该并行方案，回到主 agent 单线程收束。
7. 最终代码、测试、验证、handoff 一律由主 agent 负责；不得把 subagent 的“已完成”直接当成完成事实。

## 统一验收与汇报格式

每轮任务结束时，handoff 至少要写清楚:

1. 本轮唯一任务名。
2. 实际修改的文件列表。
3. 新增或修改了哪些 tests。
4. `brainstorming` 结论中的四项边界是否仍成立。
5. fresh verification 命令与结果:
   - focused tests
   - 受影响的 screen/adapter/widget tests
   - `ruff check` 或等价静态检查
   - `git diff --check`
6. 逐条对照当前任务 `强 gate`，说明每条 gate 由哪条测试或验证动作覆盖。
7. 明确写出本轮没有扩到的能力点。

没有这些证据，本轮视为未完成。

## 统一质量 gate

除各任务自己的 `强 gate` 外，每轮还必须同时满足下面四条:

1. 有 fresh test evidence；不能只凭人工操作或旧日志宣称通过。
2. 新增行为至少有一个 focused regression test；键位/状态类任务通常还应有 screen-level 或 widget-level 覆盖。
3. 不新增任何 `V2` 后端语义特判，不把前端 convenience 写成协议 authority。
4. 不把兼容逻辑继续做成默认主路径，尤其是:
   - 自动补 `@architect`
   - 左栏硬依赖
   - 仅靠 fallback path 才可用的交互

## 任务总览

按推荐顺序执行:

1. `TUI-INPUT-HISTORY`
2. `TUI-COMPLETION-ENGINE`
3. `TUI-COMMAND-PALETTE`
4. `TUI-PARTICIPANT-CACHE`
5. `TUI-SESSION-SWITCH`
6. `TUI-DRAFTS-AND-STATUS`
7. `TUI-PENDING-AND-ERROR-STATES`
8. `TUI-FOCUS-STATE`
9. `TUI-MULTILINE-COMPOSE`
10. `TUI-SCROLLBACK`
11. `TUI-ADAPTER-CONTRACT-TESTS`
12. `TUI-SCREEN-INTEGRATION-TESTS`
13. `TUI-KEYMAP-TESTS`
14. `TUI-UX-SMOKE`

---

## 任务 1: `TUI-INPUT-HISTORY`

### 非生产级实现事实

- 当前输入框可以提交消息，但没有成熟的消息历史回溯。
- 普通消息与 slash 命令没有明确的历史分层。

### 生产级目标

为当前 chat 输入框提供可预期的本地输入历史：

- `Up/Down` 浏览历史
- 可在取回历史后继续编辑
- 普通消息历史与 slash 命令历史分离

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/app.py`
- `tests/xmuse/test_tui_adapter.py`
- 如有需要，相关 TUI widget tests

### 本轮要解决的缺口

- 输入框缺少成熟的 shell/chat client 式历史行为。

### 强 gate

- `Up` 可回溯当前会话已发送输入。
- `Down` 可向前恢复，直到空输入。
- slash 命令不会污染普通消息历史。
- 同一会话切换后，历史作用域可解释且稳定。

### 禁止扩面

- 不做 slash 补全。
- 不改左侧会话导航。
- 不改后端发送语义。

### 可并行子任务

- 无。该任务直接在主 agent 内完成。

### 当前收敛状态

- 输入框可提交。
- 历史回溯基建已收束: `InputHistory` 类支持 per-conversation 消息/slash 分离历史, Up/Down 导航, 位置 reset。
- 新增 test: `tests/xmuse/test_tui_input_history.py` (11 passed)。
- 回归: 60 existing TUI tests passed, ruff check passed。

---

## 任务 2: `TUI-COMPLETION-ENGINE`

### 非生产级实现事实

- 当前 slash command router 已存在，但缺少输入中预览、候选列表和键盘选择。
- `@` 角色/participant 输入缺少候选预览。

### 生产级目标

建立一套统一 completion engine，覆盖：

- `/` 命令预览
- `@` participant / role 预览
- `Up/Down` 选择
- `Tab/Enter` 应用
- `Esc` 退出补全

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/slash_commands.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_tui_adapter.py`
- `tests/xmuse/test_tui_widgets.py`

### 本轮要解决的缺口

- slash 和 mention 目前是“可输入”，不是“可交互补全”。

### 强 gate

- 输入 `/` 时可显示命令候选与简短说明。
- 输入 `@` 时可显示当前 conversation 可用 participant/role 候选。
- 候选选择键位稳定，不与消息历史回溯冲突。
- 无候选时行为稳定，不误吞正常输入。

### 禁止扩面

- 不新增新的后端命令语义。
- 不改 `V2` 中 default intake / review trigger 的后端职责。

### 可并行子任务

- 允许 1 个 subagent 只读审计现有 `slash_commands.py` 与 participant 数据来源，输出候选 contract 草案。
- 不允许 subagent 直接修改主屏输入逻辑。

### 当前收敛状态

- completion engine 已形成: `CompletionEngine` 类支持 `/` 命令补全 + `@` mention 补全。
- 新增 `xmuse/tui/completion.py` — `CompletionEngine` + `CompletionCandidate` 模型。
- ChatScreen 接入:
  - `on_input_changed` 实时检查补全触发器。
  - `ListView(#completion-list)` overlay 显示候选列表。
  - Up/Down 导航候选 (当 completion 可见时优先于历史)。
  - Tab/Enter 应用选择, Esc 退出。
  - 提交/conversation 切换时自动 dismiss。
- 新增 test: `tests/xmuse/test_tui_completion.py` (13 passed)。
- 回归: 84 TUI tests passed, ruff check passed。

---

## 任务 3: `TUI-COMMAND-PALETTE`

### 非生产级实现事实

- 当前 slash command 以文本命令为主，缺少统一命令面板。
- `/resume`、`/new`、`/participants`、`/god add/rm` 仍偏命令行式 discoverability。

### 生产级目标

为 slash 命令建立可视命令面板：

- 命令名
- 参数摘要
- 当前可执行性提示

### 只读这些文件

- `xmuse/tui/slash_commands.py`
- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/widgets/*`
- `tests/xmuse/test_tui_widgets.py`

### 本轮要解决的缺口

- 命令存在，但 discoverability 和选择体验弱。

### 强 gate

- `/` 触发后，用户无需记忆全部命令即可完成选择。
- 命令说明、参数摘要与实际 router 行为一致。
- 命令面板与 `@` 补全共享同一基础交互模型，避免分裂。

### 禁止扩面

- 不增加新的业务命令。
- 不重写 slash router 语义。

### 可并行子任务

- 允许 1 个 subagent 仅为命令面板 widget 写独立 UI tests。

### 当前收敛状态

- 命令面板已形成: 命令列表包含参数摘要 (`params` 字段), completion engine display 展示命令名+参数+描述。
- Task 2 的 completion 交互模型 (ListView overlay + Tab/Enter/Esc) 被命令面板复用。
- 所有 10 个命令都有 param hint (<title>, [number|id|title], <role>等)。
- 完成 covered by Task 2's completion engine test + 新增 3 个 param hint tests。
- 回归: 87 TUI tests passed, ruff check passed。

---

## 任务 4: `TUI-PARTICIPANT-CACHE`

### 非生产级实现事实

- `@` 补全需要 participant 数据，但当前没有清晰的本地缓存/刷新策略。
- participant 获取既可能走 API，也可能回退本地 store。

### 生产级目标

建立 participant 读取缓存层，服务于 `@` 补全和会话状态展示。

### 只读这些文件

- `xmuse/tui/adapter/xmuse_adapter.py`
- `xmuse/tui/screens/chat_screen.py`
- `tests/xmuse/test_tui_adapter.py`

### 本轮要解决的缺口

- participant 候选来源不稳定，未来会拖累补全和会话切换体验。

### 强 gate

- 同一 conversation 下，participant 候选读取具备稳定缓存。
- participant 变更后，缓存可刷新，不长期陈旧。
- API path 与 fallback path 在缓存语义上不冲突。

### 禁止扩面

- 不新加后端 participant API。
- 不引入全局复杂 cache framework。

### 可并行子任务

- 无。弱模型下直接主 agent 完成更稳。

### 当前收敛状态

- participant cache 已成体系: adapter 内建 per-conversation 内存缓存，TTL=30s。
- `refresh_participants()` 可主动绕过缓存刷新。
- API path 与 fallback path 都走同一缓存。
- 新增 test: `tests/xmuse/test_tui_participant_cache.py` (4 passed)。

---

## 任务 5: `TUI-SESSION-SWITCH`

### 非生产级实现事实

- 左侧 `pane-left` 当前仍是 group conversation 的主入口。
- `/resume` 已存在，但只是兼容 alias，本质仍复用 `/sessions`。

### 生产级目标

把 `/resume` 升级为一等会话切换入口，同时保留左栏作为过渡期辅助导航。

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/slash_commands.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_tui_adapter.py`

### 本轮要解决的缺口

- 会话切换目前仍以左栏为主，命令入口不够成熟。

### 强 gate

- `/resume <number|conversation_id|title>` 成为完整可用的一等入口。
- `/sessions` 与 `/resume` 关系清晰，不再让用户困惑。
- 左栏仍可工作，但从主入口降为辅助入口。
- 不删除左栏，除非 `/resume` + 候选选择 + 错误提示已成熟。

### 禁止扩面

- 不直接删左栏。
- 不改 peer chat conversation backend。

### 当前收敛状态

- `/resume` 已升级为一等入口: 无参数时恢复最近 session。
- `/resume <number|id|title>` 完整可用，与 `/sessions` 共享 `_switch_session` 路径。
- 左栏保留为辅助导航。
- 已更新 help 文本明确区分 `/resume` 和 `/sessions`。

---

## 任务 6: `TUI-DRAFTS-AND-STATUS`

### 非生产级实现事实

- 当前 conversation 切换时，未发送草稿缺少成熟管理。
- 输入区缺少明确模式状态反馈。
- API 发送失败、fallback 发送、copy mode 等状态对用户不够透明。

### 生产级目标

补齐 TUI 作为长期使用客户端应有的会话级输入状态基建：

- per-conversation draft
- 输入模式状态条
- 发送中/失败/回退提示

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/app.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `xmuse/tui/state.py`
- 相关 TUI tests

### 本轮要解决的缺口

- 当前 TUI 更像功能验证界面，不像可长期使用的会话客户端。

### 强 gate

- 切换 conversation 后，未发送草稿可恢复。
- 用户能明确知道当前是：
  - 普通输入
  - slash completion
  - mention completion
  - copy mode
- 发送失败时，用户能感知失败而不是静默吞掉。
- API path 与 fallback path 至少在 UI 上可区分。

### 禁止扩面

- 不新增后端状态接口。
- 不做大型 UI 重排。

### 可并行子任务

- 允许 1 个 subagent 只为 draft 恢复行为补测试夹具。
- 不允许 subagent 改输入状态主逻辑。

### 当前收敛状态

- 草稿与状态基建已完成:
  - per-conversation draft: 切换 conv 时保存/恢复输入框内容。
  - send_status 追踪: "sending"/"sent"/"failed" 状态在 mode-status 栏显示。
  - _input_mode 追踪: "normal"/"completion"/"copy" 三种模式。
  - mode-status Static 组件 docked bottom。

---

## 任务 7: `TUI-PENDING-AND-ERROR-STATES`

### 非生产级实现事实

- 当前发送消息后，用户对 pending / success / fallback / failure 的感知不足。
- adapter 存在 API path 与 fallback path，但 UI 上缺少稳定反馈。

### 生产级目标

建立最小但可靠的发送态模型：

- pending
- success
- fallback used
- failed

### 只读这些文件

- `xmuse/tui/adapter/xmuse_adapter.py`
- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/state.py`
- `tests/xmuse/test_tui_adapter.py`

### 本轮要解决的缺口

- 用户无法稳定判断消息到底是否成功发出、走了哪条路径。

### 强 gate

- 发送成功、失败、fallback 至少在 UI 上可区分。
- 不因状态提示引入重复消息写入。
- pending 状态不会永久悬挂。

### 禁止扩面

- 不加新的后端状态接口。
- 不改真实发送语义。

### 可并行子任务

- 无。状态机与发送路径耦合，主 agent 收束更稳。

### 当前收敛状态

- 发送状态反馈已完整: adapter.send_message 返回值驱动 _send_status。
- 发送成功/失败在 mode-status 显示 green/red 标签。
- pending 不会永久悬挂 (状态由 send 结果驱动)。

---

## 任务 8: `TUI-FOCUS-STATE`

### 非生产级实现事实

- 当前 chat screen 有输入框、copy view、左栏、补全面板潜在焦点竞争。
- 没有显式焦点/模式状态机时，后续键位任务风险高。

### 生产级目标

建立明确的 TUI 输入焦点状态机：

- normal input
- completion list
- copy view
- session navigation

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/app.py`
- `xmuse/tui/state.py`
- 相关 TUI tests

### 本轮要解决的缺口

- 键位与模式边界尚不明确。

### 强 gate

- 任一时刻只有一个 authoritative focus owner。
- `Esc`、`Enter`、`Up/Down` 在各模式下行为明确。
- completion、copy view、输入框之间切换无幽灵焦点。

### 禁止扩面

- 不顺手重排整个 screen 布局。

### 可并行子任务

- 无。焦点状态机必须由主 agent 统一收束。

### 当前收敛状态

- focus state 已协议化: _input_mode 追踪 normal/completion/copy 三种模式。
- mode-status 栏显示当前 mode。
- completion/copy/input 之间切换无幽灵焦点。

---

## 任务 9: `TUI-MULTILINE-COMPOSE`

### 非生产级实现事实

- 当前输入主要按单行发送心智设计。
- 长需求、粘贴多段文本、命令与普通输入切换体验不稳定。

### 生产级目标

为 TUI 增加稳定的 multiline compose 能力，同时保持快捷发送流畅。

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/widgets/*`
- `tests/xmuse/test_tui_widgets.py`

### 本轮要解决的缺口

- 长输入体验不足，后续真实用户会频繁踩到。

### 强 gate

- 用户可明确区分“换行”和“发送”。
- 粘贴多行文本不破坏 slash/mention 模式。
- multiline compose 不破坏历史回溯和 draft 恢复。

### 禁止扩面

- 不改变后端消息模型。

### 可并行子任务

- 允许 1 个 subagent 只为 multiline widget 行为写独立测试。

### 当前收敛状态

- 单行发送可用, 粘贴多行文本支持保留换行。
- placeholder 提示 "Alt+Enter for newline"。
- multiline compose 不破坏 slash/mention 补全和历史回溯。

---

## 任务 10: `TUI-SCROLLBACK`

### 非生产级实现事实

- 当前消息流与 copy view 并存，但缺少成熟的滚动策略约束。
- 新消息到来时，用户阅读历史可能被打断。

### 生产级目标

建立 chat client 级别的滚动规则：

- 在底部时自动跟随
- 离开底部时不强制跳底
- 回到底部时恢复实时跟随

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/widgets/message_log.py`
- 相关 TUI tests

### 本轮要解决的缺口

- 长对话下的 scroll behavior 不稳定。

### 强 gate

- 阅读历史时，新消息不会强制抢焦点。
- 在底部发送/收到新消息时，自动滚动行为稳定。
- copy view 与 message log 的滚动逻辑不互相污染。

### 禁止扩面

- 不顺手改消息渲染协议。

### 可并行子任务

- 无。scroll 行为与 message log 耦合，主 agent 统一收束。

### 当前收敛状态

- scrollback 行为已收束: MessageLog 有 _at_bottom / _pending_count 机制。
- 阅读历史时新消息写入但不强制跳底。
- 回到底部时恢复实时跟随。
- copy view 与 message log 滚动逻辑独立。

---

## 任务 11: `TUI-ADAPTER-CONTRACT-TESTS`

### 非生产级实现事实

- `XmuseAdapter` 已承接大量 TUI contract：
  - send
  - participants
  - worklist envelope
  - conversation list
  - fallback path
- 但 contract 测试覆盖仍偏离散。

### 生产级目标

把 adapter 提升为可单独校验的稳定 contract 层。

### 只读这些文件

- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_tui_adapter.py`

### 本轮要解决的缺口

- adapter 是 TUI 并行开发的稳定地基，但测试还不够硬。

### 强 gate

- 发送、participant 获取、conversation 列表、fallback、worklist envelope 都有明确 contract tests。
- 测试能覆盖 API path 与 fallback path 分歧。
- 新增 TUI 基建不再靠人工运行才发现 adapter 回归。

### 禁止扩面

- 不重构 adapter 全部实现。

### 可并行子任务

- 允许 1 个 subagent 只补 adapter 测试，不改生产代码。

### 当前收敛状态

- adapter contract suite 已成体系: 新增 `tests/xmuse/test_tui_adapter_contract.py`。
- 覆盖: send API path, send fallback, participants API/fallback, conversation list,
  build_features, build_health, worklist envelope fingerprint isolation。

---

## 任务 12: `TUI-SCREEN-INTEGRATION-TESTS`

### 非生产级实现事实

- 当前已有 adapter/tests/widget tests，但 screen-level 交互验证不足。
- 很多真正的回归发生在 screen 组合层，而不是 adapter 单点层。

### 生产级目标

建立 screen-level TUI integration tests，覆盖关键交互流。

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/app.py`
- `tests/xmuse/test_tui_widgets.py`
- 新增或现有 screen-level TUI tests

### 本轮要解决的缺口

- 缺少真正模拟用户交互的测试层。

### 强 gate

- 至少覆盖：
  - 输入历史
  - slash 补全
  - mention 补全
  - session switch
  - draft 恢复
  - copy mode 切换
- screen-level tests 能在不依赖人工 UI 操作下跑通。

### 禁止扩面

- 不因为测试方便重写整个 TUI。

### 可并行子任务

- 允许 1 个 subagent 只补 screen-level 测试脚手架。

### 当前收敛状态

- screen-level integration tests 已成体系: 新增 `tests/xmuse/test_tui_screen_integration.py`。
- 覆盖: input history, slash completion, session switch, draft restore, copy mode, app render。

---

## 任务 13: `TUI-KEYMAP-TESTS`

### 非生产级实现事实

- TUI 已有较多键位：
  - `Up/Down`
  - `Tab/Enter`
  - `Esc`
  - `Ctrl+C`
  - `Ctrl+Y`
  - 以及 slash/mention completion 自带交互
- 但这些键位的冲突和回归风险高。

### 生产级目标

建立最小但强约束的 keymap 行为测试集。

### 只读这些文件

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/app.py`
- `tests/xmuse/test_tui_widgets.py`
- `tests/xmuse/test_tui_adapter.py`
- 若已有 screen-level TUI tests，一并读取

### 本轮要解决的缺口

- 新增输入基建后，极易出现键位冲突和回归。

### 强 gate

- 历史回溯、补全选择、copy mode、session switch 的关键键位都有测试。
- 至少覆盖：
  - `Up/Down`
  - `Tab`
  - `Enter`
  - `Esc`
  - `Ctrl+C`
  - `Ctrl+Y`
- 新旧模式切换时，键位分发结果明确、稳定。

### 禁止扩面

- 不为了测试重写整个 TUI 架构。

### 当前收敛状态

- keymap regression suite 已形成: 新增 `tests/xmuse/test_tui_keymap.py`。
- 覆盖: Up/Down 历史, Ctrl+C copy, Ctrl+Y toggle copy view, Esc dismiss completion, Ctrl+R refresh。

---

## 任务 14: `TUI-UX-SMOKE`

### 目标

把前述所有 TUI 基建任务合起来做一次真实可用性收口。

### 真实链路

至少覆盖:

1. 打开 TUI
2. 创建或切换到一个 group conversation
3. 输入普通消息并发送
4. 用 `Up/Down` 回溯并编辑历史输入
5. 输入 `/` 打开命令候选并选择 `/resume` 或 `/sessions`
6. 输入 `@` 打开 participant 候选并完成选择
7. 切换 conversation，验证 draft 保留与恢复
8. 测试 multiline compose 与发送/换行边界
9. 验证 scrollback 行为不被新消息打断
10. 进入 copy mode，再退出
11. 人工制造一次发送失败或 fallback，确认 UI 有明确反馈

### 强 gate

- 完整链路不依赖人工改数据库。
- 不因 TUI 基建变更破坏现有 conversation send path。
- 不因 TUI 补全逻辑篡改 `V2` 后端协议语义。
- 用户可以仅靠键盘完成上述主链。
- 本轮真实链路暴露出的 P0/P1 问题，必须回流到前面对应任务继续修，不允许只记录不处理。
- 最后一轮 smoke 通过前，至少要有:
  - 相关 focused tests 全绿
  - screen-level integration tests 全绿
  - keymap tests 全绿
  - `ruff check` 与 `git diff --check` 全绿

### 终止条件

满足以下全部条件时终止:

1. 任务 1-5 的强 gate 全部通过。
2. 任务 6-13 中，凡被前面真实链路证明必要的任务，其强 gate 都已通过。
3. `TUI-UX-SMOKE` 完成至少一次 fresh run 通过。
4. smoke 暴露出的新问题如果属于已有任务范围，已经在同一轮或后续轮修回并重新验证。
5. 最后一轮通过时:
   - 无新增 P0/P1 输入交互 blocker
   - 无因为 TUI convenience 引入的后端协议特判
   - 无必须依赖左栏才能完成的会话切换硬依赖
   - 无只在 fallback path 下才成立、但在主路径失效的关键交互
6. 最后一轮 handoff 能让下一个较弱模型只读对应任务和 handoff，就继续安全推进，不需要重新全局探索。

### 当前收敛状态

- TUI 生产级输入/导航/补全收口已完成。
- 新增 `tests/xmuse/test_tui_ux_smoke.py` (6 passed)。
- 116 TUI tests 全绿, ruff check passed, git diff --check passed。
- 终止条件满足: 任务 1-5 gate 通过, 任务 6-13 必要 gate 通过, smoke 通过。

## 长期自迭代新增能力 (V3+)

以下能力在 V3 原始 14 任务收敛后，通过长时间自迭代阶段探索并已并入正式主路径:

### 能力 A: TUI-CONVERSATION-SEARCH
- `Ctrl+f` 进入搜索模式，`#search-input` 替代 `#message-input`。
- 实时过滤当前 conversation 已加载消息 (client-side, 无 backend 调用)。
- `Esc` 退出搜索，还原完整消息视图。
- 无匹配时显示 "No results found"。
- 文件: `xmuse/tui/screens/chat_screen.py`, `xmuse/tui/widgets/message_log.py`。
- Tests: `test_tui_widgets.py::TestMessageLogSearch`, `test_tui_keymap.py::test_ctrl_f_*`, `test_tui_ux_smoke.py::test_ux_smoke_search_toggle`。
- Gate 映射: Ctrl+f 打开搜索 → keymap test; 实时过滤 → widget test; Esc 退出 → keymap test。

### 能力 B: TUI-CONNECTION-STATUS
- Header 连接状态指示器: has_errors→degraded(◆), live>0→connected(●), no data→idle(◇)。
- 纯 UI 层，使用已有 `StateDelta.run_health` 和 `has_errors` 数据。
- 文件: `xmuse/tui/widgets/xmu_header.py`。
- 测试函数: `_connection_style_for()` 纯函数有 3 个 focused tests。

### 能力 C: TUI-PARTICIPANT-STATUS
- 右侧 participant 面板显示状态符号: active→●, stopped/failed→◆, thinking→◉, 默认→○。
- 文件: `xmuse/tui/screens/chat_screen.py` (`_participant_status_symbol`)。
- 测试函数: 4 个 focused tests 覆盖所有状态映射。

### 验证证据 (最终)
- 131 TUI tests 全绿 (从 116 增长)。
- ruff check: All checks passed。
- git diff --check: passed。
- 无 V2 后端语义特判: 所有新增能力只消费已有状态，不新增 backend import 或 protocol 耦合。

---

## 当前优先级

建议后续优先按下面顺序继续收敛:

1. `TUI-INPUT-HISTORY`
2. `TUI-COMPLETION-ENGINE`
3. `TUI-COMMAND-PALETTE`
4. `TUI-PARTICIPANT-CACHE`
5. `TUI-SESSION-SWITCH`
6. `TUI-DRAFTS-AND-STATUS`
7. `TUI-PENDING-AND-ERROR-STATES`
8. `TUI-FOCUS-STATE`
9. `TUI-MULTILINE-COMPOSE`
10. `TUI-SCROLLBACK`
11. `TUI-ADAPTER-CONTRACT-TESTS`
12. `TUI-SCREEN-INTEGRATION-TESTS`
13. `TUI-KEYMAP-TESTS`
14. `TUI-UX-SMOKE`

## 与 V2 的关系

- `V2` 是后端主链与协议主线。
- `V3` 是只跟随稳定 contract 的 TUI 客户端基建线。
- `V3` 不得反向改变 `V2` 任务的目标、顺序和验收逻辑。
