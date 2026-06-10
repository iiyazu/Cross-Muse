from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_rework_status_application import (
    apply_feature_graph_rework_packet_status,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatusRecord,
    ReworkPacket,
)


@dataclass(frozen=True)
class FeatureGraphReworkStatusApplicationOutcome:
    evidence_bundle: FeatureEvidenceBundle
    rework_packet: ReworkPacket
    status: FeatureGraphExecutionStatusRecord


def apply_feature_graph_rework_packet_status_from_artifacts(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore,
    rework_id: str,
    updated_at: str,
) -> FeatureGraphReworkStatusApplicationOutcome:
    """Apply a saved rework packet to graph-native status."""

    packet = artifact_store.get_rework_packet(rework_id)
    evidence_bundle = artifact_store.get_evidence_bundle(packet.evidence_bundle_id)
    status = apply_feature_graph_rework_packet_status(
        store=status_store,
        evidence_bundle=evidence_bundle,
        rework_packet=packet,
        updated_at=updated_at,
    )
    return FeatureGraphReworkStatusApplicationOutcome(
        evidence_bundle=evidence_bundle,
        rework_packet=packet,
        status=status,
    )
