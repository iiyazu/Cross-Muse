import json

import pytest

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.platform.projection.dependents import (
    aggregate_status,
    reproject_dependents_if_needed,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)


def _write_lanes(path, lanes):
    path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")


def _graph_store(tmp_path, graph: LaneGraph) -> LaneGraphStore:
    store = LaneGraphStore(tmp_path / "lane_graphs")
    store.save(graph)
    return store


def _graph(*, lanes: list[LaneNode]) -> LaneGraph:
    return LaneGraph(
        id="graph-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        lanes=lanes,
    )


def _graph_set() -> FeatureGraphSet:
    return FeatureGraphSet(
        id="graph-set-1",
        feature_plan=FeaturePlan(
            id="plan-1",
            conversation_id="conv-1",
            resolution_id="res-1",
            version=1,
            features=[
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Schema",
                    goal="Build schema.",
                    acceptance_criteria=["Schema lanes merge."],
                    graph_id="graph-schema",
                ),
                FeaturePlanFeature(
                    feature_id="projection",
                    title="Projection",
                    goal="Build projection.",
                    acceptance_criteria=["Projection lanes merge."],
                    dependencies=["schema"],
                    graph_id="graph-projection",
                ),
            ],
        ),
        graphs=[
            LaneGraph(
                id="graph-schema",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=1,
                lanes=[LaneNode(feature_id="schema-root", prompt="Build schema.")],
            ),
            LaneGraph(
                id="graph-projection",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=1,
                lanes=[
                    LaneNode(feature_id="projection-root", prompt="Build projection root."),
                    LaneNode(
                        feature_id="projection-dependent",
                        prompt="Build projection dependent.",
                        depends_on=["projection-root"],
                    ),
                    LaneNode(
                        feature_id="projection-blocked",
                        prompt="Build blocked lane.",
                        depends_on=["projection-dependent"],
                    ),
                ],
            ),
        ],
    )


def _projection_lane_id(
    graph_id: str,
    lane_local_id: str,
    *,
    conversation_id: str = "conv-1",
) -> str:
    return build_projection_lane_id(
        conversation_id=conversation_id,
        graph_id=graph_id,
        lane_local_id=lane_local_id,
    )


def _graph_set_for_conversation(conversation_id: str) -> FeatureGraphSet:
    graph_set = _graph_set().model_copy(deep=True)
    graph_set.feature_plan.conversation_id = conversation_id
    for graph in graph_set.graphs:
        graph.conversation_id = conversation_id
    return graph_set


