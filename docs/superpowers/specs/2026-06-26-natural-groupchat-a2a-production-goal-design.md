# Natural Groupchat A2A Production Goal Design

Date: 2026-06-26

## Purpose

This design defines the next multi-hour xmuse `/goal`.

The goal is to make xmuse use its own natural agents groupchat to complete a
small real xmuse change through:

```text
Chat API human demand
-> durable natural groupchat
-> real Codex provider participants
-> proposal or fail-closed blocker
-> structured review verdict
-> approved or blocked state
-> dispatch / execution
-> PR
-> CI observation
-> operator merge or explicit blocker
```

This is not a spec for production-ready natural groupchat as a finished
product. It is a design for the next long goal that moves the real chain
forward without repeating prior infrastructure-only loops.

## Current Calibration

The current public main is `origin/main` after PR #192:

```text
bd540de Merge pull request #192 from iiyazu/codex/m6-authority-inbox-stdout-fallback-guard
```

Important current facts:

- `review_trigger` authority now requires structured
  `review_trigger_verdict` writeback.
- provider stdout and degraded fallback are diagnostic only for
  `review_trigger`.
- `chat.db`, inbox, proposals, review trigger verdicts, dispatch queues, and
  acceptance/final gates remain xmuse authority.
- MemoryOS is an opt-in integration surface, not a groupchat authority.
- Ray exists as an optional runtime layer, but it is not the right default
  natural groupchat kernel.

The original repository worktree may contain dirty historical branches and
unmerged assets. The next goal must start from a clean `origin/main` worktree.
Unmerged files may be read as reference only after truth refresh.

## Design Decision

Use this default architecture:

```text
natural groupchat
-> official a2a-sdk provider / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / CI / operator merge
```

Do not use this as the default architecture:

```text
natural groupchat
-> RayGodSessionLayer
-> Ray actor
-> provider transport
```

Ray should be isolated as an optional legacy runtime adapter. The long goal
should not spend its main effort patching Ray. If Ray blocks the real natural
groupchat chain, bypass it through provider-native sessions and the A2A SDK
provider boundary.

## Why A2A SDK, But Not As Authority

A2A is useful for agent interop and collaboration shape:

- agent cards and capability discovery;
- task / message / artifact envelopes;
- remote agent invocation;
- normalized provider result status;
- natural handoff between participants.

The implementation plan must directly introduce the official Python
`a2a-sdk` package for new public A2A surfaces instead of growing another
homegrown wire protocol. The existing `xmuse_core.integrations.a2a_bridge`
should be treated as a thin compatibility bridge and migration reference, not
as proof of official SDK compliance.

Minimum SDK scope for the next goal:

```text
Agent Card
task/send lifecycle
task status mapping
text/data/file artifact parts
JSON-RPC / HTTP boundary
explicit non-goals for streaming and push notifications unless implemented
```

A2A is not the xmuse authority store. Every event that matters must be
normalized into xmuse durable state before it can affect proposal, review,
dispatch, or merge state.

Required rule:

```text
A2A event
-> xmuse chat.db message / inbox item / structured envelope
-> xmuse gate consumes the normalized artifact
```

Never allow:

```text
A2A task status
-> direct proposal approval / dispatch / merge
```

## Clowder-AI Extraction

Reference source:

```text
/home/iiyatu/clowder-ai
```

Borrow the core shapes, not the product stack:

| clowder-ai primitive | xmuse adoption |
|---|---|
| `SystemPromptBuilder` | layered xmuse prompt: L0 rules, role identity, roster, current task, tool/writeback instructions |
| `ContextAssembler` | bounded transcript, structured state refs, proposal/review/dispatch refs, MemoryOS recall |
| line-start A2A mention parsing | strict natural handoff trigger with code-block stripping, target validation, self-filtering |
| `InvocationQueue` / `WorklistRegistry` | one handoff/worklist path with depth, dedupe, coalescing, ping-pong guard |
| `SessionMutex` | serialize same provider-native session while allowing cross-participant concurrency |
| `MessageDeliveryService` | reconcile callback/writeback before UI/API projection |
| `A2AAgentService` | informs the adapter shape; `a2a-sdk` supplies the actual public wire protocol |

Do not copy:

- clowder-ai Redis authority;
- full product UI;
- broad rich-message system;
- its entire queue stack if xmuse `chat.db` and inbox already express the
  authority path.

## Main Components

### Agent Profile And Card

Add or refine a minimal agent profile/card contract:

```text
participant id
role
provider runtime
model
capabilities
supported task types
endpoint / auth state when remote
session binding state
health / availability
```

This should be readable by frontend APIs and prompt/context assembly. It must
not approve work by itself.

When exposed as an A2A Agent Card, use SDK-compatible models and keep read-only
card access separate from write access to task submission.

### Security And Authority Gate

Security is an M0/P0 condition for A2A provider work, not a release polish item.

Required behavior:

```text
A2A bridge/server disabled by default
Chat API / MCP / A2A write paths local-only or token-gated by default
read-only Agent Card and task/send write path permissions separated
missing token rejected for write paths
valid token accepted for write paths
trusted-local-only mode documented separately from external exposure
```

No A2A endpoint may be described as externally safe until these gates are
implemented and validated.

### Prompt Builder And Context Assembler

Prompt construction should be centralized and layered:

```text
xmuse L0 rules
+ role identity
+ roster / capability summary
+ current inbox item or task
+ bounded transcript
+ structured state refs
+ MemoryOS recall, if enabled
+ exact MCP/writeback instructions
```

If prompt construction requires scattered string fragments across scheduler,
service, provider, and tests, refactor it into one focused builder instead of
patching fragments.

### Canonical Handoff Task Envelope

Natural handoff should normalize to one envelope shape:

```text
schema_version
task_id
type
source_participant_id
target_participant_id or target_participant_ids
intent
source_message_id
source_inbox_item_id
input_parts
artifact_refs
what
why
tradeoffs
open_questions
next_action
evidence_refs
conversation_id
feature_scope_id, when present
```

Line-start mention should be treated as a handoff signal, but the result must
be a durable xmuse inbox/task item, not an in-memory side route.

Failure semantics:

```text
missing why / next_action / evidence_refs -> ask or durable blocker
review handoff -> never approval by itself
execute handoff -> never dispatch authorization by itself
```

The canonical schema must merge the A2A task shell with xmuse's existing
`natural_handoff.py` required fields.

### Durable Natural Route Worklist

Natural routing must become durable execution control, not only a payload hash.

The implementation plan must declare:

```text
where route_key persistence and dedupe happen
how replay/restart avoids duplicate inbox creation
where max_depth and max_fanout are enforced
where ping-pong / loop blockers are written
whether human mention, MCP callback, provider final text, and A2A inbound share one entry path
why provider stdout / streamed text cannot directly trigger review or dispatch authority
```

### Provider Runtime Adapter

Default runtime path:

```text
provider-native CLI session / resume
```

Optional runtime paths:

```text
A2A remote provider
Ray legacy local actor
```

Ray must not be the natural groupchat default. Existing Ray tests may remain as
compatibility coverage, but new production proof should prefer
provider-native/A2A SDK runtime boundaries.

Ray migration boundary:

```text
Ray/Codex/MCP path remains supported until provider-native/A2A SDK child runtime proves parity
MCP writeback authority must be preserved
existing full-chain real runtime tests must pass or be documented as known baseline
Ray-specific code may be isolated behind an adapter, not removed in the first slice
```

Provider-native parity gate:

```text
durable inbox read
durable proposal or fail-closed blocker
structured review_trigger_verdict
dispatch acknowledgement via xmuse authority
no provider stdout as truth
same source_refs lineage as existing Ray/Codex/MCP path
```

### Writeback Reconciler

Provider output must pass through one reconciliation boundary before it is
projected or consumed:

```text
provider result / A2A task / MCP callback
-> normalized message/envelope
-> inbox reply linkage
-> proposal/review/dispatch gate
-> read-only projection
```

Provider stdout can be diagnostic. It cannot create review truth or merge truth.

## MemoryOS Role

MemoryOS is an opt-in sidecar:

```text
conversation summary
decisions
blockers
artifact refs
source refs
restart recall
```

MemoryOS recall may enter `ContextAssembler`. It must not directly mutate
`chat.db`, proposal, review, dispatch, or merge state.

Failure behavior:

```text
MemoryOS unavailable -> degraded recall omitted -> main chain continues
```

If live MemoryOS is available, the goal may record live proof. If it is not
available, fake/local contract proof is acceptable for this phase.

## Frontend Scope

Do not attempt a full frontend implementation in this goal.

Improve the frontend/API contract so a future frontend can work out of the box:

```text
conversation timeline
agent cards
inbox / worklist
review / dispatch state
blocker / next action
artifact/source refs
card summary with collapsible detail payload
```

These APIs are read-only projections. They do not create truth.

## Execution Phases

### Phase 0: Truth Refresh

Start from clean `origin/main`.

Record:

```text
git status -sb
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
open PRs and exact heads
provider availability
which local/remote references contain useful natural groupchat assets
```

Exit criteria:

- active clean worktree chosen;
- first real runtime chain selected;
- Ray marked optional legacy for this goal;
- existing `natural_routing.py`, `natural_handoff.py`, `a2a_bridge.py`,
  `review_trigger_verdicts.py`, and chat inbox/proposal/review/dispatch stores
  audited as reuse surfaces;
- `a2a-sdk` dependency and SDK server/client integration surface selected;
- no dirty historical work is treated as main capability.

### Phase 1: Security And Authority Preflight

Deliver:

- A2A disabled-by-default preserved;
- Chat/MCP/A2A write paths local-only or token-gated;
- read-only Agent Card path separated from task/send write path;
- no free-form text, stdout, SDK task status, or UI projection becomes
  authority.

Validation:

```text
missing token is rejected for write path
valid token accepted for write path
read-only card remains available according to configured policy
```

### Phase 2: Agent Interop Kernel

Deliver:

- agent profile/card read model;
- official `a2a-sdk` dependency and minimal SDK model boundary;
- prompt/context layering;
- provider-native session binding and same-session serialization;
- first canonical handoff task envelope.

Validation:

```text
Chat API can create a durable groupchat where each participant has
identity, capability, provider/session state, and a prompt/context payload.
```

### Phase 3: Natural Handoff And Provider Invocation

Deliver:

- line-start mention or explicit target to durable handoff item;
- outbound A2A SDK provider adapter for remote/provider invocation;
- provider task/artifact normalization;
- writeback reconciliation.

Validation:

```text
real Codex participant reads inbox and produces durable proposal or blocker;
handoff path does not use Ray as default route.
```

### Phase 4: Review, Dispatch, Execution Closure

Deliver:

- structured review verdict remains review authority;
- P1/P2 review findings map to `decision=blocked` with evidence refs;
- non-blocking P3 findings may allow `dispatch_allowed` only with explicit
  non-blocking evidence;
- approval/blocked state has source refs;
- dispatch/execution consumes xmuse authority, not stdout;
- one real xmuse small PR created from the chain;
- CI observed by operator through server-side evidence;
- operator merge or explicit fail-closed blocker.

Minimum success for the long goal:

```text
real natural groupchat chain reaches PR/CI/operator merge,
or reaches a durable blocker that accurately names the next authority boundary.
```

### Phase 5: MemoryOS Sidecar

Deliver if the main chain has advanced enough:

- opt-in ingest of summaries, decisions, blockers, artifact refs;
- recall into context assembler;
- degraded mode when unavailable.

Validation:

```text
contract proof by fake/local adapter;
live proof only if live MemoryOS is available.
```

### Phase 6: Frontend API / UX Contract

Deliver if the main chain has advanced enough:

- read-only endpoints/payloads for timeline, agent cards, worklist, review,
  dispatch, blockers, next action, artifact/source refs;
- card summary plus collapsible detail payloads.

Validation:

```text
frontend can consume the data contract without reading internal stores directly.
```

### Phase 7: Claims And Documentation Sync

Deliver before final report:

- update or explicitly defer updates to `docs/xmuse/release-checklist.md`,
  `docs/xmuse/mainline-contracts.md`, `README.md`, and quickstart/operator
  docs touched by the new A2A SDK path;
- distinguish merged natural/A2A capabilities from still-forbidden production
  claims;
- record whether Ray remains only compatibility/legacy in the actual path;
- record whether MemoryOS is skipped, degraded, contract proof, or live proof.

Validation:

```text
docs do not claim production-ready natural groupchat
docs do not claim live MemoryOS authority
docs do not claim A2A SDK production interop beyond implemented SDK lifecycle
docs do not claim GitHub review truth or autonomous merge
```

## Refactor Rule

Use focused refactor immediately when it is simpler than another patch.

Refactor triggers:

- the same complex boundary fails twice;
- a fix would add a compatibility branch;
- routing, callback, scheduler, and provider paths duplicate state;
- Ray compatibility becomes the reason the main chain cannot progress;
- prompt or context construction is scattered across modules;
- writeback reconciliation is split across several ad hoc paths.

Every refactor must declare:

```text
old path replaced
new producer
new consumer
unchanged authority
proof command or runtime replay
```

Do not use a broad rewrite when a smaller boundary refactor would remove the
complexity.

## GitHub And CI/CD Policy

Use main-based small PRs.

PR count is dynamic, not fixed, but each PR must have:

```text
authority
producer
consumer
validation
forbidden claims
```

Every PR must pass remote CI before merge. Local tests are local evidence only.
Operator performs final merge; xmuse may produce PRs and structured ready/block
signals, but it must not autonomously merge in this goal.

GitHub/CI observation must use server-side evidence such as GitHub checks and
run metadata. Do not treat copied UI text, local logs, or local tests as
GitHub truth or review truth.

## Stop Conditions

Stop and report when:

- the real chain repeats the same complex failure after a focused refactor;
- MemoryOS or frontend API work starts displacing the natural groupchat chain;
- a change requires provider stdout as proof;
- Ray must be patched again to stay on the main route;
- a PR expands into an umbrella PR;
- proof boundaries would need to be weakened.

## Forbidden Claims

Do not claim:

```text
production-ready natural groupchat
live MemoryOS authority
fully autonomous merge
GitHub review truth
provider stdout review truth
full multi-provider parity
front-end complete
Ray-backed production proof
```

## Final Report Requirements

The final goal report must include:

- maximum real chain reached;
- the xmuse small demand attempted or completed;
- PR/CI/merge state;
- A2A provider/interop progress by phase;
- MemoryOS state: skipped, degraded, contract proof, or live proof;
- frontend API contract changes, if any;
- whether Ray was used in the main path;
- durable blockers and next authority boundary;
- exact forbidden claims not made.
