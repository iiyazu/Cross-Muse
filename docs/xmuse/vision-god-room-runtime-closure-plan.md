# Vision GOD Room Runtime Closure Plan

> **For agentic workers:** This is the next long `/goal` handoff after the
> overnight autonomy closure wave. Use stage manifests, TDD, focused
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

Known planning facts from the previous validated run:

- Branch: `vision-closure-deliberation-tui`.
- Latest validated head before this planning document:
  `940bf9179cff282c8f72db7cdfde702d68199157`.
- PR #43 remains draft/open/unmerged.
- GitHub Actions run `27462667689` succeeded for that head with
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`.
- The local release evidence pack was rebuilt as `decision=ready` and
  `overnight_replay_decision=ready_for_replay`, but this is not merge truth.
- Raw GitHub truth still had `merged=false`, `draft=true`, and
  `can_emit_pr_merged=false`.
- No `pr_merged` event may be emitted until server-side merge proof exists.

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
| 0:30-1:30 | S1 GOD Room Event Contract | Durable event model for speak/question/challenge/handoff/freeze. |
| 1:30-2:30 | S2 Speaker Runtime Slice | Deterministic room runtime and speaker selector fixture/replay. |
| 2:30-3:45 | S3 Blueprint Freeze Compiler | Typed freeze artifact with assumptions, conflicts, rejected alternatives, blockers. |
| 3:45-5:00 | S4 Feature/LaneDAG Runtime Contracts | Feature/lane output with owner, budget, lease, checks, rollback, memory anchors. |
| 5:00-6:00 | S5 Lane Budget And Recovery | Suspend/retry/backoff/refactor-required policy through durable evidence. |
| 6:00-7:00 | S6 MemoryOS Trace Anchors | God-private, task, shared, blueprint, review, and operator memory refs. |
| 7:00-8:00 | S7 TUI Operator Cockpit | Room, blueprint, laneDAG, review queue, trace, replay/readiness projections. |
| 8:00-10:00 | S8 Evidence, Soak, Docs, PR | Replay bundle, review/GitHub truth, focused tests, docs, PR update. |

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

Goal: define the production event vocabulary for natural GOD collaboration.

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

Current implementation status:

- `src/xmuse_core/chat/god_room_runtime.py` now defines
  `xmuse.god_room_event.v1` for durable room events. The event vocabulary covers
  `speak`, `question`, `challenge`, `handoff`, and `freeze_requested`.
- Each event carries room/conversation identity, participant/GOD identity,
  actor kind, timestamp, content, target participants, causal parent,
  source refs, optional CLI/provider profile, and payload. Missing identity,
  empty content, missing source refs, invalid challenge routing, and incomplete
  freeze requests are rejected by the contract.
- This is contract/replay infrastructure only. It does not make TUI,
  dashboard, `feature_lanes.json`, Ray actor memory, or provider subprocess
  state authoritative.

## S2 - Speaker Runtime Slice

Goal: make GOD room turn-taking replayable before adding broader autonomy.

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

Current implementation status:

- `replay_god_room_turns(...)` replays `GodRoomEventV1` events against an
  explicit roster and emits deterministic next-speaker decisions.
- Routing is causal-parent aware. `challenge`, `question`, and `handoff` route
  to their first target participant; normal `speak` uses round-robin; and
  `freeze_requested` ends the turn sequence for blueprint freeze handling.
- Missing participants or missing target participants produce
  `manual_gap/manual_gap` replay results with a concrete blocked reason instead
  of inventing a provider response.

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

Do not use `deepseek-v4-flash:max`,
`opencode-go/deepseek-v4-flash:max`, `deepseek-v4-flash-max`, or
`opencode-go/deepseek-v4-flash-max`.