@pytest.mark.asyncio
async def test_reproject_dependents_handles_feature_group_none(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "lane-1",
                "status": "merged",
                "prompt": "build chat",
                "graph_id": "graph-1",
            }
        ],
    )
    graph_store = _graph_store(
        tmp_path,
        _graph(
            lanes=[
                LaneNode(feature_id="lane-1", prompt="build chat"),
                LaneNode(
                    feature_id="lane-2",
                    prompt="build dashboard",
                    depends_on=["lane-1"],
                    feature_group=None,
                ),
            ]
        ),
    )

    await reproject_dependents_if_needed(
        "lane-1",
        sm=LaneStateMachine(lanes_path),
        graph_store=graph_store,
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-2"]
    assert lanes[1]["status"] == "pending"
    assert "feature_group" not in lanes[1]
    lane_1 = next(lane for lane in lanes if lane["feature_id"] == "lane-1")
    assert lane_1["dependency_projection_count"] == 1
    assert lane_1["dependency_projection_processed_at"] > 0


@pytest.mark.asyncio
async def test_reproject_dependents_waits_for_all_unmerged_dependencies(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {"feature_id": "lane-a", "status": "merged", "prompt": "first", "graph_id": "graph-1"},
            {
                "feature_id": "lane-b",
                "status": "pending",
                "prompt": "second",
                "graph_id": "graph-1",
            },
            {
                "feature_id": "lane-d",
                "status": "executed",
                "prompt": "third",
                "graph_id": "graph-1",
            },
        ],
    )
    graph_store = _graph_store(
        tmp_path,
        _graph(
            lanes=[
                LaneNode(feature_id="lane-a", prompt="first"),
                LaneNode(feature_id="lane-b", prompt="second"),
                LaneNode(feature_id="lane-d", prompt="third"),
                LaneNode(
                    feature_id="lane-c",
                    prompt="combine results",
                    depends_on=["lane-a", "lane-b", "lane-d"],
                ),
            ]
        ),
    )

    await reproject_dependents_if_needed(
        "lane-a",
        sm=LaneStateMachine(lanes_path),
        graph_store=graph_store,
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == ["lane-a", "lane-b", "lane-d"]
    assert lanes[0]["dependency_projection_count"] == 0


@pytest.mark.asyncio
async def test_reproject_dependents_projects_after_all_dependencies_merged(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {"feature_id": "lane-a", "status": "merged", "prompt": "first", "graph_id": "graph-1"},
            {"feature_id": "lane-b", "status": "merged", "prompt": "second", "graph_id": "graph-1"},
        ],
    )
    graph_store = _graph_store(
        tmp_path,
        _graph(
            lanes=[
                LaneNode(feature_id="lane-a", prompt="first"),
                LaneNode(feature_id="lane-b", prompt="second"),
                LaneNode(
                    feature_id="lane-c",
                    prompt="combine results",
                    depends_on=["lane-a", "lane-b"],
                    feature_group="chat/resolution",
                ),
            ]
        ),
    )

    await reproject_dependents_if_needed(
        "lane-a",
        sm=LaneStateMachine(lanes_path),
        graph_store=graph_store,
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == ["lane-a", "lane-b", "lane-c"]
    assert lanes[2]["status"] == "pending"
    assert lanes[2]["feature_group"] == "chat/resolution"
    assert lanes[0]["dependency_projection_count"] == 1


@pytest.mark.asyncio
async def test_reproject_dependents_records_missing_graph_once_and_retries_later(
    tmp_path,
    caplog,
):
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "lane-1",
                "status": "merged",
                "prompt": "first",
                "graph_id": "graph-1",
            }
        ],
    )
    graph_store = LaneGraphStore(tmp_path / "lane_graphs")

    caplog.set_level("WARNING", logger="xmuse_core.platform.projection.dependents")
    sm = LaneStateMachine(lanes_path)
    await reproject_dependents_if_needed("lane-1", sm=sm, graph_store=graph_store)
    await reproject_dependents_if_needed("lane-1", sm=sm, graph_store=graph_store)

    missing_logs = [
        record
        for record in caplog.records
        if "lane_graph_not_found" in record.getMessage()
    ]
    assert len(missing_logs) == 1
    lane = LaneStateMachine(lanes_path).get_lane("lane-1")
    assert lane["dependency_projection_missing_graph_id"] == "graph-1"
    assert "dependency_projection_processed_at" not in lane

    graph_store.save(
        _graph(
            lanes=[
                LaneNode(feature_id="lane-1", prompt="first"),
                LaneNode(
                    feature_id="lane-2",
                    prompt="second",
                    depends_on=["lane-1"],
                ),
            ]
        ),
    )

    await reproject_dependents_if_needed(
        "lane-1",
        sm=LaneStateMachine(lanes_path),
        graph_store=graph_store,
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-2"]
    assert lanes[0]["dependency_projection_count"] == 1
    assert lanes[0]["dependency_projection_processed_at"] > 0
    assert lanes[0]["dependency_projection_missing_graph_id"] is None
    assert lanes[0]["dependency_projection_missing_graph_resolved_at"] > 0


@pytest.mark.asyncio
async def test_reproject_dependents_projects_graph_set_dependents_by_graph_id(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )
    graph_set_store = FeatureGraphSetStore(tmp_path / "graph_sets")
    graph_set_path = graph_set_store.save(_graph_set())
    before_snapshot = graph_set_path.read_text(encoding="utf-8")

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(tmp_path / "lane_graphs"),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        projection_dependent_id,
    ]
    assert lanes[2]["lane_id"] == projection_dependent_id
    assert lanes[2]["lane_local_id"] == "projection-dependent"
    assert lanes[2]["depends_on"] == [projection_root_id]
    assert lanes[2]["lane_depends_on_ids"] == [projection_root_id]
    assert lanes[2]["status"] == "pending"
    assert lanes[2]["feature_plan_id"] == "plan-1"
    assert lanes[2]["plan_feature_id"] == "projection"
    assert lanes[2]["graph_id"] == "graph-projection"
    assert lanes[1]["dependency_projection_count"] == 1
    assert lanes[1]["dependency_projection_processed_at"] > 0
    assert lanes[1]["dependency_projection_processed_status"] == "merged"
    assert graph_set_path.read_text(encoding="utf-8") == before_snapshot


@pytest.mark.asyncio
async def test_reproject_dependents_does_not_mark_non_success_lanes_processed(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "reviewed",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
                "graph_set_id": "graph-set-1",
            },
        ],
    )
    FeatureGraphSetStore(tmp_path / "graph_sets").save(_graph_set())
    sm = LaneStateMachine(lanes_path)

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=sm,
        graph_store=LaneGraphStore(tmp_path / "lane_graphs"),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
    ]
    assert "dependency_projection_processed_at" not in lanes[1]

    sm.transition(projection_root_id, "merged")
    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(tmp_path / "lane_graphs"),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        projection_dependent_id,
    ]
    assert lanes[1]["dependency_projection_processed_status"] == "merged"


