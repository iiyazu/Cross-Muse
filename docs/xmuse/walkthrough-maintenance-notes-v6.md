# xmuse Walkthrough Maintenance Notes V6

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的 xmuse 群聊层 x memoryOS 独立 sidecar 交接文档。

它只覆盖一条并行线:

- 基于 xmuse 群聊层当前实现与 `V2` 群聊愿景，结合 memoryOS 当前正式实现，摸索一套 chat-memory sidecar；先做 taxonomy、contract、replay、eval 和 integration recommendation，暂不接入 xmuse authority 主链

它不覆盖:

- xmuse peer chat 主链协议
- provider/runtime 决策主链
- graph-native authority 主链
- TUI 输入/焦点/补全主链
- operator / observability 主目标
- memoryOS 内核、store schema、public behavior 的直接改造

这些仍分别以 `walkthrough-maintenance-notes-v2.md`、
`walkthrough-maintenance-notes-v3.md`、
`walkthrough-maintenance-notes-v4.md` 和 memoryOS 当前正式实现为准。

## 任务形态

`V6` 不是短平快任务线，而是一条长时间探索线。默认要求:

1. 目标执行时长按长时 goal 设计，硬约束为 `10h`。
2. 允许在 `V6` 边界内自主探索、回退、重切任务顺序，但必须持续受本文档约束。
3. 默认保持实现独立:
   - 不直接耦合改 xmuse 主链
   - 不直接耦合改 memoryOS 主线
   - 优先产出 sidecar contract、fixtures、replay、eval、recommendation

`V6` 的目标不是“尽快接上 memoryOS”，而是用 10h 级别探索，把 xmuse 群聊层真正需要的 memory boundary 摸清，并给出不污染主链的证据化结论。

## 使用规则

1. `V6` 只能做独立 sidecar 探索，不得直接改 xmuse authority 或 memoryOS 主线行为。
2. 一次只做一个任务。
3. 只读当前任务列出的文件；没有进入当前任务的文件，默认不读不改。
4. 默认只在 xmuse 侧新增 sidecar 代码、fixtures、tests、docs；默认不写 memoryOS repo。
5. 如果发现 memoryOS 当前 API/contract 不足，只允许记录为 upstream gap，不允许在同一轮直接改 memoryOS 主实现。
6. 不得为了 memory 接入便利而新增 xmuse 后端语义特判。
7. 不得把 memoryOS sidecar 结果写成 xmuse authority source。
8. 每轮必须满足该任务自己的强 gate，才算完成。
9. 每轮完成后，只更新:
   - 本文档对应任务的 `当前收敛状态`
   - `docs/xmuse/codex-strengthening-handoff.md` 的本轮收口记录
10. 因为 `V6` 可能交给较弱模型执行，默认采用强流程约束：
   - 每个任务开始前，必须先做一次 `superpowers:brainstorming`
   - 涉及 taxonomy、schema、replay、eval、adapter 的任务，默认按 `superpowers:test-driven-development` 执行
   - 宣称完成前，必须按 `superpowers:verification-before-completion` 跑 gate
11. `subagent` 默认禁用；只有任务明确标注“可并行子任务”时，才允许启用，而且必须满足：
   - 子任务之间没有共享编辑文件
   - 子任务不决定 authority、runtime 或 memoryOS 正式语义
   - 子任务只做测试、夹具、只读审计或独立 sidecar 小模块实验
   - 同一轮最多启用 1 个 subagent
   - 主 agent 负责最终整合、验证与 handoff
12. 允许读取 `/home/iiyatu/projects/python/memoryOS` 当前正式实现，但必须遵守:
   - 以源码和正式文档为准，不看历史草案决定行为
   - 只把 memoryOS 当作 sidecar 依赖，不把它当 xmuse 的 authority replacement
13. 参考 memoryOS 时，必须在本轮 handoff 写明:
   - 参考了哪些文件
   - 借鉴的是哪条 contract / recall / context 约束
   - 为什么没有直接把 memoryOS 现状嵌进 xmuse 主链
14. `V6` 允许实时监控 `V2` 的最新实现收敛情况，并据此调整 `V6` 任务顺序、taxonomy、replay packet shape、eval query 集，但必须遵守:
   - 只能根据 `V2` 已落地源码和已更新文档调整
   - 不得反向要求 `V2` 为 `V6` 改协议
   - 每次调整都必须在 handoff 中写明“观察到的 V2 变化 -> V6 调整”
