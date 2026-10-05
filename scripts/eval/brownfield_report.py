"""Brownfield run report (offline Markdown/JSON comparison tables).

Turns one directory of brownfield evaluation run files into per-run and
per-arm comparison tables. It only reads files; it never runs an
evaluation.

Usage::

    python scripts/eval/brownfield_report.py <logs-dir> [--exclude SUB ...] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RUN_NAME_RE = re.compile(r"^(?P<prefix>.+)-(?P<arm>[A-Za-z]+)-r(?P<rep>\d+)$")
SCORE_PREFIX = '{"resolved"'


def parse_run_name(name: str) -> tuple[str, int]:
    """Split ``<prefix>-<ARM>-r<REP>`` into ``(arm, rep)``.

    Names that do not match keep their own identity: the whole name
    becomes the arm with rep 0 so they still sort deterministically.
    """

    match = RUN_NAME_RE.match(name)
    if match is None:
        return name, 0
    return match.group("arm"), int(match.group("rep"))


def parse_fraction(raw: Any) -> tuple[int | None, int | None]:
    """Parse an ``"num/den"`` cell into ints, or ``(None, None)``."""

    if not isinstance(raw, str):
        return None, None
    num, sep, den = raw.partition("/")
    if not sep:
        return None, None
    try:
        return int(num.strip()), int(den.strip())
    except ValueError:
        return None, None


def find_score(text: str) -> dict[str, Any] | None:
    """Return the first score-line object, or None when there is no score.

    The score is the FIRST line whose stripped form starts with
    ``{"resolved"``. First match wins: a malformed JSON line means the
    run has no score, it does not fall through to later lines.
    """

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(SCORE_PREFIX):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def find_wall_fallback(text: str) -> int | None:
    """Return the first ``wall_s=<int>`` value at a line start, if any."""

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("wall_s="):
            try:
                return int(stripped[len("wall_s=") :].strip())
            except ValueError:
                continue
    return None


def load_result(path: Path) -> dict[str, Any] | None:
    """Load one ``<run>.result.json`` file, or None when missing/invalid."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _basename(entry: Any) -> str:
    return str(entry).rsplit("/", 1)[-1]


def format_typecheck(failures: Any) -> tuple[str, list[str]]:
    """Format the typecheck cell; return ``(display, basenames)``."""

    if failures is None:
        return "ok", []
    items = (
        [_basename(entry) for entry in failures if isinstance(entry, str) and entry]
        if isinstance(failures, list)
        else []
    )
    if not items:
        return "ok", []
    return ",".join(items), items


def format_wall(value: Any) -> tuple[str, float | int | None]:
    """Format a wall-clock value; return ``(display, numeric)``."""

    if isinstance(value, bool):
        return "-", None
    if isinstance(value, int):
        return str(value), value
    if isinstance(value, float):
        return f"{value:g}", value
    return "-", None


def board_cells(result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Derive board-only cells from a ``board_brownfield_result/v1`` dict."""

    if result is None:
        return {
            "wall": "-",
            "wall_value": None,
            "integrated": "-",
            "blocked": "-",
            "fixed": "-",
            "reviews": "-",
            "objected": None,
            "endorsed": None,
            "conflicts": "-",
        }
    wall_display, wall_value = format_wall(result.get("wall_seconds"))
    modules = result.get("modules")
    module_ids = list(modules.keys()) if isinstance(modules, Mapping) else []
    integrated = result.get("integrated_modules")
    integrated_list = list(integrated) if isinstance(integrated, list) else []
    verifications = result.get("verifications")
    failed: set[str] = set()
    passed: set[str] = set()
    if isinstance(verifications, list):
        for index, entry in enumerate(verifications):
            if not isinstance(entry, Mapping):
                continue
            module_id = entry.get("module_id")
            key = str(module_id) if isinstance(module_id, str) else f"#{index}"
            if entry.get("status") == "failed":
                failed.add(key)
            if entry.get("status") == "passed":
                passed.add(key)
    reviews = result.get("reviews")
    objected = 0
    endorsed = 0
    if isinstance(reviews, list):
        for entry in reviews:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("status") == "objected":
                objected += 1
            elif entry.get("status") == "endorsed":
                endorsed += 1
    jobs = result.get("integration_jobs")
    conflicts = 0
    if isinstance(jobs, list):
        for job in jobs:
            if not isinstance(job, Mapping):
                continue
            items = job.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                total = item.get("conflicts_total")
                if isinstance(total, int) and not isinstance(total, bool):
                    conflicts += total
    return {
        "wall": wall_display,
        "wall_value": wall_value,
        "integrated": f"{len(integrated_list)}/{len(module_ids)}",
        "blocked": str(len(failed)),
        "fixed": str(len(failed & passed)),
        "reviews": f"{objected}/{endorsed}",
        "objected": objected,
        "endorsed": endorsed,
        "conflicts": str(conflicts),
    }


def discover_runs(logs_dir: Path) -> dict[str, dict[str, Path]]:
    """Map run name to its files (``score``, ``log``, ``result``)."""

    found: dict[str, dict[str, Path]] = {}
    try:
        entries = sorted(logs_dir.iterdir(), key=lambda item: item.name)
    except OSError:
        return found
    for entry in entries:
        if not entry.is_file():
            continue
        name = entry.name
        if name.endswith(".score.out"):
            run = name[: -len(".score.out")]
            found.setdefault(run, {})["score"] = entry
        elif name.endswith(".log"):
            run = name[: -len(".log")]
            found.setdefault(run, {})["log"] = entry
        elif name.endswith(".result.json"):
            run = name[: -len(".result.json")]
            found.setdefault(run, {})["result"] = entry
    return found


def collect_runs(logs_dir: Path, excludes: Sequence[str]) -> list[dict[str, Any]]:
    """Read every run in ``logs_dir`` into display-ready row dicts."""

    rows: list[dict[str, Any]] = []
    for run, files in discover_runs(logs_dir).items():
        if any(token and token in run for token in excludes):
            continue
        arm, rep = parse_run_name(run)
        text: str | None = None
        for key in ("score", "log"):
            path = files.get(key)
            if path is not None:
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    text = None
                break
        score = find_score(text) if text is not None else None
        result = load_result(files["result"]) if "result" in files else None
        cells = board_cells(result)
        wall = cells["wall"]
        wall_value = cells["wall_value"]
        if result is None and text is not None:
            fallback = find_wall_fallback(text)
            if fallback is not None:
                wall, wall_value = str(fallback), fallback
        if score is None:
            rows.append(
                {
                    "run": run,
                    "arm": arm,
                    "rep": rep,
                    "has_score": False,
                    "resolved": "no score",
                    "resolved_num": None,
                    "resolved_den": None,
                    "f2p": "-",
                    "f2p_num": None,
                    "f2p_den": None,
                    "regressions": "-",
                    "regressions_value": None,
                    "typecheck": "-",
                    "typecheck_fail": [],
                    "wall": wall,
                    "wall_value": wall_value,
                    "integrated": cells["integrated"],
                    "blocked": cells["blocked"],
                    "fixed": cells["fixed"],
                    "reviews": cells["reviews"],
                    "objected": cells["objected"],
                    "endorsed": cells["endorsed"],
                    "conflicts": cells["conflicts"],
                }
            )
            continue
        resolved_raw = score.get("resolved")
        f2p_raw = score.get("f2p")
        resolved_num, resolved_den = parse_fraction(resolved_raw)
        f2p_num, f2p_den = parse_fraction(f2p_raw)
        regressions_raw = score.get("regressions")
        regressions_value = (
            regressions_raw
            if isinstance(regressions_raw, int) and not isinstance(regressions_raw, bool)
            else None
        )
        typecheck_display, typecheck_names = format_typecheck(score.get("typecheck_fail"))
        rows.append(
            {
                "run": run,
                "arm": arm,
                "rep": rep,
                "has_score": True,
                "resolved": str(resolved_raw)
                if isinstance(resolved_raw, str)
                else ("-" if resolved_raw is None else str(resolved_raw)),
                "resolved_num": resolved_num,
                "resolved_den": resolved_den,
                "f2p": str(f2p_raw)
                if isinstance(f2p_raw, str)
                else ("-" if f2p_raw is None else str(f2p_raw)),
                "f2p_num": f2p_num,
                "f2p_den": f2p_den,
                "regressions": str(regressions_value) if regressions_value is not None else "-",
                "regressions_value": regressions_value,
                "typecheck": typecheck_display,
                "typecheck_fail": typecheck_names,
                "wall": wall,
                "wall_value": wall_value,
                "integrated": cells["integrated"],
                "blocked": cells["blocked"],
                "fixed": cells["fixed"],
                "reviews": cells["reviews"],
                "objected": cells["objected"],
                "endorsed": cells["endorsed"],
                "conflicts": cells["conflicts"],
            }
        )
    rows.sort(key=lambda row: (str(row["arm"]), int(row["rep"]), str(row["run"])))
    return rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_arms(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate scored runs per arm; every row states its n."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["arm"]), []).append(row)
    arms: list[dict[str, Any]] = []
    for arm in sorted(grouped):
        scored = [row for row in grouped[arm] if row.get("has_score")]
        resolved = [
            float(row["resolved_num"]) for row in scored if isinstance(row.get("resolved_num"), int)
        ]
        f2p = [float(row["f2p_num"]) for row in scored if isinstance(row.get("f2p_num"), int)]
        regressions = [
            float(row["regressions_value"])
            for row in scored
            if isinstance(row.get("regressions_value"), int)
        ]
        arms.append(
            {
                "arm": arm,
                "n": len(scored),
                "mean_resolved": _mean(resolved),
                "mean_f2p": _mean(f2p),
                "mean_regressions": _mean(regressions),
            }
        )
    return arms


def _fmt_mean(value: Any) -> str:
    return f"{float(value):.1f}" if isinstance(value, (int, float)) else "-"


def render_markdown(rows: Sequence[Mapping[str, Any]], arms: Sequence[Mapping[str, Any]]) -> str:
    """Render the per-run and per-arm tables; every arm row states its n."""

    lines = [
        "# Brownfield run report",
        "",
        "Descriptive small-n summary: every arm row states its n and no significance is claimed.",
        "",
        "| run | resolved | F2P | regressions | typecheck | wall s | integrated | "
        "host blocked | blocked fixed | reviews | conflicts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['resolved']} | {row['f2p']} | "
            f"{row['regressions']} | {row['typecheck']} | {row['wall']} | "
            f"{row['integrated']} | {row['blocked']} | {row['fixed']} | "
            f"{row['reviews']} | {row['conflicts']} |"
        )
    lines.extend(
        [
            "",
            "| arm | n | mean resolved | mean F2P | mean regressions |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for arm in arms:
        lines.append(
            f"| {arm['arm']} | {arm['n']} | {_fmt_mean(arm['mean_resolved'])} | "
            f"{_fmt_mean(arm['mean_f2p'])} | {_fmt_mean(arm['mean_regressions'])} |"
        )
    lines.extend(["", "n = runs with a score.", ""])
    return "\n".join(lines)


def build_payload(
    rows: Sequence[Mapping[str, Any]], arms: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build the ``--json`` payload with the same data as the tables."""

    return {
        "runs": [
            {
                "run": str(row["run"]),
                "arm": str(row["arm"]),
                "rep": int(row["rep"]),
                "has_score": bool(row["has_score"]),
                "resolved": str(row["resolved"]),
                "resolved_num": row["resolved_num"],
                "resolved_den": row["resolved_den"],
                "f2p": str(row["f2p"]),
                "f2p_num": row["f2p_num"],
                "f2p_den": row["f2p_den"],
                "regressions": str(row["regressions"]),
                "regressions_value": row["regressions_value"],
                "typecheck": str(row["typecheck"]),
                "typecheck_fail": list(row["typecheck_fail"]),
                "wall": str(row["wall"]),
                "wall_value": row["wall_value"],
                "integrated": str(row["integrated"]),
                "blocked": str(row["blocked"]),
                "fixed": str(row["fixed"]),
                "reviews": str(row["reviews"]),
                "objected": row["objected"],
                "endorsed": row["endorsed"],
                "conflicts": str(row["conflicts"]),
            }
            for row in rows
        ],
        "arms": [
            {
                "arm": str(arm["arm"]),
                "n": int(arm["n"]),
                "mean_resolved": arm["mean_resolved"],
                "mean_f2p": arm["mean_f2p"],
                "mean_regressions": arm["mean_regressions"],
            }
            for arm in arms
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the report command-line parser."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("logs_dir", type=Path, help="directory of run files")
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
        help="print JSON (keys: runs, arms) instead of Markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the brownfield run report."""

    args = build_parser().parse_args(argv)
    logs_dir = args.logs_dir
    if not logs_dir.is_dir():
        print(f"brownfield_report: logs dir not found: {logs_dir}", file=sys.stderr)
        return 2
    rows = collect_runs(logs_dir, list(args.exclude))
    arms = aggregate_arms(rows)
    if args.json:
        print(json.dumps(build_payload(rows, arms), indent=2, sort_keys=True))
    else:
        print(render_markdown(rows, arms), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