@pytest.mark.asyncio
async def test_reproject_dependents_retries_legacy_zero_count_marker(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
                "graph_set_id": "graph-set-1",
                "dependency_projection_processed_at": 1.0,
                "dependency_projection_count": 0,
                "dependency_projection_source": "graph_set",
            },
        ],
    )
    FeatureGraphSetStore(tmp_path / "graph_sets").save(_graph_set())

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(tmp_path / "lane_graphs"),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        projection_dependent_id,
    ]
    assert lanes[1]["dependency_projection_count"] == 1
    assert lanes[1]["dependency_projection_processed_status"] == "merged"


@pytest.mark.asyncio
async def test_reproject_dependents_projects_sanitized_graph_set_lanes(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
                "graph_set_id": "graph-set-1",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
                "graph_set_id": "graph-set-1",
            },
        ],
    )
    FeatureGraphSetStore(tmp_path / "graph_sets").save(_graph_set())

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(tmp_path / "lane_graphs"),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    projected = lanes[2]
    assert projected["lane_local_id"] == "projection-dependent"
    assert "prompt" not in projected
    assert projected["prompt_summary"] == "Build projection dependent."
    assert projected["prompt_ref"].endswith(".md")
    assert (tmp_path / projected["prompt_ref"]).read_text(encoding="utf-8") == (
        "Build projection dependent."
    )
    assert projected["graph_set_id"] == "graph-set-1"
    assert projected["graph_set_version"] == 1
    assert projected["feature_plan_version"] == 1
    assert projected["projection_source"] == "graph_set"


@pytest.mark.asyncio
async def test_reproject_dependents_finds_graph_set_snapshot_in_lane_graphs_root(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )
    lane_graphs_root = tmp_path / "lane_graphs"
    lane_graphs_root.mkdir()
    graph_set_path = lane_graphs_root / "graph-set-1.json"
    graph_set_path.write_text(
        _graph_set().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(lane_graphs_root),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        projection_dependent_id,
    ]
    assert lanes[2]["lane_local_id"] == "projection-dependent"
    assert lanes[1]["dependency_projection_source"] == "graph_set"
    assert lanes[1]["dependency_projection_count"] == 1


