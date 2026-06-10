from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.models import (
    ReviewGodTakeoverAction,
    ReviewGodTakeoverContextContract,
    ReviewGodTakeoverDecision,
)


def _base_takeover_decision(action: str = "repair_and_merge") -> dict:
    return {
        "lane_id": "lane-takeover",
        "action": action,
        "summary": "Review GOD resolved the failed lane.",
        "evidence": {
            "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
            "change_ref": "logs/diffs/lane-takeover.patch",
            "verification_ref": "logs/gates/lane-takeover/report.json",
            "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
            "audit_event_ref": "xmuse/audit/lane-takeover.json",
            "chat_card_ref": "xmuse/chat/cards/lane-takeover.json",
        },
    }


def _base_takeover_context_contract() -> dict:
    return {
        "schema_version": "takeover-context-contract/v1",
        "lane_id": "lane-takeover",
        "attempt": {
            "takeover_attempt_id": "takeover-attempt-1",
            "retry_count": 2,
            "review_retry_count": 1,
        },
        "lease": {
            "lease_id": "lease-1",
            "lease_owner": "runner-1",
            "lease_expires_at": "2026-06-01T12:34:56Z",
        },
        "projection": {
            "projection_revision": 7,
            "projection_source": "feature_lanes.json",
        },
        "lane": {
            "lane_id": "lane-takeover",
            "lane_status": "exec_failed",
            "graph_id": "graph-1",
            "conversation_id": "conv-1",
        },
        "evidence": {
            "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
            "lane_context_ref": "logs/lane_context/lane-takeover/latest.json",
            "lane_context_hash": "lane-context-hash",
            "evidence_bundle_id": "evbundle_123",
            "evidence_bundle_hash": "evidence-bundle-hash",
            "gate_report_refs": ["logs/gates/lane-takeover/report.json"],
            "review_history_refs": ["lane.review_history[0]"],
            "worker_diff_refs": ["logs/diffs/lane-takeover.patch"],
        },
        "graph_set": {
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-1",
        },
        "feature_plan": {
            "feature_plan_id": "plan-1",
            "plan_feature_id": "feature-1",
        },
        "max_attempt": {
            "max_attempts_by_reason": {"execution_infra_failure": 2},
            "takeover_attempt_cap": 3,
            "cooldown_seconds": 90,
            "terminal_escalation_policy": "escalate_to_human_or_outer_god",
        },
    }


def test_takeover_action_contract_supports_spec_actions_and_alias_normalization() -> None:
    supported = {
        action.value for action in ReviewGodTakeoverAction
    }

    assert supported == {
        "repair_and_merge",
        "requeue_with_context",
        "abandon_lane",
        "self_correction_then_abandon",
        "escalate_to_human_or_outer_god",
    }

    normalized = ReviewGodTakeoverDecision.model_validate(
        _base_takeover_decision(action="escalate")
    )

    assert normalized.action is ReviewGodTakeoverAction.ESCALATE_TO_HUMAN_OR_OUTER_GOD


def test_takeover_action_contract_requires_required_evidence_refs() -> None:
    payload = _base_takeover_decision()
    del payload["evidence"]["chat_card_ref"]

    with pytest.raises(ValidationError, match="chat_card_ref"):
        ReviewGodTakeoverDecision.model_validate(payload)


def test_takeover_action_contract_requires_abandon_metadata() -> None:
    with pytest.raises(ValidationError, match="abandon_reason"):
        ReviewGodTakeoverDecision.model_validate(
            _base_takeover_decision(action="abandon_lane")
        )


def test_takeover_action_contract_requires_self_correction_audit_fields() -> None:
    payload = _base_takeover_decision(action="self_correction_then_abandon")
    payload.update(
        {
            "abandon_reason": "Wrong subsystem",
            "impact": "Lane is invalid and must stop.",
            "replacement_required": True,
            "feature_gap_implications": "Coverage remains open until replacement lane exists.",
        }
    )

    with pytest.raises(ValidationError, match="review_self_correction"):
        ReviewGodTakeoverDecision.model_validate(payload)


def test_takeover_context_contract_requires_guard_sections() -> None:
    contract = ReviewGodTakeoverContextContract.model_validate(
        _base_takeover_context_contract()
    )

    assert contract.attempt.takeover_attempt_id == "takeover-attempt-1"
    assert contract.lease.lease_owner == "runner-1"
    assert contract.projection.projection_revision == 7
    assert contract.evidence.evidence_bundle_id == "evbundle_123"
    assert contract.graph_set.graph_set_id == "graph-set-1"
    assert contract.feature_plan.plan_feature_id == "feature-1"
    assert contract.max_attempt.max_attempts_by_reason == {
        "execution_infra_failure": 2
    }


def test_takeover_context_contract_rejects_missing_guard_sections() -> None:
    payload = _base_takeover_context_contract()
    del payload["lease"]

    with pytest.raises(ValidationError, match="lease"):
        ReviewGodTakeoverContextContract.model_validate(payload)


def test_takeover_context_contract_rejects_empty_max_attempt_policy() -> None:
    payload = _base_takeover_context_contract()
    payload["max_attempt"]["max_attempts_by_reason"] = {}

    with pytest.raises(ValidationError, match="max_attempts_by_reason"):
        ReviewGodTakeoverContextContract.model_validate(payload)


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("lease", "lease_id"),
        ("lease", "lease_owner"),
        ("lease", "lease_expires_at"),
        ("evidence", "evidence_bundle_id"),
        ("evidence", "evidence_bundle_hash"),
        ("graph_set", "graph_set_id"),
        ("feature_plan", "feature_plan_id"),
        ("max_attempt", "max_attempts_by_reason"),
        ("max_attempt", "takeover_attempt_cap"),
        ("max_attempt", "cooldown_seconds"),
        ("max_attempt", "terminal_escalation_policy"),
    ],
)
def test_takeover_context_contract_rejects_missing_required_guard_fields(
    section: str,
    field: str,
) -> None:
    payload = _base_takeover_context_contract()
    del payload[section][field]

    with pytest.raises(ValidationError, match=field):
        ReviewGodTakeoverContextContract.model_validate(payload)
