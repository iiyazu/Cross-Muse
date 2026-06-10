from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.feature_graph_provider_binding_degradation_coordinator import (
    reconcile_feature_graph_provider_binding_degradations,
    record_feature_graph_provider_binding_degradation_from_lane,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
)


def _running_status() -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id="fgs-running",
        conversation_id="conv-1",
        planning_run_id="planning-1",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        feature_id="feature-a",
        feature_graph_id="graph-feature-a",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        active_worker_session_id="god-worker-a",
        active_provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        completed_lane_ids=[],
        blocked_lane_ids=[],
        projection_lane_ids=["lane:conv-1:graph-feature-a:lane-a"],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=7",
        updated_at="2026-06-03T03:10:00Z",
    )


def test_records_lane_provider_binding_degradation_into_graph_status_store(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    lane = {
        "feature_id": "lane-a",
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-feature-a",
        "provider_session_binding_degraded": True,
        "provider_session_binding_degraded_reason": "mark_failed_failed",
        "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
        "provider_session_binding_failure": "provider store write failed",
        "feature_lanes_projection_ref": "feature_lanes.json#projection_revision=7",
    }
    projection_path = tmp_path / "feature_lanes.json"
    projection_path.write_text(json.dumps({"lanes": [lane]}) + "\n", encoding="utf-8")
    before_projection = projection_path.read_text(encoding="utf-8")

    outcome = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane=lane,
        updated_at="2026-06-03T03:11:00Z",
        compatibility_bridge_enabled=True,
    )

    assert outcome is not None
    assert outcome.evidence.binding_id == "provider_session_binding:psb-worker-a:v1"
    assert outcome.evidence.reason == "mark_failed_failed"
    assert outcome.status.provider_session_binding_degradations == [outcome.evidence]
    assert outcome.status.updated_at == "2026-06-03T03:11:00Z"
    assert projection_path.read_text(encoding="utf-8") == before_projection
    events = store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )
    assert [event.event_type for event in events] == [
        "feature_graph_status.provider_session_binding_degraded"
    ]


def test_lane_provider_binding_degradation_chain_is_idempotent(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    lane = {
        "feature_id": "lane-a",
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-feature-a",
        "provider_session_binding_degraded": True,
        "provider_session_binding_degraded_reason": "mark_failed_failed",
        "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
        "provider_session_binding_failure": "provider store write failed",
    }
    first = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane=lane,
        updated_at="2026-06-03T03:11:00Z",
        compatibility_bridge_enabled=True,
    )

    replay = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane=lane,
        updated_at="2026-06-03T03:12:00Z",
        compatibility_bridge_enabled=True,
    )

    assert first is not None
    assert replay is not None
    assert replay.status == first.status
    assert len(store.list_events(graph_set_id="graph-set-1")) == 1


def test_lane_without_provider_binding_degradation_does_not_write_status(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    current = _running_status()
    store.upsert(current)

    outcome = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_degraded": False,
        },
        updated_at="2026-06-03T03:11:00Z",
    )

    assert outcome is None
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_lane_bridge_is_disabled_by_default(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    current = _running_status()
    store.upsert(current)

    outcome = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "upsert_failed",
            "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
            "provider_session_binding_failure": "projection failure detail",
        },
        updated_at="2026-06-03T03:11:00Z",
    )

    assert outcome is None
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_reconciles_degraded_lanes_after_graph_status_becomes_available(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    lane = {
        "feature_id": "lane-a",
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-feature-a",
        "provider_session_binding_degraded": True,
        "provider_session_binding_degraded_reason": "upsert_failed",
        "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
        "provider_session_binding_failure": "provider store write failed",
    }

    assert reconcile_feature_graph_provider_binding_degradations(
        store=store,
        lanes=[lane],
        updated_at="2026-06-03T03:11:00Z",
    ) == []

    store.upsert(_running_status())
    outcomes = reconcile_feature_graph_provider_binding_degradations(
        store=store,
        lanes=[lane],
        updated_at="2026-06-03T03:12:00Z",
        compatibility_bridge_enabled=True,
    )

    assert len(outcomes) == 1
    assert outcomes[0].evidence.reason == "upsert_failed"
    assert (
        outcomes[0].status.provider_session_binding_degradations[0].binding_id
        == "provider_session_binding:psb-worker-a:v1"
    )


def test_reconcile_bridge_skips_when_graph_native_evidence_already_exists(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    lane = {
        "feature_id": "lane-a",
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-feature-a",
        "provider_session_binding_degraded": True,
        "provider_session_binding_degraded_reason": "upsert_failed",
        "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
        "provider_session_binding_failure": "projection failure detail",
        "feature_lanes_projection_ref": "feature_lanes.json#projection_revision=7",
    }
    first = record_feature_graph_provider_binding_degradation_from_lane(
        store=store,
        lane=lane,
        updated_at="2026-06-03T03:11:00Z",
        compatibility_bridge_enabled=True,
    )

    outcomes = reconcile_feature_graph_provider_binding_degradations(
        store=store,
        lanes=[lane],
        updated_at="2026-06-03T03:12:00Z",
        compatibility_bridge_enabled=True,
    )

    assert first is not None
    assert len(outcomes) == 1
    assert outcomes[0].status == first.status
    assert outcomes[0].evidence == first.evidence
    assert len(store.list_events(graph_set_id="graph-set-1")) == 1


def test_reconcile_bridge_is_disabled_by_default(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    lane = {
        "feature_id": "lane-a",
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-feature-a",
        "provider_session_binding_degraded": True,
        "provider_session_binding_degraded_reason": "upsert_failed",
        "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
        "provider_session_binding_failure": "projection failure detail",
    }

    outcomes = reconcile_feature_graph_provider_binding_degradations(
        store=store,
        lanes=[lane],
        updated_at="2026-06-03T03:12:00Z",
    )

    assert outcomes == []
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ).provider_session_binding_degradations == []
