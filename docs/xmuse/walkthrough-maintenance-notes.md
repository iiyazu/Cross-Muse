# xmuse Walkthrough Maintenance Notes

更新日期: 2026-06-03

本文档用于在逐步走读 xmuse 时维护共同上下文。它不替代
`docs/xmuse/解耦开发协议.md` 和 `xmuse/HANDOFF.md`，只记录走读进度、当前实现事实、
实现与目标口径之间的差距，以及用户明确要求记录的非生产级部分。

## 走读原则

- 以当前最新实现为准；历史 spec、plan 和 archived prompt 只作为背景材料。
- 每次只讲一个小块，按真实 session 和真实数据流理解，而不是一次性扫完整代码。
- 对外表述优先使用专业术语: peer agents、persistent sessions、coordinator、
  planner/reviewer/worker、DAG、runtime backend。
- 旧文档里的 `GOD` 术语视为历史命名；解释架构时默认翻译为 peer agent 或 persistent
  agent session，除非正在讨论具体文件名、类名或历史兼容。
- 记录“非生产级/探索性/迁移中”的部分时，只记录会影响理解、交接、简历口径或后续实现闭环的内容。

## 当前产品口径

xmuse 是一个仍在快速演进的个人多 coding-agent 统合编排平台。当前合理口径分为两层:

1. Ray-based 多 coding-agent CLI 对等讨论层: 让 Claude Code、Codex、OpenCode 等
   coding-agent CLI 以 peer 形式讨论用户需求、互相质询、汇集多方意见，收束为更可靠的
   blueprint，从而减少单一 main agent 的中心化决策偏差。
2. 中心化任务拆分与并行执行层: 将已批准的 blueprint 拆成 feature plan 和有依赖关系的
   lane DAG，再由 coordinator 调度 ready lanes 并行执行、review、rework 和 merge。

## 当前真实实现摘要

- 当前代码已经有 peer chat、proposal、blueprint、feature plan、lane graph、
  projection、orchestrator、review/rework/merge、Ray adapter、provider policy 等实现和测试覆盖。
- peer discussion 的目标口径是多 CLI peer，但当前真实 peer chat runtime 主要是
  Codex-first。OpenCode 和 Claude Code 已出现在 provider/launcher/枚举边界中，但还没有作为
  peer chat 的一等运行时完整接入。
- 执行层当前以中心化 coordinator/orchestrator 为主，符合“讨论去中心化、执行中心化”的方向。
- `feature_lanes.json` 当前仍是迁移期 live queue/status source。它不是最终设计权威，但在
  cutover 前必须视为当前执行事实源。

## 走读进度

### 1. 顶层形态与真实状态

状态: 已开始。

本轮先建立 xmuse 的两个平面:

- 讨论平面: conversation、participants、messages、inbox、mentions、proposal 和
  blueprint approval。它回答“需求如何被多视角讨论并收束”。
- 执行平面: blueprint approval、feature plan、graph-set/lane DAG、ready set、
  dispatch、worker、review、rework、merge。它回答“蓝图如何变成可并行执行的工程任务”。

### 2. 后续候选小节

- blueprint 如何从讨论产物变成可执行边界。
- feature plan 和 lane graph 如何表示 DAG。
- coordinator/orchestrator 如何选择 ready lanes 并推进状态。
- provider 层如何抽象 Codex/OpenCode/Claude Code，以及当前缺口。

### 3. 运行时如何维护长 CLI Session

状态: 已开始。

xmuse 维护长 CLI session 的核心不是把所有状态放进 CLI 进程，而是分成三层:

- `GodSessionRegistry`: 持久化 session 身份。记录 `god_session_id`、role、runtime、
  conversation/participant、model、prompt fingerprint、worktree、feature scope 等。
- `GodSessionLayer` / `RayGodSessionLayer`: 运行时 session 管理层。负责
  `ensure_conversation_session`、复用 live session、检查身份是否匹配、必要时重启 transport。
- transport/shim: 真实和 CLI 或 app-server 通讯的进程。native 路径是 line-oriented
  process JSON；Ray 路径可以用 process-json，也可以用 Codex app-server JSON-RPC。

当前有两种主要承载形态:

```text
native GodSessionLayer
-> LocalSession.spawn(python -m xmuse_core.agents.codex_persistent ...)
-> stdin/stdout JSON protocol
-> 每个 turn 内部再调用 codex exec
```

```text
RayGodSessionLayer
-> RayGodActor
-> transport.ensure_alive()
-> 默认 Codex app-server stdio JSON-RPC
-> thread/start 后复用同一个 app-server thread 处理多个 turn
```

关键事实:

- native `codex_persistent` 是长驻 shim，不是长驻 `codex exec`。它常驻读取 xmuse JSON
  消息；每个 turn 再启动一次 `codex exec`。
- Ray app-server transport 更接近真正的长 CLI/app session: actor 长驻，app-server 进程长驻，
  `thread_id` 长驻，后续 turn 复用同一个 thread。
- session 的业务身份由 registry 和 conversation/participant 绑定保证，不依赖 CLI 进程自己记住。
- live transport 只存在于当前 Python 进程或 Ray actor 内；registry 只能恢复身份，不能自动恢复
  一个已经消失的本地 transport。

当前启用路径:

- lane 执行 / persistent review / persistent execute 仍默认使用 native `GodSessionLayer`。
- peer chat scheduler 默认优先使用 Ray `RayGodSessionLayer`，环境变量
  `XMUSE_PEER_GOD_BACKEND` 默认为 `ray`；如果 Ray backend import/startup 失败，则回退 native
  `GodSessionLayer`。
- Ray peer session 内部默认 transport 是 `CodexAppServerTransport`，环境变量
  `XMUSE_RAY_GOD_TRANSPORT` 默认为 `app-server`。若显式设为 `process`、`process-json`、
  `batch` 或 `codex-persistent`，则退回 process-json shim。
- MCP 在 Ray app-server transport 中默认不开启，`XMUSE_RAY_GOD_MCP=1` 才启用。

#### Ray 驱动长 CLI Session 的细节

Ray 路径目前主要服务 peer chat，而不是所有 lane execution。真实链路是:

```text
platform_runner --peer-chat
-> _build_peer_god_layer(backend=XMUSE_PEER_GOD_BACKEND or "ray")
-> RayGodSessionLayer
-> prewarm()
-> PeerChatScheduler(god_layer=RayGodSessionLayer)
```

当某个 participant 被 inbox 唤醒时:

```text
PeerChatScheduler.tick_once()
-> god_layer.ensure_conversation_session(conversation_id, participant_id, role, agent, worktree)
-> RayGodSessionLayer 查 _live_sessions
-> 若同一 conversation + participant 的 actor alive，直接返回原 GodSessionRecord
-> 否则查/建 GodSessionRegistry record
-> RayGodActor.remote(...)
-> actor.ensure_alive()
-> actor 内部启动 transport
```

