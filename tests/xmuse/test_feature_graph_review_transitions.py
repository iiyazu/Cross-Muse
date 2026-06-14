from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_review_transitions import (
    build_feature_graph_review_status_transition_plan,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphReviewCoordinatorAction,
    FeatureReviewVerdict,
    ProviderSessionBindingDegradationEvidence,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _bundle() -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )


def _merge_verdict() -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(_artifact_payload("feature_review_verdict.v1.json"))


def _reviewing_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )
    return status.model_copy(
        update={
            "status_id": "fgstatus_reviewing_demo",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "ready_lane_ids": [],
            "active_lane_ids": [],
            "completed_lane_ids": ["binding-schema"],
            "updated_at": "2026-06-03T02:13:30Z",
        }
    )


def _rework_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_rework_demo",
            "decision": "rework",
            "summary": "Focused verification is missing for stale binding recovery.",
            "blocking_findings": [
                {
                    "finding_id": "finding-stale-binding",
                    "severity": "blocking",
                    "summary": "Missing stale binding recovery coverage.",
                    "evidence_refs": ["logs/gates/provider-binding.json"],
                }
            ],
        }
    )


def _blocked_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_blocked_demo",
            "decision": "blocked",
            "summary": "Cannot review without provider CLI resume behavior evidence.",
            "blocked_missing_inputs": ["Codex CLI resume smoke evidence"],
            "blocked_reason": "Need Codex CLI resume smoke evidence.",
            "blocked_owner": "coordinator",
        }
    )


def _patch_forward_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_patch_forward_demo",
            "decision": "patch_forward",
            "summary": "A one-line import fix can be patched by reviewer under gate.",
            "patch_forward_gate": {
                "risk": "low",
                "reason_not_rework": "The fix is a one-line import in an existing touched file.",
                "allowed_file_refs": ["src/xmuse_core/agents/provider_session_binding.py"],
                "max_files_changed": 1,
                "max_lines_changed": 5,
                "focused_gates_to_rerun": [
                    "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
                ],
                "disallow_new_dependencies": True,
                "disallow_public_contract_changes": True,
            },
        }
    )


def _takeover_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_takeover_demo",
            "decision": "takeover",
            "summary": "Worker session is not recoverable.",
            "takeover_reason": "Provider session binding is stale and worker context is lost.",
            "takeover_triggers": ["worker_unrecoverable", "context_lost"],
        }
    )


def test_review_merge_verdict_builds_graph_status_transition_plan() -> None:
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    assert plan.coordinator_action is FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS
    assert plan.expected_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.target_status is FeatureGraphExecutionStatus.MERGED
    assert plan.target_status_record is not None
    assert plan.target_status_record.status is FeatureGraphExecutionStatus.MERGED
    assert plan.target_status_record.completed_lane_ids == ["binding-schema"]
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_review_status_transition_plan.v1.json"
    )


def test_review_status_transition_preserves_provider_binding_degradations() -> None:
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb_demo:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=binding-schema"],
    )
    current = _reviewing_status().model_copy(
        update={"provider_session_binding_degradations": [degradation]}
    )

    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=current,
        updated_at="2026-06-03T02:14:00Z",
    )

    assert plan.target_status_record is not None
    assert plan.target_status_record.provider_session_binding_degradations == [
        degradation
    ]


def test_review_status_transition_preserves_blueprint_proof_level() -> None:
    current = _reviewing_status().model_copy(
        update={"blueprint_proof_level": "opt_in_live_proof"}
    )

    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=current,
        updated_at="2026-06-03T02:14:00Z",
    )

    assert plan.target_status_record is not None
    assert plan.target_status_record.blueprint_proof_level == "opt_in_live_proof"


def test_review_status_transition_rejects_blueprint_proof_level_mismatch() -> None:
    current = _reviewing_status().model_copy(
        update={"blueprint_proof_level": "opt_in_live_proof"}
    )
    bundle = _bundle().model_copy(update={"blueprint_proof_level": "contract_proof"})

    with pytest.raises(
        ValueError,
        match="evidence bundle blueprint_proof_level must match current status",
    ):
        build_feature_graph_review_status_transition_plan(
            evidence_bundle=bundle,
            verdict=_merge_verdict(),
            current_status=current,
            updated_at="2026-06-03T02:14:00Z",
        )


def test_review_rework_and_blocked_verdicts_build_status_transitions() -> None:
    rework_plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_rework_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )
    blocked_plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_blocked_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    assert rework_plan.target_status is FeatureGraphExecutionStatus.REWORKING
    assert rework_plan.target_status_record is not None
    assert rework_plan.target_status_record.status is FeatureGraphExecutionStatus.REWORKING
    assert blocked_plan.target_status is FeatureGraphExecutionStatus.BLOCKED
    assert blocked_plan.target_status_record is not None
    assert blocked_plan.target_status_record.status is FeatureGraphExecutionStatus.BLOCKED


def test_patch_forward_and_takeover_do_not_build_status_transition_records() -> None:
    patch_plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_patch_forward_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )
    takeover_plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_takeover_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    assert patch_plan.coordinator_action is FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE
    assert patch_plan.target_status is None
    assert patch_plan.target_status_record is None
    assert takeover_plan.coordinator_action is FeatureGraphReviewCoordinatorAction.TAKEOVER_REQUIRED
    assert takeover_plan.target_status is None
    assert takeover_plan.target_status_record is None


def test_review_status_transition_plan_rejects_mismatched_artifacts() -> None:
    mismatched_bundle = _bundle().model_copy(update={"bundle_id": "different-bundle"})

    with pytest.raises(ValueError, match="verdict evidence_bundle_id must match bundle_id"):
        build_feature_graph_review_status_transition_plan(
            evidence_bundle=mismatched_bundle,
            verdict=_merge_verdict(),
            current_status=_reviewing_status(),
            updated_at="2026-06-03T02:14:00Z",
        )


def test_review_status_transition_plan_requires_reviewing_status() -> None:
    running = _reviewing_status().model_copy(
        update={"status": FeatureGraphExecutionStatus.RUNNING}
    )

    with pytest.raises(ValueError, match="review verdict requires reviewing status"):
        build_feature_graph_review_status_transition_plan(
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            current_status=running,
            updated_at="2026-06-03T02:14:00Z",
        )
