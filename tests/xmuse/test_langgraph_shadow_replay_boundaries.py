from __future__ import annotations

from typing import TypedDict

import pytest


class ShadowReplayState(TypedDict, total=False):
    trace: list[dict[str, object]]


@pytest.mark.asyncio
async def test_langgraph_shadow_replay_records_artifact_trace_without_lane_status_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    langgraph = pytest.importorskip("langgraph.graph")
    from xmuse_core.platform.projection.syncer import LaneProjectionSyncer

    direct_status_writes: list[str] = []

    def _forbid_direct_status_write(*args: object, **kwargs: object) -> None:
        direct_status_writes.append("called")
        raise AssertionError("LangGraph shadow replay must not write lane status directly")

    monkeypatch.setattr(LaneProjectionSyncer, "update_lane", _forbid_direct_status_write)
    monkeypatch.setattr(LaneProjectionSyncer, "metadata_update", _forbid_direct_status_write)

    graph = langgraph.StateGraph(ShadowReplayState)

    def blueprint_node(state: ShadowReplayState) -> ShadowReplayState:
        trace = list(state.get("trace", []))
        trace.append(
            {
                "node": "blueprint",
                "event_ref": "planning_events.sqlite3#pevt-blueprint-approved",
                "artifact_ref": "resolution:res-shadow:mission_blueprint",
            }
        )
        return {"trace": trace}

    def feature_plan_node(state: ShadowReplayState) -> ShadowReplayState:
        trace = list(state.get("trace", []))
        trace.append(
            {
                "node": "feature_plan",
                "event_ref": "planning_events.sqlite3#pevt-feature-plan-ready",
                "artifact_ref": "feature_plans/conv-shadow/plan-shadow.v1.json",
            }
        )
        return {"trace": trace}

    graph.add_node("blueprint", blueprint_node)
    graph.add_node("feature_plan", feature_plan_node)
    graph.add_edge(langgraph.START, "blueprint")
    graph.add_edge("blueprint", "feature_plan")
    graph.add_edge("feature_plan", langgraph.END)

    result = await graph.compile().ainvoke({})

    assert result["trace"] == [
        {
            "node": "blueprint",
            "event_ref": "planning_events.sqlite3#pevt-blueprint-approved",
            "artifact_ref": "resolution:res-shadow:mission_blueprint",
        },
        {
            "node": "feature_plan",
            "event_ref": "planning_events.sqlite3#pevt-feature-plan-ready",
            "artifact_ref": "feature_plans/conv-shadow/plan-shadow.v1.json",
        },
    ]
    assert direct_status_writes == []


def test_native_structuring_modules_do_not_import_langgraph() -> None:
    import ast
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    native_paths = [
        path
        for path in (project_root / "src" / "xmuse_core" / "structuring").rglob("*.py")
        if "__pycache__" not in path.parts
    ]

    importers: list[str] = []
    for path in native_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "langgraph" for alias in node.names):
                    importers.append(path.relative_to(project_root).as_posix())
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "langgraph" or node.module.startswith("langgraph."):
                    importers.append(path.relative_to(project_root).as_posix())

    assert sorted(set(importers)) == []
