from __future__ import annotations

from xmuse.tui.adapter.xmuse_adapter import StateDelta, XmuseAdapter
from xmuse.tui.state import AppState
from xmuse_core.integrations.memoryos_lite_interop import MemoryOSLiteTraceEvidence
from xmuse_core.platform.tui_vision_read_model import build_tui_vision_read_model


def test_tui_vision_read_model_summarizes_deliberation_speech_acts() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        messages=[
            {
                "id": "msg-propose",
                "conversation_id": "conv-1",
                "author": "architect",
                "envelope_json": {
                    "speech_act": "propose",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["memory://conversation/conv-1/source"],
                    "target_ref": "blueprint:conv-1:1",
                    "payload": {"summary": "freeze the scoped blueprint"},
                },
            },
            {
                "id": "msg-challenge",
                "conversation_id": "conv-1",
                "author": "review",
                "envelope_json": {
                    "act": "challenge",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["message:msg-propose"],
                    "target_refs": ["blueprint:conv-1:1"],
                    "blocking": True,
                    "payload": {"summary": "acceptance criteria are missing"},
                },
            },
        ],
    )

    deliberation = model["deliberation"]
    assert deliberation["proof_level"] == "contract_proof"
    assert deliberation["fact_state"] == "blocked"
    assert deliberation["speech_act_counts"] == {"challenge": 1, "propose": 1}
    assert deliberation["source_refs"] == [
        "message:msg-propose",
        "memory://conversation/conv-1/source",
        "message:msg-challenge",
    ]
    assert deliberation["target_refs"] == ["blueprint:conv-1:1"]
    assert deliberation["blockers"] == [
        {
            "message_id": "msg-challenge",
            "speech_act": "challenge",
            "reason": "acceptance criteria are missing",
            "source_refs": ["message:msg-propose"],
            "target_refs": ["blueprint:conv-1:1"],
        }
    ]
    assert deliberation["manual_gap_reason"] is None


def test_tui_vision_read_model_reports_blueprint_freeze_readiness_not_freeze_fact() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        messages=[
            {
                "id": "msg-decide",
                "conversation_id": "conv-1",
                "author": "architect",
                "envelope_json": {
                    "type": "decide",
                    "decision_scope": "blueprint.freeze",
                    "target_ref": "blueprint:conv-1:1",
                    "source_refs": ["message:msg-vote-review"],
                    "payload": {"decision": "freeze_ready"},
                },
            }
        ],
    )

    freeze = model["blueprint_freeze"]
    assert freeze["proof_level"] == "contract_proof"
    assert freeze["fact_state"] == "ready_to_freeze"
    assert freeze["ready_to_freeze"] is True
    assert freeze["frozen"] is False
    assert freeze["target_refs"] == ["blueprint:conv-1:1"]
    assert freeze["source_refs"] == ["message:msg-decide", "message:msg-vote-review"]
    assert freeze["blockers"] == []
    assert freeze["manual_gap_reason"] is None


def test_tui_vision_read_model_summarizes_lane_dag_projection() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        worklist_envelope={
            "source_authority": "feature_lanes_projection",
            "projection_revision": 7,
            "items": [
                {
                    "lane_id": "lane-a",
                    "plan_feature_id": "feature-a",
                    "ready": True,
                    "blocked": False,
                    "scoped_dependency_ids": [],
                },
                {
                    "lane_id": "lane-b",
                    "plan_feature_id": "feature-a",
                    "ready": False,
                    "blocked": True,
                    "scoped_dependency_ids": ["lane-a"],
                    "prompt_summary": "needs review evidence",
                    "review_decision": "rework",
                    "review_decision_id": "review-decision-b",
                    "review_summary": "Review found missing evidence.",
                    "review_verdict_id": "verdict-b",
                },
                {
                    "lane_id": "lane-c",
                    "plan_feature_id": "feature-a",
                    "ready": True,
                    "blocked": False,
                    "source_lane_id": "lane-b",
                    "review_decision": "merge",
                    "review_summary": "Patch-forward reviewed cleanly.",
                },
            ],
            "graph_lineage": {
                "authoritative_graph_id": "graph-1",
                "checked_graph_ids": ["graph-1"],
                "degraded": False,
            },
        },
    )

    execution = model["execution"]
    assert execution["proof_level"] == "contract_proof"
    assert execution["fact_state"] == "blocked"
    assert execution["lane_count"] == 3
    assert execution["ready_lane_ids"] == ["lane-a", "lane-c"]
    assert execution["blocked_lane_ids"] == ["lane-b"]
    assert execution["dependency_edges"] == [
        {"lane_id": "lane-b", "depends_on": ["lane-a"]}
    ]
    assert execution["graph_lineage"]["authoritative_graph_id"] == "graph-1"
    assert execution["source_refs"] == ["feature_lanes_projection#projection_revision=7"]
    assert execution["target_refs"] == [
        "lane:lane-a",
        "lane:lane-b",
        "lane:lane-c",
        "graph:graph-1",
    ]
    assert execution["blockers"] == [
        {
            "lane_id": "lane-b",
            "reason": "needs review evidence",
            "source_refs": ["feature_lanes_projection#projection_revision=7"],
            "target_refs": ["lane:lane-b"],
        }
    ]
    assert execution["review_items"] == [
        {
            "lane_id": "lane-b",
            "decision": "rework",
            "summary": "Review found missing evidence.",
            "source_refs": ["feature_lanes_projection#projection_revision=7"],
            "target_refs": [
                "lane:lane-b",
                "review_verdict:verdict-b",
                "review_decision:review-decision-b",
            ],
            "verdict_id": "verdict-b",
            "decision_id": "review-decision-b",
        },
        {
            "lane_id": "lane-c",
            "decision": "merge",
            "summary": "Patch-forward reviewed cleanly.",
            "source_refs": ["feature_lanes_projection#projection_revision=7"],
            "target_refs": ["lane:lane-c"],
        },
    ]
    assert execution["patch_forward_lineage"] == [
        {
            "source_lane_id": "lane-b",
            "patch_lane_id": "lane-c",
            "source_refs": ["feature_lanes_projection#projection_revision=7"],
            "target_refs": ["lane:lane-b", "lane:lane-c"],
        }
    ]


