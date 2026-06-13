# xmuse Production Closure Gap Ledger

更新日期: 2026-06-13

本文档是 xmuse 生产闭环缺口台账。它用于从用户视角一层一层讨论:

```text
用户入口
-> GOD room
-> speaker runtime
-> blueprint freeze
-> laneDAG
-> execution/review
-> MemoryOS
-> release evidence
-> GitHub truth
-> overnight autonomy
```

本文档不是完成证明，也不是 merge truth。每一层都必须区分:

- 已有实现证据；
- 仍缺的生产闭环；
- 要关闭该层必须拿到的 proof；
- 下一步最小生产切片；
- 目前不能声称的能力。

## Current Truth Snapshot

当前事实，需在每轮长 `/goal` 开始时重新确认:

- Branch: `vision-closure-deliberation-tui`
- Head: `1a244285c6e9b287f9c32acb640b0bc68087d90b`
- PR: <https://github.com/iiyazu/Cross-Muse/pull/43>
- PR state: draft/open/unmerged
- PR merge state: `CLEAN`
- PR review decision: empty
- Latest GitHub Actions for current head: `27470910514`, success
- Local worktree at document creation: clean

Evidence boundaries:

- No `pr_merged` claim is valid until GitHub server-side merge proof exists.
- OpenCode remains a bounded worker unless a later contract and live proof
  explicitly upgrade it.
- TUI/dashboard/read models are operator surfaces and projections, not durable
  state authority.
- `feature_lanes.json`, Ray actor memory, LangGraph nodes, provider subprocess
  state, and runtime artifacts are not authoritative lane status.
- MemoryOS evidence is governed plan/artifact proof unless a configured live
  MemoryOS service trace is captured.
- Speaker response capture is real-provider evidence only when backed by a
  server-loaded provider response artifact and a durable GOD room `speak` event
  present in room replay evidence.

## Layer Map

| Layer | Name | Closure state |
|---|---|---|
| L1 | User Entry / Operator Cockpit | Partial production slice |
| L2 | GOD Room Durable Event Runtime | Durable contract/store slice exists |
| L3 | Speaker Selection / Provider Response | Replay and artifact-backed capture exist; provider invocation missing |
| L4 | Blueprint Freeze Authority | Typed freeze slice exists |
| L5 | Feature / LaneDAG Authority | Contract artifact slice exists |
| L6 | Lane Runtime Enforcement / Recovery | Recovery contract/API slice exists; full runner enforcement incomplete |
| L7 | Execution / Review / Patch-Forward | Review plane exists; full GOD-room-to-review runtime proof incomplete |
| L8 | MemoryOS Live Trace | Governed plan exists; live trace proof missing |
| L9 | Release Evidence / Replay Bundle | Strong evidence pack slice exists |
| L10 | GitHub Review / Merge Truth | CI truth exists; review/merge truth missing |
| L11 | Overnight Autonomy / Soak | Harness/policies exist; live soak incomplete |

## L1 - User Entry / Operator Cockpit

- User-visible promise:
  - The operator can supervise and actuate the autonomous development loop from
    TUI/API surfaces without inspecting raw logs for every step.
- Current implemented evidence:
  - TUI exposes GOD room actions including room ensure/event append/freeze,
    laneDAG, recovery, MemoryOS plan, speaker attempt, speaker response, and
    release pack aliases.
  - TUI actions route through Chat API/operator contracts.
- Missing production closure:
  - The cockpit is not yet a complete live operations console for provider
    invocation, review queue decisions, live MemoryOS trace, and overnight
    continuation/stop decisions.
- Proof required to close:
  - Operator can run a complete live session through room discussion,
    provider-backed speech, freeze, laneDAG, execution/review, evidence pack,
    and stop/continue decision without bypassing contracts.
- Current risk:
  - Expanding panels can create false confidence if live/provider/server proof
    is not clearly separated from projection proof.
- Next production slice:
  - Add operator controls and evidence for provider response artifact creation,
    not only response capture.
- Do not claim yet:
  - Do not claim TUI is a complete autonomous operations cockpit.

## L2 - GOD Room Durable Event Runtime

- User-visible promise:
  - GOD discussion is not just chat text; it is a durable, replayable sequence
    of speech acts.
- Current implemented evidence:
  - `xmuse.god_room_event.v1` covers `speak`, `question`, `challenge`,
    `handoff`, and `freeze_requested`.
  - `GodRoomEventStore` persists rooms/events and supports replay/snapshot
    export.
  - Chat API exposes room creation, event append, and snapshot routes.
- Missing production closure:
  - Natural multi-GOD live runtime has not been proven over a long session.
