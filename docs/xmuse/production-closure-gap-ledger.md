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
- Local base head before audit reinforcement annotation:
  `2cfc9e3016ff1671758bd78b3b69f8ca922307c1`
- Local head at start of L4 provider invocation producer slice:
  `db9a759ac23e3e5f6095fe35ed5d373e64281505`
- Local head at start of L5 provider invocation capture slice:
  `85e573c24c4c1abc955638b4feb609c6381580ff`
- Local head at start of L4/L5 opt-in live route repair:
  `7aef014e41b6de3caac032c3338c39accf1a8e90`
- Local head at start of L6 freeze proof classification slice:
  `5f74e2d3911d1f919758ea397ff5c423149a20ce`
- Local head at start of L7 laneDAG proof metadata slice:
  `914d1b2597bf2a011cb321b123391bd0d26a5b28`
- Local head at start of L8 recovery lineage evidence slice:
  `7d96d3045af4a02d12c045485ed78f072af9f093`
- Local head at start of L9 review intake evidence slice:
  `b345bff0488275aeb1f472653eed7dae66cb1171`
- Local head at start of L9 independent review verdict artifact slice:
  `9cfde76cf5e974a0c0fdbbb851a58cbf09fcbe63`
- Local head at start of L9 patch-forward laneDAG contract slice:
  `39c5c00c46a3ec09ad9a65019ad5b95697d961f4`
- Local head at start of L9 reviewed patch-lane closure handoff slice:
  `734a410a181dd5e6d880f68e248c945e0668f76a`
- Local head at start of L10 review-closure release evidence linkage slice:
  `31f9a96195d8194f6b0fcd5a4464fb340ecc7f85`
- Local head at start of L10 review-closure MemoryOS candidate source-ref slice:
  `112d410334ebf8ae702dc5582297aedc57cd223d`
- Local head at start of L9 review-plane store sync slice:
  `b9b94acbdf8748bbc5fcd56bd40c5a93b702aded`
- Local head at start of L8 review-intake recovery enforcement slice:
  `d8e268c2a70ffc1e2fe83fe3d51850cc93a2ed1d`
- Local head at start of L8 dispatch recovery enforcement slice:
  `9befbc8709585df60072ffef26b26cbc0b61c6ee`
- Local head at start of L3 public event append proof-boundary slice:
  `9190723d7da2580fed392829f3367c32b52f82a9`
- Local head at start of L3 public event append authorship classification slice:
  `2ac5eebeb0226324e3bba5a3e62b73c7c27e3124`
- Local head at start of L3 replay event proof projection slice:
  `515f1817e8c7fabf9c594b96ed044018eaefbc6f`
- Local head at start of L6 freeze manual-gap event proof enforcement slice:
  `604851eca5df99de1e0c9a3b51576037c8a3c93b`
- Local head at start of L3-L5 multi-turn provider speech orchestrator slice:
  `3c8b17eb433a5536899ca8936c545323da1ee1ab`
- Local head at start of L6 multi-turn freeze lineage slice:
  `4d9e5ef9f9404813e337038409138448e70495da`
- Local head at start of L7 graph-native dispatch authority slice:
  `91500e4d852e07bacf4ed4ff00e9aa7ef0bd2f71`
- Local head at start of L7 blueprint proof status lineage slice:
  `3251134b63f886758559a27d80393e9543ac3c80`
- Local head at start of L7 laneDAG graph-set/status bridge slice:
  `a9644c58fd3b0ef1b7d02cd95b703fd1a3344938`
- Local head at start of L9 review-intake graph-status gate slice:
  `60d233c5758c63a2a31a2c2b3d78e62559971a29`
- PR: <https://github.com/iiyazu/Cross-Muse/pull/43>
- PR state last checked: draft/open/unmerged
- PR merge state last checked: `CLEAN`
- PR review decision last checked: empty
- Verified GitHub Actions truth at the start of this slice applied to remote head
  `a9644c58fd3b0ef1b7d02cd95b703fd1a3344938`: run
  `27494551576`, success
- Local changes after `a9644c58fd3b0ef1b7d02cd95b703fd1a3344938` must not be
  treated as CI-verified until pushed and checked again.

Machine-readable snapshot for gates and future `/goal` setup:

