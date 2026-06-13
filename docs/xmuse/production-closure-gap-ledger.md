# xmuse Production Closure Gap Ledger

更新日期: 2026-06-14

本文档是 xmuse 生产闭环缺口台账。它用于把“用户最终看到的体验”和
“生产实现必须遵守的依赖顺序”分开记录。

用户最终体验路径可以这样理解:

```text
用户入口
-> operator cockpit / TUI
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

但实现与验收不能按这个展示顺序推进。TUI、dashboard、release pack 和
overnight soak 都是下游投影、控制面或综合证明，不能先于它们依赖的 durable
runtime、provider invocation、lane authority、review truth 完成。后续生产级
实现按本文的 Dependency-First Closure Layers 推进。

本文档不是完成证明，也不是 merge truth。每一层都必须区分:

- 已有实现证据；
- 仍缺的生产闭环；
- 要关闭该层必须拿到的 proof；
- 下一步最小生产切片；
- 下游在该层关闭前不能声称的能力。

## Current Truth Snapshot

当前事实需在每轮长 `/goal` 开始时重新确认。本节是台账编写时的事实边界，
不是自动更新状态。

- Branch: `vision-closure-deliberation-tui`
- Local base head before L11 native CLI cockpit annotation:
  `b5ebad9563c611e2e136e336c3180216966d1010`
- PR: <https://github.com/iiyazu/Cross-Muse/pull/43>
- PR state last checked: draft/open/unmerged
- PR merge state last checked: `CLEAN`
- PR review decision last checked: empty
- Latest verified GitHub Actions truth applies to remote head
  `1a244285c6e9b287f9c32acb640b0bc68087d90b`: run
  `27470910514`, success
- Local documentation commits after the remote head must not be treated as
  CI-verified until pushed and checked again.

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

## Dependency-First Layer Map

| Layer | Name | Dependency role | Closure state |
|---|---|---|---|
| L1 | Authority / Boundary Model | Defines what can write truth | Partly documented; enforcement still uneven |
| L2 | GOD Identity / Provider Binding | Defines selectable GOD/provider actors and account/CLI bindings | Registry slice exists; production selection proof incomplete |
| L3 | GOD Room Durable Event Runtime | Stores durable deliberation events | Durable contract/store slice exists |
| L4 | Speaker Selection / Provider Invocation | Produces live provider response artifacts | Selection/capture slices exist; invocation missing |
| L5 | Speaker Response Capture / Replay Proof | Converts provider artifacts into durable speech | Artifact-backed capture exists |
| L6 | Blueprint Freeze Authority | Turns deliberation into executable blueprint | Typed freeze slice exists |
| L7 | Feature / LaneDAG Authority | Turns blueprint into execution authority | Contract artifact slice exists |
| L8 | Lane Runtime Enforcement / Recovery | Enforces budgets, retries, suspend, refactor | Recovery contract/API slice exists; full enforcement incomplete |
| L9 | Execution / Review / Patch-Forward | Executes bounded work and records review truth | Review plane exists; GOD-room-to-review chain incomplete |
| L10 | MemoryOS / Release Evidence / GitHub Truth | Builds cross-stage memory, replay, and server truth | Evidence slices exist; live/server truth gaps remain |
| L11 | Operator Cockpit / TUI / Overnight Soak | Exposes only closed upstream controls and proves long-run closure | TUI/control slices exist; complete cockpit/soak incomplete |

## L1 - Authority / Boundary Model

- Dependency role:
  - This layer defines which component may create or mutate authoritative
    production state. All later layers depend on this boundary.
- User-visible promise unlocked:
  - The operator can trust that status, readiness, and recovery claims come
    from durable contracts or server truth, not from a convenient UI panel,
    queue file, actor memory, or provider subprocess.
- Current implemented evidence:
  - Mainline docs distinguish graph-set/lane graph/review plane/GitHub checks
    from projections such as cards, dashboard, TUI, and `feature_lanes.json`.
  - Package boundary tests enforce that `xmuse_core` does not import runtime
    `xmuse/` or `memoryos_lite`.
  - Development policy states Ray actors, LangGraph nodes, provider subprocess
    state, and TUI projections are not durable authority.
- Missing production closure:
  - Enforcement is not yet uniformly present across every runner, supervisor,
    dashboard, TUI action, and evidence capture path.
- Proof required to close:
  - A boundary audit showing every mutating path writes through approved
    contracts/stores and every projection/control surface refuses to bypass
    those contracts.
- Current risk:
  - Downstream work can accidentally make a projection look authoritative.
- Next production slice:
  - Add an authority-boundary audit for mutating TUI/API/runner paths and mark
    any bypass as `manual_gap` or `refactor_required`.
- Downstream blocked until:
  - L2-L11 can be built in slices, but none may claim production authority if
    they rely on projection state.
- Do not claim yet:
  - Do not claim all runtime status authority is fully centralized.

## L2 - GOD Identity / Provider Binding

- Dependency role:
  - Real GOD room runtime requires registered GOD identities, registered
    provider/account profiles, and room-level selected-GOD bindings before any
    natural deliberation or speaker invocation can be production proof.
- User-visible promise unlocked:
  - The operator can register and choose which CLI/provider acts as a GOD, and
    later evidence can prove which actor produced which response.
- Required authority objects:
  - `ProviderAccount` / `ProviderProfile`:
    - Records usable provider/CLI/account metadata such as `account_ref`,
      `provider_kind`, `auth_type`, `base_url`, `models`, `env_vars_ref`, and
      `credential_ref`.
    - It is provider availability and credential binding metadata. It is not a
      GOD identity and must not be used directly as room speaker truth.
  - `GodProfile`:
    - Records GOD identity and role metadata such as `god_id`, `display_name`,
      `role`, `capabilities`, `constraints`, and `proof_policy`.
    - It does not store secrets and does not directly invoke providers.
  - `RoomSelectedGodBinding`:
    - Records which GODs are selected for a room/session and how each selected
      GOD resolves to an account/CLI/model.
    - Required fields include `room_id`, `binding_revision`, `god_id`,
      `account_ref`, `cli_command`, `model`, `variant`, `proof_level`,
      `selected_by`, and `selected_at`.
    - L3 event authorship and L4 provider invocation must reference this
      binding, not provider inventory, raw environment discovery, naked CLI
      command strings, or TUI temporary state.
- Current implemented evidence:
  - Provider inventory and provider board projections exist.
  - Provider policy/registry modules exist for Codex, OpenCode, and fake
    providers.
  - Current evidence correctly keeps OpenCode as bounded worker, not peer-GOD.
- Missing production closure:
  - Durable `ProviderAccount`, `GodProfile`, and `RoomSelectedGodBinding`
    contracts are not yet the production authority for GOD room speaker
    identity.
  - Provider inventory/runtime evidence is not yet sufficient to upgrade a CLI
    into a peer-GOD role.
- Proof required to close:
  - Durable account/profile/selection artifacts exist and are consumed by GOD
    room speaker selection and provider invocation.
  - Explicit binding resolution is fail-closed: unresolved `account_ref`,
    incompatible provider/model, missing CLI, or missing proof config produces
    `manual_gap` or `refactor_required`, not fallback environment scanning.
  - For OpenCode/DeepSeek, invocation metadata preserves model and variant as
    separate fields:
    - `cli_command = opencode`
    - `model = opencode-go/deepseek-v4-flash`
    - `variant = max`
    - Never encode `max` into the model id.
- Current risk:
  - Treating a configured worker provider as a selectable GOD without explicit
    role contract and live proof.
  - Letting provider inventory or TUI-selected strings bypass durable selected
    GOD binding.
- Next production slice:
  - Implement durable `ProviderAccount` + `GodProfile` +
    `RoomSelectedGodBinding`, then require L3/L4 to resolve speaker identity
    through the selected binding.
- Downstream blocked until:
  - L3 can store events, but L4 cannot claim live GOD/provider speech without a
    selected actor from this layer.
- Do not claim yet:
  - Do not claim OpenCode or any CLI is a peer-GOD solely because it appears in
    provider inventory.

### L2 clowder-ai reference sources

Use these as implementation references, not as xmuse package dependencies:

- Account binding authority:
  - `/home/iiyatu/clowder-ai/packages/api/src/config/cat-account-binding.ts:9`
    shows that `accountRef` becomes authoritative once written to runtime
    catalog and bootstrap/template state must not reinterpret it.
- Provider/account resolver:
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:23`
    defines `RuntimeProviderProfile` without mixing it with member identity.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:88`
    maps well-known builtin account refs to client families.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:119`
    resolves a single `accountRef`.
  - `/home/iiyatu/clowder-ai/packages/api/src/config/account-resolver.ts:159`
    fails closed when an explicit preferred account ref cannot resolve.