Ray actor 内部的默认 transport 是 Codex app-server:

```text
RayGodActor.ensure_alive()
-> CodexAppServerTransport.start()
-> codex app-server --listen stdio://
-> JSON-RPC initialize
-> thread/start(cwd, model, approvalPolicy=never, sandbox=danger-full-access, base/developer instructions)
-> 保存 thread_id
```

后续每一轮 peer chat nudge:

```text
RayGodSessionLayer.send_message(...)
-> actor.send_typed("peer_chat_nudge", prompt, context, request_id)
-> CodexAppServerTransport.send_typed(...)
-> turn/start(threadId=<同一个 thread_id>, input=<本轮 prompt/context>, effort=low)
-> receive() 读取 app-server events
-> AppServerTurnAccumulator 聚合 agentMessage delta / item completed
-> turn/completed 后返回 StdoutMessage(result)
```

长 session 的“长”体现在三处:

- `GodSessionRecord` 持久记录 peer 身份。
- `RayGodActor` 长驻并持有 transport。
- `CodexAppServerTransport` 长驻 app-server 进程和 `thread_id`。

当前限制:

- `_live_sessions` 仍是当前 runner 进程内的内存映射；registry 能恢复身份，但不能直接恢复旧 actor
  对象。
- app-server thread 使用 `ephemeral=True`，所以更像运行期长会话，不是跨进程重启后的持久 thread。
- `send_typed` 同一 transport 一次只允许一个 active turn；若已有 `_active_accumulator`，会拒绝并发
  turn。
- MCP 默认关闭，peer chat 主要依靠 final assistant message fallback 被 xmuse 持久化。

### 4. Provider Session 绑定缺口

状态: 已记录。

实际测试中，如果同一个群聊重启后各 peer agent 不保留上次会话记忆，原因符合当前实现:

- xmuse 目前稳定保存的是 `god_session_id` / conversation / participant 这类 xmuse 级身份。
- 当前 `GodSessionRecord` 没有记录 Codex 自己的 provider-side session id。
- native `codex_persistent` 每轮内部调用新的 `codex exec`，没有使用 `codex exec resume <session_id>`。
- Ray app-server 路径虽然在运行期复用 `thread_id`，但当前 `thread/start` 使用 `ephemeral=True`，
  且没有把 app-server `thread_id` 作为可恢复 provider session 绑定写入 registry。

结论:

- MemoryOS 可以作为外部强化记忆层，但不应全盘替代 provider 原生 session。它不能让 Codex/Claude
  自己的会话状态、工具使用历史和内部上下文自动恢复。
- 更合理的生产级方向是双层记忆: provider session resume 负责短中期 CLI 会话连续性；
  xmuse/MemoryOS 负责跨 provider、跨 session、可审计、可裁剪的项目记忆。

建议实现目标:

```text
conversation_id + participant_id
-> xmuse god_session_id
-> provider_session_binding(provider=codex, provider_session_id=<codex session uuid>)
-> first turn: codex exec --json ...
-> capture session_meta.id or JSON event session id
-> later turns/restart: codex exec resume <provider_session_id> <prompt>
```

绑定数据至少应包含:

- provider id: `codex` / `claude_code` / `opencode`。
- provider session id: Codex 的 session UUID，或其他 provider 的等价会话 id。
- provider session kind: `exec`、`interactive`、`app_server_thread` 等。
- cwd/worktree、model、profile、role、prompt fingerprint。
- created_at、last_used_at、last_verified_at、status、failure_reason。
- resume command template 或 adapter 能力标识，而不是在业务层硬编码 provider 命令。

实现顺序建议:

1. 先给 Codex exec 路径补 provider session binding，因为本地 Codex CLI 已支持
   `codex exec resume [SESSION_ID] [PROMPT]`。
2. 再评估 Ray app-server 是否可以使用非 ephemeral thread 或官方可恢复 thread API；在没有明确
   resume 能力前，不把它当作跨重启持久会话来源。
3. 最后把 MemoryOS 接入为附加上下文和长期事实提炼，而不是每轮唯一记忆来源。

#### 绑定实现应放在哪些边界

不要把 provider resume 逻辑写进 `PeerChatScheduler`。scheduler 的职责应保持为:

```text
claim inbox item
-> ensure_conversation_session
-> send_message
-> receive_message
-> 根据结果更新 chat/inbox
```

provider session binding 应放在更低的 provider/runtime 边界:

```text
PeerChatScheduler
-> GodSessionLayer / RayGodSessionLayer
-> ProviderSessionBindingStore
-> Codex transport/adapter
-> codex exec 或 codex exec resume
```

建议新增一个独立 store，而不是只扩展 `GodSessionRecord`:

- `GodSessionRecord` 继续表示 xmuse 业务身份。
- `ProviderSessionBinding` 表示某个 xmuse identity 对应的 provider 原生会话。
- 一个 `god_session_id` 理论上可以有多个历史 provider binding，当前 active 的只有一个。
- 这样将来 Claude Code / OpenCode 接入时，不会污染 GOD session registry 的核心 schema。

Codex exec binding 的最小闭环:

```text
ensure_conversation_session(...)
-> 拿到/创建 GodSessionRecord
-> binding_store.find_active(god_session_id, provider="codex", kind="exec")
-> CodexPersistentTransport 启动
-> send_typed:
   if binding exists:
      codex exec resume <provider_session_id> --json <prompt>
   else:
      codex exec --json <prompt>
      从 JSON event 或 session artifact 捕获 provider_session_id
      binding_store.upsert_active(...)
```

关键 gate:

- 只有当 model、worktree、role/profile、prompt fingerprint 与 binding 兼容时才允许 resume。
- resume 失败要标记 binding 为 `failed` 或 `stale`，并按策略新建 provider session；不能无限重试
  同一个坏 id。
- 禁止用 `--last` 作为生产绑定策略；必须保存显式 provider session id。
- 捕获 provider session id 的主路径应来自 Codex JSON event；扫描 `~/.codex/sessions` 只能作为
  诊断兜底。
- MemoryOS 注入只能发生在 prompt/context 组装阶段，不能覆盖 provider resume 的身份判定。

### 5. Provider 扩展现状: OpenCode 与 Claude Code

状态: 已记录。

当前不能简单说“provider 只有 Codex”。更准确地说:

- Codex 是完整主路径 provider: registry/profile、adapter、policy、execution/review/GOD
  profile、persistent capability、MCP、runner command 都已覆盖。
- OpenCode 已经进入 provider registry 和 adapter，但定位是低成本、低风险、一次性 worker。
  它目前支持 `opencode --model opencode-go/<model> run --format json --dir ... <prompt>`，
  有 env/config/health/fallback 测试，但不支持 MCP 和 persistent session。