```yaml
truth_snapshot:
  branch: vision-closure-deliberation-tui
  base_head: 2cfc9e3016ff1671758bd78b3b69f8ca922307c1
  local_head_at_l4_provider_invocation_slice: db9a759ac23e3e5f6095fe35ed5d373e64281505
  local_head_at_l5_provider_invocation_capture_slice: 85e573c24c4c1abc955638b4feb609c6381580ff
  local_head_at_l4_l5_opt_in_live_route_repair: 7aef014e41b6de3caac032c3338c39accf1a8e90
  local_head_at_l6_freeze_proof_classification_slice: 5f74e2d3911d1f919758ea397ff5c423149a20ce
  local_head_at_l7_lanedag_proof_metadata_slice: 914d1b2597bf2a011cb321b123391bd0d26a5b28
  local_head_at_l8_recovery_lineage_evidence_slice: 7d96d3045af4a02d12c045485ed78f072af9f093
  local_head_at_l9_review_intake_evidence_slice: b345bff0488275aeb1f472653eed7dae66cb1171
  local_head_at_l9_review_verdict_artifact_slice: 9cfde76cf5e974a0c0fdbbb851a58cbf09fcbe63
  local_head_at_l9_patch_forward_lanedag_contract_slice: 39c5c00c46a3ec09ad9a65019ad5b95697d961f4
  local_head_at_l9_reviewed_patch_lane_closure_handoff_slice: 734a410a181dd5e6d880f68e248c945e0668f76a
  local_head_at_l10_review_closure_release_evidence_linkage_slice: 31f9a96195d8194f6b0fcd5a4464fb340ecc7f85
  local_head_at_l10_review_closure_memoryos_candidate_source_ref_slice: 112d410334ebf8ae702dc5582297aedc57cd223d
  local_head_at_l9_review_plane_store_sync_slice: b9b94acbdf8748bbc5fcd56bd40c5a93b702aded
  local_head_at_l8_review_intake_recovery_enforcement_slice: d8e268c2a70ffc1e2fe83fe3d51850cc93a2ed1d
  local_head_at_l8_dispatch_recovery_enforcement_slice: 9befbc8709585df60072ffef26b26cbc0b61c6ee
  local_head_at_l3_public_event_append_proof_boundary_slice: 9190723d7da2580fed392829f3367c32b52f82a9
  local_head_at_l3_public_event_append_authorship_classification_slice: 2ac5eebeb0226324e3bba5a3e62b73c7c27e3124
  local_head_at_l3_replay_event_proof_projection_slice: 515f1817e8c7fabf9c594b96ed044018eaefbc6f
  local_head_at_l6_freeze_manual_gap_event_proof_enforcement_slice: 604851eca5df99de1e0c9a3b51576037c8a3c93b
  local_head_at_l3_l5_multi_turn_provider_speech_orchestrator_slice: 3c8b17eb433a5536899ca8936c545323da1ee1ab
  local_head_at_l6_multi_turn_freeze_lineage_slice: 4d9e5ef9f9404813e337038409138448e70495da
  local_head_at_l7_graph_native_dispatch_authority_slice: 91500e4d852e07bacf4ed4ff00e9aa7ef0bd2f71
  local_head_at_l7_blueprint_proof_status_lineage_slice: 3251134b63f886758559a27d80393e9543ac3c80
  local_head_at_l7_lanedag_graph_set_status_bridge_slice: a9644c58fd3b0ef1b7d02cd95b703fd1a3344938
  local_head_at_l9_review_intake_graph_status_gate_slice: 60d233c5758c63a2a31a2c2b3d78e62559971a29
  pr: 43
  pr_url: https://github.com/iiyazu/Cross-Muse/pull/43
  pr_state: draft_open_unmerged
  merge_state: CLEAN
  review_decision: empty
  verified_ci_head_at_slice_start: a9644c58fd3b0ef1b7d02cd95b703fd1a3344938
  verified_ci_run_at_slice_start: 27494551576
  ci_verified_for_slice_start_head: true
  local_changes_after_verified_head: true
  pr_merged_claim_allowed: false
```

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

