# xmuse Walkthrough Maintenance Notes V14

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的 **decentralized groupchat runtime production closure**
指导文档。V14 的目标不是继续优化普通聊天体验，而是把 xmuse 群聊层推进到可驱动真实工程任务的
生产级闭环。

## 一句话目标

让 xmuse GOD 群聊从 `mention-routed multi-GOD chat` 升级为:

```text
human goal
-> decentralized GOD discussion
-> bounded collaboration + structured aggregation
-> proposal / artifact routing
-> automatic real-provider dispatch
-> review / veto / iteration
-> durable trace + TUI/dashboard visible closure
```

V14 必须用一个真实任务证明闭环成立: **根据 xmuse 后端，参考 Codex/OpenCode 等主流
agent TUI，实现 xmuse TUI 的生产级可用改造**。允许直接修改正式 TUI 主路径代码。

## 不可变产品语义

- 默认编排模式是 `peer_consensus`。
- 保留 `leader_assisted` 模式开关，但不是默认。
- 默认允许自动进入真实 provider 执行层。
- 人类审批是配置开关，默认关闭；goal 执行者可作为 human/product owner 在群聊中灵活对话和调整。
- 普通聊天文本不能直接触发真实执行，必须经 structured proposal / artifact / dispatch gate。
- 本轮不接 MemoryOS，不引入 memoryOS dependency/config/runtime coupling。
- TUI/dashboard 必须消费正式 read surface / API，不允许直写或自行推断 authority。

## 必须参考 clowder-ai

V14 goal 开始后必须读取并吸收 `/home/iiyatu/clowder-ai` 的源码和测试。不得只写“参考了
clowder”这类空话；必须在 handoff 或本文档追加一张映射表，说明 clowder 机制如何落到 xmuse。

最低必读路径:

- `/home/iiyatu/clowder-ai/assets/system-prompts/system-prompt-l0.md`
- `/home/iiyatu/clowder-ai/docs/features/F086-cat-orchestration-multi-mention.md`
- `/home/iiyatu/clowder-ai/docs/features/F122-unified-dispatch-queue.md`
- `/home/iiyatu/clowder-ai/packages/shared/src/types/multi-mention.ts`
- `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/routing/MultiMentionOrchestrator.ts`
- `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/routing/multi-mention-state-machine.ts`
- `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/invocation/InvocationQueue.ts`
- `/home/iiyatu/clowder-ai/packages/api/src/routes/callback-multi-mention-routes.ts`
- `/home/iiyatu/clowder-ai/packages/api/src/routes/proposal-approve-dispatch.ts`
- `/home/iiyatu/clowder-ai/packages/mcp-server/src/tools/callback-tools.ts`
- `/home/iiyatu/clowder-ai/packages/api/test/multi-mention-*.test.js`
- `/home/iiyatu/clowder-ai/packages/api/test/proposal-approve-dispatch.test.js`

重点吸收:

- structured routing，而不是只靠文本 `@`。
- bounded multi-mention: targets、callback aggregation、timeout、partial、idempotency。
- anti-cascade: 被召唤者不能无限级联召唤其他 GOD。
- unified queue / dispatch: user、connector、agent sourced work 共享 busy/queue/steer 语义。
- proposal approve dispatch: 讨论结果进入执行必须有结构化 artifact 和 dispatch handoff。
- harness-first verification: 用真实多轮链路证明协作协议，不只测纯函数。

## 允许自由度

本文档不锁死类名、文件名、状态字段和内部拆分。goal 可以根据 clowder-ai 和 xmuse 当前源码重新调整设计。

允许替换的内容:

- `DiscussionRun` / `ChatMultiMention` / `Objection` / `ProposalBridge` 等名称。
- 存储表结构、Pydantic model 形态、API route 命名。
- TUI 命令名称和页面组织。
- artifact routing 的内部实现。

不允许降低的能力:

- 有状态协作 lifecycle。
- bounded request/response aggregation。
- structured objection / veto。
- proposal/artifact bridge。
- real-provider dispatch gate。
- anti-cascade / timeout / max-depth。
- durable runtime trace。
- TUI/dashboard 半透明事件可见。
- restart/resume。
- real task 多轮执行和 review iteration。

## 编排模式

