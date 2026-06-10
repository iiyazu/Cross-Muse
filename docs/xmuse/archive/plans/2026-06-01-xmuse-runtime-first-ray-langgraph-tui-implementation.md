# xmuse Runtime-First Ray/LangGraph/Textual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reviewed runtime-first xmuse foundation: projection quarantine, single-writer runner safety, native runtime facade, provider/OpenCode bounded worker routing, Review GOD autotakeover, Textual read envelopes, and follow-up Ray/LangGraph/multi-feature scheduling paths.

**Architecture:** Keep the existing runner, `LaneStateMachine`, and `LaneProjectionSyncer` as the A-lite execution compatibility layer. Split the spec's P0 foundation into five parallel implementation features (`P0A-P0E`) so provider, evidence, lineage, projection hygiene, and writer safety can land independently before R3/R4b/R5 enforce paths. Ray remains an optional A-full/F4 dependency and is not introduced before the F4 lane.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, Textual, existing xmuse stores/read-models, Codex provider profiles, OpenCode DeepSeek V4 Flash profile, optional Ray in F4 only.

---

## Authoritative Inputs

- Spec: `docs/superpowers/specs/2026-06-01-xmuse-runtime-first-ray-langgraph-tui-blueprint-design.md`
- Graph generator: `xmuse/work/generate_runtime_first_graph_set.py`
- Graph preview: `xmuse/work/runtime_first_graph_preview.md`
- Existing provider/platform plan to avoid duplicating old work: `docs/superpowers/plans/2026-05-31-xmuse-provider-platform-autonomous-recovery.md`
- Existing live projection is migration input only: `xmuse/feature_lanes.json`

## File Map

Planned new or modified modules:

- `src/xmuse_core/platform/projection/allowlist.py`
  Owns projection field allowlist, raw field classification, prompt/command migration helpers, and validation errors.
- `src/xmuse_core/platform/projection/syncer.py`
  Applies allowlist on every write and strips forbidden runtime telemetry from new metadata.
- `src/xmuse_core/structuring/projection.py`
  Adds graph-set lineage fields, prompt refs, scoped lane uniqueness, and graph-native projection metadata.
- `src/xmuse_core/structuring/planning_run_store.py` and `src/xmuse_core/structuring/blueprint_execution/*`
  Keep `PlanningRun.graph_set_id/version` aligned with saved `FeatureGraphSet` snapshots.
- `src/xmuse_core/providers/health.py`, `src/xmuse_core/providers/policy.py`, `src/xmuse_core/providers/selection_record.py`, `src/xmuse_core/providers/service.py`
  Connect health-aware selection and fallback records to runner decisions.
- `src/xmuse_core/providers/registry.py`, `src/xmuse_core/providers/policy.py`, `xmuse/platform_runner.py`
  Enforce the cost model: gpt-5.5 only for merge/final quality GOD, gpt-5.4 for ordinary planning/review/worker roles, and OpenCode only for bounded low-risk workers.
- `src/xmuse_core/chat/driver.py`, `src/xmuse_core/chat/participant_store.py`, `src/xmuse_core/chat/peer_service.py`, `src/xmuse_core/platform/agent_spawner.py`
  Close ordinary chat/peer/spawn model leaks so participant read-normalization, peer provisioning, and fallback spawns do not coerce gpt-5.4 back to gpt-5.5.
- `src/xmuse_core/providers/adapters/opencode.py`
  Keeps OpenCode behind provider-native bounded worker transport; no GOD/review/takeover role.
- `src/xmuse_core/platform/runtime_facade.py` and `src/xmuse_core/platform/runtime_health.py`
  Backend-neutral native runtime facade and health evidence.
- `src/xmuse_core/platform/runner_writer_lease.py` and `src/xmuse_core/platform/merge_lock.py`
  Single-writer projection lease and target-branch merge lock.
- `src/xmuse_core/platform/lane_takeover.py`, `src/xmuse_core/platform/takeover_actions.py`, `src/xmuse_core/platform/autotakeover/*`
  Evidence hash/revision guards, candidate shadow read-models, and Review GOD enforce loop.
- `src/xmuse_core/platform/read_envelopes.py`, `src/xmuse_core/platform/read_contracts.py`, `xmuse/dashboard_api.py`, `xmuse/tui/adapter/xmuse_adapter.py`
  Textual-facing compact envelopes with source authority, revision, generated time, degradation, backend, fallback, and debug drill-down refs.
- `xmuse/platform_runner.py` and `src/xmuse_core/platform/orchestrator.py`
  Runner tick integration, single-writer lease acquisition, dispatch CAS metadata, merge lock use, real run-health discovery, and autotakeover enforcement.
- `pyproject.toml` and `uv.lock`
  Only F4 may add `ray` as an optional dependency. A-lite tasks must not add Ray.

## Feature DAG

`P0E` is the only bootstrap root. It lands writer lease, merge lock, merge-head guards, and real writer-process health before any other lane can merge concurrently.

After `P0E`:

- `P0A`, `P0B`, `P0C`, and `P0D` depend on `P0E` and may run concurrently.

After the P0 foundation:

- `R1` depends on `P0A`, `P0D`.
- `R2a` depends on `P0C`.
- `M0` depends on `P0C`, `R2a`.
- `R4a` depends on `P0C`, `P0D`, `P0E`.
- `T1` depends on `P0A`, `P0B`, `P0C`, `P0E`.
- `R3` depends on `R1`, `R2a`, `M0`, `P0B`, `P0D`, `P0E`.
- `R2b` depends on `R1`, `R2a`, `M0`, `P0A`.
- `R4b` depends on `R3`, `R4a`, `T1`.
- `R5` depends on `R2b`, `R3`, `R4b`, `T1`.

A-full:

- `F1` depends on `R1`, `R4a`.
- `F2a` depends on `P0A`, `P0B`, `P0D`, `P0E`.
- `F3a` depends on `P0A`, `P0B`, `P0E`.
- `F2b` depends on `F2a`, `F3a`, `R5`.
- `F3b` depends on `F3a`, `R3`, `R5`.
- `F4` depends on `R1`, `R3`, `R4b`, `R5`.
- `F5a` depends on `F3b`, `R3`.
- `F5b` depends on `F4`, `F5a`.
- `F6` depends on `T1`, `F2a`, `F2b`, `F3a`, `F3b`.

## Task P0A: Projection Quarantine And Prompt Refs

**Files:**
- Create: `src/xmuse_core/platform/projection/allowlist.py`
- Modify: `src/xmuse_core/platform/projection/syncer.py`
- Modify: `src/xmuse_core/structuring/projection.py`
- Test: `tests/xmuse/test_lane_projection_syncer.py`
- Test: `tests/xmuse/test_feature_graph_projection.py`
- Test: `tests/xmuse/test_dashboard_api.py`

- [ ] **Step 1: Write failing allowlist tests**

Add tests that create lanes with `prompt`, `worker_command`, raw stdout/stderr, provider health diagnostics, and long failure blobs in metadata. Expected behavior: new writes keep `prompt_summary`, `prompt_ref`, `raw_debug_ref`, `command_hash`, and short status/reason fields, while forbidden raw fields are absent from `feature_lanes.json`. Cover dashboard/MCP/direct append paths or explicitly gate them behind debug-only authority so `FeatureGraphSet` remains the normal creation path.

Run:

```bash
uv run pytest tests/xmuse/test_lane_projection_syncer.py tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_dashboard_api.py -q
```

Expected before implementation: at least one failure proving forbidden fields still leak.

- [ ] **Step 2: Implement allowlist module**

Create `ProjectionFieldPolicy` with:

- `allowed_lane_fields`
- `forbidden_runtime_fields`
- `sanitize_lane_for_projection(lane: Mapping[str, Any]) -> dict[str, Any]`
- `sanitize_metadata_for_projection(metadata: Mapping[str, Any]) -> dict[str, Any]`
- deterministic `command_hash` generation for command arrays or shell strings

The implementation must keep legacy debug refs but not raw text in worklist-facing projection fields.

- [ ] **Step 3: Wire syncer and graph projection**

Call the sanitizer from `LaneProjectionSyncer.append_lane`, `replace_lanes`, and `update` before writing. Update `project_feature_graph_set_ready_lanes` payloads to emit `prompt_summary`, `prompt_ref`, and `raw_debug_ref` instead of storing raw prompt as the primary projected worklist field. Legacy debug drill-down may retain raw prompt in artifact files, not in the live projection row. Ad hoc mutators such as `POST /api/lanes` and MCP lane mutation tools must sanitize through the same policy or require explicit debug authority.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_lane_projection_syncer.py tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_platform_state_machine.py -q
```

Expected: tests pass and assertions prove no new `prompt`/`worker_command` leakage.

## Task P0B: Graph-Set Lineage And Scoped Lane Identity

**Files:**
- Modify: `src/xmuse_core/structuring/projection.py`
- Modify: `src/xmuse_core/structuring/feature_plan_store.py`
- Modify: `src/xmuse_core/structuring/blueprint_execution/feature_planning.py`
- Test: `tests/xmuse/test_feature_graph_projection.py`
- Test: `tests/xmuse/test_planning_run_store.py`
- Test: `tests/xmuse/test_blueprint_execution_service.py`

- [ ] **Step 1: Write lineage tests**

Add tests proving newly projected lanes include `graph_set_id`, `graph_set_version`, `feature_plan_id`, `feature_plan_version`, `plan_feature_id`, `lane_id`, `lane_local_id`, `projection_revision`, and `projection_source`. Add a test where two different feature graphs both contain lane local id `design`; the graph set must validate because scoped `lane_id` is unique.

- [ ] **Step 2: Implement graph-set lineage propagation**

Update graph-set save/projection paths so `FeatureGraphSetStore.save()` and projection callers can pass and preserve graph-set id/version. Ensure `PlanningRun.graph_set_id/version` is updated when a graph set is saved from a planning run.

- [ ] **Step 3: Relax local lane uniqueness**

Change validation so lane local ids are unique only within one `LaneGraph`; cross-graph uniqueness is based on the scoped projection lane id.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_planning_run_store.py tests/xmuse/test_blueprint_execution_service.py -q
```

Expected: graph-set lineage is present and duplicate local ids across graphs are accepted when scoped ids differ.

## Task P0C: Provider Health, Selection, And Fallback Contracts