| Layer | Name | Contract state | Runtime state | Server truth state | Allowed claim |
|---|---|---|---|---|---|
| L1 | Authority / Boundary Model | Partly documented | Enforcement uneven | Not server-bound | Boundary policy exists, not global enforcement |
| L2 | GOD Identity / Provider Binding | Durable account/profile/room binding contract and store exist | Speaker attempt/capture consume binding fail-closed; one isolated Codex L4/L5 live route consumed binding | Not server-bound | L2 contract proof; bounded worker/provider inventory only |
| L3 | GOD Room Durable Event Runtime | Durable event contract/store exists | Single-turn opt-in live Codex L4/L5 route appended and replayed one `speak` event; bounded multi-turn API can append/replay multiple L5-gated `speak` events; live natural multi-GOD proof still missing | Not server-bound | Durable room contract proof plus isolated opt-in live speak replay proof and bounded multi-turn orchestration contract proof |
| L4 | Speaker Selection / Provider Invocation | Selection/attempt evidence plus provider invocation artifact producer contract exist | Core/API producer emits response artifacts, fail-closed artifacts, one verified local opt-in live Codex artifact through execution worktree, and multiple artifacts when driven by the bounded multi-turn route | Not server-bound | Provider invocation artifact contract/fail-closed proof plus isolated Codex opt-in live proof |
| L5 | Speaker Response Capture / Replay Proof | Artifact-backed capture plus composed L4-to-L5 route exists | Rejects contract-only L4 artifacts; appends/replays only server-written real-proof artifacts; one local opt-in live Codex artifact was captured into durable replay; bounded multi-turn route stops on manual_gap and preserves prior durable events | Not server-bound | Capture/replay contract proof plus isolated Codex opt-in live capture proof and bounded multi-turn capture orchestration proof |
| L6 | Blueprint Freeze Authority | Typed freeze artifact exists with proof-level classification | Single-turn provider-backed Codex speech and bounded multi-turn L3-L5 run lineage can feed freeze artifacts while preserving durable event authority; fresh natural multi-GOD freeze still missing | Not server-bound | Freeze contract proof plus isolated opt-in live freeze proof plus bounded multi-turn lineage proof |
| L7 | Feature / LaneDAG Authority | LaneDAG/contract artifact exists with upstream freeze proof metadata and graph-set/status initialization contract | Live L4/L5/L6 proof metadata can flow into laneDAG without writing `feature_lanes.json`; laneDAG route now derives graph-set artifacts and initializes graph-native status records with inherited `blueprint_proof_level`; `graph_set_id`-backed orchestrator dispatch/review/reprojection now fail closed when durable graph-native status is missing; full dispatch/review authority still not unified | Not server-bound | LaneDAG contract proof plus isolated opt-in live upstream-proof propagation, graph-native proof-lineage carrier proof, laneDAG-to-status initialization proof, and graph-native missing-status fail-closed proof |
| L8 | Lane Runtime Enforcement / Recovery | Recovery contract/API exists and recovery artifacts carry laneDAG proof lineage | Recovery API consumes laneDAG contract/budget and preserves blueprint proof/source refs; GOD-room review intake and orchestrator dispatch now fail-close non-retry recovery decisions; review intake now also requires graph-native `REVIEWING` status from `FeatureGraphStatusStore`; broader supervisor/live runner enforcement still incomplete | Not server-bound | Recovery policy proof plus laneDAG-lineage evidence proof plus review-intake/dispatch enforcement proof |
| L9 | Execution / Review / Patch-Forward | Review plane plus GOD-room review intake/verdict/patch-forward/closure artifact contracts exist | GOD-room lane contracts/recovery/candidate evidence can be packaged for independent review only after graph-native status is `REVIEWING`; review verdicts sync task/verdict lineage into `review_plane.json`; patch-forward verdicts can append a laneDAG patch lane and reviewed patch-lane merge verdicts can produce a release-evidence handoff; live execution proof and server truth still missing | Not server-bound | GOD-room review/patch-forward closure contract proof plus graph-status-gated review-intake proof and review-plane store lineage proof, not server/GitHub truth |
| L10 | MemoryOS / Release Evidence / GitHub Truth | Evidence bundle semantics exist and can index GOD-room review closure handoff; release candidates can seed MemoryOS source refs from that handoff | Live MemoryOS trace and live execution/server truth missing | PR open/unmerged; CI truth only for verified remote head | Replay/readiness proof with explicit gaps |
| L11 | Operator Cockpit / TUI / Overnight Soak | TUI/control slices exist | Complete cockpit/soak missing | Depends on L10 | Operator projection/control proof only |

Current closure audit:

- Overall ledger verdict: valid as a gap ledger, not valid as closure proof.
- Most mature areas: control surfaces, read models, evidence envelopes, and
  claim-boundary governance.
- Least closed areas: natural multi-GOD deliberation, GOD-room-originated
  execution/review, live MemoryOS trace, and GitHub merge truth.
- Next production priority: carry bounded multi-turn L3-L5 speech lineage into
  L6 freeze and L10 release evidence where appropriate, then enforce L7-L9
  runtime/review consumption of authoritative laneDAG contracts without
  claiming natural multi-GOD closure.

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
  - `src/xmuse_core/providers/god_identity_binding.py` defines durable
    `ProviderAccount`, `GodProfile`, and `RoomSelectedGodBinding` contracts plus
    `GodIdentityBindingStore` and fail-closed binding resolution.
  - `select_god_cli` can now persist a room-scoped selected-GOD binding through
    operator action contract when `room_id`, `participant_id`, `god_id`, and
    `model` are supplied.
  - Chat API speaker attempt/response paths pass a selected binding resolver, so
    L4 attempt and L5 capture cannot proceed from selected runtime projection
    alone when the room binding is missing or mismatched.
  - L5-generated durable `speak` events now carry binding lineage fields such as
    `binding_revision`, `account_ref`, `cli_command`, `model`, and `variant`.
