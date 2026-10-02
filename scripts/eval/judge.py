"""Blinded rubric judging for eval transcripts (design §3.4).

Two backends, no API keys anywhere in this repository:

- ``--judge manual`` writes ``judging_sheet.md`` (full blinded prompt per transcript)
  and ``judging_sheet.csv`` (fill-in columns) for a human judge.
- ``--judge command --judge-cmd "<cmd>"`` pipes the identical prompt to an external
  command's stdin and parses strict JSON from stdout, twice per transcript by
  default, so a cheap model CLI can be plugged in later.

Blinding rules: participant display names are replaced with seeded random letters
A/B/C..., ``collaboration.mode``, room title, conversation id, and the addressed-mode
mention prefix never enter the rendered text, and the human root mentions are stripped.
The letter assignment is shuffled per transcript with ``Random(f"{seed}:{transcript_id}")``
so identity is not positionally predictable across transcripts.

Usage::

    uv run python scripts/eval/judge.py --transcripts eval_out/transcripts --judge manual
    uv run python scripts/eval/judge.py --transcripts eval_out/transcripts \
        --judge command --judge-cmd "my-cheap-judge-cli --temperature 0"
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval import tasks

JUDGMENTS_SCHEMA_VERSION = "eval_judgments/v1"
LETTERS = "ABCDEFGH"
PARTICIPANT_MENTION_RE = re.compile(r"@participant:[A-Za-z0-9_:-]+")


class JudgeOutputError(ValueError):
    """The judge backend did not return valid strict JSON."""


@dataclass(frozen=True)
class BlindedTranscript:
    transcript_id: str
    task_id: str
    letters: dict[str, str]  # participant_id -> letter
    rendered: str

    def to_json(self) -> dict[str, Any]:
        return {
            "transcript_id": self.transcript_id,
            "task_id": self.task_id,
            "letters": dict(self.letters),
        }


def _projection_participants(transcript: Mapping[str, Any]) -> list[dict[str, Any]]:
    projection = transcript.get("projection")
    values: Any = projection.get("participants") if isinstance(projection, Mapping) else None
    if not isinstance(values, list):
        values = transcript.get("roster_observed")
    if not isinstance(values, list):
        return []
    return [dict(value) for value in values if isinstance(value, Mapping)]


def letter_mapping(transcript: Mapping[str, Any], seed: int) -> dict[str, str]:
    """Seeded random letter per participant id (stable for the same seed)."""
    transcript_id = str(transcript.get("transcript_id") or "transcript")
    identifiers = sorted(
        {
            str(participant.get("participant_id"))
            for participant in _projection_participants(transcript)
            if participant.get("participant_id")
        }
    )
    order = list(identifiers)
    random.Random(f"{seed}:{transcript_id}:letters").shuffle(order)
    return {participant_id: LETTERS[index] for index, participant_id in enumerate(order)}


def _handle_map(transcript: Mapping[str, Any], letters: Mapping[str, str]) -> dict[str, str]:
    """Literal mention handles (and ``@role`` / ``@display_name`` forms) -> letter."""
    handles: dict[str, str] = {}
    for participant in _projection_participants(transcript):
        letter = letters.get(str(participant.get("participant_id") or ""))
        if letter is None:
            continue
        for key in ("mention_handle", "role", "display_name"):
            value = participant.get(key)
            if isinstance(value, str) and value.strip():
                handles[f"@{value}"] = letter
    return handles


def _name_map(transcript: Mapping[str, Any], letters: Mapping[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for participant in _projection_participants(transcript):
        letter = letters.get(str(participant.get("participant_id") or ""))
        if letter is None:
            continue
        # Bare role words ("research", "architect") are ordinary prose; only the
        # display name is an identity reference.  Roles stay blinded as @handles.
        value = participant.get("display_name")
        if isinstance(value, str) and value.strip():
            names[value] = letter
    return names


def _sanitize(
    text: str,
    handles: Mapping[str, str],
    names: Mapping[str, str],
) -> str:
    # Whole-token matches only: a substring replace turned "architecturally" into
    # "Agent Burally" and the judge then penalized the agents for the garbling.
    for handle in sorted(handles, key=len, reverse=True):
        text = re.sub(rf"{re.escape(handle)}(?![\w-])", f"Agent {handles[handle]}", text)
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<![\w@-]){re.escape(name)}(?![\w-])", f"Agent {names[name]}", text)
    return PARTICIPANT_MENTION_RE.sub("[participant]", text)


def blind_transcript(transcript: Mapping[str, Any], *, seed: int = 0) -> BlindedTranscript:
    letters = letter_mapping(transcript, seed)
    handles = _handle_map(transcript, letters)
    names = _name_map(transcript, letters)
    projection = transcript.get("projection")
    items: list[dict[str, Any]] = []
    if isinstance(projection, Mapping) and isinstance(projection.get("timeline_items"), list):
        items = [dict(item) for item in projection["timeline_items"] if isinstance(item, Mapping)]
    items.sort(key=lambda item: int(item.get("room_seq") or 0))
    name_to_letter = {
        str(participant.get("display_name") or ""): letters[str(participant.get("participant_id"))]
        for participant in _projection_participants(transcript)
        if participant.get("participant_id") in letters
    }

    mention_prefix = transcript.get("mention_prefix")
    lines: list[str] = []
    for item in items:
        actor_value = item.get("actor")
        actor: Mapping[str, Any] = actor_value if isinstance(actor_value, Mapping) else {}
        content = str(item.get("content") or "")
        if actor.get("kind") == "human":
            if isinstance(mention_prefix, str) and content.startswith(mention_prefix):
                content = content[len(mention_prefix) :].lstrip()
            lines.append(f"Human:\n{_sanitize(content, handles, names)}")
            continue
        letter = letters.get(str(actor.get("participant_id") or ""), "?")
        label = f"Agent {letter}"
        kind = item.get("kind")
        if kind == "handoff":
            targets = [
                f"Agent {name_to_letter[target]}" if target in name_to_letter else "[participant]"
                for target in item.get("handoff_targets") or []
            ]
            label += " (handoff" + (f" -> {', '.join(targets)}" if targets else "") + ")"
        elif kind == "proposal":
            label += " (proposal)"
        lines.append(f"{label}:\n{_sanitize(content, handles, names)}")

    rendered = "\n\n".join(lines) if lines else "(no durable messages)"
    return BlindedTranscript(
        transcript_id=str(transcript.get("transcript_id") or "transcript"),
        task_id=str(transcript.get("task_id") or ""),
        letters=letters,
        rendered=rendered,
    )


def build_judge_prompt(task: tasks.EvalTask, blinded: BlindedTranscript) -> str:
    checklist = "\n".join(f"- {item}" for item in task.must_hit)
    anchors = "\n".join(
        f"- {score}: {tasks.RUBRIC_ANCHORS[score]}" for score in ("3", "2", "1", "0")
    )
    schema_keys = json.dumps({item: True for item in task.must_hit}, ensure_ascii=False)
    return (
        "You are grading one anonymized transcript of a multi-agent workroom against a "
        "pre-registered rubric. The agents appear as Agent A/B/C. You do not know which "
        "system or configuration produced the transcript; do not try to guess, and do not "
        "reward verbosity or confident tone.\n"
        "\n"
        "# Task given to the room\n"
        f"{task.prompt}\n"
        "\n"
        "# Must-hit checklist\n"
        "Mark each item true only if the transcript actually shows it:\n"
        f"{checklist}\n"
        "\n"
        "# Score anchors\n"
        f"{anchors}\n"
        "\n"
        "# Transcript\n"
        f"{blinded.rendered}\n"
        "\n"
        "# Required output\n"
        f"Respond with STRICT JSON only (no markdown fences, no commentary), with "
        f'"must_hits" keys exactly these: {schema_keys}\n'
        'Schema: {"score": <integer 0-3>, "rationale": "<at most 120 words>", '
        '"must_hits": {<item>: <true|false>, ...}}'
    )


def parse_judge_output(text: str) -> dict[str, Any]:
    """Parse and validate the strict judge JSON; raise JudgeOutputError otherwise."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if "```" in stripped:
            stripped = stripped.rsplit("```", 1)[0]
        stripped = stripped.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise JudgeOutputError("no JSON object found in judge output")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeOutputError(f"judge output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise JudgeOutputError("judge output must be a JSON object")
    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3:
        raise JudgeOutputError("score must be an integer between 0 and 3")
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise JudgeOutputError("rationale must be a non-empty string")
    must_hits = payload.get("must_hits")
    if not isinstance(must_hits, dict) or not all(
        isinstance(key, str) and isinstance(value, bool) for key, value in must_hits.items()
    ):
        raise JudgeOutputError("must_hits must be an object mapping item text to booleans")
    return {
        "score": score,
        "rationale": rationale.strip(),
        "must_hits": {str(key): bool(value) for key, value in must_hits.items()},
    }


def run_judge_command(cmd: str, prompt: str, *, timeout_s: float = 300.0) -> str:
    """Pipe the prompt to an external judge command and return its stdout."""
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise JudgeOutputError(f"judge command timed out after {timeout_s}s") from exc
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "").strip()[-300:]
        raise JudgeOutputError(f"judge command failed ({completed.returncode}): {stderr_tail}")
    return completed.stdout


