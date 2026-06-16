from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
    FeatureReviewDecision,
    FeatureReviewVerdict,
)


def build_feature_graph_review_status_transition_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    current_status: FeatureGraphExecutionStatusRecord,
    updated_at: str,
) -> FeatureGraphReviewStatusTransitionPlan:
    """Build the coordinator-owned status action implied by a review verdict."""

    _validate_review_inputs(evidence_bundle, verdict, current_status)
    coordinator_action = _coordinator_action_for_decision(verdict.decision)
    target_status = _target_status_for_decision(verdict.decision)
    target_record = (
        _target_status_record(
            evidence_bundle=evidence_bundle,
            current_status=current_status,
            target_status=target_status,
            updated_at=updated_at,
        )
        if target_status is not None
        else None
    )
    return FeatureGraphReviewStatusTransitionPlan(
        plan_id=_transition_plan_id(
            verdict_id=verdict.verdict_id,
            graph_set_id=evidence_bundle.graph_set_id,
            feature_graph_id=evidence_bundle.feature_graph_id,
            decision=verdict.decision,
            target_status=target_status,
            updated_at=updated_at,
        ),
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        decision=verdict.decision,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        current_status=current_status.status,
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
        target_status=target_status,
        coordinator_action=coordinator_action,
        rationale=verdict.summary,
        evidence_refs=list(verdict.evidence_refs),
        target_status_record=target_record,
        updated_at=updated_at,
    )


def _validate_review_inputs(
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    current_status: FeatureGraphExecutionStatusRecord,
) -> None:
    if verdict.evidence_bundle_id != evidence_bundle.bundle_id:
        raise ValueError("verdict evidence_bundle_id must match bundle_id")
    if current_status.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("review verdict requires reviewing status")
    identity_pairs = (
        ("graph_set_id", current_status.graph_set_id, evidence_bundle.graph_set_id),
        ("graph_set_version", current_status.graph_set_version, evidence_bundle.graph_set_version),
        ("feature_plan_id", current_status.feature_plan_id, evidence_bundle.feature_plan_id),
        (
            "feature_plan_version",
            current_status.feature_plan_version,
            evidence_bundle.feature_plan_version,
        ),
        ("feature_id", current_status.feature_id, evidence_bundle.feature_id),
        ("feature_graph_id", current_status.feature_graph_id, evidence_bundle.feature_graph_id),
    )
    for field_name, current_value, bundle_value in identity_pairs:
        if current_value != bundle_value:
            raise ValueError(f"current status {field_name} must match evidence bundle")


def _coordinator_action_for_decision(
    decision: FeatureReviewDecision,
) -> FeatureGraphReviewCoordinatorAction:
    if decision in {
        FeatureReviewDecision.MERGE,
        FeatureReviewDecision.REWORK,
        FeatureReviewDecision.BLOCKED,
    }:
        return FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS
    if decision is FeatureReviewDecision.PATCH_FORWARD:
        return FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE
    if decision is FeatureReviewDecision.TAKEOVER:
        return FeatureGraphReviewCoordinatorAction.TAKEOVER_REQUIRED
    raise ValueError(f"unsupported feature review decision: {decision.value}")


def _target_status_for_decision(
    decision: FeatureReviewDecision,
) -> FeatureGraphExecutionStatus | None:
    if decision is FeatureReviewDecision.MERGE:
        return FeatureGraphExecutionStatus.MERGED
    if decision is FeatureReviewDecision.REWORK:
        return FeatureGraphExecutionStatus.REWORKING
    if decision is FeatureReviewDecision.BLOCKED:
        return FeatureGraphExecutionStatus.BLOCKED
    if decision in {
        FeatureReviewDecision.PATCH_FORWARD,
        FeatureReviewDecision.TAKEOVER,
    }:
        return None
    raise ValueError(f"unsupported feature review decision: {decision.value}")


def _target_status_record(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
    target_status: FeatureGraphExecutionStatus,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    blueprint_proof_level = _resolve_blueprint_proof_level(
        evidence_bundle,
        current_status,
    )
    return FeatureGraphExecutionStatusRecord(
        status_id=_feature_graph_status_id(
            graph_set_id=evidence_bundle.graph_set_id,
            feature_graph_id=evidence_bundle.feature_graph_id,
            status=target_status,
            updated_at=updated_at,
        ),
        conversation_id=evidence_bundle.conversation_id,
        planning_run_id=evidence_bundle.planning_run_id,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_plan_id=evidence_bundle.feature_plan_id,
        feature_plan_version=evidence_bundle.feature_plan_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        blueprint_proof_level=blueprint_proof_level,
        status=target_status,
        ready_lane_ids=[],
        active_lane_ids=[],
        completed_lane_ids=_target_completed_lane_ids(
            evidence_bundle=evidence_bundle,
            current_status=current_status,
            target_status=target_status,
        ),
        blocked_lane_ids=list(current_status.blocked_lane_ids),
        projection_lane_ids=list(current_status.projection_lane_ids),
        feature_lanes_projection_ref=current_status.feature_lanes_projection_ref,
        provider_session_binding_degradations=list(
            current_status.provider_session_binding_degradations
        ),
        updated_at=updated_at,
    )


def _resolve_blueprint_proof_level(
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
) -> str | None:
    bundle_level = evidence_bundle.blueprint_proof_level
    current_level = current_status.blueprint_proof_level
    if bundle_level is not None and current_level is not None and bundle_level != current_level:
        raise ValueError("evidence bundle blueprint_proof_level must match current status")
    return bundle_level if bundle_level is not None else current_level


def _target_completed_lane_ids(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
    target_status: FeatureGraphExecutionStatus,
) -> list[str]:
    if target_status is FeatureGraphExecutionStatus.MERGED:
        return list(evidence_bundle.lane_graph_summary.completed_lane_ids)
    return list(current_status.completed_lane_ids)


def _transition_plan_id(
    *,
    verdict_id: str,
    graph_set_id: str,
    feature_graph_id: str,
    decision: FeatureReviewDecision,
    target_status: FeatureGraphExecutionStatus | None,
    updated_at: str,
) -> str:
    action_fragment = target_status.value if target_status is not None else decision.value
    return (
        f"fgrstp:{verdict_id}:{graph_set_id}:{feature_graph_id}:"
        f"{action_fragment}:{_safe_updated_at(updated_at)}"
    )


def _feature_graph_status_id(
    *,
    graph_set_id: str,
    feature_graph_id: str,
    status: FeatureGraphExecutionStatus,
    updated_at: str,
) -> str:
    return (
        f"fgs:{graph_set_id}:{feature_graph_id}:{status.value}:"
        f"{_safe_updated_at(updated_at)}"
    )


def _safe_updated_at(updated_at: str) -> str:
    return (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
