# xmuse Walkthrough Maintenance Notes V12

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的群聊层延迟体验闭环交接文档。

`V12` 的目标是让 xmuse groupchat 的用户体感延迟尽量接近单独 provider session，同时保留
V7/V11 已收束的 MCP writeback authority。不要为了“快”把 stdout fallback 重新当成 happy
path；不要接 memoryOS；不要改 feature graph execution/review authority。

## 背景事实

当前真实 soak 结果显示:

- 8 轮真实 Ray + Codex app-server + MCP writeback 的 median latency 约 `16018ms`。
- p95/max 约 `17136ms`。
- 慢点主要在 `chat_read_inbox -> chat_post_message`，最大约 `8164ms`。
- Ray startup、session binding、MCP discovery 不是重复 turn 的主因。
- `first_delta_at` 当前由 scheduler 在 `receive_message(...)` 完成后记录，不是真正 token-level
  first delta。

参考 `/home/iiyatu/clowder-ai` 的有效模式:

- provider invocation 以 streaming event 形式逐步外显。
- frontend 先看到 stream start / chunk / tool-status，最终 message persistence 稍后完成。
- 用户体验接近 provider 原生 CLI，是因为“第一可见反馈”不等最终持久化。

V12 采用这一原则: **first-visible streaming/status 先外显，MCP writeback 仍是最终 authority**。

## 使用规则

1. 必须使用 `superpowers:systematic-debugging` 先复核当前延迟证据。
2. 必须使用 `superpowers:test-driven-development`；每个任务先 RED 后实现。
3. 一次只做一个任务；不得顺手扩到 provider parity、A2A、memoryOS、feature graph execution。
4. fake provider 只能做 focused gate；最终必须有真实 Ray + Codex app-server smoke。
5. 不允许把 stdout fallback 计入 happy path。
6. 不允许删除 MCP writeback validation；只能让 writeback 更直接、更早可见。
7. 每轮完成只更新本文档对应任务状态和 `docs/xmuse/codex-strengthening-handoff.md`。

## 任务总览

1. `DIRECT-MCP-POST-PROMPT`
2. `FIRST-VISIBLE-STREAM-TRACE`
3. `TUI-IMMEDIATE-PEER-FEEDBACK`
4. `STREAM-FINALIZATION-INTEGRITY`
5. `REAL-RUNTIME-LATENCY-PARITY-SMOKE`

---

## 任务 1: `DIRECT-MCP-POST-PROMPT`

### 非生产级实现事实

`src/xmuse_core/chat/peer_scheduler.py` 当前 prompt 强制 GOD 先调用
`chat_read_inbox`，再用 `chat_post_message` 回复。但 scheduler 已经把当前
`inbox_item`、`participant_id`、`god_session_id` 和 group context 放入
`xmuse_context`。简单 @architect turn 再读 inbox 是重复动作，也增加模型规划和工具调用延迟。

### 生产级目标

对 peer chat nudge，优先要求 GOD 直接基于 `xmuse_context.inbox_item.payload.content`
调用:

```text
chat_post_message(
  conversation_id=xmuse_context.conversation_id,
  participant_id=xmuse_context.participant_id,
  god_session_id=xmuse_context.god_session_id,
  reply_to_inbox_item_id=xmuse_context.inbox_item.id,
  content=<assistant reply>
)
```

`chat_read_inbox` 只作为异常恢复/批量检查工具，不再是每轮 happy path 必经步骤。

### 只读/可改文件

- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/codex-strengthening-handoff.md`

### 强 gate

- focused test 必须断言 scheduler prompt 不再包含“must use chat_read_inbox”。
- focused test 必须断言 prompt 明确要求 direct `chat_post_message`，并保留
  `reply_to_inbox_item_id`。
- success validation 仍必须要求真实 assistant message + `chat_post_message` evidence。
- stdout fallback 仍只能在 degraded mode 下成功。
- 真实 smoke 中允许没有 `chat_read_inbox` stage，但必须有 `chat_post_message` stage。

### 当前收敛状态

- 已收束于 2026-06-04。
- focused gate 已验证 scheduler prompt 不再要求 `must use chat_read_inbox`，并明确 direct
  `chat_post_message(... reply_to_inbox_item_id=xmuse_context.inbox_item.id ...)`。
- app-server MCP developer instructions 同步偏向 direct `chat_post_message`；`chat_read_inbox`
  只保留为 recovery / batch inspection。
- success validation 仍要求真实 assistant message 和 `chat_post_message` stage；stdout fallback
  仍只作为 degraded path。

---

## 任务 2: `FIRST-VISIBLE-STREAM-TRACE`

### 非生产级实现事实

`CodexAppServerTransport` 已能写 `ChatStreamStore`，TUI adapter 也会读取 active stream。
但 latency trace 的 `first_delta_at` 仍由 scheduler 在最终 `receive_message(...)` 返回后记录。
这会掩盖用户真正第一次看到反馈的时间。

### 生产级目标

把 first-visible 拆成独立指标:

- `stream_started_at`: send turn 后 active stream 被创建的时间。
- `first_stream_delta_at`: app-server 收到首个 `item/agentMessage/delta` 的时间。
- `first_visible_at`: `stream_started_at` 或 `first_stream_delta_at`，取最早可对 TUI 外显的时间。
- `writeback_at`: 最终 MCP writeback 被 scheduler 确认的时间。

### 只读/可改文件

- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `tests/xmuse/test_chat_streams.py`
- `tests/xmuse/test_ray_adapters.py`
- `tests/xmuse/test_peer_chat_scheduler.py`

### 强 gate

- app-server accumulator 或 transport test 必须证明首个 delta 会记录 `first_stream_delta_at`。
- `PeerTurnLatencyTraceStore.list_recent()` 必须返回 `stage_timings.first_visible`。
- scheduler 不得再把最终 receive 完成点命名为 first delta；如需保留，命名为
  `scheduler_observed_result_at`。
- focused tests 使用 fake clock，不允许依赖 wall-clock sleep。

### 当前收敛状态

- 已收束于 2026-06-04。
- `ChatStreamStore` 记录 active stream 首个 delta 的 `first_delta_at`，且后续 delta 不覆盖。
- app-server accumulator 在首个 `item/agentMessage/delta` 记录
  `latency_stages.first_stream_delta`；transport 成功创建 active stream 时记录
  `latency_stages.stream_started`。
- scheduler latency trace 的兼容字段 `first_delta_at` 改为真正首个 stream delta；最终
  `receive_message(...)` 完成点只写入 `stage_timings.scheduler_observed_result`。
- `PeerTurnLatencyTraceStore.list_recent()` 返回 `stage_timings.first_visible`，取
  `stream_started` / `first_stream_delta` 中最早可外显时间。

---

## 任务 3: `TUI-IMMEDIATE-PEER-FEEDBACK`

### 非生产级实现事实

TUI 当前 `poll_messages()` 会合并 active stream，但刷新间隔是 `2.5s`，且发送后只
`action_refresh_now()` 一次。如果 provider 尚未创建 active stream，用户仍会看到空白等待。

### 生产级目标

用户发送消息后立即看到 peer turn 状态:

- 本地 echo 用户消息保持不变。
- 对命中的 target GOD，显示临时 pending/stream message，例如 `architect-god ...`。
- 一旦 `ChatStreamStore` 有 active stream，用 active stream 内容替换 pending。
- 一旦最终 assistant message 到达，移除 pending/stream，只保留正式 message。

### 只读/可改文件

- `xmuse/tui/adapter/xmuse_adapter.py`
- `xmuse/tui/state.py`
- `xmuse/tui/screens/chat_screen.py`
- `tests/xmuse/test_tui_adapter.py`
- `tests/xmuse/test_tui_state.py`
- `tests/xmuse/test_tui_navigation.py`

### 强 gate

- TUI test 必须证明发送 `@architect ...` 后，不等后端最终 reply，也会显示 pending peer row。
- active stream 到来后，pending row 被替换或合并，不能出现重复 assistant row。
- final assistant message 到来后，pending/stream row 被移除。
- 不允许 TUI 合成 durable assistant message；pending 只能是 UI transient 或 stream projection。

### 当前收敛状态

- 已收束于 2026-06-04。
- ChatScreen 在成功发送 explicit `@role` 消息后，基于当前 participants 立即注入
  `envelope_type=peer_pending` 的 UI transient assistant row，例如 `architect-god ...`。
- pending row 只进入 TUI `AppState`，不写入 durable `ChatStore`。
- active stream 到达后，同一 peer 的 pending row 被替换为 stream row。
- final assistant message 到达后，同一 peer 的 pending/stream transient row 被移除，只保留
  durable final message。

---

## 任务 4: `STREAM-FINALIZATION-INTEGRITY`

### 非生产级实现事实

active stream 是临时投影。若 app-server error、scheduler timeout、或 final writeback 竞态，
stream 可能滞留，造成 TUI 误以为 GOD 仍在回复。

### 生产级目标

stream lifecycle 必须和 peer turn lifecycle 对齐:

- turn start -> stream active。
- first delta -> stream content append。
- MCP writeback confirmed -> stream done / hidden by final message。
- timeout/error/degraded fallback -> stream error/done，并有 degraded card/trace。
- stale active stream 有清理策略，但不能误删当前活跃 turn。

### 只读/可改文件

- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_chat_streams.py`
- `tests/xmuse/test_peer_chat_scheduler.py`