- Claude Code 目前主要存在于 `AgentRuntime.CLAUDE_CODE` 和 `ClaudeCodeLauncher`，属于旧
  launcher/runtime 边界；它还没有进入 `ProviderId`、`ProviderRegistry`、`RunnerProviderService`
  和 provider policy。
- peer chat participant store 当前仍是 Codex-only，因此 OpenCode/Claude Code 都还不能作为
  一等 peer participant runtime。

当前实现中一个容易误解的点:

- `RunnerProviderService.runtime_for_invocation()` 对 Codex 和 OpenCode 都返回 `"codex"`。
  这不是说 OpenCode 通过 Codex 执行，而是为了复用现有 runner surface；真正的 CLI 命令由
  `build_command()` 根据 provider adapter 选择。
- 这个命名容易误导，后续生产级重构应把它改成 provider-native worker transport 或更中性的
  execution surface，避免“OpenCode 被 Codex runtime alias 包住”的表述和实现混淆。

建议新增 provider 的顺序:

1. **先补齐 OpenCode 的边界，而不是扩大权限。**
   保持它只做 bounded low-risk worker，补齐结果契约、失败分类、selection audit、health
   read model 和真实 smoke/fallback。暂不让 OpenCode 进入 review、planning、peer chat。
2. **再把 Claude Code 纳入 provider registry。**
   新增 `ProviderId.CLAUDE_CODE`、`AdapterKind.CLAUDE_CODE_CLI`、profile、adapter、health
   check、command/env/result mapping。先从 bounded worker 或 review 之一开始，不要直接作为
   GOD/peer runtime。
3. **最后再做多 CLI peer runtime。**
   peer runtime 需要 participant store 放开 `cli_kind`、scheduler runtime dispatch、
   provider session binding、resume 策略、MCP/工具能力差异、失败隔离和端到端测试。这个阶段
   不能只靠新增 provider profile 完成。

推荐的能力边界:

| 能力 | Codex | OpenCode 当前目标 | Claude Code 首个目标 |
|---|---|---|---|
| peer chat | 当前主路径 | 暂不接 | 暂不接 |
| planning/GOD | 当前主路径 | 暂不接 | 暂不接 |
| review | 当前主路径 | 暂不接 | 可作为后续候选 |
| bounded worker | 当前 fallback/主路径 | 低风险优先 | 可作为首个接入点 |
| persistent session | 支持但需 provider binding | 暂不支持 | 需先确认 CLI resume 能力 |
| MCP | 支持 | 暂不支持 | 需确认 CLI/MCP 接入方式 |

### 6. Blueprint 到 Feature Plan

状态: 已开始。

当群聊中的 blueprint 被批准后，xmuse 不会立刻把它投到执行队列，而是先进入 planning run:

```text
blueprint.approved
-> BlueprintAutomationService.tick()
-> claim planning event
-> create_or_get PlanningRun
-> enqueue planning.started
-> emit blueprint execution started card
-> write audit event
-> ack blueprint.approved
```

这里的 `PlanningRun` 是从“讨论产物”进入“可执行规划”的边界对象。它把 conversation、
blueprint_ref、feature_plan_id、graph_set_id、audit_refs、chat_card_refs 等后续执行线索串起来。

`planning.started` 之后由 `FeaturePlanningService.tick()` 继续处理:

```text
planning.started
-> load approved blueprint
-> ProviderPolicyService select planning/review profiles
-> CodexPlanningAdapterFactory build planner/reviewer
-> FeaturePlanDeliberationService.deliberate()
-> planner proposal
-> reviewer review
-> approve / request rework / reject / challenge / manual review
-> if approved: enqueue feature_plan.ready
-> if failed: enqueue planning.failed
```

这一层已经不是纯机械流程。planner 会提出 `FeaturePlanProposal`，reviewer 会审阅，必要时进入
最多两轮 rework。通过后才保存 approved feature plan 并发出 `feature_plan.ready`。

当前限制:

- 默认 `CodexPlanningAdapterFactory` 要求 planning 和 review profile 都是 Codex provider。
  这意味着 feature planning 虽有 provider policy 外壳，但真实 planner/reviewer runtime 仍是
  Codex-first。
- deliberation 能审 feature plan 的合理性，但它产出的 feature 仍会在下一层被默认规则化地转换成
  lane graph。也就是说，当前智能主要集中在 feature plan 审议，不等于后续 DAG 生成已经生产级。

下一小节继续看 `feature_plan.ready` 如何变成 graph-set、lane DAG 和 `feature_lanes.json`
projection。

#### 执行层职责边界修正

目标执行粒度不应默认是“一个 worker 执行一条 lane”。更合理的生产级边界是:

```text
approved blueprint
-> feature plan
-> 每个 feature 对应一个 lane graph
-> 一个 feature worker/subagent 负责推进一个 lane graph
-> worker 内部按 lane DAG 顺序执行、调用必要的子步骤或短任务
-> reviewer 审计 feature 级结果和跨 feature 风险
```

这样做的原因:

- feature worker 能保持一个 feature 的局部工程上下文，不会被每条 lane 的 oneshot 调用打碎。
- lane graph 仍保留 DAG 约束，但它变成 worker 内部执行计划，而不是每条 lane 都必须对应一个独立
  顶层 CLI session。
- reviewer 的审计对象更清晰: 审 feature 级交付、验收标准、变更集、测试证据、跨 feature 影响。
- 中央 coordinator 仍负责确定性调度: 按 blueprint、feature dependencies、graph/lane status 和
  gate 规则推进，不把执行决策重新交回群聊。

推荐边界:

- peer chat gods: 负责需求澄清、方案争论、风险提示和 blueprint 收束。
- planner/reviewer gods: 负责 feature plan、graph review、质量审计和必要 rework。
- feature worker/subagent: 负责一个 feature/lane graph 的连续推进。
- oneshot CLI: 保留给测试、lint、health check、小型诊断、低风险独立修复和可重试工具任务。

执行层应保持中心化，因为它已经有 approved blueprint、feature plan 和 DAG 作为确定性输入。对等
讨论层的价值主要在需求产生和方案纠偏；执行层的价值主要在可追踪、可恢复、可审计地推进状态。

初始 reviewer 配比建议:

- 默认: 1 个 reviewer 长 session 审多个 feature workers，适合个人项目和中等规模需求。
- 高风险: 1 个 primary reviewer + 1 个 specialist reviewer，按安全、数据迁移、架构边界或 UI
  回归等风险触发。
- 不建议默认 1 feature : 1 reviewer。这样会放大上下文管理和调度成本，且 reviewer 之间还需要额外
  协调，和中心化执行层目标冲突。

因此推荐从 `1 reviewer : N feature workers` 起步，其中 N 由并发预算、风险等级和改动面积决定。
生产级 gate 应限制同一 reviewer 同时审阅的 active feature 数，并在高风险 feature 上临时降低 N。

