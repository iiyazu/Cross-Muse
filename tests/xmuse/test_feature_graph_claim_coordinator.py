from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.feature_graph_claim_coordinator import (
    claim_next_ready_feature_graph_worker,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
)


def _status(
    *,
    status_id: str,
    graph_set_id: str = "graph-set-1",
    conversation_id: str = "conv-1",
    feature_id: str = "feature-a",
    feature_graph_id: str = "graph-feature-a",
    status: FeatureGraphExecutionStatus = FeatureGraphExecutionStatus.READY,
    ready_lane_ids: list[str] | None = None,
    updated_at: str = "2026-06-03T03:00:00Z",
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=status_id,
        conversation_id=conversation_id,
        planning_run_id="planning-1",
        graph_set_id=graph_set_id,
        graph_set_version=1,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        feature_id=feature_id,
        feature_graph_id=feature_graph_id,
        status=status,
        ready_lane_ids=ready_lane_ids or ["lane-a"],
        active_lane_ids=[],
        completed_lane_ids=[],
        blocked_lane_ids=[],
        projection_lane_ids=[
            f"lane:{conversation_id}:{feature_graph_id}:{(ready_lane_ids or ['lane-a'])[0]}",
        ],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=7",
        updated_at=updated_at,
    )


def test_claim_next_ready_feature_graph_worker_claims_without_projection_write(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    ready = _status(status_id="fgs-ready")
    store.upsert(ready)
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

    outcome = claim_next_ready_feature_graph_worker(
        store=store,
        graph_set_id="graph-set-1",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )

    assert outcome is not None
    assert outcome.plan.source_status_id == "fgs-ready"
    assert outcome.status.status is FeatureGraphExecutionStatus.RUNNING
    assert outcome.status.active_lane_ids == ["lane-a"]
    assert outcome.status.active_worker_session_id == "god-session-feature-worker-a"
    assert store.list_ready(graph_set_id="graph-set-1") == []
    assert projection_path.read_text(encoding="utf-8") == before_projection


def test_claim_next_ready_feature_graph_worker_filters_by_conversation_and_graph(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(
        _status(
            status_id="fgs-conv-2",
            conversation_id="conv-2",
            feature_id="feature-other",
            feature_graph_id="graph-other",
            ready_lane_ids=["other-root"],
            updated_at="2026-06-03T02:59:00Z",
        )
    )
    target = _status(
        status_id="fgs-target",
        conversation_id="conv-1",
        feature_id="feature-target",
        feature_graph_id="graph-target",
        ready_lane_ids=["target-root"],
        updated_at="2026-06-03T03:01:00Z",
    )
    store.upsert(target)

    outcome = claim_next_ready_feature_graph_worker(
        store=store,
        conversation_id="conv-1",
        feature_graph_id="graph-target",
        worker_session_id="god-session-feature-worker-target",
        provider_session_binding_ref=None,
        updated_at="2026-06-03T03:10:00Z",
    )

    assert outcome is not None
    assert outcome.status.feature_graph_id == "graph-target"
    assert outcome.status.active_lane_ids == ["target-root"]
    assert store.get(graph_set_id="graph-set-1", feature_graph_id="graph-other").status is (
        FeatureGraphExecutionStatus.READY
    )


def test_claim_next_ready_feature_graph_worker_returns_none_when_no_ready(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(
        _status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            updated_at="2026-06-03T03:00:00Z",
        )
    )

    assert claim_next_ready_feature_graph_worker(
        store=store,
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref=None,
        updated_at="2026-06-03T03:10:00Z",
    ) is None
    assert store.list_events(graph_set_id="graph-set-1") == []