### 强 gate

- timeout 后 active stream 不得永久留在 `list_active()`。
- error 后 TUI 可以显示 degraded/status，但不显示无限 `...`。
- final message 与 stream 同 `source_inbox_item_id` 时只显示 final message。
- 不允许把 stream content 落成 durable assistant message，除非走已有 degraded fallback gate。

### 当前收敛状态

- 已收束于 2026-06-04。
- `ChatStreamStore` 支持按 `conversation_id + source_inbox_item_id` 关闭 active streams。
- scheduler 在 timeout、provider error、stdout/degraded fallback、failed writeback validation 和
  final MCP writeback 后，按当前 inbox item 关闭或隐藏 active stream。
- timeout/degraded fallback 后 active stream 状态写为 `error`，不再留在 `list_active()`。
- TUI adapter 在 durable final assistant message 已有相同 `source_inbox_item_id` 时，不再返回
  同源 active stream，避免 final + `...` 重复显示。

---

## 任务 5: `REAL-RUNTIME-LATENCY-PARITY-SMOKE`

### 目标

用真实 Ray + Codex app-server + MCP writeback 证明 V12 的延迟体验改善。

### 只读/可改文件

- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/codex-strengthening-handoff.md`
- 本文档

### 强 gate

必须跑至少一条 fresh + restart/resume 真实链路，并记录:

- `provider_session_id` 是否跨 restart 复用。
- 每轮 `delivery_mode`。
- 每轮 `first_visible_ms`。
- 每轮 `writeback_ms`。
- 每轮是否有 `chat_post_message` stage。
- 每轮是否有 stdout fallback。
- 进程清理后无 `codex app-server` / `raylet` / `gcs_server` / `ray::` 残留。

验收阈值:

- `delivery_mode` 必须为 MCP writeback authority，不得是 stdout happy path。
- `first_visible_ms` 在 provider 可用时应明显低于最终 `writeback_ms`。
- direct post path 不要求 `chat_read_inbox` stage。
- 若 `first_visible_ms` 仍接近 `writeback_ms`，不得标记 V12 完成；必须回到任务 2/3
  定位 stream 或 TUI projection 断点。

### 当前收敛状态

- 已收束于 2026-06-04。
- 真实 Ray + Codex app-server + MCP writeback restart/resume smoke 已通过。
- provider session id `019e92f3-e67c-7fb0-bba3-18638575478e` 跨 restart 复用。
- fresh turn:
  - `delivery_mode=mcp_writeback`
  - `first_visible_ms=1701`
  - `writeback_ms=16782`
  - 有 `chat_post_message` stage
  - 无 stdout fallback
- resume turn:
  - `delivery_mode=mcp_writeback`
  - `first_visible_ms=1377`
  - `writeback_ms=12769`
  - 有 `chat_post_message` stage
  - 无 stdout fallback
- cleanup 检查无 `codex app-server` / `raylet` / `gcs_server` / `ray::` 残留。

## V12 收敛状态

- V12 已收束于 2026-06-04。
- direct `chat_post_message` 已成为 peer chat MCP happy path；`chat_read_inbox` 不再是 simple
  peer turn 必经步骤。
- TUI 在最终 writeback 前已有 transient pending/stream 反馈。
- latency trace 已区分 `first_visible_ms` 与 `writeback_ms`。
- 真实 Ray + Codex app-server restart/resume smoke 已通过。
- stdout fallback 未被重新计入 happy path。
- touched-file ruff、`git diff --check`、leftover process cleanup 均已通过。

## V12 完成定义

只有同时满足以下条件，才能宣称 V12 complete:

1. direct `chat_post_message` 成为 peer chat MCP happy path。
2. `chat_read_inbox` 不再是简单 peer turn 必经步骤。
3. TUI 在最终 writeback 前有可见 pending/stream 反馈。
4. latency trace 能区分 `first_visible_ms` 和 `writeback_ms`。
5. 真实 Ray + Codex app-server restart/resume smoke 通过。
6. stdout fallback 没有被重新计入 happy path。
7. touched-file ruff 通过，`git diff --check` 通过。