reviewer 不应是轻量 oneshot 打分器。生产级 reviewer 应该是掌握充分上下文的长 session:

- 需求上下文: approved blueprint、关键群聊决策、约束和非目标。
- 计划上下文: feature plan、feature dependencies、lane graph、acceptance criteria。
- 执行上下文: worker 提交的 diff、执行日志、测试证据、失败和 rework 历史。
- 全局上下文: 当前并行 feature 状态、共享模块风险、跨 feature 冲突和已知技术债。

这类上下文不适合每次审查临时拼成巨大 prompt。更合理的方向是 reviewer 长 session + 可检索项目记忆
+ 每次审查的结构化 evidence bundle。

#### Worker 与 Reviewer 的交互边界

目标态下，一个 feature worker/subagent 连续推进一个 feature/lane graph，直到该 feature 达到
“完成、明确失败、或需要人工输入”的终态。reviewer 不是 worker 的同级执行者，而是中心化质量门禁。

reviewer 对 worker 结果的判定建议分三类:

1. **Accept / merge**

   接受标准:

   - 实现覆盖 approved blueprint 和 feature plan 中对应 feature 的目标。
   - acceptance criteria 有直接证据，例如测试、lint、截图、日志或可读 diff。
   - diff scope 与 feature/lane graph 匹配，没有无关重构或隐藏行为变化。
   - worktree 干净度、分支、base head、依赖状态和 gate 结果满足 merge guard。
   - reviewer 能解释为什么该结果不会破坏相邻 feature 或共享模块。

   行动:

   ```text
   reviewer verdict=merge
   -> coordinator 执行 merge guard
   -> merge 成功后更新 feature/lane graph 状态
   -> 投影/解锁 dependent feature 或 lanes
   -> 记录 review history、evidence refs、merge refs
   ```

2. **Core rework**

   适用条件:

   - 核心实现不满足需求。
   - acceptance criteria 缺失或验证失败。
   - 架构方向错误、破坏边界、引入明显回归。
   - diff scope 严重漂移，reviewer 无法通过小补丁纠正。

   行动:

   ```text
   reviewer verdict=rework
   -> 生成结构化 rework packet
      包含 blocking findings、证据、期望修改、禁止修改范围、必须重跑的 gate
   -> 打回同一个 feature worker/subagent
   -> worker 保持存活或通过 provider session resume 恢复
   -> worker 继续直到完成、失败或超过 rework limit
   ```

   这里的关键是: worker 不应每次 rework 都失去上下文。生产级实现需要 provider session binding
   或 Ray/app-server 长 session 来保证同一个 feature worker 能吸收 review 反馈。

3. **Reviewer patch-forward**

   适用条件:

   - 问题是边缘性、局部性、低风险的，例如格式、轻微测试断言、遗漏 import、worktree 小脏点、
     文档行文或明显机械修正。
   - reviewer 判断打回 worker 的上下文切换成本高于直接修复成本。
   - 修复不会改变核心设计，不会扩大 diff scope，不会绕过 acceptance criteria。

   行动:

   ```text
   reviewer verdict=patch_forward
   -> reviewer 在同一 worktree 做最小补丁
   -> rerun focused gates
   -> 记录 patch-forward reason、diff summary、verification
   -> 再进入 merge guard
   ```

   patch-forward 必须是受限能力，不应让 reviewer 变成第二个 worker。建议 gate:

   - 只能修改已有 worker diff 涉及文件，除非明确是测试/格式修复。
   - 行数或文件数有上限。
   - 不允许引入新架构、新依赖、大范围重构或修改 public contract。
   - 必须记录“为什么不打回 worker”。
   - patch 后必须重新跑相关 gate。

当前实现能力判断:

- 已具备 lane 级 `review_decision=merge/rework`、review history、gate passed、merge failure
  metadata、persistent Review GOD helper、configured review peer、takeover context 等基础能力。
- 已能表达“reviewer 接受后进入 merge”以及“reviewer 不接受后 rework”的核心状态。
- 仍未完全达到目标态: 当前主要是 lane 级 worker/reviewer，而不是 feature worker 拥有整个 lane
  graph；reviewer patch-forward/takeover 虽有相关模型和历史字段，但还没有在导览确认成生产级默认闭环。
- 生产级补齐重点是 feature worker 长 session、feature graph 级 rework packet、reviewer
  patch-forward 强 gate、以及 merge/rework/takeover 的统一事件和证据模型。

### 7. Feature Plan 到 Graph Projection

状态: 已开始。

`feature_plan.ready` 之后，系统进入从“规划对象”到“执行队列”的转换层。当前默认流程可以理解为:

```text
feature_plan.ready
-> load approved feature plan
-> build_feature_graph_set(feature_plan)
-> 每个 FeaturePlanFeature 生成一个 LaneGraph
-> 每个 expected_touched_area 生成一个 root lane
-> 每个 feature 额外生成一个 verify lane
-> project_feature_graph_set_ready_lanes(...)
-> 把当前 ready lanes 投影进 feature_lanes.json
```

这里有两个对象需要区分:

- `FeatureGraphSet`: 一个 feature plan 对应的一组 feature graphs，保存 graph-set 级来源和版本。
- `LaneGraph`: 单个 feature 的内部 lane DAG。目标态下它更适合作为 feature worker 的内部执行计划，
  而不是把每个 lane 都暴露为独立顶层 worker。

projection 的作用是把 graph-set 中“当前可执行”的 lane 映射到兼容执行队列:

- feature dependency 未满足时，不投影该 feature 的 lanes。
- lane dependency 未满足时，不投影该 lane。
- 已经存在于 `feature_lanes.json` 的 lane 不重复投影。
- 投影 payload 会带上 graph_set、feature_plan、graph、lane_local_id、acceptance criteria 等血缘字段。

当前限制:

- graph builder 仍偏机械，主要按 `expected_touched_areas` 建 root lanes，再追加 verify lane。
- `feature_lanes.json` 仍是迁移期 live queue，所以 graph-set 不是唯一执行事实源。
- 若改成“一个 feature worker 推进一个 lane graph”，projection 层需要从“lane 级派发队列”逐步升级为
  “feature graph 级派发 + lane 状态回写”的兼容层。

### 8. Coordinator / Orchestrator 是执行仲裁层

状态: 已开始。

worker 和 reviewer 不应彼此直接改 durable state。执行层需要一个中心化仲裁者，负责领取 ready work、
调用 subagent、接收 reviewer verdict、执行 merge guard、更新状态和解锁依赖。

当前协议中的执行层边界是:

```text
graph_set.ready / lane.ready
-> xmuse coordinator
-> projection / ready-set
-> PlatformOrchestrator / state machine
-> worker subagent
-> gate evidence
-> reviewer verdict
-> merge / rework / patch-forward / takeover / blocked
-> lane.updated / run.terminal / dependent unlock
```

