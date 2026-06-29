from __future__ import annotations

import pytest

from xmuse_core.chat.failure_taxonomy import (
    FAILURE_TAXONOMY_VERSION,
    catalog_by_class_id,
    classify_failure_boundary,
)


def test_durable_failure_taxonomy_catalog_covers_rung_2_classes() -> None:
    catalog = catalog_by_class_id()

    assert set(catalog) == {
        "provider_turn_no_writeback_or_timeout",
        "collaboration_callback_or_proposal_failure",
        "review_trigger_timeout_or_rejected_verdict",
        "lane_execution_failure",
        "docs_or_code_gate_failure",
        "branch_behind_or_stale_base_pr_creation",
        "exact_head_ci_failure",
        "guarded_merge_rejection",
        "main_ci_failure",
        "memoryos_unavailable_or_ingest_failure",
        "frontend_projection_gap",
    }
    for failure_class in catalog.values():
        payload = failure_class.to_projection()
        assert payload["taxonomy"] == FAILURE_TAXONOMY_VERSION
        assert payload["class_id"]
        assert payload["label"]
        assert payload["producer"]
        assert payload["consumer"]
        assert payload["condition"]
        assert payload["proof_level"]
        assert payload["failure_boundary"]
        assert payload["next_recovery_action"]


def test_failure_boundary_classifier_uses_existing_durable_evidence_only() -> None:
    classification = classify_failure_boundary(
        {
            "kind": "acceptance_spine",
            "status": "blocked",
            "producer": "chat.db:acceptance_spines",
            "condition": "provider timeout",
            "proof_boundary": "acceptance_spine_blocker_boundary",
            "next_recovery_action": "resume_from_recorded_acceptance_spine_boundary",
        }
    )

    assert classification == {
        "taxonomy": FAILURE_TAXONOMY_VERSION,
        "class_id": "provider_turn_no_writeback_or_timeout",
        "label": "provider turn no-writeback or timeout",
        "producer": "provider adapter / chat dispatch bridge",
        "consumer": "chat.db writeback reconciliation",
        "condition": "provider turn failed to produce durable message, callback, or timeout result",
        "proof_level": "durable xmuse authority gap",
        "failure_boundary": "provider_writeback_boundary",
        "next_recovery_action": (
            "inspect provider run, reconcile writeback, or retry the turn with durable "
            "timeout evidence"
        ),
    }


@pytest.mark.parametrize(
    ("boundary", "class_id"),
    [
        (
            {
                "condition": "provider timeout",
                "proof_boundary": "acceptance_spine_blocker_boundary",
            },
            "provider_turn_no_writeback_or_timeout",
        ),
        (
            {"condition": "proposal_ref_unresolved", "kind": "proposal"},
            "collaboration_callback_or_proposal_failure",
        ),
        (
            {"condition": "review verdict rejected", "kind": "review_verdict"},
            "review_trigger_timeout_or_rejected_verdict",
        ),
        (
            {"condition": "worker crashed", "proof_boundary": "dispatch_failure_boundary"},
            "lane_execution_failure",
        ),
        (
            {"condition": "docs code gate report failed", "kind": "gate_report"},
            "docs_or_code_gate_failure",
        ),
        (
            {"condition": "gate_failed", "proof_boundary": "dispatch_failure_boundary"},
            "docs_or_code_gate_failure",
        ),
        (
            {"condition": "branch-behind stale-base PR creation"},
            "branch_behind_or_stale_base_pr_creation",
        ),
        (
            {"condition": "exact-head CI failed", "kind": "github_gate"},
            "exact_head_ci_failure",
        ),
        (
            {"condition": "required CI head_mismatch"},
            "exact_head_ci_failure",
        ),
        (
            {"condition": "required CI head mismatch"},
            "exact_head_ci_failure",
        ),
        (
            {"condition": "post-merge main CI head mismatch"},
            "exact_head_ci_failure",
        ),
        (
            {"condition": "guarded merge head_mismatch"},
            "exact_head_ci_failure",
        ),
        (
            {"condition": "guarded merge rejected by match-head"},
            "guarded_merge_rejection",
        ),
        (
            {"kind": "main_ci", "condition": "post-merge main CI failed"},
            "main_ci_failure",
        ),
        (
            {"kind": "memoryos_sidecar", "condition": "MemoryOS ingest failed"},
            "memoryos_unavailable_or_ingest_failure",
        ),
        (
            {"kind": "final_action", "condition": "final_action_ref_unresolved"},
            "frontend_projection_gap",
        ),
    ],
)
def test_failure_boundary_classifier_covers_rung_2_boundaries(
    boundary: dict[str, str],
    class_id: str,
) -> None:
    assert classify_failure_boundary(boundary)["class_id"] == class_id