- Identity/member config:
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat.ts:15`
    defines CLI client identity separately from provider account metadata.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat.ts:58`
    shows member identity/config fields including `accountRef`, `clientId`,
    `defaultModel`, `cli`, `roleDescription`, and `provider`.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:34`
    defines reusable CLI invocation config.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:56`
    shows variant-level account/model/CLI binding.
  - `/home/iiyatu/clowder-ai/packages/shared/src/types/cat-breed.ts:217`
    defines account metadata without secrets.
- Account and member mutation validation:
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/accounts.ts:254`
    creates account metadata and writes credentials separately.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:312`
    validates account binding, provider/model compatibility, and API-key model
    requirements.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:510`
    validates binding before creating a runtime member.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/cats.ts:645`
    resolves effective binding during member updates and validates provider
    config changes.
- Runtime invocation and OpenCode reference:
  - `/home/iiyatu/clowder-ai/docs/decisions/001-agent-invocation-approach.md:24`
    records CLI subprocess + MCP callback as the default agent invocation path.
  - `/home/iiyatu/clowder-ai/docs/decisions/001-agent-invocation-approach.md:64`
    records account-binding fail-closed and governance gates for native
    provider opt-in.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/OpenCodeAgentService.ts:115`
    resolves and invokes the OpenCode CLI as an agent service.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/opencode-config-template.ts:84`
    treats provider name as runtime routing authority for OpenCode API type.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/agents/providers/opencode-config-template.ts:124`
    parses OpenCode `provider/model` format.
- Runtime config boundary:
  - `/home/iiyatu/clowder-ai/docs/decisions/017-no-runtime-home-overwrite.md:23`
    forbids runtime dispatch/invocation from overwriting provider home
    directory config files.

## L3 - GOD Room Durable Event Runtime

- Dependency role:
  - This layer is the durable event substrate for deliberation. Speaker
    runtime, freeze, replay, MemoryOS trace, and TUI projections all depend on
    these events.
- User-visible promise unlocked:
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
  - Event append controls still need to prove they use L2 actor identity and L1
    authority boundaries consistently.
- Proof required to close:
  - A fresh transcript where multiple configured GODs produce durable
    question/challenge/handoff/freeze events through provider-backed runtime.
- Current risk:
  - Contract proof can be mistaken for natural peer-GOD runtime proof.
- Next production slice:
  - Bind room event authorship to the selected GOD/provider registry and drive
    provider-backed room speech through the durable event store.
- Downstream blocked until:
  - L6 blueprint freeze cannot claim live deliberation closure without fresh
    durable room event proof.
- Do not claim yet:
  - Do not claim natural peer-GOD groupchat closure.

## L4 - Speaker Selection / Provider Invocation

- Dependency role:
  - This layer chooses the next speaker and invokes the selected provider/GOD
    to produce a provider response artifact. L5 must consume this artifact; it
    must not fabricate provider output.
- User-visible promise unlocked:
  - xmuse can decide who should speak next and ask the configured GOD/provider
    to respond through a production invocation path.
- Current implemented evidence:
  - Speaker replay decisions are deterministic and recoverable.
  - Speaker attempt evidence joins room replay to selected GOD runtime
    continuity.
  - Correct OpenCode/DeepSeek invocation format is documented:
    `opencode run --model opencode-go/deepseek-v4-flash --variant max ...`.
- Missing production closure:
  - The provider response artifact is not yet produced by a production provider
    invocation path in the GOD room flow.
  - Failure modes such as missing provider config, bad CLI, timeout, and
    nonzero exit need contract-level evidence.
- Proof required to close:
  - A provider invocation contract creates
    `xmuse.god_room_provider_speech_response.v1` from a real configured
    provider session with actor identity, command/model/variant, prompt refs,
    output refs, timing, exit status, and proof level.
- Current risk:
  - Treating an imported artifact as equivalent to the live invocation that
    produced it.
- Next production slice:
  - Build the provider invocation/action that emits the provider response
    artifact, with `manual_gap` when provider config or live proof is missing.
- Downstream blocked until:
  - L5 can validate/capture artifacts, but cannot claim live provider speech
    unless the artifact came from this invocation path.
- Do not claim yet:
  - Do not claim the GOD room can autonomously generate live provider speech
    end to end.

## L5 - Speaker Response Capture / Replay Proof

- Dependency role:
  - This layer converts L4 provider response artifacts into durable L3 `speak`
    events and proves the result by replay.
- User-visible promise unlocked:
  - Provider output becomes auditable GOD room speech instead of a loose log or
    manually pasted response.
- Current implemented evidence:
  - Speaker response capture appends a durable `speak` event only when backed
    by a server-loaded provider response artifact.
  - Request-body-only/direct response becomes `manual_gap` when provider
    response artifact proof is missing.
  - Release evidence cross-checks claimed appended `speak_event_id` against
    GOD room replay events.
- Missing production closure:
  - This layer still depends on L4 producing the artifact through a real
    invocation path.
  - Long natural multi-turn capture has not yet been proven.
- Proof required to close:
  - A fresh L4 invocation artifact is captured into L3 room events, then replay
    evidence confirms the appended `speak` event and lineage.
- Current risk:
  - Capture proof can be overread as invocation proof.
- Next production slice:
  - Run capture against the new provider invocation artifact and preserve
    lineage into release evidence.
- Downstream blocked until:
  - L6 cannot claim real deliberation freeze if room speech was not captured
    through L4/L5 proof.
- Do not claim yet:
  - Do not claim live provider invocation proof from capture-only artifacts.

## L6 - Blueprint Freeze Authority

- Dependency role:
  - This layer turns durable deliberation into an executable, typed blueprint.
    It depends on L3-L5 for real discussion provenance.
- User-visible promise unlocked:
  - Discussion becomes executable only through a frozen blueprint with source
    event lineage, assumptions, blockers, rejected alternatives, and decision
    evidence.
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
  - Require live transcript source evidence for production freeze claims and
    mark fixture-only freezes as contract proof.
- Downstream blocked until:
  - L7 cannot claim blueprint-to-lane authority unless the blueprint freeze is
    tied to durable deliberation proof.
- Do not claim yet:
  - Do not claim blueprint freeze is backed by natural peer-GOD deliberation.

## L7 - Feature / LaneDAG Authority

- Dependency role:
  - This layer turns a frozen blueprint into execution authority: feature,
    lane, laneDAG, graph-set, owner, checks, rollback, memory refs, and budget.
- User-visible promise unlocked:
  - A frozen blueprint becomes a governed execution graph, not an ad hoc task
    list or projection queue.
- Current implemented evidence:
  - LaneDAG artifacts include lane runtime contracts with owner, checks,
    rollback, memory refs, and budget.
  - Chat API can build laneDAG from GOD-room freeze resolution without writing
    `feature_lanes.json`.
- Missing production closure:
  - The graph-set/lane authority path is not yet fully unified with every
    execution/dispatch path.
- Proof required to close:
  - A frozen GOD room blueprint feeds authoritative laneDAG/graph-set state
    used by dispatch and review.
- Current risk:
  - Detached laneDAG artifacts may be treated as execution authority before
    dispatch/review actually consumes them.
- Next production slice:
  - Wire lane runtime contracts into dispatch/review evidence and reject
    `feature_lanes.json` as authority.
- Downstream blocked until:
  - L8 and L9 cannot claim production execution closure without consuming this
    lane authority.
- Do not claim yet:
  - Do not claim full blueprint-to-execution authority closure.

## L8 - Lane Runtime Enforcement / Recovery

- Dependency role:
  - This layer enforces L7 lane authority at runtime: budgets, retries,
    suspend/manual_gap, and direct refactor for repeated failure or demo-grade
    implementation.
- User-visible promise unlocked:
  - Lanes cannot silently loop or keep patching demo-grade paths; repeated
    failure triggers suspend or bounded refactor.
- Current implemented evidence:
  - Lane recovery contracts classify retry, suspend, manual_gap, and
    refactor_required.
  - Goal-stage and development policy require direct refactor for repeated
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
- Downstream blocked until:
  - L9 cannot claim trustworthy execution/review if lanes can bypass recovery
    decisions.
- Do not claim yet:
  - Do not claim overnight-safe lane runtime recovery.

## L9 - Execution / Review / Patch-Forward

- Dependency role:
  - This layer executes bounded work from L7/L8, reviews it independently, and
    records accepted/reworked/rejected lineage.
- User-visible promise unlocked:
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
- Downstream blocked until:
  - L10 release evidence cannot claim end-to-end closure without execution and
    review truth from this layer.
- Do not claim yet:
  - Do not claim end-to-end execution/review closure from GOD room input.

## L10 - MemoryOS / Release Evidence / GitHub Truth

- Dependency role:
  - This layer aggregates cross-stage proof and external truth after upstream
    runtime events exist. It records memory traces, replay bundles, readiness,
    GitHub checks, review, and merge facts.
- User-visible promise unlocked:
  - The operator can replay what happened, see what is ready or blocked, and
    distinguish local replay readiness from server-side review/merge truth.
- Current implemented evidence:
  - MemoryOS namespaces and trace anchors exist.
  - GOD room MemoryOS plan artifacts build governed write/context plans without
    importing `memoryos_lite`.
  - Release evidence pack indexes GOD room closure inputs, speaker attempt,
    artifact-backed speaker response, laneDAG, MemoryOS plan, TUI projection,
    GitHub truth, and readiness.
  - PR #43 latest verified CI passed for remote head
    `1a244285c6e9b287f9c32acb640b0bc68087d90b`; merge state was `CLEAN` when
    last checked.
- Missing production closure:
  - No current live MemoryOS Lite trace proof is established for this branch
    head.
  - The release pack still depends on missing live provider invocation, review
    truth, and merge truth for full production closure.
  - PR #43 is still draft/open/unmerged and has no review decision.
- Proof required to close:
  - Configured MemoryOS Lite service accepts writes/context requests and
    returns trace ids mapped to GOD/lane/review artifacts.
  - A fresh replay bundle contains real provider speech, freeze, laneDAG,
    execution/review, MemoryOS trace, GitHub review/check/merge truth or honest
    blockers.
  - Required review/check/merge server-side truth, including merge proof before
    any `pr_merged` event.
- Current risk:
  - Governance plan proof can be overread as live memory proof.
  - `ready_for_replay` can be confused with `ready_to_merge` or `pr_merged`.
  - CI success can be overread as review or merge truth.
- Next production slice:
  - Add opt-in live MemoryOS trace capture after upstream artifacts exist, then
    produce a fresh replay bundle and GitHub truth capture.
- Downstream blocked until:
  - L11 cannot claim production cockpit or overnight readiness unless this
    layer shows honest replay/server truth.
- Do not claim yet:
  - Do not claim live MemoryOS memory closure, release/mainline closure, merge
    closure, or `pr_merged`.

## L11 - Operator Cockpit / TUI / Overnight Soak

- Dependency role:
  - This layer is the final operator surface and long-run proof. It may expose
    partial controls early, but production closure requires L1-L10 to be
    truthful and wired.
- User-visible promise unlocked:
  - The operator can supervise and actuate the autonomous development loop from
    TUI/API surfaces, then run for hours with recovery, replay, memory, review,
    and server truth.
- Current implemented evidence:
  - TUI exposes GOD room actions including room ensure/event append/freeze,
    laneDAG, recovery, MemoryOS plan, speaker attempt, speaker response, and
    release pack aliases.
  - TUI actions route through Chat API/operator contracts.
  - Goal-stage harness, worker delegation policy, RIGR-V, anti-TDD-abuse rules,
    and repeated-failure refactor policy are documented.
  - Evidence/control surfaces exist for many stages.
- Target native CLI cockpit architecture:
  - `NativeCliSessionBridge` starts the real selected CLI from the L2
    `RoomSelectedGodBinding`, preserving native slash commands, ANSI/progress
    rendering, tool-process output, and interactive terminal semantics.
  - `MachineEventBridge` consumes the same CLI run through a separate structured
    stream or raw archive and produces L4 provider invocation artifacts. For
    non-structured output it may preserve raw terminal evidence, but it must
    downgrade structured proof instead of inventing a `speak` event.
  - `GodRoomProjectionBridge` renders the run as if Codex, OpenCode, and other
    selected GODs are in one group room, but room truth still comes only from L3
    durable events and L5 artifact-backed capture.
  - A pane/session registry may expose running native CLI panes to the TUI, but
    it is discovery/projection state, not durable authority.
- Native command-routing rule:
  - Room-level slash commands such as `/freeze`, `/dispatch`, and `/review`
    route through xmuse contracts.
  - Explicit target commands such as `@opencode /models` or `@codex /status`
    may route to the selected native CLI when the L2 binding authorizes it.
  - Focused native-pane input may pass raw bytes to the CLI, but each operator
    input must be recorded as an operator action/source ref.
  - `//` is reserved as an escape hatch to force raw CLI input when a leading
    slash would otherwise be interpreted by xmuse.