**Files:**
- Modify: `src/xmuse_core/providers/health.py`
- Modify: `src/xmuse_core/providers/policy.py`
- Modify: `src/xmuse_core/providers/selection_record.py`
- Modify: `src/xmuse_core/providers/service.py`
- Modify: `src/xmuse_core/platform/read_contracts.py`
- Test: `tests/xmuse/test_provider_policy.py`
- Test: `tests/xmuse/test_provider_models.py`
- Test: `tests/xmuse/test_provider_opencode.py`

- [ ] **Step 1: Write provider fallback tests**

Add fake health snapshots for Codex ready, OpenCode ready, OpenCode auth/config/model unavailable, OpenCode timeout, and unknown unavailable. Expected: OpenCode unavailable creates a bounded fallback cause and selects Codex without marking the lane execution failed.

- [ ] **Step 2: Wire health-aware policy**

Make `ProviderPolicyService.select_worker` require and consume `health_by_profile` for low-cost OpenCode selection. If OpenCode is not healthy, return Codex worker with `fallback_cause` and an evidence ref/record id.

- [ ] **Step 3: Persist selection records**

Selection records must include selected profile, task capability, risk tier, fallback cause, generated_at, source authority, health failure kind, and bounded diagnostics ref. Do not write provider health diagnostics into projection rows.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_models.py tests/xmuse/test_provider_opencode.py tests/xmuse/test_run_health.py -q
```

Expected: health-aware selection and fallback evidence pass with fake providers.

## Task P0D: Evidence Bundle Guard And Takeover Contract

**Files:**
- Modify: `src/xmuse_core/platform/lane_takeover.py`
- Modify: `src/xmuse_core/platform/lane_context.py`
- Modify: `src/xmuse_core/platform/takeover_actions.py`
- Modify: `src/xmuse_core/structuring/models.py`
- Test: `tests/xmuse/test_lane_takeover.py`
- Test: `tests/xmuse/test_takeover_actions.py`
- Test: `tests/xmuse/test_takeover_contracts.py`

- [ ] **Step 1: Write hash/revision guard tests**

Add tests that reject takeover decisions when `evidence_bundle_hash`, `projection_revision`, `lane_context_hash`, `lane_status`, or `lease_id` is missing or mismatched. Missing evidence must produce escalation metadata, never a mutation.

- [ ] **Step 2: Add guard fields**

Extend takeover context/evidence models with `takeover_attempt_id`, `lease_owner`, `lease_expires_at`, `projection_revision`, `lane_status`, `lane_context_hash`, `evidence_bundle_id`, `evidence_bundle_hash`, `graph_set_id`, `feature_plan_id`, and `max_attempts_by_reason`.

- [ ] **Step 3: Enforce guarded apply**

Update `apply_takeover_decision` path so every mutating takeover action requires matching guard fields, including `repair_and_merge`, `requeue_with_context`, `abandon_lane`, `self_correction_then_abandon`, and any escalation metadata write that touches lane state. `requeue_with_context` must have bounded attempt cap and cooldown.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_lane_takeover.py tests/xmuse/test_takeover_actions.py tests/xmuse/test_takeover_contracts.py -q
```

Expected: mismatch cases escalate; valid guarded decisions apply.

## Task P0E: Single Writer, Dispatch CAS, Merge Lock, Real Run Health

**Files:**
- Create: `src/xmuse_core/platform/runner_writer_lease.py`
- Create: `src/xmuse_core/platform/merge_lock.py`
- Modify: `xmuse/platform_runner.py`
- Modify: `src/xmuse_core/platform/orchestrator.py`
- Modify: `src/xmuse_core/platform/run_health.py`
- Modify: `src/xmuse_core/platform/read_contracts.py`
- Test: `tests/xmuse/test_platform_runner.py`
- Test: `tests/xmuse/test_platform_orchestrator.py`
- Test: `tests/xmuse/test_run_health.py`
- Test: `tests/xmuse/test_merge_safety_guard.py`

- [ ] **Step 1: Write single-writer and merge-lock tests**

Add tests proving a second enforce runner cannot write to the same projection, dispatch writes include `dispatch_attempt_id`, `runner_id`, and projection revision guard, stale writer lease reclaim/rejection works, and concurrent merge attempts serialize on target branch lock while revalidating reviewed base/target HEAD under the lock.

- [ ] **Step 2: Implement runner writer lease**

Create a file-backed lease under `xmuse/runtime/runner_writer_lease.json` or equivalent runtime path with `runner_id`, `writer_lease_id`, heartbeat, and expires_at. Enforce mode refuses writes when lease is held by another live runner.

- [ ] **Step 3: Implement merge lock**

Create target-branch merge lock with timeout, owner, and stale cleanup. `auto_merge` and takeover `repair_and_merge` must capture reviewed `base_head_sha`/`target_head_sha`, acquire the target-branch lock before checkout/merge, re-read target HEAD under the lock, and abort/escalate if the target advanced before releasing after success/failure.

- [ ] **Step 4: Use real process discovery in run health**

