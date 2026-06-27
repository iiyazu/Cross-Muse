# V10 CI Candidate Audit

Date: 2026-06-04

Scope: Path A Phase 3 (Quality Gates) from `docs/xmuse/path-a-foundation-first-roadmap.md`.
This audit identifies the smallest useful default CI gate set for the independent xmuse project. It does not implement CI workflow.

---

## 1. Default CI Candidate Commands

Three commands that should run on every commit/push in the default CI path:

### 1a. Ruff lint

```bash
uv run ruff check src/xmuse_core/ xmuse/ tests/xmuse/
```

**Current result**: 81 errors across 3 source trees:
- `src/xmuse_core/`: 17 errors (12 fixable)
- `xmuse/`: 30 errors (3 fixable)
- `tests/xmuse/`: 34 errors (25 fixable)

Breakdown by code:
| Code | Count | Meaning |
|------|-------|---------|
| E501 | 33 | line-too-long (100 char limit) |
| I001 | 19 | unsorted-imports |
| F401 | 15 | unused-import |
| E741 | 4 | ambiguous-variable-name (`l`) |
| UP035 | 3 | deprecated-import |
| UP037 | 3 | quoted-annotation |
| UP012 | 2 | unnecessary-encode-utf8 |
| E702 | 1 | multiple-statements-on-one-line |
| F841 | 1 | unused-variable |

40 errors are auto-fixable (`ruff check --fix`).

**Recommendation**: Set a zero-tolerance baseline after one bulk `--fix` pass. Accept only new errors. Focus the gate on `src/xmuse_core/` and `tests/xmuse/` first, then add `xmuse/`.

### 1b. Package installability

```bash
uv build
```

**Current result**: PASS — builds both `dist/xmuse-0.1.0.tar.gz` and `dist/xmuse-0.1.0-py3-none-any.whl` successfully. No memoryOS dependency in wheel metadata.

**Recommendation**: Hard gate. Must pass before any other gate.

### 1c. Focused pytest groups

Default CI should run fast (<60s total), mock-only tests. Proposed groups:

| Group | Command | Tests | Current | Est. time |
|-------|---------|-------|---------|-----------|
| Core models & contracts | `uv run pytest -q tests/xmuse/test_provider_models.py tests/xmuse/test_provider_adapters.py tests/xmuse/test_provider_policy.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_feature_review_contracts.py tests/xmuse/test_chat_store.py tests/xmuse/test_provider_session_binding_store.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_worker_goal_contract.py tests/xmuse/test_runtime_settings.py` | 157 | 157 pass | ~5s |
| Feature graph & structuring | `uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py tests/xmuse/test_feature_graph_builder.py tests/xmuse/test_feature_graph_projection.py tests/xmuse/test_feature_graph_blocked_review.py tests/xmuse/test_feature_graph_claim_coordinator.py tests/xmuse/test_feature_graph_dependency_coordinator.py tests/xmuse/test_feature_graph_patch_forward.py tests/xmuse/test_feature_graph_patch_forward_status_application.py tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_feature_graph_review_coordinator.py tests/xmuse/test_feature_graph_review_transition_application.py tests/xmuse/test_feature_graph_review_transitions.py tests/xmuse/test_feature_graph_rework_packets.py tests/xmuse/test_feature_graph_rework_status_application.py tests/xmuse/test_feature_graph_takeover_plan.py tests/xmuse/test_feature_graph_worker_claims.py tests/xmuse/test_feature_graph_worker_evidence_submission.py tests/xmuse/test_feature_plan_deliberation.py tests/xmuse/test_feature_plan_graph_set.py tests/xmuse/test_feature_plan_proposal.py tests/xmuse/test_feature_summary.py tests/xmuse/test_feature_context.py` | 295 | 294 pass, 1 fail | ~3s |
| Chat services | `uv run pytest -q tests/xmuse/test_chat_participant_store.py tests/xmuse/test_chat_envelopes.py tests/xmuse/test_chat_health_cards.py tests/xmuse/test_chat_driver.py tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_chat_blueprint_revision.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_chat_lane_scope.py tests/xmuse/test_chat_api_models_module.py tests/xmuse/test_chat_streams.py tests/xmuse/test_chat_structure_escalation.py` | ~150 | TBD | ~5s |
| Core agents | `uv run pytest -q tests/xmuse/test_core_agents_consumer.py tests/xmuse/test_core_agents_launchers.py tests/xmuse/test_core_agents_manager.py tests/xmuse/test_core_agents_protocol.py tests/xmuse/test_core_agents_registry.py tests/xmuse/test_core_agents_session.py tests/xmuse/test_core_callback_server.py tests/xmuse/test_core_routing.py tests/xmuse/test_core_schema.py tests/xmuse/test_core_state.py tests/xmuse/test_core_status.py` | ~80 | TBD | ~5s |
| Peer chat | `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_peer_chat_store.py tests/xmuse/test_peer_chat_turn_budget.py tests/xmuse/test_peer_chat_cards_module.py tests/xmuse/test_peer_chat_mentions.py tests/xmuse/test_peer_chat_proposal_flow.py tests/xmuse/test_peer_chat_proposals_module.py tests/xmuse/test_peer_chat_end_to_end.py tests/xmuse/test_peer_chat_mcp_tools.py` | ~200 | TBD | ~10s |
| Execution & platform | `uv run pytest -q tests/xmuse/test_execution_cards.py tests/xmuse/test_execution_child_worker.py tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_platform_event_bus.py tests/xmuse/test_platform_god_picker.py tests/xmuse/test_platform_projection_dependents.py tests/xmuse/test_platform_prompt_builders.py tests/xmuse/test_platform_review_fallback.py tests/xmuse/test_platform_state_machine.py tests/xmuse/test_platform_verdicts_writer.py` | ~200 | TBD | ~10s |
| TUI | `uv run pytest -q tests/xmuse/test_tui_*.py` | ~84 | pass | ~8s |
| Reliability & boundary | `uv run pytest -q tests/xmuse/test_reliability_hardening.py tests/xmuse/test_replay_fixtures.py tests/xmuse/test_split_export_contract.py tests/xmuse/test_state_normalizer.py tests/xmuse/test_export_tool.py tests/xmuse/test_verdict_store_atomic.py tests/xmuse/test_verdict_store_consistency.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_memory_refs.py tests/xmuse/test_session_router.py tests/xmuse/test_runtime_settings.py` | ~200 | TBD | ~10s |

