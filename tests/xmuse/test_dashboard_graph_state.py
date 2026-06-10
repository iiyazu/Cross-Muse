from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.dashboard_graph_state import build_derived_graph_state


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_graph(tmp_path: Path, graph_id: str = "graph-a") -> None:
    _write_json(
        tmp_path / "lane_graphs" / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": "conv-a",
            "resolution_id": "res-a",
            "version": 1,
            "lanes": [{"feature_id": "lane-a1", "prompt": "Build A."}],
        },
    )


def test_build_derived_graph_state_reports_merged_graph(tmp_path: Path) -> None:
    _write_graph(tmp_path)
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "lane-a1", "status": "merged", "graph_id": "graph-a"}]},
    )

    state = build_derived_graph_state(tmp_path, "graph-a")

    assert state is not None
    assert state["status"] == "merged"
    assert state["terminal"] is True
    assert state["merged_lineages"] == ["lane-a1"]


def test_build_derived_graph_state_reports_blocked_for_input(tmp_path: Path) -> None:
    _write_graph(tmp_path)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-a1",
                    "status": "blocked_for_input",
                    "graph_id": "graph-a",
                    "clarification_request": {
                        "missing_input": "need API spec",
                        "owner": "human",
                        "resume_path": "provide spec and reproject",
                    },
                }
            ]
        },
    )

    state = build_derived_graph_state(tmp_path, "graph-a")

    assert state is not None
    assert state["status"] == "blocked_for_input"
    assert state["terminal"] is True
    assert state["blocked_objects"] == [
        {
            "lane_id": "lane-a1",
            "missing_input": "need API spec",
            "owner": "human",
            "resume_path": "provide spec and reproject",
        }
    ]