`read_run_health` must support real writer-capable process discovery and expose duplicate/stale runner, MCP mutators, dashboard/chat APIs, legacy `master_loop.py`/`xmuse_main.py`/`overnight_runner.sh`, legacy scheduler/monitor and master writer paths (`scheduler_monitor.sh`, `start_scheduler_monitor.sh`, `god_launcher.sh`, `multi_lane_dispatcher.py`, `master_review_runner.py`, `integrated_test_runner.py`, `master_merge_runner.py`), persistent GOD shims, and repo-local Codex/OpenCode workers as hard failure or explicit degraded evidence.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_platform_runner.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_run_health.py tests/xmuse/test_merge_safety_guard.py -q
```

Expected: single-writer, CAS, merge lock, and real run-health tests pass.

## Task R1: Native Runtime Facade

**Files:**
- Create: `src/xmuse_core/platform/runtime_facade.py`
- Create: `src/xmuse_core/platform/runtime_health.py`
- Modify: `src/xmuse_core/agents/god_session_layer.py`
- Test: `tests/xmuse/test_persistent_cli_peer.py`
- Test: `tests/xmuse/test_god_session_layer.py`
- Test: `tests/xmuse/test_platform_runner.py`

- [ ] **Step 1: Write facade tests**

Tests should create a native persistent peer handle, route execute/review/takeover request envelopes, and report runtime health without Ray installed.

- [ ] **Step 2: Implement native backend**

Define `PeerRuntimeBackend`, `PeerSessionHandle`, `RuntimeDispatchFacade`, and native backend over existing session layer/subprocess abstractions.

- [ ] **Step 3: Add Ray shadow placeholder without dependency**

Add `RayRuntimeBackendUnavailable` health evidence path using import-gated detection only. Do not add `ray` to `pyproject.toml` in this task.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_god_session_layer.py tests/xmuse/test_platform_runner.py -q
```

Expected: native facade works and Ray absence does not fail A-lite.

## Task R2a: Provider Health-Aware Selection In Runner

**Files:**
- Modify: `src/xmuse_core/providers/service.py`
- Modify: `src/xmuse_core/platform/orchestrator.py`
- Modify: `xmuse/platform_runner.py`
- Test: `tests/xmuse/test_provider_policy.py`
- Test: `tests/xmuse/test_platform_orchestrator.py`

- [ ] **Step 1: Write runner selection tests**

Add tests that pass OpenCode ready/unavailable fake health into runner provider service and assert correct selection/fallback record without lane failure.

- [ ] **Step 2: Wire health into runner provider service**

Provider service must receive health snapshots, call policy with `health_by_profile`, persist selection record, and pass only bounded refs to lane metadata.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_provider_policy.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_run_health.py -q
```

Expected: selection record and fallback evidence are generated before dispatch.

## Task M0: Execution Model Tier Policy

**Files:**
- Modify: `src/xmuse_core/providers/registry.py`
- Modify: `src/xmuse_core/providers/policy.py`
- Modify: `src/xmuse_core/providers/models.py`
- Modify: `src/xmuse_core/platform/model_policy.py`
- Modify: `src/xmuse_core/platform/execution/review_god.py`
- Modify: `src/xmuse_core/platform/execution/executor.py`
- Modify: `src/xmuse_core/platform/run_health.py`
- Modify: `src/xmuse_core/agents/launchers/codex.py`
- Modify: `src/xmuse_core/agents/codex_persistent.py`
- Modify: `src/xmuse_core/chat/driver.py`
- Modify: `src/xmuse_core/chat/participant_store.py`
- Modify: `src/xmuse_core/chat/peer_service.py`
- Modify: `src/xmuse_core/platform/agent_spawner.py`
- Modify: `xmuse/platform_runner.py`
- Test: `tests/xmuse/test_model_policy.py`
- Test: `tests/xmuse/test_provider_policy.py`
- Test: `tests/xmuse/test_chat_driver.py`
- Test: `tests/xmuse/test_chat_participant_store.py`
- Test: `tests/xmuse/test_peer_chat_service.py`
- Test: `tests/xmuse/test_platform_agent_spawner.py`

- [ ] **Step 1: Write model-tier policy tests**

Tests must prove gpt-5.5 is selected only for a first-class merge/final quality role or explicit final quality gate. Ordinary planning, ordinary review, chat-driver replies, coordination, lane workers, and rework workers select gpt-5.4 unless OpenCode DeepSeek V4 Flash is healthy and the task is bounded low-risk. Tests must cover legacy defaults in `CodexModelPolicy`, `CodexLauncher`, `codex_persistent`, `chat_driver_model`, participant store read-normalization, peer-service review/execute provisioning, `agent_spawner` fallback defaults, runner CLI defaults, persistent review fallback defaults, executor worker defaults, and run-health model-policy summaries.

- [ ] **Step 2: Add final-quality role/capability**

Add a machine-checkable provider role/task concept such as `FINAL_ACTION_QUALITY` or `MERGE_FINAL_REVIEW`. This role is the only normal gpt-5.5 exception. Do not encode the exception as free-form prompt text or an ad hoc `if role == "review"` branch.

- [ ] **Step 3: Implement model-tier policy**

Centralize tier rules in provider/model policy. Runner CLI, chat-driver, participant store, peer service, and agent-spawner defaults must use gpt-5.4 for ordinary coordinator/review/worker/chat roles. The final merge/final-action quality GOD remains gpt-5.5 through the first-class final-quality role only. OpenCode DeepSeek V4 Flash is eligible only for `BOUNDED_CODE_WRITING` and only with ready health evidence. Retire `CodexModelPolicy` or make it a thin compatibility adapter over provider policy so old `gpt-5.5` ordinary-role defaults cannot leak back in through launchers, chat-driver, participant read-normalization, peer provisioning, agent spawner, or persistent shims. In particular, `participant_store._read_model` must not rewrite gpt-5.4 to gpt-5.5.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_model_policy.py tests/xmuse/test_provider_policy.py tests/xmuse/test_platform_runner.py tests/xmuse/test_run_health.py tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_chat_driver.py tests/xmuse/test_chat_participant_store.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_platform_agent_spawner.py -q
```

