from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.platform.feature_graph_dependency_coordinator import (
    release_ready_feature_graph_dependents,
)
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)


def test_release_ready_feature_graph_dependents_uses_status_store_not_projection(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 7, "lanes": [{"feature_id": "legacy"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    graph_set = _graph_set()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initialized = status_store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    _merge_feature_a(status_store, initialized[0])

    outcome = release_ready_feature_graph_dependents(
        store=status_store,
        graph_set=graph_set,
        updated_at="2026-06-03T03:11:00Z",
    )
    replay = release_ready_feature_graph_dependents(
        store=status_store,
        graph_set=graph_set,
        updated_at="2026-06-03T03:11:00Z",
    )

    assert outcome.graph_set == graph_set
    assert [(record.feature_id, record.status) for record in outcome.released] == [
        ("feature-b", FeatureGraphExecutionStatus.READY)
    ]
    assert outcome.released[0].ready_lane_ids == ["feature-b-root"]
    assert replay.released == []
    assert status_store.list_ready(graph_set_id=graph_set.id) == [outcome.released[0]]
    assert lanes_path.read_text(encoding="utf-8") == before_projection


def test_release_ready_feature_graph_dependents_revalidates_graph_set(
    tmp_path: Path,
) -> None:
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    invalid_graph_set = _graph_set().model_copy(update={"id": ""})

    with pytest.raises(ValueError, match="id"):
        release_ready_feature_graph_dependents(
            store=status_store,
            graph_set=invalid_graph_set,
            updated_at="2026-06-03T03:11:00Z",
        )


def test_orchestrator_release_ready_feature_graph_dependents_facade(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "legacy"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    graph_set = _graph_set()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initialized = status_store.initialize_from_graph_set(
        graph_set,
        updated_at="2026-06-03T03:00:00Z",
    )
    _merge_feature_a(status_store, initialized[0])
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.release_ready_feature_graph_dependents(
            graph_set=graph_set,
            updated_at="2026-06-03T03:11:00Z",
        )

    assert [(record.feature_id, record.status) for record in outcome.released] == [
        ("feature-b", FeatureGraphExecutionStatus.READY)
    ]
    assert status_store.get(
        graph_set_id=graph_set.id,
        feature_graph_id="graph-feature-b",
    ) == outcome.released[0]
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def _merge_feature_a(status_store: FeatureGraphStatusStore, ready_status) -> None:
    running = ready_status.model_copy(
        update={
            "status_id": "fgs-feature-a-running",
            "status": FeatureGraphExecutionStatus.RUNNING,
            "ready_lane_ids": [],
            "active_lane_ids": ["feature-a-root"],
            "updated_at": "2026-06-03T03:05:00Z",
        }
    )
    reviewing = running.model_copy(
        update={
            "status_id": "fgs-feature-a-reviewing",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "active_lane_ids": [],
            "completed_lane_ids": ["feature-a-root", "feature-a-verify"],
            "updated_at": "2026-06-03T03:09:00Z",
        }
    )
    merged = reviewing.model_copy(
        update={
            "status_id": "fgs-feature-a-merged",
            "status": FeatureGraphExecutionStatus.MERGED,
            "updated_at": "2026-06-03T03:10:00Z",
        }
    )
    status_store.transition(running)
    status_store.transition(reviewing)
    status_store.transition(merged)


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