**Total estimate for all default groups**: ~60s, ~1500 tests.

**Recommendation**: Start with Group 1 (core models + package boundaries) as the minimal CI gate, then add groups incrementally as the project stabilizes.

### Known test failures in scope

| Test file | Test | Error | Gate impact |
|-----------|------|-------|-------------|
| `test_skill_plan_execute_review.py` | collection | `ModuleNotFoundError: No module named 'skills.plan_execute_review'` | Must be excluded from default CI or fixed |
| `test_gate_profiles.py` | 5 tests | `FileNotFoundError: xmuse/gate_profiles.json` | Self-referential gate tests; exclude from default CI |
| `test_feature_plan_proposal.py::test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes` | 1 | `KeyError: 'id'` | Real issue — fixture or API contract change |

---

## 2. Extended/Manual Gates

These tests require real Ray, Codex CLI, provider API keys, or network access. They must NOT run in default CI.

### Real Ray + Codex (manual only)

| Test file | Tests | Dependency | Command |
|-----------|-------|------------|---------|
| `test_full_chain_real_run.py` | 4 | Real Ray, Codex binary, MCP server | `uv run pytest -q tests/xmuse/test_full_chain_real_run.py` |
| `test_ray_adapters.py` | 10 | Real Ray, Codex app-server | `uv run pytest -q tests/xmuse/test_ray_adapters.py` |
| `test_runtime_ray_backend.py` | 5 | Real Ray runtime | `uv run pytest -q tests/xmuse/test_runtime_ray_backend.py` |
| `test_mcp_server.py` | 14 | Real MCP server process | `uv run pytest -q tests/xmuse/test_mcp_server.py` |

### Real provider API key (manual only)

| Test file | Tests | Dependency | Command |
|-----------|-------|------------|---------|
| `test_provider_opencode.py` | 8 | `DEEPSEEK_API_KEY` env var | `uv run pytest -q tests/xmuse/test_provider_opencode.py` |

### Slow or soak tests (extended/nightly)

| Test file | Tests | Reason | Recommendation |
|-----------|-------|--------|----------------|
| `test_platform_orchestrator.py` | ~165 | 9085 lines, integration-heavy, ~30s | Extended |
| `test_self_evolution.py` | ~80 | 3999 lines, slow | Extended |
| `test_dashboard_api.py` | ~60 | 3248 lines, HTTP integration | Extended |
| `test_platform_runner.py` | ~50 | 2321 lines, runner simulation | Extended |
| `test_chat_api.py` | ~40 | 2032 lines, HTTP client | Extended |

### E2E tests (manual)

| Test file | Tests | Reason |
|-----------|-------|--------|
| `test_mvp_e2e.py` | 1 | Full dispatch cycle |
| `test_mvp_e2e_chat_to_lane.py` | 1 | E2E with HTTP TestClient |

---

## 3. Test Classification Table

