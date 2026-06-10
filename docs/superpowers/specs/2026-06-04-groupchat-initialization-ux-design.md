# Groupchat Initialization UX Design

Date: 2026-06-04

## Goal

把 xmuse 群聊初始化从“固定 seed participants”提升为产品级初始化流程：

```text
create conversation
-> ensure init god session
-> choose preset/provider/role templates
-> produce auditable team plan
-> validate/apply team plan
-> materialize peer gods + durable session records + fork lineage
-> conversation ready
```

本设计只定义初始化 UX 和后端契约，不改 memoryOS，不扩展 execution/review plane，不引入 Letta 级 runtime。

## Current Baseline

当前代码已经具备基础能力：

- `PeerChatService.create_conversation()` 是建群单一路径。
- 建群会创建 `init` participant 和真实 `init god` session。
- 默认会创建 `architect / review / execute` participants。
- bootstrap artifact 已写入 `artifacts/chat_bootstrap/<conversation_id>.json`。
- `RoleTemplateStore`、`ParticipantStore`、`PeerForkStore`、`GodSessionRegistry` 已存在。
- `fork_participant(...)` 可以记录 fork lineage，但当前 bootstrap artifact 的 `fork_plan` 仍固定为空。

主要缺口：

- preset 不是一等契约，只是硬编码默认角色。
- provider/role/template 选择没有产品化入口。
- `init god` 没有真正参与“收集上下文 -> 提议队伍 -> fork peers”的流程。
- TUI 还没有明确 `/new` 或 `/init` 初始化向导。

## Recommended Approach

采用两阶段 Hybrid 初始化：

1. 后端确定性创建 conversation、init god、bootstrap draft。
2. init god 可基于用户输入和上下文产出结构化 `TeamPlanProposal`。
3. init god 不能直接写 participants/session/fork records。
4. 后端验证 proposal，通过后 apply，物化 peer gods、durable session records、role templates、fork lineage。
5. TUI/API 只调用后端契约，不自行拼装 participants。

这样保留 init god 的智能规划价值，同时避免模型直接污染运行时状态。

## Product UX

### Primary Entry

后端契约优先，TUI 消费：

```text
/new
  title: <conversation title>
  preset: architect-review-execute
  providers:
    architect: codex/god
    review: codex/review
    execute: codex/worker or opencode/<explicit-model>
  init_mode:
    deterministic
    proposal_then_approve
```

初版默认：

- `preset = architect-review-execute`
- `init_mode = proposal_then_approve`
- Codex 是 primary provider。
- OpenCode 仅在显式模型存在时允许。
- Claude Code 不进入 groupchat provider adapter，除非后续已有正式 adapter。
- `proposal_then_approve` 不允许 `POST /api/chat/conversations` 同步 apply，必须走后端 apply endpoint。

### Preset Modes

建议先支持四个内置 preset：

| Preset | Roles | Use Case |
|---|---|---|
| `architect-review-execute` | architect, review, execute | 默认中大型需求讨论 |
| `architect-review` | architect, review | 方案讨论和审计 |
| `solo-architect` | architect | 轻量需求澄清 |
| `debug-light` | architect, review | 使用低成本模型/profile 的运行时验证 |

每个 preset 都必须解析为同一个后端 `BootstrapDraft`，不能在 TUI/API 层写死 participants。

## Core Contracts

### GroupchatPreset

定义初始化模板：

```python
class GroupchatPreset(BaseModel):
    preset_id: str
    display_name: str
    description: str
    roles: list[PresetRoleSpec]
    allowed_overrides: list[Literal["provider", "model", "template", "display_name"]]

class PresetRoleSpec(BaseModel):
    role: str
    address_slug: str
    display_name: str
    template_slug: str
    provider_id: Literal["codex", "opencode"]
    profile_id: str
    model: str
```

`role` 是能力标签，不是唯一身份。唯一性由 `address_slug` 和 `display_name` 约束。

### BootstrapDraft

后端创建 conversation 后立即生成：

