from __future__ import annotations

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    ReworkPacket,
)


def apply_feature_graph_rework_packet_status(
    *,
    store: FeatureGraphStatusStore,
    evidence_bundle: FeatureEvidenceBundle,
    rework_packet: ReworkPacket,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    """Apply a coordinator-approved rework packet to graph-native status."""

    bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    packet = ReworkPacket.model_validate(rework_packet.model_dump(mode="json"))
    _require_packet_targets_bundle(packet, bundle)
    current = store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    )
    target = _target_status_record(
        current_status=current,
        evidence_bundle=bundle,
        rework_packet=packet,
        updated_at=updated_at,
    )
    if (
        current.status is FeatureGraphExecutionStatus.RUNNING
        and current.status_id == target.status_id
    ):
        return current
    _require_reworking_identity(current, bundle)
    return store.transition(target, expected_status=FeatureGraphExecutionStatus.REWORKING)


def _target_status_record(
    *,
    current_status: FeatureGraphExecutionStatusRecord,
    evidence_bundle: FeatureEvidenceBundle,
    rework_packet: ReworkPacket,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=_feature_graph_status_id(
            graph_set_id=evidence_bundle.graph_set_id,
            feature_graph_id=evidence_bundle.feature_graph_id,
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
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=_rework_active_lane_ids(current_status, evidence_bundle),
        active_worker_session_id=rework_packet.target_worker_session_id,
        active_provider_session_binding_ref=(
            rework_packet.target_provider_session_binding_ref
        ),
        completed_lane_ids=list(current_status.completed_lane_ids),
        blocked_lane_ids=list(current_status.blocked_lane_ids),
        projection_lane_ids=list(current_status.projection_lane_ids),
        feature_lanes_projection_ref=current_status.feature_lanes_projection_ref,
        provider_session_binding_degradations=list(
            current_status.provider_session_binding_degradations
        ),
        updated_at=updated_at,
    )


def _require_packet_targets_bundle(
    rework_packet: ReworkPacket,
    evidence_bundle: FeatureEvidenceBundle,
) -> None:
    if rework_packet.evidence_bundle_id != evidence_bundle.bundle_id:
        raise ValueError("rework packet evidence_bundle_id must match bundle_id")
    if (
        rework_packet.target_worker_session_id is not None
        and rework_packet.target_worker_session_id != evidence_bundle.worker_session_id
    ):
        raise ValueError("rework packet target_worker_session_id must match evidence bundle")
    if (
        rework_packet.target_provider_session_binding_ref is not None
        and rework_packet.target_provider_session_binding_ref
        != evidence_bundle.provider_session_binding_ref
    ):
        raise ValueError(
            "rework packet target_provider_session_binding_ref must match evidence bundle"
        )


def _require_reworking_identity(
    current_status: FeatureGraphExecutionStatusRecord,
    evidence_bundle: FeatureEvidenceBundle,
) -> None:
    if current_status.status is not FeatureGraphExecutionStatus.REWORKING:
        raise ValueError("rework packet status application requires reworking status")
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
        (
            "feature_graph_id",
            current_status.feature_graph_id,
            evidence_bundle.feature_graph_id,
        ),
    )
    for field_name, current_value, bundle_value in identity_pairs:
        if current_value != bundle_value:
            raise ValueError(f"current status {field_name} must match evidence bundle")


def _rework_active_lane_ids(
    current_status: FeatureGraphExecutionStatusRecord,
    evidence_bundle: FeatureEvidenceBundle,
) -> list[str]:
    candidates = [
        *current_status.active_lane_ids,
        *current_status.blocked_lane_ids,
        *evidence_bundle.lane_graph_summary.blocked_lane_ids,
        *evidence_bundle.lane_graph_summary.completed_lane_ids,
    ]
    active: list[str] = []
    seen: set[str] = set()
    for lane_id in candidates:
        if lane_id in seen:
            continue
        seen.add(lane_id)
        active.append(lane_id)
    return active


def _feature_graph_status_id(
    *,
    graph_set_id: str,
    feature_graph_id: str,
    updated_at: str,
) -> str:
    return (
        f"fgs:{graph_set_id}:{feature_graph_id}:rework_running:"
        f"{_safe_updated_at(updated_at)}"
    )


def _safe_updated_at(updated_at: str) -> str:
    return (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