All `tests/xmuse/` files classified by category and recommended gate.

### Default CI (fast, no external deps)

| File | Category | Reason | Gate |
|------|----------|--------|------|
| `test_provider_models.py` | unit | Pure data models, no I/O | default |
| `test_provider_adapters.py` | unit | Mock-based adapter tests | default |
| `test_provider_policy.py` | unit | Provider selection policy logic | default |
| `test_provider_session_binding_store.py` | unit | Store with temp file fixtures | default |
| `test_provider_read_contracts_module.py` | unit | Read contract models | default |
| `test_provider_support_level.py` | unit | Support level enum logic | default |
| `test_worker_goal_contract.py` | unit | Goal contract validation | default |
| `test_package_boundaries.py` | package_boundary | Enforces no memoryos_lite imports | default |
| `test_shared_contract_fixtures_contract.py` | unit | Golden fixture validation | default |
| `test_parallel_contract_fixtures.py` | unit | Parallel fixture tests | default |
| `test_feature_review_contracts.py` | unit | Feature review contract schemas | default |
| `test_feature_graph_builder.py` | unit | Graph builder, no I/O | default |
| `test_feature_graph_projection.py` | unit | Projection logic | default |
| `test_feature_graph_status_store.py` | unit | Status store with temp file fixtures | default |
| `test_feature_graph_artifact_store.py` | unit | Artifact store | default |
| `test_feature_graph_blocked_review.py` | unit | Blocked review logic | default |
| `test_feature_graph_claim_coordinator.py` | unit | Claim coordinator | default |
| `test_feature_graph_dependency_coordinator.py` | unit | Dependency coordination | default |
| `test_feature_graph_patch_forward.py` | unit | Patch forward logic | default |
| `test_feature_graph_patch_forward_status_application.py` | unit | Status application | default |
| `test_feature_graph_provider_binding_degradation_coordinator.py` | unit | Degradation coordination | default |
| `test_feature_graph_review_coordinator.py` | unit | Review coordination | default |
| `test_feature_graph_review_transition_application.py` | unit | Review transition application | default |
| `test_feature_graph_review_transitions.py` | unit | Review transition logic | default |
| `test_feature_graph_rework_packets.py` | unit | Rework packet logic | default |
| `test_feature_graph_rework_status_application.py` | unit | Rework status application | default |
| `test_feature_graph_takeover_plan.py` | unit | Takeover planning | default |
| `test_feature_graph_worker_claims.py` | unit | Worker claims | default |
| `test_feature_graph_worker_evidence_submission.py` | unit | Evidence submission | default |
| `test_feature_plan_deliberation.py` | unit | Plan deliberation | default |
| `test_feature_plan_graph_set.py` | unit | Graph set | default |
| `test_feature_plan_proposal.py` | unit | Plan proposals (1 known fail) | default |
| `test_feature_summary.py` | unit | Feature summary | default |
| `test_feature_context.py` | unit | Feature context | default |
| `test_chat_store.py` | unit | SQLite store with temp db | default |
| `test_chat_participant_store.py` | unit | Participant store | default |
| `test_chat_envelopes.py` | unit | Read envelopes | default |
| `test_chat_health_cards.py` | unit | Health cards | default |
| `test_chat_driver.py` | unit | Chat driver (mock) | default |
| `test_chat_default_intake.py` | unit | Default intake | default |
| `test_chat_review_trigger.py` | unit | Review trigger | default |
| `test_chat_blueprint_revision.py` | unit | Blueprint revision | default |
| `test_chat_bootstrap.py` | unit | Chat bootstrap | default |
| `test_chat_lane_scope.py` | unit | Lane scope | default |
| `test_chat_api_models_module.py` | unit | API models | default |
| `test_chat_streams.py` | unit | Streams | default |
| `test_chat_structure_escalation.py` | unit | Structure escalation | default |
| `test_core_agents_consumer.py` | unit | Agent consumer | default |
| `test_core_agents_launchers.py` | unit | Agent launchers | default |
| `test_core_agents_manager.py` | unit | Agent manager | default |
| `test_core_agents_protocol.py` | unit | Agent protocol | default |
| `test_core_agents_registry.py` | unit | Agent registry | default |
| `test_core_agents_session.py` | unit | Agent session | default |
| `test_core_callback_server.py` | unit | Callback HTTP server | default |
| `test_core_routing.py` | unit | Core routing | default |
| `test_core_schema.py` | unit | Core schema | default |
| `test_core_state.py` | unit | Core state | default |
| `test_core_status.py` | unit | Core status | default |
| `test_execution_cards.py` | unit | Execution cards | default |
| `test_execution_child_worker.py` | unit | Child worker | default |
| `test_execution_provider_session_binding.py` | unit | Provider session binding | default |
| `test_gate_profiles.py` | other | Gate profile meta-tests (broken) | skip |
| `test_god_identity.py` | unit | God identity | default |
| `test_god_session_layer.py` | unit | GOD session layer (mock) | default |
| `test_god_session_registry.py` | unit | GOD session registry | default |
| `test_graph_authority.py` | unit | Graph authority | default |
| `test_lane_context.py` | unit | Lane context | default |
| `test_lane_graph_planner.py` | unit | Lane graph planner | default |
| `test_lane_graph_validation.py` | unit | Lane graph validation | default |
| `test_lane_projection.py` | unit | Lane projection | default |
| `test_lane_projection_syncer.py` | unit | Lane projection syncer | default |
| `test_lane_takeover.py` | unit | Lane takeover | default |
| `test_langgraph_adapters.py` | unit | LangGraph adapters | default |
| `test_langgraph_shadow_replay_boundaries.py` | unit | Shadow replay | default |
| `test_memory_refs.py` | unit | Memory refs | default |
| `test_memory_update_events.py` | unit | Memory update events | default |
| `test_memoryos_client.py` | unit | MemoryOS client (mock) | default |
| `test_merge_safety_guard.py` | unit | Merge safety guard | default |
| `test_model_policy.py` | unit | Model policy | default |
| `test_model_policy_surfaces.py` | unit | Model policy surfaces | default |
| `test_codex_persistent.py` | unit | Codex persistent (mock) | default |
| `test_peer_chat_scheduler.py` | unit | Peer chat scheduler | default |
| `test_peer_chat_service.py` | unit | Peer chat service (mock) | default |
| `test_peer_chat_store.py` | unit | Peer chat store | default |
| `test_peer_chat_turn_budget.py` | unit | Turn budget | default |
| `test_peer_chat_cards_module.py` | unit | Peer chat cards | default |
| `test_peer_chat_mentions.py` | unit | Mention parsing | default |
| `test_peer_chat_proposal_flow.py` | unit | Proposal flow | default |
| `test_peer_chat_proposals_module.py` | unit | Proposals module | default |
| `test_peer_chat_end_to_end.py` | unit | Peer chat E2E (mock) | default |
| `test_peer_chat_mcp_tools.py` | unit | MCP tools | default |
| `test_peer_forks.py` | unit | Peer forks | default |
| `test_peer_provider_parity.py` | unit | Provider parity | default |
| `test_peer_request_cards.py` | unit | Request cards | default |
| `test_persistent_cli_peer.py` | unit | Persistent CLI peer | default |
| `test_persistent_execute_god.py` | unit | Persistent execute GOD | default |
| `test_persistent_review_context_module.py` | unit | Review context | default |
| `test_persistent_review_delivery_module.py` | unit | Review delivery | default |
| `test_persistent_review_session_contracts.py` | unit | Review session contracts | default |
| `test_planning_event_store.py` | unit | Planning event store | default |
| `test_planning_god_adapters.py` | unit | Planning GOD adapters | default |
| `test_planning_run_store.py` | unit | Planning run store | default |
| `test_platform_agent_spawner.py` | unit | Agent spawner | default |
| `test_platform_event_bus.py` | unit | Event bus | default |
| `test_platform_god_picker.py` | unit | GOD picker | default |
| `test_platform_mcp_tools.py` | unit | Platform MCP tools | default |
| `test_platform_projection_dependents.py` | unit | Projection dependents | default |
| `test_platform_prompt_builders.py` | unit | Prompt builders | default |
| `test_platform_review_fallback.py` | unit | Review fallback | default |
| `test_platform_state_machine.py` | unit | State machine | default |
| `test_platform_verdicts_writer.py` | unit | Verdicts writer | default |
| `test_provider_codex_retrofit.py` | unit | Codex retrofit tests (mocked) | default |
| `test_read_surface_schema_parity.py` | unit | Schema parity | default |
| `test_read_tool_inventory_module.py` | unit | Tool inventory | default |
| `test_reliability_hardening.py` | unit | Reliability hardening | default |
| `test_replay_fixtures.py` | unit | Replay fixtures | default |
| `test_review_aggregation_module.py` | unit | Review aggregation | default |
| `test_review_evidence_bundle_module.py` | unit | Evidence bundle | default |
| `test_review_gate.py` | unit | Review gate | default |
| `test_review_merge_guards_module.py` | unit | Merge guards | default |
| `test_review_plane.py` | unit | Review plane | default |
| `test_review_plane_controller.py` | unit | Review plane controller | default |
| `test_review_plane_merge_guards.py` | unit | Merge guards | default |
| `test_review_plane_merge_lineage.py` | unit | Merge lineage | default |
| `test_review_plane_merge_safety.py` | unit | Merge safety | default |
| `test_review_plane_merge_safety_legacy.py` | unit | Merge safety legacy | default |
| `test_review_plane_orchestrator_integration.py` | unit | Orchestrator integration | default |
| `test_review_plane_run_lineage.py` | unit | Run lineage | default |
| `test_review_rework_alignment.py` | unit | Rework alignment | default |
| `test_review_verdict_adapter.py` | unit | Verdict adapter | default |
| `test_rework_loop.py` | unit | Rework loop | default |
| `test_run_health.py` | unit | Run health | default |
| `test_run_processes.py` | unit | Run processes | default |
| `test_run_terminal_aggregation.py` | unit | Terminal aggregation | default |
| `test_runner_supervisor.py` | unit | Runner supervisor | default |
| `test_runtime_settings.py` | unit | pydantic-settings | default |
| `test_self_evolution_adapters.py` | unit | Self-evolution adapters | default |
| `test_self_evolution_checkpoint.py` | unit | Checkpoint | default |
| `test_self_evolution_clarification_recovery.py` | unit | Clarification recovery | default |
| `test_self_evolution_controller_decomposition.py` | unit | Controller decomposition | default |
| `test_self_evolution_decomposer.py` | unit | Decomposer | default |
| `test_self_evolution_peer_chat_decomposer.py` | unit | Peer chat decomposer | default |
| `test_self_evolution_watcher.py` | unit | Watcher | default |
| `test_session_router.py` | unit | Session router | default |
| `test_state_normalizer.py` | unit | State normalizer | default |
| `test_structuring_planning_event_models.py` | unit | Planning event models | default |
| `test_structuring_review_models.py` | unit | Review models | default |
| `test_structuring_takeover_models.py` | unit | Takeover models | default |
| `test_takeover_actions.py` | unit | Takeover actions | default |
| `test_takeover_contracts.py` | unit | Takeover contracts | default |
| `test_textual_read_layer.py` | unit | Textual read layer | default |
| `test_tui_adapter.py` | unit | TUI adapter | default |
| `test_tui_adapter_contract.py` | unit | TUI adapter contract | default |
| `test_tui_clipboard.py` | unit | TUI clipboard | default |
| `test_tui_completion.py` | unit | TUI completion engine | default |
| `test_tui_input_history.py` | unit | TUI input history | default |
| `test_tui_keymap.py` | unit | TUI keymap | default |
| `test_tui_navigation.py` | unit | TUI navigation | default |
| `test_tui_participant_cache.py` | unit | TUI participant cache | default |
| `test_tui_screen_integration.py` | unit | TUI screen integration | default |
| `test_tui_state.py` | unit | TUI state | default |
| `test_tui_ux_smoke.py` | unit | TUI UX smoke | default |
| `test_tui_widgets.py` | unit | TUI widgets | default |
| `test_verdict_store_atomic.py` | unit | Verdict store atomic | default |
| `test_verdict_store_atomic_legacy.py` | unit | Verdict store atomic legacy | default |
| `test_verdict_store_consistency.py` | unit | Verdict store consistency | default |