15. 若 `V2` 或 memoryOS 的最新实现变化使当前 `V6` 假设失效，允许在 `V6` 内回退到前置任务重做 contract / replay / eval，但不得顺手改主链实现。

## 长时探索约束

`V6` 必须按长时 goal 方式执行，而不是单轮小修小补。默认约束如下:

1. 硬预算: `10h`。
2. 每个阶段结束时都要保留可继续接力的中间产物:
   - 当前已验证结论
   - 当前未解问题
   - 下一阶段推荐入口
3. 允许在任务 1-6 之间迭代往返，不要求一次线性做完，但任何回退都要有明确原因。
4. 长时探索的自由度只体现在:
   - 可以根据 `V2` 最新实现调整边界判断
   - 可以根据 replay / eval 结果修正 taxonomy
   - 可以新增 sidecar fixture / eval case
   不体现在:
   - 任意改 xmuse 主链
   - 任意改 memoryOS 主线
   - 把未证实想法写成集成结论
5. 任一阶段如果发现“只有改 xmuse 或 memoryOS 主实现才能继续”，必须先记录 blocker 和 recommendation，再停止该路径，不得直接改主链。

## 弱模型执行协议

每个任务都按下面顺序执行，不允许跳步:

1. 只读当前任务列出的文件，外加它直接依赖、且为了通过 gate 不可避免的测试文件。
2. 先做一次 `superpowers:brainstorming`，只产出四项结论:
   - 本轮唯一任务边界
   - 本轮允许改动的文件
   - 本轮 gate 映射到哪些测试或验证动作
   - 本轮明确不做什么
3. 对 taxonomy、schema、adapter、replay、eval 的改动，必须使用
   `superpowers:test-driven-development`：
   - 先写 focused test
   - 先跑出预期 RED
   - 再做最小实现到 GREEN
4. 完成实现后，必须用 `superpowers:verification-before-completion` 跑 fresh gate。
5. gate 未全部通过时，不得宣称任务完成，不得切下一个任务。

如果 `brainstorming` 得出的结论需要改 xmuse authority、改 runtime path、改 memoryOS
正式行为、或扩大到 `V2/V3/V4` 主线，立即停止当前任务，并在 handoff 里记为越界，不继续实现。

## 自主探索边界

`V6` 允许比 `V2/V3/V4/V5` 更高的自主探索度，但探索只能发生在以下范围内:

1. 观察 xmuse `V2` 最新实现，修正 group-chat memory needs 的理解。
2. 观察 memoryOS 当前正式实现，修正 ingest / recall / context contract 的可行边界。
3. 重排 `V6` 内部任务顺序，例如:
   - 先补 replay packet，再回头修 taxonomy
   - 先做小规模 eval，再决定 replay exporter 细节
4. 新增 sidecar 层的:
   - fixtures
   - replay packets
   - eval queries
   - recommendation reports

以下探索明确禁止:

1. 为了验证想法，直接把 memoryOS 接到 xmuse authority 主路径。
2. 为了验证想法，直接修改 memoryOS v3 composer、recall pipeline、store schema。
3. 把 lane memory / feature memory 的现有 legacy coupling 偷偷升级成群聊层正式方案。
4. 以“未来可能需要”为理由，提前改 `V2` 群聊协议。

## subagent 硬边界

`subagent` 不是默认能力，只是少数任务的辅助工具。弱模型执行时必须遵守:

1. 只有当前任务写了“可并行子任务”，才允许启用。
2. 同一轮最多 1 个 subagent。
3. 默认不要启用 `superpowers:subagent-driven-development`；只有当前任务明确允许，
   且主 agent 已经先完成本轮边界判定时，才可局部使用其思路。
4. subagent 只允许做下列事情之一:
   - 只读审计
   - 补测试或测试脚手架
   - 独立 sidecar schema / replay packet 的局部实验
5. subagent 不允许:
   - 修改 xmuse authority source
   - 修改 provider/runtime 决策逻辑
   - 修改 memoryOS 主线实现
   - 修改任何 `V2/V3/V4` 主线语义