- Proof required to close:
  - A fresh transcript where multiple configured GODs produce durable
    question/challenge/handoff/freeze events through provider-backed runtime.
- Current risk:
  - Contract proof can be mistaken for natural peer-GOD runtime proof.
- Next production slice:
  - Drive real provider-backed room speech through the durable event store.
- Do not claim yet:
  - Do not claim natural peer-GOD groupchat closure.

## L3 - Speaker Selection / Provider Response

- User-visible promise:
  - xmuse can decide who should speak next, ask the configured provider/GOD to
    respond, and persist the result as durable room speech.
- Current implemented evidence:
  - Speaker replay decisions are deterministic and recoverable.
  - Speaker attempt evidence joins room replay to selected GOD runtime
    continuity.
  - Speaker response capture appends a durable `speak` event only when backed
    by a server-loaded provider response artifact.
- Missing production closure:
  - The provider response artifact is not yet produced by a production provider
    invocation path in this GOD room flow.
- Proof required to close:
  - A provider invocation contract that creates
    `xmuse.god_room_provider_speech_response.v1` from a real configured
    provider session, then passes it into speaker response capture.
- Current risk:
  - Treating an imported artifact as equivalent to the live invocation that
    produced it.
- Next production slice:
  - Build the provider invocation/action that emits the provider response
    artifact, with manual_gap when provider config is missing.
- Do not claim yet:
  - Do not claim the GOD room can autonomously generate live provider speech
    end to end.

## L4 - Blueprint Freeze Authority

- User-visible promise:
  - Discussion becomes executable only through a frozen, typed blueprint.
- Current implemented evidence:
  - GOD room events can compile into `xmuse.god_room_blueprint_freeze.v1`.
  - The freeze endpoint persists through the existing mission blueprint
    proposal/resolution path.
- Missing production closure:
  - The freeze path has not yet been proven from a fresh live multi-GOD
    transcript with real challenges and objections.
- Proof required to close:
  - A live transcript produces a freeze artifact preserving assumptions,
    blockers, rejected alternatives, source refs, and decision event lineage.
- Current risk:
  - Freezing a clean contract fixture can be mistaken for real deliberation
    closure.
- Next production slice:
  - Require live transcript source evidence for production freeze claims.
- Do not claim yet:
  - Do not claim blueprint freeze is backed by natural peer-GOD deliberation.

## L5 - Feature / LaneDAG Authority

- User-visible promise:
  - A frozen blueprint becomes feature/lane/laneDAG execution authority, not an
    ad hoc task list.
- Current implemented evidence:
  - LaneDAG artifacts include lane runtime contracts with owner, checks,
    rollback, memory refs, and budget.
  - Chat API can build laneDAG from GOD-room freeze resolution without writing
    `feature_lanes.json`.
- Missing production closure:
  - The graph-set/lane authority path is not yet fully unified with every
    execution/dispatch path.
- Proof required to close:
  - A frozen GOD room blueprint feeds authoritative laneDAG/graph-set state used
    by dispatch and review.
- Current risk:
  - Detached laneDAG artifacts may be treated as execution authority before
    dispatch/review actually consumes them.
- Next production slice:
  - Wire lane runtime contracts into dispatch/review evidence.
- Do not claim yet:
  - Do not claim full blueprint-to-execution authority closure.

## L6 - Lane Runtime Enforcement / Recovery

- User-visible promise:
  - Lanes cannot silently loop; repeated failure triggers suspend or bounded
    refactor.
- Current implemented evidence:
  - Lane recovery contracts classify retry, suspend, manual_gap, and
    refactor_required.
  - Goal-stage and development policy now require direct refactor for repeated
    failure/demo-grade production paths.
- Missing production closure:
  - Recovery is not yet enforced through every supervisor, runner, dispatch,
    and review path.
- Proof required to close:
  - A real lane failure sequence enters recovery/refactor_required and blocks
    further same-path retries until a refactor artifact exists.
- Current risk:
  - Recovery remains advisory if runners can bypass it.
- Next production slice:
  - Enforce recovery decisions in runner/supervisor control flow.
- Do not claim yet:
  - Do not claim overnight-safe lane runtime recovery.

## L7 - Execution / Review / Patch-Forward

- User-visible promise:
  - Work is executed by bounded workers, reviewed with evidence, and failed
    lanes create auditable patch-forward lineage.
- Current implemented evidence:
  - Review plane, evidence bundles, final action gates, and patch-forward
    contracts exist.
  - OpenCode delegation policy treats worker output as candidate evidence only.
