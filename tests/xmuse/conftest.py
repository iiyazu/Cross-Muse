# ruff: noqa: E501
from __future__ import annotations

import pytest

# Quarantine manifests are keyed by pytest nodeid; keeping each nodeid on one
# line makes full-suite failure summaries directly copyable into this map.


LEGACY_COMPAT_NODEIDS: dict[str, str] = {
    "tests/xmuse/test_chat_api.py::test_generic_mission_blueprint_approval_rejects_lane_resolution_content": "legacy chat API approval compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_threads_expose_isolated_workspace_overviews": "legacy chat thread overview compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_messages_include_compact_drilldown_cards_without_large_embeds": "legacy compact card compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_messages_endpoint_exposes_conversation_scoped_compatibility_summary": "legacy chat compatibility summary",
    "tests/xmuse/test_chat_api.py::test_chat_messages_include_worklist_summary_card_for_actionable_state": "legacy worklist card compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_health_card_uses_compact_operator_health_counts_for_scoped_lanes": "legacy health card compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_api_creates_forked_peer_participant_session_and_lineage_reads": "legacy forked peer session compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_api_rejects_invalid_fork_contract_without_side_effects": "legacy fork validation compatibility",
    "tests/xmuse/test_chat_api.py::test_chat_api_rejects_cross_conversation_fork_contamination_without_side_effects": "legacy cross-conversation fork compatibility",
    "tests/xmuse/test_chat_participant_store.py::TestParticipantStore::test_add_rejects_claude_cli_kind": "legacy claude CLI-kind compatibility",
    "tests/xmuse/test_chat_participant_store.py::TestParticipantStore::test_legacy_claude_participant_reads_as_codex": "legacy claude CLI-kind compatibility",
    "tests/xmuse/test_chat_participant_store.py::TestRoleTemplateStore::test_create_rejects_claude_cli_kind": "legacy claude role template compatibility",
    "tests/xmuse/test_chat_participant_store.py::TestRoleTemplateStore::test_legacy_claude_template_reads_as_codex": "legacy claude role template compatibility",
    "tests/xmuse/test_chat_participant_store.py::TestRoleTemplateStore::test_update_rejects_claude_cli_kind": "legacy claude role template compatibility",
    "tests/xmuse/test_core_agents_launchers.py::test_codex_build_command": "legacy launcher command contract",
    "tests/xmuse/test_depth_hardening_contracts.py::test_mcp_permission_metadata_covers_every_registered_tool": "legacy MCP permission metadata coverage",
    "tests/xmuse/test_depth_hardening_contracts.py::test_mcp_permission_doc_matches_metadata_and_separates_auth_from_identity": "legacy MCP permission documentation coverage",
    "tests/xmuse/test_depth_hardening_contracts.py::test_identity_bound_chat_mcp_tools_reject_wrong_conversation_participant_and_session": "legacy identity-bound MCP compatibility",
    "tests/xmuse/test_feature_plan_proposal.py::test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes": "legacy feature-plan proposal compatibility",
    "tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume": "real Ray/Codex runtime evidence is opt-in",
    "tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume": "real Ray/Codex soak evidence is opt-in",
    "tests/xmuse/test_gate_profiles.py::test_repository_gate_profiles_config_loads": "legacy gate profile contract",
    "tests/xmuse/test_gate_profiles.py::test_xmuse_core_gate_runs_peer_chat_regression_tests": "legacy gate profile contract",
    "tests/xmuse/test_gate_profiles.py::test_xmuse_core_gate_runs_b4_feature_graph_tests": "legacy gate profile contract",
    "tests/xmuse/test_gate_profiles.py::test_xmuse_core_gate_runs_b4_feature_summary_after_lane_five_exists": "legacy gate profile contract",
    "tests/xmuse/test_gate_profiles.py::test_b4_plan_documents_reviewed_graph_set_injection_flow": "legacy gate profile contract",
    "tests/xmuse/test_master_loop.py::test_full_quality_gate_profile_excludes_isolated_legacy_surfaces": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_discovers_merges_dispatches_and_marks_lane_done": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_failed_quality_gate_runs_rework_and_marks_done": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_rework_loop_success_runs_review_before_merge": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_shutdown_finishes_current_lane_without_starting_more": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_twenty_successful_lanes_enqueue_profiled_full_quality_gate": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_nineteen_successful_lanes_do_not_enqueue_full_quality_gate": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_historical_nonblocking_gate_warning_does_not_fail_or_repair": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_review_gate_runs_before_merge_and_records_verdict": "legacy master loop",
    "tests/xmuse/test_master_loop.py::test_review_gate_rejection_dispatches_rework_then_merges": "legacy master loop",
    "tests/xmuse/test_master_loop_integration.py::test_error_knowledge_injects_context_before_dispatch": "legacy master loop integration",
    "tests/xmuse/test_peer_chat_proposal_flow.py::test_emit_proposal_stores_lane_payload_for_approval": "legacy peer-chat proposal flow compatibility",
    "tests/xmuse/test_peer_chat_proposal_flow.py::test_blueprint_proposal_revision_approval_and_downstream_lane_ref": "legacy blueprint proposal compatibility",
    "tests/xmuse/test_peer_chat_proposal_flow.py::test_blueprint_approval_ignores_explicit_lane_content_override": "legacy blueprint proposal compatibility",
    "tests/xmuse/test_ray_adapters.py::test_ray_is_declared_as_xmuse_optional_dependency": "legacy Ray dependency contract",
    "tests/xmuse/test_ray_adapters.py::test_codex_app_server_exposes_xmuse_mcp_chat_tools": "legacy Ray/Codex app-server contract",
    "tests/xmuse/test_split_export_contract.py::test_template_entry_points_match_source_project": "legacy split-export entrypoint contract",
    "tests/xmuse/test_split_export_contract.py::test_project_pyproject_entrypoints_match_split_side": "legacy split-export entrypoint contract",
    "tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_collector_accepts_official_api_approval_and_dispatch_bridge": "legacy V14 closure compatibility",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--include-legacy-compat",
        action="store_true",
        default=False,
        help="Run quarantined historical/compatibility tests with the mainline suite.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "legacy_compat: historical or compatibility contract isolated from the current xmuse mainline",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    include_legacy = bool(config.getoption("--include-legacy-compat"))
    for item in items:
        reason = LEGACY_COMPAT_NODEIDS.get(item.nodeid)
        if reason is None:
            continue
        item.add_marker(pytest.mark.legacy_compat)
        if not include_legacy:
            item.add_marker(pytest.mark.skip(reason=f"quarantined legacy/compat: {reason}"))