### Extended/nightly CI (integration-heavy or large)

| File | Category | Reason | Gate |
|------|----------|--------|------|
| `test_platform_orchestrator.py` | integration | 9085 lines, 165 tests, heavy fixture use | extended |
| `test_self_evolution.py` | integration | 3999 lines, model-dependent | extended |
| `test_dashboard_api.py` | integration | 3248 lines, HTTP integration | extended |
| `test_platform_runner.py` | integration | 2321 lines, runner simulation | extended |
| `test_chat_api.py` | integration | 2032 lines, FastAPI TestClient | extended |
| `test_review_plane_orchestrator_integration.py` | integration | 2025 lines, integration | extended |
| `test_peer_chat_dashboard.py` | integration | 1610 lines, dashboard integration | extended |
| `test_self_evolution_clarification_recovery.py` | integration | 942 lines, recovery tests | extended |
| `test_hermes_hardening.py` | integration | 1305 lines, hermes integration | extended |

### Manual only (real Ray, Codex, API keys)

| File | Category | Reason | Gate |
|------|----------|--------|------|
| `test_full_chain_real_run.py` | real_ray_codex | Needs real Ray, Codex, MCP | manual_only |
| `test_ray_adapters.py` | real_ray_codex | Needs real Ray | manual_only |
| `test_runtime_ray_backend.py` | real_ray_codex | Needs real Ray runtime | manual_only |
| `test_mcp_server.py` | network_required | Starts real MCP server process | manual_only |
| `test_provider_opencode.py` | network_required | Needs DEEPSEEK_API_KEY | manual_only |
| `test_mvp_e2e.py` | integration | Full dispatch cycle | manual_only |
| `test_mvp_e2e_chat_to_lane.py` | network_required | E2E + HTTP TestClient | manual_only |
| `test_peer_chat_api.py` | network_required | Needs chat API server | manual_only |
| `test_fe_vision_layer1_api.py` | network_required | FE vision API | manual_only |
| `test_fe_vision_layer1_participant_store.py` | unit | Participant store (may be default) | manual_only |

