from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.chat.lane_scope import conversation_scoped_lanes


def test_conversation_scoped_lanes_uses_graph_and_unambiguous_feature_scope(
    tmp_path: Path,
) -> None:
    graphs_dir = tmp_path / "lane_graphs"
    graphs_dir.mkdir()
    (graphs_dir / "alpha-graph.json").write_text(
        json.dumps(
            {
                "id": "alpha-graph",
                "conversation_id": "conv-alpha",
                "lanes": [{"feature_id": "alpha-only"}, {"feature_id": "shared"}],
            }
        ),
        encoding="utf-8",
    )
    (graphs_dir / "beta-graph.json").write_text(
        json.dumps(
            {
                "id": "beta-graph",
                "conversation_id": "conv-beta",
                "lanes": [{"feature_id": "shared"}],
            }
        ),
        encoding="utf-8",
    )
    lanes = [
        {"feature_id": "explicit", "conversation_id": "conv-alpha"},
        {"feature_id": "alpha-graph-lane", "graph_id": "alpha-graph"},
        {"feature_id": "beta-graph-lane", "graph_id": "beta-graph"},
        {"feature_id": "alpha-only"},
        {"feature_id": "shared"},
        {"feature_id": "foreign", "conversation_id": "conv-beta"},
    ]

    scoped = conversation_scoped_lanes(tmp_path, "conv-alpha", lanes)

    assert [lane["feature_id"] for lane in scoped] == [
        "explicit",
        "alpha-graph-lane",
        "alpha-only",
    ]
