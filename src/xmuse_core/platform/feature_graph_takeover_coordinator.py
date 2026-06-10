from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.platform.feature_graph_review_coordinator import (
    FeatureGraphReviewVerdictOutcome,
    submit_feature_graph_review_verdict,
)
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_graph_takeover_plan import (
    build_feature_graph_takeover_decision,
    build_feature_graph_takeover_handoff,
    build_feature_graph_takeover_outcome,
    build_feature_graph_takeover_review_handoff,
    validate_feature_graph_takeover_followup_verdict,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardPlan,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverFollowupReviewApplicationRecord,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ReworkPacket,
)


@dataclass(frozen=True)
class FeatureGraphTakeoverDecisionOutcome:
    plan: FeatureGraphTakeoverPlan
    decision: FeatureGraphTakeoverDecision
    eligible_for_takeover: bool
    takeover_handoff: FeatureGraphTakeoverHandoff | None = None


@dataclass(frozen=True)
class FeatureGraphTakeoverWorkerOutcome:
    handoff: FeatureGraphTakeoverHandoff
    outcome: FeatureGraphTakeoverOutcome
    eligible_for_followup_review: bool
    review_handoff: FeatureGraphTakeoverReviewHandoff | None = None


@dataclass(frozen=True)
class FeatureGraphTakeoverFollowupReviewVerdictOutcome:
    handoff: FeatureGraphTakeoverReviewHandoff
    evidence_bundle: FeatureEvidenceBundle
    verdict: FeatureReviewVerdict


@dataclass(frozen=True)
class FeatureGraphTakeoverFollowupReviewApplicationOutcome:
    handoff: FeatureGraphTakeoverReviewHandoff
    application: FeatureGraphTakeoverFollowupReviewApplicationRecord
    review_outcome: FeatureGraphReviewVerdictOutcome


def submit_feature_graph_takeover_decision(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore | None,
    plan_id: str,
    approved: bool,
    takeover_worker_session_id: str | None,
    takeover_provider_session_binding_ref: str | None,
    gate_refs: list[str] | None,
    failure_reasons: list[str] | None,
    checked_at: str,
) -> FeatureGraphTakeoverDecisionOutcome:
    """Record coordinator-owned takeover gate output.

    This helper only writes the takeover decision artifact. It does not start a
    takeover worker, mutate graph status, or touch the legacy lane projection.
    """

    plan = artifact_store.get_takeover_plan(plan_id)
    if approved:
        _require_takeover_reviewing_context(
            status_store=status_store,
            graph_set_id=plan.graph_set_id,
            graph_set_version=plan.graph_set_version,
            feature_id=plan.feature_id,
            feature_graph_id=plan.feature_graph_id,
            missing_status_message="approved takeover decision requires status store",
            stale_status_message="approved takeover decision requires reviewing status",
            identity_label="takeover plan",
        )
    decision = build_feature_graph_takeover_decision(
        plan=plan,
        decision_id=_takeover_decision_id(plan_id=plan.plan_id, checked_at=checked_at),
        approved=approved,
        takeover_worker_session_id=takeover_worker_session_id,
        takeover_provider_session_binding_ref=takeover_provider_session_binding_ref,
        gate_refs=gate_refs,
        failure_reasons=failure_reasons,
        checked_at=checked_at,
    )
    saved = artifact_store.save_takeover_decision(decision)
    handoff = None
    if saved.approved:
        handoff = artifact_store.save_takeover_handoff(
            build_feature_graph_takeover_handoff(
                decision=saved,
                handoff_id=_takeover_handoff_id(saved),
                decision_ref=_takeover_decision_ref(saved),
                created_at=saved.checked_at,
            )
        )
    return FeatureGraphTakeoverDecisionOutcome(
        plan=plan,
        decision=saved,
        eligible_for_takeover=saved.approved,
        takeover_handoff=handoff,
    )


def _require_takeover_reviewing_context(
    *,
    status_store: FeatureGraphStatusStore | None,
    graph_set_id: str,
    graph_set_version: int,
    feature_id: str,
    feature_graph_id: str,
    missing_status_message: str,
    stale_status_message: str,
    identity_label: str,
) -> None:
    if status_store is None:
        raise ValueError(missing_status_message)
    current = status_store.get(
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
    )
    if current.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError(stale_status_message)
    identity_pairs = (
        ("graph_set_id", current.graph_set_id, graph_set_id),
        ("graph_set_version", current.graph_set_version, graph_set_version),
        ("feature_id", current.feature_id, feature_id),
        ("feature_graph_id", current.feature_graph_id, feature_graph_id),
    )
    for field_name, current_value, plan_value in identity_pairs:
        if current_value != plan_value:
            raise ValueError(f"current status {field_name} must match {identity_label}")