### `peer_consensus` 默认模式

默认采用角色加权的对等协商:

- 任一 GOD 可发起结构化协作请求、修正、反对、请求补充。
- `architect` 默认负责把讨论收束为 proposal / artifact。
- `execute` 必须确认 proposal 可执行，或返回 feasibility blocker。
- `review` 拥有 veto 权；active veto 必须阻止 dispatch。
- `init-god` 负责 bootstrap、模式切换、异常收口、恢复，不做日常独裁调度。

### `leader_assisted` 可选模式

保留 architect/init-god 主导路径，适合简单任务或需要更少 token 的场景。它必须复用同一套
collaboration、proposal、dispatch、trace 能力，不能成为另一条临时捷径。

## 核心能力要求

### 1. 有状态协作运行

每个真实任务必须有 durable lifecycle，可追踪:

- conversation id
- goal / user request
- orchestration mode
- participants
- current round
- current phase
- active blockers/vetoes
- proposal/artifact refs
- dispatch/run refs
- review/iteration result

建议状态可参考:

```text
intake -> deliberating -> proposal_ready -> execution_ready
-> dispatching -> executing -> reviewing -> iterating
-> complete | blocked | failed
```

### 2. Bounded multi-party collaboration

GOD 间协作不能只是裸 `@role` 文本。必须支持结构化 request/response:

- initiator
- targets
- callback/aggregation target
- question
- context refs
- idempotency key
- timeout
- status: `pending/running/partial/done/timeout/failed`
- per-target response
- max-depth / anti-cascade evidence

### 3. Structured objection / veto

review、execute、architect 的阻塞意见必须结构化，至少包含:

- blocker id
- issuer role / participant
- severity
- reason
- affected artifact / lane / command / UI surface
- suggested fix
- active/resolved status
- whether dispatch is blocked

Active veto 必须阻止 dispatch。解除 veto 必须有可追踪证据。

### 4. Proposal / artifact bridge

讨论结果必须落到 xmuse 现有结构化体系，不能创造第二套 execution authority。

artifact routing 按复杂度自动选择:

- 简单任务可直接生成 `lane_graph` proposal。
- 复杂任务走 `mission_blueprint -> feature_plan -> lane_graph`。
- V14 最终 gate 必须至少覆盖一条完整链路，不允许只用直接 lane graph 捷径证明闭环。

### 5. Real-provider dispatch gate

默认允许自动真实执行，但 dispatch 前必须验证:

- structured proposal/artifact exists
- artifact 可追踪到 conversation/discussion run
- execute 已确认可执行
- review 没有 active veto
- anti-cascade / max-depth 通过
- dispatch policy 允许真实 provider
- trace/read surface 可落库

普通聊天、普通 `@execute`、普通 “我可以执行” 文本都不能单独触发真实执行。

### 6. Runtime trace + read surface

TUI/dashboard 必须能读取半透明结构化事件:

- collaboration requested
- responses collected / timeout / partial
- proposal ready
- blocker/veto raised/resolved
- dispatch started
- execution progress
- review result
- iteration started/complete
- final closure

不要暴露原始 JSON 给用户。参考 Codex/OpenCode 类 agent TUI 的表达: 当前阶段、动作、工具/命令、
结果、失败原因、下一步。

## 真实验收任务: TUI production closure

V14 的 proof task 固定为:

> 根据 xmuse 后端与当前愿景，参考 Codex/OpenCode 等主流 agent TUI，实现 xmuse TUI 的生产级可用闭环:
> 完善 `/` 命令系统、用户页面可用性、dashboard 展示、运行/审查/阻塞可观测性，以及必要的 TUI 基建设施。

允许直接修改:

- `xmuse/tui/**`
- `xmuse/chat_api.py`
- dashboard/read API 相关文件
- `src/xmuse_core/chat/**`
- 需要支撑 read surface / runtime trace / dispatch bridge 的 xmuse runtime 文件
- 对应 tests/docs/handoff

命令系统不预设完整命令表，来源只允许两类:

1. xmuse 系统闭环必需入口，例如 conversation、bootstrap、discussion run、dispatch、review、blocker、
   resume、dashboard、provider health。
