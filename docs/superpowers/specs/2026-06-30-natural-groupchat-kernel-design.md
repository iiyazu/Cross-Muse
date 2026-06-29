---
status: design
created: 2026-06-30
topic: xmuse natural groupchat kernel
source: brainstorming with operator
---

# Natural Groupchat Kernel Design

This document records the approved brainstorming design for the Track A
natural groupchat vision. It is a design artifact, not the xmuse operational
entrypoint. The current operational documentation remains under `docs/xmuse/`.

Do not use this document to restart old L8-L11, closure-ledger, Path-A, or
pre-M7 framing. The design below starts from the current xmuse baseline:
`chat.db`, inbox, proposal, review verdict, dispatch queue, execution harness,
final-action gate, and GitHub server facts are the authority surfaces.

## Vision

xmuse should provide a decentralized natural agent groupchat harness and a
strict development-chain harness.

Track A focuses on the first half: a single natural groupchat conversation
should let multiple agents deliberate, challenge each other, and form durable
decisions without a central agent silently becoming the only decision maker.

The execution harness already occupies the external-work execution role.
Therefore the groupchat design should not duplicate clowder-ai's main/subthread
task distribution model. xmuse should instead focus on the single-conversation
natural groupchat runtime that produces decisions for the existing execution
harness to consume.

## Stage Architecture

Track A should close in stages. A later long goal can take a stage-sized slice,
but the vision is the whole ladder:

```text
A1 Natural Groupchat Kernel
-> A2 Groupchat Decision Closure
-> A3 Dispatch To Execution Harness
-> A4 Result Writeback To Groupchat
-> A5 Unattended Groupchat Development Loop
```

### A1: Natural Groupchat Kernel

A1 proves that one `chat.db` conversation can host a real natural groupchat
runtime. Architect, review, and critic participants can be routed, queued,
claimed, invoked, and written back through durable authority.

A1 does not require PR creation, proposal approval, MemoryOS continuity, or
frontend completeness.

### A2: Groupchat Decision Closure

A2 turns discussion into durable decisions:

```text
discussion chain
-> architect proposal candidate
-> critic objection or clearance
-> review verdict
-> approved decision or durable blocker
```

The acceptance boundary is not that an agent says "approve" in text. The
boundary is that authority stores contain proposal, objection, clearance,
review verdict, and blocker references that future stages can consume.

### A3: Dispatch To Execution Harness

A3 makes an approved groupchat decision produce a dispatch queue entry consumed
by the existing execution harness.

The groupchat layer must not write lane status directly, run worker code, or
create GitHub truth. It produces decisions and source refs. The execution
harness consumes them.

### A4: Result Writeback To Groupchat

A4 writes execution and review outcomes back into the conversation timeline:

```text
dispatch accepted
execution started
execution evidence produced
review accepted or blocked
final action pending or resolved
GitHub gate evidence or gap observed
main CI observed
```

The groupchat can then continue from durable result refs instead of relying on
operator summaries or provider stdout.

### A5: Unattended Groupchat Development Loop

A5 proves repeated long-running cycles:

```text
demand
-> discussion
-> decision
-> dispatch
-> execution
-> result writeback
-> next decision
```

Success means the system can proceed without human routing and can stop with a
durable blocker when human input is required.

## A1 Kernel Design

### Roles

A1 uses a fixed three-role roster:

```text
architect: proposes structure, implementation direction, and proposal candidates
review: checks goals, boundaries, acceptance, and compliance
critic: challenges assumptions, bias, risks, weak evidence, and premature closure
```

The critic role is not a second reviewer. It exists to reduce central-agent
bias and force explicit challenge before decisions harden.

### Authority Surfaces

A1 authority is:

```text
chat_messages: conversation timeline truth
groupchat_worklist: groupchat routing and handoff truth
chat_inbox_items: participant delivery truth
structured callback/writeback: provider response truth
```

The following are not authority:

```text
provider stdout
raw text mention before normalization
frontend cards
MemoryOS recall
worker summaries
local tests
```

Text mentions are candidate signals only. A route becomes real only after it is
accepted into `groupchat_worklist`.

### Routing Rules

Human messages:

```text
explicit @mentions: enqueue up to 2 valid targets
no explicit @mention: lightweight local router chooses 1 target
```

Agent messages:

```text
explicit @mentions: use only the first valid target
no explicit @mention: no automatic route
structured route intent: allowed, but still passes policy guards
```

The lightweight router is local and deterministic. It must not call a model.

Suggested routing categories:

```text
implementation, proposal, build, fix, add, design -> architect
review, verify, audit, acceptance, check -> review
why, risk, bias, challenge, not accepted, correction, no progress -> critic
fallback -> critic
```

This intentionally avoids routing all unaddressed messages to architect.

### Chain Policy

A1 should use policy-driven depth rather than a hardcoded global depth.

Default policy:

```text
policy_id = default-natural-groupchat
max_depth = 3
human_max_targets = 2
agent_max_targets = 1
max_items_per_tick = 1
pingpong_warn_after = 2
pingpong_block_after = 4
```

This allows:

```text
human -> architect -> critic -> review
```

without allowing unbounded agent fanout.

### Scheduler Ownership

A1 adds a thin `GroupchatWorklistScheduler`.

It owns:

```text
groupchat_worklist claim and status transitions
chain policy
depth guard
dedup guard
ping-pong guard
route candidate enqueue
```