def submit_feature_graph_takeover_outcome(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore | None,
    handoff_id: str,
    changed_file_refs: list[str] | None,
    evidence_refs: list[str] | None,
    verification_refs: list[str] | None,
    output_summary: str,
    completed: bool,
    failure_reasons: list[str] | None,
    created_at: str,
) -> FeatureGraphTakeoverWorkerOutcome:
    """Record takeover worker output without mutating execution status."""

    handoff = artifact_store.get_takeover_handoff(handoff_id)
    _require_takeover_reviewing_context(
        status_store=status_store,
        graph_set_id=handoff.graph_set_id,
        graph_set_version=handoff.graph_set_version,
        feature_id=handoff.feature_id,
        feature_graph_id=handoff.feature_graph_id,
        missing_status_message="takeover outcome requires status store",
        stale_status_message="takeover outcome requires reviewing status",
        identity_label="takeover handoff",
    )
    existing_outcome = _find_takeover_outcome_for_handoff(
        artifact_store=artifact_store,
        handoff_id=handoff.handoff_id,
    )
    if existing_outcome is not None:
        _require_matching_takeover_outcome(
            existing=existing_outcome,
            changed_file_refs=changed_file_refs,
            evidence_refs=evidence_refs,
            verification_refs=verification_refs,
            output_summary=output_summary,
            completed=completed,
            failure_reasons=failure_reasons,
        )
        recovered_review_handoff = _recover_takeover_review_handoff_if_missing(
            artifact_store=artifact_store,
            outcome=existing_outcome,
        )
        return FeatureGraphTakeoverWorkerOutcome(
            handoff=handoff,
            outcome=existing_outcome,
            eligible_for_followup_review=existing_outcome.completed,
            review_handoff=recovered_review_handoff,
        )
    outcome = build_feature_graph_takeover_outcome(
        handoff=handoff,
        outcome_id=_takeover_outcome_id(handoff_id=handoff.handoff_id, created_at=created_at),
        changed_file_refs=changed_file_refs,
        evidence_refs=evidence_refs,
        verification_refs=verification_refs,
        output_summary=output_summary,
        completed=completed,
        failure_reasons=failure_reasons,
        created_at=created_at,
    )
    saved = artifact_store.save_takeover_outcome(outcome)
    review_handoff = _recover_takeover_review_handoff_if_missing(
        artifact_store=artifact_store,
        outcome=saved,
    )
    return FeatureGraphTakeoverWorkerOutcome(
        handoff=handoff,
        outcome=saved,
        eligible_for_followup_review=saved.completed,
        review_handoff=review_handoff,
    )


def submit_feature_graph_takeover_followup_review_verdict(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore | None,
    review_handoff_id: str,
    verdict: FeatureReviewVerdict,
) -> FeatureGraphTakeoverFollowupReviewVerdictOutcome:
    """Record a reviewer verdict for a completed takeover handoff.

    This helper validates that the verdict was based on the takeover follow-up
    review handoff and saves the verdict artifact. It does not apply status
    transitions or run merge guard.
    """

    handoff = artifact_store.get_takeover_review_handoff(review_handoff_id)
    evidence_bundle = artifact_store.get_evidence_bundle(handoff.evidence_bundle_id)
    _require_takeover_reviewing_context(
        status_store=status_store,
        graph_set_id=handoff.graph_set_id,
        graph_set_version=handoff.graph_set_version,
        feature_id=handoff.feature_id,
        feature_graph_id=handoff.feature_graph_id,
        missing_status_message="takeover follow-up review verdict requires status store",
        stale_status_message="takeover follow-up review verdict requires reviewing status",
        identity_label="takeover review handoff",
    )
    validated_verdict = validate_feature_graph_takeover_followup_verdict(
        handoff=handoff,
        evidence_bundle=evidence_bundle,
        verdict=verdict,
    )
    saved = artifact_store.save_review_verdict(validated_verdict)
    return FeatureGraphTakeoverFollowupReviewVerdictOutcome(
        handoff=handoff,
        evidence_bundle=evidence_bundle,
        verdict=saved,
    )


