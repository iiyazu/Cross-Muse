"""In-repo board reliability evaluation (``xmuse-eval board``).

Runs selected ``scripts/board_owners_smoke.py`` scenarios ``--repeat N``
times, each as a sequential subprocess with ``--result`` and a per-run
timeout, then aggregates one Markdown table from the same
``room_board_projection`` derivation the UI uses (per-module §6 counters in
each result file).  A failed or timed-out run is recorded, never fatal.
``--from-results <dir>`` re-aggregates existing result files without
running anything.  No significance is ever claimed: every cell states n.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPORT_SCHEMA_VERSION = "board_eval_report/v1"
EVAL_SCENARIOS: tuple[str, ...] = ("revision", "verify", "false-done", "review", "integration")
DEFAULT_REPEAT = 3
DEFAULT_RUN_TIMEOUT_S = 7200.0
SMOKE_SCRIPT = Path(__file__).resolve().parents[1] / "board_owners_smoke.py"


def build_parser() -> argparse.ArgumentParser:
    """Build the ``xmuse-eval`` parser with its ``board`` subcommand."""

    parser = argparse.ArgumentParser(
        prog="xmuse-eval",
        description="In-repo reliability evaluation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    board = sub.add_parser("board", help="run board smoke scenarios and aggregate one table")
    board.description = __doc__
    board.add_argument(
        "--scenarios",
        default=",".join(EVAL_SCENARIOS),
        help="comma-separated subset of: " + ",".join(EVAL_SCENARIOS),
    )
    board.add_argument("--repeat", type=int, default=DEFAULT_REPEAT)
    board.add_argument("--out", required=True, help="output directory for the report")
    board.add_argument(
        "--run-timeout-s",
        type=float,
        default=DEFAULT_RUN_TIMEOUT_S,
        help="per-run subprocess timeout in seconds",
    )
    board.add_argument(
        "--frontend-cli",
        choices=["opencode", "claude", "antigravity"],
        default="opencode",
        help="owner frontend for every run (review auto-switches, see below)",
    )
    board.add_argument(
        "--from-results",
        default=None,
        help="re-aggregate existing smoke result files without running anything",
    )
    return parser


def selected_scenarios(raw: str) -> list[str]:
    """Split and validate the ``--scenarios`` value, preserving order."""

    names = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in names if item not in EVAL_SCENARIOS]
    if not names or unknown:
        raise ValueError(f"unknown scenarios {unknown}; expected a subset of {EVAL_SCENARIOS}")
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def frontend_cli_for_run(scenario: str, requested: str) -> tuple[str, bool]:
    """Return the frontend CLI for one run plus whether it was auto-switched.

    The ``review`` scenario needs two model families for the cross-family
    rule; with the default ``opencode`` frontend both owners would share one
    family and the run could never endorse.  Auto-switching to ``claude`` is
    recorded on the run so the report stays honest about provider kinds.
    """

    if scenario == "review" and requested == "opencode":
        return "claude", True
    return requested, False


def _str_values(raw: Any) -> list[str]:
    if isinstance(raw, Mapping):
        return sorted({str(value) for value in raw.values() if isinstance(value, str)})
    if isinstance(raw, list):
        return sorted({str(value) for value in raw if isinstance(value, str)})
    return []


def summarize_modules(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate one run's per-module projection snapshot (§6 counters)."""

    raw = summary.get("modules")
    modules = raw if isinstance(raw, Mapping) else {}
    claims = 0
    verified = 0
    rework: list[int] = []
    endorsed = 0
    objected = 0
    conflicts = 0
    fix_rounds: list[int] = []

    def _int(value: Any) -> int:
        return int(value) if isinstance(value, bool) is False and isinstance(value, int) else 0

    for _module_id, info in modules.items():
        if not isinstance(info, Mapping):
            continue
        counters = info.get("counters")
        counts = counters if isinstance(counters, Mapping) else {}
        claims += _int(counts.get("done_reports"))
        if info.get("state") == "verified":
            verified += 1
        rework.append(_int(counts.get("rework_rounds")))
        endorsed += _int(counts.get("reviews_endorsed"))
        objected += _int(counts.get("reviews_objected"))
        conflicts += _int(counts.get("integrations_conflicted"))
        fix_rounds.append(_int(counts.get("conflict_fix_rounds")))
    return {
        "modules": len([item for item in modules.values() if isinstance(item, Mapping)]),
        "claims": claims,
        "verified": verified,
        "rework": rework,
        "endorsed": endorsed,
        "objected": objected,
        "conflicts": conflicts,
        "fix_rounds": fix_rounds,
    }


