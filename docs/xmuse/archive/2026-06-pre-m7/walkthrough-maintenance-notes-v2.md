# xmuse Walkthrough Maintenance Notes V2

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的渐进式交接文档，不是 walkthrough。

它只做三件事:

- 标记当前仍属非生产级的实现部分
- 给出对应的生产级落地目标
- 把这些缺口拆成可单轮收束、可强 gate 验收的任务

## 使用规则

1. 一次只做一个任务。
2. 只读当前任务列出的文件；没有进入当前任务的文件，默认不读不改。
3. 不顺手扩第二个能力点，不做“顺便重构”。
4. 每轮必须满足该任务自己的强 gate，才算完成。
5. 每轮完成后，只更新:
   - 本文档对应任务的 `当前收敛状态`
   - `docs/xmuse/codex-strengthening-handoff.md` 的本轮收口记录
6. 如果某轮发现上游协议不成立，只允许回退到该任务声明的前置任务，不允许横向扩面。
7. 必要时允许参考 `/home/iiyatu/clowder-ai` 源码，但仅限:
   - 借鉴群聊产品层、协议层、thread/participant 组织方式
   - 帮助判断 xmuse 缺口的目标形态
   不能直接复制其 runtime、实现细节或引入与 xmuse 主链无关的能力。
8. 参考 `clowder-ai` 时，必须在本轮 handoff 中写明:
   - 参考了哪些文件
   - 借鉴的是哪条协议/产品约束
   - 为什么没有直接照搬实现

## 任务总览

按推荐顺序执行:

1. `CHAT-BOOTSTRAP`
2. `CHAT-DEFAULT-INTAKE`
3. `CHAT-REVIEW-TRIGGER`
4. `CHAT-STRUCTURE-ESCALATION`
5. `CHAT-BLUEPRINT-REVISION`
6. `PEER-PROVIDER-PARITY`
7. `PEER-CROSS-RESTART`
8. `NATIVE-HISTORICAL-ISOLATION`
9. `DEGRADATION-BRIDGE-REMOVAL`
10. `FEATURE-LANES-HISTORICAL-ISOLATION`
11. `FULL-CHAIN-REAL-RUN`

---

## 任务 1: `CHAT-BOOTSTRAP`

### 非生产级实现事实

- `POST /api/chat/conversations` 当前只创建 conversation，并写入 initial participants。
- 默认初始化只是插入 `architect / review / execute` 三个 participant。
- `init god` 虽有独立 participant/session 概念，但不会在建群时自动拉起。
- `fork_participant(...)` 已存在，但它是独立动作，且前提是 source peer 已有 session record。
- participant API 形状带有 `provider_id / profile_id / cli_kind`，但 peer chat participant runtime 当前仍是 codex-only。

### 生产级目标

把“建群”从静态 seed 收束为单一 bootstrap path:

`create conversation -> ensure init god session -> collect bootstrap context -> produce participant/fork plan -> instantiate peers -> emit bootstrap artifact/card`

