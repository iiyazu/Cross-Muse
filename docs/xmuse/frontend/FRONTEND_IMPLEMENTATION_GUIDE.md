# xmuse Frontend Implementation Guide

更新日期: 2026-06-30 HKT

本文档面向单独开发 xmuse 前端/TUI 的人。它只基于 WSL/Linux 侧当前仓库的后端
实现和文档，不依赖 Windows/Open Design 目录。当前用户前门方向是 Textual TUI；
旧 `xmuse/frontend/` browser frontend 已归档到
`xmuse/history/cleanup_20260601T163850Z/`。

## 结论

当前后端足够支撑一个 chat-first/TUI MVP：

- 群聊列表、群聊详情、参与者、角色模板、fork lineage 可从 Chat API 获取。
- 消息流和 compact cards 可从 Chat API 或 dashboard peer-chat API 获取。
- lane、run health、lane graph、feature graph-set、audit/read-model 可从
  Dashboard API 获取。
- TUI 可以把 dashboard 做成灰盒 drill-down，而不是主入口。

当前后端还不足以支撑完整 north-star 愿景：

- 没有 WebSocket/streaming；先用轮询。
- `GET /api/chat/conversations/{id}/worklist` 已提供只读 worklist projection。
- proposal `narrow/reject` REST endpoint 未落地；当前主要有 approve。
- C-class autonomous blueprint execution 的 PlanningRun/card/API 仍未稳定落地。
- 用户批准 blueprint 后自动 feature/lane DAG 生成正在 C-class 中推进，前端先按
  reserved capability 处理。

2026-06-02 HKT 运行态补充：

- 不要假设当前有 live runner；启动 xmuse runtime 需要用户明确要求。
- `/api/feature-graph-sets` 和 `/api/lane-graphs` 可以用于查看 C-class graph
  drill-down。
- PlanningRun、autonomous execution cards、blueprint-approved 后自动生成
  feature/lane DAG 的前端稳定契约仍未收束；前端只能做占位或灰盒调试视图。
- 解耦边界以 `docs/xmuse/解耦开发协议.md` 为准。

## 启动

从仓库根目录启动：

```bash
uv run python xmuse/chat_api.py
uv run python xmuse/dashboard_api.py
```

按需启动 xmuse 执行后台：

```bash
uv run python xmuse/mcp_server.py
uv run python xmuse/platform_runner.py --max-hours 10 --max-concurrent 4 --god-runtime codex --mcp-port 8100 --peer-chat --persistent-review-god
```

默认本地地址：

| Surface | Base URL |
|---|---|
| Chat REST | `http://localhost:8201/api/chat` |
| Dashboard REST | `http://localhost:8200/api` |
| MCP JSON-RPC | `http://localhost:8100/mcp` |

旧 browser frontend 的环境变量如下，仅供兼容历史实现。Textual TUI 可先直接读取
本地 store/read envelope，后续再切换稳定 API。

```bash
NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL=http://localhost:8201/api/chat
NEXT_PUBLIC_XMUSE_API_BASE_URL=http://localhost:8200/api
NEXT_PUBLIC_XMUSE_MCP_ENDPOINT=http://localhost:8100/mcp
```

## 推荐页面

### `/chat`

主入口，展示 conversation/thread 列表。数据源优先级：

1. `GET /api/chat/threads`：当前最接近前端 thread read model，包含 messages、
   cards、items、recent_cards。
2. `GET /api/chat/conversations`：更原始的 conversation 列表。

### `/chat/:conversation_id`

群聊工作区。建议三列：

- 左侧：conversation 列表、participant 列表、role template 入口。
- 中间：消息流和 compact cards。
- 右侧：worklist 替代视图，先由 lane/dashboard API 聚合得到。

消息数据源：

- `GET /api/chat/conversations/{conversation_id}/messages`
- `POST /api/chat/conversations/{conversation_id}/messages`
- 或兼容旧 UI 的 `POST /api/chat/threads/{conversation_id}/messages`

参与者数据源：

- `GET /api/chat/conversations/{conversation_id}/participants`
- `POST /api/chat/conversations/{conversation_id}/participants`
- `DELETE /api/chat/conversations/{conversation_id}/participants/{participant_id}`

fork 和角色模板：

- `GET/POST /api/chat/conversations/{conversation_id}/forks`
- `GET/POST/PUT/DELETE /api/chat/role-templates`

### `/dashboard`

灰盒入口，不作为用户主流程。建议只从 chat card 或 worklist drill-down 进入。

主要数据源：

- `GET /api/health`
- `GET /api/run-health?conversation_id=...`
- `GET /api/lanes`
- `GET /api/lane-graphs`
- `GET /api/feature-graph-sets`
- `GET /api/dashboard/audit-events`
- `GET /api/dashboard/state-history`
- `GET /api/dashboard/lineage`

### `/dashboard/lanes/:feature_id`

lane 详情页：

- `GET /api/lanes/{feature_id}`

展示 prompt、status/effective_status、logs、gate/review/failure metadata。

### `/dashboard/lane-graphs/:graph_id`

lane graph DAG 详情页：

- `GET /api/lane-graphs/{graph_id}`

展示 graph definition、derived_state、lineage、aggregation。

### `/dashboard/feature-graph-sets/:graph_set_id`

feature graph-set 详情页：

- `GET /api/feature-graph-sets/{graph_set_id}`

这是多 feature 并行能力的核心 drill-down 页面。

## 前端数据模型建议

### Conversation

以 `conversation.id` 作为工作区隔离主键。不要把 lane graph 或 feature id 当成
conversation id。

### Participant / GOD

参与者是 conversation-scoped。显示名优先使用 `display_name`，路由/身份字段
优先使用后端返回的 participant/session id。不要假设一个 feature 对应一个 GOD。