def _mean(values: list[int]) -> float | None:
    return float(statistics.fmean(values)) if values else None


def aggregate_group(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate run records (each with ``summary`` or ``None``) into stats."""

    records = list(records)
    ok = sum(1 for item in records if item.get("status") == "ok")
    claims = 0
    verified = 0
    rework: list[int] = []
    endorsed = 0
    objected = 0
    conflicts = 0
    fix_rounds: list[int] = []
    walls: list[float] = []
    models: set[str] = set()
    provider_kinds: set[str] = set()
    for item in records:
        wall = item.get("wall_s")
        if isinstance(wall, (int, float)):
            walls.append(float(wall))
        summary = item.get("summary")
        if not isinstance(summary, Mapping):
            continue
        module_stats = summarize_modules(summary)
        claims += int(module_stats["claims"])
        verified += int(module_stats["verified"])
        rework.extend(int(value) for value in module_stats["rework"])
        endorsed += int(module_stats["endorsed"])
        objected += int(module_stats["objected"])
        conflicts += int(module_stats["conflicts"])
        fix_rounds.extend(int(value) for value in module_stats["fix_rounds"])
        models.update(_str_values(summary.get("models")))
        provider_kinds.update(_str_values(summary.get("provider_kinds")))
    return {
        "runs": len(records),
        "ok": ok,
        "ok_rate": (ok / len(records)) if records else None,
        "claims": claims,
        "verified": verified,
        "claimed_verified_ratio": (verified / claims) if claims else None,
        "false_done_intercepted": sum(rework),
        "mean_rework_rounds": _mean(rework),
        "rework_n": len(rework),
        "reviews_endorsed": endorsed,
        "reviews_objected": objected,
        "review_catches": objected,
        "integration_conflicts": conflicts,
        "mean_conflict_fix_rounds": _mean(fix_rounds),
        "conflict_fix_n": len(fix_rounds),
        "wall_s": {
            "median": (float(statistics.median(walls)) if walls else None),
            "min": (min(walls) if walls else None),
            "max": (max(walls) if walls else None),
            "n": len(walls),
        },
        "models": sorted(models),
        "provider_kinds": sorted(provider_kinds),
    }


def build_report(
    *,
    records: Sequence[Mapping[str, Any]],
    scenarios: Sequence[str],
    repeat: int | None,
) -> dict[str, Any]:
    """Build the ``board_eval_report/v1`` dict from run records."""

    ordered = list(records)
    per_scenario = {
        name: aggregate_group([item for item in ordered if item.get("scenario") == name])
        for name in scenarios
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scenarios": list(scenarios),
        "repeat": repeat,
        "per_scenario": per_scenario,
        "overall": aggregate_group(ordered),
        "runs": [
            {
                "scenario": str(item.get("scenario")),
                "index": int(item.get("index", 0)),
                "status": str(item.get("status")),
                "ok": bool(item.get("status") == "ok"),
                "wall_s": item.get("wall_s"),
                "result_file": item.get("result_file"),
                "frontend_cli": item.get("frontend_cli"),
                "frontend_cli_auto": bool(item.get("frontend_cli_auto")),
            }
            for item in ordered
        ],
    }


def _fmt_ratio(value: Any, n: int) -> str:
    if value is None:
        return f"n/a (n={n})"
    return f"{value:.2f} (n={n})"


def _fmt_mean(value: Any, n: int) -> str:
    if value is None:
        return f"n/a (n={n})"
    return f"{value:.2f} (n={n})"


def render_markdown_table(report: Mapping[str, Any]) -> str:
    """Render the one evaluation table; every metric cell states its n."""

    raw_scenarios = report.get("scenarios")
    scenarios = list(raw_scenarios) if isinstance(raw_scenarios, list) else []
    raw_groups = report.get("per_scenario")
    groups = raw_groups if isinstance(raw_groups, Mapping) else {}
    raw_overall = report.get("overall")
    overall = raw_overall if isinstance(raw_overall, Mapping) else {}

    def _row(name: str, stats: Mapping[str, Any]) -> str:
        runs = int(stats.get("runs", 0))
        ok = int(stats.get("ok", 0))
        wall = stats.get("wall_s")
        wall_map = wall if isinstance(wall, Mapping) else {}
        wall_n = int(wall_map.get("n", 0))
        wall_text = (
            f"{wall_map.get('median')}s"
            f" [{wall_map.get('min')}s-{wall_map.get('max')}s] (n={wall_n})"
            if wall_map.get("median") is not None
            else f"n/a (n={wall_n})"
        )
        models = stats.get("models")
        kinds = stats.get("provider_kinds")
        mean_fix = _fmt_mean(
            stats.get("mean_conflict_fix_rounds"), int(stats.get("conflict_fix_n", 0))
        )
        return (
            f"| {name} | {runs} | {ok}/{runs} (n={runs}) | "
            f"{stats.get('claims')} (n={runs}) | "
            f"{stats.get('verified')} (n={runs}) | "
            f"{_fmt_ratio(stats.get('claimed_verified_ratio'), runs)} | "
            f"{stats.get('false_done_intercepted')} (n={runs}) | "
            f"{_fmt_mean(stats.get('mean_rework_rounds'), int(stats.get('rework_n', 0)))} | "
            f"{stats.get('reviews_endorsed')} (n={runs}) | "
            f"{stats.get('reviews_objected')} (n={runs}) | "
            f"{stats.get('integration_conflicts')} (n={runs}) | "
            f"{mean_fix} | "
            f"{wall_text} | "
            f"{', '.join(str(item) for item in models) if isinstance(models, list) else ''} | "
            f"{', '.join(str(item) for item in kinds) if isinstance(kinds, list) else ''} |"
        )

    ok_rate_note = (
        "ok rate"
        if not scenarios
        else "ok rate = runs ok / runs; "
        "claimed→verified = modules verified / done claims; "
        "false done intercepted = Σ rework_rounds; "
        "review catches = objected; "
        "wall = median [min-max] seconds"
    )
    lines = [
        "# Board reliability evaluation",
        "",
        f"Report `{REPORT_SCHEMA_VERSION}`. Descriptive small-n summary: "
        "every cell states its n and no significance is claimed.",
        "",
        f"Runs: {len(report.get('runs', [])) if isinstance(report.get('runs'), list) else 0}; "
        f"repeat: {report.get('repeat')}; created: {report.get('created_at')}.",
        "",
        "| scenario | runs | ok (n) | done claims (n) | verified (n) | "
        "claimed→verified (n) | false done intercepted (n) | mean rework (n) | "
        "endorsed (n) | objected = catches (n) | conflicts (n) | "
        "mean fix rounds (n) | wall median [range] (n) | models | provider kinds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- |",
    ]
    for name in scenarios:
        stats = groups.get(name)
        if isinstance(stats, Mapping):
            lines.append(_row(name, stats))
    if isinstance(overall, Mapping) and overall:
        lines.append(_row("overall", overall))
    lines.extend(["", ok_rate_note + ".", ""])
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md`` into ``out_dir``."""

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown_table(report), encoding="utf-8")
    return json_path, md_path