### 只读这些文件

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/participant_store.py`
- `src/xmuse_core/chat/peer_forks.py`
- `src/xmuse_core/agents/god_session_registry.py`

### 本轮要解决的缺口

- 建群不是 runtime bootstrap，而只是数据 seed。
- 预制模式不是 bootstrap plan，只是一组默认 participant。

### 强 gate

- 建群后存在可审计 bootstrap artifact 或 card。
- `init god` session 已真实建立，不再只是 participant 记录存在。
- 预制模式通过单一 bootstrap path 落地，而不是外层脚本拼装。
- 失败中断后 rerun 不产生重复 participant / duplicate init session / fork lineage 污染。

### 禁止扩面

- 不做 provider parity。
- 不做跨重启恢复。
- 不改 execution/review plane。

### 当前收敛状态

- `POST /api/chat/conversations` 已切到 `PeerChatService.create_conversation()` 的单一
  bootstrap path，不再由 API 层直接 seed participants。
- bootstrap 会为 conversation 自动确保唯一 `init` participant 与真实
  `init god` session，并对重复/冲突 session 做 identity 校验。
- 默认 `architect / review / execute` 预制模式已通过同一 bootstrap path
  做 participant plan -> instantiate -> artifact 落地。
- bootstrap 会写入可审计 artifact:
  `artifacts/chat_bootstrap/<conversation_id>.json`。
- 对同一 conversation 重跑 bootstrap 时：
  - 不重复创建默认 participant
  - 不重复创建 init session
  - 不产生 fork lineage 污染
- `CHAT-BOOTSTRAP` 强 gate 已满足，可进入下一个任务 `CHAT-DEFAULT-INTAKE`。

---

## 任务 2: `CHAT-DEFAULT-INTAKE`

### 非生产级实现事实

- human/god 消息都会落全局 transcript，但真正触发 GOD 工作的是 inbox item，不是 transcript 本身。
- human 发消息时，只有显式 `@mention` 到的 participant 会收到 inbox item；未被 mention 不会自动进入 peer 调度。
- 旧 `ChatDriver` 路径里存在“未指明则 architect 默认接球”，但当前 peer chat 主路径没有等价默认首响协议。

### 生产级目标

定义正式默认首响协议:

`human unaddressed message -> architect inbox -> architect first response`

默认首响是 intake 权，不是 authority 权。

### 只读这些文件

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/mentions.py`
- `src/xmuse_core/chat/inbox_store.py`
- `src/xmuse_core/chat/driver.py`

### 本轮要解决的缺口

- 新 peer chat 主路径缺少无 `@` 默认 intake。
- 旧 `ChatDriver` 语义与新 peer 路径分裂。

### 强 gate

- human 无 `@` 发消息时，必然创建且只创建一个默认 intake inbox item。
- 默认 intake target 必须可解释且稳定，当前固定为 `architect`。
- 不影响显式 `@review` / `@execute` / `@participant:...` 的路由语义。
- idempotent replay 不重复消耗 turn budget，不重复写 inbox。

### 禁止扩面

- 不自动拉 `review`。
- 不改 proposal/blueprint 升级逻辑。
- 不改 scheduler 为并行调度器。

### 当前收敛状态

- peer chat 主路径现在会把 human 无 `@` 的消息稳定路由为单个
  `architect` default-intake inbox item。
- `architect` 已被收束为共享默认 intake target，`ChatDriver` 与
  `PeerChatService` 不再各自硬编码不同语义。
- 显式 `@review` / `@execute` / `@participant:...` 仍保持原 mention-only 路由，
  不额外补 architect intake。
- replay 同一 `client_request_id` 时会复用已记录结果，不重复写 inbox。
- `CHAT-DEFAULT-INTAKE` 强 gate 已满足，可进入下一个任务 `CHAT-REVIEW-TRIGGER`。

---

## 任务 3: `CHAT-REVIEW-TRIGGER`

### 非生产级实现事实

- proposal / blueprint 已有结构化产物与 approval 边界。
- review 何时自动介入仍未协议化，当前主要依赖 architect 手动 `@review`。
- review 角色定义已明确，但它还不是群聊主链上的正式自动 gate。

### 生产级目标

定义 review 自动介入协议:

- message 阶段不自动打断
- 一旦形成 reviewable object，review 自动进入

### 只读这些文件

- `src/xmuse_core/chat/participant_store.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/chat/peer_proposals.py`
- `xmuse/chat_api.py`

### 本轮要解决的缺口

- review 现在只是“可被 mention 到”，不是“会被协议化拉入”。

### 强 gate

- 对进入 reviewable state 的对象，system 会自动为 review 建立 inbox 或等价调度事件。
- 非 reviewable message 不自动唤起 review。
- replay / retry 不重复制造 review 请求。
- architect 手动 `@review` 与自动 review trigger 不冲突，且 duplicate-safe。