Expected: model selection evidence proves the cost policy and never promotes OpenCode into GOD/review/takeover roles.

## Task R2b: OpenCode Provider-Native Bounded Worker

**Files:**
- Modify: `src/xmuse_core/providers/service.py`
- Modify: `src/xmuse_core/providers/adapters/opencode.py`
- Modify: `src/xmuse_core/platform/agent_spawner.py`
- Modify: `src/xmuse_core/platform/orchestrator.py`
- Modify: `src/xmuse_core/platform/execution/executor.py`
- Test: `tests/xmuse/test_provider_opencode.py`
- Test: `tests/xmuse/test_platform_agent_spawner.py`
- Test: `tests/xmuse/test_platform_orchestrator.py`
- Test: `tests/xmuse/test_execution_child_worker.py`

- [ ] **Step 1: Write worker-transport contract tests**

Add tests proving OpenCode low-risk worker uses a `BOUNDED_CODE_WRITING` worker transport contract, does not pass through Codex-only `runtime_for_invocation`, does not reuse `LANE_COORDINATION` as the worker invocation type, and does not persist raw argv/prompt in projection.

- [ ] **Step 2: Implement orchestrator worker invocation contract**

Add an orchestrator-level worker invocation path separate from GOD/coordinator/review runtime mapping. This path may build provider-native worker invocations for OpenCode and Codex fallback, but it must not alias `opencode` to `codex`.

- [ ] **Step 3: Implement OpenCode bounded worker path**

Introduce provider-native one-shot worker invocation/result handling. GOD/review/takeover roles remain Codex. OpenCode unavailable falls back before dispatch.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_provider_opencode.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_execution_child_worker.py tests/xmuse/test_lane_projection_syncer.py -q
```

Expected: OpenCode ready/unavailable paths are deterministic with fake health and projection stays clean.

## Task R3: Runner Bridge, Lease, CAS, Merge Lock

**Files:**
- Modify: `xmuse/platform_runner.py`
- Modify: `src/xmuse_core/platform/orchestrator.py`
- Modify: `src/xmuse_core/platform/execution/merger.py`
- Modify: `src/xmuse_core/platform/runtime_facade.py`
- Test: `tests/xmuse/test_platform_runner.py`
- Test: `tests/xmuse/test_platform_orchestrator.py`
- Test: `tests/test_review_plane_merge_safety.py`

- [ ] **Step 1: Write bridge tests**

Tests must prove runner acquires writer lease, dispatches through facade after provider/model policy is available, writes CAS metadata, uses merge lock, rejects stale writer attempts after a lease is reclaimed by another runner, and revalidates reviewed `base_head_sha`/`target_head_sha` under lock before both `auto_merge` and takeover `repair_and_merge`.

- [ ] **Step 2: Implement bridge**

Route execute/review/takeover request creation through `RuntimeDispatchFacade` while preserving existing `PlatformOrchestrator` and `LaneStateMachine` authority. All projection, takeover, and merge writes must carry and validate the active `writer_lease_id`; stale owners must be rejected with audited evidence.

- [ ] **Step 3: Add target-head merge guards**

Record target branch and reviewed base/target head evidence before merge. Under merge lock, re-read target HEAD and refuse `auto_merge` or `repair_and_merge` when the target branch has advanced until context/evidence is refreshed.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_platform_runner.py tests/xmuse/test_platform_orchestrator.py tests/test_review_plane_merge_safety.py tests/xmuse/test_merge_safety_guard.py -q
```

Expected: current runner path still works and duplicate writer/merge cases are guarded.

## Task R4a: Takeover Classifier And Shadow Read Model

**Files:**
- Modify: `src/xmuse_core/platform/autotakeover/classifier.py`
- Modify: `src/xmuse_core/platform/lane_takeover.py`
- Modify: `src/xmuse_core/platform/read_contracts.py`
- Test: `tests/xmuse/test_autotakeover_classifier.py`
- Test: `tests/xmuse/test_lane_takeover.py`
- Test: `tests/xmuse/test_run_health.py`

- [ ] **Step 1: Write shadow candidate tests**

Add cases for failed, gate_failed, exec_failed, stale worker, merge conflict, review no verdict, provider unavailable, retry exhausted, and prompt mismatch. Expected: candidate read model emits evidence refs without mutating status.

- [ ] **Step 2: Implement shadow candidate read model**