2. Codex/OpenCode 等主流 agent TUI 已验证的基础设施，例如 command palette、输入历史、搜索、
   日志/trace、provider 状态、快捷键帮助、面板导航。

新增命令必须说明适配理由，并有测试和真实演示路径。不能只注册空壳。

最低 TUI gate:

- 可创建/恢复 conversation。
- `/new` 后自动进入 init-god 引导，而不是静默建会话。
- bootstrap/init 状态可见，action 可原生选择，不要求用户复制长命令。
- discussion run / dispatch / blockers 可见。
- orchestration mode 可展示，必要时可切换。
- dashboard/overview 能看到群聊、执行、review 的关联状态。
- TUI 可真实启动并完成演示路径。

## Goal 执行规范

1. 必须使用 `superpowers:brainstorming`、`superpowers:test-driven-development`、
   `superpowers:subagent-driven-development`、`superpowers:requesting-code-review`、
   `superpowers:verification-before-completion`。
2. 必须先做 clowder-ai intake，并写出 clowder -> xmuse 映射。
3. 必须按 RED -> implementation -> verification 推进关键能力。
4. 必须让 review subagent 介入 runtime gate、dispatch gate、TUI/read surface gate。
5. 允许 goal 执行者作为 human/product owner 在真实群聊中对话、澄清、调整方向。
6. 人工介入必须可追踪；不能手工创建 artifact、手工 dispatch、手工跳过 review/veto 来伪造闭环。
7. 如果真实任务范围需要调整，必须记录原因，且不能降低终止条件。
8. 每轮迭代必须更新 `docs/xmuse/codex-strengthening-handoff.md`。

## 强 gate

### Clowder intake gate

- 已读 clowder 必读路径。
- 文档/handoff 有 clowder -> xmuse 映射表。
- 偏离 clowder 机制时，写明 xmuse-specific 原因。

### Runtime gate

- fresh conversation 自动 bootstrap。
- GOD 间协作有结构化 request/response 聚合。
- 至少一次 review veto/blocker 阻止 dispatch。
- 修正后 blocker 被解除并可追踪。
- 至少一次自动 dispatch 进入真实 provider 执行层。
- 普通聊天文本不能直接 dispatch。

### Real task gate

- 正式 TUI 主路径代码被修改并可运行。
- `/` 命令、dashboard/overview、blocker/dispatch/read surface 的新增能力有测试。
- TUI 能真实启动，用户能通过界面看到 init、run、dispatch、review 事件。
- 不能只产出计划、文档或 fake-only demo。

### Restart/resume gate

- runner/backend/TUI restart 后，conversation 可恢复。
- GOD sessions 可复用或有明确 degraded evidence。
- pending discussion run、proposal、blocker、dispatch trace 可恢复。
- 不丢 active blocker/proposal/dispatch 状态。

### Soak gate

- 真实 Ray + Codex app-server + MCP writeback。
- 多轮协作，至少包含 fresh run 和 restart/resume run。
- 无 stdout fallback happy path。
- 无 MemoryOS dependency/config/runtime use。
- 无残留 `codex app-server`、`raylet`、`gcs_server`、`ray::` 进程。
- 记录 latency、dispatch、review、iteration trace。

### Quality gate

- Focused tests 覆盖 runtime/proposal/dispatch/TUI/read surface。
- Affected regression tests 通过。
- Ruff touched files 通过。
- `git diff --check` 通过。
- review subagent 无 critical findings；如有 findings，必须修复或记录非阻塞理由。

## 终止条件

V14 只能在以下条件全部满足后标记 complete:

- clowder-ai intake 和映射完成。
- decentralized groupchat runtime 能驱动真实 TUI 任务。
- 真实 provider 自动执行至少一次正式代码修改。
- review/veto 负例和解除路径被真实或 focused gate 覆盖。
- TUI/dashboard 可演示 init、discussion、dispatch、review、blocker、resume。
- fresh + restart/resume 真实链路通过。
- 无 MemoryOS 依赖。
- 无 stdout fallback happy path。
- 无残留 Ray/app-server 进程。
- handoff 记录最终 commands/results、trace evidence、剩余风险。

不能因为“单测通过”提前收口。不能把 fake provider demo 当成 production evidence。不能把普通聊天回复当成
执行闭环。
