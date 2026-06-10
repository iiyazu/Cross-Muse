from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ReworkPacket,
)


def build_feature_graph_rework_packet(
    *,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    rework_id: str,
    max_remaining_attempts: int,
    created_at: str,
) -> ReworkPacket:
    """Build a structured rework packet for the same resumable feature worker."""

    evidence_bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    verdict = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
    if verdict.evidence_bundle_id != evidence_bundle.bundle_id:
        raise ValueError("verdict evidence_bundle_id must match bundle_id")
    if verdict.decision is not FeatureReviewDecision.REWORK:
        raise ValueError("rework packet requires rework verdict")

    return ReworkPacket(
        rework_id=rework_id,
        source_verdict_id=verdict.verdict_id,
        evidence_bundle_id=evidence_bundle.bundle_id,
        target_worker_session_id=evidence_bundle.worker_session_id,
        target_provider_session_binding_ref=evidence_bundle.provider_session_binding_ref,
        blocking_findings=list(verdict.blocking_findings),
        required_changes=[finding.summary for finding in verdict.blocking_findings],
        forbidden_changes=[
            f"Do not expand changes beyond feature {evidence_bundle.feature_id}.",
        ],
        evidence_refs=_unique_texts(
            [
                *verdict.evidence_refs,
                *[
                    evidence_ref
                    for finding in verdict.blocking_findings
                    for evidence_ref in finding.evidence_refs
                ],
            ]
        ),
        files_or_areas_to_revisit=_revisit_scope(evidence_bundle, verdict),
        gates_to_rerun=(
            list(verdict.required_gates_before_merge)
            if verdict.required_gates_before_merge
            else list(evidence_bundle.verification.commands_run)
        ),
        max_remaining_attempts=max_remaining_attempts,
        return_requirements=[
            (
                "Return an updated FeatureEvidenceBundle for feature graph "
                f"{evidence_bundle.feature_graph_id}."
            ),
            "Include evidence for every blocking finding and rerun the required gates.",
        ],
        created_at=created_at,
    )


def _revisit_scope(
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
) -> list[str]:
    scope = _unique_texts(
        [
            *evidence_bundle.touched_files,
            *evidence_bundle.changed_files,
            *verdict.scope_assessment.touched_files,
        ]
    )
    if scope:
        return scope
    return [f"feature_graph:{evidence_bundle.feature_graph_id}"]


def _unique_texts(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
