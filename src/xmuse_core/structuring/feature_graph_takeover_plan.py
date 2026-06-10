from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureReviewDecision,
    FeatureReviewVerdict,
)


def build_feature_graph_takeover_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    current_status: FeatureGraphExecutionStatusRecord,
    plan_id: str,
    created_at: str,
) -> FeatureGraphTakeoverPlan:
    """Build the coordinator gate plan for a reviewer takeover request."""

    evidence_bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    verdict = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
    current_status = FeatureGraphExecutionStatusRecord.model_validate(
        current_status.model_dump(mode="json")
    )
    if verdict.evidence_bundle_id != evidence_bundle.bundle_id:
        raise ValueError("verdict evidence_bundle_id must match bundle_id")
    if verdict.decision is not FeatureReviewDecision.TAKEOVER:
        raise ValueError("takeover plan requires takeover verdict")
    if current_status.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("takeover plan requires reviewing status")
    _validate_current_status_identity(evidence_bundle, current_status)
    if verdict.takeover_reason is None or not verdict.takeover_triggers:
        raise ValueError("takeover plan requires takeover reason and triggers")

    return FeatureGraphTakeoverPlan(
        plan_id=plan_id,
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        current_status=current_status.status,
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
        reviewer_session_id=verdict.reviewer_session_id,
        takeover_reason=verdict.takeover_reason,
        takeover_triggers=list(verdict.takeover_triggers),
        failed_worker_session_id=evidence_bundle.worker_session_id,
        failed_provider_session_binding_ref=evidence_bundle.provider_session_binding_ref,
        evidence_refs=list(verdict.evidence_refs),
        created_at=created_at,
    )


def build_feature_graph_takeover_decision(
    *,
    plan: FeatureGraphTakeoverPlan,
    decision_id: str,
    approved: bool,
    takeover_worker_session_id: str | None,
    takeover_provider_session_binding_ref: str | None,
    gate_refs: list[str] | None,
    failure_reasons: list[str] | None,
    checked_at: str,
) -> FeatureGraphTakeoverDecision:
    """Build the coordinator gate decision for a feature graph takeover plan."""

    plan = FeatureGraphTakeoverPlan.model_validate(plan.model_dump(mode="json"))
    return FeatureGraphTakeoverDecision(
        decision_id=decision_id,
        plan_id=plan.plan_id,
        verdict_id=plan.verdict_id,
        evidence_bundle_id=plan.evidence_bundle_id,
        graph_set_id=plan.graph_set_id,
        graph_set_version=plan.graph_set_version,
        feature_id=plan.feature_id,
        feature_graph_id=plan.feature_graph_id,
        takeover_reason=plan.takeover_reason,
        takeover_triggers=list(plan.takeover_triggers),
        approved=approved,
        takeover_worker_session_id=takeover_worker_session_id,
        takeover_provider_session_binding_ref=takeover_provider_session_binding_ref,
        gate_refs=list(gate_refs or []),
        failure_reasons=list(failure_reasons or []),
        checked_at=checked_at,
    )


def build_feature_graph_takeover_handoff(
    *,
    decision: FeatureGraphTakeoverDecision,
    handoff_id: str,
    decision_ref: str,
    created_at: str,
) -> FeatureGraphTakeoverHandoff:
    """Build the coordinator-owned handoff for approved takeover execution.

    The handoff is only an input artifact for a later takeover worker. It does
    not start a worker, acquire a worktree lease, or transition graph status.
    """

    decision = FeatureGraphTakeoverDecision.model_validate(
        decision.model_dump(mode="json")
    )
    if not decision.approved:
        raise ValueError("takeover handoff requires approved decision")
    if decision.takeover_worker_session_id is None:
        raise ValueError("takeover handoff requires takeover_worker_session_id")
    if decision.takeover_provider_session_binding_ref is None:
        raise ValueError("takeover handoff requires takeover_provider_session_binding_ref")
    return FeatureGraphTakeoverHandoff(
        handoff_id=handoff_id,
        decision_id=decision.decision_id,
        plan_id=decision.plan_id,
        verdict_id=decision.verdict_id,
        evidence_bundle_id=decision.evidence_bundle_id,
        graph_set_id=decision.graph_set_id,
        graph_set_version=decision.graph_set_version,
        feature_id=decision.feature_id,
        feature_graph_id=decision.feature_graph_id,
        takeover_worker_session_id=decision.takeover_worker_session_id,
        takeover_provider_session_binding_ref=(
            decision.takeover_provider_session_binding_ref
        ),
        takeover_reason=decision.takeover_reason,
        takeover_triggers=list(decision.takeover_triggers),
        gate_refs=list(decision.gate_refs),
        takeover_input_refs=[
            decision_ref,
            *decision.gate_refs,
            decision.takeover_provider_session_binding_ref,
        ],
        required_takeover_checks=[
            "verify_takeover_decision_approved",
            "verify_takeover_worker_session_binding",
            "verify_takeover_worktree_lease",
            "verify_failed_worker_is_not_resumed",
        ],
        created_at=created_at,
    )