def load_result_file(path: Path) -> dict[str, Any] | None:
    """Load one smoke ``--result`` file, or None when it is missing/invalid."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def run_smoke_once(
    *,
    scenario: str,
    index: int,
    result_path: Path,
    frontend_cli: str,
    timeout_s: float,
    log_path: Path,
) -> dict[str, Any]:
    """Run one smoke subprocess; failed or timed-out runs are recorded."""

    started = time.monotonic()
    cmd = [
        sys.executable,
        str(SMOKE_SCRIPT),
        "--scenario",
        scenario,
        "--frontend-cli",
        frontend_cli,
        "--result",
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        wall_s = time.monotonic() - started
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ {' '.join(cmd)}\nreturncode={completed.returncode}\n"
            f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n",
            encoding="utf-8",
        )
        summary = load_result_file(result_path)
        if completed.returncode == 0 and isinstance(summary, dict) and summary.get("ok"):
            status = "ok"
        else:
            status = "failed"
        return {
            "scenario": scenario,
            "index": index,
            "status": status,
            "wall_s": wall_s,
            "summary": summary,
            "result_file": result_path.name,
            "frontend_cli": frontend_cli,
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        wall_s = time.monotonic() - started
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = exc.stdout
        stderr = exc.stderr
        log_path.write_text(
            f"$ {' '.join(cmd)}\nTIMEOUT after {timeout_s}s\n"
            f"--- stdout ---\n{stdout if isinstance(stdout, str) else ''}\n"
            f"--- stderr ---\n{stderr if isinstance(stderr, str) else ''}\n",
            encoding="utf-8",
        )
        return {
            "scenario": scenario,
            "index": index,
            "status": "timeout",
            "wall_s": wall_s,
            "summary": load_result_file(result_path),
            "result_file": result_path.name,
            "frontend_cli": frontend_cli,
            "returncode": None,
        }


def collect_from_results(results_dir: Path) -> list[dict[str, Any]]:
    """Build run records from existing ``--result`` files (no subprocesses)."""

    records: list[dict[str, Any]] = []
    paths = sorted(item for item in results_dir.glob("*.json") if item.is_file())
    for index, path in enumerate(paths):
        summary = load_result_file(path)
        scenario = (
            str(summary.get("scenario"))
            if isinstance(summary, Mapping) and isinstance(summary.get("scenario"), str)
            else path.stem.split("-")[0]
        )
        wall = summary.get("wall_seconds") if isinstance(summary, Mapping) else None
        records.append(
            {
                "scenario": scenario,
                "index": index,
                "status": (
                    "ok" if isinstance(summary, Mapping) and summary.get("ok") else "failed"
                ),
                "wall_s": float(wall) if isinstance(wall, (int, float)) else None,
                "summary": summary,
                "result_file": path.name,
                "frontend_cli": None,
            }
        )
    return records


def run_board(args: argparse.Namespace) -> int:
    """Run the ``board`` subcommand from parsed arguments."""

    try:
        scenarios = selected_scenarios(args.scenarios)
    except ValueError as exc:
        print(f"xmuse-eval board: {exc}", flush=True)
        return 2
    if args.repeat < 1:
        print("xmuse-eval board: --repeat must be >= 1", flush=True)
        return 2
    out_dir = Path(args.out)
    if args.from_results is not None:
        results_dir = Path(args.from_results)
        if not results_dir.is_dir():
            print(f"xmuse-eval board: results dir not found: {results_dir}", flush=True)
            return 2
        records = collect_from_results(results_dir)
        report = build_report(records=records, scenarios=scenarios, repeat=None)
        json_path, md_path = write_report(report, out_dir)
        print(f"xmuse-eval board: re-aggregated {len(records)} files -> {json_path}, {md_path}")
        return 0
    runs_dir = out_dir / "runs"
    logs_dir = out_dir / "logs"
    records = []
    for scenario in scenarios:
        cli, auto = frontend_cli_for_run(scenario, args.frontend_cli)
        if auto:
            print(
                "xmuse-eval board: review needs two model families; "
                f"using --frontend-cli claude for review runs (requested {args.frontend_cli})"
            )
        for index in range(args.repeat):
            result_path = runs_dir / f"{scenario}-{index}.json"
            log_path = logs_dir / f"{scenario}-{index}.log"
            print(f"xmuse-eval board: run {scenario} {index + 1}/{args.repeat} ...", flush=True)
            record = run_smoke_once(
                scenario=scenario,
                index=index,
                result_path=result_path,
                frontend_cli=cli,
                timeout_s=args.run_timeout_s,
                log_path=log_path,
            )
            record["frontend_cli_auto"] = auto
            records.append(record)
            print(
                f"xmuse-eval board: {scenario} run {index}: "
                f"{record['status']} ({float(record['wall_s']):.1f}s)",
                flush=True,
            )
    report = build_report(records=records, scenarios=scenarios, repeat=args.repeat)
    json_path, md_path = write_report(report, out_dir)
    print(f"xmuse-eval board: report -> {json_path}, {md_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``xmuse-eval`` console script."""

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "board":
        return run_board(args)
    raise AssertionError(f"unknown xmuse-eval subcommand {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
