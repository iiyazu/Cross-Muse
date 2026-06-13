# Vision GOD Room Runtime Closure Plan

> **For agentic workers:** This is the next long `/goal` handoff after the
> initial GOD room contract/store slices. Use stage manifests, TDD, focused
> validation, proof discipline, and independent Codex review. This plan is not
> evidence that the xmuse vision is already closed.

**Goal:** Turn the current evidence/control-ready branch into a production
slice of the real GOD room runtime: natural multi-GOD events, speaker
selection, challenge/handoff/freeze semantics, typed blueprint freeze, laneDAG
runtime budgets, MemoryOS trace anchors, TUI operator cockpit, and replayable
evidence.

**Architecture:** Keep the two-phase product model. GODs deliberate in a
durable room and emit auditable events until a typed blueprint is frozen. After
freeze, centralized feature/lane execution proceeds through contracts, review
gates, MemoryOS governance, GitHub truth, and release evidence packs. Durable
authority remains in stores/contracts/server truth; TUI/dashboard surfaces are
operator projections and control surfaces only.

**Tech Stack:** Python, FastAPI, Textual, xmuse_core contracts, chat stores,
provider/GOD registry, goal-stage harness, MemoryOS Lite REST compatibility,
GitHub CLI/API truth capture, pytest, ruff, uv, optional bounded OpenCode
worker delegation.

---

Updated: 2026-06-13

Source reports:

```text
C:\Users\iiyatu\Downloads\deep-research-report_11.md
/mnt/c/Users/iiyatu/Downloads/deep-research-report_11.md
C:\Users\iiyatu\Downloads\mession_01.md
/mnt/c/Users/iiyatu/Downloads/mession_01.md
```

Short `/goal` prompt:

```text
docs/xmuse/vision-god-room-runtime-closure-goal-prompt.md
```

## Starting Facts

The source reports converge on the same conclusion: the current branch has a
strong evidence/control closure, but xmuse cannot honestly claim vision
closure, mainline merge closure, or natural peer-GOD runtime closure yet.

Verified planning facts for this update, checked on 2026-06-13:

- Branch: `vision-closure-deliberation-tui`.
- Local and remote head:
  `45a3d920e268c02c2309c5ffa56f11bb78c211b2`.