关键原则:

- `coordinator` 是状态写入和调度仲裁者，不是新的对等 GOD。
- `worker` 是受控执行体，输出 diff、日志、测试证据和失败信息。
- `reviewer` 是质量门禁，输出结构化 verdict 和 evidence，不应绕过 coordinator 直接改状态。
- `Ray actor` 只承载生命周期和并发执行，不拥有业务状态。
- `LangGraph` 可以编排 workflow 节点，但不能成为 lane status 的权威写入者。
- 迁移期 `feature_lanes.json` 仍是执行事实源；目标态应迁到 graph-native ready-set/status store。

用 feature worker 目标态重述:

```text
coordinator 领取一个 ready feature graph
-> 启动/恢复 feature worker 长 session
-> worker 按 lane graph 内部推进
-> worker 提交 feature-level evidence bundle
-> reviewer 长 session 审 feature-level bundle
-> coordinator 根据 verdict 执行 merge/rework/patch-forward/takeover
```

这能保留执行层中心化: worker 和 reviewer 都是 coordinator 调用的角色，不能互相协商后自行决定状态。

当前实现能力判断:

- 已有 `PlatformOrchestrator`、`LaneStateMachine`、`LaneProjectionSyncer`、
  review/rework/merge/takeover 相关模型和运行态字段。
- 当前 runner 仍主要消费 `feature_lanes.json` 的 flat lane projection。
- 目标中的 “ready feature graph -> feature worker 长 session -> feature-level review” 还未完全落地；
  当前更接近 lane 级调度和 lane 级 review。

生产级补齐方向:

- 引入 graph-native ready-set/status store，让 feature graph 成为执行粒度。
- coordinator 只派发 feature graph，不默认派发每条 lane 给顶层 worker。
- worker/reviewer session 都要绑定 provider 原生 session id，支持 rework 后继续上下文。
- review verdict、patch-forward、takeover、merge guard 都要产生统一事件和 evidence refs。

#### 长 Session Runtime 收口: Ray 为目标，Native 分阶段退场

推荐目标是把所有长 session 统一交给 Ray 管理，包括 peer participants、planner、reviewer、
feature worker 和必要的 coordinator actor。原因:

- Ray actor 更适合表达“长生命周期角色”: 可预热、可心跳、可隔离、可重启、可集中观测。
- native `GodSessionLayer` / `codex_persistent` 当前更像本地 shim，xmuse 级 session 长驻，
  但 provider 侧未必是真正长 session。
- 统一到 Ray 后，provider session binding、心跳、并发限制、取消、恢复、evidence 收集和 dashboard
  观测可以落在同一 runtime 抽象上。

但不建议现在直接把 native 收进历史隔离。native 应先降级为兼容/诊断 fallback，等 Ray 路径通过
parity gates 后再归档。原因:

- 当前 peer chat 已偏 Ray，但 lane execution / persistent review / planner/reviewer 仍可能依赖
  native 路径。
- Ray app-server 目前仍有跨重启恢复缺口，例如 ephemeral thread 和 provider session id 绑定不足。
- 本地开发、CI、最小 smoke 和故障排查仍需要一个不依赖 Ray cluster 的简单路径。

建议分阶段:

1. **抽象统一**: 对上层只暴露 `SessionRuntime` / `LongSessionManager` 能力，不让业务代码区分
   Ray/native。
2. **Ray 默认**: peer、planner、reviewer、feature worker 默认走 Ray actor；native 仅在显式
   env flag 或 Ray 不可用时启用。
3. **能力补齐**: Ray 路径必须支持 provider session binding、resume、heartbeat、cancel、shutdown、
   crash recovery、structured events 和 evidence refs。
4. **Parity gate**: 用同一组契约测试验证 Ray 与 native 在 peer chat、planning、feature worker、
   review/rework、merge guard 上行为一致。
5. **Native 归档**: 当 Ray 连续通过真实 smoke 和 focused gates 后，把 native 从默认 runtime
   移到 legacy/historical 隔离，只保留必要的测试夹具或诊断工具。

最终口径:

```text
生产目标: Ray 管理所有长 session
迁移现实: native 仍是兼容 fallback
归档条件: Ray 具备 provider resume + feature worker/reviewer parity + CI/smoke 稳定
```

### 9. Feature Worker 长 Session 生命周期

状态: 已开始。

目标态中的 worker 不是“一条 lane 一个临时 CLI”，而是“一个 feature graph 一个长 session
subagent”。它接收的是整个 `LaneGraph`，内部按 DAG 推进各 lane，并把 feature 级证据交给
reviewer。

一次理想生命周期:

```text
coordinator 发现 ready feature graph
-> 分配或恢复 feature worker actor/session
-> 绑定 provider session id、worktree、branch、feature_graph_id
-> 注入 blueprint + feature plan + lane graph + acceptance criteria
-> worker 按 lane DAG 执行实现、局部测试、自检
-> worker 产出 feature-level evidence bundle
-> reviewer 长 session 审 evidence bundle + diff + gates
-> verdict=merge / rework / patch_forward / takeover / blocked
-> coordinator 执行状态转换和依赖解锁
```

worker session 应该保持到以下终态之一:

- feature merged。
- feature failed，并有明确 failure layer 和 failure reason。
- blocked_for_input，需要人工或群聊补充信息。
- rework limit exceeded，需要升级给 reviewer/coordinator/human。
- runtime failure，经恢复策略后仍不可继续。

rework 时不应创建一个全新 worker 重新理解任务。推荐做法:

```text
reviewer verdict=rework
-> coordinator 生成 rework packet
-> 发回同一个 feature worker session
-> worker 保留已有上下文、diff 认知和失败历史
-> worker 继续修复并提交新 evidence bundle
```

feature worker 的上下文包应至少包含:

- approved blueprint 中与该 feature 相关的目标、非目标和约束。
- feature plan 中的 feature goal、dependencies、acceptance criteria。
- lane graph 的 lane 列表、依赖、预期 touched areas 和 gate profiles。
- 当前 worktree diff、测试结果、失败日志、review history。
- 相邻 feature 的状态摘要和共享模块风险。

这与 MemoryOS 的关系:

- provider session resume 保证同一个 CLI agent 的短中期上下文连续。
- xmuse/MemoryOS 记忆负责长期项目事实、历史决策、错误模式和跨 session 检索。
- 每轮 prompt 不应无限塞完整历史，而应由 coordinator 组装结构化 context package。

当前实现差距:

- 当前运行态仍主要是 flat lane projection + lane 级 worker/review。
- feature worker actor/session 作为 graph owner 尚未完全落地。
- provider session binding / resume 仍是关键缺口。
- evidence bundle 已有雏形，但还需要升到 feature graph 级别，作为 reviewer 的标准输入。

### 10. Evidence Bundle 与 Rework Packet