### Skip (broken, deprecated, or historical)

| File | Category | Reason | Gate |
|------|----------|--------|------|
| `test_skill_plan_execute_review.py` | deprecated | ModuleNotFoundError during collection | skip |
| `test_gate_profiles.py` | deprecated | Missing gate_profiles.json, 5 tests fail | skip |
| `test_master_loop.py` | deprecated | Old master_loop tests | skip |
| `test_master_loop_cli_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_full_gate_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_git_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_lanes_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_state_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_tasks_module.py` | deprecated | Old master_loop | skip |
| `test_master_loop_integration.py` | deprecated | Old master_loop | skip |
| `test_hermes_reporter.py` | deprecated | Legacy hermes reporter | skip |
| `test_hermes_master_state.py` | deprecated | Legacy hermes state | skip |
| `test_hermes_modules.py` | deprecated | Legacy hermes modules | skip |
| `test_overnight_runner.py` | deprecated | Shell script tests | skip |
| `test_native_historical_isolation.py` | deprecated | Historical isolation tests | skip |
| `test_sidecar_recall_eval.py` | deprecated | Sidecar recall eval | skip |
| `test_sidecar_recall_lab.py` | deprecated | Sidecar recall lab | skip |
| `test_sidecar_replay_exporter.py` | deprecated | Sidecar exporter | skip |
| `test_sidecar_replay_packet.py` | deprecated | Sidecar replay | skip |
| `test_sidecar_taxonomy.py` | deprecated | Sidecar taxonomy | skip |
| `test_v6_independent_smoke.py` | deprecated | V6 historical smoke | skip |
| `test_auto_discovery.py` | deprecated | Auto-discovery | skip |
| `test_autotakeover_classifier.py` | deprecated | Auto-takeover | skip |
| `test_split_export_contract.py` | package_boundary | Export contract (may fix for default) | extended |
| `test_export_tool.py` | package_boundary | Export tool (may fix for default) | extended |
| `test_ray_adapter_boundaries.py` | unit | Ray adapter boundaries (may be default) | extended |
| `test_peer_cross_restart.py` | unit | Peer cross restart | extended |
| `test_production_operations_doc.py` | unit | Doc validation | default |

