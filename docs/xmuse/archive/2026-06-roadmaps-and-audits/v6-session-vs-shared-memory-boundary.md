# V6 Session vs Shared Memory Boundary Recommendation

更新日期: 2026-06-04

## 依据来源

本 recommendation 基于 V6 Tasks 1-5 的 evidence:

1. **Task 1 (LEGACY-MEMORYOS-COUPLING-INVENTORY)**: 找到 10 个 legacy memoryOS 接缝，确认当前 integration 全在 lane/feature level，无正式群聊 shared memory contract。
2. **Task 2 (CHAT-MEMORY-TAXONOMY-CONTRACT)**: 定义 5 个 scope + 10 个 category 的 chat-memory taxonomy。
3. **Task 3 (SIDECAR-REPLAY-PACKET-CONTRACT)**: 定义 replay packet，支持 message/proposal/blueprint/verdict 的稳定 replay。
4. **Task 4 (GROUPCHAT-REPLAY-EXPORTER)**: 验证可从 chat store 导出 replay packets，不污染 store。
5. **Task 5 (SIDECAR-RECALL-EVAL-HARNESS)**: 验证 baseline recall 可区分 content finding 与 source evidence finding。

## 四类场景边界

### 1. GOD 长 Session Continuity

**结论: 留在 provider session binding，不进 memoryOS。**

| 维度 | 归属 | 理由 |
|------|------|------|
| agent 内部状态 | provider session binding | Codex/OpenCode native session resume 持有未提交变更和工作上下文 |
| provider 特有缓存 | provider session binding | 各 provider 的 CLI-specific 缓存 (model cache, 中间推理状态) |
| 实时进程状态 | provider session binding | PID、live transport、ephemeral thread 由 Ray/session layer 管理 |
| session identity + binding ref | `GodSessionRecord` + `ProviderSessionBindingStore` | 已由 V2/V3 contract 收束 |

**memoryOS 不适用的原因**:
- memoryOS 没有 "live session" 概念，只有 session 内 memory 的持久化
- provider session resume 需要毫秒级恢复，memoryOS build_context 不是实时管道
- 已有 `ProviderSessionBindingStore` 做 durable binding store，不需要 memoryOS 做第二份

### 2. 群聊 Shared Memory

**结论: 适合进 memoryOS sidecar，但需从 V6 独立 sidecar 逐步验证再决定是否主链接入。**

| 子类 | 优先级 | 建议 |
|------|--------|------|
| conversation_summary | P1 | 最自然的 memoryOS candidate。每次群聊里程碑后自动摘要 → memoryOS ingest |
| session_boundary | P1 | 每条 conversation 的创建/重启边界 → memoryOS session 可对齐 |
| blueprint_version | P1 | 已批准的 mission blueprint 是核心 shared memory |
| decision_rationale | P1 | 决策理由最有跨 session 检索价值 |
| feature_plan_ref | P2 | feature plan 已在 graph-native status store，mirror 到 memoryOS 仅用于跨 conversation recall |

**接入策略**:
- 当前不对接 xmuse 主链，保持 V6 sidecar 状态
- 先通过 `ChatReplayExporter` → memoryOS sidecar ingest → recall eval harness 验证 recall 收益
- 只有 recall evals 稳定通过后才能考虑 coordinator-level 接入

### 3. Cross-Restart Recovery

**结论: 双轨保留 — provider session binding 负责绑定恢复，memoryOS sidecar 负责上下文恢复。**

| 恢复层面 | 负责方 | 说明 |
|---------|--------|------|
| provider session binding | `ProviderSessionBindingStore` | runner 重启后查询 compatible binding，resume provider native session |
| 群聊 shared context | memoryOS sidecar | 从 memoryOS 恢复 conversation summary、最近决策、unresolved threads |
| live session transport | Ray/god session layer | 重启后重新 spawn live process，不通过 memoryOS |