状态: 已开始。

feature worker、reviewer、coordinator 之间不应只靠自然语言总结交接。生产级闭环需要两个稳定
契约:

- `FeatureEvidenceBundle`: worker 完成或阶段性完成后提交给 reviewer 的证据包。
- `ReworkPacket`: reviewer 不接受时，由 coordinator 发回 worker 的结构化返工包。

`FeatureEvidenceBundle` 应至少包含:

```text
identity:
  conversation_id
  planning_run_id
  feature_plan_id / version
  graph_set_id / version
  feature_id
  feature_graph_id
  worker_session_id
  provider_session_binding_ref

scope:
  blueprint_refs
  feature_goal
  acceptance_criteria
  lane_graph_summary
  touched_files

changes:
  base_head_sha
  branch
  worktree
  diff_ref / patch_ref
  changed_files
  dependency_changes

verification:
  commands_run
  test_results
  lint_results
  screenshots_or_logs
  known_failures

worker_notes:
  implementation_summary
  decisions_made
  risks_or_open_questions
  skipped_items_with_reason
```

reviewer 的 verdict 也应结构化，而不是只写 `merge` 或 `rework`:

```text
review_verdict:
  decision: merge | rework | patch_forward | takeover | blocked
  blocking_findings
  non_blocking_findings
  evidence_refs
  acceptance_coverage
  scope_assessment
  required_gates_before_merge
  reviewer_session_id
```

`ReworkPacket` 的目标不是“再试试”，而是让同一个 feature worker 带着 reviewer 的精确信息继续:

```text
rework_packet:
  rework_id
  source_verdict_id
  blocking_findings
  required_changes
  forbidden_changes
  evidence_refs
  files_or_areas_to_revisit
  gates_to_rerun
  max_remaining_attempts
  return_requirements
```

关键设计点:

- worker 负责交付 evidence bundle，不直接写最终状态。
- reviewer 负责判定 evidence，不直接绕过 coordinator 改状态。
- coordinator 负责把 verdict 转成状态转换、merge guard、rework packet 或 takeover。
- rework packet 必须回到同一个 worker session，除非 worker 已不可恢复。
- patch-forward 是 reviewer 的受限小修能力，也必须产出 patch evidence 和 verification。

当前实现能力判断:

- 当前运行态已经有 review history、review summary、gate result、merge failure metadata 等字段，
  能支撑 evidence 的一部分。
- 交接文档显示 evidence bundle 组装、review evidence、takeover context 已有相关模块化方向。
- 但目标中的 feature-level `FeatureEvidenceBundle` / `ReworkPacket` 还不是统一权威契约；
  当前更像多个 lane 级字段和 review 文本散落在 projection/runtime 状态里。

生产级补齐方向:

- 先定义 feature-level evidence/rework Pydantic schema 和 golden fixtures。
- coordinator 只接受结构化 evidence/ref，不依赖 reviewer 从零翻 worktree。
- dashboard/TUI 展示 evidence bundle 摘要和 drill-down，不直接读取杂散 runtime 字段。
- reviewer prompt 和 feature worker prompt 都围绕这些 schema 组织。

### 11. A2A 协议接入取舍

状态: 已开始。

根据 2026-06-03 查阅的官方 A2A 文档，A2A 适合解决“不同 agent 系统之间如何发现、通信、
协作、跟踪长任务”的互操作问题。它有 `AgentCard`、`Message`、`Task`、`Artifact`、
`contextId`、task status、streaming / push notification 等概念，和 xmuse 的 peer agents、
feature worker、reviewer、evidence bundle 有明显对应关系。

推荐结论:

```text
应该强化 A2A，把它作为 xmuse 与独立 agent 的边界协议候选
不应该让 A2A 替代 xmuse coordinator / state machine / graph store
```

这里需要明确: xmuse 的 gods、feature workers、reviewers 本质上都是 agent。它们背后可能是
Codex、Claude Code、OpenCode 或其他独立 agent runtime。xmuse 不是把这些 CLI 简单降格成
“函数工具”，而是在平台层编排它们讨论、执行、审计和交接。

因此，A2A 的价值比“外部 façade”更高: 它可以成为 xmuse 与各独立 agent runtime 之间的统一协议
边界。xmuse 负责分配任务、状态仲裁、权限控制、证据落库和依赖解锁；agent runtime 负责完成被分配
的长任务并返回结构化产物。

适合接入 A2A 的边界:

- provider/agent capability discovery: 用 AgentCard 表达 Codex/OpenCode/Claude Code wrapper
  或外部 agent 的能力、认证、endpoint、streaming 支持。
- agent task delegation: peer god、planner、reviewer、feature worker 都可以被抽象成 A2A-capable
  agent endpoint，接受 xmuse coordinator 分配的 task。
- peer discussion: conversation 可以映射为 A2A `contextId`，peer nudge/reply 可以映射为
  Message 或 Task。
- feature worker: 一个 feature graph 可以映射为一个 A2A Task；worker 输出的
  `FeatureEvidenceBundle` 可以映射为 Artifact。
- reviewer: reviewer verdict 可以作为 Artifact 或 task status metadata 返回。
- external agent integration: 如果未来接入非本地 CLI agent，A2A 比自定义 JSON shim 更适合。

不适合交给 A2A 的边界:

- graph-set / lane graph / ready-set 的权威状态。
- merge guard、worktree 写入、状态转换、依赖解锁。
- provider session binding 和 Ray actor 生命周期管理。
- MemoryOS/xmuse 的长期记忆与审计存储。

建议映射:

```text
xmuse conversation_id       -> A2A contextId
feature_graph_id            -> A2A taskId 或 task metadata
FeatureEvidenceBundle       -> A2A Artifact(DataPart/FilePart)
review verdict              -> A2A Artifact + TaskStatus metadata
blocked_for_input           -> A2A input-required state
feature merged              -> A2A completed + xmuse merge event
feature failed              -> A2A failed + xmuse failure event
rework                      -> 新 Task 或同 context 下 refinement task
```

需要注意: A2A task 到 terminal state 后不应重启；后续 refinement/rework 更适合在同一 `contextId`
下创建新 task，并通过 metadata/reference 关联旧 task。这与 xmuse 的 rework history 可以兼容，
但 xmuse 仍要自己维护“哪个 artifact/version 是当前可接受结果”。

生产级接入顺序:

1. **Schema alignment first**: 先把 `FeatureEvidenceBundle`、`ReviewVerdict`、
   `ReworkPacket` 做成稳定 schema，再设计 A2A adapter。
2. **A2A façade**: 给 xmuse feature worker/reviewer 暴露 A2A server/client façade，但内部仍由
   coordinator 写状态。
3. **External agent pilot**: 先让一个外部/非 Codex agent 通过 A2A 承接低风险 review 或 worker
   task。