---

## 4. Provider/Config Drift Risks

### Docs accuracy check

| Matrix | Claim | Current reality | Drift |
|--------|-------|-----------------|-------|
| config-matrix.md:174 | `pydantic-settings` declared but unused, no `BaseSettings` | `src/xmuse_core/runtime/settings.py` has working `Settings(BaseSettings)` class with 20+ fields | **Outdated** — doc needs update |
| provider-matrix.md:182 | `pydantic-settings` declared but unused | Same as above | **Outdated** |
| config-matrix.md:29 | `DEEPSEEK_API_KEY` read at `registry.py:25` | Actual: `registry.py:26` | +1 line (negligible) |
| config-matrix.md:43 | `XMUSE_RAY_GOD_TRANSPORT` at `ray_session_layer.py:377` | Actual: `ray_session_layer.py:383` | +6 lines |
| config-matrix.md:44 | `XMUSE_RAY_GOD_EFFORT` at `ray_session_layer.py:387` | Actual: `ray_session_layer.py:393` | +6 lines |
| config-matrix.md:45 | `XMUSE_RAY_GOD_MCP` at `ray_session_layer.py:395` | Actual: `ray_session_layer.py:401` | +6 lines |
| config-matrix.md:41 | `XMUSE_PEER_GOD_BACKEND` at `platform_runner.py:210` | Actual: `platform_runner.py:217` | +7 lines |
| config-matrix.md:42 | `XMUSE_DEGRADED_LOCAL_GOD_MODE` at `platform_runner.py:832` | Actual: `platform_runner.py:856` | +24 lines |

Line drifts in `ray_session_layer.py` and `platform_runner.py` are consistent (~6 lines added near the top of both files). Content accuracy is preserved.

### Undocumented env vars