- Latest local commit: `45a3d92 Add durable GOD room event store`.
- PR #43 remains draft/open/unmerged.
- GitHub PR merge state was `CLEAN`; review decision was empty.
- GitHub Actions run `27465828379` succeeded for that head with
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`.
- No `pr_merged` event may be emitted until server-side merge proof exists.
- Since the source reports, the branch has added durable GOD room event
  contracts, deterministic replay, blueprint freeze compilation, lane runtime
  contracts, lane recovery decisions, MemoryOS trace anchors, TUI projections,
  a GOD room runtime closure evidence section, and a SQLite-backed GOD room
  event store. These are production contract/store slices, not live peer-GOD
  provider proof.

The next `/goal` runner must re-check every current fact in S0. This document
is a task plan, not a durable truth source.

## Product Direction

Do not add another broad dashboard or demo fixture. The next wave should make
the gods layer real enough that every later production claim has a runtime
trace behind it:

```text
fresh truth map
-> durable GOD room event protocol
-> speaker selection / question / challenge / handoff / freeze
-> typed BlueprintFreezeArtifact
-> feature and laneDAG contracts with budgets and suspend reasons
-> MemoryOS trace anchors for god/lane/review memory
-> TUI operator cockpit for room, blueprint, laneDAG, queue, trace, replay
-> evidence pack / GitHub truth / review boundary
```

Because several contract slices now exist, the next run must not spend its
budget re-creating them as parallel implementations. It should promote the
existing contracts into the runtime path:

1. GOD room mutations go through Chat API/MCP/platform operator contracts and
   persist to the durable room event store.
2. Speaker runtime attempts real configured provider/GOD bindings when
   available and records `manual_gap` when they are not.
3. Blueprint freeze consumes durable room snapshots and emits immutable typed
   artifacts that can feed graph-set/laneDAG authority.
4. Lane budget/recovery decisions are enforced by supervisor/orchestrator
   paths, not only tested as pure evaluators.
5. MemoryOS trace anchors become REST-first write/context plans with live proof
   only when a configured service responds.
6. TUI becomes an operator cockpit by invoking contracts; it must not write
   internal state or treat projections as authority.

The reports' useful external pressure is operational:

- peer identity matters, but identity without durable event evidence is only a
  label;
- natural group chat can still use a manager/speaker-selector model, but the
  selector must be replayable;
- blueprint freeze is the boundary between social deliberation and centralized
  execution;
- every lane needs budget, lease, checkpoint, review, rollback, and memory
  anchors;
- operator-visible autonomy requires TUI controls and replay, not just logs;
- long `/goal` autonomy needs strict permissions, review triggers, retry
  budgets, and evidence-backed progress reports.

## Direct Refactor Rule

Repeated failure and demo-grade implementation are production blockers, not
signals to keep adding patches.

Apply this rule during the next `/goal`:

- If the same feature, stage, test cluster, or runtime path fails twice with
  the same failure class, stop local patch stacking and perform root-cause
  analysis.
- If a third retry would be required, or the supervisor/stage harness reports
  `refactor_required`, replace or restructure the failing boundary before any
  further retry.
- If the current path is demo-grade and lies on the production mainline, do not
  wrap it with compatibility glue to make a gate green. Isolate or archive the
  demo path, then build the contract-backed production path.
- A refactor must have a bounded owner, allowed files, migration notes, tests,
  and rollback/compatibility behavior. Broad rewrites without a contract are
  not acceptable.
- OpenCode may help with mechanical substeps after Codex writes the refactor
  boundary and gates, but OpenCode may not decide the architecture or accept
  its own patch.

## Non-Goals

- Do not claim xmuse vision closure, mainline merge closure, or peer-GOD
  graduation from this plan alone.
- Do not rebuild a browser frontend.
- Do not make TUI/dashboard/read models authoritative.
- Do not make `feature_lanes.json`, Ray actor memory, provider subprocess
  memory, or old runtime artifacts durable authority.
- Do not bypass Chat API/MCP/platform operator-action contracts for mutation.
- Do not weaken GitHub truth. `pr_merged` still requires server-side merge
  proof.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, `xmuse/logs/`, or
  `.goal-runs/`.
- Do not create `xmuse/__init__.py`.

## Stage Budget

Treat this as an 8-10 hour production-grade run. If full closure does not fit,
land the strongest validated production slice in priority order: GOD room
events, blueprint freeze compiler, lane budget/suspend contracts, MemoryOS
trace anchors, TUI operator projection, evidence pack.

| Window | Stage | Expected output |
| --- | --- | --- |
| 0:00-0:30 | S0 Baseline Truth | Current branch/head/PR/CI/env/proof map, no edits. |
| 0:30-1:30 | S1 GOD Room Control Surface | Chat API/MCP/operator actions write durable room events through contracts. |
| 1:30-2:30 | S2 Speaker Runtime Integration | Provider-bound speaker attempts, deterministic fallback, and honest proof labels. |
| 2:30-3:45 | S3 Freeze-To-LaneDAG Authority | Durable room snapshot -> freeze artifact -> graph-set/laneDAG authority. |
| 3:45-5:00 | S4 Lane Runtime Enforcement | Owner, budget, lease, checks, rollback, memory anchors enforced in runtime paths. |
| 5:00-6:00 | S5 Recovery And Refactor Policy | Retry/suspend/refactor-required decisions enforced by stage/supervisor paths. |
| 6:00-7:00 | S6 MemoryOS Live Trace Plans | Multi-GOD context/write plans and opt-in live MemoryOS trace proof. |
| 7:00-8:00 | S7 TUI Operator Actuation | Room, blueprint, laneDAG, review queue, trace, replay/readiness controls. |
| 8:00-10:00 | S8 Evidence, Soak, Docs, PR | Fresh replay bundle, review/GitHub truth, focused tests, docs, PR update. |

## S0 - Baseline Truth

Goal: reconcile the research reports and previous closure evidence with
current repository and server truth.

Tasks:

- Read `AGENTS.md`, `docs/xmuse/README.md`,
  `docs/xmuse/mainline-contracts.md`,
  `docs/xmuse/development-goal-worker-delegation-policy.md`,
  `docs/xmuse/goal-stage-harness.md`,
  `docs/xmuse/vision-overnight-autonomy-closure-plan.md`, this plan, the
  short prompt, and the two source reports.
- Run `git status --short --branch`; preserve unrelated changes.
- Confirm `xmuse/__init__.py` is absent.
- Re-check PR #43 metadata and latest GitHub Actions for current head.
- Inventory configured resources by probe/key presence only: GitHub auth,
  Codex, OpenCode/DeepSeek, Ray, MemoryOS Lite, MCP/Chat API ports, TUI
  operator token bundle.
- Record stale, current, live, server-side, contract-only, and `manual_gap`
  facts.

Acceptance:

- No behavior changes are made in S0.
- PR/CI/merge facts use current server data, not report text.
- Missing configured resources have owner and next action.

## S1 - GOD Room Event Contract

Goal: put the production event vocabulary on the runtime control path.

Tasks:

- Inspect current chat, participant, transcript, GOD CLI registration,
  provider binding, and natural deliberation contracts.
- Add or extend contracts only where there is no production path for:
  `speak`, `question`, `challenge`, `handoff`, and `freeze_requested`.
- Every event must carry room/conversation id, participant/god identity,
  provider or CLI source when available, source refs, timestamp, causality
  reference, and redaction-safe content.
- The event contract must distinguish natural speech, operator action,
  system/supervisor action, and derived projection.

Acceptance:

- Deterministic tests validate event serialization, causality, and rejection
  of missing identity/source refs.
- The contract does not make TUI or `feature_lanes.json` an authority.

Next-round advancement:

- Wire `GodRoomEventStore` into Chat API, MCP, or platform operator-action
  surfaces for room creation, event append, replay, and snapshot export.
- TUI controls may call those surfaces, but must not write the room store
  directly.
- Event append must be idempotent and must reject mismatched conversation,
  unknown participant, unknown target, missing source refs, and conflicting
  event identity before any projection is updated.

Current implementation status:

- `src/xmuse_core/chat/god_room_runtime.py` now defines
  `xmuse.god_room_event.v1` for durable room events. The event vocabulary covers
  `speak`, `question`, `challenge`, `handoff`, and `freeze_requested`.
- Each event carries room/conversation identity, participant/GOD identity,
  actor kind, timestamp, content, target participants, causal parent,
  source refs, optional CLI/provider profile, and payload. Missing identity,
  empty content, missing source refs, invalid challenge routing, and incomplete
  freeze requests are rejected by the contract.
- `src/xmuse_core/chat/god_room_event_store.py` now provides a durable
  SQLite-backed GOD room event store. Rooms bind to a conversation, participants
  are explicit roster authority, event append is idempotent, conflicting event
  identity reuse is rejected, unknown participants/targets are blocked, and
  room state can be reloaded after restart.
- `xmuse/chat_api.py` now exposes a contract-backed GOD room control surface:
  `POST/GET /api/chat/conversations/{conversation_id}/god-room`,
  `POST /api/chat/conversations/{conversation_id}/god-room/events`, and
  `GET /api/chat/conversations/{conversation_id}/god-room/snapshot`.
  The API builds room rosters from active non-init chat participants, writes
  through `GodRoomEventStore`, returns replay/snapshot payloads, and maps
  membership/conflict failures to HTTP errors without updating projections.
- Auth-enabled Chat API deployments require explicit `chat_god_room`
  capability for mutating GOD room routes; generic `chat_write` is not enough.
- This is durable contract/store infrastructure, not live peer-provider proof.
  It does not make TUI, dashboard, `feature_lanes.json`, Ray actor memory, or
  provider subprocess state authoritative.

## S2 - Speaker Runtime Slice

Goal: make GOD room turn-taking replayable and ready for provider-bound runtime
attempts before adding broader autonomy.

Tasks:

- Implement the smallest production speaker selector compatible with the event
  contract. It may be deterministic at first, but it must support future
  provider scoring.
- Support question/challenge/handoff events as first-class routing signals.
- Produce a replayable transcript fixture with at least three GOD
  participants, one challenge, one handoff, and one freeze request.
- Keep provider runtime proof labels honest: fake/local fixtures remain
  `contract_proof`, not `real_provider_proof`.

Acceptance:

- Focused tests replay the room and recover the same next-speaker sequence.
- The runtime can emit a blocked/manual_gap result instead of inventing a
  provider response when a provider is unavailable.

Next-round advancement:

- Connect speaker decisions to the selected GOD/provider registry path without
  hard-coding a provider in business logic.
- When a selected provider is configured, capture a fresh provider-bound speak
  attempt as `real_provider_proof` only if the provider actually responds.
- When no provider is configured, emit `manual_gap` with provider, owner, and
  next action; do not downgrade to fake speech and label it live.

Current implementation status:

- `replay_god_room_turns(...)` replays `GodRoomEventV1` events against an
  explicit roster and emits deterministic next-speaker decisions.
- Routing is causal-parent aware. `challenge`, `question`, and `handoff` route
  to their first target participant; normal `speak` uses round-robin; and
  `freeze_requested` ends the turn sequence for blueprint freeze handling.
- Missing participants or missing target participants produce
  `manual_gap/manual_gap` replay results with a concrete blocked reason instead
  of inventing a provider response.
- `GodRoomEventStore.write_room_snapshot(...)` exports
  `xmuse.god_room_snapshot.v1` with participants, events, and replay decisions,
  so replay/release evidence can reference a durable room snapshot instead of
  ad hoc transcript fixtures.

## S3 - Blueprint Freeze Compiler

Goal: turn natural GOD transcript evidence into a typed, auditable freeze
artifact.

Tasks:

- Inspect existing `MissionBlueprintV1`, blueprint freeze, and release replay
  sections before adding new schema.
- Build a compiler path from GOD room transcript to a freeze artifact that
  includes objective, assumptions, accepted requirements, rejected
  alternatives, conflicts, unresolved blockers, source refs, and freeze
  decision.
- Freeze output must be immutable after freeze; follow-up changes require a
  new revision or patch-forward lineage.

Acceptance:

- Tests cover successful freeze, unresolved-conflict manual gap, and
  rejected-alternative preservation.
- The compiler reads transcript/contract sources and does not write lane
  status directly.

Next-round advancement:

- Expose freeze compilation as a contract-backed runtime action from a durable
  GOD room snapshot.
- Persist or export the freeze artifact through the existing blueprint
  authority path; follow-up changes require a new revision or patch-forward
  lineage.
- Reject freeze when the room has unresolved challenges, missing quorum, missing
  acceptance contracts, or stale source refs.

Current implementation status:

- `src/xmuse_core/structuring/god_room_blueprint_freeze.py` now provides
  `xmuse.god_room_blueprint_freeze.v1`, a typed artifact wrapper around
  `MissionBlueprintV1`.
- `compile_blueprint_freeze_from_god_room_events(...)` compiles
  `GodRoomEventV1` transcripts into a frozen `MissionBlueprintV1` when a valid
  `freeze_requested` event exists and unresolved challenges are absent.
- The artifact preserves assumptions, conflicts, rejected alternatives,
  blockers, source refs, and the freeze decision event id. Unresolved challenge
  events produce `manual_gap` with a concrete blocker instead of freezing a
  blueprint.
- The compiler is pure contract logic. It does not write lane status, mutate
  chat state, call providers, or make replay/read-model artifacts
  authoritative.
- `xmuse/chat_api.py` now exposes
  `POST /api/chat/conversations/{conversation_id}/god-room/freeze-blueprint`.
  The endpoint compiles a durable `GodRoomEventStore` room snapshot into
  `xmuse.god_room_blueprint_freeze.v1`; successful freezes are persisted
  through the existing mission blueprint proposal/resolution/read-model path
  with `approval_mode = god_room_blueprint_freeze`.
- Unresolved challenges, missing freeze events, or invalid transcript-derived
  blueprint fields return `409` with a `manual_gap`/invalid artifact or detail.
  The blocked path does not write a mission blueprint card, TUI projection,
  lane status, or `feature_lanes.json`.
- This runtime action is contract/store proof. It is not live provider proof,
  not MemoryOS live proof, and not GitHub merge truth.

## S4 - Feature/LaneDAG Runtime Contracts

Goal: make the blueprint-to-execution boundary concrete without creating a
second state authority.

Tasks:

- Extend feature owner/laneDAG contracts only from graph-set or frozen
  blueprint authority.
- Each lane must include owner, inputs, outputs, dependency refs, required
  checks, allowed files, rollback constraints, review profile, memory anchors,
  and budget.
- Keep `feature_lanes.json` as projection/queue only.

Acceptance:

- Contract tests prove laneDAG output can be reconstructed from authoritative
  graph/blueprint inputs.
- No LangGraph node, TUI action, or Ray actor writes lane status directly.

Next-round advancement:

- Feed frozen GOD room blueprint artifacts into graph-set/laneDAG planning
  without using read-model projections as inputs.
- Ensure lane runtime contracts are carried into dispatch/review evidence, not
  only generated as detached artifacts.
- Missing owner, budget, rollback, memory anchors, or review profile must block
  dispatch with an actionable gap.

Current implementation status:

- `src/xmuse_core/structuring/blueprint_execution/lane_dag_service.py` now
  attaches typed `LaneRuntimeContract` records to `BlueprintLaneDagPlan`.
- Each runtime contract carries lane/feature identity, owner, inputs, outputs,
  dependency refs, required checks, allowed files, rollback constraints, review
  profile, MemoryOS refs, budget, and source refs derived from frozen blueprint
  and lane spec inputs.
- The lane graph remains graph structure; `feature_lanes.json`, TUI/dashboard,
  Ray actors, and LangGraph nodes are still not state authorities.

## S5 - Lane Budget And Recovery

Goal: prevent long-run loops from repeatedly patching the same failed design.

Tasks:

- Add or advance lane/stage budget records for time, retry count, failure
  class, suspend reason, and refactor-required reason.
- Integrate goal-stage repeated failures with supervisor evidence so repeated
  failure becomes `refactor_required`, not silent retry.
- Add review triggers for: same failure twice, CI failure twice, core contract
  changes, security/merge semantics changes, and broad file churn.

Acceptance:

- Tests cover retry, suspend, manual_gap, and refactor-required transitions.
- A fourth same-path retry is impossible without a refactor artifact.

Next-round advancement:

- Wire `evaluate_lane_recovery(...)` or an equivalent contract into
  goal-stage import, overnight supervisor, and execution/review paths.
- Two same-class failures on the same feature/stage/test cluster/runtime path
  must stop local patch stacking and create a bounded refactor action.
- A third attempt is allowed only after a refactor/replacement artifact defines
  failed boundary, replacement boundary, migration behavior, focused tests, and
  rollback/compatibility plan.

Current implementation status:

- `LaneRuntimeBudget`, `LaneFailureEvidence`, `LaneRecoveryDecision`, and
  `evaluate_lane_recovery(...)` provide a pure recovery decision contract.
- Missing failure evidence returns `manual_gap`; retry budget exhaustion returns
  `suspended`; repeated same-class failure returns `refactor_required` with
  `retry_allowed=false` and a concrete refactor next action.
- This is contract/evaluator infrastructure only. It does not yet wire recovery
  decisions into every runner or operator action path.

## S6 - MemoryOS Trace Anchors

Goal: make MemoryOS a traceable multi-GOD memory substrate, not a black-box
recall helper.

Tasks:

- Extend or document namespaces for god-private, task, shared, blueprint,
  review, and operator memory.
- Link room events, blueprint freeze, lane evidence, review outcome, and
  release pack refs to MemoryOS trace ids where live service is configured.
- Preserve REST-first behavior and redaction/tombstone policy.

Acceptance:

- Contract/fake tests prove MemoryOS write plans carry source refs and correct
  governance decisions.
- Live MemoryOS proof remains `manual_gap` when no service/config is present.

Next-round advancement:

- Build multi-GOD MemoryOS write/context plans from room events, freeze
  artifacts, lane runtime contracts, and review results.
- Keep namespace, redaction, tombstone, and REST-first governance explicit in
  every write plan.
- Attempt live MemoryOS Lite trace capture only when configured; otherwise keep
  `manual_gap` evidence instead of claiming live service proof.

Current implementation status:

- `src/xmuse_core/integrations/memoryos_namespace.py` now names explicit
  `god_private`, `blueprint`, `review`, and `operator` namespaces in addition
  to existing repo/workspace/conversation/participant/shared/task namespaces.
- `MemoryOSTraceAnchor` links a namespace, trace id, source refs, proof level,
  and metadata. Trace anchors require source refs and expose deterministic
  `memory://.../traces/<trace_id>` URIs.
