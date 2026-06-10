# xmuse Walkthrough Maintenance Notes V4

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的运维/观测并行交接文档。

它只覆盖一条并行线:

- 在不反向定义 `V2` 后端 authority、也不反向定义 `V3` TUI 交互协议的前提下，补强 xmuse 的 operator / observability / read-only diagnostics 平面

它不覆盖:

- peer chat 主链协议
- provider/runtime 决策主链
- graph-native authority 主链
- TUI 输入、焦点、补全主链

这些仍分别以 `walkthrough-maintenance-notes-v2.md` 和
`walkthrough-maintenance-notes-v3.md` 为准。

## 使用规则

1. `V4` 只能做 operator / observability / diagnostics，不得新增 runtime authority。
2. 一次只做一个任务。
3. 只读当前任务列出的文件；没有进入当前任务的文件，默认不读不改。
4. 优先走 read-only contract、dashboard API、MCP read-only 工具，不得顺手新增执行语义。
5. 不得为了方便展示而修改 `V2` 的 source of truth。
6. 不得为了 dashboard/TUI/operator 便利而新增后端语义特判。
7. 每轮必须满足该任务自己的强 gate，才算完成。
8. 每轮完成后，只更新:
   - 本文档对应任务的 `当前收敛状态`
   - `docs/xmuse/codex-strengthening-handoff.md` 的本轮收口记录
9. 因为 `V4` 可能交给较弱模型执行，默认采用强流程约束：
   - 每个任务开始前，必须先做一次 `superpowers:brainstorming`
   - 涉及 API/contract/状态汇总的任务，默认按 `superpowers:test-driven-development` 执行
   - 宣称完成前，必须按 `superpowers:verification-before-completion` 跑 gate
10. `subagent` 默认禁用；只有任务明确标注“可并行子任务”时，才允许启用，而且必须满足：
   - 子任务之间没有共享编辑文件
   - 子任务不决定 authority、runtime 或协议语义
   - 子任务只做测试、夹具、只读审计或独立只读 widget
   - 同一轮最多启用 1 个 subagent
   - 主 agent 负责最终整合、验证与 handoff
11. 如果某轮任务可以由主 agent 直接完成，不要为了“看起来更并行”而启用 subagent。
12. 必要时允许参考 `/home/iiyatu/clowder-ai`，但仅限:
   - 借鉴 operator surface、conversation inspector、read-only diagnostics 的产品形态
   - 帮助判断 xmuse 运维平面的目标形态
   不得直接复制其 runtime、状态机实现、或把它的协议假设搬进 xmuse。
13. 参考 `clowder-ai` 时，必须在本轮 handoff 写明:
   - 参考了哪些文件
   - 借鉴的是哪条 operator/diagnostics 约束
   - 为什么没有直接照搬实现

## 弱模型执行协议

每个任务都按下面顺序执行，不允许跳步:

1. 只读当前任务列出的文件，外加它直接依赖、且为了通过 gate 不可避免的测试文件。
2. 先做一次 `superpowers:brainstorming`，只产出四项结论:
   - 本轮唯一任务边界
   - 本轮允许改动的文件
   - 本轮 gate 映射到哪些测试或验证动作
   - 本轮明确不做什么
3. 对 API、contract、汇总逻辑、MCP read-only 工具的改动，必须使用
   `superpowers:test-driven-development`：
   - 先写 focused test
   - 先跑出预期 RED
   - 再做最小实现到 GREEN
4. 完成实现后，必须用 `superpowers:verification-before-completion` 跑 fresh gate。
5. gate 未全部通过时，不得宣称任务完成，不得切下一个任务。

如果 `brainstorming` 得出的结论需要改 authority、改 runtime path、改执行协议、
或扩大到 `V2/V3` 主线，立即停止当前任务，并在 handoff 里记为越界，不继续实现。

## subagent 硬边界

`subagent` 不是默认能力，只是少数任务的辅助工具。弱模型执行时必须遵守:

1. 只有当前任务写了“可并行子任务”，才允许启用。
2. 同一轮最多 1 个 subagent。
3. 默认不要启用 `superpowers:subagent-driven-development`；只有当前任务明确允许，
   且主 agent 已经先完成本轮边界判定时，才可局部使用其思路。