```python
class BootstrapDraft(BaseModel):
    draft_id: str
    conversation_id: str
    preset_id: str
    init_participant_id: str
    init_session_id: str
    requested_overrides: dict[str, Any]
    default_team: list[LogicalPeerSpec]
    status: Literal["drafting", "proposal_ready", "validation_failed", "applied", "degraded"]
    created_at: str
    updated_at: str
```

`BootstrapDraft` 的权威状态应在 chat-owned store 中持久化；JSON artifact 是 audit mirror，不是唯一权威状态。

### TeamPlanProposal

init god 或 deterministic planner 产出的结构化计划：

```python
class TeamPlanProposal(BaseModel):
    proposal_id: str
    draft_id: str
    conversation_id: str
    source: Literal["init_god", "deterministic"]
    peers: list[LogicalPeerSpec]
    fork_plan: list[LogicalForkSpec]
    rationale: str
    validation_status: Literal["pending", "accepted", "rejected"]

class LogicalPeerSpec(BaseModel):
    role: str
    address_slug: str
    display_name: str
    template_slug: str
    provider_id: Literal["codex", "opencode"]
    profile_id: str
    model: str

class LogicalForkSpec(BaseModel):
    source_role: Literal["init"]
    target_address_slug: str
    prompt_delta: str
    inherited_refs: list[str]
    fork_reason: str
```

Proposal 是写入前的计划，不是运行时事实。
Proposal 只能包含 logical specs。它不得携带 `participant_id`、`god_session_id`、`fork_id`、provider-native session id、existing binding id，或任何 authority-store primary key。

### AppliedBootstrap

proposal 被接受后产生的权威结果：

```python
class AppliedBootstrap(BaseModel):
    apply_id: str
    draft_id: str
    proposal_id: str
    conversation_id: str
    participants: list[str]
    durable_god_sessions: list[str]
    fork_records: list[str]
    status: Literal["bootstrapped", "degraded"]
    created_at: str
```

Bootstrap apply 只创建 durable xmuse session records，例如 `GodSessionRegistry` 记录；不得在建群时强制启动 live Ray actor、provider app-server 或 provider-native resume。真实 provider binding 和 live transport 仍由首次调度 turn 触发。

### Idempotency

`apply_id` 必须由 `conversation_id + proposal_id` 派生。fork lineage 必须使用 deterministic idempotency key，例如：

```text
bootstrap-fork:{conversation_id}:{proposal_id}:{source_peer_id}:{target_address_slug}
```

重复 apply 同一个 proposal 必须返回已有 participants、durable sessions、fork records，不得追加重复 lineage。

## Data Flow

```text
POST /api/chat/conversations
  -> create conversation
  -> ensure init god participant/session
  -> resolve preset + overrides
  -> write BootstrapDraft artifact
  -> return conversation + bootstrap state

POST /api/chat/conversations/{conversation_id}/bootstrap/proposals
  -> create deterministic proposal or ask init god for TeamPlanProposal
  -> validate proposal shape
  -> store proposal
  -> return proposal + validation result

POST /api/chat/conversations/{conversation_id}/bootstrap/apply
  -> require accepted proposal or deterministic auto-apply mode
  -> validate proposal against current conversation state
  -> materialize participants + durable GodSessionRegistry records + fork lineage
  -> write AppliedBootstrap artifact
  -> return conversation + participants + bootstrap state
```

TUI `/new` should call this flow rather than creating participants locally.

`init_mode = deterministic` may auto-create and apply the deterministic proposal in one backend request. `init_mode = proposal_then_approve` must stop at `proposal_ready` until TUI/API calls apply.

## Validation Rules

