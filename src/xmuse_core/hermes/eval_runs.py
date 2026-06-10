from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from xmuse_core.hermes.json_artifacts import read_json


def _counter_dict(values: list[str]) -> dict[str, int]:
    return dict(Counter(value for value in values if value))


counter_dict = _counter_dict


def summarize_eval_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {
            "valid": False,
            "error": "missing report",
            "path": str(report_path),
            "rows_done": 0,
        }
    try:
        rows = read_json(report_path)
    except Exception as exc:
        return {
            "valid": False,
            "error": f"invalid json: {exc}",
            "path": str(report_path),
            "rows_done": 0,
        }
    if not isinstance(rows, list):
        return {
            "valid": False,
            "error": "report root is not a list",
            "path": str(report_path),
            "rows_done": 0,
        }

    verdicts = [str(row.get("verdict", "")).lower() for row in rows if isinstance(row, dict)]
    answer_modes = [
        str(row.get("answer_mode", "missing")).lower() for row in rows if isinstance(row, dict)
    ]
    judge_statuses = [
        str(row.get("judge_status") or row.get("verdict") or "missing").lower()
        for row in rows
        if isinstance(row, dict)
    ]
    movements = [
        str(row.get("movement_status") or row.get("movement", "")).lower()
        for row in rows
        if isinstance(row, dict)
    ]
    last_case_id = None
    if rows and isinstance(rows[-1], dict):
        last_case_id = rows[-1].get("case_id")

    stat = report_path.stat()
    return {
        "valid": True,
        "path": str(report_path),
        "rows_done": len(rows),
        "last_case_id": last_case_id,
        "pass_count": verdicts.count("pass"),
        "fail_count": verdicts.count("fail"),
        "answer_mode_counts": _counter_dict(answer_modes),
        "judge_status_counts": _counter_dict(judge_statuses),
        "movement_counts": _counter_dict(movements),
        "file_size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def _llm_promotion_problem(summary: dict[str, Any]) -> str | None:
    rows_done = summary.get("rows_done", 0)
    if rows_done == 0:
        return "requires llm answer and judge but report has no rows"
    answer_mode_counts = summary.get("answer_mode_counts", {})
    if answer_mode_counts.get("llm", 0) != rows_done:
        return "requires llm answer and judge but some rows are not llm answer mode"
    judge_status_counts = summary.get("judge_status_counts", {})
    non_judged = {
        key: value
        for key, value in judge_status_counts.items()
        if key not in {"pass", "fail", "passed", "failed", "judge_pass", "judge_fail"}
    }
    if non_judged:
        return f"requires llm answer and judge but non-judged rows exist: {non_judged}"
    return None


llm_promotion_problem = _llm_promotion_problem


def classify_eval_run(
    *,
    run_id: str,
    benchmark: str,
    partial_path: str | Path,
    final_path: str | Path,
    previous_snapshot: dict[str, Any] | None = None,
    now: float | None = None,
    stale_after_seconds: int = 900,
    require_llm: bool = True,
) -> dict[str, Any]:
    partial = Path(partial_path)
    final = Path(final_path)
    current_time = time.time() if now is None else now

    if final.exists():
        summary = summarize_eval_report(final)
        state = "completed" if summary.get("valid") else "invalid_final"
        reason = (
            "final report exists" if state == "completed" else summary.get("error", "invalid final")
        )
        if require_llm and summary.get("valid"):
            problem = _llm_promotion_problem(summary)
            if problem:
                state = "invalid_for_promotion"
                reason = problem
        return {
            "run_id": run_id,
            "benchmark": benchmark,
            "state": state,
            "reason": reason,
            **summary,
        }

    if not partial.exists():
        return {
            "run_id": run_id,
            "benchmark": benchmark,
            "state": "missing",
            "reason": "no partial or final report",
            "rows_done": 0,
        }

    summary = summarize_eval_report(partial)
    if not summary.get("valid"):
        return {
            "run_id": run_id,
            "benchmark": benchmark,
            "state": "invalid_partial",
            "reason": summary.get("error", "invalid partial"),
            **summary,
        }

    if require_llm:
        problem = _llm_promotion_problem(summary)
        if problem:
            return {
                "run_id": run_id,
                "benchmark": benchmark,
                "state": "invalid_for_promotion",
                "reason": problem,
                **summary,
            }

    if previous_snapshot:
        grew = (
            summary.get("file_size", 0) > previous_snapshot.get("file_size", 0)
            or summary.get("rows_done", 0) > previous_snapshot.get("rows_done", 0)
            or summary.get("mtime", 0) > previous_snapshot.get("mtime", 0)
        )
        if grew:
            return {
                "run_id": run_id,
                "benchmark": benchmark,
                "state": "running_or_progressing",
                "reason": "partial grew since previous snapshot",
                **summary,
            }

    age = current_time - float(summary.get("mtime", current_time))
    if age > stale_after_seconds:
        return {
            "run_id": run_id,
            "benchmark": benchmark,
            "state": "stalled",
            "reason": f"no final report and partial stale for {age:.0f}s",
            **summary,
        }
    return {
        "run_id": run_id,
        "benchmark": benchmark,
        "state": "running_or_progressing",
        "reason": "partial mtime is fresh",
        **summary,
    }
