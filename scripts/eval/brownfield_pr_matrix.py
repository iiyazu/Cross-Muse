"""Per-PR pass matrix for brownfield evaluation runs.

Reads one directory of run outputs and prints one Markdown table showing,
per upstream change request (PR), in how many runs it was resolved. Only
reads files; it never runs an evaluation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_PR_LINE_RE = re.compile(r"#(\d+):\s*f2p\s+(\d+)/(\d+)\s+p2p\s+(\d+)/(\d+)\s*(RESOLVED)?\s*$")
_RUN_SUFFIX_RE = re.compile(r"-(?P<arm>[A-Za-z]+)-r(?P<rep>\d+)$")


@dataclass(frozen=True)
class PrResult:
    """One PR's first result line inside a single run."""

    resolved: bool
    f2p: tuple[int, int]
    p2p: tuple[int, int]


def parse_pr_line(line: str) -> tuple[int, PrResult] | None:
    """Parse one text line into ``(pr_number, PrResult)`` or None.

    A PR is resolved exactly when the stripped line ends with ``RESOLVED``.
    """

    stripped = line.strip()
    match = _PR_LINE_RE.match(stripped)
    if match is None:
        return None
    # ``RESOLVED`` only counts at the very end (modulo trailing spaces,
    # which ``strip`` already removed).
    resolved = stripped.endswith("RESOLVED")
    pr = int(match.group(1))
    f2p = (int(match.group(2)), int(match.group(3)))
    p2p = (int(match.group(4)), int(match.group(5)))
    return pr, PrResult(resolved=resolved, f2p=f2p, p2p=p2p)


def parse_run_file(path: Path) -> dict[int, PrResult]:
    """Parse one run output file; the first line per PR wins."""

    results: dict[int, PrResult] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return results
    for line in text.splitlines():
        parsed = parse_pr_line(line)
        if parsed is None:
            continue
        pr, result = parsed
        if pr not in results:
            results[pr] = result
    return results


def run_sort_key(name: str) -> tuple[int, str, int, str]:
    """Sort runs by ARM then REP; unparsable names sort last by name."""

    match = _RUN_SUFFIX_RE.search(name)
    if match is None:
        return (1, name, 0, name)
    return (0, str(match.group("arm")), int(match.group("rep")), name)