**cross_restart_recall scope** (Task 2 taxonomy) 专门为此设计:
- `recovery_checkpoint`: 写入群聊里程碑事件，供重启后 context 重建
- `session_boundary`: 标记会话边界，帮助 memoryOS sidecar 区分"重启前 context"与"重启后新 context"

### 4. Source-Grounded Recommendation

**结论: 必须通过 sidecar contract 而非 memoryOS 隐式推理。**

**原则**:
- memoryOS 是 memory store + retrieve 层，不是 recommendation engine
- 任何 "根据 memory 建议下一步" 的逻辑必须在 xmuse coordinator 层实现
- memoryOS sidecar 只负责: "给定 query，返回匹配的 context items + 对应 source refs"

**当前 V6 侧car 已支持**:
- `ReplayPacketItem` 每个 item 携带 `source_id` + `participant_id` + `timestamp`
- `RecallEvalResult` 明确区分 `found_content` (memoryOS 返回了内容) 与 `found_source_evidence` (内容可追到 source)
- 主链接入时必须保证 source evidence 可追性不丢失

## 完整分配矩阵

| 数据类型 | 应当归属 | 当前状态 | 建议动作 |
|---------|---------|---------|---------|
| agent 内部工作上下文 | provider session binding | ✅ 已有 `ProviderSessionBindingStore` | 继续收束，不引入 memoryOS |
| provider 特有状态 | provider session binding | ⚠️ 部分捕获 | 完善 Codex/OpenCode session id 提取 |
| 实时进程/transport | Ray/god session layer | ✅ 已分离 | 保持现有设计 |
| conversation 摘要 | memoryOS sidecar (P1) | ❌ 未接入 | 通过 V6 sidecar 验证 recall 收益 |
| blueprint 决策 | memoryOS sidecar (P1) | ⚠️ 部分在 lane-level | 通过 V6 sidecar 验证后接入 |
| feature plan 引用 | graph-native status + memoryOS mirror (P2) | ✅ graph-native 已有 | mirror 到 memoryOS 做跨 conversation recall |
| participant 偏好 | memoryOS sidecar (P2) | ❌ 未定义 | 需要 V2 participant profile 落地后对接 |
| unresolved thread | memoryOS sidecar (P2) | ❌ 未定义 | 需要 V2 thread 协议落地后对接 |
| turn budget | 不进 memoryOS | ✅ 已有 | 保持 chat store 内 |
| inbox item 状态 | 不进 memoryOS | ✅ 已有 | 保持 chat store 内 |
| lane memory lesson | legacy lane-memory | ⚠️ 已有 | 保持现状，不与群聊 shared memory 混用 |

## 风险标注

1. **memoryOS v3 composer 的 recall layer 与 xmuse taxonomy 不对齐**: memoryOS 的 `ContextLayerItem` 层 (task/core/recall/archival/recent) 与 xmuse 的 memory scope (conversation_shared/blueprint_decision/participant) 是正交分类。接入时需要 mapping layer。
2. **无 participant-level isolation**: 当前 memoryOS `IdentityScope` 可区分 session/user/agent，但 xmuse 的 participant 概念 (architect/review/execute 角色 + 具体 participant_id) 需要额外 mapping。
3. **eval harness 是 baseline**: Task 5 的 harness 使用 keyword/source matching，不是真实 memoryOS recall pipeline。真实 recall 收益需等 sidecar→memoryOS 实际集成后才能测量。

## 保持独立 sidecar 视角

以上 recommendation 全部来自 V6 独立 sidecar exploration，不要求主链接入。
建议:
- V6 保持 sidecar 状态，继续通过 exporter → memoryOS ingest → recall eval 闭环验证
- 只有 recall evals 稳定证明 memoryOS sidecar 对 xmuse 群聊层有 measurable 收益时，才启动主链接入计划
- 主链接入计划必须保留 source evidence 可追性，不允许黑盒 memoryOS 替代 xmuse artifact authority