def apply_feature_graph_takeover_followup_review_verdict(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore,
    review_handoff_id: str,
    verdict_id: str,
    updated_at: str,
    max_rework_attempts: int = 2,
) -> FeatureGraphTakeoverFollowupReviewApplicationOutcome:
    """Apply a saved takeover follow-up verdict through the graph review path."""

    handoff = artifact_store.get_takeover_review_handoff(review_handoff_id)
    evidence_bundle = artifact_store.get_evidence_bundle(handoff.evidence_bundle_id)
    verdict = artifact_store.get_review_verdict(verdict_id)
    validated_verdict = validate_feature_graph_takeover_followup_verdict(
        handoff=handoff,
        evidence_bundle=evidence_bundle,
        verdict=verdict,
    )
    existing_application = _find_takeover_followup_review_application(
        artifact_store=artifact_store,
        review_handoff_id=handoff.review_handoff_id,
        verdict_id=validated_verdict.verdict_id,
    )
    if existing_application is not None:
        return FeatureGraphTakeoverFollowupReviewApplicationOutcome(
            handoff=handoff,
            application=existing_application,
            review_outcome=_review_outcome_from_application(
                artifact_store=artifact_store,
                application=existing_application,
            ),
        )
    recovered_application = _recover_takeover_followup_application_if_status_applied(
        artifact_store=artifact_store,
        status_store=status_store,
        handoff=handoff,
        evidence_bundle=evidence_bundle,
        verdict=validated_verdict,
    )
    if recovered_application is not None:
        return FeatureGraphTakeoverFollowupReviewApplicationOutcome(
            handoff=handoff,
            application=recovered_application,
            review_outcome=_review_outcome_from_application(
                artifact_store=artifact_store,
                application=recovered_application,
            ),
        )
    recovered_application = _recover_takeover_followup_application_if_review_artifacts_applied(
        artifact_store=artifact_store,
        handoff=handoff,
        evidence_bundle=evidence_bundle,
        verdict=validated_verdict,
    )
    if recovered_application is not None:
        return FeatureGraphTakeoverFollowupReviewApplicationOutcome(
            handoff=handoff,
            application=recovered_application,
            review_outcome=_review_outcome_from_application(
                artifact_store=artifact_store,
                application=recovered_application,
            ),
        )
    review_outcome = submit_feature_graph_review_verdict(
        store=status_store,
        evidence_bundle=evidence_bundle,
        verdict=validated_verdict,
        updated_at=updated_at,
        artifact_store=artifact_store,
        max_rework_attempts=max_rework_attempts,
    )
    application = artifact_store.save_takeover_followup_review_application(
        _build_takeover_followup_review_application(
            handoff=handoff,
            evidence_bundle=evidence_bundle,
            verdict=validated_verdict,
            review_outcome=review_outcome,
            applied_at=updated_at,
        )
    )
    return FeatureGraphTakeoverFollowupReviewApplicationOutcome(
        handoff=handoff,
        application=application,
        review_outcome=review_outcome,
    )


def _find_takeover_followup_review_application(
    *,
    artifact_store: FeatureGraphArtifactStore,
    review_handoff_id: str,
    verdict_id: str,
) -> FeatureGraphTakeoverFollowupReviewApplicationRecord | None:
    for application in artifact_store.list_takeover_followup_review_applications_for_handoff(
        review_handoff_id
    ):
        if application.verdict_id == verdict_id:
            return application
    return None


def _find_takeover_outcome_for_handoff(
    *,
    artifact_store: FeatureGraphArtifactStore,
    handoff_id: str,
) -> FeatureGraphTakeoverOutcome | None:
    outcomes = artifact_store.list_takeover_outcomes_for_handoff(handoff_id)
    if not outcomes:
        return None
    if len(outcomes) > 1:
        raise ValueError(f"multiple takeover outcomes recorded for handoff: {handoff_id}")
    return outcomes[0]


def _require_matching_takeover_outcome(
    *,
    existing: FeatureGraphTakeoverOutcome,
    changed_file_refs: list[str] | None,
    evidence_refs: list[str] | None,
    verification_refs: list[str] | None,
    output_summary: str,
    completed: bool,
    failure_reasons: list[str] | None,
) -> None:
    if existing.changed_file_refs != list(changed_file_refs or []):
        raise ValueError("takeover outcome replay changed_file_refs must match")
    if existing.evidence_refs != list(evidence_refs or []):
        raise ValueError("takeover outcome replay evidence_refs must match")
    if existing.verification_refs != list(verification_refs or []):
        raise ValueError("takeover outcome replay verification_refs must match")
    if existing.output_summary != output_summary:
        raise ValueError("takeover outcome replay output_summary must match")
    if existing.completed is not completed:
        raise ValueError("takeover outcome replay completed flag must match")
    if existing.failure_reasons != list(failure_reasons or []):
        raise ValueError("takeover outcome replay failure_reasons must match")


