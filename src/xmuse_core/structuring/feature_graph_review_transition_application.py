from __future__ import annotations

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphExecutionStatusRecord,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
)


def apply_feature_graph_review_status_transition_plan(
    store: FeatureGraphStatusStore,
    plan: FeatureGraphReviewStatusTransitionPlan,
) -> FeatureGraphExecutionStatusRecord:
    """Apply a coordinator-approved review status transition plan.

    Patch-forward and takeover plans are intentionally not applied here; they
    must pass their coordinator gates before any durable status write happens.
    """

    validated = FeatureGraphReviewStatusTransitionPlan.model_validate(
        plan.model_dump(mode="json")
    )
    if validated.coordinator_action is not FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS:
        raise ValueError("only transition_status review plans can be applied")
    if validated.target_status_record is None:
        raise ValueError("transition_status review plans require target_status_record")
    return store.transition(
        validated.target_status_record,
        expected_status=validated.expected_status,
    )