- Missing production closure:
  - The cockpit is not yet a complete live operations console for provider
    invocation, review queue decisions, live MemoryOS trace, GitHub truth, and
    overnight continuation/stop decisions.
  - The native CLI cockpit bridge does not yet exist. TUI cannot yet preserve
    full Codex/OpenCode native TUI behavior while simultaneously producing L4/L5
    proof artifacts.
  - No 8-10 hour live GOD room runtime soak has proven natural discussion,
    provider speech, freeze, lane execution, review, MemoryOS trace, and
    GitHub truth together.
- Proof required to close:
  - Operator can run a complete live session through room discussion,
    provider-backed speech, freeze, laneDAG, execution/review, evidence pack,
    and stop/continue decision without bypassing contracts.
  - Native CLI session evidence includes `room_id`, `invocation_id`, `god_id`,
    `binding_revision`, `account_ref`, `cli_command`, `model`, `variant`,
    `pane_id` or `session_id`, `raw_archive_ref`, `stdout_ref`, `stderr_ref`,
    `started_at`, `completed_at`, `exit_code`, `status`, operator input refs,
    L4 artifact ref, L5 `speak_event_id` when captured, and `proof_level`.
  - Read-only observer panes and raw terminal views remain separate from
    authority. A visible native CLI response is not a GOD room `speak` event
    until it is captured through L4/L5 with matching digest and actor/binding
    lineage.
  - A live overnight run with budget ledger, recovery decisions, replay bundle,
    review evidence, and honest blockers.