- Missing production closure:
  - Durable binding authority is currently proven at `contract_proof` through
    JSON store, operator action, resolver, speaker attempt, and capture paths;
    it is also consumed by one isolated local Codex opt-in L4/L5 live speech
    route.
  - Provider inventory/runtime evidence is not yet sufficient to upgrade a CLI
    into a peer-GOD role.
  - Full peer-GOD speech closure still requires the remaining escalation
    conditions below, including non-`speak` deliberation acts and release
    evidence.
- Proof required to close:
  - Durable account/profile/selection artifacts exist and are consumed by GOD
    room speaker selection and provider invocation. Current evidence proves
    selection/attempt/capture consumption at `contract_proof` and one isolated
    Codex opt-in live L4/L5 route.
  - Explicit binding resolution is fail-closed: unresolved `account_ref`,
    incompatible provider/model, missing CLI, or missing proof config produces
    `manual_gap` or `refactor_required`, not fallback environment scanning.
  - For OpenCode/DeepSeek, invocation metadata preserves model and variant as
    separate fields:
    - `cli_command = opencode`
    - `model = opencode-go/deepseek-v4-flash`
    - `variant = max`
    - Never encode `max` into the model id.
- Proof escalation policy:
  - A CLI/provider can be promoted from `bounded_worker` to `peer_god` only when
    all of these are true:
    - `GodProfile` exists with explicit `proof_policy`.
    - `RoomSelectedGodBinding` resolves fail-closed to a `ProviderAccount`.
    - L4 emits a provider speech artifact from that selected binding.
    - L5 captures the artifact into a durable L3 `speak` event.
    - L3 replay proves authored speech with GOD identity and binding revision.
    - At least one `question`, `challenge`, or `handoff` event is produced under
      that identity in the same room lineage.
    - Release evidence records `proof_level=live_provider_god_speech`.
  - Until every condition passes, the CLI/provider remains a bounded worker or
    provider inventory entry, even if it is configured and callable.
- Current risk:
  - Treating a configured worker provider as a selectable GOD without explicit
    role contract and live proof.
  - Letting provider inventory or TUI-selected strings bypass durable selected
    GOD binding in paths not yet audited.
  - Treating L2 `contract_proof` as L4 provider invocation proof.
- Next production slice:
  - Use the isolated L4/L5 Codex live speech lineage as input for L6 freeze or
    L10 evidence while preserving the missing natural multi-GOD and release
    evidence gaps.
- Downstream blocked until:
  - L3-L5 can prove isolated live Codex speech, but natural peer-GOD room
    closure remains blocked until multiple configured GOD acts and release
    evidence exist.
- Do not claim yet:
  - Do not claim OpenCode or any CLI is a peer-GOD solely because it appears in
    provider inventory.
  - Do not claim L2 `contract_proof` as live provider speech or natural GOD room
    closure.

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
  - Public Chat API event append now rejects direct `actor_kind=god` `speak`
    events that try to carry provider-backed proof markers such as
    `provider_response_artifact:` source refs, provider invocation refs, or
    L4/L5 capture payload fields. Such attempts return
    `proof_level=manual_gap` and do not write a durable event; provider-backed
    `speak` remains writable only through the L5 capture path that loads the
    L4 artifact server-side.
  - Public Chat API direct append now writes a server-owned
    `public_append_authority` payload for GOD-authored direct events. If
    `RoomSelectedGodBinding` resolves, the payload records
    `proof_level=contract_proof`, binding revision, account/model metadata, and
    binding source refs. If resolution fails, the event remains a
    contract/manual transcript but records `proof_level=manual_gap`,
    `room_selected_god_binding_unresolved`, and forbidden live-proof claims.
    Client-supplied `public_append_authority` is rejected as a reserved proof
    field.
  - A local opt-in live Codex composed route run appended one provider-backed
    `speak` event and returned room replay `ok` from a temp runtime root:
    `/tmp/xmuse-live-l4-l5-uynpv_gj`.
  - `GodRoomReplayResult` now includes `event_proofs`, a projection derived
    from durable `GodRoomEventV1` payload/source refs. It distinguishes public
    append `manual_gap`, public append `contract_proof`, and L5
    provider-backed `opt_in_live_proof` event lineage while keeping the
    room-level replay `proof_level` at `contract_proof` or `manual_gap`. The
    original L4/L5 artifact proof label remains available as artifact lineage,
    not as a room-level closure claim.
  - Chat API now exposes a bounded sequential
    `POST /api/chat/conversations/{conversation_id}/god-room/multi-turn-provider-speech`
    route. The route drives multiple turns only by repeatedly invoking the
    existing L4 provider invocation producer and L5 capture path, reloading
    durable GOD room state between turns and writing a
    `xmuse.god_room_multi_turn_provider_speech_run.v1` evidence artifact under
    `reports/god_room_provider_speech_runs/`.
