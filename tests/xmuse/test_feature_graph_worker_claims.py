from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_graph_worker_claim_application import (
    apply_feature_graph_worker_claim_plan,
)
from xmuse_core.structuring.feature_graph_worker_claims import (
    build_feature_graph_worker_claim_plan,
)
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerClaimPlan,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _ready_status() -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )


def _claim_plan() -> FeatureGraphWorkerClaimPlan:
    return build_feature_graph_worker_claim_plan(
        current_status=_ready_status(),
        worker_session_id="god-session-feature-worker-demo",
        provider_session_binding_ref="provider_session_binding:psb_demo:v1",
        updated_at="2026-06-03T02:16:00Z",
    )


def test_feature_graph_worker_claim_plan_golden_fixture_is_stable() -> None:
    plan = _claim_plan()

    assert plan.current_status is FeatureGraphExecutionStatus.READY
    assert plan.expected_status is FeatureGraphExecutionStatus.READY
    assert plan.target_status is FeatureGraphExecutionStatus.RUNNING
    assert plan.active_lane_ids == ["binding-schema"]
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_worker_claim_plan.v1.json"
    )


def test_feature_graph_worker_claim_plan_requires_ready_status() -> None:
    running_status = _ready_status().model_copy(
        update={
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["binding-schema"],
            "active_worker_session_id": "god-session-feature-worker-demo",
            "active_provider_session_binding_ref": "provider_session_binding:psb_demo:v1",
            "updated_at": "2026-06-03T02:16:00Z",
        }
    )

    with pytest.raises(ValueError, match="worker claim requires ready status"):
        build_feature_graph_worker_claim_plan(
            current_status=running_status,
            worker_session_id="god-session-feature-worker-demo",
            provider_session_binding_ref="provider_session_binding:psb_demo:v1",
            updated_at="2026-06-03T02:16:00Z",
        )


def test_apply_feature_graph_worker_claim_plan_writes_running_status_event(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_ready_status())
    plan = _claim_plan()

    claimed = apply_feature_graph_worker_claim_plan(store, plan)

    assert claimed.status is FeatureGraphExecutionStatus.RUNNING
    assert claimed.active_worker_session_id == "god-session-feature-worker-demo"
    assert (
        claimed.active_provider_session_binding_ref
        == "provider_session_binding:psb_demo:v1"
    )
    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == claimed
    events = store.list_events(graph_set_id=plan.graph_set_id)
    assert len(events) == 1
    assert events[0].from_status is FeatureGraphExecutionStatus.READY
    assert events[0].to_status is FeatureGraphExecutionStatus.RUNNING


def test_apply_feature_graph_worker_claim_plan_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_ready_status())
    plan = _claim_plan()

    first = apply_feature_graph_worker_claim_plan(store, plan)
    replay = apply_feature_graph_worker_claim_plan(store, plan)

    assert replay == first
    assert len(store.list_events(graph_set_id=plan.graph_set_id)) == 1


def test_apply_feature_graph_worker_claim_plan_revalidates_model_copy_bypass(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(_ready_status())
    plan = _claim_plan()
    invalid_plan = plan.model_copy(
        update={
            "current_status": FeatureGraphExecutionStatus.RUNNING,
            "expected_status": FeatureGraphExecutionStatus.RUNNING,
        }
    )

    with pytest.raises(ValueError, match="worker claim plans require ready status"):
        apply_feature_graph_worker_claim_plan(store, invalid_plan)

    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=plan.graph_set_id) == []
