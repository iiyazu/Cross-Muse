from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphSet,
    FeatureGraphStatusEventRecord,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
    ProviderSessionBindingDegradationEvidence,
)


def _status(
    *,
    status_id: str = "fgs-1",
    graph_set_id: str = "graph-set-1",
    graph_set_version: int = 1,
    feature_id: str = "feature-a",
    feature_graph_id: str = "graph-feature-a",
    status: FeatureGraphExecutionStatus = FeatureGraphExecutionStatus.READY,
    ready_lane_ids: list[str] | None = None,
    active_lane_ids: list[str] | None = None,
    completed_lane_ids: list[str] | None = None,
    blocked_lane_ids: list[str] | None = None,
    provider_session_binding_degradations: list[
        ProviderSessionBindingDegradationEvidence
    ] | None = None,
    updated_at: str = "2026-06-03T03:00:00Z",
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=status_id,
        conversation_id="conv-1",
        planning_run_id="planning-1",
        graph_set_id=graph_set_id,
        graph_set_version=graph_set_version,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        feature_id=feature_id,
        feature_graph_id=feature_graph_id,
        status=status,
        ready_lane_ids=ready_lane_ids or ["lane-a"],
        active_lane_ids=active_lane_ids or [],
        completed_lane_ids=completed_lane_ids or [],
        blocked_lane_ids=blocked_lane_ids or [],
        projection_lane_ids=[
            f"lane:conv-1:{feature_graph_id}:lane-a",
        ],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=7",
        provider_session_binding_degradations=(
            provider_session_binding_degradations or []
        ),
        updated_at=updated_at,
    )


def _graph_set() -> FeatureGraphSet:
    plan = FeaturePlan(
        id="feature-plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=3,
        features=[
            FeaturePlanFeature(
                feature_id="feature-a",
                title="Feature A",
                goal="Build the first feature.",
                acceptance_criteria=["Feature A works."],
                graph_id="graph-feature-a",
                blueprint_refs=["blueprint:bp-1:v1"],
            ),
            FeaturePlanFeature(
                feature_id="feature-b",
                title="Feature B",
                goal="Build the dependent feature.",
                acceptance_criteria=["Feature B works."],
                dependencies=["feature-a"],
                graph_id="graph-feature-b",
                blueprint_refs=["blueprint:bp-1:v1"],
            ),
        ],
    )
    return FeatureGraphSet(
        id="graph-set-1",
        version=3,
        source_refs=["feature_plan:feature-plan-1:v3", "blueprint:bp-1:v1"],
        feature_plan=plan,
        graphs=[
            LaneGraph(
                id="graph-feature-a",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=3,
                lanes=[
                    LaneNode(feature_id="feature-a-root", prompt="Build feature A."),
                    LaneNode(
                        feature_id="feature-a-verify",
                        prompt="Verify feature A.",
                        depends_on=["feature-a-root"],
                    ),
                ],
            ),
            LaneGraph(
                id="graph-feature-b",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=3,
                lanes=[
                    LaneNode(feature_id="feature-b-root", prompt="Build feature B."),
                    LaneNode(
                        feature_id="feature-b-verify",
                        prompt="Verify feature B.",
                        depends_on=["feature-b-root"],
                    ),
                ],
            ),
        ],
    )


def test_feature_graph_status_store_upserts_and_reads_graph_native_record(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    record = _status()

    stored = store.upsert(record)
    found = store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )

    assert stored == record
    assert found == record
    assert store.list(graph_set_id="graph-set-1") == [record]
    raw = json.loads((tmp_path / "feature_graph_statuses.json").read_text())
    assert raw["schema_version"] == "xmuse.feature_graph_statuses.v1"
    assert raw["statuses"][0]["feature_graph_id"] == "graph-feature-a"
    assert raw["events"] == []


def test_feature_graph_status_store_replaces_same_feature_graph_without_duplicates(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_status(status=FeatureGraphExecutionStatus.READY))
    running = _status(
        status_id="fgs-1-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:05:00Z",
    )

    store.upsert(running)

    records = store.list(graph_set_id="graph-set-1")
    assert records == [running]
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ).status is FeatureGraphExecutionStatus.RUNNING


