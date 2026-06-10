from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform import master_loop_lanes


def _write_lanes(path: Path, lanes: list[dict]) -> None:
    path.write_text(json.dumps({"lanes": lanes}))


def _read_lanes(path: Path) -> list[dict]:
    return json.loads(path.read_text())["lanes"]


def test_master_loop_lanes_module_loads_ready_lanes_and_updates_retry(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "done-dep",
                "task_type": "execute",
                "prompt": "done",
                "status": "done",
                "worktree": str(tmp_path),
            },
            {
                "feature_id": "retry-me",
                "task_type": "execute",
                "prompt": "retry",
                "status": "failed",
                "auto_retry": True,
                "retry_count": 1,
                "worktree": str(tmp_path),
                "depends_on": ["done-dep"],
                "priority": 50,
            },
            {
                "feature_id": "blocked",
                "task_type": "execute",
                "prompt": "blocked",
                "worktree": str(tmp_path),
                "depends_on": ["missing"],
                "priority": 100,
            },
        ],
    )

    tasks = master_loop_lanes.load_lanes(lanes_path)

    assert [task.feature_id for task in tasks] == ["retry-me"]
    assert tasks[0].lane_metadata["retry_count"] == 2
    retry_lane = _read_lanes(lanes_path)[1]
    assert retry_lane["status"] == "pending"
    assert retry_lane["retry_count"] == 2


def test_master_loop_lanes_module_updates_status_via_projection_syncer(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [{"feature_id": "lane-1", "prompt": "do", "worktree": str(tmp_path)}],
    )

    master_loop_lanes.update_lane_status(lanes_path, "lane-1", "done")

    assert _read_lanes(lanes_path)[0]["status"] == "done"