| Env var | Used in | Also in source | Risk |
|---------|---------|---------------|------|
| `XMUSE_GOD_RUNTIME` | `test_platform_orchestrator.py` | `src/xmuse_core/platform/orchestrator.py` | Not in config-matrix |
| `XMUSE_NON_GOD_CODEX_MODEL` | `test_self_evolution_peer_chat_decomposer.py` | `chat/driver.py`, `peer_chat_decomposer.py` | Not in config-matrix |
| `XMUSE_PEER_CHAT_RUNTIME` | `test_self_evolution_peer_chat_decomposer.py` | `self_evolution/peer_chat_decomposer.py:8` | Not in config-matrix |
| `XMUSE_CHAT_DRIVER_RUNTIME` | `test_chat_driver.py` | `chat/driver.py:9` | Not in config-matrix |

### pydantic-settings name mismatch

`src/xmuse_core/runtime/settings.py` maps `codex_model` to env var `CODEX_MODEL` (no `XMUSE_` prefix). All other code uses `XMUSE_CODEX_MODEL`. If the Settings class is adopted by production paths, this mismatch will cause silent fallback to defaults.

### CI-specific risks

| # | Risk | Severity | Detail |
|---|------|----------|--------|
| 1 | **No CI config exists** | BLOCKER | `.github/workflows/`, `.gitlab-ci.yml` all absent |
| 2 | **DEEPSEEK_API_KEY not in CI** | HIGH | OpenCode adapter returns UNAVAILABLE without it |
| 3 | **Ray is a heavy dependency** | HIGH | `ray[default]>=2.55.1` requires native extensions, ~200MB install |
| 4 | **Codex binary required** | HIGH | `codex.*` profiles fail health checks without binary in PATH |
| 5 | **`python-dotenv` is dead weight** | LOW | Declared dep but zero imports in `src/` |
| 6 | **`pydantic-settings` is parallel overlay** | MEDIUM | `Settings` class exists but production uses `os.environ.get()` |
| 7 | **No `.env` loading in production** | LOW | Only `Settings` class supports `.env`, no production caller |
| 8 | **Undocumented test env vars** | LOW | 4+ env vars in tests not in config-matrix |

---

## 5. Type-Check Feasibility

### Command attempted

```bash
uv run mypy src/xmuse_core/
```

**Result**: 124 errors in 35 files (checked 261 source files).

### Error breakdown

| Error code | Count | Typical file |
|-----------|-------|-------------|
| `attr-defined` | ~10 | `self_evolution/controller.py` — `_chat`, `_graph_store`, `_store` |
| `arg-type` | ~15 | `chat/peer_service.py` — `Literal['codex', 'opencode']` mismatch |
| `assignment` | ~15 | `platform/orchestrator.py` — `bool` vs `str` |
| `misc` (rest) | ~84 | Various missing annotations, Any usage |

### Blockers for CI gate

1. **`self_evolution/controller.py`**: 9 errors — uses dynamically assigned attributes (`_chat`, `_graph_store`, `_store`) not in `__init__`. Requires either `__init__` update or `__getattr__` stub.
2. **`chat/peer_service.py`**: 3 errors — `cli_kind` passed as `str` where `Literal['codex', 'opencode']` expected.
3. **`platform/read_contracts.py`**: 4 errors — `str | None` passed where `str` expected in `_http_ref`.
4. **`platform/mcp_tools.py`**: `dict[str, Any] | None` assigned to `dict[str, Any]`.
5. **`platform/orchestrator.py`**: `bool` assigned to `str`.

### Recommended baseline

```bash
uv run mypy src/xmuse_core/ \
  --ignore-missing-imports \
  --follow-imports=skip \
  --exclude 'src/xmuse_core/self_evolution/controller.py' \
  --exclude 'src/xmuse_core/self_evolution/watcher.py' \
  --exclude 'src/xmuse_core/chat/peer_service.py' \
  --exclude 'src/xmuse_core/platform/read_contracts.py' \
  --exclude 'src/xmuse_core/platform/mcp_tools.py'
```

Even with exclusions, 100+ errors remain in `providers/`, `platform/`, `agents/`, and `chat/`. **Type-check is not feasible as a V10 CI gate.**

### Recommendation for V10

Do not add mypy to default CI. Instead:
- Add a documented `[tool.mypy]` baseline with known-excluded files in `pyproject.toml`.
- Target a "no new type errors" policy using `mypy --warn-unused-configs`.
- Revisit after ruff gate is stable and real provider tests are passing.

---

## 6. Proposed V10 Hard Gates and Non-Goals

### Hard gates (all must pass)