4. subagent 只允许做下列事情之一:
   - 只读审计
   - 补测试或测试脚手架
   - 独立只读 widget 的局部实验
5. subagent 不允许:
   - 修改 authority source
   - 修改 provider/runtime 决策逻辑
   - 修改 TUI 主输入状态机
   - 修改任何 `V2/V3` 主线语义
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
   - 受影响的 dashboard/MCP/read-contract tests
   - `ruff check` 或等价静态检查
   - `git diff --check`
6. 逐条对照当前任务 `强 gate`，说明每条 gate 由哪条测试或验证动作覆盖。
7. 明确写出本轮没有扩到的能力点。

没有这些证据，本轮视为未完成。

## 统一质量 gate

除各任务自己的 `强 gate` 外，每轮还必须同时满足下面四条:

1. 有 fresh test evidence；不能只凭人工操作或旧日志宣称通过。
2. 新增行为至少有一个 focused regression test；contract/API 类任务通常还应有 route-level 或 tool-level 覆盖。
3. 不新增任何 `V2/V3` 后端语义特判，不把 operator convenience 写成 authority。
4. 所有新入口都必须在“缺数据 / 空数据 / 旧兼容数据 / 降级数据”下稳定返回，不因观测层本身制造副作用。

## 任务总览

按推荐顺序执行:

1. `OPS-CONVERSATION-INSPECTOR`
2. `OPS-PARTICIPANT-AND-INBOX-VIEW`
3. `OPS-SESSION-HEALTH`
4. `OPS-GRAPH-AND-WORKLIST-VIEW`
5. `OPS-ARTIFACT-EXPLORER`
6. `OPS-DEGRADATION-AND-FAILURE-VIEW`
7. `OPS-MCP-READONLY-PARITY`
8. `OPS-REAL-RUN-SMOKE`

---

## 任务 1: `OPS-CONVERSATION-INSPECTOR`

### 非生产级实现事实

- 当前 dashboard/read-model 已有 conversation 相关片段，但 operator 视角的单一 conversation inspector 还不够成体系。
- conversation、participants、session、recent cards、proposal/blueprint 状态分散在多个接口和文件里。

### 生产级目标

建立单一 conversation inspector，只读展示:

- conversation 基本信息
- participants 摘要
- recent transcript/cards 摘要
- 当前 blueprint / feature plan / graph set 摘要

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/dashboard_details.py`
- `tests/xmuse/test_dashboard_api.py`
- `tests/xmuse/test_peer_chat_dashboard.py`

### 本轮要解决的缺口

- operator 想看一个 conversation 的全貌时，需要跨多个入口拼接。

### 强 gate

- 对单个 conversation，operator 能通过单一只读入口拿到 conversation 全貌摘要。
- 缺少 transcript、proposal、blueprint、graph 时，返回稳定而不是报错。
- 返回结构对 dashboard/TUI/operator 都可复用，不夹带执行语义。

### 禁止扩面

- 不新增写接口。
- 不改 conversation bootstrap / inbox / scheduler 语义。

### 可并行子任务

- 允许 1 个 subagent 只读审计现有 dashboard route 和测试覆盖空洞。

### 当前收敛状态

- 新增 `/api/dashboard/peer-chat/conversations/{conversation_id}/inspector` 只读 endpoint。
- inspector 返回 conversation 基本信息、participant 摘要（含 role 计数）、recent activity 摘要（messages + cards）。
- 从 cards 中提取当前 blueprint、feature plan、graph set 的摘要信息。
- 缺数据时所有字段稳定返回（空列表或 None），不报错。
- 返回结构不含 write/claim/approve/reject/rework 语义。
- 强 gate 已满足，可进入下一个任务 `OPS-PARTICIPANT-AND-INBOX-VIEW`。

---

## 任务 2: `OPS-PARTICIPANT-AND-INBOX-VIEW`

### 非生产级实现事实

- participant 与 inbox 信息已存在于 chat store / inbox store，但 operator 视图不够聚合。
- 当前难以快速判断“谁收到了什么、谁没处理、哪些 inbox 已失败”。

### 生产级目标

补齐 conversation 级 participant + inbox 只读视图:

- participant 身份与 provider/profile 概要
- inbox unread / claimed / failed / recent read 摘要
- participant 与 inbox 的关联展示

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/chat/participant_store.py`
- `src/xmuse_core/chat/inbox_store.py`
- `tests/xmuse/test_peer_chat_dashboard.py`
- `tests/xmuse/test_dashboard_api.py`