- Governance write-plan tests cover using review trace anchors as durable
  source refs. This is contract proof; no live MemoryOS service proof is
  claimed by this stage.

## S7 - TUI Operator Cockpit

Goal: expose the production loop to an operator without making the TUI
authoritative.

Tasks:

- Advance read models/widgets for GOD room events, blueprint freeze state,
  laneDAG budget/suspend state, review queue, MemoryOS trace refs, replay
  bundle, and release readiness.
- Mutations must route through existing Chat API/MCP/platform operator action
  contracts.
- Surface proof labels and gap reasons clearly.

Acceptance:

- Widget/read-model tests prove the TUI renders the new projections from
  envelopes/contracts.
- No TUI code directly writes internal state.

Next-round advancement:

- Add or advance operator controls for room event append/import, freeze
  compile, lane budget/recovery inspection, MemoryOS trace drill-down, replay
  export, and release readiness refresh.
- Every mutating control must route through Chat API, MCP, or platform
  operator-action contracts and return proof level, source authority, artifact
  refs, and gap reason.
- Rendering successful controls is not evidence of live provider, live
  MemoryOS, GitHub enforcement, or merge truth.

Current implementation status:

- `src/xmuse_core/platform/tui_vision_read_model.py` now projects lane runtime
  contracts, lane recovery decisions, and MemoryOS trace anchors from read-only
  envelopes into the vision read model.