def build_feature_graph_takeover_outcome(
    *,
    handoff: FeatureGraphTakeoverHandoff,
    outcome_id: str,
    changed_file_refs: list[str] | None,
    evidence_refs: list[str] | None,
    verification_refs: list[str] | None,
    output_summary: str,
    completed: bool,
    failure_reasons: list[str] | None,
    created_at: str,
) -> FeatureGraphTakeoverOutcome:
    """Build a takeover worker output artifact for coordinator review.

    The outcome records what the takeover worker produced. It does not merge
    code, run merge guard, or transition graph-native status.
    """

    handoff = FeatureGraphTakeoverHandoff.model_validate(
        handoff.model_dump(mode="json")
    )
    return FeatureGraphTakeoverOutcome(
        outcome_id=outcome_id,
        handoff_id=handoff.handoff_id,
        decision_id=handoff.decision_id,
        plan_id=handoff.plan_id,
        verdict_id=handoff.verdict_id,
        evidence_bundle_id=handoff.evidence_bundle_id,
        graph_set_id=handoff.graph_set_id,
        graph_set_version=handoff.graph_set_version,
        feature_id=handoff.feature_id,
        feature_graph_id=handoff.feature_graph_id,
        takeover_worker_session_id=handoff.takeover_worker_session_id,
        takeover_provider_session_binding_ref=(
            handoff.takeover_provider_session_binding_ref
        ),
        changed_file_refs=list(changed_file_refs or []),
        evidence_refs=list(evidence_refs or []),
        verification_refs=list(verification_refs or []),
        output_summary=output_summary,
        completed=completed,
        failure_reasons=list(failure_reasons or []),
        created_at=created_at,
    )


def build_feature_graph_takeover_review_handoff(
    *,
    outcome: FeatureGraphTakeoverOutcome,
    review_handoff_id: str,
    outcome_ref: str,
    created_at: str,
) -> FeatureGraphTakeoverReviewHandoff:
    """Build the follow-up review input after a completed takeover outcome."""

    outcome = FeatureGraphTakeoverOutcome.model_validate(
        outcome.model_dump(mode="json")
    )
    if not outcome.completed:
        raise ValueError("takeover review handoff requires completed outcome")
    return FeatureGraphTakeoverReviewHandoff(
        review_handoff_id=review_handoff_id,
        outcome_id=outcome.outcome_id,
        takeover_handoff_id=outcome.handoff_id,
        decision_id=outcome.decision_id,
        plan_id=outcome.plan_id,
        verdict_id=outcome.verdict_id,
        evidence_bundle_id=outcome.evidence_bundle_id,
        graph_set_id=outcome.graph_set_id,
        graph_set_version=outcome.graph_set_version,
        feature_id=outcome.feature_id,
        feature_graph_id=outcome.feature_graph_id,
        takeover_worker_session_id=outcome.takeover_worker_session_id,
        takeover_provider_session_binding_ref=(
            outcome.takeover_provider_session_binding_ref
        ),
        changed_file_refs=list(outcome.changed_file_refs),
        evidence_refs=list(outcome.evidence_refs),
        verification_refs=list(outcome.verification_refs),
        reviewer_input_refs=[
            outcome_ref,
            *outcome.evidence_refs,
            *outcome.verification_refs,
        ],
        required_review_checks=[
            "review_takeover_output_against_original_evidence",
            "verify_takeover_changes_match_feature_scope",
            "verify_takeover_focused_gates",
            "decide_merge_rework_patch_forward_or_blocked",
        ],
        created_at=created_at,
    )


def validate_feature_graph_takeover_followup_verdict(
    *,
    handoff: FeatureGraphTakeoverReviewHandoff,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
) -> FeatureReviewVerdict:
    """Validate a reviewer verdict against takeover follow-up review input."""

    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        handoff.model_dump(mode="json")
    )
    evidence_bundle = FeatureEvidenceBundle.model_validate(
        evidence_bundle.model_dump(mode="json")
    )
    verdict = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
    _validate_handoff_bundle_identity(handoff, evidence_bundle)
    if verdict.evidence_bundle_id != handoff.evidence_bundle_id:
        raise ValueError("takeover follow-up verdict evidence_bundle_id must match handoff")
    if verdict.decision is FeatureReviewDecision.TAKEOVER:
        raise ValueError("takeover follow-up verdict must not request another takeover")
    missing_refs = [
        ref for ref in handoff.reviewer_input_refs if ref not in verdict.evidence_refs
    ]
    if missing_refs:
        raise ValueError("takeover follow-up verdict must cite reviewer_input_refs")
    return verdict


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


def _validate_handoff_bundle_identity(
    handoff: FeatureGraphTakeoverReviewHandoff,
    evidence_bundle: FeatureEvidenceBundle,
) -> None:
    identity_pairs = (
        ("evidence_bundle_id", evidence_bundle.bundle_id, handoff.evidence_bundle_id),
        ("graph_set_id", evidence_bundle.graph_set_id, handoff.graph_set_id),
        ("graph_set_version", evidence_bundle.graph_set_version, handoff.graph_set_version),
        ("feature_id", evidence_bundle.feature_id, handoff.feature_id),
        ("feature_graph_id", evidence_bundle.feature_graph_id, handoff.feature_graph_id),
    )
    for field_name, bundle_value, handoff_value in identity_pairs:
        if bundle_value != handoff_value:
            raise ValueError(f"takeover follow-up {field_name} must match evidence bundle")
