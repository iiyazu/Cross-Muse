from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any, TypedDict


class ShadowReplayState(TypedDict, total=False):
    native_events: list[dict[str, Any]]
    native_artifact_trace: list[dict[str, Any]]
    replayed_events: list[dict[str, Any]]
    replayed_artifact_trace: list[dict[str, Any]]
    lane_status_write_calls: list[str]


def _copy_dicts(values: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(value) for value in values]


def _disabled_result(
    *,
    native_events: Sequence[dict[str, Any]],
    native_artifact_trace: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "backend": "langgraph-disabled",
        "status": "skipped",
        "replayed_events": _copy_dicts(native_events),
        "replayed_artifact_trace": _copy_dicts(native_artifact_trace),
        "lane_status_write_calls": [],
    }


class LangGraphShadowReplayAdapter:
    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    async def replay(
        self,
        *,
        native_events: Sequence[dict[str, Any]],
        native_artifact_trace: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self._enabled:
            return _disabled_result(
                native_events=native_events,
                native_artifact_trace=native_artifact_trace,
            )

        langgraph = _load_langgraph_graph()
        if langgraph is None:
            return {
                "backend": "langgraph-unavailable",
                "status": "fake-replayed",
                "replayed_events": _copy_dicts(native_events),
                "replayed_artifact_trace": _copy_dicts(native_artifact_trace),
                "lane_status_write_calls": [],
            }

        def load_events(state: ShadowReplayState) -> ShadowReplayState:
            return {
                **state,
                "replayed_events": _copy_dicts(state["native_events"]),
            }

        def replay_artifacts(state: ShadowReplayState) -> ShadowReplayState:
            return {
                **state,
                "replayed_artifact_trace": _copy_dicts(state["native_artifact_trace"]),
            }

        def finish(state: ShadowReplayState) -> ShadowReplayState:
            return {
                **state,
                "lane_status_write_calls": [],
            }

        graph = langgraph.StateGraph(ShadowReplayState)
        graph.add_node("load_events", load_events)
        graph.add_node("replay_artifacts", replay_artifacts)
        graph.add_node("finish", finish)
        graph.add_edge(langgraph.START, "load_events")
        graph.add_edge("load_events", "replay_artifacts")
        graph.add_edge("replay_artifacts", "finish")
        graph.add_edge("finish", langgraph.END)
        result = await graph.compile().ainvoke(
            {
                "native_events": _copy_dicts(native_events),
                "native_artifact_trace": _copy_dicts(native_artifact_trace),
            }
        )
        return {
            "backend": "langgraph",
            "status": "shadow-replayed",
            "replayed_events": _copy_dicts(result["replayed_events"]),
            "replayed_artifact_trace": _copy_dicts(result["replayed_artifact_trace"]),
            "lane_status_write_calls": list(result.get("lane_status_write_calls", [])),
        }


def _load_langgraph_graph() -> Any | None:
    try:
        return importlib.import_module("langgraph.graph")
    except ModuleNotFoundError:
        return None


__all__ = ["LangGraphShadowReplayAdapter", "ShadowReplayState"]
