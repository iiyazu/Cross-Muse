from __future__ import annotations

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerClaimPlan,
)


def apply_feature_graph_worker_claim_plan(
    store: FeatureGraphStatusStore,
    plan: FeatureGraphWorkerClaimPlan,
) -> FeatureGraphExecutionStatusRecord:
    """Apply a coordinator-approved feature worker claim plan."""

    validated = FeatureGraphWorkerClaimPlan.model_validate(plan.model_dump(mode="json"))
    if validated.expected_status is not FeatureGraphExecutionStatus.READY:
        raise ValueError("worker claim plans require ready status")
    if validated.target_status is not FeatureGraphExecutionStatus.RUNNING:
        raise ValueError("worker claim plans target running status")
    return store.claim_ready(
        graph_set_id=validated.graph_set_id,
        feature_graph_id=validated.feature_graph_id,
        worker_session_id=validated.worker_session_id,
        provider_session_binding_ref=validated.provider_session_binding_ref,
        updated_at=validated.updated_at,
        active_lane_ids=list(validated.active_lane_ids),
    )