4. **Ray actor bridge**: Ray actor 管生命周期，A2A 管协议消息；二者不要混成一个状态源。
5. **Contract tests**: 用 golden fixtures 测 `contextId`、task state、artifact refs、
   streaming events 和 xmuse event/state 的映射。

风险:

- A2A 是互操作协议，不是编排引擎；过早把内部执行全改成 A2A 会制造额外复杂度。
- A2A 的 Message/history 不应被当成关键证据的可靠唯一来源；关键证据仍要落 xmuse artifact store。
- 安全、认证、权限收缩和工作区隔离必须由 xmuse 自己强约束，不能只依赖 agent card 文本声明。

因此，A2A 应成为 xmuse 的“agent 边界协议”和“跨 provider 互操作层”，而不是核心状态权威。
xmuse 的平台层职责仍然是:

- 维护 conversation、blueprint、feature plan、graph-set、ready-set 和 run state。
- 控制 worktree 权限、merge guard、rework limit、patch-forward gate 和 takeover。
- 管理 Ray actor 生命周期和 provider session binding。
- 把 agent 返回的 artifact/verdict 归档为可审计证据，并驱动确定性状态转换。

## 补充约束与优先级

本节记录当前走读后形成的高优先级架构约束。它们不是额外功能清单，而是后续完善 xmuse 时应优先守住
的边界。

### P0. 状态权威必须统一

目标态应由 `graph-set / feature graph / event store / graph-native status store` 作为执行权威，
`feature_lanes.json` 只保留为迁移期投影或兼容导出。

理由:

- 只要 `feature_lanes.json` 仍是 live queue，执行模型就会被迫维持 lane 级调度。
- feature worker 拥有整个 lane graph、feature-level review、rework packet、A2A task 映射都需要
  graph-native 状态权威支撑。
- dashboard/TUI/read model 应读权威状态派生结果，不应继续围绕 flat projection 扩张。

### P1. Agent 边界必须协议化

xmuse 编排的是独立 coding agents，而不是普通函数工具。Codex、Claude Code、OpenCode 以及未来
远程 agent 应通过统一的 `AgentRuntimeAdapter` 或 A2A-compatible boundary 接入。

约束:

- agent 可以拥有长任务、上下文、artifact 和 verdict。
- xmuse 仍拥有状态权威、权限控制、merge guard、rework limit 和依赖解锁。
- A2A 适合作为 agent 边界协议候选，但不能替代 coordinator/state machine。

### P2. 长 Session 是生产级核心

不是所有 CLI 调用都必须长 session，但以下角色必须按长 session 设计:

- peer gods / peer agents。
- planner。
- reviewer。
- feature worker。

oneshot CLI 应收束到 lint、test、health check、小诊断、低风险可重试工具任务。中大型需求的执行和
审查不能依赖反复新建上下文的 oneshot agent。

### P3. 执行粒度优先升到 Feature Graph

默认执行粒度应从 lane 提升为 feature graph:

```text
一个 feature graph
-> 一个 feature worker 长 session
-> worker 内部按 lane DAG 推进
-> reviewer 做 feature-level 审计
```

lane 是 feature worker 的内部计划，不应默认等同于顶层 worker 派发单位。这样能降低上下文破碎、
rework 丢失上下文和跨 lane merge 摩擦。

### P4. Reviewer 要有强权，但必须受 Gate 限制

reviewer 应掌握充分上下文，并能输出:

```text
merge | rework | patch_forward | takeover | blocked
```

但 reviewer 的 `patch_forward` 必须有强 gate:

- 只能修边缘性、局部性、低风险问题。
- 必须记录为什么不打回 worker。
- 必须限制文件数/行数/scope。
- 必须重跑 focused gates。
- 不能引入新架构、新依赖或 public contract 变化。

### P5. MemoryOS 不替代 Provider Session

MemoryOS/xmuse memory 负责长期事实、历史决策、错误模式、跨 session 检索和可审计上下文。
Codex/Claude Code/OpenCode 的 provider 原生 session resume 负责 agent 自身短中期连续性。

两者是互补关系:

```text
provider session resume -> 保持当前 agent 的工作连续性
xmuse/MemoryOS memory   -> 提供长期、跨 agent、可裁剪、可审计项目记忆
```

### P6. 简历与对外口径必须诚实

xmuse 可以作为自主开发项目进入简历，但表述应是:

```text
自主开发中的多 coding-agent 编排平台原型
```

重点强调架构判断和闭环能力: peer discussion、centralized execution、feature graph、long sessions、
review/rework/merge、provider boundary、A2A-compatible direction。不要声称已经是成熟生产平台或
完整多 provider runtime。

一句话收束:

```text
xmuse 的核心不是多开几个 CLI，而是把独立 coding agents 编排成可审计、可恢复、可并行、
中心化执行的工程系统。
```

## Codex 强化开发支撑度

当前本文档已经能支撑 Codex 强化 xmuse 的“架构证据”，但不能单独替代实现 handoff 或 goal prompt。

已能支撑的部分:

- 说明 xmuse 的产品定位: 多独立 coding-agent 编排平台，而不是单 agent 工具箱。
- 说明核心拓扑: 需求讨论去中心化，执行层中心化。
- 说明关键目标: Ray 长 session、feature graph worker、reviewer 长 session、evidence/rework
  契约、A2A-compatible agent boundary。
- 说明当前缺口: `feature_lanes.json` 仍是迁移期事实源、peer/runtime Codex-first、feature
  planning Codex-first、provider session binding 缺失、lane 级执行尚未升到 feature graph。
- 说明非生产级部分，避免 Codex 误把当前实现描述成成熟平台。

不足之处:

- 还不是可直接执行的 implementation plan；缺少逐步任务、文件级改动、测试命令和验收标准。
- 当前 repo 正在经历 xmuse / MemoryOS 拆分，本文档记录的是架构走读，Codex 仍需先确认当前源码位置。
- 某些当前事实来自拆分前 `src/xmuse_core` 检阅；后续 Codex 必须以最新 xmuse 源码为准重新核对。
- A2A、feature-level evidence bundle、graph-native status store 仍是目标方向，不是已完成能力。

因此推荐把本文档作为 Codex prompt 的“架构约束与证据来源”，再配合 `xmuse/HANDOFF.md`、
`docs/xmuse/解耦开发协议.md`、当前源码和 focused tests 生成具体实现计划。

### 推荐给 Codex 的开发优先级

1. **确认当前源码和运行根**

   先定位拆分后的 xmuse 源码、runtime root、测试目录和当前默认入口。不要假设
   `src/xmuse_core` 一定仍在 MemoryOS 仓库内。

2. **补 graph-native 状态权威**

   优先让 graph-set / feature graph / ready-set / status store 成为执行权威，降低
   `feature_lanes.json` 的业务地位。