- Missing production closure:
  - A GOD-room-originated lane has not yet been proven through live execution,
    review, patch-forward, and release evidence in one chain.
- Proof required to close:
  - A lane from GOD room freeze is executed, reviewed, accepted/reworked, and
    linked into release evidence with lineage.
- Current risk:
  - Worker self-report or local test results can be mistaken for review truth.
- Next production slice:
  - Connect GOD room lane contracts to review evidence ingestion.
- Do not claim yet:
  - Do not claim end-to-end execution/review closure from GOD room input.

## L8 - MemoryOS Live Trace

- User-visible promise:
  - GODs, blueprints, lanes, reviews, and operator decisions leave traceable
    long-term memory.
- Current implemented evidence:
  - MemoryOS namespaces and trace anchors exist.
  - GOD room MemoryOS plan artifacts build governed write/context plans without
    importing `memoryos_lite`.
- Missing production closure:
  - No current live MemoryOS Lite trace proof is established for this branch
    head.
- Proof required to close:
  - Configured MemoryOS Lite service accepts writes/context requests and returns
    trace ids mapped to GOD/lane/review artifacts.
- Current risk:
  - Governance plan proof can be overread as live memory proof.
- Next production slice:
  - Add opt-in live MemoryOS trace capture for GOD room closure artifacts.
- Do not claim yet:
  - Do not claim live MemoryOS memory closure.

## L9 - Release Evidence / Replay Bundle

- User-visible promise:
  - The operator can replay what happened and see exactly why the system is
    ready, blocked, or manual_gap.
- Current implemented evidence:
  - Release evidence pack indexes GOD room closure inputs, speaker attempt,
    artifact-backed speaker response, laneDAG, MemoryOS plan, TUI projection,
    GitHub truth, and readiness.
  - Speaker response evidence is cross-checked against room events before being
    treated as appended speech.
- Missing production closure:
  - The pack still depends on missing live provider invocation, live MemoryOS,
    review truth, and merge truth for full production closure.
- Proof required to close:
  - A fresh replay bundle contains real provider speech, freeze, laneDAG,
    execution/review, MemoryOS trace, GitHub review/check/merge truth or honest
    blockers.
- Current risk:
  - `ready_for_replay` may be confused with `ready_to_merge` or `pr_merged`.
- Next production slice:
  - Produce a fresh replay bundle from a live GOD room provider invocation run.
- Do not claim yet:
  - Do not claim release/mainline closure from local replay readiness alone.

## L10 - GitHub Review / Merge Truth

- User-visible promise:
  - GitHub is the server-side control plane for review/check/merge truth.
- Current implemented evidence:
  - PR #43 latest CI passed for head
    `1a244285c6e9b287f9c32acb640b0bc68087d90b`.
  - PR merge state is currently `CLEAN`.
- Missing production closure:
  - PR #43 is still draft/open/unmerged and has no review decision.
- Proof required to close:
  - Required review/check/merge server-side truth, including merge proof before
    any `pr_merged` event.
- Current risk:
  - CI success can be overread as review or merge truth.
- Next production slice:
  - Capture fresh GitHub review/merge truth after review readiness changes.
- Do not claim yet:
  - Do not claim merge closure or `pr_merged`.

## L11 - Overnight Autonomy / Soak

- User-visible promise:
  - xmuse can run for hours, recover from failures, preserve evidence, and stop
    safely when blocked.
- Current implemented evidence:
  - Goal-stage harness, worker delegation policy, RIGR-V, anti-TDD-abuse rules,
    and repeated-failure refactor policy are documented.
  - Evidence/control surfaces exist for many stages.
- Missing production closure:
  - No 8-10 hour live GOD room runtime soak has proven natural discussion,
    provider speech, freeze, lane execution, review, MemoryOS trace, and
    GitHub truth together.
- Proof required to close:
  - A live overnight run with budget ledger, recovery decisions, replay bundle,
    review evidence, and honest blockers.
- Current risk:
  - Long `/goal` progress reports can become optimistic if not tied to replay
    artifacts and server truth.
- Next production slice:
  - Run a bounded soak after provider invocation and recovery enforcement are
    in place.
- Do not claim yet:
  - Do not claim overnight autonomous production readiness.

## Maintenance Rules

- Update this ledger after every production-slice commit that changes a layer.
- Keep claims tied to current branch/head/PR/CI facts.
- If a layer is only contract proof, say so explicitly.
- If a live/server proof is missing, record `manual_gap` and the next artifact
  required to close it.
- Do not downgrade evidence boundaries to make a layer look complete.
- Prefer direct refactor over repeated patch stacking for demo-grade or
  repeatedly failing production paths.