- Current risk:
  - Expanding panels can create false confidence if live/provider/server proof
    is not clearly separated from projection proof.
  - Long `/goal` progress reports can become optimistic if not tied to replay
    artifacts and server truth.
  - Native CLI interactivity can mutate provider/session state invisibly unless
    every operator input and raw archive ref is attached to the invocation.
- Next production slice:
  - After L2-L5 provider speech closes, expose provider invocation as an
    operator control through a native CLI bridge. After L8-L10 close, run
    bounded soak and cockpit proof.
- Downstream blocked until:
  - This is the terminal integration layer; it should not be used to justify
    upstream shortcuts.
- Do not claim yet:
  - Do not claim TUI is a complete autonomous operations cockpit.
  - Do not claim overnight autonomous production readiness.
  - Do not claim raw terminal output, pane registry state, or a provider process
    session is durable GOD room speech.

### L11 clowder-ai reference sources

Use these as implementation references, not as xmuse package dependencies:

- Single-source dual consumer and tmux-backed provider execution:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:1`
    documents the `tmux pane -> FIFO machine stream + PTY human stream` shape.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:54`
    builds the CLI command with `tee` and exit-code capture.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:90`
    keeps tmux execution on the same event contract as normal CLI spawning.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:104`
    creates per-invocation temp/FIFO/stdin/exit/stderr paths.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:141`
    starts the command and then makes the pane read-only.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:317`
    consumes FIFO output as plain text or NDJSON.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:382`
    captures exit/stderr/diagnostic evidence.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-agent-spawner.ts:480`
    exposes a spawn override so callers remain execution-mode agnostic.