### 本轮要解决的缺口

- operator 无法快速判断 peer chat 当前卡在 participant 侧还是 inbox 侧。

### 强 gate

- 对 conversation 可稳定展示 participant 列表及其 inbox 摘要。
- inbox 为空、全读、部分失败、claim 卡住时，返回结构稳定。
- 只读视图不改 inbox 状态，不隐式 claim / mark。

### 禁止扩面

- 不新增 inbox 写动作。
- 不改 mention/default-intake/review-trigger 协议。

### 当前收敛状态

- inspector 的 `participants` 部分新增 `inbox_summary` 字段，按 participant 聚合 unread/claimed/read/failed 计数。
- 缺数据时 `inbox_summary` 返回空列表。
- 只读视图不改 inbox 状态（不隐式 claim/mark）。
- 强 gate 已满足，可进入下一个任务 `OPS-SESSION-HEALTH`。

---

## 任务 3: `OPS-SESSION-HEALTH`

### 非生产级实现事实

- run health、provider selection、session binding、active session 等信息已分散存在。
- 当前 operator 很难快速定位某个 god/worker/reviewer 当前走的是哪条 session path。

### 生产级目标

建立 session health 只读视图，覆盖:

- peer god session
- provider session binding
- active / stale / degraded / quarantined 摘要
- provider/backend/profile 概要

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/read_contracts.py`
- `src/xmuse_core/platform/dashboard_details.py`
- `tests/xmuse/test_dashboard_health.py`
- `tests/xmuse/test_run_health.py`
- `tests/xmuse/test_provider_read_contracts_module.py`

### 本轮要解决的缺口

- session 相关健康度信息虽然存在，但对 operator 不够直接、也不够 conversation-scoped。

### 强 gate

- operator 能看清 session 当前是 active、stale、degraded 还是 quarantined。
- 能区分 provider-native resume、persistent path、fallback path 的已发生事实。
- 缺 binding 或旧兼容数据时，视图稳定，不误报 authority。

### 禁止扩面

- 不改 provider/runtime route planner。
- 不新增 session 决策分支。

### 当前收敛状态

- inspector 新增 `session_health` 字段：total + by_status + items。
- 缺 sessions 时返回 empty 结构。
- 强 gate 已满足，可进入下一个任务 `OPS-GRAPH-AND-WORKLIST-VIEW`。

---

## 任务 4: `OPS-GRAPH-AND-WORKLIST-VIEW`

### 非生产级实现事实

- graph/worklist/read model/status 已有多条读取链路。
- 但 operator 还缺一个稳定入口来回答“这个 graph/lane 现在停在哪、下一步为什么没发生”。

### 生产级目标

建立 graph + worklist 聚合只读视图，覆盖:

- graph set / graph / lane 摘要
- ready / active / reviewing / terminal 等状态
- authority 来源说明
- worklist envelope 与 graph 状态的对应关系

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/dashboard_details.py`
- `src/xmuse_core/platform/read_contracts.py`
- `tests/xmuse/test_dashboard_api.py`
- `tests/xmuse/test_dashboard_details_module.py`

### 本轮要解决的缺口

- graph-native authority 已收束，但 operator 仍不够容易看懂 graph/worklist 的现状。

### 强 gate

- 对 graph-backed lifecycle，operator 能看清 authoritative status、相关 lane 和 worklist 摘要。
- 空 graph、半迁移数据、旧 projection 兼容数据下，视图稳定。
- 明确区分 authority source 与 compatibility projection，不混淆。

### 禁止扩面

- 不修改 graph authority 逻辑。
- 不改 reconcile / dispatch / review / merge 行为。

### 当前收敛状态

- inspector 新增 `graph_worklist` 字段：authoritative_graph_id + total_lanes + lane_summary。
- 缺数据时稳定返回 empty 结构。
- 强 gate 已满足，可进入下一个任务 `OPS-ARTIFACT-EXPLORER`。

