import pytest
from pydantic import ValidationError

from xmuse_core.chat.models import StructuredResolution
from xmuse_core.structuring.planner import build_lane_graph


def test_build_lane_graph_preserves_lane_order_and_dependencies() -> None:
    resolution = StructuredResolution(
        id="res-1",
        conversation_id="conv-1",
        version=1,
        derived_from_proposal_ids=["prop-1"],
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Build xmuse MVP",
        status="approved",
        created_at="2026-05-27T00:00:00Z",
        content={
            "lanes": [
                {
                    "feature_id": "chat-plane",
                    "title": "Chat plane",
                    "prompt": "Build the chat plane.",
                    "priority": 90,
                    "capabilities": ["code"],
                    "depends_on": [],
                },
                {
                    "feature_id": "dashboard-read-model",
                    "title": "Dashboard",
                    "prompt": "Build the dashboard read model.",
                    "priority": 60,
                    "capabilities": ["code", "test"],
                    "depends_on": ["chat-plane"],
                },
            ]
        },
    )

    graph = build_lane_graph(resolution)

    assert graph.resolution_id == "res-1"
    assert graph.version == 1
    assert graph.status == "planned"
    assert [lane.feature_id for lane in graph.lanes] == [
        "chat-plane",
        "dashboard-read-model",
    ]
    assert graph.lanes[0].priority == 90
    assert graph.lanes[1].depends_on == ["chat-plane"]


def test_build_lane_graph_falls_back_to_single_lane_from_goal_summary() -> None:
    resolution = StructuredResolution(
        id="res-2",
        conversation_id="conv-1",
        version=2,
        derived_from_proposal_ids=["prop-2"],
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Add a chat-first xmuse surface",
        status="approved",
        created_at="2026-05-27T00:00:00Z",
        content={},
    )

    graph = build_lane_graph(resolution)

    assert len(graph.lanes) == 1
    assert graph.lanes[0].feature_id == "res-2-lane-1"
    assert graph.lanes[0].prompt == "Add a chat-first xmuse surface"
    assert graph.lanes[0].depends_on == []


def test_build_lane_graph_rejects_unknown_lane_dependencies() -> None:
    resolution = StructuredResolution(
        id="res-3",
        conversation_id="conv-1",
        version=3,
        derived_from_proposal_ids=["prop-3"],
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Validate lane dependencies",
        status="approved",
        created_at="2026-05-27T00:00:00Z",
        content={
            "lanes": [
                {
                    "feature_id": "worker",
                    "title": "Worker",
                    "prompt": "Build the worker lane.",
                    "depends_on": ["missing-lane"],
                }
            ]
        },
    )

    with pytest.raises(ValidationError, match="unknown lane dependency: missing-lane"):
        build_lane_graph(resolution)


def test_build_lane_graph_rejects_dependency_cycles() -> None:
    resolution = StructuredResolution(
        id="res-4",
        conversation_id="conv-1",
        version=4,
        derived_from_proposal_ids=["prop-4"],
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Reject cyclic lane graphs",
        status="approved",
        created_at="2026-05-27T00:00:00Z",
        content={
            "lanes": [
                {
                    "feature_id": "lane-a",
                    "title": "Lane A",
                    "prompt": "Implement lane A.",
                    "depends_on": ["lane-b"],
                },
                {
                    "feature_id": "lane-b",
                    "title": "Lane B",
                    "prompt": "Implement lane B.",
                    "depends_on": ["lane-a"],
                },
            ]
        },
    )

    with pytest.raises(
        ValidationError,
        match="dependency cycle detected: lane-a -> lane-b -> lane-a",
    ):
        build_lane_graph(resolution)