- Missing production closure:
  - Natural multi-GOD live runtime has not been proven over a long session.
  - The multi-turn provider speech route is bounded sequential orchestration,
    not natural peer-GOD autonomy, distributed groupchat, or overnight runtime
    proof.
  - Public direct append now classifies GOD event authorship through L2 binding
    resolution or explicit `manual_gap`, but this still does not prove fresh
    provider-backed natural deliberation or every non-HTTP writer path.
  - Event proof projection summarizes existing durable event lineage only; it
    does not load or re-verify L4 artifacts and must not be treated as new
    provider invocation proof.
- Proof required to close:
  - A fresh transcript where multiple configured GODs produce durable
    question/challenge/handoff/freeze events through provider-backed runtime.
- Current risk:
  - Contract proof can be mistaken for natural peer-GOD runtime proof.
  - Direct public append remains contract/manual proof only unless backed by
    the L4/L5 provider-capture route.
- Next production slice:
  - Use bounded multi-turn provider-backed speech as input for L6 freeze and
    L10 release-evidence lineage while preserving the natural peer-GOD
    groupchat and live/server proof gaps.
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
  - Speaker attempt/response capture now fail closed through
    `RoomSelectedGodBinding` resolution when the Chat API runtime hook is used.
  - `src/xmuse_core/chat/god_room_provider_invocation.py` now provides the L4
    producer for `xmuse.god_room_provider_speech_response.v1`. It consumes a
    ready `GodRoomSpeakerAttemptV1`, preserves selected binding lineage
    (`binding_revision`, `account_ref`, `cli_command`, `model`, `variant`),
    builds the provider CLI command, records prompt/output refs, timing,
    exit status, raw output digest, failure kind, and proof level.
  - Chat API exposes
    `POST /api/chat/conversations/{conversation_id}/god-room/provider-invocation`
    and writes provider response artifacts under `reports/provider-responses/`
    without appending a durable `speak` event.
  - The bounded multi-turn provider speech route does not create provider
    responses itself. Each turn calls the same L4 producer, so every successful
    turn still has its own `xmuse.god_room_provider_speech_response.v1`
    artifact and fail-closed outcome.
  - The provider invocation API now uses the configured execution worktree for
    provider CLI subprocesses while continuing to write runtime artifacts under
    the xmuse runtime root; this prevents Codex/OpenCode from being launched in
    untrusted state directories.
  - A local opt-in live Codex smoke run through the composed L4/L5 route
    produced a `completed` `real_provider_proof` L4 artifact with command
    `codex exec -m gpt-5.4 -C /home/iiyatu/projects/python/xmuse`, provider
    session id `019ec42d-b245-7d10-b3f8-f511fdceff5f`, and artifact ref
    `reports/provider-responses/conv_b1a9fbccd098460abbb4e9ca84131d3f.evt-live-propose.provider-response-7e7a878796cfeebd.json`
    in temp runtime root `/tmp/xmuse-live-l4-l5-uynpv_gj`.
  - Focused tests cover the contract producer success path, unresolved binding,
    unsupported CLI, missing CLI, nonzero exit, timeout, non-structured output
    as `raw_archive_only`, and L5 refusing to capture contract-only provider
    responses as real provider speech.
  - Correct OpenCode/DeepSeek invocation format is documented:
    `opencode run --model opencode-go/deepseek-v4-flash --variant max ...`.
- Missing production closure:
  - `allow_live_provider_proof=true` remains opt-in runtime behavior and must
    not be claimed broadly unless the resulting artifact, L5 capture, and L3
    replay are inspected from current runtime evidence.
  - The verified live path is limited to local Codex invocation artifacts; the
    bounded multi-turn route can preserve multiple per-turn artifacts, but it
    still does not prove OpenCode peer-GOD status, natural multi-GOD
    deliberation, or long-running autonomous provider speech.
- Proof required to close:
  - A provider invocation contract creates
    `xmuse.god_room_provider_speech_response.v1` from a real configured
    provider session with actor identity, command/model/variant, prompt refs,
    output refs, timing, exit status, and proof level.
- Negative proof matrix:
  - These outcomes must be enforced by the L4 invocation path and the L4/L5
    capture boundary:

| Condition | Required outcome | Claim boundary |
|---|---|---|
| Missing `account_ref` | `manual_gap` | No provider speech artifact |
| Unknown `god_id` | `manual_gap` | No provider speech artifact |
| Unsupported provider/model/variant | `manual_gap` or `refactor_required` | No fallback model/provider |
| Missing CLI binary | `manual_gap` | No live invocation proof |
| Nonzero CLI exit | `invocation_failed` | Artifact records failure only |
| Timeout | `invocation_timeout` | Artifact records timeout only |
| Non-structured output | `raw_archive_only` | No automatic `speak` event |
| Digest mismatch at capture | `capture_rejected` | No durable `speak` event |
| Operator raw input without `source_ref` | `capture_rejected` | No durable `speak` event |