6. 如果 subagent 产出与主 agent 将要编辑的文件重叠，立刻取消该并行方案，回到主 agent 单线程收束。
7. 最终代码、测试、验证、handoff 一律由主 agent 负责；不得把 subagent 的“已完成”直接当成完成事实。

## 统一验收与汇报格式

每轮任务结束时，handoff 至少要写清楚:

1. 本轮唯一任务名。
2. 实际修改的文件列表。
3. 新增或修改了哪些 tests / fixtures / docs / sidecar modules。
4. `brainstorming` 结论中的四项边界是否仍成立。
5. fresh verification 命令与结果:
   - focused tests
   - 受影响的 sidecar / replay / eval / memory-ref tests
   - `ruff check` 或等价静态检查
   - `git diff --check`
6. 逐条对照当前任务 `强 gate`，说明每条 gate 由哪条测试或验证动作覆盖。
7. 明确写出本轮没有扩到的能力点。
8. 如果遇到 memoryOS upstream gap，明确写出:
   - 缺的是哪条 API / contract / context shape
   - 当前为什么只能 sidecar 规避，不能主链解决

没有这些证据，本轮视为未完成。

## 统一质量 gate

除各任务自己的 `强 gate` 外，每轮还必须同时满足下面四条:

1. 有 fresh test evidence；不能只凭人工操作或旧日志宣称通过。
2. 新增行为至少有一个 focused regression test；replay / eval 类任务通常还应有 fixture-level 或 smoke-level 覆盖。
3. 不新增任何 `V2/V3/V4` 后端语义特判，不把 memory convenience 写成 authority。
4. sidecar 产物必须保留 source-grounded evidence 边界；不能让“只有 memory 里有、源码和 artifact 里不可追”的结论进入建议主链。

## 任务总览

按推荐顺序执行:

1. `LEGACY-MEMORYOS-COUPLING-INVENTORY`
2. `CHAT-MEMORY-TAXONOMY-CONTRACT`
3. `SIDECAR-REPLAY-PACKET-CONTRACT`
4. `GROUPCHAT-REPLAY-EXPORTER`
5. `SIDECAR-RECALL-EVAL-HARNESS`
6. `SESSION-VS-SHARED-MEMORY-BOUNDARY`
7. `INDEPENDENT-SIDECAR-SMOKE`

---

## 任务 1: `LEGACY-MEMORYOS-COUPLING-INVENTORY`

### 非生产级实现事实

- xmuse 当前已经有一批旧式 memoryOS 接缝：
  - `xmuse_core.agents.memoryos_client.MemoryOSClient`
  - `xmuse_core.platform.memory_refs.MemoryOSStoreAdapter`
  - `AgentSpawner` 的 `<memoryos_context>` 注入
  - `PlatformOrchestrator` 的 lane-level memory lesson 写入
- 这些接缝主要是 lane / peer / feature 级别，偏 execution plane，不是正式的 group-chat shared memory contract。

### 生产级目标

先把“现有 memoryOS 接缝”做成可审计 inventory，明确:

- 哪些是现有 legacy coupling
- 哪些可复用为 V6 sidecar 基础
- 哪些不能直接拿来当群聊层 memory contract

### 只读这些文件

