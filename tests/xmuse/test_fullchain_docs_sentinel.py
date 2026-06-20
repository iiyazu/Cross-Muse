from __future__ import annotations

import argparse
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


def test_main_writes_expected_note_content_into_command_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run-root"
    execution_worktree = tmp_path / "execution-worktree"
    feature_id = "docs-sentinel-note"

    monkeypatch.setattr(
        sentinel,
        "_parse_args",
        lambda: argparse.Namespace(
            run_root=run_root,
            execution_worktree=execution_worktree,
            feature_id=feature_id,
            chat_port=43111,
            mcp_port=43112,
            proposal_timeout_s=900.0,
            lane_timeout_s=1200.0,
            max_hours=0.75,
            architect_model="gpt-5.4",
            executor_model="gpt-5.4-mini",
        ),
    )

    def stop_after_command_artifacts(*_args, **_kwargs):
        raise RuntimeError("stop after commands")

    monkeypatch.setattr(sentinel, "_start_chat_api", stop_after_command_artifacts)

    assert sentinel.main() == 1

    commands_json = json.loads(
        (run_root / "loop_driver_artifacts" / "commands.json").read_text(
            encoding="utf-8"
        )
    )
    commands_txt = (run_root / "commands.txt").read_text(encoding="utf-8")
    expected_note_content = sentinel._expected_note_content(feature_id)

    assert commands_json["expected_note_content"] == expected_note_content
    assert f"expected_note_content={expected_note_content}\n" in commands_txt