- Current risk:
  - Treating an imported artifact as equivalent to the live invocation that
    produced it.
  - Treating an L4 `contract_proof` artifact as L5-capturable
    `real_provider_proof`.
- Next production slice:
  - Carry the bounded multi-turn L4 provider artifact lineage into L6/L10
    evidence without expanding the claim beyond per-turn artifact proof.
- Downstream blocked until:
  - L5 can validate/capture live-proof artifacts, but cannot claim live
    provider speech from contract-only L4 artifacts.
- Do not claim yet:
  - Do not claim natural multi-GOD autonomous provider speech end to end.

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
  - Contract-only L4 provider invocation artifacts remain `manual_gap` at the
    L5 capture boundary; this prevents capture proof from being overread as
    provider invocation live proof.
  - Chat API now exposes
    `POST /api/chat/conversations/{conversation_id}/god-room/provider-invocation-capture`
    to produce a server-written L4 artifact and immediately pass that artifact
    ref into the L5 capture gate.
  - The composed route writes both provider response and speaker response
    artifacts and returns the durable room replay from `GodRoomEventStore`.
  - The bounded multi-turn provider speech route repeatedly uses the composed
    L4/L5 route. It appends each `speak` event only through L5 capture, stops
    on the first `manual_gap`, preserves already appended durable events, and
    records the run artifact with per-turn provider response refs, speaker
    response refs, final replay, manual gaps, and forbidden claims.
  - The composed route now refreshes durable `GodSessionRegistry` provider
    binding from a completed `real_provider_proof` L4 artifact before L5
    capture, so L5 still enforces provider session lineage while accepting a
    fresh session id created by the live provider invocation.
  - Focused tests prove that contract/manual L4 artifacts do not append speech,
    while a server-produced `real_provider_proof` artifact is captured into a
    durable `speak` event and appears in replay with binding lineage.
  - A local opt-in live Codex route produced L5
    `status=speak_event_appended`, `proof_level=real_provider_proof`, matching
    provider session id `019ec42d-b245-7d10-b3f8-f511fdceff5f`, events
    `["evt-live-propose", "evt-live-provider-speak"]`, and replay `ok`.
  - Release evidence cross-checks claimed appended `speak_event_id` against
    GOD room replay events.
- Missing production closure:
  - Long natural multi-turn capture has not yet been proven; current multi-turn
    proof is bounded sequential API orchestration.
  - Release evidence does not yet preserve this live L4/L5 lineage as a
    production release proof.
- Proof required to close:
  - A fresh L4 invocation artifact is captured into L3 room events, then replay
    evidence confirms the appended `speak` event and lineage.
- Current risk:
  - Capture proof can be overread as invocation proof.
- Next production slice:
  - Preserve the bounded multi-turn appended `speak_event_id` values, L4
    artifact refs, L5 artifact refs, and replay evidence in L6/L10 lineage,
    then use the durable speech as input for freeze without claiming natural
    deliberation.
- Downstream blocked until:
  - L6 cannot claim real deliberation freeze if room speech was not captured
    through L4/L5 proof.
- Do not claim yet:
  - Do not claim natural multi-turn provider speech or OpenCode peer-GOD proof
    from this single Codex opt-in live route.

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
  - Freeze artifacts now carry explicit `proof_level`:
    - `manual_gap` for blocked freezes;
    - `contract_proof` for fixture/contract transcripts;
    - `opt_in_live_proof` only when durable source events include
      `speak` events with `real_provider_proof` and a
      `provider_response_artifact:` lineage ref from L4/L5.
  - Legacy `xmuse.god_room_blueprint_freeze.v1` artifacts without
    `proof_level` deserialize as `manual_gap` when blocked and
    `contract_proof` otherwise; missing proof metadata does not become live
    proof.
  - Freeze compilation now consumes L3 event proof projection and blocks
    `manual_gap` event proof before persisting a frozen blueprint. This prevents
    unresolved public GOD-room transcripts from being frozen as authoritative
    blueprint evidence.
  - GOD-room freeze requests can now cite a server-written
    `xmuse.god_room_multi_turn_provider_speech_run.v1` artifact. The Chat API
    validates that the run artifact stays under the runtime root, matches the
    current conversation and room, is completed, is not `manual_gap`, and that
    each run `appended_event_id` exists in the current durable room events.
    When validation passes, the run artifact and per-turn provider/speaker
    response artifact refs are carried into the freeze artifact and frozen
    blueprint `source_refs` as lineage only. Freeze `proof_level` remains
    derived from durable event proof projection, not from the run artifact.
  - A local L6 smoke run in temp runtime root
    `/tmp/xmuse-live-l6-freeze-9anxog8k` used a live Codex L4/L5 speak event,
    appended `evt-freeze`, and produced a frozen
    `xmuse.god_room_blueprint_freeze.v1` artifact with
    `proof_level=opt_in_live_proof`, `decision_event_id=evt-freeze`, provider
    artifact lineage in source refs, and resolution
    `res_70fff7c8e1224215a6e35c58ffadcf5d` with
    `approval_mode=god_room_blueprint_freeze`.
