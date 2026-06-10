from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_blocked_review import (
    build_feature_graph_blocked_review_plan,
)
from xmuse_core.structuring.feature_graph_patch_forward import (
    build_feature_graph_patch_forward_plan,
)
from xmuse_core.structuring.feature_graph_review_transition_application import (
    apply_feature_graph_review_status_transition_plan,
)
from xmuse_core.structuring.feature_graph_review_transitions import (
    build_feature_graph_review_status_transition_plan,
)
from xmuse_core.structuring.feature_graph_rework_packets import (
    build_feature_graph_rework_packet,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_graph_takeover_plan import (
    build_feature_graph_takeover_plan,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardPlan,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
    FeatureGraphTakeoverPlan,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ReworkPacket,
)


@dataclass(frozen=True)
class FeatureGraphReviewVerdictOutcome:
    plan: FeatureGraphReviewStatusTransitionPlan
    status: FeatureGraphExecutionStatusRecord | None
    rework_packet: ReworkPacket | None = None
    patch_forward_plan: FeatureGraphPatchForwardPlan | None = None
    blocked_review_plan: FeatureGraphBlockedReviewPlan | None = None
    takeover_plan: FeatureGraphTakeoverPlan | None = None


def submit_feature_graph_review_verdict(
    *,
    store: FeatureGraphStatusStore,
    evidence_bundle: FeatureEvidenceBundle,
    verdict: FeatureReviewVerdict,
    updated_at: str,
    artifact_store: FeatureGraphArtifactStore | None = None,
    max_rework_attempts: int = 2,
) -> FeatureGraphReviewVerdictOutcome:
    """Submit a feature-level review verdict to the graph-native coordinator path.

    Merge/rework/blocked verdicts become guarded status transitions. Patch-forward
    and takeover verdicts only return their coordinator plan here; their stronger
    gates must run before any durable status write.
    """

    bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    validated_verdict = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
    current = store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    )
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=bundle,
        verdict=validated_verdict,
        current_status=current,
        updated_at=updated_at,
    )
    rework_id = _rework_packet_id(
        verdict_id=validated_verdict.verdict_id,
        evidence_bundle_id=bundle.bundle_id,
        updated_at=updated_at,
    )
    rework_packet = (
        build_feature_graph_rework_packet(
            evidence_bundle=bundle,
            verdict=validated_verdict,
            rework_id=rework_id,
            max_remaining_attempts=_remaining_rework_attempts(
                artifact_store=artifact_store,
                evidence_bundle_id=bundle.bundle_id,
                current_rework_id=rework_id,
                max_rework_attempts=max_rework_attempts,
            ),
            created_at=updated_at,
        )
        if validated_verdict.decision is FeatureReviewDecision.REWORK
        else None
    )
    patch_forward_plan = (
        build_feature_graph_patch_forward_plan(
            evidence_bundle=bundle,
            verdict=validated_verdict,
            current_status=current,
            plan_id=_patch_forward_plan_id(
                verdict_id=validated_verdict.verdict_id,
                evidence_bundle_id=bundle.bundle_id,
                updated_at=updated_at,
            ),
            created_at=updated_at,
        )
        if validated_verdict.decision is FeatureReviewDecision.PATCH_FORWARD
        else None
    )
    blocked_review_plan = (
        build_feature_graph_blocked_review_plan(
            evidence_bundle=bundle,
            verdict=validated_verdict,
            current_status=current,
            plan_id=_blocked_review_plan_id(
                verdict_id=validated_verdict.verdict_id,
                evidence_bundle_id=bundle.bundle_id,
                updated_at=updated_at,
            ),
            created_at=updated_at,
        )
        if validated_verdict.decision is FeatureReviewDecision.BLOCKED
        else None
    )
    takeover_plan = (
        build_feature_graph_takeover_plan(
            evidence_bundle=bundle,
            verdict=validated_verdict,
            current_status=current,
            plan_id=_takeover_plan_id(
                verdict_id=validated_verdict.verdict_id,
                evidence_bundle_id=bundle.bundle_id,
                updated_at=updated_at,
            ),
            created_at=updated_at,
        )
        if validated_verdict.decision is FeatureReviewDecision.TAKEOVER
        else None
    )
    if plan.coordinator_action is not FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS:
        _save_review_artifacts(
            artifact_store=artifact_store,
            verdict=validated_verdict,
            rework_packet=rework_packet,
            patch_forward_plan=patch_forward_plan,
            blocked_review_plan=blocked_review_plan,
            takeover_plan=takeover_plan,
        )
        return FeatureGraphReviewVerdictOutcome(
            plan=plan,
            status=None,
            rework_packet=rework_packet,
            patch_forward_plan=patch_forward_plan,
            blocked_review_plan=blocked_review_plan,
            takeover_plan=takeover_plan,
        )
    status = apply_feature_graph_review_status_transition_plan(store, plan)
    _save_review_artifacts(
        artifact_store=artifact_store,
        verdict=validated_verdict,
        rework_packet=rework_packet,
        patch_forward_plan=patch_forward_plan,
        blocked_review_plan=blocked_review_plan,
        takeover_plan=takeover_plan,
    )
    return FeatureGraphReviewVerdictOutcome(
        plan=plan,
        status=status,
        rework_packet=rework_packet,
        patch_forward_plan=patch_forward_plan,
        blocked_review_plan=blocked_review_plan,
        takeover_plan=takeover_plan,
    )


