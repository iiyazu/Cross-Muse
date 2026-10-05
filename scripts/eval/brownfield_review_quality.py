"""Review quality vs hidden tests for brownfield evaluation runs.

Reads one directory of brownfield run files and measures how well
cross-family board review agreed with the hidden upstream tests, per run
and per arm. It only reads files; it never runs an evaluation.

Usage::

    python scripts/eval/brownfield_review_quality.py <logs-dir> \\
        --module-prs a=11854,11888 --module-prs b=11901,11906,11915 [...]
        [--exclude SUBSTRING ...] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval import brownfield_pr_matrix, brownfield_report

FINAL_STATUSES = ("objected", "endorsed", "pending", "superseded")

SKIP_NO_RESULT = "no result.json"
SKIP_NO_REVIEWS = "no reviews"
SKIP_NO_PARTICIPANT = "no participant reviews"

NOTE_LINE = (
    "Note: hidden tests judge the final integrated head, "
    "so an objection that led to a fix is counted against the final result."
)


def parse_module_prs(values: Sequence[str]) -> dict[str, list[int]]:
    """Parse ``--module-prs MODULE=PR[,PR...]`` values into module -> PRs."""

    parsed: dict[str, list[int]] = {}
    for raw in values:
        module, sep, prs_raw = raw.partition("=")
        module = module.strip()
        if not sep or not module:
            raise ValueError(f"invalid --module-prs {raw!r}: expected MODULE=PR[,PR...]")
        if module in parsed:
            raise ValueError(f"duplicate --module-prs module {module!r}")
        parts = [part.strip() for part in prs_raw.split(",")]
        prs: list[int] = []
        for part in parts:
            if not part:
                raise ValueError(f"invalid --module-prs {raw!r}: expected MODULE=PR[,PR...]")
            try:
                number = int(part)
            except ValueError:
                raise ValueError(
                    f"invalid --module-prs {raw!r}: PR {part!r} is not an integer"
                ) from None
            if number <= 0:
                raise ValueError(f"invalid --module-prs {raw!r}: PR {part!r} must be positive")
            if number in prs:
                raise ValueError(f"invalid --module-prs {raw!r}: duplicate PR {number}")
            prs.append(number)
        if not prs:
            raise ValueError(f"invalid --module-prs {raw!r}: expected MODULE=PR[,PR...]")
        parsed[module] = prs
    if not parsed:
        raise ValueError("at least one --module-prs MODULE=PR[,PR...] is required")
    return parsed


def classify_hidden(prs: Sequence[int], score: Mapping[int, Any]) -> str:
    """Classify one module's hidden outcome as ``pass``, ``fail`` or ``unknown``.

    ``pass`` needs every listed PR present and resolved; ``fail`` needs any
    listed PR present and unresolved; otherwise (nothing present, or only a
    strict subset present and resolved) the run says nothing about the
    module, so it is ``unknown``.
    """

    seen = [pr for pr in prs if pr in score]
    if not seen:
        return "unknown"
    for pr in seen:
        result = score[pr]
        resolved = bool(getattr(result, "resolved", False))
        if not resolved:
            return "fail"
    if len(seen) == len(prs):
        return "pass"
    return "unknown"


def analyze_reviews(reviews: Sequence[Mapping[str, Any]], module_id: str) -> tuple[bool, str, bool]:
    """Return ``(ever_objected, final, escalated)`` for one module."""

    owned = [entry for entry in reviews if entry.get("module_id") == module_id]
    ever_objected = any(
        entry.get("status") == "objected" and entry.get("reviewer_kind") == "participant"
        for entry in owned
    )
    if not owned:
        return False, "none", False
    last = owned[-1]
    status = last.get("status")
    final = str(status) if isinstance(status, str) and status in FINAL_STATUSES else "none"
    escalated = last.get("reviewer_kind") == "operator"
    return ever_objected, final, escalated


def load_result_json(path: Path) -> dict[str, Any] | None:
    """Load one ``<run>.result.json`` file, or None when missing/invalid."""

    try:
        # Agent logs need not be valid UTF-8; result files are JSON but stay tolerant.
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def format_ratio(num: int, den: int) -> str:
    """Format ``k/n`` plus a whole-number percentage, or ``-`` when empty."""

    if den == 0:
        return "-"
    return f"{num}/{den} {100 * num / den:.0f}%"


def collect_runs(
    logs_dir: Path,
    module_prs: Mapping[str, Sequence[int]],
    excludes: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Collect per-run review-quality rows and the skipped list."""

    discovered = brownfield_report.discover_runs(logs_dir)
    names = [run for run in discovered if not any(token and token in run for token in excludes)]

    def sort_key(name: str) -> tuple[str, int, str]:
        arm, rep = brownfield_report.parse_run_name(name)
        return (str(arm), int(rep), str(name))

    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for run in sorted(names, key=sort_key):
        files = discovered[run]
        arm, rep = brownfield_report.parse_run_name(run)
        result_path = files.get("result")
        if result_path is None:
            skipped.append({"run": run, "reason": SKIP_NO_RESULT})
            continue
        result = load_result_json(result_path)
        reviews_raw = result.get("reviews") if isinstance(result, dict) else None
        if not isinstance(reviews_raw, list) or not reviews_raw:
            skipped.append({"run": run, "reason": SKIP_NO_REVIEWS})
            continue
        reviews: list[Mapping[str, Any]] = [
            entry for entry in reviews_raw if isinstance(entry, Mapping)
        ]
        if not any(entry.get("reviewer_kind") == "participant" for entry in reviews):
            skipped.append({"run": run, "reason": SKIP_NO_PARTICIPANT})
            continue
        score_path = files.get("score") or files.get("log")
        score = brownfield_pr_matrix.parse_run_file(score_path) if score_path is not None else {}
        modules: dict[str, dict[str, Any]] = {}
        for module_id, prs in module_prs.items():
            ever_objected, final, escalated = analyze_reviews(reviews, module_id)
            hidden = classify_hidden(list(prs), score)
            modules[module_id] = {
                "hidden": hidden,
                "ever_objected": ever_objected,
                "final": final,
                "escalated": escalated,
            }
        counted = {mid: info for mid, info in modules.items() if info["hidden"] != "unknown"}
        n_modules = len(counted)
        n_objected = sum(1 for info in counted.values() if info["ever_objected"])
        n_hidden_fail = sum(1 for info in counted.values() if info["hidden"] == "fail")
        tp = sum(
            1 for info in counted.values() if info["ever_objected"] and info["hidden"] == "fail"
        )
        n_endorsed = sum(1 for info in counted.values() if info["final"] == "endorsed")
        endorse_ok = sum(
            1
            for info in counted.values()
            if info["final"] == "endorsed" and info["hidden"] == "pass"
        )
        n_escalated = sum(1 for info in counted.values() if info["escalated"])
        final_counts = {status: 0 for status in (*FINAL_STATUSES, "none")}
        for info in counted.values():
            final_counts[str(info["final"])] = final_counts.get(str(info["final"]), 0) + 1
        runs.append(
            {
                "run": run,
                "arm": str(arm),
                "rep": int(rep),
                "n_modules": n_modules,
                "n_objected": n_objected,
                "n_hidden_fail": n_hidden_fail,
                "precision_num": tp,
                "precision_den": n_objected,
                "recall_num": tp,
                "recall_den": n_hidden_fail,
                "n_endorsed": n_endorsed,
                "endorsement_num": endorse_ok,
                "endorsement_den": n_endorsed,
                "escalated": n_escalated,
                "final_counts": dict(final_counts),
                "modules": modules,
            }
        )
    skipped.sort(key=lambda entry: sort_key(entry["run"]))
    return runs, skipped