def discover_run_files(logs_dir: Path) -> dict[str, Path]:
    """Map run name to its output file, preferring ``.score.out`` over ``.log``."""

    runs: dict[str, Path] = {}
    try:
        entries = sorted(logs_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return runs
    for entry in entries:
        if not entry.is_file():
            continue
        name = entry.name
        run: str | None = None
        prefer = False
        if name.endswith(".score.out"):
            run = name[: -len(".score.out")]
            prefer = True
        elif name.endswith(".log"):
            run = name[: -len(".log")]
            prefer = False
        else:
            continue
        if not run:
            continue
        existing = runs.get(run)
        if existing is None:
            runs[run] = entry
        elif prefer and existing.name.endswith(".log"):
            runs[run] = entry
    return runs


def collect_runs(
    logs_dir: Path, exclude: Sequence[str]
) -> tuple[list[str], dict[str, dict[int, PrResult]], list[str]]:
    """Return ``(runs, data, skipped)`` for the included runs.

    ``runs`` holds non-skipped run names sorted by ARM then REP; ``data``
    maps each such run to its PR results; ``skipped`` holds sorted names of
    runs with no PR lines.
    """

    files = discover_run_files(logs_dir)
    names = [run for run in files if not any(sub in run for sub in exclude if sub)]
    data: dict[str, dict[int, PrResult]] = {}
    skipped: list[str] = []
    for run in names:
        results = parse_run_file(files[run])
        if not results:
            skipped.append(run)
        else:
            data[run] = results
    runs = sorted(data, key=run_sort_key)
    skipped.sort(key=run_sort_key)
    return runs, data, skipped


def format_cell(result: PrResult | None) -> str:
    """Format one matrix cell: ``R``, ``a/b``, ``a/b pc/d``, or ``-``."""

    if result is None:
        return "-"
    if result.resolved:
        return "R"
    cell = f"{result.f2p[0]}/{result.f2p[1]}"
    if result.p2p[0] != result.p2p[1]:
        cell += f" p{result.p2p[0]}/{result.p2p[1]}"
    return cell


def ordered_prs(data: dict[str, dict[int, PrResult]]) -> list[int]:
    """Return PR numbers sorted by resolved count ascending, then PR number."""

    counts: dict[int, int] = {}
    totals: dict[int, int] = {}
    for results in data.values():
        for pr, result in results.items():
            totals[pr] = totals.get(pr, 0) + 1
            if result.resolved:
                counts[pr] = counts.get(pr, 0) + 1
    for pr in totals:
        counts.setdefault(pr, 0)
    return sorted(counts, key=lambda pr: (counts[pr], pr))


def resolved_counts(data: dict[str, dict[int, PrResult]]) -> dict[int, tuple[int, int]]:
    """Map PR to ``(resolved_runs, runs_where_present)``."""

    counts: dict[int, tuple[int, int]] = {}
    totals: dict[int, int] = {}
    resolved: dict[int, int] = {}
    for results in data.values():
        for pr, result in results.items():
            totals[pr] = totals.get(pr, 0) + 1
            if result.resolved:
                resolved[pr] = resolved.get(pr, 0) + 1
    for pr, total in totals.items():
        counts[pr] = (resolved.get(pr, 0), total)
    return counts


def render_markdown(
    runs: Sequence[str],
    data: dict[str, dict[int, PrResult]],
    skipped: Sequence[str],
) -> str:
    """Render the one Markdown table plus skipped/never-resolved lines."""

    counts = resolved_counts(data)
    prs = ordered_prs(data)
    if runs:
        header_line = "| " + " | ".join(["PR", "resolved", *runs]) + " |"
    else:
        header_line = "| PR | resolved |"
    separator = "| " + " | ".join(["---"] * (2 + len(runs))) + " |"
    lines = [header_line, separator]
    for pr in prs:
        resolved, total = counts[pr]
        row = [f"#{pr}", f"{resolved}/{total}"]
        for run in runs:
            row.append(format_cell(data[run].get(pr)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    if skipped:
        lines.append("Skipped: " + ", ".join(skipped))
    never = [pr for pr in prs if counts[pr][0] == 0]
    if never:
        lines.append("Never resolved: " + ", ".join(f"#{pr}" for pr in never))
    else:
        lines.append("Never resolved: none")
    lines.append("")
    return "\n".join(lines)


def build_json_payload(
    runs: Sequence[str],
    data: dict[str, dict[int, PrResult]],
    skipped: Sequence[str],
) -> dict[str, object]:
    """Build the ``--json`` payload dict."""

    prs: dict[str, dict[str, dict[str, object]]] = {}
    for pr in sorted({pr for results in data.values() for pr in results}):
        per_run: dict[str, dict[str, object]] = {}
        for run in runs:
            result = data[run].get(pr)
            if result is None:
                continue
            per_run[run] = {
                "resolved": result.resolved,
                "f2p": [result.f2p[0], result.f2p[1]],
                "p2p": [result.p2p[0], result.p2p[1]],
            }
        prs[str(pr)] = per_run
    return {"runs": list(runs), "prs": prs, "skipped": list(skipped)}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(
        prog="brownfield_pr_matrix",
        description="Per-PR pass matrix for brownfield evaluation runs.",
    )
    parser.add_argument("logs_dir", help="directory of run outputs")
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
        help="print JSON instead of Markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: read run outputs and print the matrix."""

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    logs_dir = Path(str(args.logs_dir))
    if not logs_dir.is_dir():
        print(f"brownfield_pr_matrix: logs dir not found: {logs_dir}", flush=True)
        return 2
    exclude: list[str] = list(args.exclude or [])
    runs, data, skipped = collect_runs(logs_dir, exclude)
    if bool(args.json):
        payload = build_json_payload(runs, data, skipped)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(render_markdown(runs, data, skipped), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