- Missing production closure:
  - The freeze path has not yet been proven from a fresh live multi-GOD
    transcript with real challenges and objections.
  - Release evidence does not yet preserve the L4/L5/L6 live lineage as a
    production proof bundle.
  - Event proof enforcement does not re-verify L4 provider artifacts; it only
    preserves the upstream event proof boundary.
  - Multi-turn run artifact validation links orchestration lineage to freeze,
    but it still does not prove natural peer-GOD deliberation or server truth.
- Proof required to close:
  - A live transcript produces a freeze artifact preserving assumptions,
    blockers, rejected alternatives, source refs, and decision event lineage.
- Current risk:
  - Freezing a clean contract fixture can be mistaken for real deliberation
    closure.
- Next production slice:
  - Carry the frozen blueprint and bounded multi-turn lineage refs into L7
    laneDAG authority while preserving whether the freeze proof level is
    `contract_proof` or `opt_in_live_proof`.
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
  - `BlueprintLaneDagPlan` now carries `blueprint_proof_level` and source refs
    inherited from the GOD-room freeze artifact. This keeps downstream
    execution/review/release evidence aware of whether the source freeze was
    `contract_proof` or `opt_in_live_proof`.
  - A local L7 smoke run in temp runtime root
    `/tmp/xmuse-live-l7-lanedag-vtb6b6by` consumed a live L4/L5/L6 Codex
    lineage and produced `lane_graphs/graph-live-route.lane-dag.json` with
    `blueprint_proof_level=opt_in_live_proof`, provider artifact source refs,
    and no `feature_lanes.json` write.
  - Orchestrator graph-native authority guards now fail closed for
    `graph_set_id`-backed lanes when `FeatureGraphStatusStore` has no matching
    durable status record. Legacy lanes and graph-id-only compatibility paths
    keep projection-compatible behavior; graph-set-backed lanes with only
    `feature_lanes.json` projection state do not dispatch/review/reproject from
    projection alone.
  - `FeatureGraphExecutionStatusRecord` and `FeatureEvidenceBundle` now carry
    optional `blueprint_proof_level`, and `FeatureGraphStatusStore`
    initialization/upsert/transition plus worker-evidence, review, rework, and
    patch-forward status producers preserve that lineage. Legacy records with
    no proof field remain readable and are treated as proof boundary unknown /
    contract-level rather than live proof.
  - The GOD-room laneDAG Chat API route now derives a `FeatureGraphSet` from the
    produced `BlueprintLaneDagPlan`, saves it under `graph_sets/`, and initializes
    `FeatureGraphStatusStore` records with the laneDAG `blueprint_proof_level`.
    Focused API coverage proves a two-feature laneDAG becomes ready/planned
    graph-native status records without writing `feature_lanes.json`.
- Missing production closure:
  - The graph-set/lane authority path is not yet fully unified with every
    execution/dispatch path.
  - Dispatch/review still need to prove they consume laneDAG authority and do
    not fall back to detached artifacts or projection queue state.
  - `blueprint_proof_level` is preserved in laneDAG artifacts, graph-native
    status records, worker evidence bundles, GOD-room recovery/review
    artifacts, and key graph-native status-transition producers, but it is not
    yet proven through every live runner evidence path.
  - The laneDAG-to-graph-set bridge is contract proof only; it has not yet been
    exercised in a fresh live L4/L5/L6/L7 runtime chain and does not prove
    execution/review consumption.
- Proof required to close:
  - A frozen GOD room blueprint feeds authoritative laneDAG/graph-set state
    used by dispatch and review.
- Current risk:
  - Detached laneDAG artifacts may be treated as execution authority before
    dispatch/review actually consumes them.
  - Legacy projection lanes and graph-id-only compatibility lanes remain
    compatibility-only and must not be described as graph-native L7 authority.
- Next production slice:
  - Feed the laneDAG-derived graph-set/status authority into the next
    dispatch/review runner path, then continue removing graph-backed
    dispatch/review fallbacks to detached laneDAG artifacts or
    `feature_lanes.json`.
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
  - GOD-room lane recovery API consumes the laneDAG artifact and lane runtime
    contract budget, then writes recovery artifacts with
    `blueprint_proof_level` and laneDAG/source refs.
  - GOD-room lane review intake now consumes the latest lane recovery decision
    as a gate: `retry_allowed=false` decisions (`manual_gap`, `suspended`, or
    `refactor_required`) return 409 and do not write review-intake, review-plane,
    or `feature_lanes.json` artifacts.
  - GOD-room lane review intake also consumes `FeatureGraphStatusStore` and
    fails closed unless the lane's graph-native feature status is `REVIEWING`.
    A laneDAG artifact, recovery artifact, worker candidate ref, or
    `feature_lanes.json` projection cannot by itself authorize review intake.
  - Orchestrator dispatch now consumes the durable lane recovery artifact before
    dispatch CAS. A latest `retry_allowed=false` decision blocks same-path
    dispatch, records recovery block metadata, and does not invoke the execution
    GOD.
  - Goal-stage and development policy require direct refactor for repeated
    failure/demo-grade production paths.