Expose bounded candidate summaries with takeover reason, refs, provider selection refs, real run-health refs, and required guard fields. This feature depends on P0C/P0E because provider-unavailable and stale-worker evidence must not be guessed from lane status alone.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_autotakeover_classifier.py tests/xmuse/test_lane_takeover.py tests/xmuse/test_run_health.py -q
```

Expected: candidate summaries are complete and read-only.

## Task T1: Textual Worklist Read Envelopes

**Files:**
- Create: `src/xmuse_core/platform/read_envelopes.py`
- Modify: `src/xmuse_core/platform/read_contracts.py`
- Modify: `xmuse/dashboard_api.py`
- Modify: `xmuse/tui/adapter/xmuse_adapter.py`
- Modify: `xmuse/FRONTEND_API.md`
- Test: `tests/xmuse/test_tui_adapter.py`
- Test: `tests/xmuse/test_dashboard_api.py`
- Test: `tests/xmuse/test_run_health.py`

- [ ] **Step 1: Write envelope tests**

Tests must prove `GET /api/tui/worklist-envelope` returns a versioned envelope with `schema_version`, `source_authority`, `projection_revision`, `generated_at`, `items`, `run_health`, `provider_selection_refs`, `degradation`, `runtime_backend`, `fallback_reason`, `read_model_version`, and `debug_refs`. Each `items[]` entry is compact and explicitly typed: `lane_id`, `lane_local_id`, `plan_feature_id`, compact feature label, effective status, ready/blocked/rework state, scoped dependency ids, priority, provider-selection ref, debug refs, and `prompt_summary`; raw prompt, raw argv, stdout/stderr, or provider diagnostics are not item fields. Tests must also prove `conversation_id` and `workspace_id` query params are applied server-side, with source-authority/degradation evidence when projection and graph lineage disagree.

- [ ] **Step 2: Implement envelopes**

Textual-facing adapter must consume `GET /api/tui/worklist-envelope`, not raw projection. Legacy `/api/lanes` remains debug/drill-down. `xmuse/tui/adapter/xmuse_adapter.py` must stop polling `feature_lanes.json` directly after this feature lands. The endpoint owns conversation/workspace scoping so the TUI does not filter multi-conversation worklists client-side.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_dashboard_api.py tests/xmuse/test_run_health.py -q
```

Expected: TUI/worklist paths no longer rely on raw lane shape and the endpoint schema is pinned for Textual.

## Task R4b: Review GOD Autotakeover Enforce Loop

**Files:**
- Create: `src/xmuse_core/platform/autotakeover/review_god_loop.py`
- Modify: `xmuse/platform_runner.py`
- Modify: `src/xmuse_core/platform/orchestrator.py`
- Modify: `src/xmuse_core/platform/takeover_actions.py`
- Test: `tests/xmuse/test_autotakeover_classifier.py`
- Test: `tests/xmuse/test_takeover_actions.py`
- Test: `tests/xmuse/test_platform_runner.py`

- [ ] **Step 1: Write enforce loop tests**

Add controlled failed/gate_failed lane tests where runner tick scans candidate, acquires takeover lease, requests Review GOD decision, validates guard, applies requeue/repair/escalation, and records run-health evidence. Outer GOD may mutate only from accepted escalation refs; ordinary failures remain Review GOD-owned.

- [ ] **Step 2: Implement enforce loop**

Implement `ReviewGodAutotakeoverLoop` with shadow/enforce mode, single-flight lease, request id, cooldown, max attempts, canonical action names, and explicit escalation records. Outer GOD intervention must be read-only unless an accepted escalation record authorizes mutation.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_autotakeover_classifier.py tests/xmuse/test_takeover_actions.py tests/xmuse/test_platform_runner.py tests/xmuse/test_run_health.py -q
```

Expected: controlled failed lane is handled without ordinary `outer_god_*` metadata; outer GOD mutation is rejected unless a validated accepted-escalation ref exists.

## Task R5: A-lite Non-Demo Gate

**Files:**
- Create: `tests/xmuse/test_runtime_first_e2e.py`
- Create: `xmuse/work/smoke_runtime_first_alite.py`
- Modify: `xmuse/platform_runner.py`
- Test: `tests/xmuse/test_runtime_first_e2e.py`

- [ ] **Step 1: Write E2E gate tests**

Cover the full A-lite hard gate: native runtime without Ray, Ray import/startup fallback as shadow evidence only, projection allowlist, single-writer lease, merge lock and base/target head guards, Codex execute/review/merge, OpenCode ready/unavailable fallback, Review GOD takeover without ordinary outer-GOD mutation, shared evidence-bundle id/hash/projection-revision/lane-context/status-guard/lease lineage, concurrent takeover single lease, real writer-process discovery, `takeover_context_needed=0` unless accepted escalation exists, complete graph-set lineage fields, and Textual envelope evidence.

- [ ] **Step 2: Implement smoke script**

`xmuse/work/smoke_runtime_first_alite.py` must produce a JSON report with one boolean/ref entry per A-lite hard-gate item in the blueprint. It must not start multiple runners. The gate fails if `takeover_context_needed` is nonzero without accepted escalation, ordinary `outer_god_*` traces exist, writer-process discovery is fake or narrower than injection quiescence, evidence-bundle/lease/status lineage is missing, Ray blocks A-lite, provider fallback evidence is absent, or graph-set lineage fields are incomplete.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_runtime_first_e2e.py -q
uv run python xmuse/work/smoke_runtime_first_alite.py
uv run python xmuse/platform_runner.py --health-once --lanes xmuse/feature_lanes.json
```

Expected: A-lite hard gates pass or produce explicit bounded unavailable evidence for external providers.

## Task F1: Init GOD Fork Model

**Files:**
- Modify: `src/xmuse_core/agents/persistent_peer.py`
- Modify: `src/xmuse_core/agents/god_session_layer.py`
- Test: `tests/xmuse/test_peer_forks.py`

- [ ] **Step 1: Write fork model tests**

Test init GOD forks peers with conversation/workspace/provider/profile identity and incremental role prompts.