def _recover_takeover_review_handoff_if_missing(
    *,
    artifact_store: FeatureGraphArtifactStore,
    outcome: FeatureGraphTakeoverOutcome,
) -> FeatureGraphTakeoverReviewHandoff | None:
    if not outcome.completed:
        return None
    handoffs = artifact_store.list_takeover_review_handoffs_for_outcome(outcome.outcome_id)
    if len(handoffs) > 1:
        raise ValueError(
            "multiple takeover review handoffs recorded for outcome: "
            f"{outcome.outcome_id}"
        )
    if handoffs:
        return handoffs[0]
    return artifact_store.save_takeover_review_handoff(
        build_feature_graph_takeover_review_handoff(
            outcome=outcome,
            review_handoff_id=_takeover_review_handoff_id(outcome),
            outcome_ref=_takeover_outcome_ref(outcome),
            created_at=outcome.created_at,
        )
    )


def _recover_takeover_followup_application_if_status_applied(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore,
    handoff: FeatureGraphTakeoverReviewHandoff,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
) -> FeatureGraphTakeoverFollowupReviewApplicationRecord | None:
    target_status = _transition_target_status_for_recovery(verdict.decision)
    if target_status is None:
        return None
    current_status = status_store.get(
        graph_set_id=evidence_bundle.graph_set_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
    )
    if current_status.status is not target_status:
        return None
    review_plan = _recovered_review_transition_plan(
        evidence_bundle=evidence_bundle,
        verdict=verdict,
        target_status=current_status,
    )
    review_outcome = FeatureGraphReviewVerdictOutcome(
        plan=review_plan,
        status=current_status,
        rework_packet=_find_rework_packet_for_verdict(
            artifact_store=artifact_store,
            verdict_id=verdict.verdict_id,
            evidence_bundle_id=evidence_bundle.bundle_id,
        ),
        blocked_review_plan=_find_blocked_review_plan_for_verdict(
            artifact_store=artifact_store,
            verdict_id=verdict.verdict_id,
            evidence_bundle_id=evidence_bundle.bundle_id,
        ),
    )
    return artifact_store.save_takeover_followup_review_application(
        _build_takeover_followup_review_application(
            handoff=handoff,
            evidence_bundle=evidence_bundle,
            verdict=verdict,
            review_outcome=review_outcome,
            applied_at=current_status.updated_at,
        )
    )


def _recover_takeover_followup_application_if_review_artifacts_applied(
    *,
    artifact_store: FeatureGraphArtifactStore,
    handoff: FeatureGraphTakeoverReviewHandoff,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
) -> FeatureGraphTakeoverFollowupReviewApplicationRecord | None:
    if verdict.decision is not FeatureReviewDecision.PATCH_FORWARD:
        return None
    patch_forward_plan = _find_patch_forward_plan_for_verdict(
        artifact_store=artifact_store,
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
    )
    if patch_forward_plan is None:
        return None
    review_outcome = FeatureGraphReviewVerdictOutcome(
        plan=_recovered_nontransition_review_transition_plan(
            evidence_bundle=evidence_bundle,
            verdict=verdict,
            updated_at=patch_forward_plan.created_at,
        ),
        status=None,
        patch_forward_plan=patch_forward_plan,
    )
    return artifact_store.save_takeover_followup_review_application(
        _build_takeover_followup_review_application(
            handoff=handoff,
            evidence_bundle=evidence_bundle,
            verdict=verdict,
            review_outcome=review_outcome,
            applied_at=patch_forward_plan.created_at,
        )
    )