def aggregate_arms(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pool per-run numerators/denominators per arm; every row states its n."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in runs:
        grouped.setdefault(str(row["arm"]), []).append(row)
    arms: list[dict[str, Any]] = []
    for arm in sorted(grouped):
        rows = grouped[arm]
        arms.append(
            {
                "arm": arm,
                "n_runs": len(rows),
                "n_modules": sum(int(row["n_modules"]) for row in rows),
                "n_objected": sum(int(row["n_objected"]) for row in rows),
                "n_hidden_fail": sum(int(row["n_hidden_fail"]) for row in rows),
                "precision_num": sum(int(row["precision_num"]) for row in rows),
                "precision_den": sum(int(row["precision_den"]) for row in rows),
                "recall_num": sum(int(row["recall_num"]) for row in rows),
                "recall_den": sum(int(row["recall_den"]) for row in rows),
                "n_endorsed": sum(int(row["n_endorsed"]) for row in rows),
                "endorsement_num": sum(int(row["endorsement_num"]) for row in rows),
                "endorsement_den": sum(int(row["endorsement_den"]) for row in rows),
                "escalated": sum(int(row["escalated"]) for row in rows),
            }
        )
    return arms


def render_markdown(
    runs: Sequence[Mapping[str, Any]],
    arms: Sequence[Mapping[str, Any]],
    skipped: Sequence[Mapping[str, str]],
) -> str:
    """Render the per-run and per-arm tables plus the skipped line and note."""

    lines = [
        "# Brownfield review quality",
        "",
        "Descriptive small-n summary: every arm row states its n and no significance is claimed.",
        "",
        "| run | modules | objected | hidden fail | precision | recall | "
        "endorsed | endorsement accuracy | escalated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in runs:
        lines.append(
            f"| {row['run']} | {row['n_modules']} | {row['n_objected']} | "
            f"{row['n_hidden_fail']} | "
            f"{format_ratio(int(row['precision_num']), int(row['precision_den']))} | "
            f"{format_ratio(int(row['recall_num']), int(row['recall_den']))} | "
            f"{row['n_endorsed']} | "
            f"{format_ratio(int(row['endorsement_num']), int(row['endorsement_den']))} | "
            f"{row['escalated']} |"
        )
    lines.extend(
        [
            "",
            "| arm | runs | modules | precision | recall | endorsement accuracy | escalated |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for arm in arms:
        lines.append(
            f"| {arm['arm']} | {arm['n_runs']} | {arm['n_modules']} | "
            f"{format_ratio(int(arm['precision_num']), int(arm['precision_den']))} | "
            f"{format_ratio(int(arm['recall_num']), int(arm['recall_den']))} | "
            f"{format_ratio(int(arm['endorsement_num']), int(arm['endorsement_den']))} | "
            f"{arm['escalated']} |"
        )
    lines.append("")
    if skipped:
        lines.append(
            "Skipped: " + ", ".join(f"{item['run']} ({item['reason']})" for item in skipped)
        )
    else:
        lines.append("Skipped: none")
    lines.extend(["", NOTE_LINE, ""])
    return "\n".join(lines)


def build_payload(
    runs: Sequence[Mapping[str, Any]],
    arms: Sequence[Mapping[str, Any]],
    skipped: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Build the ``--json`` payload with the same data as the tables."""

    return {
        "runs": [
            {
                "run": str(row["run"]),
                "arm": str(row["arm"]),
                "rep": int(row["rep"]),
                "n_modules": int(row["n_modules"]),
                "n_objected": int(row["n_objected"]),
                "n_hidden_fail": int(row["n_hidden_fail"]),
                "precision_num": int(row["precision_num"]),
                "precision_den": int(row["precision_den"]),
                "recall_num": int(row["recall_num"]),
                "recall_den": int(row["recall_den"]),
                "n_endorsed": int(row["n_endorsed"]),
                "endorsement_num": int(row["endorsement_num"]),
                "endorsement_den": int(row["endorsement_den"]),
                "escalated": int(row["escalated"]),
                "final_counts": dict(row["final_counts"]),
            }
            for row in runs
        ],
        "arms": [
            {
                "arm": str(arm["arm"]),
                "n_runs": int(arm["n_runs"]),
                "n_modules": int(arm["n_modules"]),
                "n_objected": int(arm["n_objected"]),
                "n_hidden_fail": int(arm["n_hidden_fail"]),
                "precision_num": int(arm["precision_num"]),
                "precision_den": int(arm["precision_den"]),
                "recall_num": int(arm["recall_num"]),
                "recall_den": int(arm["recall_den"]),
                "n_endorsed": int(arm["n_endorsed"]),
                "endorsement_num": int(arm["endorsement_num"]),
                "endorsement_den": int(arm["endorsement_den"]),
                "escalated": int(arm["escalated"]),
            }
            for arm in arms
        ],
        "skipped": [{"run": str(item["run"]), "reason": str(item["reason"])} for item in skipped],
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the review-quality command-line parser."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("logs_dir", type=Path, help="directory of run files")
    parser.add_argument(
        "--module-prs",
        action="append",
        default=[],
        metavar="MODULE=PR[,PR...]",
        help="which upstream PRs a module implements (repeatable, required)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="drop runs whose name contains SUBSTRING (repeatable)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print JSON (keys: runs, arms, skipped) instead of Markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the brownfield review-quality report."""

    args = build_parser().parse_args(argv)
    logs_dir = args.logs_dir
    if not logs_dir.is_dir():
        print(f"brownfield_review_quality: logs dir not found: {logs_dir}", file=sys.stderr)
        return 2
    try:
        module_prs = parse_module_prs(list(args.module_prs))
    except ValueError as exc:
        print(f"brownfield_review_quality: {exc}", file=sys.stderr)
        return 2
    runs, skipped = collect_runs(logs_dir, module_prs, list(args.exclude))
    arms = aggregate_arms(runs)
    if args.json:
        print(json.dumps(build_payload(runs, arms, skipped), indent=2, sort_keys=True))
    else:
        print(render_markdown(runs, arms, skipped), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