- `src/xmuse_core/platform/memory_refs.py`
- `src/xmuse_core/agents/memoryos_client.py`
- `src/xmuse_core/platform/agent_spawner.py`
- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_memory_refs.py`
- `tests/xmuse/test_memory_update_events.py`
- `tests/xmuse/test_platform_agent_spawner.py`
- `tests/xmuse/test_memoryos_client.py`

### 本轮要解决的缺口

- 当前代码里已经有 memoryOS sidecar 雏形，但它的定位不清晰，容易被误认成群聊记忆正式方案。

### 强 gate

- inventory 能明确区分 legacy lane-memory coupling 与目标 chat-memory sidecar。
- 文档或测试能证明当前 legacy 路径仍保持现状，不被 V6 偷偷重定义。
- 不新增新的 runtime coupling。

### 禁止扩面

- 不改现有 lane memory 行为。
- 不改 `MemoryOSClient` public behavior。

### 当前收敛状态

- 已审计全部 10 个 legacy memoryOS 接缝，产出 `docs/xmuse/v6-legacy-coupling-inventory.md`。
- 明确分类: 3 个 sidecar-reusable, 2 个需扩展, 5 个 legacy lane-memory coupling。
- 未新增任何 runtime coupling；未改任何 `.py` 文件。
- inventory 确认 `memory_update_events.py` 的 event→lesson 模式是 V6 replay packet builder 的天然起点。

---

## 任务 2: `CHAT-MEMORY-TAXONOMY-CONTRACT`

### 非生产级实现事实

- xmuse `V2` 已有群聊层愿景，但还没有正式的 chat-memory taxonomy。
- 当前 `MemoryScope` / `MemoryCategory` 偏 lane / feature / peer lesson，不足以直接覆盖：
  - conversation shared memory
  - blueprint decisions
  - unresolved threads
  - participant-specific long-term memory
- memoryOS 当前正式实现以 v3 composer + recall pipeline 为准，也没有 xmuse-specific chat-memory taxonomy。

### 生产级目标

定义 xmuse 群聊层的最小 memory taxonomy 和 sidecar contract，至少覆盖:

- conversation shared memory
- blueprint / decision memory
- participant memory
- unresolved thread memory
- cross-restart recall need

### 只读这些文件

- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `src/xmuse_core/platform/memory_refs.py`
- `tests/xmuse/test_memory_refs.py`
- `/home/iiyatu/projects/python/memoryOS/docs/source-guide.md`
- `/home/iiyatu/projects/python/memoryOS/docs/non-production-implementation-notes.md`
- `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/v3_contracts.py`

### 本轮要解决的缺口

- 还没有一个正式 contract 告诉 xmuse 群聊层：什么该进 shared memory，什么不该进。

### 强 gate

- taxonomy 至少能覆盖 conversation / blueprint / participant / unresolved thread 四类核心 memory need。
- scope、category、source evidence 要求清晰可测。
- taxonomy 不要求直接改 memoryOS 或 xmuse 主线。

### 禁止扩面

- 不直接把 taxonomy 写进 xmuse runtime 主路径。
- 不改 memoryOS store schema。

### 可并行子任务

- 允许 1 个 subagent 只读审计 memory need 覆盖空洞，不改生产实现。

### 当前收敛状态

- chat-memory taxonomy 已定义，覆盖 5 个 scope + 10 个 category。
  - `ChatMemoryScope`: conversation_shared / blueprint_decision / participant / unresolved_thread / cross_restart_recall
  - `ChatMemoryCategory`: conversation_summary / blueprint_version / decision_rationale / feature_plan_ref / participant_preference / participant_history / thread_question / thread_decision_pending / recovery_checkpoint / session_boundary
- `SourceEvidence` contract 定义了 source_type / source_id / conversation_id / participant_id / timestamp / thread_id / evidence_uri。
- 所有 builders 已绑定 scope→category 映射，非法组合在 schema 层被拒绝。
- focused tests 20 passed; ruff check passed; golden fixture 已写入 `tests/fixtures/xmuse/contracts/artifacts/chat_memory_taxonomy.v1.json`。
- 不修改 xmuse 或 memoryOS 主线任何文件。

---

## 任务 3: `SIDECAR-REPLAY-PACKET-CONTRACT`

### 非生产级实现事实

- xmuse 有 transcript、cards、proposal、blueprint、participant/inbox 等现成信息源。
- 但没有一套正式 replay packet contract，把这些群聊事实稳定导出给 memoryOS sidecar ingest。

### 生产级目标

定义 chat-memory replay packet contract，至少包含:

- stable packet id
- conversation / participant / thread scope
- source artifact refs
- temporal ordering
- ingest intent: raw message / decision / summary candidate / unresolved thread

### 只读这些文件

- `src/xmuse_core/chat/store.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/participant_store.py`
- `tests/xmuse/test_peer_chat_service.py`
- `tests/xmuse/test_peer_chat_store.py`
- `tests/fixtures/xmuse/contracts/**`
- `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/schemas.py`

### 本轮要解决的缺口

- 没有稳定 packet contract，就无法做真正可复现的 replay / eval。

### 强 gate

- replay packet contract 能稳定表示 transcript / card / proposal / blueprint 派生的 memory ingest 候选。
- packet 明确保留 source refs 和 timestamps。
- contract 为 read/replay 用，不直接驱动 runtime 写入。

### 禁止扩面

- 不新增 chat store 主表字段。
- 不把 replay packet 直接写成生产事件流。

### 当前收敛状态

- replay packet contract 已定义，含 `ReplayPacket` + `ReplayPacketItem` + `IngestIntent`。
  - Packet: packet_id (stable), conversation_id, ingest_intent, scope_note, items (chronological), created_at
  - Item: source_type (message/card/proposal/blueprint/verdict/artifact), source_id, conversation_id, participant_id, content, timestamp, thread_id, envelope_type, metadata
  - IngestIntent: raw_message / decision / summary_candidate / unresolved_thread / blueprint_version / participant_note
  - Builder helpers: `build_message_item()`, `build_proposal_item()`, `build_replay_packet()`
- `source_type_for_envelope()` 提供 envelope→source_type 映射。
- focused tests 14 passed; ruff check passed; golden fixture 已写入 `tests/fixtures/xmuse/contracts/artifacts/chat_replay_packet.v1.json`。
- 不新增 chat store 主表字段，不把 replay packet 写成生产事件流。

---

## 任务 4: `GROUPCHAT-REPLAY-EXPORTER`

### 非生产级实现事实

- 当前没有把真实群聊链路稳定导出成 memory replay packets 的 sidecar exporter。
- 现有 fixtures 更偏 platform / contract / operator，不够聚焦 group-chat memory replay。

### 生产级目标

实现独立 exporter，把群聊层已有事实导出为 V6 replay packets，供 memoryOS sidecar ingest / eval 使用。

### 只读这些文件

- `src/xmuse_core/chat/store.py`
- `src/xmuse_core/chat/peer_proposals.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/knowledge/**`
- `tests/xmuse/test_peer_chat_end_to_end.py`
- `tests/xmuse/test_chat_blueprint_revision.py`
- `tests/xmuse/test_chat_review_trigger.py`

### 本轮要解决的缺口

- 即使 taxonomy 和 packet contract 定下来了，也还没有 exporter 能把真实群聊链路喂给 sidecar。

### 强 gate

- 给定一条真实或 fixture 化的群聊链路，exporter 能稳定导出 replay packets。
- exporter 输出顺序、id、scope、source refs 可重复。
- exporter 失败时不污染 chat store 或 runtime state。

### 禁止扩面

- 不把 exporter 挂进在线群聊主链。
- 不要求实时接入 memoryOS。

### 当前收敛状态

- `ChatReplayExporter` 已实现，接受 `ChatStore` 输入，导出 `list[ReplayPacket]`。
  - 读取 conversation 所有 messages + proposals + resolutions + cards，转换为 ReplayPacketItem
  - source_type 映射覆盖: conversation cards (19 种 card_type), resolutions (blueprint/proposal 派生)
  - 输出按 timestamp 排序，packet_id 等完全由内容决定
  - 不写 chat store、不污染 runtime state
- `export_all_conversations()` 批量导出所有 conversation 的 replay packets。
- focused tests 10 passed; ruff check passed; 失败路径 (unknown conversation) 返回空列表。

---

## 任务 5: `SIDECAR-RECALL-EVAL-HARNESS`

### 非生产级实现事实

- 现有 memoryOS 评测关注 memoryOS 自身，不面向 xmuse 群聊层 memory needs。
- xmuse 也没有独立 harness 来回答：对群聊问题，memoryOS sidecar 到底能否找回有用信息。

### 生产级目标

建立独立 recall eval harness，至少验证:

- conversation-level recall
- blueprint decision recall
- participant-specific recall
- unresolved-thread recall
- source attribution 可追性

### 只读这些文件

- `tests/fixtures/xmuse/**`
- `tests/xmuse/test_peer_chat_end_to_end.py`
- `tests/xmuse/test_memory_refs.py`
- `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/context_composer.py`
- `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/retrieval/recall_pipeline.py`
- `/home/iiyatu/projects/python/memoryOS/docs/source-guide.md`

### 本轮要解决的缺口

- 当前没有证据说明 memoryOS sidecar 对 xmuse 群聊层 recall 是否真的有帮助。

### 强 gate

- harness 能对至少一组 replay data 跑出可复现 recall 结果。
- 评测能区分“找到了内容”和“找到了可追 source evidence”。
- harness 结果不会被误读为主链已可用。

### 禁止扩面

- 不把 eval harness 当成生产 runtime。
- 不直接宣传主链接入完成。

### 可并行子任务

- 允许 1 个 subagent 只补 eval fixture 或 focused tests，不改主实现。

### 当前收敛状态

- `ChatRecallEvalHarness` 已建立，基于 baseline keyword + source matching 算法。
- `RecallQuery` / `RecallEvalResult` / `RecallEvalScore` 定义了 query→result→score 全链路。
- `default_accuracy_gate()` 提供最小 pass_rate gate (默认 50%)。
- `derive_recall_queries_from_packets()` 从 replay packet 内容自动生成含 evidence expectation 的 query，
  不再使用空默认值。支持 stop-word 过滤、关键词提取、自动问题生成。
- harness 明确区分"found_content"与"found_source_evidence"两个维度。
- 这是 contract/evidence smoke harness，不是语义 recall eval。baseline 算法仅做 keyword/substring 匹配，
  不模拟 memoryOS recall pipeline。
- focused tests 22 passed; ruff check passed。

---

## 任务 6: `SESSION-VS-SHARED-MEMORY-BOUNDARY`

### 非生产级实现事实

- xmuse 当前同时有 CLI session continuity 的需求，也有 shared long-term memory 的需求。
- 但两者边界尚未正式收束，容易出现“什么都交给 memoryOS”或“什么都留在 provider session”两种极端。

### 生产级目标

基于前面 taxonomy、replay、eval 的结果，给出明确边界建议:

- 哪些必须留在 provider session continuity
- 哪些适合进 memoryOS shared sidecar
- 哪些需要双轨保留
- 哪些暂时不值得进入 memoryOS

### 只读这些文件

- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/walkthrough-maintenance-notes-v6.md`
- `src/xmuse_core/agents/god_session_layer.py`
- `src/xmuse_core/agents/god_session_registry.py`
- `src/xmuse_core/platform/memory_refs.py`
- `/home/iiyatu/projects/python/memoryOS/docs/source-guide.md`
- `/home/iiyatu/projects/python/memoryOS/docs/memoryos-kernel-agent-handoff.md`

### 本轮要解决的缺口

- 没有正式边界建议，就无法知道未来该如何把 session continuity 和 shared memory 分工。

### 强 gate

- 边界建议必须能解释至少四类场景：
  - god 长 session continuity
  - 群聊 shared memory
  - cross-restart recovery
  - source-grounded recommendation
- recommendation 必须以前面 replay / eval 结果为依据，不凭空拍脑袋。
- 结论仍保持独立 sidecar 视角，不要求主链接入。

### 禁止扩面

- 不直接改 session binding 主链。
- 不直接把 recommendation 写成 runtime policy。

### 当前收敛状态

- `docs/xmuse/v6-session-vs-shared-memory-boundary.md` 已产出，基于 Tasks 1-5 的证据。
- 四类场景有明确结论:
  - GOD session continuity → provider session binding
  - 群聊 shared memory → memoryOS sidecar (P1)
  - cross-restart recovery → 双轨 (binding store + memoryOS context)
  - source-grounded recommendation → sidecar contract (不通过 memoryOS 隐式推理)
- 完整分配矩阵覆盖 11 种数据类型，标注 each 的当前状态与建议动作。
- 不修改 xmuse 主链或 memoryOS 主实现。

---

## 任务 7: `INDEPENDENT-SIDECAR-SMOKE`

### 目标

把前述所有 V6 任务合起来做一次独立 sidecar 收口。

### 真实链路

至少覆盖:

1. 识别 legacy memoryOS coupling
2. 定义并验证 chat-memory taxonomy
3. 生成 replay packet contract
4. 从一条群聊链路导出 replay packets
5. 用 replay packets 驱动 memoryOS sidecar recall eval
6. 输出 session vs shared memory boundary recommendation

### 强 gate

- 全链路不依赖直接修改 memoryOS 主实现。
- 不因 `V6` 变更破坏 `V2/V3/V4/V5` 已有目标和验收边界。
- sidecar 结果能回答“memoryOS 是否适合作为 xmuse 群聊 shared memory 的一部分，以及边界在哪里”。
- 本轮 smoke 暴露出的 P0/P1 问题，必须回流到前面对应任务继续修，不允许只记录不处理。
- 最后一轮 smoke 通过前，至少要有:
  - 相关 focused tests 全绿
  - sidecar / replay / eval tests 全绿
  - `ruff check` 与 `git diff --check` 全绿

### 终止条件

满足以下全部条件时终止:

1. 任务 1-5 的强 gate 全部通过。
2. 任务 6 的 boundary recommendation 已经有明确、基于证据的结论。
3. `INDEPENDENT-SIDECAR-SMOKE` 完成至少一次 fresh run 通过。
4. smoke 暴露出的新问题如果属于已有任务范围，已经在同一轮或后续轮修回并重新验证。
5. 最后一轮通过时:
   - 无新增 P0/P1 sidecar blocker
   - 无因为 memory convenience 引入的 xmuse authority 特判
   - 无必须修改 memoryOS 主实现才能继续的未记录 blocker
   - 无“只有 memory 里有，但 source evidence 不可追”的关键建议
6. 最后一轮 handoff 能让下一个较弱模型只读对应任务和 handoff，就继续安全推进，不需要重新全局探索。

### 当前收敛状态

- V6 全链路独立 sidecar smoke 已通过。
  - exporter → replay packets → recall eval → boundary gate 闭环验证通过 (6 focused tests)
  - 90 sidecar tests + 23 legacy regression tests 全部通过
  - ruff check 全部通过
- Tasks 1-6 强 gate 全部满足。
- Task 6 boundary recommendation 有明确证据化结论。
- 无 P0/P1 sidecar blocker。
- 无因为 memory convenience 引入的 xmuse authority 特判。
- 无必须修改 memoryOS 主实现才能继续的未记录 blocker。
- 无"只有 memory 里有，但 source evidence 不可追"的关键建议。

### 后续扩展: MemoryOS Offline Adapter + Source-Grounded Recall Lab

完成: 新增三个 sidecar 模块:

| 模块 | 文件 | 功能 |
|------|------|------|
| Adapter Contract | `memoryos_adapter.py` | `MemoryOSSidecarAdapter` Protocol, `SidecarIngestRecord`, `SidecarRecallRequest/Result`, `FakeMemoryOSSidecarAdapter`, `LiveMemoryOSSidecarAdapter` (env-gated) |
| Ingest Projection | `ingest_projection.py` | `project_item()` / `project_packets()` — replay packet item → ingest record, preserves source evidence, taxonomy scope, ingest intent |
| Recall Lab | `recall_lab.py` | `SourceGroundedRecallLab`, `run_recall_lab()` — ingest + query + report; `RecallLabReport` with content_hit/source_evidence_hit/missing_evidence |

设计要点:
- FakeAdapter 基于 in-memory dict，关键词匹配 + source evidence 追踪
- LiveAdapter 包装 httpx 调用 memoryOS REST API，仅当显式 env 开启时使用
- 所有默认测试不依赖 live memoryOS
- 投影不静默丢弃 evidence — 所有 valid PacketSourceType 都有对应映射
- 报告中明确区分 content_hit 与 source_evidence_hit，missing_evidence 在 content_hit 但证据不匹配时标记
- 总共 19 focused tests + 1 smoke test

---

## 当前优先级

建议后续优先按下面顺序继续收敛:

1. `LEGACY-MEMORYOS-COUPLING-INVENTORY`
2. `CHAT-MEMORY-TAXONOMY-CONTRACT`
3. `SIDECAR-REPLAY-PACKET-CONTRACT`
4. `GROUPCHAT-REPLAY-EXPORTER`
5. `SIDECAR-RECALL-EVAL-HARNESS`
6. `SESSION-VS-SHARED-MEMORY-BOUNDARY`
7. `INDEPENDENT-SIDECAR-SMOKE`

## 与 V2 / V3 / V4 / V5 / memoryOS 的关系

- `V2` 是 xmuse 群聊与后端主链协议线。
- `V3` 是 TUI 客户端交互基建线。
- `V4` 是 operator / observability / diagnostics 只读平面。
- `V5` 是 contract / fixture / boundary / export / replay governance 平面。
- `V6` 是 xmuse 群聊层 x memoryOS 的独立 sidecar 探索线。
- `V6` 默认只在 xmuse 侧落实现和评测，不直接修改 memoryOS 主线。
- `V6` 不得反向改变 `V2`、`V3`、`V4`、`V5` 或 memoryOS 当前正式实现的目标、顺序和验收逻辑。
