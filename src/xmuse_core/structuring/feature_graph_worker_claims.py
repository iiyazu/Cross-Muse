from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerClaimPlan,
)


def build_feature_graph_worker_claim_plan(
    *,
    current_status: FeatureGraphExecutionStatusRecord,
    worker_session_id: str,
    provider_session_binding_ref: str | None,
    updated_at: str,
    active_lane_ids: list[str] | None = None,
) -> FeatureGraphWorkerClaimPlan:
    """Build a coordinator-owned feature graph worker claim plan."""

    current = FeatureGraphExecutionStatusRecord.model_validate(
        current_status.model_dump(mode="json")
    )
    if current.status is not FeatureGraphExecutionStatus.READY:
        raise ValueError("worker claim requires ready status")
    lane_ids = (
        list(active_lane_ids)
        if active_lane_ids is not None
        else list(current.ready_lane_ids)
    )
    return FeatureGraphWorkerClaimPlan(
        plan_id=_claim_plan_id(
            graph_set_id=current.graph_set_id,
            feature_graph_id=current.feature_graph_id,
            worker_session_id=worker_session_id,
            updated_at=updated_at,
        ),
        graph_set_id=current.graph_set_id,
        graph_set_version=current.graph_set_version,
        feature_plan_id=current.feature_plan_id,
        feature_plan_version=current.feature_plan_version,
        feature_id=current.feature_id,
        feature_graph_id=current.feature_graph_id,
        current_status=current.status,
        expected_status=FeatureGraphExecutionStatus.READY,
        target_status=FeatureGraphExecutionStatus.RUNNING,
        worker_session_id=worker_session_id,
        provider_session_binding_ref=provider_session_binding_ref,
        active_lane_ids=lane_ids,
        source_status_id=current.status_id,
        updated_at=updated_at,
    )


def _claim_plan_id(
    *,
    graph_set_id: str,
    feature_graph_id: str,
    worker_session_id: str,
    updated_at: str,
) -> str:
    return (
        f"fgwclaim:{graph_set_id}:{feature_graph_id}:"
        f"{worker_session_id}:{_safe_updated_at(updated_at)}"
    )


def _safe_updated_at(updated_at: str) -> str:
    return (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