### 禁止扩面

- 不定义 `approve / narrow / reject` 的后续全链路动作。
- 不改 execution review plane。

### 当前收敛状态

- lane graph proposal 与 mission blueprint proposal 一旦落成 reviewable object，
  system 会自动为 `review` 建立单个 review-trigger inbox item。
- 普通 message 阶段不会自动拉起 `review`，仍保持 message 不打断的协议边界。
- replay 同一 proposal/blueprint emit request 时会复用同一 message，并按
  `source_message_id + review participant` 去重，不重复制造 review 请求。
- 手动 `@review` mention 与自动 review trigger 可并存；它们按不同 source message
  分别落库，不发生重复污染。
- `CHAT-REVIEW-TRIGGER` 强 gate 已满足，可进入下一个任务 `CHAT-STRUCTURE-ESCALATION`。

---

## 任务 4: `CHAT-STRUCTURE-ESCALATION`

### 非生产级实现事实

- `proposal / mission_blueprint / verdict` 等结构化对象已存在。
- 何时从普通 `message` 升级到这些对象，仍缺少明确收束判据。

### 生产级目标

把“继续聊天”与“必须结构化收束”分开，定义正式升级判据:

- `message`
- `mission_blueprint`
- `proposal / feature_plan / lane_graph`
- `verdict`

### 只读这些文件

- `src/xmuse_core/chat/envelopes.py`
- `src/xmuse_core/chat/models.py`
- `src/xmuse_core/chat/peer_proposals.py`
- `src/xmuse_core/chat/participant_store.py`
- `xmuse/chat_api.py`

### 本轮要解决的缺口

- 当前对象类型存在，但没有正式升级规则。

### 强 gate

- 同一输入在同一上下文下，对应的升级结果稳定且可解释。
- feature plan / lane graph 不能绕过 blueprint 上游约束。
- 结构化对象一旦形成，就能被下游 review / approval / execution 正确识别。

### 禁止扩面

- 不实现 blueprint revision。
- 不实现 human approval 自动化。

### 当前收敛状态

- `create_proposal` 现在会按 payload 形态做稳定升级判定，而不再盲信来路上的
  `proposal_type` 标签。
- 当前已协议化的升级结果：
  - `lanes` -> `lane_graph`
  - `title/body/acceptance_criteria` -> `mission_blueprint`
  - `features/source_blueprint_ref` -> `feature_plan`
  - `decision/rationale` -> `verdict`
  - 其余保持 `proposal`
- `lane_graph` proposal 会被规范化写入 `resolution_content.type = "lane_graph"`，
  下游 approval / execution 可直接识别。
- `feature_plan` payload 一旦被识别，就必须经过已批准 blueprint 引用校验，
  不能再伪装成普通 proposal 或 lane_graph 绕过上游约束。
- `CHAT-STRUCTURE-ESCALATION` 强 gate 已满足，可进入下一个任务
  `CHAT-BLUEPRINT-REVISION`。

---

## 任务 5: `CHAT-BLUEPRINT-REVISION`

### 非生产级实现事实

- 源码已强约束 feature plan / lane graph 不能脱离已批准 mission blueprint 随意生成。
- blueprint 已支持 `revision_of` 语义链。
- 但“何时应修订既有 blueprint，而不是沿着失稳 blueprint 继续长 feature plan”仍未协议化。

### 生产级目标

定义 blueprint revision trigger:

- 变更“做什么” -> 修 blueprint
- 变更“怎么拆/怎么做” -> 继续 feature plan

### 只读这些文件

- `src/xmuse_core/chat/peer_proposals.py`
- `src/xmuse_core/chat/store.py`
- `xmuse/chat_api.py`
- `src/xmuse_core/structuring/feature_plan_store.py`
- `src/xmuse_core/structuring/models.py`

### 本轮要解决的缺口

- 现在能表达 revision，但不会强制在该修时修。

### 强 gate