def _save_review_artifacts(
    *,
    artifact_store: FeatureGraphArtifactStore | None,
    verdict: FeatureReviewVerdict,
    rework_packet: ReworkPacket | None,
    patch_forward_plan: FeatureGraphPatchForwardPlan | None,
    blocked_review_plan: FeatureGraphBlockedReviewPlan | None,
    takeover_plan: FeatureGraphTakeoverPlan | None,
) -> None:
    if artifact_store is None:
        return
    artifact_store.save_review_verdict(verdict)
    if rework_packet is not None:
        artifact_store.save_rework_packet(rework_packet)
    if patch_forward_plan is not None:
        artifact_store.save_patch_forward_plan(patch_forward_plan)
    if blocked_review_plan is not None:
        artifact_store.save_blocked_review_plan(blocked_review_plan)
    if takeover_plan is not None:
        artifact_store.save_takeover_plan(takeover_plan)


def _rework_packet_id(
    *,
    verdict_id: str,
    evidence_bundle_id: str,
    updated_at: str,
) -> str:
    return f"rework:{verdict_id}:{evidence_bundle_id}:{_safe_updated_at(updated_at)}"


def _patch_forward_plan_id(
    *,
    verdict_id: str,
    evidence_bundle_id: str,
    updated_at: str,
) -> str:
    return f"fgpf:{verdict_id}:{evidence_bundle_id}:{_safe_updated_at(updated_at)}"


def _blocked_review_plan_id(
    *,
    verdict_id: str,
    evidence_bundle_id: str,
    updated_at: str,
) -> str:
    return f"fgblocked:{verdict_id}:{evidence_bundle_id}:{_safe_updated_at(updated_at)}"


def _takeover_plan_id(
    *,
    verdict_id: str,
    evidence_bundle_id: str,
    updated_at: str,
) -> str:
    return f"fgtakeover:{verdict_id}:{evidence_bundle_id}:{_safe_updated_at(updated_at)}"


def _remaining_rework_attempts(
    *,
    artifact_store: FeatureGraphArtifactStore | None,
    evidence_bundle_id: str,
    current_rework_id: str,
    max_rework_attempts: int,
) -> int:
    if max_rework_attempts < 0:
        raise ValueError("max_rework_attempts must be >= 0")
    previous_count = 0
    if artifact_store is not None:
        previous_count = len(
            {
                packet.rework_id
                for packet in artifact_store.list_rework_packets_for_evidence_bundle(
                    evidence_bundle_id
                )
                if packet.rework_id != current_rework_id
            }
        )
    return max(0, max_rework_attempts - previous_count - 1)


def _safe_updated_at(updated_at: str) -> str:
    return (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
