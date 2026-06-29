# V6 Legacy MemoryOS Coupling Inventory

更新日期: 2026-06-04

## 范围

本 inventory 覆盖 xmuse 当前所有直接或间接依赖 memoryOS 的代码路径。目标是区分:
- **legacy lane-memory coupling** (execution plane, 不可直接复用到群聊层)
- **sidecar-reusable infrastructure** (transport, adapter, taxonomy 可复用为 V6 sidecar 基础)
- **not suitable for chat-memory contract** (因 scope 限制或架构假设不能直接当群聊层 memory contract)

## 完整接缝清单

### Seam 1: `MemoryOSClient` — HTTP Transport

**文件**: `src/xmuse_core/agents/memoryos_client.py` (69 行)

**功能**: 薄 HTTP client 封装 memoryOS REST API (`/sessions`, `/sessions/{id}/ingest`, `/sessions/{id}/build-context`)

**分类**: ✅ **sidecar-reusable infrastructure**

**理由**:
- 纯协议层，无 domain 语义
- 降级优雅 (connection error 返回 None/空)
- 可原样复用作 sidecar transport

**限制**:
- 当前只暴露 memoryOS 的 v1/v3 API 子集；未来如果 memoryOS 侧增加新 endpoint，需要同步更新
- 不负责 session lifecycle 管理 (caller 负责)

---

### Seam 2: `MemoryOSStoreAdapter` — Sidecar Adapter

**文件**: `src/xmuse_core/platform/memory_refs.py:100-179`

**功能**: Protocol-based adapter，封装 `remember(lesson)` 和 `build_context(refs, task, budget)`

**分类**: ✅ **sidecar-reusable infrastructure**

**理由**:
- `MemoryOSStoreClient` Protocol 是干净抽象，可替换为 fake/test client
- `remember()` 的 lesson→ingest 模式可直接用于 sidecar ingest
- `build_context()` 的多 session context composition 可用于 eval

**限制**:
- session_id 缓存是 in-memory dict，无持久化；重启后需重新 `_ensure_ref`
- 未适配 group-chat 的多 participant 并发 ingest

---

### Seam 3: `MemoryScope` / `MemoryCategory` — 当前 Taxonomy

**文件**: `src/xmuse_core/platform/memory_refs.py:9-23`

**分类**: ⚠️ **partial — 需要扩展**

**现状**:
- 4 scopes: `CONVERSATION`, `FEATURE`, `PEER`, `GLOBAL`
- 6 categories: `CONVERSATION_SUMMARY`, `BLUEPRINT_DECISION`, `FEATURE_HISTORY`, `REVIEW_REWORK_LESSON`, `PEER_LESSON`, `PLATFORM_LESSON`

**对 V6 的缺口**:
- 缺少 `UNRESOLVED_THREAD` category
- 缺少 `PARTICIPANT_LTM` (participant-specific long-term memory)
- `CONVERSATION` scope 当前是 lane-level 元数据，不是正式群聊 shared memory scope
- 没有 `cross-restart` / `recovery` 相关 category

---

### Seam 4: `MemoryRef` / `MemoryLesson` — Memory Domain Models

**文件**: `src/xmuse_core/platform/memory_refs.py:25-92`

**分类**: ⚠️ **partial — 模式可复用，字段不足**

**现状**:
- `MemoryRef` 有 scope/category/session_id/title/primary_evidence_refs/metadata
- `MemoryLesson` 额外有 summary/source_lane_id
- URI 计算按 scope 规则生成 `memoryos://` 格式

**对 V6 的缺口**:
- 没有 `thread_id` / `parent_message_id` / `in_reply_to` 等群聊结构
- `primary_evidence_refs` 偏 lane artifact ref，不是群聊 message/card ref
- 没有 `ingest_intent` (raw message / decision / summary candidate / unresolved thread)

---

### Seam 5: `AgentSpawner._prepare_memoryos_prompt()` — Context Injection

**文件**: `src/xmuse_core/platform/agent_spawner.py:390-410`

**分类**: ❌ **legacy lane-memory coupling**

**功能**: Lane agent spawn 前创建 memoryOS session + 获取 context，包装为 `<memoryos_context>` XML 注入 prompt

**为什么不能直接用于群聊层**:
- Per-spawn, per-lane session；群聊层需要 persistent shared session
- 注入的是 `<memoryos_context>` XML tag，群聊层需要的 context shape 不同
- 降级策略 (失败时静默跳过) 对群聊 shared memory 不合适

---

### Seam 6: `AgentSpawner._ingest_memoryos_result()` — Result Write-Back

**文件**: `src/xmuse_core/platform/agent_spawner.py:412-435`

**分类**: ❌ **legacy lane-memory coupling**

**功能**: Lane agent 完成后，把 prompt+response ingest 回 memoryOS session