@pytest.mark.asyncio
async def test_reproject_dependents_prefers_lane_graphs_snapshot_over_legacy_graph_sets(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )
    lane_graphs_root = tmp_path / "lane_graphs"
    legacy_root = tmp_path / "graph_sets"
    lane_graphs_root.mkdir()
    legacy_root.mkdir()
    current_graph_set = _graph_set()
    stale_graph_set = _graph_set()
    stale_graph_set.graphs[1].lanes[1].feature_id = "stale-dependent"
    stale_graph_set.graphs[1].lanes[2].depends_on = ["stale-dependent"]
    (lane_graphs_root / "current.json").write_text(
        current_graph_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (legacy_root / "stale.json").write_text(
        stale_graph_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(lane_graphs_root),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        projection_dependent_id,
    ]


@pytest.mark.asyncio
async def test_reproject_dependents_prefers_lane_graph_set_id_over_sorted_graph_match(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    schema_root_id = _projection_lane_id("graph-schema", "schema-root")
    projection_root_id = _projection_lane_id("graph-projection", "projection-root")
    current_dependent_id = _projection_lane_id(
        "graph-projection",
        "current-dependent",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": schema_root_id,
                "lane_id": schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
                "graph_set_id": "current-graph-set",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
                "graph_set_id": "current-graph-set",
            },
        ],
    )
    lane_graphs_root = tmp_path / "lane_graphs"
    lane_graphs_root.mkdir()
    stale_graph_set = _graph_set().model_copy(update={"id": "stale-graph-set"}, deep=True)
    stale_graph_set.graphs[1].lanes[1].feature_id = "stale-dependent"
    stale_graph_set.graphs[1].lanes[2].depends_on = ["stale-dependent"]
    current_graph_set = _graph_set().model_copy(update={"id": "current-graph-set"}, deep=True)
    current_graph_set.graphs[1].lanes[1].feature_id = "current-dependent"
    current_graph_set.graphs[1].lanes[2].depends_on = ["current-dependent"]
    (lane_graphs_root / "a-stale.json").write_text(
        stale_graph_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (lane_graphs_root / "z-current.json").write_text(
        current_graph_set.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(lane_graphs_root),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        schema_root_id,
        projection_root_id,
        current_dependent_id,
    ]


@pytest.mark.asyncio
async def test_reproject_dependents_does_not_count_other_conversation_terminals(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    other_schema_root_id = _projection_lane_id(
        "graph-schema",
        "schema-root",
        conversation_id="conv-other",
    )
    schema_root_id = _projection_lane_id(
        "graph-schema",
        "schema-root",
        conversation_id="conv-1",
    )
    projection_root_id = _projection_lane_id(
        "graph-projection",
        "projection-root",
        conversation_id="conv-1",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": other_schema_root_id,
                "lane_id": other_schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-other",
                "status": "merged",
                "prompt": "Build other schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": projection_root_id,
                "lane_id": projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )
    lane_graphs_root = tmp_path / "lane_graphs"
    lane_graphs_root.mkdir()
    (lane_graphs_root / "graph-set-1.json").write_text(
        _graph_set_for_conversation("conv-1").model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    await reproject_dependents_if_needed(
        projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(lane_graphs_root),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        other_schema_root_id,
        projection_root_id,
        schema_root_id,
    ]
    assert lanes[2]["lane_local_id"] == "schema-root"
    assert lanes[1]["dependency_projection_count"] == 1


@pytest.mark.asyncio
async def test_reproject_dependents_selects_graph_set_for_triggering_conversation(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    other_schema_root_id = _projection_lane_id(
        "graph-schema",
        "schema-root",
        conversation_id="conv-other",
    )
    other_projection_root_id = _projection_lane_id(
        "graph-projection",
        "projection-root",
        conversation_id="conv-other",
    )
    other_projection_dependent_id = _projection_lane_id(
        "graph-projection",
        "projection-dependent",
        conversation_id="conv-other",
    )
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": other_schema_root_id,
                "lane_id": other_schema_root_id,
                "lane_local_id": "schema-root",
                "conversation_id": "conv-other",
                "status": "merged",
                "prompt": "Build other schema.",
                "graph_id": "graph-schema",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "schema",
            },
            {
                "feature_id": other_projection_root_id,
                "lane_id": other_projection_root_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-other",
                "status": "merged",
                "prompt": "Build other projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )
    lane_graphs_root = tmp_path / "lane_graphs"
    lane_graphs_root.mkdir()
    (lane_graphs_root / "a-conv-1.json").write_text(
        _graph_set_for_conversation("conv-1").model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (lane_graphs_root / "b-conv-other.json").write_text(
        _graph_set_for_conversation("conv-other").model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    await reproject_dependents_if_needed(
        other_projection_root_id,
        sm=LaneStateMachine(lanes_path),
        graph_store=LaneGraphStore(lane_graphs_root),
    )

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == [
        other_schema_root_id,
        other_projection_root_id,
        other_projection_dependent_id,
    ]
    assert {lane["conversation_id"] for lane in lanes} == {"conv-other"}
    assert lanes[2]["lane_local_id"] == "projection-dependent"
    assert lanes[1]["dependency_projection_count"] == 1


@pytest.mark.asyncio
async def test_reproject_dependents_records_missing_graph_set_once(tmp_path, caplog):
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "projection-root",
                "status": "merged",
                "prompt": "Build projection root.",
                "graph_id": "graph-projection",
                "feature_plan_id": "plan-1",
                "plan_feature_id": "projection",
            },
        ],
    )

    caplog.set_level("WARNING", logger="xmuse_core.platform.projection.dependents")
    sm = LaneStateMachine(lanes_path)
    graph_store = LaneGraphStore(tmp_path / "lane_graphs")
    await reproject_dependents_if_needed("projection-root", sm=sm, graph_store=graph_store)
    await reproject_dependents_if_needed("projection-root", sm=sm, graph_store=graph_store)

    missing_graph_set_logs = [
        record
        for record in caplog.records
        if "feature_graph_set_not_found" in record.getMessage()
    ]
    assert len(missing_graph_set_logs) == 1
    lane = LaneStateMachine(lanes_path).get_lane("projection-root")
    assert lane["dependency_projection_missing_graph_id"] == "graph-projection"
    assert lane["dependency_projection_missing_graph_set_graph_id"] == "graph-projection"
    assert "dependency_projection_processed_at" not in lane


def test_aggregate_status_reports_graph_lanes(tmp_path):
    lanes = [
        {"feature_id": "other", "status": "pending", "graph_id": "other-graph"},
        {"feature_id": "lane-a", "status": "merged", "graph_id": "graph-1"},
        {"feature_id": "lane-b", "status": "pending", "graph_id": "graph-1"},
    ]

    status = aggregate_status(lanes, "graph-1")

    assert status.graph_id == "graph-1"
    assert status.status == "in_progress"
    assert status.terminal is False
    assert status.lane_counts["total"] == 2