- `xmuse/tui/widgets/execution_cockpit.py` renders lane contract owner/checks
  and recovery decisions. `xmuse/tui/widgets/memory_trace_drawer.py` renders
  MemoryOS trace anchors.
- This remains a projection/control-surface slice. TUI code does not write
  lane status, MemoryOS truth, `feature_lanes.json`, or runner state.

## S8 - Evidence, Soak, Validation, Docs, PR

Goal: finish with reproducible evidence and an honest handoff.

Tasks:

- Build or update an overnight replay bundle that includes room transcript,
  blueprint freeze, laneDAG, supervisor, MemoryOS governance/trace, review
  truth, GitHub truth, and release readiness.
- Attempt configured live gates. Missing config becomes `manual_gap`; failing
  configured live gates are blockers.
- Run focused tests for every changed surface, then the standard quality
  checks.
- Update docs/walkthrough/PR body with current facts. Do not auto-merge.

Acceptance:

- Evidence pack distinguishes `ready_for_replay` from `pr_merged`.
- Final report lists stages completed/blocked, files changed, validation
  results, live/server proof, remaining blockers, and PR #43 state.

Next-round advancement:

- Rebuild the GOD room closure evidence from fresh artifacts created in this
  run, not stale samples.
- Re-capture GitHub PR/check/review/merge truth for the current head before
  updating PR #43.