def test_feature_graph_status_store_upsert_is_idempotent_for_same_status_id_replay(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    record = _status()

    first = store.upsert(record)
    replay = store.upsert(record)

    assert first == record
    assert replay == record
    assert store.list(graph_set_id="graph-set-1") == [record]


def test_feature_graph_status_store_rejects_conflicting_status_id_replay(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    original = _status()
    store.upsert(original)
    conflicting = original.model_copy(update={"ready_lane_ids": ["lane-b"]})

    with pytest.raises(ValueError, match="feature graph status replay conflict"):
        store.upsert(conflicting)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == original


def test_feature_graph_status_store_rejects_stale_update_for_same_graph(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    current = _status(
        status=FeatureGraphExecutionStatus.RUNNING,
        updated_at="2026-06-03T03:05:00Z",
    )
    stale = _status(
        status_id="fgs-stale",
        status=FeatureGraphExecutionStatus.READY,
        updated_at="2026-06-03T03:04:59Z",
    )

    store.upsert(current)

    with pytest.raises(ValueError, match="stale feature graph status update"):
        store.upsert(stale)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current


def test_feature_graph_status_store_upsert_rejects_dropped_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    current = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        provider_session_binding_degradations=[degradation],
        updated_at="2026-06-03T03:10:00Z",
    )
    candidate_without_degradation = _status(
        status_id="fgs-running-replay",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:11:00Z",
    )
    store.upsert(current)

    with pytest.raises(
        ValueError,
        match="provider session binding degradation evidence cannot be dropped",
    ):
        store.upsert(candidate_without_degradation)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_upsert_rejects_added_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    current = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    candidate_with_degradation = _status(
        status_id="fgs-running-replay",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        provider_session_binding_degradations=[degradation],
        updated_at="2026-06-03T03:11:00Z",
    )
    store.upsert(current)

    with pytest.raises(
        ValueError,
        match="provider session binding degradation evidence cannot be changed",
    ):
        store.upsert(candidate_with_degradation)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_compares_timestamp_offsets_chronologically(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    current = _status(
        status=FeatureGraphExecutionStatus.RUNNING,
        updated_at="2026-06-03T03:00:00Z",
    )
    lexically_newer_but_chronologically_stale = _status(
        status_id="fgs-offset-stale",
        status=FeatureGraphExecutionStatus.READY,
        updated_at="2026-06-03T04:00:00+02:00",
    )

    store.upsert(current)

    with pytest.raises(ValueError, match="stale feature graph status update"):
        store.upsert(lexically_newer_but_chronologically_stale)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == current


def test_feature_graph_status_store_ready_query_uses_status_store_not_projection(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    projection_path = tmp_path / "feature_lanes.json"
    projection_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "status": "failed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    reviewing = _status(
        status_id="fgs-review",
        feature_id="feature-b",
        feature_graph_id="graph-feature-b",
        status=FeatureGraphExecutionStatus.REVIEWING,
        updated_at="2026-06-03T03:06:00Z",
    )

    store.upsert(ready)
    store.upsert(reviewing)

    assert store.list_ready(graph_set_id="graph-set-1") == [ready]
    assert ready.feature_lanes_projection_ref is not None


def test_feature_graph_status_store_claims_ready_feature_graph_without_projection_write(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    projection_path = tmp_path / "feature_lanes.json"
    projection_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "status": "pending",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = projection_path.read_text(encoding="utf-8")
    store.upsert(ready)

    claimed = store.claim_ready(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )

    assert claimed.status is FeatureGraphExecutionStatus.RUNNING
    assert claimed.ready_lane_ids == []
    assert claimed.active_lane_ids == ["lane-a"]
    assert claimed.active_worker_session_id == "god-session-feature-worker-a"
    assert (
        claimed.active_provider_session_binding_ref
        == "provider_session_binding:psb-worker-a:v1"
    )
    assert store.list_ready(graph_set_id="graph-set-1") == []
    assert projection_path.read_text(encoding="utf-8") == before_projection


def test_feature_graph_status_store_claim_ready_is_idempotent_for_same_claim(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    store.upsert(ready)

    first = store.claim_ready(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )
    replay = store.claim_ready(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )

    assert first == replay
    assert len(
        store.list_events(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
        )
    ) == 1


def test_feature_graph_status_store_claim_ready_rejects_competing_worker(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    store.upsert(ready)
    first = store.claim_ready(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )

    with pytest.raises(ValueError, match="expected feature graph status ready"):
        store.claim_ready(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
            worker_session_id="god-session-feature-worker-b",
            provider_session_binding_ref="provider_session_binding:psb-worker-b:v1",
            updated_at="2026-06-03T03:11:00Z",
        )

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == first


def test_feature_graph_status_store_records_provider_binding_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    evidence = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="mark_failed_failed",
        failure="store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    store.upsert(running)

    updated = store.record_provider_session_binding_degradation(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        evidence=evidence,
        updated_at="2026-06-03T03:11:00Z",
    )

    assert updated.status is FeatureGraphExecutionStatus.RUNNING
    assert updated.provider_session_binding_degradations == [evidence]
    assert updated.updated_at == "2026-06-03T03:11:00Z"
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == updated
    assert [event.model_dump(mode="json") for event in store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )] == [
        {
            "event_id": (
                "fgse:provider-session-binding-degraded:"
                "graph-set-1:graph-feature-a:fgs-running:"
                "provider_session_binding-psb-worker-a-v1:mark_failed_failed"
            ),
            "event_type": "feature_graph_status.provider_session_binding_degraded",
            "graph_set_id": "graph-set-1",
            "graph_set_version": 1,
            "feature_graph_id": "graph-feature-a",
            "feature_id": "feature-a",
            "from_status": "running",
            "to_status": "running",
            "from_status_id": "fgs-running",
            "status_id": (
                "fgs:graph-set-1:graph-feature-a:"
                "provider-session-binding-degraded:"
                "provider_session_binding-psb-worker-a-v1:"
                "mark_failed_failed:20260603T031100z"
            ),
            "updated_at": "2026-06-03T03:11:00Z",
            "idempotency_key": (
                "feature_graph_status.provider_session_binding_degraded:"
                "graph-set-1:graph-feature-a:"
                "provider_session_binding:psb-worker-a:v1:mark_failed_failed"
            ),
        }
    ]


def test_feature_graph_status_store_provider_binding_degradation_is_idempotent(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    evidence = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="mark_failed_failed",
        failure="store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    store.upsert(running)
    first = store.record_provider_session_binding_degradation(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        evidence=evidence,
        updated_at="2026-06-03T03:11:00Z",
    )

    replay = store.record_provider_session_binding_degradation(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
        evidence=evidence,
        updated_at="2026-06-03T03:12:00Z",
    )

    assert replay == first
    assert len(
        store.list_events(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
        )
    ) == 1


def test_feature_graph_status_record_golden_fixture_tracks_active_worker_binding() -> None:
    payload = json.loads(
        Path(
            "tests/fixtures/xmuse/contracts/artifacts/"
            "feature_graph_status_running_claim.v1.json"
        )
        .read_text(encoding="utf-8")
    )["payload"]

    status = FeatureGraphExecutionStatusRecord.model_validate(payload)

    assert status.active_worker_session_id == "god-session-feature-worker-demo"
    assert (
        status.active_provider_session_binding_ref
        == "provider_session_binding:psb_demo:v1"
    )


def test_feature_graph_status_store_keeps_graph_sets_separate(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    first = _status(graph_set_id="graph-set-1")
    second = _status(
        status_id="fgs-2",
        graph_set_id="graph-set-2",
        feature_graph_id="graph-feature-a",
        updated_at="2026-06-03T03:07:00Z",
    )

    store.upsert(first)
    store.upsert(second)

    assert store.list(graph_set_id="graph-set-1") == [first]
    assert store.list(graph_set_id="graph-set-2") == [second]


def test_feature_graph_status_store_initializes_graph_set_statuses(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")

    initialized = store.initialize_from_graph_set(
        _graph_set(),
        updated_at="2026-06-03T03:00:00Z",
    )

    assert [(record.feature_id, record.status) for record in initialized] == [
        ("feature-a", FeatureGraphExecutionStatus.READY),
        ("feature-b", FeatureGraphExecutionStatus.PLANNED),
    ]
    assert initialized[0].ready_lane_ids == ["feature-a-root"]
    assert initialized[0].projection_lane_ids == []
    assert initialized[0].feature_lanes_projection_ref is None
    assert store.list_ready(graph_set_id="graph-set-1") == [initialized[0]]
    assert [
        (event.event_type, event.feature_id, event.from_status, event.to_status)
        for event in store.list_events(graph_set_id="graph-set-1")
    ] == [
        ("feature_graph_status.initialized", "feature-a", None, "ready"),
        ("feature_graph_status.initialized", "feature-b", None, "planned"),
    ]


def test_feature_graph_status_store_repeated_initialize_does_not_duplicate_events(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()

    store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:10:00Z",
    )

    assert [
        event.idempotency_key
        for event in store.list_events(graph_set_id="graph-set-1")
    ] == [
        (
            "feature_graph_status.initialized:"
            "graph-set-1:graph-feature-a:"
            "fgs:graph-set-1:graph-feature-a:ready:20260603T030000z"
        ),
        (
            "feature_graph_status.initialized:"
            "graph-set-1:graph-feature-b:"
            "fgs:graph-set-1:graph-feature-b:planned:20260603T030000z"
        ),
    ]


def test_feature_graph_status_store_initialize_does_not_overwrite_advanced_status(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initialized = store.initialize_from_graph_set(
        _graph_set(),
        updated_at="2026-06-03T03:00:00Z",
    )
    running_feature_a = initialized[0].model_copy(
        update={
            "status_id": "fgs-feature-a-running",
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["feature-a-root"],
            "updated_at": "2026-06-03T03:05:00Z",
        }
    )

    store.transition(running_feature_a)
    second_initialize = store.initialize_from_graph_set(
        _graph_set(),
        updated_at="2026-06-03T03:10:00Z",
    )

    assert second_initialize[0] == running_feature_a
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == running_feature_a
    assert [
        event.event_type
        for event in store.list_events(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
        )
    ] == [
        "feature_graph_status.initialized",
        "feature_graph_status.transitioned",
    ]


def test_feature_graph_status_store_initialize_new_version_preserves_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    initialized = store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=feature-a-root"],
    )
    degraded_feature_a = store.record_provider_session_binding_degradation(
        graph_set_id=initialized[0].graph_set_id,
        feature_graph_id=initialized[0].feature_graph_id,
        evidence=degradation,
        updated_at="2026-06-03T03:05:00Z",
    )
    graph_set_v4 = graph_set.model_copy(
        update={
            "version": 4,
            "source_refs": ["feature_plan:feature-plan-1:v4", "blueprint:bp-1:v1"],
            "feature_plan": graph_set.feature_plan.model_copy(update={"version": 4}),
            "graphs": [
                graph.model_copy(update={"version": 4})
                for graph in graph_set.graphs
            ],
        }
    )

    reinitialized = store.initialize_from_graph_set(
        graph_set_v4,
        updated_at="2026-06-03T03:10:00Z",
    )

    assert reinitialized[0].graph_set_version == 4
    assert reinitialized[0].provider_session_binding_degradations == [degradation]
    assert store.get(
        graph_set_id=degraded_feature_a.graph_set_id,
        feature_graph_id=degraded_feature_a.feature_graph_id,
    ).provider_session_binding_degradations == [degradation]


def test_feature_graph_status_store_releases_ready_dependents_after_merge(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    initialized = store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    running_feature_a = initialized[0].model_copy(
        update={
            "status_id": "fgs-feature-a-running",
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["feature-a-root"],
            "updated_at": "2026-06-03T03:05:00Z",
        }
    )
    reviewing_feature_a = running_feature_a.model_copy(
        update={
            "status_id": "fgs-feature-a-reviewing",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "active_lane_ids": [],
            "completed_lane_ids": ["feature-a-root", "feature-a-verify"],
            "updated_at": "2026-06-03T03:09:00Z",
        }
    )
    merged_feature_a = reviewing_feature_a.model_copy(
        update={
            "status_id": "fgs-feature-a-merged",
            "status": FeatureGraphExecutionStatus.MERGED,
            "updated_at": "2026-06-03T03:10:00Z",
        }
    )

    store.transition(running_feature_a)
    store.transition(reviewing_feature_a)
    store.transition(merged_feature_a)
    released = store.release_ready_dependents(
        graph_set,
        updated_at="2026-06-03T03:11:00Z",
    )

    assert [(record.feature_id, record.status) for record in released] == [
        ("feature-b", FeatureGraphExecutionStatus.READY)
    ]
    assert released[0].ready_lane_ids == ["feature-b-root"]
    assert store.list_ready(graph_set_id="graph-set-1") == [released[0]]


def test_feature_graph_status_store_release_ready_preserves_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    initialized = store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-b:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=feature-b-root"],
    )
    running_feature_a = initialized[0].model_copy(
        update={
            "status_id": "fgs-feature-a-running",
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["feature-a-root"],
            "updated_at": "2026-06-03T03:05:00Z",
        }
    )
    reviewing_feature_a = running_feature_a.model_copy(
        update={
            "status_id": "fgs-feature-a-reviewing",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "active_lane_ids": [],
            "completed_lane_ids": ["feature-a-root", "feature-a-verify"],
            "updated_at": "2026-06-03T03:09:00Z",
        }
    )
    merged_feature_a = reviewing_feature_a.model_copy(
        update={
            "status_id": "fgs-feature-a-merged",
            "status": FeatureGraphExecutionStatus.MERGED,
            "updated_at": "2026-06-03T03:10:00Z",
        }
    )

    store.transition(running_feature_a)
    store.transition(reviewing_feature_a)
    store.transition(merged_feature_a)
    planned_feature_b = store.record_provider_session_binding_degradation(
        graph_set_id=initialized[1].graph_set_id,
        feature_graph_id=initialized[1].feature_graph_id,
        evidence=degradation,
        updated_at="2026-06-03T03:10:30Z",
    )
    released = store.release_ready_dependents(
        graph_set,
        updated_at="2026-06-03T03:11:00Z",
    )

    assert [(record.feature_id, record.status) for record in released] == [
        ("feature-b", FeatureGraphExecutionStatus.READY)
    ]
    assert released[0].provider_session_binding_degradations == [degradation]
    assert store.get(
        graph_set_id=planned_feature_b.graph_set_id,
        feature_graph_id=planned_feature_b.feature_graph_id,
    ).provider_session_binding_degradations == [degradation]


def test_feature_graph_status_store_does_not_release_dependents_before_all_dependencies_merge(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    initialized = store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    running_feature_a = initialized[0].model_copy(
        update={
            "status_id": "fgs-feature-a-running",
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["feature-a-root"],
            "updated_at": "2026-06-03T03:10:00Z",
        }
    )

    store.transition(running_feature_a)

    assert store.release_ready_dependents(
        graph_set,
        updated_at="2026-06-03T03:11:00Z",
    ) == []
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-b",
    ).status is FeatureGraphExecutionStatus.PLANNED


def test_feature_graph_status_store_does_not_release_blocked_for_non_dependency_reason(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    initialized = store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    merged_feature_a = initialized[0].model_copy(
        update={
            "status_id": "fgs-feature-a-merged",
            "status": FeatureGraphExecutionStatus.MERGED,
            "ready_lane_ids": [],
            "completed_lane_ids": ["feature-a-root", "feature-a-verify"],
            "updated_at": "2026-06-03T03:10:00Z",
        }
    )
    blocked_feature_b = initialized[1].model_copy(
        update={
            "status_id": "fgs-feature-b-blocked",
            "status": FeatureGraphExecutionStatus.BLOCKED,
            "blocked_lane_ids": ["feature-b-root"],
            "updated_at": "2026-06-03T03:09:00Z",
        }
    )

    store.upsert(merged_feature_a)
    store.upsert(blocked_feature_b)

    assert store.release_ready_dependents(
        graph_set,
        updated_at="2026-06-03T03:11:00Z",
    ) == []
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-b",
    ) == blocked_feature_b


def test_feature_graph_status_store_requires_all_dependencies_to_match_current_graph_set(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    stale_dependency = _status(
        status_id="fgs-stale-feature-a",
        graph_set_version=2,
        feature_id="feature-a",
        feature_graph_id="graph-feature-a-old",
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        completed_lane_ids=["old-lane"],
        updated_at="2026-06-03T03:00:00Z",
    )
    current_feature_b = _status(
        status_id="fgs-current-feature-b",
        graph_set_version=3,
        feature_id="feature-b",
        feature_graph_id="graph-feature-b",
        status=FeatureGraphExecutionStatus.PLANNED,
        ready_lane_ids=[],
        updated_at="2026-06-03T03:01:00Z",
    )

    store.upsert(stale_dependency)
    store.upsert(current_feature_b)

    assert store.release_ready_dependents(
        graph_set,
        updated_at="2026-06-03T03:11:00Z",
    ) == []
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-b",
    ) == current_feature_b


def test_feature_graph_status_store_transition_applies_allowed_status_change(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(ready)

    transitioned = store.transition(
        running,
        expected_status=FeatureGraphExecutionStatus.READY,
    )

    assert transitioned == running
    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == running
    assert [event.model_dump(mode="json") for event in store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )] == [
        {
            "event_id": "fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
            "event_type": "feature_graph_status.transitioned",
            "graph_set_id": "graph-set-1",
            "graph_set_version": 1,
            "feature_graph_id": "graph-feature-a",
            "feature_id": "feature-a",
            "from_status": "ready",
            "to_status": "running",
            "from_status_id": "fgs-1",
            "status_id": "fgs-running",
            "updated_at": "2026-06-03T03:10:00Z",
            "idempotency_key": (
                "feature_graph_status.transitioned:"
                "graph-set-1:graph-feature-a:fgs-1:fgs-running"
            ),
        }
    ]


def test_feature_graph_status_store_transition_rejects_dropped_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        provider_session_binding_degradations=[degradation],
        updated_at="2026-06-03T03:10:00Z",
    )
    reviewing_without_degradation = _status(
        status_id="fgs-reviewing",
        status=FeatureGraphExecutionStatus.REVIEWING,
        ready_lane_ids=[],
        active_lane_ids=[],
        completed_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:11:00Z",
    )
    store.upsert(running)

    with pytest.raises(
        ValueError,
        match="provider session binding degradation evidence cannot be dropped",
    ):
        store.transition(reviewing_without_degradation)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == running
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_transition_rejects_changed_provider_degradation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb-worker-a:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=lane-a"],
    )
    changed_degradation = ProviderSessionBindingDegradationEvidence(
        binding_id=degradation.binding_id,
        reason=degradation.reason,
        failure="different failure text",
        evidence_refs=list(degradation.evidence_refs),
    )
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        provider_session_binding_degradations=[degradation],
        updated_at="2026-06-03T03:10:00Z",
    )
    reviewing_with_changed_degradation = _status(
        status_id="fgs-reviewing",
        status=FeatureGraphExecutionStatus.REVIEWING,
        ready_lane_ids=[],
        active_lane_ids=[],
        completed_lane_ids=["lane-a"],
        provider_session_binding_degradations=[changed_degradation],
        updated_at="2026-06-03T03:11:00Z",
    )
    store.upsert(running)

    with pytest.raises(
        ValueError,
        match="provider session binding degradation evidence cannot be dropped",
    ):
        store.transition(reviewing_with_changed_degradation)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == running
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_transition_rejects_illegal_status_jump(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    merged = _status(
        status_id="fgs-merged",
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        completed_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(ready)

    with pytest.raises(ValueError, match="cannot transition feature graph status"):
        store.transition(merged)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == ready
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_transition_rejects_conflicting_status_id_replay(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running_with_same_status_id = _status(
        status_id=ready.status_id,
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at=ready.updated_at,
    )

    store.upsert(ready)

    with pytest.raises(ValueError, match="feature graph status replay conflict"):
        store.transition(running_with_same_status_id)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == ready
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_missing_transition_preserves_events(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    graph_set = _graph_set()
    store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    before = store.list_events(graph_set_id="graph-set-1")
    missing = _status(
        status_id="fgs-missing-running",
        feature_id="feature-missing",
        feature_graph_id="graph-feature-missing",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-missing"],
        updated_at="2026-06-03T03:10:00Z",
    )

    with pytest.raises(KeyError, match="feature graph status not found"):
        store.transition(missing)

    assert store.list_events(graph_set_id="graph-set-1") == before


def test_feature_graph_status_store_transition_is_idempotent_for_same_record_replay(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(ready)
    first = store.transition(running)
    second = store.transition(running)

    assert first == running
    assert second == running
    assert store.list(graph_set_id="graph-set-1") == [running]
    assert len(
        store.list_events(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
        )
    ) == 1


def test_feature_graph_status_store_transition_replay_ignores_original_expected_status(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(ready)
    first = store.transition(
        running,
        expected_status=FeatureGraphExecutionStatus.READY,
    )
    replay = store.transition(
        running,
        expected_status=FeatureGraphExecutionStatus.READY,
    )

    assert first == running
    assert replay == running
    assert store.list(graph_set_id="graph-set-1") == [running]


def test_feature_graph_status_store_transition_rejects_terminal_same_status_mutation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    merged = _status(
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        completed_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    mutated_merged = _status(
        status_id="fgs-merged-mutated",
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        completed_lane_ids=["lane-a", "lane-b"],
        updated_at="2026-06-03T03:11:00Z",
    )

    store.upsert(merged)

    with pytest.raises(ValueError, match="same-status transition must be an exact replay"):
        store.transition(mutated_merged)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == merged


def test_feature_graph_status_store_transition_rejects_non_terminal_same_status_mutation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    running = _status(
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    mutated_running = _status(
        status_id="fgs-running-mutated",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-b"],
        updated_at="2026-06-03T03:11:00Z",
    )

    store.upsert(running)

    with pytest.raises(ValueError, match="same-status transition must be an exact replay"):
        store.transition(mutated_running)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == running


def test_feature_graph_status_store_transition_rejects_expected_status_mismatch(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(ready)

    with pytest.raises(ValueError, match="expected feature graph status"):
        store.transition(
            running,
            expected_status=FeatureGraphExecutionStatus.REWORKING,
        )

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == ready
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_stale_transition_preserves_events(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    stale_reviewing = _status(
        status_id="fgs-stale-reviewing",
        status=FeatureGraphExecutionStatus.REVIEWING,
        active_lane_ids=[],
        completed_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:09:00Z",
    )

    store.upsert(ready)
    store.transition(running)
    before = store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )

    with pytest.raises(ValueError, match="stale feature graph status update"):
        store.transition(stale_reviewing)

    assert store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == before


def test_feature_graph_status_store_transition_rejects_terminal_status_mutation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    merged = _status(
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        completed_lane_ids=["lane-a"],
    )
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )

    store.upsert(merged)

    with pytest.raises(ValueError, match="cannot transition feature graph status"):
        store.transition(running)

    assert store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == merged
    assert store.list_events(graph_set_id="graph-set-1") == []


def test_feature_graph_status_store_reads_legacy_payload_without_events(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    assert store.list(graph_set_id="graph-set-1") == [status]
    assert store.list_events(graph_set_id="graph-set-1") == []


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["not-an-object-payload"], "feature graph status payload must be an object"),
        (
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": {"status_id": "not-a-list"},
            },
            "feature graph statuses must be a list",
        ),
        (
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": ["not-a-status-object"],
            },
            "feature graph status must be an object",
        ),
    ],
)
def test_feature_graph_status_store_rejects_corrupt_status_payload(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match=message):
        store.list(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_duplicate_persisted_graph_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    ready = _status(status=FeatureGraphExecutionStatus.READY)
    running = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [
                    ready.model_dump(mode="json"),
                    running.model_dump(mode="json"),
                ],
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(
        ValueError,
        match="duplicate feature graph status identity",
    ):
        store.list(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_conflicting_persisted_status_id_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    original = _status(status_id="fgs-shared")
    conflicting = _status(
        status_id="fgs-shared",
        feature_id="feature-b",
        feature_graph_id="graph-feature-b",
        ready_lane_ids=["lane-b"],
        updated_at="2026-06-03T03:10:00Z",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [
                    original.model_dump(mode="json"),
                    conflicting.model_dump(mode="json"),
                ],
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(
        ValueError,
        match="feature graph status replay conflict",
    ):
        store.list(graph_set_id="graph-set-1")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["not-an-object-payload"], "feature graph status payload must be an object"),
        (
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": {"status_id": "not-a-list"},
            },
            "feature graph statuses must be a list",
        ),
        (
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": ["not-a-status-object"],
            },
            "feature graph status must be an object",
        ),
    ],
)
def test_feature_graph_status_store_preserves_corrupt_status_payload_on_upsert(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match=message):
        store.upsert(_status())

    assert path.read_text(encoding="utf-8") == before


def test_feature_graph_status_store_validates_persisted_events(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    valid_event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-running"
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [valid_event.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )

    store = FeatureGraphStatusStore(path)

    assert store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == [valid_event]

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["events"][0]["event_type"] = "lane.updated"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="event_type must be a feature graph status event"):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_conflicting_event_id_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    original = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-running"
        ),
    )
    conflicting = original.model_copy(update={"updated_at": "2026-06-03T03:11:00Z"})
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [
                    original.model_dump(mode="json"),
                    conflicting.model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match="feature graph status event replay conflict"):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_duplicate_persisted_event_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-running"
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [
                    event.model_dump(mode="json"),
                    event.model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match="feature graph status event replay conflict"):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_event_for_missing_status_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    orphan_event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-missing:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-missing",
        feature_id="feature-missing",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-missing:fgs-1:fgs-running"
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [orphan_event.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(
        ValueError,
        match="feature graph status event references missing status identity",
    ):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_event_with_mismatched_graph_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        graph_set_version=3,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    drifted_event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=2,
        feature_graph_id="graph-feature-a",
        feature_id="feature-stale",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-running"
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [drifted_event.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(
        ValueError,
        match="feature graph status event metadata does not match status identity",
    ):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_event_status_lineage_gap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status(
        status_id="fgs-running",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        updated_at="2026-06-03T03:10:00Z",
    )
    reviewing_event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-reviewing",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.REVIEWING,
        from_status_id="fgs-1",
        status_id="fgs-reviewing",
        updated_at="2026-06-03T03:09:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-reviewing"
        ),
    )
    invalid_event = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-never-seen:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.REVIEWING,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-never-seen",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-never-seen:fgs-running"
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [
                    reviewing_event.model_dump(mode="json"),
                    invalid_event.model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(
        ValueError,
        match="feature graph status event lineage does not match status record",
    ):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_conflicting_event_idempotency_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    original = FeatureGraphStatusEventRecord(
        event_id="fgse:transition:graph-set-1:graph-feature-a:fgs-1:fgs-running",
        event_type="feature_graph_status.transitioned",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_graph_id="graph-feature-a",
        feature_id="feature-a",
        from_status=FeatureGraphExecutionStatus.READY,
        to_status=FeatureGraphExecutionStatus.RUNNING,
        from_status_id="fgs-1",
        status_id="fgs-running",
        updated_at="2026-06-03T03:10:00Z",
        idempotency_key=(
            "feature_graph_status.transitioned:"
            "graph-set-1:graph-feature-a:fgs-1:fgs-running"
        ),
    )
    conflicting = original.model_copy(
        update={
            "updated_at": "2026-06-03T03:11:00Z",
        }
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": [
                    original.model_dump(mode="json"),
                    conflicting.model_dump(mode="json"),
                ],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match="feature graph status event replay conflict"):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_malformed_event_container(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": {"event_id": "not-a-list"},
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match="feature graph status events must be a list"):
        store.list_events(graph_set_id="graph-set-1")


def test_feature_graph_status_store_rejects_malformed_event_entry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feature_graph_statuses.json"
    status = _status()
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_statuses.v1",
                "statuses": [status.model_dump(mode="json")],
                "events": ["not-an-event-object"],
            }
        ),
        encoding="utf-8",
    )
    store = FeatureGraphStatusStore(path)

    with pytest.raises(ValueError, match="feature graph status event must be an object"):
        store.list_events(graph_set_id="graph-set-1")