- 当变更触及 mission / scope / acceptance / core constraints 时，不允许直接继续 feature plan。
- revision blueprint 批准后，后续 feature plan 必须引用新的 approved blueprint。
- 旧 blueprint 上已存在的下游 feature plan，不能在新 revision 出现后继续被当作当前 authoritative source。

### 禁止扩面

- 不做 feature graph runtime 迁移。
- 不做 execution plane rebase/rework。

### 当前收敛状态

- `create_proposal` 现在会把“继续拆解 feature plan”与“必须修 mission blueprint”
  区分开：
  - 仅改 `features/source_blueprint_ref` -> `feature_plan`
  - 一旦同时改 `title/body/acceptance_criteria` 这类“做什么/验收”字段 ->
    `mission_blueprint` revision
- blueprint revision proposal 若带 `source_blueprint_ref`，会被规范化为
  `revision_of=<source_blueprint_ref>`。
- 新 blueprint revision 批准后，被修订的 blueprint resolution 会被标记为
  `SUPERSEDED`，不再作为当前 authoritative source。
- 新建 feature plan 时若仍引用旧 blueprint ref，会在 `create_proposal`
  直接被 `stale_feature_plan_blueprint` 拦下。
- 旧 blueprint 上已存在但尚未批准的 feature plan proposal，在新 revision
  批准后也无法继续通过 approve 成为 authoritative feature plan。
- `CHAT-BLUEPRINT-REVISION` 强 gate 已满足，可进入下一个任务
  `PEER-PROVIDER-PARITY`。

---

## 任务 6: `PEER-PROVIDER-PARITY`

### 非生产级实现事实

- peer participant 已有 role、model、cli_kind 等抽象。
- `PeerChatScheduler` 当前稳定运行路径仍是 Codex-first。
- OpenCode / Claude Code 只进入了部分 provider/launcher 边界，未完成 peer chat 长 session parity。

### 生产级目标

peer chat 成为真正的多 provider runtime，而不是接口形状多 provider。

### 只读这些文件

- `src/xmuse_core/chat/participant_store.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/agents/ray_session_layer.py`
- `src/xmuse_core/agents/god_session_layer.py`
- `src/xmuse_core/providers/service.py`
- `xmuse/platform_runner.py`

### 本轮要解决的缺口

- peer chat 仍是 Codex-first。

### 强 gate

- peer bootstrap、peer send/receive、peer resume path 不再业务层特判 Codex。
- 至少完成 Codex / OpenCode 两条 peer chat authoritative path。
- 不兼容 provider 不得误走 resume / persistent happy path。

### 禁止扩面

- 不碰 execution worker provider parity。
- 不引入新 provider 第三家。

### 当前收敛状态

- `ParticipantStore` / `PeerChatScheduler` 现已稳定接受 `codex` / `opencode`
  两种 peer participant runtime，不再把 peer participant 业务身份锁死到 Codex。
- `GodSessionLayer` 与 `RayGodSessionLayer` 已支持以字符串 runtime token
  持久化和恢复 peer session，peer bootstrap、send/receive、resume path
  不再要求业务层把非 Codex runtime 强行映射回 `AgentRuntime.CODEX`。
- `RunnerProviderService` 现会把 OpenCode invocation 映射为 `opencode`
  runtime；同时显式 provider session resume 仍只允许 Codex，
  不兼容 provider 不会误走 persistent/resume happy path。
- focused parity tests 与相关 chat/session 回归已通过，`PEER-PROVIDER-PARITY`
  强 gate 已满足，可进入下一个任务 `PEER-CROSS-RESTART`。

---

## 任务 7: `PEER-CROSS-RESTART`

### 非生产级实现事实

- `RayGodSessionLayer` 以 `conversation_id + participant_id` 复用 peer session。
- `god_sessions.json` 持久化的是 session 身份，不是 live actor 或 provider 内部会话状态。
- live actor / transport 仍保存在进程内 `_live_sessions`。
- Ray peer 默认复用的是运行期 app-server thread，不是跨重启可恢复 thread。

