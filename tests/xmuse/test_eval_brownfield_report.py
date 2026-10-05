"""Offline tests for the brownfield run report.

All fixtures are synthetic directories under ``tmp_path``; nothing runs
an evaluation or touches the network. Assertions check parsed cell
values, never exact Markdown wording.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.eval import brownfield_report


def _score(
    resolved: str = "7/13",
    f2p: str = "228/251",
    regressions: int = 5,
    typecheck: list[str] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "resolved": resolved,
        "f2p": f2p,
        "regressions": regressions,
        "typecheck_fail": typecheck if typecheck is not None else [],
        "flagged_files": [],
        "runner_touched_restored": [],
    }
    return json.dumps(payload)


def _result(
    *,
    wall_seconds: float = 120.0,
    modules: dict[str, Any] | None = None,
    integrated: list[str] | None = None,
    verifications: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
    jobs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "board_brownfield_result/v1",
        "wall_seconds": wall_seconds,
        "modules": modules if modules is not None else {"a": {}, "b": {}, "c": {}},
        "integrated_modules": integrated if integrated is not None else ["a", "b"],
        "verifications": verifications
        if verifications is not None
        else [
            {"module_id": "a", "status": "failed", "reason_code": "x", "created_at": "t"},
            {"module_id": "a", "status": "passed", "reason_code": "", "created_at": "t"},
            {"module_id": "b", "status": "failed", "reason_code": "x", "created_at": "t"},
        ],
        "reviews": reviews
        if reviews is not None
        else [
            {"module_id": "a", "status": "objected", "reviewer_kind": "human"},
            {"module_id": "b", "status": "endorsed", "reviewer_kind": "other"},
            {"module_id": "c", "status": "pending", "reviewer_kind": "other"},
        ],
        "integration_jobs": jobs
        if jobs is not None
        else [
            {"status": "done", "items": [{"module_id": "a", "conflicts_total": 2}]},
            {"status": "done", "items": [{"module_id": "b", "conflicts_total": 3}]},
        ],
    }


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _by_run(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["run"]): row for row in rows}


def test_first_score_line_wins(tmp_path: Path) -> None:
    first = _score(resolved="7/13")
    second = _score(resolved="9/13")
    _write(tmp_path / "v2-C-r1.score.out", f"noise\n{first}\n{second}\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    assert _by_run(rows)["v2-C-r1"]["resolved"] == "7/13"


def test_malformed_first_score_line_is_no_score(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.score.out", '{"resolved": oops\n' + _score() + "\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    row = _by_run(rows)["v2-C-r1"]
    assert row["has_score"] is False
    assert row["resolved"] == "no score"


def test_log_with_invalid_utf8_still_scores(tmp_path: Path) -> None:
    # Single-agent logs embed raw agent output, which need not be valid UTF-8.
    (tmp_path / "v2-A-r1.log").write_bytes(
        b"agent said \xff\xfe\n" + _score(resolved="7/13").encode() + b"\nwall_s=1320\n"
    )

    row = _by_run(brownfield_report.collect_runs(tmp_path, []))["v2-A-r1"]

    assert row["resolved"] == "7/13"
    assert row["wall"] == "1320"


def test_run_without_score_line_is_listed(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", "nothing here\nwall_s=42\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    row = _by_run(rows)["v2-C-r1"]
    assert row["has_score"] is False
    assert row["resolved"] == "no score"
    # The wall fallback still applies to unscored runs.
    assert row["wall"] == "42"


def test_board_counters(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.score.out", _score(typecheck=["packages/tar-parser"]) + "\n")
    _write(tmp_path / "v2-C-r1.result.json", json.dumps(_result()))

    rows = brownfield_report.collect_runs(tmp_path, [])

    row = _by_run(rows)["v2-C-r1"]
    assert row["typecheck"] == "tar-parser"
    assert row["integrated"] == "2/3"
    # Two distinct modules failed; one of them also passed.
    assert row["blocked"] == "2"
    assert row["fixed"] == "1"
    assert row["reviews"] == "1/1"
    assert row["conflicts"] == "5"


def test_typecheck_ok_when_empty(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", _score(typecheck=[]) + "\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    assert _by_run(rows)["v2-C-r1"]["typecheck"] == "ok"


def test_wall_clock_fallback_order(tmp_path: Path) -> None:
    # result.json beats wall_s= ...
    _write(tmp_path / "v2-C-r1.log", _score() + "\nwall_s=10\n")
    _write(tmp_path / "v2-C-r1.result.json", json.dumps(_result(wall_seconds=99.0)))
    # ... which beats nothing.
    _write(tmp_path / "v2-Dp-r1.log", _score() + "\nwall_s=33\n")
    _write(tmp_path / "v2-Dp-r2.log", _score() + "\n")

    rows = brownfield_report.collect_runs(tmp_path, [])
    by_run = _by_run(rows)

    assert by_run["v2-C-r1"]["wall"] == "99"
    assert by_run["v2-Dp-r1"]["wall"] == "33"
    assert by_run["v2-Dp-r2"]["wall"] == "-"


def test_board_cells_dash_without_result(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", _score() + "\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    row = _by_run(rows)["v2-C-r1"]
    assert row["integrated"] == "-"
    assert row["blocked"] == "-"
    assert row["fixed"] == "-"
    assert row["reviews"] == "-"
    assert row["conflicts"] == "-"


def test_exclude_drops_matching_runs(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", _score(resolved="7/13") + "\n")
    _write(tmp_path / "v2-C-r2.log", _score(resolved="9/13") + "\n")

    rows = brownfield_report.collect_runs(tmp_path, ["r1"])

    assert sorted(_by_run(rows)) == ["v2-C-r2"]


def test_per_arm_means_and_n(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", _score(resolved="6/13", f2p="200/251", regressions=4) + "\n")
    _write(tmp_path / "v2-C-r2.log", _score(resolved="8/13", f2p="220/251", regressions=6) + "\n")
    _write(tmp_path / "v2-Dp-r1.log", "no score here\n")

    rows = brownfield_report.collect_runs(tmp_path, [])
    arms = {str(arm["arm"]): arm for arm in brownfield_report.aggregate_arms(rows)}

    assert arms["C"]["n"] == 2
    assert arms["C"]["mean_resolved"] == 7.0
    assert arms["C"]["mean_f2p"] == 210.0
    assert arms["C"]["mean_regressions"] == 5.0
    # Unscored runs do not count toward n.
    assert arms["Dp"]["n"] == 0

    table = brownfield_report.render_markdown(rows, brownfield_report.aggregate_arms(rows))
    arm_row = next(line for line in table.splitlines() if line.startswith("| C |"))
    assert "| 2 |" in arm_row
    assert "7.0" in arm_row


def test_runs_sorted_by_arm_then_rep(tmp_path: Path) -> None:
    for name in ("v2-Dp-r2", "v2-C-r1", "v2-C-r10", "v2-C-r2"):
        _write(tmp_path / f"{name}.log", _score() + "\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    assert [str(row["run"]) for row in rows] == ["v2-C-r1", "v2-C-r2", "v2-C-r10", "v2-Dp-r2"]


def test_stray_files_ignored_but_run_kept(tmp_path: Path) -> None:
    _write(tmp_path / "v2-C-r1.log", _score() + "\n")
    _write(tmp_path / "notes.out", "junk\n")
    _write(tmp_path / "v2-C-r1.err", "junk\n")

    rows = brownfield_report.collect_runs(tmp_path, [])

    assert [str(row["run"]) for row in rows] == ["v2-C-r1"]


def test_json_flag_matches_tables(tmp_path: Path, capsys: Any) -> None:
    _write(tmp_path / "v2-C-r1.score.out", _score() + "\n")
    _write(tmp_path / "v2-C-r1.result.json", json.dumps(_result()))

    assert brownfield_report.main([str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert set(payload) == {"runs", "arms"}
    assert payload["runs"][0]["run"] == "v2-C-r1"
    assert payload["runs"][0]["blocked"] == "2"
    assert payload["arms"][0]["arm"] == "C"
    assert payload["arms"][0]["n"] == 1


def test_markdown_states_n_and_no_significance(tmp_path: Path, capsys: Any) -> None:
    _write(tmp_path / "v2-C-r1.log", _score() + "\n")

    assert brownfield_report.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out

    assert "no significance" in out.lower()
    assert re.search(r"\| C \| 1 \|", out) is not None


def test_missing_dir_returns_error(capsys: Any, tmp_path: Path) -> None:
    assert brownfield_report.main([str(tmp_path / "absent")]) == 2
    assert "not found" in capsys.readouterr().err