- Tmux gateway and pane lifecycle:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:51`
    manages one tmux server per worktree.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:106`
    creates panes with stable pane ids.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:166`
    supports resize for terminal UI fidelity.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:185`
    creates agent panes with remain-on-exit.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/tmux-gateway.ts:203`
    toggles read-only pane mode.
- Pane discovery and terminal routes:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:1`
    tracks invocation-to-pane discovery state as in-memory projection only.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:39`
    registers an invocation pane.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/terminal/agent-pane-registry.ts:75`
    records completion status.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:27`
    guards terminal WebSocket upgrades by origin.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:56`
    creates or reconnects terminal sessions.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:104`
    attaches PTY output/input over WebSocket for ordinary terminal sessions.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:227`
    lists agent panes for a user/worktree.
  - `/home/iiyatu/clowder-ai/packages/api/src/routes/terminal.ts:243`
    attaches to agent panes read-only.
- Event, diagnostics, and UI projection:
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:75`
    records provider/model/session metadata and CLI diagnostics.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:112`
    enumerates stream message kinds including text, tool use, errors, status,
    provider signals, and liveness signals.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:129`
    defines the streaming agent message envelope.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/types.ts:216`
    defines the spawn override contract.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/session/CliRawArchive.ts:12`
    stores per-invocation raw CLI archive.
  - `/home/iiyatu/clowder-ai/packages/api/src/domains/cats/services/session/CliRawArchive.ts:27`
    appends timestamped raw events.
  - `/home/iiyatu/clowder-ai/packages/web/src/components/workspace/AgentPaneViewer.tsx:16`
    displays a read-only xterm.js view of a native agent pane.

## Maintenance Rules

- Update this ledger after every production-slice commit that changes a layer.
- Keep claims tied to current branch/head/PR/CI facts.
- If a layer is only contract proof, say so explicitly.
- If a live/server proof is missing, record `manual_gap` and the next artifact
  required to close it.
- Do not downgrade evidence boundaries to make a layer look complete.
- Maintain dependency order: downstream UI, evidence, or soak work may expose
  partial views, but it must not claim closure before upstream authority and
  runtime proof exist.
- Prefer direct refactor over repeated patch stacking for demo-grade or
  repeatedly failing production paths.
