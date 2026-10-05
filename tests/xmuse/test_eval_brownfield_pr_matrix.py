"""Tests for the per-PR pass matrix (scripts/eval/brownfield_pr_matrix.py)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.eval import brownfield_pr_matrix as matrix


def _write_run(logs_dir: Path, run: str, text: str, suffix: str = ".score.out") -> Path:
    path = logs_dir / f"{run}{suffix}"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_pr_line_resolved_and_unresolved() -> None:
    pr, result = matrix.parse_pr_line("  #11949: f2p 17/17 p2p 57/57 RESOLVED") or (
        0,
        matrix.PrResult(False, (0, 0), (0, 0)),
    )
    assert pr == 11949
    assert result.resolved is True
    assert result.f2p == (17, 17)

    parsed = matrix.parse_pr_line("  #11888: f2p 80/88 p2p 0/0 ")
    assert parsed is not None
    assert parsed[1].resolved is False

    incomplete = matrix.parse_pr_line("  #11906: f2p 1/3 p2p 137/141")
    assert incomplete is not None
    assert incomplete[1].p2p == (137, 141)
    assert incomplete[1].resolved is False


def test_parse_pr_line_ignores_other_lines() -> None:
    assert matrix.parse_pr_line("some log noise") is None
    assert matrix.parse_pr_line("") is None


def test_first_line_wins_for_duplicate_pr(tmp_path: Path) -> None:
    path = _write_run(
        tmp_path,
        "v2-C-r1",
        "  #10: f2p 1/2 p2p 0/1\n  #10: f2p 2/2 p2p 1/1 RESOLVED\n",
    )
    results = matrix.parse_run_file(path)
    assert results[10].resolved is False
    assert results[10].f2p == (1, 2)


def test_score_out_preferred_over_log(tmp_path: Path) -> None:
    _write_run(tmp_path, "v2-C-r1", "  #10: f2p 1/1 p2p 1/1 RESOLVED\n", ".log")
    _write_run(tmp_path, "v2-C-r1", "  #10: f2p 0/1 p2p 0/1\n", ".score.out")
    runs, data, _ = matrix.collect_runs(tmp_path, [])
    assert runs == ["v2-C-r1"]
    assert data["v2-C-r1"][10].resolved is False


def test_format_cell_variants() -> None:
    assert matrix.format_cell(None) == "-"
    assert matrix.format_cell(matrix.PrResult(True, (1, 2), (0, 1))) == "R"
    assert matrix.format_cell(matrix.PrResult(False, (80, 88), (0, 0))) == "80/88"
    assert matrix.format_cell(matrix.PrResult(False, (1, 3), (137, 141))) == "1/3 p137/141"


def test_row_and_column_ordering(tmp_path: Path) -> None:
    # PR 2 resolved once, PR 1 never: PR 1 sorts first (0 < 1).
    _write_run(tmp_path, "v2-D-r2", "  #1: f2p 0/1 p2p 0/1\n  #2: f2p 1/1 p2p 1/1 RESOLVED\n")
    _write_run(tmp_path, "v2-C-r2", "  #1: f2p 0/1 p2p 0/1\n")
    _write_run(tmp_path, "v2-C-r1", "  #1: f2p 0/1 p2p 0/1\n")
    runs, data, _ = matrix.collect_runs(tmp_path, [])
    assert runs == ["v2-C-r1", "v2-C-r2", "v2-D-r2"]
    assert matrix.ordered_prs(data) == [1, 2]
    text = matrix.render_markdown(runs, data, [])
    row_lines = [line for line in text.splitlines() if line.startswith("| #")]
    assert [line.split("|")[1].strip() for line in row_lines] == ["#1", "#2"]
    header = text.splitlines()[0]
    assert header.index("v2-C-r1") < header.index("v2-C-r2") < header.index("v2-D-r2")
    # Resolved column shows k/n where n = runs where the PR appears.
    assert "0/3" in row_lines[0]
    assert "1/1" in row_lines[1]


def test_skipped_and_never_resolved(tmp_path: Path) -> None:
    _write_run(tmp_path, "v2-C-r1", "  #5: f2p 0/2 p2p 0/2\n")
    (tmp_path / "v2-C-r2.log").write_text("no pr lines here\n", encoding="utf-8")
    runs, data, skipped = matrix.collect_runs(tmp_path, [])
    assert runs == ["v2-C-r1"]
    assert skipped == ["v2-C-r2"]
    text = matrix.render_markdown(runs, data, skipped)
    assert "v2-C-r2" in text
    assert "#5" in text
    assert "Never resolved" in text


def test_exclude_drops_runs(tmp_path: Path) -> None:
    _write_run(tmp_path, "v2-C-r1", "  #7: f2p 1/1 p2p 1/1 RESOLVED\n")
    _write_run(tmp_path, "v2-D-r9", "  #7: f2p 0/1 p2p 0/1\n")
    runs, _, _ = matrix.collect_runs(tmp_path, ["D-r9"])
    assert runs == ["v2-C-r1"]


def test_json_payload(tmp_path: Path) -> None:
    _write_run(tmp_path, "v2-C-r1", "  #11: f2p 1/3 p2p 2/3\n")
    (tmp_path / "v2-C-r2.log").write_text("nothing\n", encoding="utf-8")
    runs, data, skipped = matrix.collect_runs(tmp_path, [])
    payload = matrix.build_json_payload(runs, data, skipped)
    assert payload["runs"] == ["v2-C-r1"]
    assert payload["skipped"] == ["v2-C-r2"]
    prs = payload["prs"]
    assert isinstance(prs, dict)
    entry = prs["11"]["v2-C-r1"]
    assert entry == {"resolved": False, "f2p": [1, 3], "p2p": [2, 3]}


def test_main_markdown_and_json(tmp_path: Path, capsys: object) -> None:
    _write_run(tmp_path, "v2-C-r1", "  #20: f2p 2/2 p2p 2/2 RESOLVED\n")
    _write_run(tmp_path, "v2-C-r2", "  #20: f2p 1/2 p2p 1/2\n")
    assert matrix.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "R" in out
    assert "Never resolved" in out
    assert matrix.main([str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["runs"] == ["v2-C-r1", "v2-C-r2"]
    assert payload["prs"]["20"]["v2-C-r1"]["resolved"] is True


def test_main_missing_dir_returns_error() -> None:
    assert matrix.main(["/nonexistent-dir-xyz"]) == 2
