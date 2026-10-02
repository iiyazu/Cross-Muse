"""Aggregate eval results into the design's README table (design §5).

Reads the per-cell results CSV written by ``run_eval.py`` and, when available, the
``judgments.json`` written by ``judge.py``.  Emits one aggregated table per mode plus
a data-filled takeaway paragraph; per-task detail stays in the CSV.

Usage::

    uv run python scripts/eval/report.py --results eval_out/results.csv \
        --judgments eval_out/judgments.json --out eval_out/README-table.md
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RESULTS_COLUMNS: tuple[str, ...] = (
    "task_id",
    "mode",
    "run",
    "rubric_score",
    "judge_a",
    "judge_b",
    "agree",
    "agent_turns",
    "turns_by_cli",
    "visible_msgs",
    "echo_msgs",
    "pure_ack_msgs",
    "wall_s",
    "max_causal_depth",
    "handoffs",
    "specialist_ok",
    "tokens_est",
    "notes",
)


def read_results(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def effective_scores(row: Mapping[str, Any]) -> list[float]:
    """Judge mean when available (judge_a/judge_b), else the manual rubric_score."""
    judged = [
        score for score in (_num(row.get("judge_a")), _num(row.get("judge_b"))) if score is not None
    ]
    if judged:
        return judged
    manual = _num(row.get("rubric_score"))
    return [manual] if manual is not None else []


def merge_judgments(rows: list[dict[str, Any]], judgments: Mapping[str, Any]) -> int:
    """Fill judge_a/judge_b/agree columns from judgments.json; return match count."""
    index = {
        (str(row.get("task_id")), str(row.get("mode")), str(row.get("run"))): row for row in rows
    }
    matched = 0
    for entry in judgments.get("entries") or []:
        if not isinstance(entry, Mapping) or entry.get("skipped"):
            continue
        key = (str(entry.get("task_id")), str(entry.get("mode")), str(entry.get("run")))
        row = index.get(key)
        if row is None:
            continue
        passes = entry.get("passes") or []
        scores = [
            str(pass_data.get("score")) for pass_data in passes if isinstance(pass_data, Mapping)
        ]
        if scores:
            row["judge_a"] = scores[0]
        if len(scores) > 1:
            row["judge_b"] = scores[1]
        if entry.get("agree") is not None:
            row["agree"] = str(bool(entry["agree"]))
        matched += 1
    return matched


def parse_turns_by_cli(value: Any) -> dict[str, int]:
    """Inverse of the ``kind:count;kind:count`` cell; malformed parts are ignored."""
    counts: dict[str, int] = {}
    for part in str(value or "").split(";"):
        kind, sep, count = part.partition(":")
        if sep and kind.strip() and count.strip().isdigit():
            counts[kind.strip()] = counts.get(kind.strip(), 0) + int(count)
    return counts


def _fmt_turns_by_cli(counts: Mapping[str, int]) -> str:
    if not counts:
        return "—"
    return " · ".join(f"{kind} {counts[kind]}" for kind in sorted(counts))


def aggregate(rows: Sequence[Mapping[str, Any]], modes: Sequence[str]) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for mode in modes:
        mode_rows = [row for row in rows if str(row.get("mode")) == mode]
        scores: list[float] = []
        visible: list[float] = []
        echo_ack: list[float] = []
        wall: list[float] = []
        turns_total = 0
        turns_by_cli: dict[str, int] = {}
        specialist_ok = 0
        specialist_total = 0
        for row in mode_rows:
            scores.extend(effective_scores(row))
            if _num(row.get("visible_msgs")) is not None:
                visible.append(_num(row.get("visible_msgs")) or 0.0)
            echo = _num(row.get("echo_msgs"))
            ack = _num(row.get("pure_ack_msgs"))
            if echo is not None or ack is not None:
                echo_ack.append((echo or 0.0) + (ack or 0.0))
            if _num(row.get("wall_s")) is not None:
                wall.append(_num(row.get("wall_s")) or 0.0)
            if _num(row.get("agent_turns")) is not None:
                turns_total += int(_num(row.get("agent_turns")) or 0)
            for kind, count in parse_turns_by_cli(row.get("turns_by_cli")).items():
                turns_by_cli[kind] = turns_by_cli.get(kind, 0) + count
            if row.get("specialist_ok") not in (None, ""):
                specialist_total += 1
                specialist_ok += int(_truthy(row.get("specialist_ok")))
        ack_values = [
            value for row in mode_rows if (value := _num(row.get("pure_ack_msgs"))) is not None
        ]
        aggregated[mode] = {
            "cells": len(mode_rows),
            "rubric_mean": (sum(scores) / len(scores)) if scores else None,
            "turns_total": turns_total,
            "turns_by_cli": turns_by_cli,
            "visible_mean": (sum(visible) / len(visible)) if visible else None,
            "echo_ack_mean": (sum(echo_ack) / len(echo_ack)) if echo_ack else None,
            "wall_median": statistics.median(wall) if wall else None,
            "specialist_ok": specialist_ok,
            "specialist_total": specialist_total,
            "pure_ack_mean": (sum(ack_values) / len(ack_values)) if ack_values else None,
        }
    return aggregated


def _fmt(value: float | None, *, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}{suffix}"


def render_table(aggregated: Mapping[str, Mapping[str, Any]], modes: Sequence[str]) -> str:
    header = "| | " + " | ".join(modes) + " |"
    divider = "|---" * (len(modes) + 1) + "|"
    rows = [
        ("Rubric mean (0–3)", lambda agg: _fmt(agg.get("rubric_mean"))),
        ("Agent turns (total)", lambda agg: str(agg.get("turns_total") or 0)),
        ("Turns by provider", lambda agg: _fmt_turns_by_cli(agg.get("turns_by_cli") or {})),
        ("Visible messages", lambda agg: _fmt(agg.get("visible_mean"))),
        ("Echo + pure-ack msgs", lambda agg: _fmt(agg.get("echo_ack_mean"))),
        ("Wall time (median)", lambda agg: _fmt(agg.get("wall_median"), suffix=" s")),
        (
            "Right specialist answered",
            lambda agg: (
                f"{agg.get('specialist_ok', 0)}/{agg.get('specialist_total', 0)}"
                if agg.get("specialist_total")
                else "—"
            ),
        ),
    ]
    lines = [header, divider]
    for label, value in rows:
        cells = [str(value(aggregated.get(mode) or {})) for mode in modes]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def task_means(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    """Mean judged score per (task_id, mode); unjudged cells are omitted."""

    scores: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        scores.setdefault((str(row.get("task_id")), str(row.get("mode"))), []).extend(
            effective_scores(row)
        )
    return {key: sum(values) / len(values) for key, values in scores.items() if values}


def _critique_delta(rows: Sequence[Mapping[str, Any]]) -> tuple[str, bool]:
    """State the measured open-critique (T1/T7) scores; never infer a cause."""

    means = task_means(rows)
    parts = []
    broadcast_wins = False
    for task_id in ("T1", "T7"):
        broadcast = means.get((task_id, "broadcast"))
        addressed = means.get((task_id, "addressed"))
        if broadcast is None or addressed is None:
            continue
        parts.append(f"{task_id} {broadcast:.1f} vs {addressed:.1f}")
        broadcast_wins = broadcast_wins or broadcast > addressed
    if not parts:
        return "open-critique (T1/T7) comparison unavailable in this run", False
    return (
        "open-critique tasks scored broadcast vs addressed " + ", ".join(parts),
        broadcast_wins,
    )


def render_task_table(rows: Sequence[Mapping[str, Any]], modes: Sequence[str]) -> str:
    means = task_means(rows)
    task_ids = sorted({str(row.get("task_id")) for row in rows})
    lines = ["| Task | " + " | ".join(modes) + " |", "|---" * (len(modes) + 1) + "|"]
    for task_id in task_ids:
        cells = [_fmt(means.get((task_id, mode))) for mode in modes]
        lines.append(f"| {task_id} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_takeaway(
    aggregated: Mapping[str, Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    modes: Sequence[str],
) -> str:
    if "broadcast" not in modes or "addressed" not in modes:
        return (
            "*Takeaway (single mode present):* run both `--modes broadcast,addressed` to "
            "produce the designed comparison."
        )
    broadcast = aggregated.get("broadcast") or {}
    addressed = aggregated.get("addressed") or {}
    b_mean = broadcast.get("rubric_mean")
    a_mean = addressed.get("rubric_mean")
    b_turns = broadcast.get("turns_total") or 0
    a_turns = addressed.get("turns_total") or 0
    b_ack = broadcast.get("pure_ack_mean")
    a_ack = addressed.get("pure_ack_mean")
    if b_turns and a_turns and a_turns <= b_turns:
        turn_phrase = f"using ~{round((1 - a_turns / b_turns) * 100)}% fewer agent turns"
    elif b_turns and a_turns:
        turn_phrase = f"using ~{round((a_turns / b_turns - 1) * 100)}% more agent turns"
    else:
        turn_phrase = "with insufficient turn data"
    if b_ack is not None and a_ack is not None:
        if a_ack < b_ack:
            ack_phrase = f"cutting pure-ack noise from {b_ack:.1f} to {a_ack:.1f} messages per task"
        elif a_ack == b_ack:
            ack_phrase = f"pure-ack noise was {a_ack:.1f} messages per task in both modes"
        else:
            ack_phrase = f"pure-ack noise went from {b_ack:.1f} to {a_ack:.1f} messages per task"
    else:
        ack_phrase = "pure-ack noise not measured in this run"
    if b_mean is None or a_mean is None:
        score_phrase = "rubric scores are not judged yet"
    elif abs(b_mean - a_mean) <= 0.25:
        score_phrase = (
            f"addressed scored within 0.25 of broadcast ({_fmt(b_mean)} vs {_fmt(a_mean)})"
        )
    else:
        direction = "below" if a_mean < b_mean else "above"
        score_phrase = (
            f"addressed scored {abs(b_mean - a_mean):.1f} {direction} broadcast "
            f"({_fmt(b_mean)} vs {_fmt(a_mean)})"
        )
    critique_phrase, _ = _critique_delta(rows)
    return (
        f"*Measured (same prompts, same roster):* {score_phrase}, {turn_phrase}, and "
        f"{ack_phrase}; {critique_phrase}. Small samples: read per-task rows before "
        f"drawing conclusions."
    )


def build_markdown(
    rows: Sequence[Mapping[str, Any]], judgments: Mapping[str, Any] | None, modes: Sequence[str]
) -> str:
    aggregated = aggregate(rows, modes)
    sections = [
        "## Broadcast vs. addressed Room evaluation",
        "",
        f"Aggregated per mode over {len(rows)} cells; per-task detail in `results.csv`.",
        "",
        "| | " + " | ".join(modes) + " |",
        "|---" * (len(modes) + 1) + "|",
    ]
    table = render_table(aggregated, modes).split("\n")
    sections.extend(table[2:])
    sections.extend(["", "Judged rubric mean per task:", "", render_task_table(rows, modes)])
    sections.append("")
    sections.append(render_takeaway(aggregated, rows, modes))
    if judgments:
        agreement = judgments.get("agreement")
        kappa = judgments.get("cohen_kappa")
        if agreement is not None:
            kappa_text = f"{kappa:.3f}" if isinstance(kappa, (int, float)) else "n/a"
            sections.extend(
                [
                    "",
                    f"Judging: two-pass agreement {agreement:.0%}, Cohen's kappa {kappa_text}.",
                ]
            )
    return "\n".join(sections) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--results", type=Path, required=True, help="results.csv path")
    parser.add_argument(
        "--judgments",
        type=Path,
        default=None,
        help="judgments.json path (default: sibling of --results)",
    )
    parser.add_argument("--out", type=Path, default=None, help="markdown output path")
    parser.add_argument("--modes", default="broadcast,addressed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    rows: list[dict[str, Any]] = [dict(row) for row in read_results(args.results)]
    judgments_path = args.judgments or args.results.parent / "judgments.json"
    judgments: Mapping[str, Any] | None = None
    if judgments_path.exists():
        loaded = json.loads(judgments_path.read_text(encoding="utf-8"))
        if isinstance(loaded, Mapping):
            judgments = loaded
            merge_judgments(rows, judgments)
    markdown = build_markdown(rows, judgments, modes)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
