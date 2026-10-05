"""Offline tests for the in-repo board reliability evaluation.

No test starts a provider or touches the network: aggregation runs over
synthetic smoke ``--result`` files, and the run path is exercised with a
stubbed ``subprocess.run``.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.eval import board_eval


def _counters(**overrides: object) -> dict[str, object]:
    counters: dict[str, object] = {
        "done_reports": 0,
        "passed": 0,
        "failed": 0,
        "superseded": 0,
        "errored": 0,
        "rework_rounds": 0,
        "reviews_endorsed": 0,
        "reviews_objected": 0,
        "integrations_conflicted": 0,
        "integrations_gate_failed": 0,
        "conflict_fix_rounds": 0,
    }
    counters.update(overrides)
    return counters


def _module(
    *,
    done_reports: int = 0,
    rework_rounds: int = 0,
    endorsed: int = 0,
    objected: int = 0,
    conflicts: int = 0,
    fix_rounds: int = 0,
    state: str = "verified",
    integration_status: str = "integrated",
) -> dict[str, object]:
    return {
        "counters": _counters(
            done_reports=done_reports,
            rework_rounds=rework_rounds,
            reviews_endorsed=endorsed,
            reviews_objected=objected,
            integrations_conflicted=conflicts,
            conflict_fix_rounds=fix_rounds,
        ),
        "state": state,
        "accepted": state == "verified",
        "integration_status": integration_status,
    }


def _summary(
    *,
    scenario: str,
    ok: bool = True,
    modules: dict[str, object] | None = None,
    wall_seconds: float = 10.0,
) -> dict[str, object]:
    return {
        "ok": ok,
        "scenario": scenario,
        "checks": {"a": True},
        "phases_ok": True,
        "modules": (
            modules
            if modules is not None
            else {"backend": _module(done_reports=1), "frontend": _module(done_reports=1)}
        ),
        "models": {
            "lead": "opencode-go/muse-spark-1.2-contributor",
            "backend": "opencode-go/muse-spark-1.3-contributor",
            "frontend": "opencode-go/muse-spark-1.3-contributor",
        },
        "provider_kinds": {"lead": "opencode", "backend": "opencode", "frontend": "opencode"},
        "wall_seconds": wall_seconds,
        "conversation_id": f"conv-{scenario}",
        "evidence": {},
    }


def _record(
    *,
    scenario: str,
    index: int = 0,
    status: str = "ok",
    wall_s: float | None = 10.0,
    summary: dict[str, object] | None = None,
    no_summary: bool = False,
) -> dict[str, object]:
    return {
        "scenario": scenario,
        "index": index,
        "status": status,
        "wall_s": wall_s,
        "summary": (
            None
            if no_summary
            else (summary if summary is not None else _summary(scenario=scenario))
        ),
        "result_file": f"{scenario}-{index}.json",
        "frontend_cli": "opencode",
    }


def test_aggregate_group_counts_claims_verified_and_rework() -> None:
    records = [
        _record(
            scenario="verify",
            index=0,
            wall_s=30.0,
            summary=_summary(
                scenario="verify",
                modules={
                    "backend": _module(done_reports=2, rework_rounds=1),
                    "frontend": _module(done_reports=1, state="verification_failed"),
                },
                wall_seconds=30.0,
            ),
        ),
        _record(
            scenario="verify",
            index=1,
            wall_s=50.0,
            summary=_summary(scenario="verify", wall_seconds=50.0),
        ),
    ]

    stats = board_eval.aggregate_group(records)

    assert stats["runs"] == 2
    assert stats["ok"] == 2
    assert stats["ok_rate"] == 1.0
    assert stats["claims"] == 5
    assert stats["verified"] == 3
    assert stats["claimed_verified_ratio"] == 3 / 5
    assert stats["false_done_intercepted"] == 1
    assert stats["mean_rework_rounds"] == 0.25
    assert stats["wall_s"] == {"median": 40.0, "min": 30.0, "max": 50.0, "n": 2}
    assert stats["models"] == [
        "opencode-go/muse-spark-1.2-contributor",
        "opencode-go/muse-spark-1.3-contributor",
    ]
    assert stats["provider_kinds"] == ["opencode"]


def test_aggregate_group_tolerates_failed_and_timed_out_runs() -> None:
    records = [
        _record(scenario="integration", index=0),
        _record(
            scenario="integration",
            index=1,
            status="failed",
            summary=_summary(scenario="integration", ok=False),
        ),
        _record(scenario="integration", index=2, status="timeout", no_summary=True),
    ]

    stats = board_eval.aggregate_group(records)

    assert stats["runs"] == 3
    assert stats["ok"] == 1
    assert stats["ok_rate"] == 1 / 3
    # Only the two runs with summaries contribute module metrics.
    assert stats["claims"] == 4
    assert stats["wall_s"]["n"] == 3


def test_aggregate_group_counts_reviews_and_conflicts() -> None:
    records = [
        _record(
            scenario="review",
            summary=_summary(
                scenario="review",
                modules={
                    "backend": _module(done_reports=2, endorsed=1, objected=1),
                    "frontend": _module(done_reports=1, endorsed=1),
                },
            ),
        ),
        _record(
            scenario="integration",
            summary=_summary(
                scenario="integration",
                modules={
                    "backend": _module(done_reports=1, conflicts=1, fix_rounds=1),
                    "frontend": _module(done_reports=2, conflicts=1, fix_rounds=0),
                },
            ),
        ),
    ]

    review = board_eval.aggregate_group([records[0]])
    assert review["reviews_endorsed"] == 2
    assert review["reviews_objected"] == 1
    assert review["review_catches"] == 1

    integration = board_eval.aggregate_group([records[1]])
    assert integration["integration_conflicts"] == 2
    assert integration["mean_conflict_fix_rounds"] == 0.5


def test_build_report_shape() -> None:
    records = [_record(scenario="verify"), _record(scenario="integration", index=1)]

    report = board_eval.build_report(records=records, scenarios=["verify", "integration"], repeat=1)

    assert report["schema_version"] == "board_eval_report/v1"
    assert report["scenarios"] == ["verify", "integration"]
    assert report["repeat"] == 1
    assert set(report["per_scenario"]) == {"verify", "integration"}
    assert report["overall"]["runs"] == 2
    assert len(report["runs"]) == 2
    assert set(report["runs"][0]) == {
        "scenario",
        "index",
        "status",
        "ok",
        "wall_s",
        "result_file",
        "frontend_cli",
        "frontend_cli_auto",
    }


def test_render_markdown_table_states_n_and_no_significance() -> None:
    report = board_eval.build_report(
        records=[_record(scenario="verify")],
        scenarios=["verify"],
        repeat=1,
    )

    table = board_eval.render_markdown_table(report)

    assert "| verify |" in table
    assert "| overall |" in table
    assert "(n=" in table
    assert "no significance" in table.lower()


def _write_result(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_from_results_reaggregates_without_running(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    _write_result(results / "verify-0.json", _summary(scenario="verify", wall_seconds=12.0))
    _write_result(
        results / "integration-0.json",
        _summary(scenario="integration", ok=False, wall_seconds=20.0),
    )
    _write_result(results / "broken.json", "{not json")
    out_dir = tmp_path / "out"

    rc = board_eval.main(
        [
            "board",
            "--scenarios",
            "verify,integration",
            "--from-results",
            str(results),
            "--out",
            str(out_dir),
        ]
    )

    assert rc == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "board_eval_report/v1"
    assert report["repeat"] is None
    assert report["per_scenario"]["verify"]["ok"] == 1
    assert report["per_scenario"]["integration"]["ok"] == 0
    # The invalid file is a recorded failed run, not a crash.
    assert report["overall"]["runs"] == 3
    assert report["overall"]["ok"] == 1
    assert (out_dir / "report.md").is_file()


def test_console_script_wiring() -> None:
    from pathlib import Path as _Path

    pyproject = tomllib.loads(
        (_Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"]["xmuse-eval"] == "scripts.eval.board_eval:main"
    assert callable(board_eval.main)
    args = board_eval.build_parser().parse_args(["board", "--out", "x"])
    assert args.command == "board"


def test_run_mode_aggregates_stubbed_subprocess_runs(tmp_path: Path, monkeypatch: Any) -> None:
    out_dir = tmp_path / "out"

    def _fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert "--result" in cmd
        result_path = Path(cmd[cmd.index("--result") + 1])
        scenario = cmd[cmd.index("--scenario") + 1]
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(_summary(scenario=scenario)), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(board_eval.subprocess, "run", _fake_run)

    rc = board_eval.main(
        [
            "board",
            "--scenarios",
            "verify",
            "--repeat",
            "2",
            "--out",
            str(out_dir),
            "--run-timeout-s",
            "60",
        ]
    )

    assert rc == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["overall"]["runs"] == 2
    assert report["overall"]["ok"] == 2
    assert (out_dir / "runs" / "verify-0.json").is_file()
    assert (out_dir / "runs" / "verify-1.json").is_file()


def test_run_mode_records_timeouts(tmp_path: Path, monkeypatch: Any) -> None:
    out_dir = tmp_path / "out"

    def _fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(board_eval.subprocess, "run", _fake_run)

    rc = board_eval.main(["board", "--scenarios", "verify", "--repeat", "1", "--out", str(out_dir)])

    assert rc == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["overall"]["runs"] == 1
    assert report["overall"]["ok"] == 0
    assert report["runs"][0]["status"] == "timeout"


def test_unknown_scenario_is_rejected() -> None:
    assert (
        board_eval.run_board(
            board_eval.build_parser().parse_args(["board", "--scenarios", "nope", "--out", "x"])
        )
        == 2
    )


def test_summarize_modules_handles_missing_snapshot() -> None:
    stats = board_eval.summarize_modules({"ok": True})

    assert stats["claims"] == 0
    assert stats["modules"] == 0
    assert isinstance(stats, Mapping)
