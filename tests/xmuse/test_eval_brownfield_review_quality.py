"""Tests for review quality vs hidden tests.

All fixtures are synthetic directories under ``tmp_path``; nothing runs an
evaluation or touches the network. Assertions check parsed values and JSON
payloads, never exact Markdown wording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval import brownfield_review_quality as quality


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _score_lines(*prs: tuple[int, bool]) -> str:
    lines = []
    for pr, resolved in prs:
        suffix = " RESOLVED" if resolved else ""
        lines.append(f"  #{pr}: f2p 1/2 p2p 0/1{suffix}")
    return "\n".join([*lines, ""])


def _result(reviews: list[dict[str, Any]]) -> str:
    return json.dumps({"schema_version": "board_brownfield_result/v1", "reviews": reviews})


def _review(module: str, status: str, kind: str | None = "participant") -> dict[str, Any]:
    return {
        "module_id": module,
        "status": status,
        "reviewer_kind": kind,
        "created_at": "t",
        "updated_at": "t",
    }


def _run_dir(
    tmp_path: Path,
    run: str,
    *,
    score: str | None = None,
    reviews: list[dict[str, Any]] | None = None,
    suffix: str = ".score.out",
) -> None:
    if score is not None:
        _write(tmp_path / f"{run}{suffix}", score)
    if reviews is not None:
        _write(tmp_path / f"{run}.result.json", _result(reviews))


def test_hidden_pass_fail_unknown(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, True), (2, True), (3, False)),
        reviews=[_review("a", "endorsed"), _review("b", "endorsed")],
    )
    module_prs = {"a": [1, 2], "b": [3], "c": [9], "d": [1, 9]}
    runs, _ = quality.collect_runs(tmp_path, module_prs, [])
    row = {run["run"]: run for run in runs}["v2-A-r1"]
    assert row["modules"]["a"]["hidden"] == "pass"
    assert row["modules"]["b"]["hidden"] == "fail"
    assert row["modules"]["c"]["hidden"] == "unknown"
    # Only a strict subset present and resolved: not enough to judge.
    assert row["modules"]["d"]["hidden"] == "unknown"
    assert row["n_modules"] == 2


def test_ever_objected_vs_final_and_escalated(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, True)),
        reviews=[
            _review("a", "objected", "participant"),
            _review("a", "endorsed", "participant"),
            _review("b", "endorsed", "participant"),
            _review("b", "pending", "operator"),
        ],
    )
    runs, _ = quality.collect_runs(tmp_path, {"a": [1], "b": [1]}, [])
    row = runs[0]
    assert row["modules"]["a"]["ever_objected"] is True
    assert row["modules"]["a"]["final"] == "endorsed"
    assert row["modules"]["a"]["escalated"] is False
    assert row["modules"]["b"]["ever_objected"] is False
    assert row["modules"]["b"]["final"] == "pending"
    assert row["modules"]["b"]["escalated"] is True
    assert row["escalated"] == 1
    assert row["final_counts"]["endorsed"] == 1
    assert row["final_counts"]["pending"] == 1


def test_final_none_without_reviews_for_module(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, False)),
        reviews=[_review("other", "objected")],
    )
    runs, _ = quality.collect_runs(tmp_path, {"a": [1]}, [])
    row = runs[0]
    assert row["modules"]["a"]["ever_objected"] is False
    assert row["modules"]["a"]["final"] == "none"
    assert row["modules"]["a"]["escalated"] is False


def test_precision_recall_endorsement_maths(tmp_path: Path) -> None:
    # a: objected + fail, b: clean + fail, c: endorsed + pass.
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, False), (2, False), (3, True)),
        reviews=[
            _review("a", "objected"),
            _review("b", "endorsed"),
            _review("c", "endorsed"),
        ],
    )
    runs, _ = quality.collect_runs(tmp_path, {"a": [1], "b": [2], "c": [3]}, [])
    row = runs[0]
    assert (row["precision_num"], row["precision_den"]) == (1, 1)
    assert (row["recall_num"], row["recall_den"]) == (1, 2)
    assert (row["endorsement_num"], row["endorsement_den"]) == (1, 2)
    assert quality.format_ratio(1, 2) == "1/2 50%"


def test_zero_denominators_render_dash(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, True)),
        reviews=[_review("a", "endorsed")],
    )
    runs, _ = quality.collect_runs(tmp_path, {"a": [1]}, [])
    row = runs[0]
    assert (row["precision_num"], row["precision_den"]) == (0, 0)
    assert (row["recall_num"], row["recall_den"]) == (0, 0)
    assert (row["endorsement_num"], row["endorsement_den"]) == (1, 1)
    assert quality.format_ratio(0, 0) == "-"
    text = quality.render_markdown(runs, quality.aggregate_arms(runs), [])
    assert "-" in text
    assert "Skipped:" in text
    assert "hidden tests judge the final integrated head" in text.lower()


def test_per_arm_pooling(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, False), (2, True)),
        reviews=[_review("a", "objected"), _review("b", "endorsed")],
    )
    _run_dir(
        tmp_path,
        "v2-A-r2",
        score=_score_lines((1, True), (2, False)),
        reviews=[_review("a", "endorsed"), _review("b", "objected")],
    )
    module_prs = {"a": [1], "b": [2]}
    runs, _ = quality.collect_runs(tmp_path, module_prs, [])
    arms = quality.aggregate_arms(runs)
    assert len(arms) == 1
    arm = arms[0]
    assert arm["arm"] == "A"
    assert arm["n_runs"] == 2
    assert arm["n_modules"] == 4
    # Pooled: two objections, both true positives; two hidden fails.
    assert (arm["precision_num"], arm["precision_den"]) == (2, 2)
    assert (arm["recall_num"], arm["recall_den"]) == (2, 2)
    assert (arm["endorsement_num"], arm["endorsement_den"]) == (2, 2)


def test_skipped_reasons(tmp_path: Path) -> None:
    _write(tmp_path / "v2-A-r1.score.out", _score_lines((1, True)))
    _run_dir(tmp_path, "v2-A-r2", score=_score_lines((1, True)), reviews=[])
    _write(
        tmp_path / "v2-A-r3.result.json",
        json.dumps({"schema_version": "board_brownfield_result/v1", "reviews": []}),
    )
    _run_dir(
        tmp_path,
        "v2-A-r4",
        score=_score_lines((1, True)),
        reviews=[_review("a", "endorsed", "operator")],
    )
    _, skipped = quality.collect_runs(tmp_path, {"a": [1]}, [])
    by_run = {item["run"]: item["reason"] for item in skipped}
    assert by_run["v2-A-r1"] == "no result.json"
    assert by_run["v2-A-r2"] == "no reviews"
    assert by_run["v2-A-r3"] == "no reviews"
    assert by_run["v2-A-r4"] == "no participant reviews"


def test_module_prs_parsing_errors(capsys: Any) -> None:
    with pytest.raises(ValueError):
        quality.parse_module_prs([])
    with pytest.raises(ValueError):
        quality.parse_module_prs(["no-equals"])
    with pytest.raises(ValueError):
        quality.parse_module_prs(["a=notanint"])
    with pytest.raises(ValueError):
        quality.parse_module_prs(["a=1", "a=2"])
    assert quality.parse_module_prs(["a=11854,11888", "b=11901"]) == {
        "a": [11854, 11888],
        "b": [11901],
    }


def test_main_module_prs_error_exit_code(tmp_path: Path, capsys: Any) -> None:
    _write(tmp_path / "v2-A-r1.score.out", _score_lines((1, True)))
    assert quality.main([str(tmp_path), "--module-prs", "oops"]) == 2
    assert "module-prs" in capsys.readouterr().err
    assert quality.main([str(tmp_path)]) == 2


def test_main_missing_dir_returns_error() -> None:
    assert quality.main(["/nonexistent-dir-xyz", "--module-prs", "a=1"]) == 2


def test_exclude_drops_runs(tmp_path: Path) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, True)),
        reviews=[_review("a", "endorsed")],
    )
    _run_dir(
        tmp_path,
        "v2-B-r1",
        score=_score_lines((1, True)),
        reviews=[_review("a", "endorsed")],
    )
    runs, _ = quality.collect_runs(tmp_path, {"a": [1]}, ["A-r1"])
    assert [row["run"] for row in runs] == ["v2-B-r1"]
    assert quality.main([str(tmp_path), "--module-prs", "a=1", "--exclude", "A-r1"]) == 0


def test_main_markdown_and_json(tmp_path: Path, capsys: Any) -> None:
    _run_dir(
        tmp_path,
        "v2-A-r1",
        score=_score_lines((1, False), (2, True)),
        reviews=[_review("a", "objected"), _review("b", "endorsed")],
    )
    assert quality.main([str(tmp_path), "--module-prs", "a=1", "--module-prs", "b=2"]) == 0
    out = capsys.readouterr().out
    assert "precision" in out.lower()
    assert "Skipped:" in out
    assert (
        quality.main([str(tmp_path), "--module-prs", "a=1", "--module-prs", "b=2", "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"runs", "arms", "skipped"}
    assert payload["runs"][0]["run"] == "v2-A-r1"
    assert payload["runs"][0]["precision_num"] == 1
    assert payload["arms"][0]["arm"] == "A"
    assert payload["skipped"] == []