It reuses:

```text
chat_inbox_items
PeerChatScheduler
provider service
existing structured callback/writeback path
```

Flow:

```text
new chat message
-> mention/router candidate detection
-> guard validation
-> groupchat_worklist enqueue
-> scheduler claims one item
-> scheduler creates or links a chat_inbox_item
-> existing PeerChatScheduler runs exactly that delivery
-> provider writes a durable chat message through callback/writeback
-> scheduler completes the worklist item with completed_message_id
-> completed message is scanned for the next candidate route
```

The scheduler must not recursively cascade provider calls in the same tick.

## Data Model

### groupchat_chains

A1 should create chain-level records so policy and status are explicit:

```text
chain_id
conversation_id
policy_id
root_message_id
max_depth
human_max_targets
agent_max_targets
pingpong_warn_after
pingpong_block_after
status
created_at
updated_at
```

Allowed `groupchat_chains.status` values for A1:

```text
open
completed
blocked
failed
canceled
```

### groupchat_worklist

Minimal item fields:

```text
item_id
conversation_id
chain_id
policy_id
source_message_id
source_participant_id
target_participant_id
target_role
route_kind
status
depth
dedup_key
claim_owner
claimed_at
completed_message_id
failure_reason
created_at
updated_at
```

Allowed `route_kind` values for A1:

```text
mention
router
handoff
review_request
```

Allowed `status` values for A1:

```text
queued
claimed
completed
failed
canceled
```

### Dedup

Suggested dedup key:

```text
conversation_id | chain_id | source_message_id | target_participant_id | route_kind
```

The same source message must not wake the same target more than once. A target
already pending or claimed in the same chain should not be re-enqueued from an
equivalent candidate.

### Depth

Depth semantics:

```text
root human route depth = 0
first agent turn depth = 1
agent to agent route depth increments by 1
depth >= max_depth blocks the next route
```

Depth blocks should be durable and diagnosable, not silent skips.

### Failure Reasons

Failure reasons should be structured:

```text
target_participant_missing
depth_limit
duplicate_route
pingpong_blocked
provider_timeout
callback_missing
inbox_delivery_failed
```

## Testing And Acceptance

A1 must prove:

```text
1. A conversation has architect, review, and critic participants.
2. A human message routes by explicit mention or lightweight router.
3. A durable groupchat_worklist item is created.
4. The scheduler claims one item.
5. The target participant receives a linked chat_inbox_item.
6. A provider or deterministic test double writes a durable chat message.
7. The worklist item completes with completed_message_id.
8. The completed message can produce a next-hop candidate.
9. Depth, dedup, and ping-pong guards are enforced.
10. Provider stdout, frontend projection, and MemoryOS are not authority.
```

Test layers:

```text
unit:
  mention parser
  lightweight router
  policy guard
  dedup key
  ping-pong state

store:
  groupchat_chains lifecycle
  groupchat_worklist enqueue, claim, complete, fail, cancel

integration:
  human -> architect worklist
  architect -> critic next hop
  critic -> review within max_depth
  duplicate mention no double enqueue
  depth_limit blocks next hop
  pingpong_blocked records failure

runtime smoke:
  deterministic provider or fake callback writes durable messages and verifies
  chat.db, groupchat_worklist, and chat_inbox_items state
```

Real Codex provider runtime evidence may be collected manually or in long-goal
runs. It should not be the mandatory CI gate for A1 because it would be slow and
unstable.

## Performance Boundaries

A1 must be conservative:

```text
no full conversation rescan
cursor-based or item-based message scan
max_items_per_tick defaults to 1
agent messages produce at most 1 next target
human messages produce at most 2 targets
recent K context only for provider prompts
chain policy is configurable
```

The design should prefer stable long-run behavior over a large fanout in a
single tick.

## Risks

### Boundary drift with PeerChatScheduler

Risk: groupchat scheduling semantics leak into participant inbox metadata.

Mitigation: `GroupchatWorklistScheduler` owns groupchat state. `PeerChatScheduler`
is only the delivery/provider-turn consumer.

### Critic fallback slows progress

Risk: fallback-to-critic may produce more questions before implementation.

Mitigation: A1 optimizes for anti-bias and route correctness. A2 can tune
decision closure once the runtime kernel is stable.

### New tables add migration cost

Risk: new stores add code and test surface.

Mitigation: groupchat routing is a core authority. Keeping it separate from
`chat_inbox_items` prevents later migration from overloaded inbox metadata.

### Ping-pong guard overreach

Risk: a simple pair counter may block useful challenge loops.

Mitigation: A1 uses the simplest durable pair counter. Later stages can adopt a
clowder-style substantive-activity exemption if needed.

## Non-Goals

A1 does not implement:

```text
PR creation
guarded merge
main CI observation
MemoryOS continuity
frontend UX completeness
main/child conversation orchestration
multi-lane scheduling
execution harness replacement
```

Those are downstream stages or existing harness responsibilities.

## Design Decision

Use the Kernel-First staged approach:

```text
A1 groupchat_worklist + scheduler + fixed three-role natural relay
A2 durable groupchat decision closure
A3 dispatch into existing execution harness
A4 execution result writeback into groupchat
A5 unattended multi-cycle groupchat development loop
```

This keeps the primary vision centered on decentralized natural groupchat while
preserving xmuse's existing execution harness as the downstream consumer.