- [ ] **Step 2: Implement fork model**

Use native runtime facade and existing session layer. Do not add Ray dependency.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_peer_forks.py tests/xmuse/test_god_session_layer.py -q
```

## Task F2a: Workflow Backend Interface And Trace

**Files:**
- Create: `src/xmuse_core/structuring/workflow_backend.py`
- Modify: `src/xmuse_core/structuring/blueprint_execution/*`
- Test: `tests/xmuse/test_blueprint_execution_service.py`

- [ ] **Step 1: Write native workflow trace tests**

Test blueprint approval, feature planning, graph generation, projection injection, monitor, and gap review emit replayable command/event/artifact refs.

- [ ] **Step 2: Implement interface and native trace sink**

LangGraph is not imported in this task. The interface must be backend-neutral.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_blueprint_execution_service.py tests/xmuse/test_planning_event_store.py -q
```

## Task F3a: Graph-Native Ready-Set Parity

**Files:**
- Create: `src/xmuse_core/structuring/ready_set.py`
- Modify: `xmuse/platform_runner.py`
- Test: `tests/xmuse/test_feature_graph_projection.py`
- Test: `tests/xmuse/test_platform_runner.py`

- [ ] **Step 1: Write parity tests**

Given the same graph set and projection, graph-native ready-set and current projection candidate selection must return equivalent ready lane ids.

- [ ] **Step 2: Implement ready-set read model**

Do not cut over runner source yet. Produce parity evidence only.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_platform_runner.py -q
```

## Task F2b: LangGraph Shadow Replay

**Files:**
- Create: `src/xmuse_core/structuring/langgraph_adapter.py`
- Modify: `pyproject.toml` only if existing `langgraph` dependency is missing
- Test: `tests/xmuse/test_blueprint_execution_service.py`

- [ ] **Step 1: Write shadow replay tests**

Test LangGraph adapter replays native workflow trace and produces equivalent artifact refs. It must not write lane status directly.

- [ ] **Step 2: Implement adapter**

Use existing `langgraph` dependency. Durable state remains xmuse stores.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_blueprint_execution_service.py -q
```

## Task F3b: Candidate Source Flag Cutover

**Files:**
- Modify: `xmuse/platform_runner.py`
- Modify: `src/xmuse_core/structuring/ready_set.py`
- Test: `tests/xmuse/test_platform_runner.py`

- [ ] **Step 1: Write cutover/rollback tests**

Test flag switching between projection candidates and graph-native ready-set without losing state.

- [ ] **Step 2: Implement flag**

Add candidate source flag with default legacy projection source until F3b is explicitly enabled.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_platform_runner.py tests/xmuse/test_feature_graph_projection.py -q
```

## Task F4: Optional Ray Actor Backend

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/xmuse_core/platform/ray_backend.py`
- Modify: `src/xmuse_core/platform/runtime_facade.py`
- Test: `tests/xmuse/test_runtime_ray_backend.py`

- [ ] **Step 1: Add Ray optional dependency**

Run during F4 implementation only:

```bash
uv add --optional ray "ray[default]"
uv lock
```

Expected: `pyproject.toml` gains a `ray` optional dependency group and `uv.lock` resolves Ray. If `uv add` syntax differs in the installed uv version, use `uv add --help` and keep Ray optional rather than a required project dependency.

- [ ] **Step 2: Write fake-backed Ray tests**

Tests must pass without starting a real cluster by using fake actor handles. Real Ray startup smoke is optional and skipped when Ray is unavailable.

- [ ] **Step 3: Implement import-gated backend**

Ray import/startup failure returns runtime health degraded evidence and falls back native.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_runtime_ray_backend.py tests/xmuse/test_platform_runner.py -q
```

Expected: fake-backed tests pass; real Ray smoke is skipped or records bounded unavailable evidence.

## Task F5a: Native Multi-Feature Scheduling

**Files:**
- Modify: `xmuse/platform_runner.py`
- Modify: `src/xmuse_core/structuring/ready_set.py`
- Modify: `src/xmuse_core/providers/policy.py`
- Test: `tests/xmuse/test_platform_runner.py`
- Test: `tests/xmuse/test_feature_graph_projection.py`

- [ ] **Step 1: Write multi-feature scheduling tests**

Test one runner releases ready lanes from multiple independent feature graph sets while respecting feature DAG, lane DAG, provider budget, writer lease, and merge lock.

- [ ] **Step 2: Implement scheduler**

Keep one runner process. Increase parallelism through ready-set selection and provider backpressure.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_platform_runner.py tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_provider_policy.py -q
```

## Task F5b: Actor Multi-Feature Scheduling

**Files:**
- Modify: `src/xmuse_core/platform/ray_backend.py`
- Modify: `src/xmuse_core/platform/runtime_facade.py`
- Test: `tests/xmuse/test_runtime_ray_backend.py`

- [ ] **Step 1: Write actor scheduling tests**

Test actor/session group scheduling respects provider budget, writer lease, merge lock, and native fallback on actor crash.

- [ ] **Step 2: Implement actor scheduling**

Only enabled when Ray backend is healthy and flag is on.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_runtime_ray_backend.py tests/xmuse/test_platform_runner.py -q
```

## Task F6: Full Textual Peer Workbench Contracts

**Files:**
- Modify: `xmuse/tui/adapter/xmuse_adapter.py`
- Modify: `xmuse/tui/screens/*`
- Modify: `src/xmuse_core/platform/read_envelopes.py`
- Test: `tests/xmuse/test_tui_adapter.py`
- Test: `tests/xmuse/test_tui_navigation.py`

- [ ] **Step 1: Write workbench contract tests**

Test chat/worklist/drill-down flows use compact cards and read envelopes, not raw dashboard-first lane dumps.

- [ ] **Step 2: Implement TUI contract consumption**

Keep UI terminal-first. Do not implement browser frontend.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_navigation.py -q
```

## Graph Review And Injection Procedure

1. Generate graph preview:

```bash
uv run python xmuse/work/generate_runtime_first_graph_set.py
```

2. Run gpt-5.4 subagent reviews against this plan and generator:

```bash
codex exec -m gpt-5.4 -s read-only -C /home/iiyatu/projects/python/memoryOS -o .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-results/runtime-provider.md < .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-prompts/runtime-provider.md
codex exec -m gpt-5.4 -s read-only -C /home/iiyatu/projects/python/memoryOS -o .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-results/projection-workflow.md < .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-prompts/projection-workflow.md
codex exec -m gpt-5.4 -s read-only -C /home/iiyatu/projects/python/memoryOS -o .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-results/reliability-rollout.md < .superpowers/brainstorm/20260601-runtime-first-plan-review/subagent-prompts/reliability-rollout.md
```

3. If any review returns `block`, revise this plan and generator before injection.

   Review is a gate, not an infinite loop. After the known block items are fixed,
   run one focused re-check for the changed surface; if it finds no hard blocker,
   proceed to cleanup and injection instead of repeating broad reviews.

4. After reviews pass, use a quiesced, non-destructive injection flow. It must refuse to write when any writer-capable xmuse runtime is live, including runner, MCP mutators, dashboard/chat APIs, persistent GOD shims, repo-local worker CLIs, and the legacy scheduler/supervisor/master paths (`scheduler_monitor.sh`, `start_scheduler_monitor.sh`, `god_launcher.sh`, `multi_lane_dispatcher.py`, `master_review_runner.py`, `integrated_test_runner.py`, `master_merge_runner.py`). It snapshots runtime state, including `xmuse/master/`, `xmuse/work/features/`, and `xmuse/approvals/` when present, writes the graph set first, then performs one atomic projection transaction that quarantines legacy rows into the archived snapshot/superseded artifact and leaves only sanitized current root lanes in the active `lanes` array. The quarantine manifest must record removed lane id, prior status, superseded timestamp, reason, and whether manual requeue review is required. Root lanes must include compact `prompt`, `prompt_summary`, `prompt_ref`, `raw_debug_ref`, `command_hash`, `lane_id`, `lane_local_id`, `plan_feature_id`, `graph_id`, scoped `depends_on`, `graph_set_id`, `graph_set_version`, `feature_plan_id`, `feature_plan_version`, `projection_revision`, and `projection_source`:

```bash
uv run python xmuse/work/generate_runtime_first_graph_set.py --require-no-runner --archive-runtime-state --mark-existing-superseded --write --project-roots
```

5. `--project-roots` must not write raw full prompts into live projection rows. Full prompts are stored as bounded prompt artifacts under `xmuse/work/runtime_first_prompts/`, and live rows carry only a compact bootstrap prompt plus refs. `--project-roots` and `--mark-existing-superseded` are coupled intentionally; projection injection must save the graph-set artifact and then update the live projection in one transaction.

   Runtime dependent projection must preserve the same contract as root
   injection: use `project_feature_graph_set_ready_lanes`, write compact prompt
   refs and lineage fields, prefer the triggering lane's `graph_set_id` over
   sorted graph matches, and never reproject raw prompts or stale graph-set
   versions into the live queue.

6. After `--project-roots`, start or restart only the single runner. Keep legacy monitor/supervisor/master paths stopped; do not run `scheduler_monitor.sh`, `start_scheduler_monitor.sh`, `god_launcher.sh`, `multi_lane_dispatcher.py`, `master_review_runner.py`, `integrated_test_runner.py`, or `master_merge_runner.py` during this runtime-first goal. Keep dashboard/MCP lane-mutation surfaces disabled or read-only until `P0A-03` lands; dashboard/debug reads are allowed, but ad hoc lane creation must not bypass the sanitized graph-set path.

7. Outer GOD ops contract during this goal: perform one read-only sweep every 20 minutes, not continuous high-frequency polling. Mutate only from a validated accepted-escalation ref, respect bounded per-lane cooldown, and restart the single runner only to enable newly merged runtime safety or to resolve duplicate-writer/stale-lease evidence.

## Post-Injection Operating Mode

Until `P0A-03` and `P0E-03` are merged, operate in a deliberately narrow mode:

- Exactly one `xmuse/platform_runner.py` may run.
- Legacy monitor/supervisor/master scripts remain stopped even if queues appear.
- Dashboard/MCP/chat APIs may serve reads only; lane creation or projection mutation paths stay disabled/read-only unless routed through the sanitized graph-set projection path.
- Outer GOD is the only restart authority during the 20-minute monitoring contract and may restart only to enable newly merged safety code or clear duplicate-writer/stale-lease evidence.
- The active queue is the sanitized root projection only; archived legacy lanes require manual requeue review using the quarantine manifest.