def _build_takeover_followup_review_application(
    *,
    handoff: FeatureGraphTakeoverReviewHandoff,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    review_outcome: FeatureGraphReviewVerdictOutcome,
    applied_at: str,
) -> FeatureGraphTakeoverFollowupReviewApplicationRecord:
    output_refs = [
        f"feature_graph_review_status_transition_plan:{review_outcome.plan.plan_id}:v1"
    ]
    if review_outcome.status is not None:
        output_refs.append(f"feature_graph_status:{review_outcome.status.status_id}:v1")
    if review_outcome.rework_packet is not None:
        output_refs.append(
            f"feature_graph_rework_packet:{review_outcome.rework_packet.rework_id}:v1"
        )
    if review_outcome.patch_forward_plan is not None:
        output_refs.append(
            "feature_graph_patch_forward_plan:"
            f"{review_outcome.patch_forward_plan.plan_id}:v1"
        )
    if review_outcome.blocked_review_plan is not None:
        output_refs.append(
            "feature_graph_blocked_review_plan:"
            f"{review_outcome.blocked_review_plan.plan_id}:v1"
        )
    if review_outcome.takeover_plan is not None:
        output_refs.append(
            f"feature_graph_takeover_plan:{review_outcome.takeover_plan.plan_id}:v1"
        )
    return FeatureGraphTakeoverFollowupReviewApplicationRecord(
        application_id=_takeover_followup_review_application_id(
            review_handoff_id=handoff.review_handoff_id,
            verdict_id=verdict.verdict_id,
        ),
        review_handoff_id=handoff.review_handoff_id,
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        decision=verdict.decision,
        coordinator_action=review_outcome.plan.coordinator_action,
        review_plan=review_outcome.plan,
        applied_status=review_outcome.status,
        rework_id=(
            review_outcome.rework_packet.rework_id
            if review_outcome.rework_packet is not None
            else None
        ),
        patch_forward_plan_id=(
            review_outcome.patch_forward_plan.plan_id
            if review_outcome.patch_forward_plan is not None
            else None
        ),
        blocked_review_plan_id=(
            review_outcome.blocked_review_plan.plan_id
            if review_outcome.blocked_review_plan is not None
            else None
        ),
        takeover_plan_id=(
            review_outcome.takeover_plan.plan_id
            if review_outcome.takeover_plan is not None
            else None
        ),
        input_refs=[
            f"feature_graph_takeover_review_handoff:{handoff.review_handoff_id}:v1",
            f"feature_review_verdict:{verdict.verdict_id}:v1",
            f"feature_evidence_bundle:{evidence_bundle.bundle_id}:v1",
        ],
        output_refs=output_refs,
        applied_at=applied_at,
        idempotency_key=(
            "feature_graph_takeover_followup_review.applied:"
            f"{handoff.review_handoff_id}:{verdict.verdict_id}"
        ),
    )


def _recovered_review_transition_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    target_status: FeatureGraphExecutionStatusRecord,
) -> FeatureGraphReviewStatusTransitionPlan:
    return FeatureGraphReviewStatusTransitionPlan(
        plan_id=(
            f"fgrstp:{verdict.verdict_id}:{evidence_bundle.graph_set_id}:"
            f"{evidence_bundle.feature_graph_id}:{target_status.status.value}:"
            f"{_safe_timestamp(target_status.updated_at)}"
        ),
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        decision=verdict.decision,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        current_status=FeatureGraphExecutionStatus.REVIEWING,
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
        target_status=target_status.status,
        coordinator_action=FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS,
        rationale=verdict.summary,
        evidence_refs=list(verdict.evidence_refs),
        target_status_record=target_status,
        updated_at=target_status.updated_at,
    )


def _recovered_nontransition_review_transition_plan(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    updated_at: str,
) -> FeatureGraphReviewStatusTransitionPlan:
    return FeatureGraphReviewStatusTransitionPlan(
        plan_id=(
            f"fgrstp:{verdict.verdict_id}:{evidence_bundle.graph_set_id}:"
            f"{evidence_bundle.feature_graph_id}:{verdict.decision.value}:"
            f"{_safe_timestamp(updated_at)}"
        ),
        verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        decision=verdict.decision,
        graph_set_id=evidence_bundle.graph_set_id,
        graph_set_version=evidence_bundle.graph_set_version,
        feature_id=evidence_bundle.feature_id,
        feature_graph_id=evidence_bundle.feature_graph_id,
        current_status=FeatureGraphExecutionStatus.REVIEWING,
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
        target_status=None,
        coordinator_action=FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE,
        rationale=verdict.summary,
        evidence_refs=list(verdict.evidence_refs),
        target_status_record=None,
        updated_at=updated_at,
    )


def _transition_target_status_for_recovery(
    decision: FeatureReviewDecision,
) -> FeatureGraphExecutionStatus | None:
    if decision is FeatureReviewDecision.MERGE:
        return FeatureGraphExecutionStatus.MERGED
    if decision is FeatureReviewDecision.REWORK:
        return FeatureGraphExecutionStatus.REWORKING
    if decision is FeatureReviewDecision.BLOCKED:
        return FeatureGraphExecutionStatus.BLOCKED
    return None


