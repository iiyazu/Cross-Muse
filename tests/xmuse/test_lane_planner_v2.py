from __future__ import annotations

import pytest

from xmuse_core.structuring.lane_planner_v2 import (
    LanePlannerV2Input,
    LanePlannerV2LaneInput,
    LanePlannerV2ValidationError,
    build_lane_graph_v2,
    validate_lane_plan_v2,
)


def test_lane_planner_v2_builds_normalized_lane_graph() -> None:
    request = _request(
        lanes=[
            _lane("api", acceptance_criteria=["API accepts deliberation events."]),
            _lane(
                "ui",
                acceptance_criteria=["UI renders the frozen blueprint card."],
                depends_on=["api"],
            ),
        ]
    )

    graph = build_lane_graph_v2(request)

    assert graph.id == "res-1-graph-v2"
    assert graph.resolution_id == "res-1"
    assert [lane.feature_id for lane in graph.lanes] == ["api", "ui"]
    assert graph.lanes[1].depends_on == ["api"]
    assert graph.lanes[0].blueprint_refs == ["resolution:bp-1:mission_blueprint"]


def test_lane_planner_v2_rejects_lane_without_acceptance_criteria() -> None:
    request = _request(lanes=[_lane("api", acceptance_criteria=[])])

    report = validate_lane_plan_v2(request)

    assert report.ok is False
    assert report.issues[0].code == "missing_acceptance_criteria"
    assert report.issues[0].subject_id == "api"
    with pytest.raises(LanePlannerV2ValidationError) as exc:
        build_lane_graph_v2(request)
    assert exc.value.to_chat_payload()["errors"][0]["code"] == "missing_acceptance_criteria"


def test_lane_planner_v2_rejects_invalid_blueprint_refs() -> None:
    request = _request(
        lanes=[
            _lane(
                "api",
                acceptance_criteria=["Valid refs are enforced."],
                blueprint_refs=["resolution:missing:mission_blueprint"],
            )
        ]
    )

    report = validate_lane_plan_v2(request)

    assert [issue.code for issue in report.issues] == ["invalid_blueprint_ref"]
    assert "resolution:missing:mission_blueprint" in report.issues[0].message


def test_lane_planner_v2_preserves_deterministic_cycle_rejection() -> None:
    request = _request(
        lanes=[
            _lane("lane-a", acceptance_criteria=["A done."], depends_on=["lane-b"]),
            _lane("lane-b", acceptance_criteria=["B done."], depends_on=["lane-a"]),
        ]
    )

    report = validate_lane_plan_v2(request)

    assert report.ok is False
    assert report.issues[0].code == "invalid_lane_graph"
    assert "dependency cycle detected: lane-a -> lane-b -> lane-a" in report.issues[0].message


def test_lane_planner_v2_errors_are_actionable_for_chat_and_dashboard() -> None:
    request = _request(
        lanes=[
            _lane(
                "api",
                acceptance_criteria=[],
                blueprint_refs=["resolution:missing:mission_blueprint"],
            )
        ]
    )

    payload = validate_lane_plan_v2(request).to_chat_payload()

    assert payload == {
        "ok": False,
        "errors": [
            {
                "code": "missing_acceptance_criteria",
                "message": "lane api must declare at least one acceptance criterion",
                "subject_id": "api",
                "field": "acceptance_criteria",
                "severity": "error",
                "source_refs": ["proposal:lane-plan"],
            },
            {
                "code": "invalid_blueprint_ref",
                "message": (
                    "lane api references unavailable blueprint ref "
                    "resolution:missing:mission_blueprint"
                ),
                "subject_id": "api",
                "field": "blueprint_refs",
                "severity": "error",
                "source_refs": ["proposal:lane-plan"],
            },
        ],
    }


def _request(lanes: list[LanePlannerV2LaneInput]) -> LanePlannerV2Input:
    return LanePlannerV2Input(
        graph_id="res-1-graph-v2",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=2,
        available_blueprint_refs=["resolution:bp-1:mission_blueprint"],
        lanes=lanes,
        source_refs=["proposal:lane-plan"],
    )


def _lane(
    lane_id: str,
    *,
    acceptance_criteria: list[str],
    depends_on: list[str] | None = None,
    blueprint_refs: list[str] | None = None,
) -> LanePlannerV2LaneInput:
    return LanePlannerV2LaneInput(
        lane_id=lane_id,
        title=lane_id.title(),
        prompt=f"Implement {lane_id}.",
        acceptance_criteria=acceptance_criteria,
        depends_on=depends_on or [],
        blueprint_refs=blueprint_refs or ["resolution:bp-1:mission_blueprint"],
        expected_touched_areas=[f"src/{lane_id}"],
    )