- If OpenCode is delegated any bounded worker task, Codex must independently
  audit the diff, runtime state, package boundary, tests, and proof claims
  before accepting it.

Current implementation status:

- `src/xmuse_core/platform/god_room_runtime_closure_evidence_capture.py` now
  writes a `god_room_runtime_closure` production evidence envelope for S8. It
  indexes GOD room participants/events, replay decisions, blueprint freeze,
  laneDAG runtime contracts/recovery decisions, MemoryOS trace anchors, TUI
  projection, GitHub truth, and release readiness.
- `capture_release_evidence_pack(...)` can generate that evidence from
  explicit GOD room closure inputs after release readiness is captured and
  before the overnight replay bundle is written. The CLI exposes matching
  `--god-room-*` inputs.
- `capture_overnight_replay_bundle(...)` accepts `god_room_runtime_closure` as
  an optional replay section while leaving required replay sections unchanged.
- Missing GitHub truth, release readiness, live MemoryOS, or other configured
  inputs stay `manual_gap`/blocker evidence. The closure section does not emit
  `pr_merged`, does not upgrade OpenCode to peer-GOD proof, and does not make
  TUI/read models durable authority.

## Required Validation

Use `uv run`, never bare `pytest` or `ruff`.

Minimum final validation:

```bash
uv run pytest <focused tests for changed surfaces> -q
uv run ruff check .
git diff --check
uv run pytest tests/xmuse/test_package_boundaries.py -q
test ! -e xmuse/__init__.py
```

If OpenCode is used, first verify the configured DeepSeek path with:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Recommended pre-goal smoke:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max \
  "Return exactly xmuse-opencode-smoke-ok"
```

Do not use `deepseek-v4-flash:max`,
`opencode-go/deepseek-v4-flash:max`, `deepseek-v4-flash-max`, or
`opencode-go/deepseek-v4-flash-max`.
