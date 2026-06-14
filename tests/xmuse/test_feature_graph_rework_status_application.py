from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_rework_status_application import (
    apply_feature_graph_rework_packet_status,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    ProviderSessionBindingDegradationEvidence,
    ReworkPacket,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _bundle() -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )


def _rework_packet() -> ReworkPacket:
    return ReworkPacket.model_validate(
        _artifact_payload("feature_graph_rework_packet.v1.json")
    )


def _reworking_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )
    return status.model_copy(
        update={
            "status_id": "fgstatus_reworking_demo",
            "status": FeatureGraphExecutionStatus.REWORKING,
            "ready_lane_ids": [],
            "active_lane_ids": [],
            "completed_lane_ids": ["binding-schema"],
            "updated_at": "2026-06-03T02:18:00Z",
        }
    )


def test_rework_packet_status_application_transitions_to_running(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reworking_status())
    bundle = _bundle()

    transitioned = apply_feature_graph_rework_packet_status(
        store=store,
        evidence_bundle=bundle,
        rework_packet=_rework_packet(),
        updated_at="2026-06-03T02:20:00Z",
    )

    assert transitioned.status is FeatureGraphExecutionStatus.RUNNING
    assert transitioned.status_id == (
        "fgs:gs-xmuse-hardening:graph-provider-session-binding:"
        "rework_running:20260603T022000z"
    )
    assert transitioned.active_worker_session_id == bundle.worker_session_id
    assert (
        transitioned.active_provider_session_binding_ref
        == bundle.provider_session_binding_ref
    )
    assert transitioned.active_lane_ids == ["binding-schema"]
    assert transitioned.completed_lane_ids == ["binding-schema"]
    events = store.list_events(graph_set_id=bundle.graph_set_id)
    assert len(events) == 1
    assert events[0].from_status is FeatureGraphExecutionStatus.REWORKING
    assert events[0].to_status is FeatureGraphExecutionStatus.RUNNING


def test_rework_packet_status_application_preserves_provider_binding_degradations(
    tmp_path: Path,
) -> None:
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb_demo:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=binding-schema"],
    )
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(
        _reworking_status().model_copy(
            update={"provider_session_binding_degradations": [degradation]}
        )
    )

    transitioned = apply_feature_graph_rework_packet_status(
        store=store,
        evidence_bundle=_bundle(),
        rework_packet=_rework_packet(),
        updated_at="2026-06-03T02:20:00Z",
    )

    assert transitioned.provider_session_binding_degradations == [degradation]


def test_rework_packet_status_application_preserves_blueprint_proof_level(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(
        _reworking_status().model_copy(
            update={"blueprint_proof_level": "opt_in_live_proof"}
        )
    )

    transitioned = apply_feature_graph_rework_packet_status(
        store=store,
        evidence_bundle=_bundle(),
        rework_packet=_rework_packet(),
        updated_at="2026-06-03T02:20:00Z",
    )

    assert transitioned.blueprint_proof_level == "opt_in_live_proof"


def test_rework_packet_status_application_rejects_blueprint_proof_level_mismatch(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(
        _reworking_status().model_copy(
            update={"blueprint_proof_level": "opt_in_live_proof"}
        )
    )
    bundle = _bundle().model_copy(update={"blueprint_proof_level": "contract_proof"})

    with pytest.raises(
        ValueError,
        match="evidence bundle blueprint_proof_level must match current status",
    ):
        apply_feature_graph_rework_packet_status(
            store=store,
            evidence_bundle=bundle,
            rework_packet=_rework_packet(),
            updated_at="2026-06-03T02:20:00Z",
        )


def test_rework_packet_status_application_replay_is_idempotent(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reworking_status())

    first = apply_feature_graph_rework_packet_status(
        store=store,
        evidence_bundle=_bundle(),
        rework_packet=_rework_packet(),
        updated_at="2026-06-03T02:20:00Z",
    )
    replay = apply_feature_graph_rework_packet_status(
        store=store,
        evidence_bundle=_bundle(),
        rework_packet=_rework_packet(),
        updated_at="2026-06-03T02:20:00Z",
    )

    assert replay == first
    assert len(store.list_events(graph_set_id=first.graph_set_id)) == 1


def test_rework_packet_status_application_rejects_non_reworking_status(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(
        _reworking_status().model_copy(
            update={
                "status_id": "fgstatus_reviewing_demo",
                "status": FeatureGraphExecutionStatus.REVIEWING,
            }
        )
    )

    with pytest.raises(ValueError, match="requires reworking status"):
        apply_feature_graph_rework_packet_status(
            store=store,
            evidence_bundle=_bundle(),
            rework_packet=_rework_packet(),
            updated_at="2026-06-03T02:20:00Z",
        )

    assert store.get(
        graph_set_id=initial.graph_set_id,
        feature_graph_id=initial.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=initial.graph_set_id) == []


def test_rework_packet_status_application_rejects_mismatched_target_session(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reworking_status())
    packet = _rework_packet().model_copy(
        update={"target_worker_session_id": "other-worker"}
    )

    with pytest.raises(ValueError, match="target_worker_session_id"):
        apply_feature_graph_rework_packet_status(
            store=store,
            evidence_bundle=_bundle(),
            rework_packet=packet,
            updated_at="2026-06-03T02:20:00Z",
        )


def test_orchestrator_rework_packet_status_facade_writes_running_status(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "legacy"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reworking_status())
    bundle = artifact_store.save_evidence_bundle(_bundle())
    packet = artifact_store.save_rework_packet(_rework_packet())
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.apply_feature_graph_rework_packet_status(
            rework_id=packet.rework_id,
            updated_at="2026-06-03T02:20:00Z",
        )

    assert outcome.evidence_bundle == bundle
    assert outcome.rework_packet == packet
    assert outcome.status.status is FeatureGraphExecutionStatus.RUNNING
    assert status_store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    ) == outcome.status
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()