### Message

消息流里应同时支持自然语言消息和结构化 envelope/card。渲染建议：

- `envelope_type` 缺失或为 `message`：普通气泡。
- `mention`：普通气泡加 mention metadata。
- proposal / lane graph / feature graph / run health 等 cards：compact card。
- 未识别 envelope：保留原文，并提供 JSON/debug 折叠区。

### Lane

UI 状态优先使用 `effective_status`，没有时再降级到 `status`。

建议状态分组：

- active: `ready`, `dispatched`, `executed`, `under_review`
- waiting: `awaiting_final_action`, `requeued`
- success: `merged`
- failure: `exec_failed`, `gate_failed`, `terminated`, `failed`

### Worklist

当前有专用只读 worklist endpoint：

```text
GET /api/chat/conversations/{conversation_id}/worklist
```

它返回 `chat_worklist_projection/v1`，包含 `worklist`、`groupchat_worklist`、
`counts`、`source_authority`、`projection_only=true`、`write_capabilities=[]`。
前端应优先使用这个 endpoint 展示右侧 worklist；它不是 truth producer。

若运行在旧后端或 endpoint 不可用，MVP 可临时用以下数据聚合：

1. 读取 `GET /api/lanes`。
2. 按 `conversation_id` 过滤当前 conversation。
3. 优先按 `feature_group` 分组；没有时按 `graph_id` 或 `feature_id` 前缀降级。
4. 每组显示 merged/total 和少量 active/failure lane。
5. 点击 lane 跳转 `/dashboard/lanes/:feature_id`。
6. 点击 graph 跳转 `/dashboard/lane-graphs/:graph_id`。

C-class 后续仍可扩展该 endpoint 的 lane/graph grouping，但不能让前端写入
truth。

## 轮询策略

当前没有 streaming。建议：

- chat messages: tab focused 时 2-3 秒轮询，background 时 20-30 秒。
- run health / lanes: active dashboard 或右侧 worklist 5 秒轮询。
- lane detail logs: 打开详情页时 3-5 秒轮询；离开页面停止。
- audit/history: 手动刷新或 30 秒轮询。

所有轮询都要支持后端未启动时的 degraded UI，避免刷屏报错。

## 当前可用 API 总览

Chat API:

- `POST /api/chat/conversations`
- `GET /api/chat/conversations`
- `GET/POST/DELETE /api/chat/conversations/{conversation_id}/participants`
- `GET/POST /api/chat/conversations/{conversation_id}/forks`
- `GET /api/chat/role-templates`
- `POST /api/chat/role-templates`
- `PUT /api/chat/role-templates/{template_id}`
- `DELETE /api/chat/role-templates/{template_id}`
- `GET/POST /api/chat/conversations/{conversation_id}/messages`
- `POST /api/chat/conversations/{conversation_id}/proposals`
- `POST /api/chat/proposals/{proposal_id}/approve`
- `GET /api/chat/proposals/{proposal_id}`
- `GET /api/chat/resolutions/{resolution_id}`
- `GET /api/chat/threads`
- `POST /api/chat/threads/{conversation_id}/messages`

Dashboard API:

- `GET /api/health`
- `GET /api/run-health`
- `GET/POST /api/lanes`
- `GET /api/lanes/{feature_id}`
- `POST /api/lanes/{feature_id}/approve`
- `POST /api/lanes/{feature_id}/reject`
- `GET /api/sessions`
- `GET /api/errors`
- `GET /api/resolutions`
- `GET /api/verdicts`
- `GET /api/self-evolution`
- `GET /api/self-evolution/audit`
- `GET /api/self-evolution/conversations`
- `GET /api/self-evolution/clarifications`
- `GET /api/dashboard/audit-events`
- `GET /api/dashboard/state-history`
- `GET /api/dashboard/lineage`
- `GET /api/dashboard/peer-chat/conversations`
- `GET /api/dashboard/peer-chat/conversations/{conversation_id}`
- `GET /api/dashboard/peer-chat/conversations/{conversation_id}/lane-graphs/{graph_id}`
- `GET /api/dashboard/peer-chat/conversations/{conversation_id}/feature-graph-sets/{graph_set_id}`
- `GET /api/dashboard/peer-chat/conversations/{conversation_id}/run-health`
- `GET /api/dashboard/peer-chat/conversations/{conversation_id}/execution-cards/{intent_id}`
- `GET /api/dashboard/peer-chat/sessions/{god_session_id}`
- `GET /api/dashboard/peer-chat/requests/{request_id}`
- `GET /api/dashboard/peer-chat/requests/{request_id}/result`
- `GET /api/peer-requests/{request_id}`
- `GET /api/peer-requests/{request_id}/result`
- `GET /api/lane-graphs`
- `GET /api/lane-graphs/{graph_id}`
- `GET /api/feature-graph-sets`
- `GET /api/feature-graph-sets/{graph_set_id}`
- `GET /api/metrics`

## 缺口和前端占位

前端可以先做类型和 UI 占位，但不要假定后端已返回：

- WebSocket/streaming endpoint
- proposal narrow/reject endpoints
- C-class planning run endpoints
- blueprint approved -> autonomous feature plan -> graph-set injection cards
- human review mode 开关
- review GOD failed-lane takeover cards

## 实现原则

- chat 是主界面，dashboard 是 drill-down。
- 默认不把长 prompt、完整日志、gate 输出塞进 chat。
- cards 只显示摘要、状态、下一步和 drill-down href。
- conversation/workspace 隔离必须贯穿筛选、缓存 key、路由参数。
- 对所有 API 响应做宽松解析；xmuse 仍处在迁移期，字段会增加。
- 前端不要直接写 `xmuse/feature_lanes.json` 或 runtime JSON 文件。