### 生产级目标

peer long session 不只是 runner 生命周期内连续，而是具备跨重启恢复链。

### 只读这些文件

- `src/xmuse_core/agents/ray_session_layer.py`
- `src/xmuse_core/agents/god_session_layer.py`
- `src/xmuse_core/agents/god_session_registry.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `xmuse/platform_runner.py`

### 本轮要解决的缺口

- 当前长 session 只保证运行期连续。

### 强 gate

- 区分 durable session identity / provider binding / live transport。
- runner 重启后可按显式 resume path 恢复兼容 provider peer session。
- 恢复失败时 fallback 路径清晰且不会污染旧 binding。

### 禁止扩面

- 不顺手改 deliberation protocol。
- 不做新 provider 扩展。

### 当前收敛状态

- `GodSessionRegistry` 现已把 durable session identity 与 provider binding
  分开持久化：`god_session_id / conversation_id / participant_id` 继续作为 xmuse
  会话身份，`provider_session_id / provider_session_kind / provider_binding_status`
  单独记录兼容 provider 的 resume binding。
- `CodexAppServerTransport` 已支持显式 `resume_thread_id`，可在 runner 重启后
  继续使用持久化的 Codex app-server thread id，而不是无条件新建 thread。
- `RayGodSessionLayer` 现会在成功 send/receive 后把 live transport 暴露出的
  Codex thread id 回写为 active provider binding；重启后会优先按该 binding
  恢复 peer session。
- 若恢复的 provider thread 已 stale，`RayGodSessionLayer` 会先把旧 binding
  标成 `stale`，再清晰 fallback 到 fresh actor，并在成功后写入新的 active binding，
  不复用污染旧 binding。
- focused cross-restart tests 与相关 registry/session/transport 回归已通过，
  `PEER-CROSS-RESTART` 强 gate 已满足，可进入下一个任务
  `NATIVE-HISTORICAL-ISOLATION`。

---

## 任务 8: `NATIVE-HISTORICAL-ISOLATION`

### 非生产级实现事实

- peer / review / execute 三类 GOD layer 都同时支持 Ray 和 native。
- Ray 已是默认优先后端。
- native 仍是有效 fallback，且部分路径仍直接使用 native。

### 生产级目标

Ray 成为 authoritative runtime backend；native 退为受限 fallback。

### 只读这些文件

- `xmuse/platform_runner.py`
- `src/xmuse_core/agents/god_session_layer.py`
- `src/xmuse_core/agents/ray_session_layer.py`
- 相关 runtime tests

### 本轮要解决的缺口

- 双 runtime 并存，语义和维护成本过高。

### 强 gate

- 新能力点不再先落 native。
- native 路径只在显式 fallback / degraded local mode 下进入。
- authoritative path 的验证命令默认覆盖 Ray，不以 native 通过作为主验收。

### 禁止扩面

- 不做 provider parity。
- 不做 cross-restart。

### 当前收敛状态

- `platform_runner` 现在把 Ray 视为 peer / review / execute 三条
  GOD capability path 的 authoritative 默认后端；新能力点不会再因为
  “unknown backend” 或 “Ray 初始化失败” 静默先落 native。
- native 路径现只在两类显式场景进入：
  - `XMUSE_*_GOD_BACKEND=native|local`
  - `XMUSE_DEGRADED_LOCAL_GOD_MODE=1` 下的 Ray unavailable fallback
- 未知 backend 现在会直接报错，而不是业务层无感切回 native。
- authoritative path 的 focused verification 已默认覆盖
  peer / review / execute 的 Ray 路径；native 仅作为显式 fallback 语义被单独验证。
- `NATIVE-HISTORICAL-ISOLATION` 强 gate 已满足，可进入下一个任务
  `DEGRADATION-BRIDGE-REMOVAL`。

---

## 任务 9: `DEGRADATION-BRIDGE-REMOVAL`

### 非生产级实现事实

- execution runtime 已可在真实事件点直接写 graph-native degradation evidence。
- 已覆盖 `upsert_failed` 和 `mark_failed_failed` 这类 execution-plane degradation。
- lane -> graph 的 degradation bridge 仍保留，但现在只做 migration compatibility。

### 生产级目标

把 degradation authority 完全收束到 runtime/coordinator callback，移除主路径桥接。

### 只读这些文件

- `src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py`
- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `src/xmuse_core/platform/execution/executor.py`
- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`

