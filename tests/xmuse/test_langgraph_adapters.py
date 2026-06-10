from __future__ import annotations

import importlib
import importlib.abc
import sys
from typing import Any, TypedDict

import pytest


class ShadowReplayState(TypedDict, total=False):
    native_events: list[dict[str, Any]]
    native_artifact_trace: list[dict[str, Any]]
    replayed_events: list[dict[str, Any]]
    replayed_artifact_trace: list[dict[str, Any]]
    lane_status_write_calls: list[str]


def _native_artifact_trace() -> dict[str, list[dict[str, Any]]]:
    return {
        "events": [
            {
                "event_id": "pevt-blueprint-approved",
                "event_type": "blueprint.approved",
                "artifact_refs": ["artifact:blueprint:v1"],
            },
            {
                "event_id": "pevt-feature-plan-ready",
                "event_type": "feature_plan.ready",
                "artifact_refs": ["artifact:feature-plan:v1"],
            },
        ],
        "artifact_trace": [
            {
                "artifact_ref": "artifact:blueprint:v1",
                "source_event_ref": "planning_events.sqlite3#pevt-blueprint-approved",
            },
            {
                "artifact_ref": "artifact:feature-plan:v1",
                "source_event_ref": "planning_events.sqlite3#pevt-feature-plan-ready",
            },
        ],
    }


async def _run_shadow_replay(state: ShadowReplayState) -> ShadowReplayState:
    langgraph = pytest.importorskip("langgraph.graph")

    def load_events(current: ShadowReplayState) -> ShadowReplayState:
        return {
            **current,
            "replayed_events": list(current["native_events"]),
        }

    def replay_artifacts(current: ShadowReplayState) -> ShadowReplayState:
        return {
            **current,
            "replayed_artifact_trace": list(current["native_artifact_trace"]),
        }

    def finish(current: ShadowReplayState) -> ShadowReplayState:
        return {
            **current,
            "lane_status_write_calls": list(current.get("lane_status_write_calls", [])),
        }

    graph = langgraph.StateGraph(ShadowReplayState)
    graph.add_node("load_events", load_events)
    graph.add_node("replay_artifacts", replay_artifacts)
    graph.add_node("finish", finish)
    graph.add_edge(langgraph.START, "load_events")
    graph.add_edge("load_events", "replay_artifacts")
    graph.add_edge("replay_artifacts", "finish")
    graph.add_edge("finish", langgraph.END)
    return await graph.compile().ainvoke(state)


class _BlockLangGraphImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        del path, target
        if fullname == "langgraph" or fullname.startswith("langgraph."):
            raise ModuleNotFoundError("blocked optional langgraph import")
        return None


@pytest.mark.asyncio
async def test_langgraph_shadow_replay_preserves_native_artifact_trace() -> None:
    native = _native_artifact_trace()

    replay = await _run_shadow_replay(
        {
            "native_events": native["events"],
            "native_artifact_trace": native["artifact_trace"],
        }
    )

    assert replay["replayed_events"] == native["events"]
    assert replay["replayed_artifact_trace"] == native["artifact_trace"]


@pytest.mark.asyncio
async def test_langgraph_shadow_replay_does_not_write_lane_status() -> None:
    native = _native_artifact_trace()

    replay = await _run_shadow_replay(
        {
            "native_events": native["events"],
            "native_artifact_trace": native["artifact_trace"],
            "lane_status_write_calls": [],
        }
    )

    assert replay["lane_status_write_calls"] == []


@pytest.mark.asyncio
async def test_langgraph_adapter_contract_replays_native_artifact_trace() -> None:
    from xmuse_core.structuring.langgraph_adapter import LangGraphShadowReplayAdapter

    native = _native_artifact_trace()
    adapter = LangGraphShadowReplayAdapter()

    replay = await adapter.replay(
        native_events=native["events"],
        native_artifact_trace=native["artifact_trace"],
    )

    assert replay["replayed_events"] == native["events"]
    assert replay["replayed_artifact_trace"] == native["artifact_trace"]
    assert replay["lane_status_write_calls"] == []


@pytest.mark.asyncio
async def test_langgraph_adapter_can_be_disabled_without_workflow_dispatch() -> None:
    from xmuse_core.structuring.langgraph_adapter import LangGraphShadowReplayAdapter

    native = _native_artifact_trace()
    adapter = LangGraphShadowReplayAdapter(enabled=False)

    replay = await adapter.replay(
        native_events=native["events"],
        native_artifact_trace=native["artifact_trace"],
    )

    assert replay == {
        "backend": "langgraph-disabled",
        "status": "skipped",
        "replayed_events": native["events"],
        "replayed_artifact_trace": native["artifact_trace"],
        "lane_status_write_calls": [],
    }


@pytest.mark.asyncio
async def test_langgraph_adapter_falls_back_when_langgraph_is_unavailable() -> None:
    for module_name in list(sys.modules):
        if module_name == "langgraph" or module_name.startswith("langgraph."):
            sys.modules.pop(module_name, None)
    sys.modules.pop("xmuse_core.structuring.langgraph_adapter", None)

    blocker = _BlockLangGraphImports()
    sys.meta_path.insert(0, blocker)
    try:
        module = importlib.import_module("xmuse_core.structuring.langgraph_adapter")
        native = _native_artifact_trace()
        replay = await module.LangGraphShadowReplayAdapter().replay(
            native_events=native["events"],
            native_artifact_trace=native["artifact_trace"],
        )
    finally:
        sys.meta_path.remove(blocker)

    assert replay == {
        "backend": "langgraph-unavailable",
        "status": "fake-replayed",
        "replayed_events": native["events"],
        "replayed_artifact_trace": native["artifact_trace"],
        "lane_status_write_calls": [],
    }