def test_tui_vision_read_model_keeps_review_verdict_refs_without_decision() -> None:
    model = build_tui_vision_read_model(
        worklist_envelope={
            "source_authority": "review_projection",
            "projection_revision": 3,
            "items": [
                {
                    "lane_id": "lane-a",
                    "ready": True,
                    "review_verdict_id": "verdict-a",
                }
            ],
        }
    )

    assert model["execution"]["review_items"] == [
        {
            "lane_id": "lane-a",
            "decision": "observed",
            "summary": "",
            "source_refs": ["review_projection#projection_revision=3"],
            "target_refs": ["lane:lane-a", "review_verdict:verdict-a"],
            "verdict_id": "verdict-a",
        }
    ]


def test_tui_vision_read_model_summarizes_memory_trace_and_manual_gap() -> None:
    with_trace = build_tui_vision_read_model(
        conversation_id="conv-1",
        memory_trace={
            "session_id": "mem-session-1",
            "namespace": {"conversation_id": "conv-1"},
            "trace_events": [{"event": "retrieve"}, {"event": "drop"}],
            "context_package": {
                "pinned_core": [{"id": "core-1"}],
                "active_task_pages": [{"id": "task-1"}, {"id": "task-2"}],
                "recent_messages": [{"id": "msg-1"}],
                "retrieved_pages": [{"id": "page-1"}, {"id": "page-2"}],
                "dropped_pages": [{"id": "drop-1"}],
            },
            "source_refs": ["memory://conversation/conv-1/session/mem-session-1"],
            "token_estimate": 321,
            "proof_level": "live_service_proof",
        },
    )

    memory = with_trace["memory"]
    assert memory["proof_level"] == "live_service_proof"
    assert memory["fact_state"] == "observed"
    assert memory["session_id"] == "mem-session-1"
    assert memory["namespace"] == {"conversation_id": "conv-1"}
    assert memory["trace_events_count"] == 2
    assert memory["pinned_core_count"] == 1
    assert memory["active_task_pages_count"] == 2
    assert memory["recent_messages_count"] == 1
    assert memory["retrieved_pages_count"] == 2
    assert memory["dropped_pages_count"] == 1
    assert memory["token_estimate"] == 321
    assert memory["source_refs"] == [
        "memory://conversation/conv-1/session/mem-session-1"
    ]
    assert memory["manual_gap_reason"] is None

    without_trace = build_tui_vision_read_model(conversation_id="conv-1")
    assert without_trace["memory"]["proof_level"] == "manual_gap"
    assert without_trace["memory"]["fact_state"] == "manual_gap"
    assert without_trace["memory"]["manual_gap_reason"] == "memory trace unavailable"


def test_tui_vision_read_model_accepts_memoryos_lite_trace_evidence_shape() -> None:
    trace = MemoryOSLiteTraceEvidence(
        namespace_uri="memory://conversation/conv-1",
        session_id="mem-session-1",
        trace_events=[{"event": "context", "estimated_tokens": 64}],
        source_refs=["lane:lane-1"],
        estimated_tokens=64,
    ).model_dump(mode="json")

    model = build_tui_vision_read_model(memory_trace=trace)
    memory = model["memory"]

    assert memory["proof_level"] == "live_service_proof"
    assert memory["session_id"] == "mem-session-1"
    assert memory["namespace_uri"] == "memory://conversation/conv-1"
    assert memory["namespace"] == {"uri": "memory://conversation/conv-1"}
    assert memory["trace_events_count"] == 1
    assert memory["token_estimate"] == 64
    assert memory["source_refs"] == ["lane:lane-1"]


def test_tui_vision_read_model_preserves_github_truth_without_merging_readiness() -> None:
    ready = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_enforcement_proof",
            "can_emit_pr_merged": True,
            "required_checks": {"state": "success", "checks": ["pytest"]},
            "review_truth": {"approved": True, "blocking_reviews": []},
            "merge": {"merged": False, "merge_commit_sha": None},
            "source_refs": ["github://owner/repo/pull/42"],
        },
    )

    github = ready["github"]
    assert github["proof_level"] == "server_side_enforcement_proof"
    assert github["fact_state"] == "merge_ready"
    assert github["can_emit_pr_merged"] is True
    assert github["required_checks"] == {"state": "success", "checks": ["pytest"]}
    assert github["review_truth"] == {"approved": True, "blocking_reviews": []}
    assert github["merge"] == {"merged": False, "merge_commit_sha": None}
    assert github["source_refs"] == ["github://owner/repo/pull/42"]

    merged = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": True,
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )
    assert merged["github"]["fact_state"] == "pr_merged"


def test_tui_vision_read_model_requires_can_emit_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": False,
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"
    assert model["github"]["manual_gap_reason"] == "server-side merge proof is missing"