def _find_rework_packet_for_verdict(
    *,
    artifact_store: FeatureGraphArtifactStore,
    verdict_id: str,
    evidence_bundle_id: str,
) -> ReworkPacket | None:
    for packet in artifact_store.list_rework_packets_for_evidence_bundle(evidence_bundle_id):
        if packet.source_verdict_id == verdict_id:
            return packet
    return None


def _find_blocked_review_plan_for_verdict(
    *,
    artifact_store: FeatureGraphArtifactStore,
    verdict_id: str,
    evidence_bundle_id: str,
) -> FeatureGraphBlockedReviewPlan | None:
    for plan in artifact_store.list_blocked_review_plans_for_evidence_bundle(
        evidence_bundle_id
    ):
        if plan.verdict_id == verdict_id:
            return plan
    return None


def _find_patch_forward_plan_for_verdict(
    *,
    artifact_store: FeatureGraphArtifactStore,
    verdict_id: str,
    evidence_bundle_id: str,
) -> FeatureGraphPatchForwardPlan | None:
    matches = [
        plan
        for plan in artifact_store.list_patch_forward_plans_for_evidence_bundle(
            evidence_bundle_id
        )
        if plan.verdict_id == verdict_id
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            "multiple patch-forward plans recorded for verdict: "
            f"{verdict_id}"
        )
    return matches[0]


def _review_outcome_from_application(
    *,
    artifact_store: FeatureGraphArtifactStore,
    application: FeatureGraphTakeoverFollowupReviewApplicationRecord,
) -> FeatureGraphReviewVerdictOutcome:
    return FeatureGraphReviewVerdictOutcome(
        plan=application.review_plan,
        status=application.applied_status,
        rework_packet=_get_rework_packet_or_none(
            artifact_store,
            application.rework_id,
        ),
        patch_forward_plan=_get_patch_forward_plan_or_none(
            artifact_store,
            application.patch_forward_plan_id,
        ),
        blocked_review_plan=_get_blocked_review_plan_or_none(
            artifact_store,
            application.blocked_review_plan_id,
        ),
        takeover_plan=_get_takeover_plan_or_none(
            artifact_store,
            application.takeover_plan_id,
        ),
    )


def _get_rework_packet_or_none(
    artifact_store: FeatureGraphArtifactStore,
    rework_id: str | None,
) -> ReworkPacket | None:
    return artifact_store.get_rework_packet(rework_id) if rework_id is not None else None


def _get_patch_forward_plan_or_none(
    artifact_store: FeatureGraphArtifactStore,
    plan_id: str | None,
) -> FeatureGraphPatchForwardPlan | None:
    return artifact_store.get_patch_forward_plan(plan_id) if plan_id is not None else None


def _get_blocked_review_plan_or_none(
    artifact_store: FeatureGraphArtifactStore,
    plan_id: str | None,
) -> FeatureGraphBlockedReviewPlan | None:
    return artifact_store.get_blocked_review_plan(plan_id) if plan_id is not None else None


def _get_takeover_plan_or_none(
    artifact_store: FeatureGraphArtifactStore,
    plan_id: str | None,
) -> FeatureGraphTakeoverPlan | None:
    return artifact_store.get_takeover_plan(plan_id) if plan_id is not None else None


def _takeover_decision_id(*, plan_id: str, checked_at: str) -> str:
    return f"fgtd:{plan_id}:{_safe_timestamp(checked_at)}"


def _takeover_handoff_id(decision: FeatureGraphTakeoverDecision) -> str:
    return f"fgth:{decision.decision_id}"


def _takeover_decision_ref(decision: FeatureGraphTakeoverDecision) -> str:
    return f"feature_graph_takeover_decision:{decision.decision_id}:v1"


def _takeover_outcome_id(*, handoff_id: str, created_at: str) -> str:
    return f"fgto:{handoff_id}:{_safe_timestamp(created_at)}"


def _takeover_review_handoff_id(outcome: FeatureGraphTakeoverOutcome) -> str:
    return f"fgtrh:{outcome.outcome_id}"


def _takeover_outcome_ref(outcome: FeatureGraphTakeoverOutcome) -> str:
    return f"feature_graph_takeover_outcome:{outcome.outcome_id}:v1"


def _takeover_followup_review_application_id(
    *,
    review_handoff_id: str,
    verdict_id: str,
) -> str:
    return f"fgtrha:{review_handoff_id}:{verdict_id}"


def _safe_timestamp(value: str) -> str:
    return value.replace("-", "").replace(":", "").replace(".", "").lower()
