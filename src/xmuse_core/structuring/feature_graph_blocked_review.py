from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureReviewDecision,
    FeatureReviewVerdict,
)


def build_feature_graph_blocked_review_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    current_status: FeatureGraphExecutionStatusRecord,
    plan_id: str,
    created_at: str,
) -> FeatureGraphBlockedReviewPlan:
    """Build the coordinator-owned blocked review plan from a blocked verdict."""

    evidence_bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    verdict = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
    current_status = FeatureGraphExecutionStatusRecord.model_validate(
        current_status.model_dump(mode="json")
    )
    if verdict.evidence_bundle_id != evidence_bundle.bundle_id:
        raise ValueError("verdict evidence_bundle_id must match bundle_id")
    if verdict.decision is not FeatureReviewDecision.BLOCKED:
        raise ValueError("blocked review plan requires blocked verdict")
    if current_status.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("blocked review plan requires reviewing status")
    _validate_current_status_identity(evidence_bundle, current_status)
    if (
        not verdict.blocked_missing_inputs
        or verdict.blocked_reason is None
        or verdict.blocked_owner is None
    ):
        raise ValueError(
            "blocked review plan requires missing inputs, blocked reason, and owner"
        )

    return FeatureGraphBlockedReviewPlan(
        plan_id=plan_id,
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        current_status=current_status.status,
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
        target_status=FeatureGraphExecutionStatus.BLOCKED,
        reviewer_session_id=verdict.reviewer_session_id,
        rationale=verdict.summary,
        missing_inputs=list(verdict.blocked_missing_inputs),
        blocked_reason=verdict.blocked_reason,
        blocked_owner=verdict.blocked_owner,
        evidence_refs=list(verdict.evidence_refs),
        created_at=created_at,
    )


def _validate_current_status_identity(
    evidence_bundle: FeatureEvidenceBundle,
    current_status: FeatureGraphExecutionStatusRecord,
) -> None:
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