- `init` participant is unique per conversation.
- `address_slug` and `display_name` are unique within a team; multiple peers may share the same `role` capability label.
- every participant has provider/profile/model/template resolved.
- non-Codex providers require explicit model.
- provider overrides must include `provider_id`, `profile_id`, `cli_kind`, and `model`; API models must accept OpenCode only with explicit model.
- proposal cannot reference participants outside the conversation.
- proposal cannot supply authority ids: `participant_id`, `god_session_id`, `fork_id`, provider-native session id, binding id.
- fork lineage requires both source and target persistent sessions.
- apply is idempotent for the same accepted proposal.
- rerun must not duplicate participants, sessions, or fork records.
- restart must preserve each god's durable `god_session_id`; live provider transport may be recreated by runtime scheduling.

## Error Handling

Use explicit bootstrap status:

- `drafting`: conversation/init exists, team not applied.
- `proposal_ready`: a proposal exists and awaits apply.
- `proposal_failed`: init god could not produce valid proposal.
- `validation_failed`: proposal rejected by deterministic validator.
- `bootstrapped`: peers materialized and ready.
- `degraded`: bootstrap succeeded with provider/runtime fallback.

Failures must leave a readable artifact with reason and safe retry identity.
Retry identity is `draft_id` for proposal generation and `apply_id` for apply. Mutable current status lives in chat-owned bootstrap state; artifacts are append-only audit snapshots.

## TUI Surface

TUI should expose:

- `/new` create groupchat wizard.
- `/init status` inspect current bootstrap state.
- `/init retry` retry proposal generation for the current draft.
- `/init apply` apply an accepted proposal.
- preset list with short descriptions.
- provider/model override per role.
- role template preview.
- final team confirmation before apply when `proposal_then_approve`.

TUI should not:

- write participants directly.
- infer provider compatibility by itself.
- create fork lineage directly.

## Testing Gates

Focused gates:

- create conversation with default preset creates conversation, init participant, init session, and bootstrap draft.
- `proposal_then_approve` create stops at `proposal_ready` and does not create peer participants before apply.
- deterministic mode may auto-apply through the backend contract and create the applied team.
- custom preset/provider overrides are reflected in proposal and participants.
- init proposal cannot directly mutate participants.
- proposal containing `participant_id`, `god_session_id`, `fork_id`, provider-native session id, binding id, or foreign conversation refs is rejected.
- invalid provider/model/template proposal is rejected before apply.
- proposal apply is duplicate-safe.
- duplicate apply does not append duplicate fork lineage.
- OpenCode participant override is accepted only with explicit model.
- bootstrap rerun after partial failure resumes without duplicate records.
- restart preserves durable `god_session_id` without requiring live provider transport at bootstrap time.
- TUI `/new` calls backend contract and does not synthesize participants.
- no new memoryOS import/config/runtime dependency is introduced.

Real-chain gate:

- start backend + TUI-compatible API path.
- create groupchat with default preset.
- verify `init`, `architect`, `review`, `execute` identities are stable.
- send a message to architect.
- restart runtime.
- verify same participant/session identity is reused.

## Non-Goals

- No memoryOS integration.
- No semantic shared memory design.
- No new execution DAG behavior.
- No provider parity beyond existing Codex/OpenCode constraints.
- No autonomous model-written runtime mutation.
- No dashboard redesign.

## Implementation Order

1. Introduce backend preset/proposal/apply contracts.
2. Move existing hardcoded bootstrap into default preset resolver.
3. Add proposal validation and idempotent apply.
4. Add deterministic proposal/apply first.
5. Connect init god proposal as optional path behind deterministic validator.
6. Add TUI `/new`, `/init status`, `/init retry`, and `/init apply` command flow.
7. Add full restart/resume smoke for initialized groupchat.

## Acceptance Definition

群聊初始化可称为产品级闭环，当且仅当：

- 用户能选择 preset/provider/role template 创建群聊。
- init god 有可审计 proposal 或 deterministic replacement。
- peer gods 由后端权威 apply 物化。
- fork lineage 不再永远为空，至少能用 idempotent fork key 表达 init -> peer team 的初始化来源。
- 重启后每个 god 复用原 durable `god_session_id`。
- TUI 只是后端契约的 UX 层，不是第二套初始化实现。