### 本轮要解决的缺口

- 主写路径已切，但 compatibility bridge 仍未退场。

### 强 gate

- claim/runtime authoritative path 不再依赖 lane -> graph degradation bridge。
- compatibility bridge 即使保留，也必须默认关闭主写覆盖能力。
- graph-native degradation evidence 成为 resume quarantine 的唯一主依据。

### 禁止扩面

- 不碰 peer chat。
- 不做新的 provider feature。

### 当前收敛状态

- execution/runtime authoritative path 现在只通过 runtime/coordinator callback
  直写 graph-native degradation evidence，不再在 `run_execution_god` 主路径后
  自动回扫 lane projection bridge。
- `feature_graph_provider_binding_degradation` compatibility bridge 仍保留迁移入口，
  但默认关闭：只有显式开启时才会把 lane degradation metadata 回放到
  graph-native status store。
- execution provider binding quarantine 现只认 graph-native
  `provider_session_binding_degradations`；projection 上的
  `provider_session_binding_degraded*` 字段默认不再参与 resume quarantine 决策。
- focused degradation/bridge tests、execution-plane degradation 回归与 ruff 已通过，
  `DEGRADATION-BRIDGE-REMOVAL` 强 gate 已满足，可进入下一个任务
  `FEATURE-LANES-HISTORICAL-ISOLATION`。

---

## 任务 10: `FEATURE-LANES-HISTORICAL-ISOLATION`

### 非生产级实现事实

- graph-backed lifecycle authority 已基本切到 graph-native status/artifact/store。
- 但 `feature_lanes.json` 仍承担:
  - prompt
  - worktree
  - branch
  - runtime telemetry
  - 部分兼容 metadata

### 生产级目标

把 `feature_lanes.json` 压缩成:

- compatibility projection
- lane operational carrier
- legacy flat read model

