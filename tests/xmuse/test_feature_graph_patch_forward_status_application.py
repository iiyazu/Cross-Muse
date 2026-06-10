from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_patch_forward_status_application import (
    apply_feature_graph_patch_forward_merge_guard_decision,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardMergeGuardDecision,
    ProviderSessionBindingDegradationEvidence,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _reviewing_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )
    return status.model_copy(
        update={
            "status_id": "fgstatus_reviewing_patch_forward_demo",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "ready_lane_ids": [],
            "active_lane_ids": [],
            "completed_lane_ids": ["binding-schema"],
            "updated_at": "2026-06-03T02:21:30Z",
        }
    )


def _merge_guard_decision() -> FeatureGraphPatchForwardMergeGuardDecision:
    return FeatureGraphPatchForwardMergeGuardDecision.model_validate(
        _artifact_payload("feature_graph_patch_forward_merge_guard_decision.v1.json")
    )


def test_patch_forward_merge_guard_decision_transitions_to_merged(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reviewing_status())
    decision = _merge_guard_decision()

    transitioned = apply_feature_graph_patch_forward_merge_guard_decision(
        store=store,
        decision=decision,
        updated_at="2026-06-03T02:25:00Z",
    )

    assert transitioned.status is FeatureGraphExecutionStatus.MERGED
    assert transitioned.status_id == (
        "fgs:gs-xmuse-hardening:graph-provider-session-binding:"
        "patch_forward_merged:20260603T022500z"
    )
    assert transitioned.completed_lane_ids == ["binding-schema"]
    events = store.list_events(graph_set_id=decision.graph_set_id)
    assert len(events) == 1
    assert events[0].from_status is FeatureGraphExecutionStatus.REVIEWING
    assert events[0].to_status is FeatureGraphExecutionStatus.MERGED


def test_patch_forward_merge_guard_preserves_provider_binding_degradations(
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
        _reviewing_status().model_copy(
            update={"provider_session_binding_degradations": [degradation]}
        )
    )

    transitioned = apply_feature_graph_patch_forward_merge_guard_decision(
        store=store,
        decision=_merge_guard_decision(),
        updated_at="2026-06-03T02:25:00Z",
    )

    assert transitioned.provider_session_binding_degradations == [degradation]


def test_patch_forward_merge_guard_decision_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reviewing_status())
    decision = _merge_guard_decision()

    first = apply_feature_graph_patch_forward_merge_guard_decision(
        store=store,
        decision=decision,
        updated_at="2026-06-03T02:25:00Z",
    )
    replay = apply_feature_graph_patch_forward_merge_guard_decision(
        store=store,
        decision=decision,
        updated_at="2026-06-03T02:25:00Z",
    )

    assert replay == first
    assert len(store.list_events(graph_set_id=decision.graph_set_id)) == 1


def test_patch_forward_merge_guard_decision_rejects_failed_decision(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(_reviewing_status())
    decision = _merge_guard_decision().model_copy(
        update={"passed": False, "failure_reasons": ["merge guard failed"]}
    )

    with pytest.raises(ValueError, match="decision must be passed"):
        apply_feature_graph_patch_forward_merge_guard_decision(
            store=store,
            decision=decision,
            updated_at="2026-06-03T02:25:00Z",
        )

    assert store.get(
        graph_set_id=initial.graph_set_id,
        feature_graph_id=initial.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=initial.graph_set_id) == []


def test_patch_forward_merge_guard_decision_requires_reviewing_status(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(
        _reviewing_status().model_copy(
            update={
                "status_id": "fgstatus_reworking_patch_forward_demo",
                "status": FeatureGraphExecutionStatus.REWORKING,
            }
        )
    )

    with pytest.raises(ValueError, match="requires reviewing status"):
        apply_feature_graph_patch_forward_merge_guard_decision(
            store=store,
            decision=_merge_guard_decision(),
            updated_at="2026-06-03T02:25:00Z",
        )

    assert store.get(
        graph_set_id=initial.graph_set_id,
        feature_graph_id=initial.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=initial.graph_set_id) == []