def test_tui_vision_read_model_requires_literal_true_can_emit_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": "true",
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"
    assert model["github"]["can_emit_pr_merged"] is False


def test_tui_vision_read_model_requires_merge_commit_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": True,
            "merge": {
                "merged": True,
                "merged_at": "2026-06-11T00:00:00Z",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"


def test_tui_vision_read_model_requires_merged_at_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": True,
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"


def test_tui_vision_read_model_requires_merged_flag_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": True,
            "merge": {
                "merged": "true",
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
                "merge_event_id": "merge-event-1",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "merge_ready"


def test_tui_vision_read_model_requires_merge_event_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "can_emit_pr_merged": True,
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"
    assert model["github"]["manual_gap_reason"] == "server-side merge proof is missing"


def test_tui_vision_read_model_requires_server_side_proof_for_pr_merged() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "proof_level": "contract_proof",
            "merge": {
                "merged": True,
                "merge_commit_sha": "synthetic",
                "merged_at": "2026-06-11T00:00:00Z",
            },
            "source_refs": ["fake-github://pull/42"],
        },
    )

    assert model["github"]["fact_state"] == "manual_gap"
    assert model["github"]["manual_gap_reason"] == "server-side merge proof is missing"


def test_tui_vision_read_model_projects_github_truth_into_proof_cockpit() -> None:
    model = build_tui_vision_read_model(
        github_truth={
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "required_checks": [
                "quality-gates",
                "contract-smoke-gates",
                "real-runtime-integration-gate",
            ],
            "proof_level": "manual_gap",
            "pull_request_state": "open",
            "draft": True,
            "mergeable": True,
            "mergeable_state": "clean",
            "head_sha": "head-current",
            "workflow_run_id": 27457543932,
            "check_run_ids": [101, 102, 103],
            "expected_source_app": "github-actions",
            "branch_protection_snapshot": {"required_status_checks": {"strict": True}},
            "ruleset_snapshot": None,
            "review_event_id": None,
            "internal_review_verified": False,
            "merge_commit_sha": "merge-candidate",
            "merged_at": None,
            "merge_event_id": None,
            "gap_reason": "missing server-side truth: review_truth, merge_truth",
            "schema_version": "github_server_side_truth_capture.v1",
            "expected_head_sha": "head-current",
            "head_sha_matches_expected": True,
            "can_emit_pr_merged": False,
            "merged": False,
            "capture_mode": "opt_in_read_only_gh_api",
            "source_refs": [
                "github:pr:43",
                "github:head:head-current",
                "github:expected-head:head-current",
            ],
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["github_truth"] == {
        "repo": "iiyazu/Cross-Muse",
        "pull_request_number": 43,
        "proof_level": "manual_gap",
        "schema_version": "github_server_side_truth_capture.v1",
        "pull_request_state": "open",
        "draft": True,
        "mergeable": True,
        "mergeable_state": "clean",
        "head_sha": "head-current",
        "expected_head_sha": "head-current",
        "head_sha_matches_expected": True,
        "workflow_run_id": "27457543932",
        "required_check_count": 3,
        "check_run_count": 3,
        "expected_source_app": "github-actions",
        "server_enforcement": "branch_protection",
        "review_truth": "missing",
        "merge_truth": "missing",
        "merged": False,
        "can_emit_pr_merged": False,
        "gap_reason": "missing server-side truth: review_truth, merge_truth",
        "capture_mode": "opt_in_read_only_gh_api",
        "source_refs": [
            "github:pr:43",
            "github:head:head-current",
            "github:expected-head:head-current",
        ],
    }


def test_tui_vision_read_model_summarizes_proof_cockpit_without_authority_upgrade() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "authority": "replay_index_only",
            "decision": "blocked",
            "proof_level_summary": {
                "contract_proof": 4,
                "manual_gap": 1,
                "server_side_enforcement_proof": 1,
            },
            "sections": [
                {
                    "section_id": "github_truth",
                    "status": "ok",
                    "proof_level": "server_side_enforcement_proof",
                    "source_authority": "github_server",
                    "source_refs": ["github:pr:43"],
                    "artifacts": ["artifact://github-truth.json"],
                },
                {
                    "section_id": "memoryos_trace",
                    "status": "manual_gap",
                    "proof_level": "manual_gap",
                    "source_authority": "memoryos_rest",
                    "source_refs": [],
                    "artifacts": [],
                },
                {
                    "section_id": "memory_governance",
                    "status": "ok",
                    "proof_level": "contract_proof",
                    "source_authority": "memoryos_governance_policy",
                    "source_refs": ["memory-governance:policy:S5"],
                    "artifacts": ["artifact://memory-governance.json"],
                },
            ],
            "blockers": [
                {
                    "section_id": "memoryos_trace",
                    "reason": "MemoryOS Lite was not configured",
                    "owner": "operator",
                    "next_action": "Enable MemoryOS Lite.",
                }
            ],
        },
        release_evidence_pack={
            "schema_version": "xmuse.release_evidence_pack.v1",
            "decision": "blocked",
            "release_readiness_decision": "blocked",
            "proof_contamination_decision": "clean",
            "artifact_count": 4,
            "blocker_count": 1,
            "finding_count": 0,
            "blockers": [
                {
                    "gate_id": "real-provider-runtime",
                    "kind": "real_provider",
                    "reason": "real provider runtime soak was not captured",
                    "owner": "operator",
                    "next_action": "Run provider soak.",
                }
            ],
            "readiness_report": "artifact://release-readiness.json",
            "proof_contamination_audit": "artifact://proof-contamination-audit.json",
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["proof_level"] == "contract_proof"
    assert cockpit["fact_state"] == "blocked"
    assert cockpit["source_authority"] == [
        "xmuse.overnight_replay_bundle.v1",
        "xmuse.release_evidence_pack.v1",
    ]
    assert cockpit["replay_decision"] == "blocked"
    assert cockpit["release_decision"] == "blocked"
    assert cockpit["proof_contamination_decision"] == "clean"
    assert cockpit["authority"] == "replay_index_only"
    assert cockpit["proof_level_summary"] == {
        "contract_proof": 4,
        "manual_gap": 1,
        "server_side_enforcement_proof": 1,
    }
    assert cockpit["section_count"] == 3
    assert cockpit["section_statuses"] == [
        {
            "section_id": "github_truth",
            "status": "ok",
            "proof_level": "server_side_enforcement_proof",
            "source_authority": "github_server",
        },
        {
            "section_id": "memoryos_trace",
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "source_authority": "memoryos_rest",
        },
        {
            "section_id": "memory_governance",
            "status": "ok",
            "proof_level": "contract_proof",
            "source_authority": "memoryos_governance_policy",
        },
    ]
    assert cockpit["artifact_count"] == 4
    assert cockpit["blocker_count"] == 2
    assert cockpit["finding_count"] == 0
    assert cockpit["source_refs"] == ["github:pr:43", "memory-governance:policy:S5"]
    assert cockpit["artifacts"] == [
        "artifact://github-truth.json",
        "artifact://memory-governance.json",
        "artifact://release-readiness.json",
        "artifact://proof-contamination-audit.json",
    ]
    assert cockpit["blockers"] == [
        {
            "kind": "replay_section",
            "id": "memoryos_trace",
            "reason": "MemoryOS Lite was not configured",
            "owner": "operator",
            "next_action": "Enable MemoryOS Lite.",
        },
        {
            "kind": "release_gate",
            "id": "real-provider-runtime",
            "reason": "real provider runtime soak was not captured",
            "owner": "operator",
            "next_action": "Run provider soak.",
        },
    ]


def test_tui_vision_read_model_projects_release_pack_recovery_queue() -> None:
    model = build_tui_vision_read_model(
        release_evidence_pack={
            "schema_version": "xmuse.release_evidence_pack.v1",
            "decision": "blocked",
            "release_readiness_decision": "blocked",
            "proof_contamination_decision": "clean",
            "artifact_count": 2,
            "blocker_count": 1,
            "recovery_queue_count": 2,
            "finding_count": 0,
            "recovery_queue": [
                {
                    "source": "release_readiness",
                    "kind": "release_gate",
                    "id": "real-provider-runtime",
                    "owner": "operator",
                    "reason": "real provider runtime soak was not captured",
                    "next_action": "Run provider soak.",
                    "artifact": "artifact://release-readiness.json",
                },
                {
                    "source": "overnight_replay_bundle",
                    "kind": "replay_section",
                    "id": "memoryos_trace",
                    "owner": "operator",
                    "reason": "MemoryOS Lite was not configured",
                    "next_action": "Enable MemoryOS Lite.",
                    "artifact": "artifact://overnight-replay-bundle.json",
                },
            ],
            "readiness_report": "artifact://release-readiness.json",
            "proof_contamination_audit": "artifact://proof-contamination-audit.json",
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["fact_state"] == "blocked"
    assert cockpit["recovery_queue"] == [
        {
            "source": "release_readiness",
            "kind": "release_gate",
            "id": "real-provider-runtime",
            "owner": "operator",
            "reason": "real provider runtime soak was not captured",
            "next_action": "Run provider soak.",
            "artifact": "artifact://release-readiness.json",
        },
        {
            "source": "overnight_replay_bundle",
            "kind": "replay_section",
            "id": "memoryos_trace",
            "owner": "operator",
            "reason": "MemoryOS Lite was not configured",
            "next_action": "Enable MemoryOS Lite.",
            "artifact": "artifact://overnight-replay-bundle.json",
        },
    ]
    assert cockpit["blockers"] == [
        {
            "kind": "release_gate",
            "id": "real-provider-runtime",
            "reason": "real provider runtime soak was not captured",
            "owner": "operator",
            "next_action": "Run provider soak.",
        },
        {
            "kind": "replay_section",
            "id": "memoryos_trace",
            "reason": "MemoryOS Lite was not configured",
            "owner": "operator",
            "next_action": "Enable MemoryOS Lite.",
        },
    ]


def test_tui_vision_read_model_projects_real_provider_runtime_details() -> None:
    model = build_tui_vision_read_model(
        release_evidence_pack={
            "schema_version": "xmuse.release_evidence_pack.v1",
            "decision": "blocked",
            "release_readiness_decision": "blocked",
            "proof_contamination_decision": "clean",
            "artifact_count": 1,
            "finding_count": 0,
            "real_provider_runtime": {
                "authority": "real_provider_runtime_release_gate",
                "status": "blocked",
                "proof_level": "real_provider_proof",
                "gate_artifact": "artifact://real-provider-runtime-gate.json",
                "runtime_artifact": "artifact://real-provider-runtime.json",
                "run_id": "real-soak-pr43",
                "conversation_id": "conv-prod-1",
                "provider_id": "codex",
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "provider_session_id": "codex-thread-prod-1",
                "mcp_writeback": True,
                "provider_session_reused": True,
                "fresh_provider_session_id": "codex-thread-prod-1",
                "resumed_provider_session_id": "codex-thread-prod-1",
                "turn_count": 2,
                "phases": ["fresh", "resume"],
                "mcp_writeback_turn_count": 2,
                "degraded_turn_count": 0,
                "blocker_count": 1,
            },
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["real_provider_runtime"] == {
        "authority": "real_provider_runtime_release_gate",
        "status": "blocked",
        "proof_level": "real_provider_proof",
        "gate_artifact": "artifact://real-provider-runtime-gate.json",
        "runtime_artifact": "artifact://real-provider-runtime.json",
        "run_id": "real-soak-pr43",
        "conversation_id": "conv-prod-1",
        "provider_id": "codex",
        "runtime_backend": "ray",
        "transport": "codex-app-server",
        "provider_session_id": "codex-thread-prod-1",
        "mcp_writeback": True,
        "provider_session_reused": True,
        "fresh_provider_session_id": "codex-thread-prod-1",
        "resumed_provider_session_id": "codex-thread-prod-1",
        "turn_count": 2,
        "phases": ["fresh", "resume"],
        "mcp_writeback_turn_count": 2,
        "degraded_turn_count": 0,
        "blocker_count": 1,
    }


def test_tui_vision_read_model_projects_memoryos_trace_details() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "decision": "blocked",
            "authority": "replay_index_only",
            "proof_level_summary": {"live_service_proof": 1},
            "sections": [
                {
                    "section_id": "memoryos_trace",
                    "status": "ok",
                    "proof_level": "live_service_proof",
                    "source_authority": "memoryos_live_release_gate",
                    "source_refs": [
                        "conversation:conv-live",
                        "memoryos:session:ses-live-1",
                    ],
                    "artifacts": ["artifact://memoryos-trace.json"],
                    "details": {
                        "memoryos_trace": {
                            "authority": "memoryos_live_release_gate",
                            "namespace_uri": (
                                "memory://conversation/conv-live/god-review/thread-1"
                            ),
                            "session_id": "ses-live-1",
                            "trace_event_count": 3,
                            "event_kinds": [
                                "session_created",
                                "ingest",
                                "context_built",
                            ],
                            "estimated_tokens": 96,
                            "source_ref_count": 5,
                            "blocker_count": 1,
                            "live_service_proof": True,
                        }
                    },
                }
            ],
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["memoryos_trace"] == {
        "authority": "memoryos_live_release_gate",
        "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
        "session_id": "ses-live-1",
        "trace_event_count": 3,
        "event_kinds": ["session_created", "ingest", "context_built"],
        "estimated_tokens": 96,
        "source_ref_count": 5,
        "blocker_count": 1,
        "live_service_proof": True,
    }


def test_tui_vision_read_model_projects_feature_lineage_lane_details() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "decision": "blocked",
            "authority": "replay_index_only",
            "proof_level_summary": {"contract_proof": 1},
            "sections": [
                {
                    "section_id": "feature_lineage",
                    "status": "ok",
                    "proof_level": "contract_proof",
                    "source_authority": "feature_owner_execution_contract",
                    "source_refs": ["feature-owner:feature-runtime-loop"],
                    "artifacts": ["artifact://feature-lineage.json"],
                    "details": {
                        "feature_lineage": {
                            "authority": "feature_owner_execution_contract",
                            "contract_count": 1,
                            "lane_count": 3,
                            "ready_lane_count": 1,
                            "blocked_lane_count": 1,
                            "completed_lane_count": 1,
                            "blocker_count": 1,
                            "projection_authority": False,
                            "status_write_policy": (
                                "read_only_contract_no_status_writes"
                            ),
                            "features": [
                                {
                                    "feature_id": "feature-runtime-loop",
                                    "objective": (
                                        "Run the overnight supervisor with "
                                        "replayable evidence."
                                    ),
                                    "graph_set_id": "graph-set-1",
                                    "feature_graph_id": "graph-runtime",
                                    "ready_lane_ids": ["lane-heartbeat"],
                                    "blocked_lane_ids": ["lane-replay"],
                                    "completed_lane_ids": ["lane-docs"],
                                    "lane_blockers": [
                                        {
                                            "lane_id": "lane-replay",
                                            "blocker_type": (
                                                "dependency_unsatisfied"
                                            ),
                                            "blocker_ref": "lane:lane-heartbeat",
                                            "blocker_status": "pending",
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            ],
            "blockers": [],
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["feature_lineage"] == {
        "authority": "feature_owner_execution_contract",
        "contract_count": 1,
        "lane_count": 3,
        "ready_lane_count": 1,
        "blocked_lane_count": 1,
        "completed_lane_count": 1,
        "blocker_count": 1,
        "projection_authority": False,
        "status_write_policy": "read_only_contract_no_status_writes",
        "features": [
            {
                "feature_id": "feature-runtime-loop",
                "objective": "Run the overnight supervisor with replayable evidence.",
                "graph_set_id": "graph-set-1",
                "feature_graph_id": "graph-runtime",
                "ready_lane_ids": ["lane-heartbeat"],
                "blocked_lane_ids": ["lane-replay"],
                "completed_lane_ids": ["lane-docs"],
                "lane_blockers": [
                    {
                        "lane_id": "lane-replay",
                        "blocker_type": "dependency_unsatisfied",
                        "blocker_ref": "lane:lane-heartbeat",
                        "blocker_status": "pending",
                    }
                ],
            }
        ],
    }


def test_tui_vision_read_model_projects_memory_governance_details() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "decision": "blocked",
            "authority": "replay_index_only",
            "proof_level_summary": {"contract_proof": 1},
            "sections": [
                {
                    "section_id": "memory_governance",
                    "status": "manual_gap",
                    "proof_level": "manual_gap",
                    "source_authority": "memoryos_governance_policy",
                    "source_refs": ["memory-governance:plan:blocked-shared"],
                    "artifacts": ["artifact://memory-governance.json"],
                    "details": {
                        "memory_governance": {
                            "authority": "memoryos_governance_policy",
                            "plan_count": 2,
                            "ingest_count": 1,
                            "promote_to_shared_count": 0,
                            "provider_session_binding_only_count": 0,
                            "blocked_count": 1,
                            "live_trace_proof": False,
                            "write_policy": "governed_rest_ingest_only",
                            "plans": [
                                {
                                    "plan_id": "task-write",
                                    "scope": "task",
                                    "event_kind": "blueprint_frozen",
                                    "status": "ok",
                                    "decision": "ingest",
                                    "proof_level": "contract_proof",
                                    "target_namespace_uri": (
                                        "memory://conversation/conv-1"
                                    ),
                                    "shared_namespace_uri": None,
                                    "memory_layer": "task_state",
                                    "reviewed": False,
                                    "write_request_allowed": True,
                                    "source_refs": ["blueprint:bp-1"],
                                    "blocked_reason": None,
                                    "next_action": None,
                                },
                                {
                                    "plan_id": "blocked-shared",
                                    "scope": "shared",
                                    "event_kind": "decision_rationale",
                                    "status": "blocked",
                                    "decision": "blocked",
                                    "proof_level": "manual_gap",
                                    "target_namespace_uri": (
                                        "memory://conversation/conv-1"
                                    ),
                                    "shared_namespace_uri": (
                                        "memory://global/shared/iiyazu/Cross-Muse"
                                    ),
                                    "memory_layer": "task_state",
                                    "reviewed": False,
                                    "write_request_allowed": False,
                                    "source_refs": ["message:m1"],
                                    "blocked_reason": (
                                        "shared promotion requires explicit review"
                                    ),
                                    "next_action": (
                                        "Attach review evidence before promoting "
                                        "memory beyond task scope."
                                    ),
                                },
                            ],
                        }
                    },
                }
            ],
            "blockers": [],
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["memory_governance"] == {
        "authority": "memoryos_governance_policy",
        "plan_count": 2,
        "ingest_count": 1,
        "promote_to_shared_count": 0,
        "provider_session_binding_only_count": 0,
        "blocked_count": 1,
        "live_trace_proof": False,
        "write_policy": "governed_rest_ingest_only",
        "plans": [
            {
                "plan_id": "task-write",
                "scope": "task",
                "event_kind": "blueprint_frozen",
                "status": "ok",
                "decision": "ingest",
                "proof_level": "contract_proof",
                "target_namespace_uri": "memory://conversation/conv-1",
                "shared_namespace_uri": None,
                "memory_layer": "task_state",
                "reviewed": False,
                "write_request_allowed": True,
                "source_refs": ["blueprint:bp-1"],
                "blocked_reason": None,
                "next_action": None,
            },
            {
                "plan_id": "blocked-shared",
                "scope": "shared",
                "event_kind": "decision_rationale",
                "status": "blocked",
                "decision": "blocked",
                "proof_level": "manual_gap",
                "target_namespace_uri": "memory://conversation/conv-1",
                "shared_namespace_uri": "memory://global/shared/iiyazu/Cross-Muse",
                "memory_layer": "task_state",
                "reviewed": False,
                "write_request_allowed": False,
                "source_refs": ["message:m1"],
                "blocked_reason": "shared promotion requires explicit review",
                "next_action": (
                    "Attach review evidence before promoting memory beyond task scope."
                ),
            },
        ],
    }


def test_tui_vision_read_model_projects_deliberation_transcript_details() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "decision": "blocked",
            "authority": "replay_index_only",
            "sections": [
                {
                    "section_id": "deliberation_transcript",
                    "status": "manual_gap",
                    "proof_level": "manual_gap",
                    "source_authority": "operator_transcript_v1",
                    "source_refs": ["conversation:conv-prod-1"],
                    "artifacts": ["artifact://deliberation-transcript.json"],
                    "details": {
                        "deliberation_transcript": {
                            "authority": "operator_transcript_v1",
                            "conversation_id": "conv-prod-1",
                            "message_count": 2,
                            "distinct_god_count": 2,
                            "god_ids": ["architect-god", "review-god"],
                            "speech_act_counts": {"challenge": 1, "propose": 1},
                            "natural_deliberation": True,
                            "real_provider_proof": True,
                            "runtime_required": True,
                            "runtime_artifact_attached": False,
                            "runtime_peer_god_ready_count": 0,
                            "runtime_blocked_count": 2,
                            "missing_provider_session_god_ids": ["review-god"],
                            "blocker_count": 1,
                        }
                    },
                }
            ],
            "blockers": [],
        },
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["deliberation_transcript"] == {
        "authority": "operator_transcript_v1",
        "conversation_id": "conv-prod-1",
        "message_count": 2,
        "distinct_god_count": 2,
        "god_ids": ["architect-god", "review-god"],
        "speech_act_counts": {"challenge": 1, "propose": 1},
        "natural_deliberation": True,
        "real_provider_proof": True,
        "runtime_required": True,
        "runtime_artifact_attached": False,
        "runtime_peer_god_ready_count": 0,
        "runtime_blocked_count": 2,
        "missing_provider_session_god_ids": ["review-god"],
        "blocker_count": 1,
    }


def test_tui_vision_read_model_projects_supervisor_details() -> None:
    model = build_tui_vision_read_model(
        replay_bundle={
            "schema_version": "xmuse.overnight_replay_bundle.v1",
            "decision": "blocked",
            "authority": "replay_index_only",
            "sections": [
                {
                    "section_id": "supervisor",
                    "status": "ok",
                    "proof_level": "contract_proof",
                    "source_authority": "overnight_operator_supervisor",
                    "source_refs": ["overnight_supervisor:overnight-prod"],
                    "artifacts": ["artifact://supervisor-production-evidence.json"],
                    "details": {
                        "supervisor": {
                            "authority": "overnight_operator_supervisor",
                            "run_id": "overnight-prod",
                            "current_stage_id": "S7",
                            "selected_stage_id": "S6",
                            "stage_count": 7,
                            "heartbeat_count": 9,
                            "checkpoint_count": 4,
                            "manual_gap_count": 1,
                            "self_review_count": 3,
                            "blocked_fallback_count": 2,
                            "virtual_soak_count": 1,
                            "latest_heartbeat_stage_id": "S7",
                            "latest_checkpoint_stage_id": "S6",
                            "latest_blocked_stage_id": "S4",
                            "latest_virtual_soak_run_id": "overnight-prod-soak",
                            "latest_virtual_soak_slo_status": "violated",
                        }
                    },
                }
            ],
            "blockers": [],
        },
    )

    assert model["proof_cockpit"]["supervisor"] == {
        "authority": "overnight_operator_supervisor",
        "run_id": "overnight-prod",
        "current_stage_id": "S7",
        "selected_stage_id": "S6",
        "stage_count": 7,
        "heartbeat_count": 9,
        "checkpoint_count": 4,
        "manual_gap_count": 1,
        "self_review_count": 3,
        "blocked_fallback_count": 2,
        "virtual_soak_count": 1,
        "latest_heartbeat_stage_id": "S7",
        "latest_checkpoint_stage_id": "S6",
        "latest_blocked_stage_id": "S4",
        "latest_virtual_soak_run_id": "overnight-prod-soak",
        "latest_virtual_soak_slo_status": "violated",
    }


def test_tui_vision_read_model_projects_supervisor_goal_stage_results() -> None:
    model = build_tui_vision_read_model(
        overnight_supervisor={
            "schema_version": "xmuse.overnight_supervisor.v1",
            "run_id": "overnight-stage-spine",
            "virtual_soaks": [
                {
                    "schema_version": "xmuse.overnight_virtual_soak.v1",
                    "run_id": "overnight-stage-spine",
                    "total_minutes": 480,
                    "slo_status": "violated",
                    "slo_violations": [
                        "heartbeat gap 20m exceeds 15m",
                    ],
                }
            ],
            "goal_stage_results": [
                {
                    "stage_id": "S1",
                    "status": "ok",
                    "proof_level": "contract_proof",
                    "engine": "opencode",
                    "source_authority": "goal_stage_harness",
                    "result_path": "/tmp/goal-runs/S1/result.json",
                },
                {
                    "stage_id": "S4",
                    "status": "blocked",
                    "proof_level": "manual_gap",
                    "engine": "codex",
                    "source_authority": "goal_stage_harness",
                    "result_path": "/tmp/goal-runs/S4/result.json",
                    "blocked_reason": "goal stage result is blocked: GitHub review truth missing",
                    "next_stage_id": "S7",
                },
            ],
        }
    )

    cockpit = model["proof_cockpit"]
    assert cockpit["proof_level"] == "contract_proof"
    assert cockpit["fact_state"] == "blocked"
    assert cockpit["source_authority"] == ["xmuse.overnight_supervisor.v1"]
    assert cockpit["stage_result_summary"] == {
        "ok": 1,
        "blocked": 1,
        "manual_gap": 0,
        "retry": 0,
        "total": 2,
    }
    assert cockpit["virtual_soak_summary"] == {
        "ok": 0,
        "violated": 1,
        "total": 1,
    }
    assert cockpit["latest_virtual_soak"] == {
        "run_id": "overnight-stage-spine",
        "total_minutes": 480,
        "slo_status": "violated",
        "slo_violations": ["heartbeat gap 20m exceeds 15m"],
    }
    assert cockpit["blockers"] == [
        {
            "kind": "virtual_soak",
            "id": "overnight-stage-spine",
            "reason": "heartbeat gap 20m exceeds 15m",
            "owner": "codex",
            "next_action": (
                "Reduce heartbeat/self-review intervals or fix supervisor "
                "scheduling, then rerun the overnight virtual soak."
            ),
        },
        {
            "kind": "goal_stage_result",
            "id": "S4",
            "reason": "goal stage result is blocked: GitHub review truth missing",
            "owner": "codex",
            "next_action": "Continue via dependency-aware fallback to S7.",
        },
    ]
    assert cockpit["stage_results"] == [
        {
            "stage_id": "S1",
            "status": "ok",
            "proof_level": "contract_proof",
            "engine": "opencode",
            "source_authority": "goal_stage_harness",
            "result_path": "/tmp/goal-runs/S1/result.json",
            "blocked_reason": None,
            "next_stage_id": None,
        },
        {
            "stage_id": "S4",
            "status": "blocked",
            "proof_level": "manual_gap",
            "engine": "codex",
            "source_authority": "goal_stage_harness",
            "result_path": "/tmp/goal-runs/S4/result.json",
            "blocked_reason": "goal stage result is blocked: GitHub review truth missing",
            "next_stage_id": "S7",
        },
    ]
    assert cockpit["artifacts"] == [
        "/tmp/goal-runs/S1/result.json",
        "/tmp/goal-runs/S4/result.json",
    ]
    assert cockpit["source_refs"] == [
        "overnight_virtual_soak:overnight-stage-spine",
        "goal_stage:S1",
        "goal_stage_result:/tmp/goal-runs/S1/result.json",
        "goal_stage:S4",
        "goal_stage_result:/tmp/goal-runs/S4/result.json",
    ]


def test_tui_vision_read_model_reports_proof_cockpit_manual_gap_without_artifacts() -> None:
    model = build_tui_vision_read_model()

    assert model["proof_cockpit"]["proof_level"] == "manual_gap"
    assert model["proof_cockpit"]["fact_state"] == "manual_gap"
    assert model["proof_cockpit"]["manual_gap_reason"] == (
        "overnight replay bundle and release evidence pack unavailable"
    )


def test_tui_vision_read_model_uses_inspector_optional_evidence() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        inspector={
            "memory_trace": {
                "session_id": "mem-session-2",
                "trace_events": [{"event": "ingest"}],
                "proof_level": "live_service_proof",
            },
            "github_truth": {
                "proof_level": "manual_gap",
                "manual_gap_reason": "branch protection snapshot unavailable",
            },
            "provider_runtime": [
                {
                    "provider_id": "codex-primary",
                    "runtime_kind": "codex",
                    "transport": "cli",
                    "session_continuity": "active",
                    "waiting_reason": None,
                }
            ],
        },
    )

    assert model["memory"]["session_id"] == "mem-session-2"
    assert model["github"]["manual_gap_reason"] == "branch protection snapshot unavailable"
    assert model["providers"]["items"] == [
        {
            "provider_id": "codex-primary",
            "runtime_kind": "codex",
            "transport": "cli",
            "session_continuity": "active",
            "heartbeat": None,
            "waiting_reason": None,
            "proof_level": "contract_proof",
        }
    ]


def test_state_delta_carries_vision_read_model_into_app_state() -> None:
    vision = build_tui_vision_read_model(conversation_id="conv-1")
    state = AppState()

    state.apply(StateDelta(vision=vision))

    assert state.vision == vision


async def test_adapter_poll_delta_includes_tui_vision_read_model(monkeypatch, tmp_path) -> None:
    adapter = XmuseAdapter(tmp_path)
    envelope = {
        "source_authority": "feature_lanes_projection",
        "projection_revision": 9,
        "items": [
            {
                "lane_id": "lane-a",
                "plan_feature_id": "feature-a",
                "ready": True,
                "blocked": False,
                "scoped_dependency_ids": [],
            }
        ],
    }

    monkeypatch.setattr(
        adapter,
        "poll_messages",
        lambda conv_id: (
            [
                {
                    "id": "msg-1",
                    "conversation_id": conv_id,
                    "envelope_json": {
                        "speech_act": "propose",
                        "target_ref": "blueprint:conv-1:1",
                    },
                }
            ],
            None,
        ),
    )

    async def _poll_worklist_envelope(conv_id: str | None = None):
        return envelope, None

    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "get_participants", lambda conv_id: [])
    monkeypatch.setattr(adapter, "get_conversation_inspector", lambda conv_id: {})

    delta = await adapter.poll_delta("conv-1")

    assert delta.vision["deliberation"]["speech_act_counts"] == {"propose": 1}
    assert delta.vision["execution"]["lane_count"] == 1
    assert delta.vision["execution"]["source_authority"] == "feature_lanes_projection"


async def test_adapter_poll_delta_keeps_vision_from_full_snapshots(
    monkeypatch,
    tmp_path,
) -> None:
    adapter = XmuseAdapter(tmp_path)
    envelope = {
        "source_authority": "feature_lanes_projection",
        "projection_revision": 9,
        "items": [
            {
                "lane_id": "lane-a",
                "plan_feature_id": "feature-a",
                "ready": True,
                "blocked": False,
            }
        ],
    }
    message = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "created_at": "2026-06-11T00:00:00Z",
        "envelope_json": {
            "speech_act": "propose",
            "target_ref": "blueprint:conv-1:1",
        },
    }
    message_calls = 0
    worklist_calls = 0

    def _poll_messages(conv_id):
        nonlocal message_calls
        message_calls += 1
        return ([message], None) if message_calls == 1 else ([], None)

    def _message_snapshot(conv_id):
        return [message]

    async def _poll_worklist_envelope(conv_id: str | None = None):
        nonlocal worklist_calls
        worklist_calls += 1
        return (envelope, None) if worklist_calls == 1 else (None, None)

    monkeypatch.setattr(adapter, "poll_messages", _poll_messages)
    monkeypatch.setattr(adapter, "_message_snapshot", _message_snapshot, raising=False)
    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)
    monkeypatch.setattr(adapter, "_worklist_envelope_snapshot", lambda conv_id: envelope)
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "get_participants", lambda conv_id: [])
    monkeypatch.setattr(adapter, "get_conversation_inspector", lambda conv_id: {})

    first = await adapter.poll_delta("conv-1")
    second = await adapter.poll_delta("conv-1")

    assert first.vision["deliberation"]["speech_act_counts"] == {"propose": 1}
    assert first.vision["execution"]["lane_count"] == 1
    assert second.messages == []
    assert second.lanes == []
    assert second.lanes_changed is False
    assert second.vision["deliberation"]["speech_act_counts"] == {"propose": 1}
    assert second.vision["execution"]["lane_count"] == 1