- Missing production closure:
  - Recovery is not yet enforced through every supervisor/runner path; current
    enforcement is proven at the GOD-room review-intake, graph-status intake,
    and orchestrator dispatch boundaries.
  - No live runner proof yet shows a blocked retry after refactor_required.
- Proof required to close:
  - A real lane failure sequence enters recovery/refactor_required and blocks
    further same-path retries until a refactor artifact exists.
- Current risk:
  - Recovery remains advisory if non-dispatch runner/supervisor paths can bypass
    it.
- Next production slice:
  - Enforce recovery decisions in remaining runner/supervisor control flow and
    produce local runtime proof beyond the dispatch-boundary contract test.
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
  - GOD-room lane review intake artifact consumes laneDAG authority, optional
    recovery decision, `FeatureGraphStatusStore` `REVIEWING` authority, and
    worker/execution candidate refs while preserving
    `review_truth_status = pending_independent_review`.
  - Review intake now records `graph_set_id`, `feature_graph_id`, and the
    graph-native status snapshot in its artifact. Non-`REVIEWING` or missing
    graph status returns 409 and does not write review-intake, review-plane, or
    `feature_lanes.json` artifacts.
  - GOD-room lane review verdict artifact requires an existing review intake
    artifact and evidence refs that cite reviewer inputs before recording an
    explicit reviewer decision.
  - GOD-room lane review verdict artifacts now write a `ReviewTask` and
    `ReviewVerdict` into `review_plane.json` through `VerdictStore`, and review
    closure requires the terminal patch-lane merge verdict to be present in
    that review plane store before producing the handoff artifact.
  - GOD-room lane patch-forward artifact requires a patch-forward review verdict
    and saved laneDAG artifact, then uses `BlueprintLaneDagService` to append a
    patch lane, dependency edge, runtime contract, and patch-forward link.
  - GOD-room lane review closure artifact requires the patch-forward sidecar,
    patch lane review intake with candidate refs, and an independent merge
    verdict for the patch lane before producing a release-evidence handoff
    input.
- Missing production closure:
  - A GOD-room-originated lane has not yet been proven through live execution,
    review, patch-forward, and release evidence in one chain.
  - Review intake/patch-forward/closure artifacts still do not execute live
    worker runtime or assert GitHub truth; release
    evidence linkage exists only as contract/candidate handoff, not as
    server-side readiness.
- Proof required to close:
  - A lane from GOD room freeze is executed, reviewed, accepted/reworked, and
    linked into release evidence with lineage.
- Current risk:
  - Worker self-report or local test results can be mistaken for review truth.
- Next production slice:
  - Continue graph-status authority consumption through review verdict,
    patch-forward, and closure decisions, then connect accepted/reworked
    review outcomes back to graph-native lane status without treating worker
    candidate refs as review truth.
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
  - Release evidence pack and operator action can now index
    `xmuse.god_room_lane_review_closure.v1` as GOD-room runtime closure
    handoff input while preserving `server_truth_status = not_server_truth`.
  - Release evidence candidate report can consume the same handoff artifact to
    seed `live_memoryos` operator `source_refs` hints after validating that the
    artifact remains `contract_proof` and `server_truth_status = not_server_truth`.
  - PR #43 latest verified CI passed for remote head
    `1a244285c6e9b287f9c32acb640b0bc68087d90b`; merge state was `CLEAN` when
    last checked.
- Missing production closure:
  - No current live MemoryOS Lite trace proof is established for this branch
    head.
  - The release pack still depends on missing live execution proof, live
    MemoryOS trace, review-plane/lane-status integration, and merge truth for
    full production closure.
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

- Reference boundary for every group below:
  - `reference_status: local_reference_only`
  - `must_not_gate_ci: true`
  - `must_not_claim_external_proof: true`
  - These paths are design references from a sibling local checkout. They are not
    durable xmuse evidence, release proof, package dependencies, or CI gates.
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
- Do not treat local reference paths outside this repository as release proof,
  CI gates, or externally reproducible evidence.
- Maintain dependency order: downstream UI, evidence, or soak work may expose
  partial views, but it must not claim closure before upstream authority and
  runtime proof exist.
- Prefer direct refactor over repeated patch stacking for demo-grade or
  repeatedly failing production paths.