3. **定义 feature-level 契约**

   先落 `FeatureEvidenceBundle`、`ReviewVerdict`、`ReworkPacket` schema 和 golden fixtures。
   没有这些契约，feature worker、reviewer、A2A adapter 都会变成 prompt 拼接。

4. **统一 agent runtime 边界**

   抽象 `AgentRuntimeAdapter` / `LongSessionManager`，让 Codex、Claude Code、OpenCode 和未来
   A2A agent 都以统一 task/artifact/verdict/session 语义接入。

5. **Ray 默认管理长 session**

   peer、planner、reviewer、feature worker 目标上都走 Ray actor；native 先保留为 fallback，
   通过 parity gates 后再归档。

6. **实现 feature worker graph owner**

   从 lane 级 worker 迁移到 “一个 feature graph 一个 feature worker 长 session”。lane DAG 是
   worker 内部执行计划。

7. **强化 reviewer 闭环**

   reviewer 长 session 审 feature-level evidence，输出 `merge/rework/patch_forward/takeover/blocked`。
   `patch_forward` 必须有强 gate。

8. **再接 A2A adapter**

   A2A 应在 schema 和 runtime 边界稳定后接入，先做低风险 external reviewer/worker pilot。

### Codex 实现时的硬 Gate

- 不把 A2A、Ray actor、LangGraph 或 provider CLI 当状态权威。
- 不让 worker/reviewer 直接写 durable execution state。
- 不绕过 coordinator/state machine 做 merge、rework、dependency unlock。
- 不用 `--last` 作为 provider session 绑定策略；必须保存显式 provider session id。
- 不把 MemoryOS 当 provider 原生 session 的替代品。
- 不扩大 `feature_lanes.json` 作为业务权威的依赖。
- 不把 native runtime 直接删除；先降级为 fallback，再以 parity gates 归档。
- 不把当前 Codex-first runtime 描述成完整多 provider runtime。

### 最小验收证据

Codex 每完成一个强化阶段，至少应提供:

- 相关 schema / store / adapter 的 focused tests。
- 一条从 blueprint/feature graph 到 worker evidence、review verdict、状态转换的闭环测试。
- provider session binding 或 Ray session 生命周期的恢复/失败测试。
- reviewer rework 和 patch-forward 的 gate 测试。
- `feature_lanes.json` 兼容投影不回归的测试，直到 cutover 完成。
- 运行结果和失败限制写入 handoff，而不是只给自然语言总结。

### 2. Peer Chat 的一次真实 Session

状态: 已开始。

真实讨论层不是单纯把所有文本拼成 transcript，而是围绕一个 `conversation` 维护几类对象:

- `Participant`: 当前 conversation 内的 peer 身份，包含 role、display name、provider/profile、
  cli kind、model、status。当前 store 层仍把 `cli_kind` 限制为 `codex`。
- `ChatMessage`: 可见群聊消息。human 或 peer agent 的自然语言内容都会落到 message 表，并带
  `envelope_type`、`envelope_json`、mentions 和 reply refs。
- `ChatInboxItem`: 定向唤醒队列。带 `@role` 或 `@participant` 的消息会创建 inbox item，
  scheduler 再 claim、nudge 对应 participant 的 persistent session。
- `Proposal`: 讨论产出的结构化候选物。当前包括 mission blueprint proposal 和 lane graph
  proposal；它们同时以 message/card 形态进入 timeline，供人类和后续执行层消费。

一次典型流动:

```text
human post message with @architect
-> ChatMessage(message)
-> ChatInboxItem(unread, target=architect participant)
-> PeerChatScheduler claim inbox item
-> ensure persistent Codex session for target participant
-> send peer_chat_nudge with group_chat context + inbox payload
-> peer reads inbox / replies / mentions others / emits proposal
-> message, inbox item, proposal, card 更新到同一个 conversation timeline
```

这里的关键设计点是: 群聊 transcript 只是可见层；真正驱动 agent 参与的是 inbox + scheduler +
persistent session。这样 peer 不需要每轮都由主进程直接拼 prompt 调用，而是可以被当成有身份、
有收件箱、有上下文的参与者。

## 需维护的非生产级/迁移中实现

### 1. Peer Chat 当前仍是 Codex-First

目标口径是多 coding-agent CLI peer discussion，但当前 peer chat 主要围绕 Codex runtime
落地。OpenCode/Claude Code 相关边界已经存在，但还没有完整进入 peer chat scheduler 的真实
participant runtime。

影响:

- 简历和对外交付可以表述为“设计为多 CLI 统合编排，当前 Codex-first，已预留 provider
  边界”。
- 若要称为完整多 CLI peer discussion，需要补齐非 Codex participant runtime、调度策略、
  失败隔离和对应端到端测试。

### 2. `feature_lanes.json` 仍是迁移期执行事实源

目标态应由 graph-set / lane graph / durable event 作为业务权威，`feature_lanes.json`
退化为兼容投影。但当前 runner、state machine、dashboard、MCP 工具仍共同依赖它作为 live
queue/status source。

影响:

- 后续重构不能直接删除或绕过它。
- 生产级闭环需要明确 cutover 策略: graph-set 成为权威、projection 幂等、legacy runner
  消费兼容视图。

### 3. Feature Plan 到 Lane Graph 仍偏规则化

`FeaturePlanDeliberationService` 已经有 planner/reviewer/rework 的 agentic 审议，但默认
`build_feature_graph_set()` 仍按规则生成 lane graph:

- 每个 `FeaturePlanFeature` 对应一个 `LaneGraph`。
- `expected_touched_areas` 中的每个 area 生成一个 root lane。
- 如果没有 touched areas，则生成一个通用 implementation lane。
- 每个 feature 额外生成一个 verify lane，并依赖所有 root lanes。

影响:

- 当前拆分质量很依赖 planner 给出的 feature 粒度和 touched areas。
- lane DAG 可能过粗、过细，或无法表达跨 area 的真实工程依赖。
- 生产级方向应补一个 graph/lane decomposition review 或 agentic graph builder，而不是只依赖
  当前规则生成器。

### 4. Feature Planning Runtime 仍是 Codex-First

provider policy 已经参与 planning/review 选择，但默认 adapter factory 会拒绝非 Codex provider。

影响:

- 现阶段不能把 OpenCode/Claude Code 描述为已参与 feature planning 或 review 的一等 runtime。
- 多 provider planning 的正确顺序应是先补 provider-native worker/review 边界，再把 planner/reviewer
  adapter 从 Codex-specific 改成 provider-aware。

## 当前权威入口

- `docs/xmuse/README.md`: xmuse 文档入口。
- `docs/xmuse/解耦开发协议.md`: 当前最重要的架构边界文档。
- `xmuse/HANDOFF.md`: 当前实现、运行态和交接上下文。
- `src/xmuse_core/`: xmuse 核心实现。
- `tests/xmuse/`: xmuse 行为和边界测试。