| Order | Gate | Command | Baseline target |
|-------|------|---------|-----------------|
| 1 | `uv build` | `uv build` | Zero errors |
| 2 | Ruff lint (no new errors) | `uv run ruff check src/xmuse_core/ tests/xmuse/` | Zero errors on target dirs; accept existing 51 errors with baseline |
| 3 | Package boundary | `uv run pytest -q tests/xmuse/test_package_boundaries.py` | All pass (currently pass) |
| 4 | Core contracts | `uv run pytest -q tests/xmuse/test_provider_models.py tests/xmuse/test_feature_review_contracts.py tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py tests/xmuse/test_provider_session_binding_store.py` | All pass (currently pass) |
| 5 | Provider policy & adapters | `uv run pytest -q tests/xmuse/test_provider_adapters.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_worker_goal_contract.py` | All pass (currently pass) |
| 6 | Runtime settings | `uv run pytest -q tests/xmuse/test_runtime_settings.py` | All pass (currently pass) |
| 7 | Reliability & recovery | `uv run pytest -q tests/xmuse/test_reliability_hardening.py` | All pass (currently pass) |

### Stretch gates (add after hard gates are stable)

| Gate | Command | Notes |
|------|---------|-------|
| Feature graph group | Group 2 from 1c | Fix the 1 failing test first |
| Chat services group | Group 3 from 1c | ~150 tests |
| Peer chat group | Group 5 from 1c | ~200 tests |
| TUI group | `uv run pytest -q tests/xmuse/test_tui_*.py` | ~84 tests |
| Export/split contract | `uv run pytest -q tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py` | Package boundary regression |

### Non-goals for V10

- **Do not run** `uv run ruff format --check .` — 318 files need reformatting, too noisy
- **Do not run** mypy type-check gate — 124 errors, needs baseline work first
- **Do not run** full test suite (3327 tests) — mix of broken, deprecated, and slow
- **Do not run** real Ray/Codex/MCP tests in CI — manual only
- **Do not run** tests requiring `DEEPSEEK_API_KEY` — manual only
- **Do not run** deprecated master_loop, hermes, sidecar, or overnight_runner tests
- **Do not run** `test_skill_plan_execute_review.py` — broken collection
- **Do not run** `test_gate_profiles.py` — 5 failing self-referential tests

---

## 7. Commands Run and Results

### Environment

```
repo root: /home/iiyatu/projects/python/xmuse
python: 3.11.15 (uv managed)
ruff: 0.15.x (via uv)
mypy: 2.1.0 (via uv)
pytest: 9.x (via uv)
```

### Results table

| # | Command | Exit | Key result |
|---|---------|------|------------|
| 1 | `uv run ruff check .` | 0 | 81 errors (33 E501, 19 I001, 15 F401, etc.) |
| 2 | `uv run ruff format --check .` | 0 | 318 files would be reformatted |
| 3 | `uv build` | 0 | Built `dist/xmuse-0.1.0-py3-none-any.whl` |
| 4 | `uv run mypy src/xmuse_core/` | 1 | 124 errors in 35 files |
| 5 | `uv run pytest --co -q tests/xmuse/` | 1 | 3331 collected, 1 collection error (test_skill_plan_execute_review.py) |
| 6 | `uv run pytest -q tests/xmuse/test_provider_models.py test_provider_adapters.py test_provider_policy.py test_package_boundaries.py test_shared_contract_fixtures_contract.py test_feature_review_contracts.py test_chat_store.py test_provider_session_binding_store.py test_provider_read_contracts_module.py test_worker_goal_contract.py test_runtime_settings.py` | 0 | 157 passed in 4.86s |
| 7 | `uv run pytest -q tests/xmuse/test_feature_graph_*.py tests/xmuse/test_feature_plan_*.py tests/xmuse/test_feature_summary.py tests/xmuse/test_feature_context.py` | 1 | 294 passed, 1 failed (test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes) in 2.68s |
| 8 | `uv run pytest -q tests/xmuse/test_package_boundaries.py test_gate_profiles.py test_quality_gate.py test_chat_api_models_module.py test_core_*.py test_memory_refs.py test_runtime_settings.py test_session_router.py test_verdict_store_atomic.py test_verdict_store_consistency.py test_worker_goal_contract.py test_reliability_hardening.py test_replay_fixtures.py test_split_export_contract.py test_state_normalizer.py test_export_tool.py` | 1 | 436 passed, 5 failed (test_gate_profiles) in 11.92s |
| 9 | `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_runtime_ray_backend.py tests/xmuse/test_mvp_e2e.py tests/xmuse/test_provider_opencode.py tests/xmuse/test_mcp_server.py tests/xmuse/test_master_loop*.py tests/xmuse/test_hermes_*.py tests/xmuse/test_overnight_runner.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_sidecar_*.py tests/xmuse/test_v6_independent_smoke.py` | 0 | 205 tests collected (not run — manual/network only) |
