from __future__ import annotations

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerEvidenceSubmissionPlan,
)


def apply_feature_graph_worker_evidence_submission_plan(
    store: FeatureGraphStatusStore,
    plan: FeatureGraphWorkerEvidenceSubmissionPlan,
) -> FeatureGraphExecutionStatusRecord:
    """Apply a coordinator-approved worker evidence submission plan."""

    validated = FeatureGraphWorkerEvidenceSubmissionPlan.model_validate(
        plan.model_dump(mode="json")
    )
    if validated.expected_status is not FeatureGraphExecutionStatus.RUNNING:
        raise ValueError("worker evidence submission plans require running status")
    if validated.target_status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("worker evidence submission plans target reviewing status")
    return store.transition(
        validated.target_status_record,
        expected_status=validated.expected_status,
    )