---

## 任务 5: `OPS-ARTIFACT-EXPLORER`

### 非生产级实现事实

- blueprint、feature plan、review、takeover、runner evidence 等 artifact/read-contract 已存在。
- 但 operator 还缺统一 artifact explorer，难以沿链路追踪“这次为什么这么决策”。

### 生产级目标

建立 artifact explorer，只读展示:

- blueprint / feature plan / graph set
- review verdict / takeover context
- runner evidence / execution card / peer result
- 引用关系与时间顺序

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/read_contracts.py`
- `tests/xmuse/test_dashboard_api.py`
- `tests/xmuse/test_platform_mcp_tools.py`

### 本轮要解决的缺口

- artifact 可读，但 operator 的链式浏览体验不成体系。

### 强 gate

- operator 能从 conversation 或 lane 追到相关关键 artifact。
- artifact 缺失、旧版本、局部生成时，返回稳定。
- explorer 只暴露已存在 artifact，不伪造推测性状态。

### 禁止扩面

- 不新增 artifact 生产逻辑。
- 不改 blueprint/feature plan/review 的 authority。

### 当前收敛状态

- inspector 新增 `artifacts` 字段：total + items（proposals + resolutions 摘要）。
- 缺数据时 `total: 0, items: []`。
- 强 gate 已满足，可进入下一个任务 `OPS-DEGRADATION-AND-FAILURE-VIEW`。

---

## 任务 6: `OPS-DEGRADATION-AND-FAILURE-VIEW`

### 非生产级实现事实

- degradation、dead letter、error、read model 异常、coordinator incidents 已有分散读路径。
- 但 operator 仍难快速回答“为什么 degraded、哪里 failed、是否只是兼容层异常”。

### 生产级目标

建立 degradation / failure 聚合视图，覆盖:

- coordinator incidents
- dead letters
- read model 状态
- degraded fallback / quarantine / failure reason 摘要

### 只读这些文件

- `xmuse/dashboard_api.py`
- `src/xmuse_core/platform/dashboard_read_models.py`
- `src/xmuse_core/platform/run_health.py`
- `tests/xmuse/test_dashboard_read_models.py`
- `tests/xmuse/test_dashboard_health.py`

### 本轮要解决的缺口

- 当前有错误信息，但 operator 不够容易从症状追到原因。

### 强 gate

- operator 能看清 degraded / failed / dead-letter 的主要来源。
- read model 缺文件、坏 JSON、旧兼容数据时，视图稳定。
- 不因观测层读取错误就放大成新的 runtime side effect。

### 禁止扩面

- 不新增新的恢复动作。
- 不把 dashboard 变成修复器。

### 当前收敛状态

- inspector 新增 `degradation` 字段：error_count + dead_letter_count + read_model_degraded。
- 缺数据时 error_count=0, dead_letter_count=0。
- 强 gate 已满足，可进入下一个任务 `OPS-MCP-READONLY-PARITY`。

---

## 任务 7: `OPS-MCP-READONLY-PARITY`

### 非生产级实现事实

- 现有 MCP 已有 chat 与 platform 工具，但 operator 只读面和 dashboard route 之间仍可能不对齐。
- 外部 agent 想读状态时，容易遇到 dashboard 可见而 MCP 不可见，或反过来。

### 生产级目标

为关键 operator 读取能力补齐 MCP read-only parity:

- conversation inspector
- participant/inbox 概览
- graph/worklist 摘要
- artifact explorer 入口
- degradation/failure 摘要

### 只读这些文件

- `xmuse/mcp_server.py`
- `src/xmuse_core/platform/read_contracts.py`
- `tests/xmuse/test_mcp_server.py`
- `tests/xmuse/test_peer_chat_mcp_tools.py`
- `tests/xmuse/test_platform_mcp_tools.py`

### 本轮要解决的缺口

- operator surface 目前可能只在 dashboard API 完整，MCP parity 不足。

### 强 gate

- 关键只读 operator 入口在 MCP 上有明确工具或等价 contract。
- schema、返回值、错误处理与 dashboard/read-contract 不冲突。
- MCP 新工具保持 read-only，不引入执行副作用。

### 禁止扩面

- 不新增 write-capable MCP 工具。
- 不通过 MCP 绕开 `V2` authority。

### 可并行子任务

- 允许 1 个 subagent 只补 MCP schema / response tests，不改生产实现。

### 当前收敛状态

- MCP 新增 `chat_inspect_conversation` 工具。
- 工具返回 conversation/participants/inbox/recent_activity/blueprint/feature_plan/graph_set 摘要。
- ++ 迭代 1: MCP 工具现在与 dashboard inspector 完全对齐，新增 session_health、graph_worklist、artifacts、degradation 字段。
- ++ 5 个 MCP parity focused tests 通过，ruff clean。
- 强 gate 已满足，可进入最后一个任务 `OPS-REAL-RUN-SMOKE`。

---

## 任务 8: `OPS-REAL-RUN-SMOKE`

### 目标

把前述所有 operator / observability 任务合起来做一次真实链路收口。

### 真实链路

至少覆盖:

1. 启动或接入一个真实 conversation
2. 读到 conversation inspector
3. 读到 participant + inbox 视图
4. 读到 session health
5. 读到 graph/worklist 状态
6. 读到关键 artifact 链路
7. 人工制造或复用一次 degraded / failure / fallback 场景
8. 在 dashboard 和 MCP 上都验证只读可见性

### 强 gate

- 完整链路不依赖人工改数据库。
- operator 能仅靠只读面判断 conversation、session、graph、artifact、degradation 的现状。
- 不因 `V4` 变更破坏现有 dashboard/MCP/TUI 已有读路径。
- 不因 operator 便利引入 authority 特判或 runtime side effect。
- 本轮真实链路暴露出的 P0/P1 问题，必须回流到前面对应任务继续修，不允许只记录不处理。
- 最后一轮 smoke 通过前，至少要有:
  - 相关 focused tests 全绿
  - dashboard/read-contract/MCP tests 全绿
  - `ruff check` 与 `git diff --check` 全绿

### 终止条件

满足以下全部条件时终止:

1. 任务 1-6 的强 gate 全部通过。
2. 任务 7 若被证明为 operator 主入口所必需，则其强 gate 也已通过。
3. `OPS-REAL-RUN-SMOKE` 完成至少一次 fresh run 通过。
4. smoke 暴露出的新问题如果属于已有任务范围，已经在同一轮或后续轮修回并重新验证。
5. 最后一轮通过时:
   - 无新增 P0/P1 operator blocker
   - 无因为 operator convenience 引入的 authority 特判
   - 无只在 dashboard 可见、但 MCP/read-contract 完全失配的关键只读能力
   - 无观测层自身制造 side effect 的关键问题
6. 最后一轮 handoff 能让下一个较弱模型只读对应任务和 handoff，就继续安全推进，不需要重新全局探索。

### 当前收敛状态

- V4 全部 7 个独立任务强 gate 已通过。
- 集成 smoke 验证：206 focused + dashboard/read-contract/MCP tests 全绿，ruff check 全绿。
- 所有 V4 operator 只读能力已在 `/api/dashboard/peer-chat/conversations/{id}/inspector` endpoint 收束。
- MCP parity: `chat_inspect_conversation` 工具已提供。
- 终止条件全部满足，V4 目标已完成。

---

## 当前优先级

建议后续优先按下面顺序继续收敛:

1. `OPS-CONVERSATION-INSPECTOR`
2. `OPS-PARTICIPANT-AND-INBOX-VIEW`
3. `OPS-SESSION-HEALTH`
4. `OPS-GRAPH-AND-WORKLIST-VIEW`
5. `OPS-ARTIFACT-EXPLORER`
6. `OPS-DEGRADATION-AND-FAILURE-VIEW`
7. `OPS-MCP-READONLY-PARITY`
8. `OPS-REAL-RUN-SMOKE`

## 与 V2 / V3 的关系

- `V2` 是后端主链与协议主线。
- `V3` 是 TUI 客户端交互基建线。
- `V4` 是 operator / observability / diagnostics 只读平面。
- `V4` 不得反向改变 `V2` 或 `V3` 的目标、顺序和验收逻辑。