**为什么不能直接用于群聊层**:
- 写入的是一对 user/assistant message，不是结构化的群聊 card/proposal/decision
- 不支持多 participant 并行 ingest
- 截断到 4000 chars，不适合 blueprint 等长文本

---

### Seam 7: `SpawnResult.memoryos_*` 字段

**文件**: `src/xmuse_core/platform/agent_spawner.py:70-73`

**分类**: ✅ **sidecar-reusable (observability)**

**功能**: 记录 memoryos_session_id / context_attached / ingested / degraded_reason

**可复用性**: 作为 sidecar 调试/观测字段的模式可以沿用，但字段名和语义需要重新设计

---

### Seam 8: `memory_update_events.py` — Event-Driven Lesson Builder

**文件**: `src/xmuse_core/platform/memory_update_events.py` (375 行)

**分类**: ✅ **sidecar-reusable pattern**

**功能**:
- `build_memory_lesson_for_event(event, lane)` 根据 planning/review/takeover 事件构造 MemoryLesson
- `build_planning_memory_lesson()`, `build_review_memory_lesson()`, `build_takeover_memory_lesson()`
- `find_matching_memory_ref()`, `upsert_memory_ref()` — CRUD helper

**可复用性**:
- Event → lesson 的模式可以直接用于 V6 sidecar: chat event → replay packet
- Lesson builder 的 source evidence ref 收集逻辑可借鉴

**限制**:
- 所有 builder 都假设输入是 lane dict (`feature_lanes.json` 投影)；V6 需要 chat store 模型作为输入
- 没有为群聊消息/thread/participant 场景设计

---

### Seam 9: `orchestrator_lane_flow.py` Memory Write Path

**文件**: `src/xmuse_core/platform/orchestrator_lane_flow.py:776-806`

**分类**: ❌ **legacy lane-memory coupling**

**功能**: Lane 执行后，调用 `build_memory_lesson_for_event` → `_memory_store.remember()` → `upsert_memory_ref()` → `_sm.update_metadata()`

**为什么不能直接用于群聊层**:
- 耦合在 `dispatch_lane` flow 中，不是独立 sidecar ingest path
- 写入的是 lane metadata (`feature_lanes.json`)，不是 chat store
- 单一路径，没有 group-chat shared memory 的多对多模型

---

### Seam 10: `PlatformOrchestrator._memory_store`

**文件**: `src/xmuse_core/platform/orchestrator.py:416-417`

**分类**: ❌ **legacy lane-memory coupling**

**功能**: 持有 `MemoryOSStoreAdapter` 实例，仅当 `memoryos_client` 注入时启用

**为什么不能直接用于群聊层**:
- 作用域是 orchestrator 级别，不在 chat service 或 peer service 中
- 只在 lane flow 中被消费
- Optional — 没有 memoryos_client 时完全跳过

---

## 分类汇总

| 分类 | 接缝 | 文件 |
|------|------|------|
| ✅ sidecar-reusable | MemoryOSClient | `agents/memoryos_client.py` |
| ✅ sidecar-reusable | MemoryOSStoreAdapter | `platform/memory_refs.py` |
| ✅ sidecar-reusable 可观测字段模式 | SpawnResult.memoryos_* | `platform/agent_spawner.py` |
| ✅ sidecar-reusable pattern | memory_update_events 模式 | `platform/memory_update_events.py` |
| ⚠️ 需扩展 | MemoryScope/Category taxonomy | `platform/memory_refs.py` |
| ⚠️ 需扩展 | MemoryRef/Lesson 模型 | `platform/memory_refs.py` |
| ❌ legacy lane-memory | _prepare_memoryos_prompt | `platform/agent_spawner.py` |
| ❌ legacy lane-memory | _ingest_memoryos_result | `platform/agent_spawner.py` |
| ❌ legacy lane-memory | orchestrator_lane_flow memory write | `platform/orchestrator_lane_flow.py` |
| ❌ legacy lane-memory | PlatformOrchestrator._memory_store | `platform/orchestrator.py` |

## 对 V6 的建议

1. **复用**: `MemoryOSClient` 和 `MemoryOSStoreAdapter` 可原样或小幅调整复用为 sidecar 的 transport/adapter 层。
2. **借鉴**: `memory_update_events.py` 的 event→lesson builder 模式是 V6 replay packet builder 的天然起点。
3. **新建 taxonomy**: 现有 `MemoryScope`/`MemoryCategory` 虽然已有 conversation/blueprint 概念，但不足以覆盖群聊 shared memory，需在 V6 task 2 中定义独立的 chat-memory taxonomy。
4. **不碰**: `_prepare_memoryos_prompt` / `_ingest_memoryos_result` / `orchestrator_lane_flow` 的 memory write 路径保持不动，V6 不做任何改动。