### 只读这些文件

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/structuring/projection.py`
- `feature_lanes.json` 相关读写点

### 本轮要解决的缺口

- `feature_lanes.json` 仍是当前运行时的重要 operational carrier。

### 强 gate

- graph-backed business authority 不再从 `feature_lanes.json` 读关键状态。
- 新增高价值运行时字段不再优先落 `feature_lanes.json`。
- 保留的字段必须能清晰分类为 projection / operational / legacy。

### 禁止扩面

- 不做 peer chat 协议。
- 不做 runtime backend 切换。

### 当前收敛状态

- graph-backed `dispatch/reconcile` 已改为优先读取 graph-native status store；
  `feature_lanes.json.status` 只保留为 lane operational progression guard，不再承担
  graph-backed business authority 选集。
- execution provider 选择结果不再先写回 `feature_lanes.json`；
  `provider_profile_ref` 改由 provider selection record 承载。
- 保留字段已在代码中显式分类为 `projection / operational / legacy`，
  便于后续 cutover 与 FULL-CHAIN-REAL-RUN 审计。
- `FEATURE-LANES-HISTORICAL-ISOLATION` 强 gate 已满足，可进入下一个任务
  `FULL-CHAIN-REAL-RUN`。

---

## 任务 11: `FULL-CHAIN-REAL-RUN`

### 目标

启用所有已完成的新能力，跑一次真实链路，并只围绕真实失败点全局自迭代，直到终止条件满足。

### 启用范围

- chat bootstrap authoritative path
- default intake
- auto review trigger
- structure escalation
- blueprint revision trigger
- peer provider parity
- cross-restart resume path
- Ray authoritative runtime
- graph-native degradation authority

### 真实链路

至少覆盖这条主链:

1. 创建新 conversation，走 bootstrap preset
2. 确认 `init god` 与 peer team 已建立
3. human 无 `@` 发一个真实需求
4. architect 默认接球
5. 在需要时结构化为 mission blueprint
6. review 在 reviewable object 上自动介入
7. 若 review 指向 mission 层问题，产出 revision blueprint
8. blueprint 批准后，继续 feature plan / proposal
9. proposal / feature plan handoff 到 execution
10. 中途做一次 runner 重启或等价 resume 验证
11. 全链路结束后，无错误 authority fallback、无错误 duplicate side effects

### 真实链路强 gate

- 不依赖人工数据库修补。
- 不依赖 compatibility-only bridge 作为主 authority source。
- 不允许因为重启而丢失本应恢复的 peer session identity / binding。
- 不允许 human 无 `@` 输入静默留在 transcript。
- 不允许 unstable blueprint 继续长出新的 authoritative feature plan。

### 自迭代规则

- 真实链路失败后，只修最小失败点。
- 每次修复后，先跑受影响任务 gate，再重跑整条真实链路。
- 不允许借真实链路测试机会顺手扩第二条能力线。

### 终止条件

满足以下全部条件时终止:

1. 任务 1-10 的强 gate 全部通过。
2. `FULL-CHAIN-REAL-RUN` 至少完成一次 fresh run 通过。
3. 在一次 restart/resume 条件下，链路再次通过。
4. 最后一轮通过时:
   - 无新增 P0/P1 blocker
   - 无 compatibility bridge 误升为 authority
   - 无人工降级兜底替代主路径

如果第 2 或第 3 条失败，则继续围绕失败点自迭代，直到满足终止条件。

### 当前收敛状态

- 已新增 `tests/xmuse/test_full_chain_real_run.py`，用真实 API + MCP + Ray session
  layer 贯穿 bootstrap、default intake、auto review、blueprint revision、
  feature-plan execution handoff。
- fresh run 已通过：
  - 新 conversation 走 bootstrap preset
  - `init god` session 与 peer team 建立
  - human 无 `@` 输入进入 architect default intake
  - architect 结构化 mission blueprint
  - review 自动触发并指出 mission 层问题
  - revision blueprint 被批准
  - stale feature plan 被拒绝，current feature plan 才能 handoff 到 execution
- restart/resume 条件下已再次通过：
  - architect peer session 复用同一 `god_session_id`
  - provider binding 通过 `resume_thread_id` 恢复
  - 无 duplicate participant / duplicate intake / duplicate review trigger 污染
- `FULL-CHAIN-REAL-RUN` 强 gate与终止条件已满足；V2 任务 1-11 全部完成。
- V7 纠偏说明: `tests/xmuse/test_full_chain_real_run.py` 是 API + MCP +
  Ray session layer 的协议链路 smoke；其中 Ray actor 为测试替身，不能作为真实
  Codex CLI / app-server 长 session、latency、MCP writeback happy path 或
  provider-native resume 的生产级 runtime evidence。

---

## 当前优先级

建议后续优先按下面顺序继续收敛:

1. `CHAT-BOOTSTRAP`
2. `CHAT-DEFAULT-INTAKE`
3. `CHAT-REVIEW-TRIGGER`
4. `CHAT-STRUCTURE-ESCALATION`
5. `CHAT-BLUEPRINT-REVISION`
6. `PEER-PROVIDER-PARITY`
7. `PEER-CROSS-RESTART`
8. `NATIVE-HISTORICAL-ISOLATION`
9. `DEGRADATION-BRIDGE-REMOVAL`
10. `FEATURE-LANES-HISTORICAL-ISOLATION`
11. `FULL-CHAIN-REAL-RUN`
