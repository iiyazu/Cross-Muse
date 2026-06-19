from __future__ import annotations

import json
from pathlib import Path

from scripts import run_fullchain_docs_sentinel as sentinel


def test_wait_for_lane_treats_exec_failed_as_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-exec-failed",
                        "status": "exec_failed",
                        "failure_reason": "execution_infra_unavailable",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fail_on_sleep(_seconds: float) -> None:
        raise AssertionError("exec_failed should be treated as terminal")

    monkeypatch.setattr(sentinel.time, "sleep", fail_on_sleep)

    lane = sentinel._wait_for_lane(
        lanes_path,
        feature_id="lane-exec-failed",
        timeout_s=30,
    )

    assert lane["status"] == "exec_failed"
