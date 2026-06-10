from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerEvidenceSubmissionPlan,
)


def build_feature_graph_worker_evidence_submission_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
    evidence_bundle_ref: str,
    updated_at: str,
) -> FeatureGraphWorkerEvidenceSubmissionPlan:
    """Build a coordinator-owned plan for worker evidence handoff to review."""

    bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    current = FeatureGraphExecutionStatusRecord.model_validate(
        current_status.model_dump(mode="json")
    )
    _validate_submission_inputs(bundle, current)
    target_record = _target_status_record(
        evidence_bundle=bundle,
        current_status=current,
        updated_at=updated_at,
    )
    return FeatureGraphWorkerEvidenceSubmissionPlan(
        plan_id=_submission_plan_id(
            evidence_bundle_id=bundle.bundle_id,
            graph_set_id=bundle.graph_set_id,
            feature_graph_id=bundle.feature_graph_id,
            updated_at=updated_at,
        ),
        evidence_bundle_id=bundle.bundle_id,
        evidence_bundle_ref=evidence_bundle_ref,
        graph_set_id=bundle.graph_set_id,
        graph_set_version=bundle.graph_set_version,
        feature_plan_id=bundle.feature_plan_id,
        feature_plan_version=bundle.feature_plan_version,
        feature_id=bundle.feature_id,
        feature_graph_id=bundle.feature_graph_id,
        current_status=current.status,
        expected_status=FeatureGraphExecutionStatus.RUNNING,
        target_status=FeatureGraphExecutionStatus.REVIEWING,
        worker_session_id=bundle.worker_session_id,
        provider_session_binding_ref=bundle.provider_session_binding_ref,
        source_status_id=current.status_id,
        evidence_refs=[evidence_bundle_ref],
        target_status_record=target_record,
        updated_at=updated_at,
    )


def _validate_submission_inputs(
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
) -> None:
    if current_status.status is not FeatureGraphExecutionStatus.RUNNING:
        raise ValueError("worker evidence submission requires running status")
    identity_pairs = (
        ("conversation_id", current_status.conversation_id, evidence_bundle.conversation_id),
        ("planning_run_id", current_status.planning_run_id, evidence_bundle.planning_run_id),
        ("graph_set_id", current_status.graph_set_id, evidence_bundle.graph_set_id),
        (
            "graph_set_version",
            current_status.graph_set_version,
            evidence_bundle.graph_set_version,
        ),
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
    if current_status.active_worker_session_id != evidence_bundle.worker_session_id:
        raise ValueError("current status active_worker_session_id must match evidence bundle")
    if (
        current_status.active_provider_session_binding_ref
        != evidence_bundle.provider_session_binding_ref
    ):
        raise ValueError(
            "current status active_provider_session_binding_ref must match evidence bundle"
        )


def _target_status_record(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=_feature_graph_status_id(
            graph_set_id=evidence_bundle.graph_set_id,
            feature_graph_id=evidence_bundle.feature_graph_id,
            status=FeatureGraphExecutionStatus.REVIEWING,
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
        status=FeatureGraphExecutionStatus.REVIEWING,
        ready_lane_ids=[],
        active_lane_ids=[],
        active_worker_session_id=evidence_bundle.worker_session_id,
        active_provider_session_binding_ref=evidence_bundle.provider_session_binding_ref,
        completed_lane_ids=list(evidence_bundle.lane_graph_summary.completed_lane_ids),
        blocked_lane_ids=list(evidence_bundle.lane_graph_summary.blocked_lane_ids),
        projection_lane_ids=list(current_status.projection_lane_ids),
        feature_lanes_projection_ref=current_status.feature_lanes_projection_ref,
        provider_session_binding_degradations=list(
            current_status.provider_session_binding_degradations
        ),
        updated_at=updated_at,
    )


def _submission_plan_id(
    *,
    evidence_bundle_id: str,
    graph_set_id: str,
    feature_graph_id: str,
    updated_at: str,
) -> str:
    return (
        f"fgwesp:{evidence_bundle_id}:{graph_set_id}:{feature_graph_id}:"
        f"reviewing:{_safe_updated_at(updated_at)}"
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