def cohen_kappa(labels_a: Sequence[int], labels_b: Sequence[int]) -> float | None:
    """Cohen's kappa over integer score labels; None when there is nothing to judge."""
    if len(labels_a) != len(labels_b):
        raise ValueError("kappa requires equally sized label lists")
    count = len(labels_a)
    if count == 0:
        return None
    observed = (
        sum(1 for left, right in zip(labels_a, labels_b, strict=True) if left == right) / count
    )
    labels = sorted(set(labels_a) | set(labels_b))
    expected = sum(
        (labels_a.count(label) / count) * (labels_b.count(label) / count) for label in labels
    )
    if expected >= 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def load_transcripts(transcripts_dir: Path) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for path in sorted(transcripts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            loaded.append(payload)
    return loaded


def _task_for(transcript: Mapping[str, Any], known: Mapping[str, tasks.EvalTask]) -> tasks.EvalTask:
    task_id = str(transcript.get("task_id") or "")
    if task_id not in known:
        raise ValueError(f"transcript references unknown task id: {task_id!r}")
    return known[task_id]


def _skip_entry(transcript: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "transcript_id": transcript.get("transcript_id"),
        "task_id": transcript.get("task_id"),
        "mode": transcript.get("mode"),
        "run": transcript.get("run"),
        "skipped": True,
        "reason": reason,
    }


def _judge_once(cmd: str, prompt: str, *, timeout_s: float) -> dict[str, Any]:
    """One judge pass; a failed command or malformed reply is retried once."""
    try:
        return parse_judge_output(run_judge_command(cmd, prompt, timeout_s=timeout_s))
    except JudgeOutputError:
        return parse_judge_output(run_judge_command(cmd, prompt, timeout_s=timeout_s))


def command_backend(
    transcripts: list[dict[str, Any]],
    known_tasks: Mapping[str, tasks.EvalTask],
    *,
    cmd: str,
    passes: int,
    seed: int,
    timeout_s: float,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for transcript in transcripts:
        if transcript.get("error"):
            entries.append(_skip_entry(transcript, "error transcript"))
            continue
        task = _task_for(transcript, known_tasks)
        blinded = blind_transcript(transcript, seed=seed)
        prompt = build_judge_prompt(task, blinded)
        try:
            results = [_judge_once(cmd, prompt, timeout_s=timeout_s) for _ in range(passes)]
        except JudgeOutputError as exc:
            # One bad transcript must not discard the judgments already made.
            entries.append(_skip_entry(transcript, f"judge failed: {exc}"[:300]))
            continue
        scores = [result["score"] for result in results]
        entry: dict[str, Any] = {
            **blinded.to_json(),
            "mode": transcript.get("mode"),
            "run": transcript.get("run"),
            "passes": results,
            "agree": len(set(scores)) == 1,
            "score_mean": sum(scores) / len(scores),
        }
        entries.append(entry)

    scored = [entry for entry in entries if not entry.get("skipped")]
    agreement = None
    kappa = None
    if scored:
        agreement = sum(1 for entry in scored if entry["agree"]) / len(scored)
        if passes >= 2 and all(len(entry["passes"]) >= 2 for entry in scored):
            kappa = cohen_kappa(
                [entry["passes"][0]["score"] for entry in scored],
                [entry["passes"][1]["score"] for entry in scored],
            )
    return {
        "schema_version": JUDGMENTS_SCHEMA_VERSION,
        "judge": f"command:{cmd}",
        "passes": passes,
        "seed": seed,
        "entries": entries,
        "agreement": agreement,
        "cohen_kappa": kappa,
    }


MANUAL_SHEET_COLUMNS = ("transcript_id", "task_id", "score", "rationale", "must_hits_json")


def write_manual_sheet(
    transcripts: list[dict[str, Any]],
    known_tasks: Mapping[str, tasks.EvalTask],
    *,
    seed: int,
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "judging_sheet.md"
    csv_path = out_dir / "judging_sheet.csv"
    sections: list[str] = [
        "# Eval judging sheet (manual backend)",
        "",
        "Fill one row per transcript in `judging_sheet.csv`. The prompts below are "
        "already blinded: Agent A/B/C letters are randomized per transcript, and mode, "
        "room title, and participant names are withheld. Judge only against the rubric; "
        "ignore verbosity and tone.",
        "",
    ]
    rows: list[dict[str, str]] = []
    for transcript in transcripts:
        transcript_id = str(transcript.get("transcript_id") or "")
        if transcript.get("error"):
            sections.append(f"## {transcript_id}\n\nSkipped: error transcript.\n")
            continue
        task = _task_for(transcript, known_tasks)
        blinded = blind_transcript(transcript, seed=seed)
        sections.append(f"## {transcript_id}")
        sections.append("")
        sections.append("````text")
        sections.append(build_judge_prompt(task, blinded))
        sections.append("````")
        sections.append("")
        rows.append(
            {
                "transcript_id": transcript_id,
                "task_id": task.task_id,
                "score": "",
                "rationale": "",
                "must_hits_json": "",
            }
        )
    md_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return md_path, csv_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--transcripts", type=Path, required=True, help="transcript directory")
    parser.add_argument("--judge", choices=("manual", "command"), default="manual")
    parser.add_argument("--judge-cmd", default=None, help="external command for --judge command")
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--judge-timeout-s", type=float, default=300.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="judgments.json path (default: next to --transcripts)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.judge == "command" and not args.judge_cmd:
        raise SystemExit("--judge command requires --judge-cmd")
    transcripts = load_transcripts(args.transcripts)
    if not transcripts:
        raise SystemExit(f"no transcripts found under {args.transcripts}")
    known_tasks = tasks.tasks_by_id()

    if args.judge == "manual":
        md_path, csv_path = write_manual_sheet(
            transcripts, known_tasks, seed=args.seed, out_dir=args.transcripts
        )
        print(f"Wrote {md_path}")
        print(f"Wrote {csv_path}")
        return 0

    payload = command_backend(
        transcripts,
        known_tasks,
        cmd=str(args.judge_cmd),
        passes=max(1, args.passes),
        seed=args.seed,
        timeout_s=args.judge_timeout_s,
    )
    out_path = args.out or args.transcripts.parent / "judgments.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scored = [entry for entry in payload["entries"] if not entry.get("skipped")]
    print(f"Wrote {out_path} ({len(scored)} judged transcripts)")
    if payload["agreement"] is not None:
        kappa_text = (
            f"{payload['cohen_kappa']:.3f}" if payload["cohen_kappa"] is not None else "n/a"
        )
        print(f"pass agreement: {payload['agreement']:.0%}, kappa: {kappa_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
