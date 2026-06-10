"""Phase gates, stale artifact scans, and phase status helpers for Hermes.

This module is intentionally facade-free. Callers that need legacy
master/slave summaries should inject callbacks into ``run_phase_hardening``.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROMOTION_PASS_VERDICTS = {"pass", "passed", "usable", "usable_ack", "ack", "approved"}
STALE_CANDIDATE_FILES = (
    "ack.json",
    "review_verdict.json",
    "execute_review.md",
    "result.md",
    "reflect_phase-8.md",
    "plan_review.md",
    "plan_final.md",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _context_bundle_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str):
            return path
    return None


def check_state_ack_consistency(loop_root: str | Path, phase_id: str) -> dict[str, Any]:
    loop = Path(loop_root)
    phase_dir = loop / "work" / phase_id
    blockers: list[str] = []

    ack_path = phase_dir / "ack.json"
    review_path = phase_dir / "review_verdict.json"
    result_path = phase_dir / "result.md"

    ack: dict[str, Any] = {}
    review: dict[str, Any] = {}

    if not ack_path.exists():
        blockers.append("missing ack.json")
    else:
        try:
            loaded_ack = _read_json(ack_path)
            if isinstance(loaded_ack, dict):
                ack = loaded_ack
            else:
                blockers.append("ack.json root is not an object")
        except Exception as exc:
            blockers.append(f"invalid ack.json: {exc}")
        if ack and str(ack.get("ack_level", "")).lower() != "usable":
            blockers.append("ack_level is not usable")

    if not review_path.exists():
        blockers.append("missing review_verdict.json")
    else:
        try:
            loaded_review = _read_json(review_path)
            if isinstance(loaded_review, dict):
                review = loaded_review
            else:
                blockers.append("review_verdict root is not an object")
        except Exception as exc:
            blockers.append(f"invalid review_verdict.json: {exc}")
        verdict = str(review.get("verdict", "")).lower() if review else ""
        if review and verdict not in PROMOTION_PASS_VERDICTS:
            blockers.append("review verdict is not passing")

    if not result_path.exists():
        blockers.append("missing result.md")

    ack_bundle = _context_bundle_path(ack.get("context_bundle")) if ack else None
    review_bundle = _context_bundle_path(review.get("context_bundle")) if review else None
    if ack_bundle and review_bundle and ack_bundle != review_bundle:
        blockers.append("ack/review context_bundle mismatch")
    if ack_bundle and result_path.exists():
        result_text = result_path.read_text(encoding="utf-8", errors="replace")
        if ack_bundle not in result_text:
            blockers.append("result.md does not reference ack context_bundle")

    return {
        "phase_id": phase_id,
        "ok": not blockers,
        "blockers": blockers,
        "ack_path": str(ack_path),
        "review_path": str(review_path),
        "result_path": str(result_path),
    }


def _benchmark_eval_decision_runs(decision: Any) -> bool:
    return isinstance(decision, dict) and bool(decision.get("run"))


def check_review_eval_decision(loop_root: str | Path, phase_id: str) -> dict[str, Any]:
    loop = Path(loop_root)
    review_path = loop / "work" / phase_id / "review_verdict.json"
    blockers: list[str] = []

    if not review_path.exists():
        return {
            "phase_id": phase_id,
            "ok": False,
            "blockers": ["missing review_verdict.json"],
            "review_path": str(review_path),
        }

    try:
        review = _read_json(review_path)
    except Exception as exc:
        return {
            "phase_id": phase_id,
            "ok": False,
            "blockers": [f"invalid review_verdict.json: {exc}"],
            "review_path": str(review_path),
        }

    if not isinstance(review, dict):
        return {
            "phase_id": phase_id,
            "ok": False,
            "blockers": ["review_verdict root is not an object"],
            "review_path": str(review_path),
        }

    eval_decision = review.get("review_eval_decision")
    if not isinstance(eval_decision, dict):
        return {
            "phase_id": phase_id,
            "ok": False,
            "blockers": ["missing review_eval_decision"],
            "review_path": str(review_path),
        }

    scope = str(eval_decision.get("scope", "")).lower()
    reason = str(eval_decision.get("reason", "")).strip()
    promotion_gate = str(eval_decision.get("promotion_gate", "")).lower()
    decision = str(review.get("decision", "")).lower()
    verdict = str(review.get("verdict", "")).lower()
    longmemeval = eval_decision.get("longmemeval")
    locomo = eval_decision.get("locomo")
    lme_runs = _benchmark_eval_decision_runs(longmemeval)
    locomo_runs = _benchmark_eval_decision_runs(locomo)

    if scope not in {"not_applicable", "smoke", "milestone"}:
        blockers.append("review_eval_decision.scope is invalid")
    if not reason:
        blockers.append("review_eval_decision.reason is required")
    if promotion_gate not in {"satisfied", "not_applicable", "not_satisfied"}:
        blockers.append("review_eval_decision.promotion_gate is invalid")
    if not isinstance(longmemeval, dict):
        blockers.append("review_eval_decision.longmemeval is required")
    if not isinstance(locomo, dict):
        blockers.append("review_eval_decision.locomo is required")

    if decision == "advance" and promotion_gate not in {"satisfied", "not_applicable"}:
        blockers.append("advance requires promotion_gate satisfied or not_applicable")

    if scope == "milestone":
        if not (lme_runs and locomo_runs):
            blockers.append("milestone scope requires both LongMemEval and LoCoMo")
        if promotion_gate == "satisfied" and not (
            bool(eval_decision.get("llm_answer")) and bool(eval_decision.get("llm_judge"))
        ):
            blockers.append("satisfied milestone promotion requires llm_answer and llm_judge")

    if (
        verdict in PROMOTION_PASS_VERDICTS
        and promotion_gate == "satisfied"
        and scope != "not_applicable"
        and lme_runs != locomo_runs
    ):
        blockers.append("promotion evidence cannot be LongMemEval-only or LoCoMo-only")

    return {
        "phase_id": phase_id,
        "ok": not blockers,
        "blockers": blockers,
        "review_path": str(review_path),
        "review_eval_decision": eval_decision,
    }


def check_execute_goal_contract(loop_root: str | Path, phase_id: str) -> dict[str, Any]:
    loop = Path(loop_root)
    goal_path = loop / "work" / phase_id / "execute_goal.md"
    blockers: list[str] = []

    if not goal_path.exists():
        return {
            "phase_id": phase_id,
            "ok": False,
            "blockers": ["missing execute_goal.md"],
            "goal_path": str(goal_path),
        }

    text = goal_path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""

    if first_line != f"# phase: {phase_id}":
        blockers.append("execute_goal.md phase binding mismatch")
    if "/goal" not in text:
        blockers.append("execute_goal.md missing /goal command")
    if "real memoryos" not in lowered and "real v3" not in lowered:
        blockers.append("execute_goal.md must require real MemoryOS path wiring")
    if "result.md" not in lowered:
        blockers.append("execute_goal.md must require result.md")
    if "test" not in lowered:
        blockers.append("execute_goal.md must require tests")
    if "demo-only" not in lowered and "demo only" not in lowered:
        blockers.append("execute_goal.md must forbid demo-only implementation")
    if not re.search(r"max repair cycles:\s*[1-3]\b", text, flags=re.IGNORECASE):
        blockers.append("execute_goal.md must cap max repair cycles at 1-3")

    forbidden_score_patterns = (
        r"target\s+score",
        r"score\s*(?:>=|>|=)",
        r"pass\s+rate\s*(?:>=|>|=)",
        r"accuracy\s*(?:>=|>|=)",
        r"must\s+pass\s+\d+\s*/\s*\d+",
    )
    if any(re.search(pattern, lowered) for pattern in forbidden_score_patterns):
        blockers.append("execute_goal.md contains forbidden benchmark score target")

    return {
        "phase_id": phase_id,
        "ok": not blockers,
        "blockers": blockers,
        "goal_path": str(goal_path),
    }


def check_config_blueprint_consistency(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    config_path = loop / "config.json"
    blueprint_path = loop / "blueprint.md"
    blockers: list[str] = []
    missing_headings: list[dict[str, str]] = []

    if not config_path.exists():
        blockers.append("missing config.json")
    if not blueprint_path.exists():
        blockers.append("missing blueprint.md")
    if blockers:
        return {"ok": False, "blockers": blockers, "missing_headings": missing_headings}

    try:
        config = _read_json(config_path)
    except Exception as exc:
        return {
            "ok": False,
            "blockers": [f"invalid config.json: {exc}"],
            "missing_headings": missing_headings,
        }

    blueprint = blueprint_path.read_text(encoding="utf-8", errors="replace")
    headings = set(re.findall(r"^(?:##|###)\s+(.+)$", blueprint, flags=re.MULTILINE))
    phases = config.get("phases", []) if isinstance(config, dict) else []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        heading = phase.get("blueprint_heading")
        phase_id = phase.get("id")
        if isinstance(heading, str) and heading not in headings:
            missing_headings.append({"phase": str(phase_id), "heading": heading})

    if missing_headings:
        blockers.append("config phase blueprint_heading missing from blueprint.md")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "missing_headings": missing_headings,
    }


def _phase_index(phase_id: str) -> int | None:
    match = re.fullmatch(r"phase-(\d+)", phase_id)
    if not match:
        return None
    return int(match.group(1))


def _has_superseded_adjustment(loop_root: Path, phase_id: str) -> bool:
    adjustment_path = loop_root / "work" / phase_id / "adjustment.md"
    if not adjustment_path.exists():
        return False
    text = adjustment_path.read_text(encoding="utf-8", errors="replace").lower()
    return "superseded" in text or "repeat_phase" in text or "god_adjust" in text


def check_state_phase_order(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    state_path = loop / "state.json"
    if not state_path.exists():
        return {"ok": False, "blockers": ["missing state.json"], "problems": []}

    try:
        state = _read_json(state_path)
    except Exception as exc:
        return {"ok": False, "blockers": [f"invalid state.json: {exc}"], "problems": []}

    current_phase_idx = state.get("current_phase_idx") if isinstance(state, dict) else None
    phases = state.get("phases", []) if isinstance(state, dict) else []
    if not isinstance(current_phase_idx, int):
        return {
            "ok": False,
            "blockers": ["current_phase_idx is missing or not an integer"],
            "problems": [],
        }

    problems: list[dict[str, str]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_id = str(phase.get("id", ""))
        phase_idx = _phase_index(phase_id)
        if phase_idx is None:
            continue
        status = str(phase.get("status", ""))
        if phase_idx < current_phase_idx:
            if status == "completed":
                continue
            if status == "superseded" and _has_superseded_adjustment(loop, phase_id):
                continue
            problems.append(
                {
                    "phase": phase_id,
                    "status": status,
                    "reason": (
                        "phase before current_phase_idx is not completed or documented superseded"
                    ),
                }
            )
        if phase_idx > current_phase_idx and status == "completed":
            problems.append(
                {
                    "phase": phase_id,
                    "status": status,
                    "reason": "phase after current_phase_idx is completed",
                }
            )

    return {"ok": not problems, "blockers": [], "problems": problems}


def check_execute_bootstrap_gate(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    state_path = loop / "state.json"
    if not state_path.exists():
        return {
            "ok": False,
            "phase_id": None,
            "action": "missing_state",
            "blockers": ["missing state.json"],
        }

    try:
        state = _read_json(state_path)
    except Exception as exc:
        return {
            "ok": False,
            "phase_id": None,
            "action": "invalid_state",
            "blockers": [f"invalid state.json: {exc}"],
        }

    execute_lane = state.get("execute_lane") if isinstance(state, dict) else {}
    phase_id = (
        str(execute_lane.get("phase"))
        if isinstance(execute_lane, dict) and execute_lane.get("phase")
        else None
    )
    current_state = str(state.get("current_state", "")).upper() if isinstance(state, dict) else ""
    if not phase_id:
        return {"ok": True, "phase_id": phase_id, "action": "not_in_execute", "blockers": []}

    phase_dir = loop / "work" / phase_id
    required_files = ("context_bundle.md", "god_dispatch.json", "plan_final.md")
    present = []
    missing = []
    for name in required_files:
        path = phase_dir / name
        if path.exists():
            present.append(name)
        else:
            missing.append(f"missing {name}")

    if current_state == "GOD_DISPATCH":
        missing_names = [item.removeprefix("missing ") for item in missing]
        return {
            "phase_id": phase_id,
            "ok": True,
            "action": "promote_execute" if not missing else "dispatch_incomplete",
            "blockers": [],
            "present_files": present,
            "missing_files": missing_names,
            "phase_dir": str(phase_dir),
        }

    if current_state != "EXECUTE":
        return {"ok": True, "phase_id": phase_id, "action": "not_in_execute", "blockers": []}

    blockers: list[str] = []
    if missing:
        blockers.extend(missing)
        action = "bootstrap_dispatch"
    else:
        action = "allow_execute"

    return {
        "phase_id": phase_id,
        "ok": not blockers,
        "action": action,
        "blockers": blockers,
        "present_files": present,
        "phase_dir": str(phase_dir),
    }


def promote_dispatch_to_execute(loop_root: str | Path, *, now: str | None = None) -> dict[str, Any]:
    loop = Path(loop_root)
    status = check_execute_bootstrap_gate(loop)
    if status.get("action") != "promote_execute":
        return {**status, "promoted": False}

    state_path = loop / "state.json"
    state = _read_json(state_path)
    phase_id = str(status.get("phase_id"))
    timestamp = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["current_state"] = "EXECUTE"
    state.setdefault("execute_lane", {})["state"] = "EXECUTE"
    state["last_updated"] = timestamp
    _atomic_write_json(state_path, state)

    phase_dir = loop / "work" / phase_id
    phase_status_path = phase_dir / "phase_status.md"
    if phase_status_path.exists():
        previous = phase_status_path.read_text(encoding="utf-8", errors="replace").rstrip()
    else:
        previous = f"# phase: {phase_id}"

    note = (
        "\n\n## GOD_DISPATCH Auto-Promote To EXECUTE\n\n"
        f"Time: {timestamp}\n\n"
        "Reason: `context_bundle.md`, `god_dispatch.json`, and `plan_final.md` "
        "already exist for the active execute phase. Launcher preflight promoted "
        "the controller to `EXECUTE` without waiting for prompt-level action.\n"
    )
    if "## GOD_DISPATCH Auto-Promote To EXECUTE" not in previous:
        _atomic_write_text(phase_status_path, previous + note)

    return {
        **status,
        "ok": True,
        "action": "promoted_execute",
        "promoted": True,
        "state_path": str(state_path),
        "phase_status_path": str(phase_status_path),
    }


def _markdown_phase_bound(path: Path, phase_id: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    first_line = lines[0].strip() if lines else ""
    return first_line == f"# phase: {phase_id}"


def check_execute_completion_gate(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    state_path = loop / "state.json"
    if not state_path.exists():
        return {
            "ok": False,
            "phase_id": None,
            "action": "missing_state",
            "blockers": ["missing state.json"],
        }

    try:
        state = _read_json(state_path)
    except Exception as exc:
        return {
            "ok": False,
            "phase_id": None,
            "action": "invalid_state",
            "blockers": [f"invalid state.json: {exc}"],
        }

    execute_lane = state.get("execute_lane") if isinstance(state, dict) else {}
    phase_id = (
        str(execute_lane.get("phase"))
        if isinstance(execute_lane, dict) and execute_lane.get("phase")
        else None
    )
    current_state = str(state.get("current_state", "")).upper() if isinstance(state, dict) else ""
    if not phase_id or current_state != "EXECUTE":
        return {"ok": True, "phase_id": phase_id, "action": "not_in_execute", "blockers": []}

    phase_dir = loop / "work" / phase_id
    result_path = phase_dir / "result.md"
    if not result_path.exists():
        return {
            "ok": True,
            "phase_id": phase_id,
            "action": "wait_execute",
            "blockers": [],
            "missing_files": ["result.md"],
            "phase_dir": str(phase_dir),
        }

    if not _markdown_phase_bound(result_path, phase_id):
        return {
            "ok": False,
            "phase_id": phase_id,
            "action": "blocked_stale_result",
            "blockers": ["result.md phase binding mismatch"],
            "result_path": str(result_path),
            "phase_dir": str(phase_dir),
        }

    return {
        "ok": True,
        "phase_id": phase_id,
        "action": "promote_execute_self_review",
        "blockers": [],
        "present_files": ["result.md"],
        "result_path": str(result_path),
        "phase_dir": str(phase_dir),
    }


def promote_execute_to_self_review(
    loop_root: str | Path,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    status = check_execute_completion_gate(loop)
    if status.get("action") != "promote_execute_self_review":
        return {**status, "promoted": False}

    state_path = loop / "state.json"
    state = _read_json(state_path)
    phase_id = str(status.get("phase_id"))
    timestamp = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["current_state"] = "EXECUTE_SELF_REVIEW"
    state.setdefault("execute_lane", {})["state"] = "EXECUTE_SELF_REVIEW"
    state["last_updated"] = timestamp
    _atomic_write_json(state_path, state)

    phase_dir = loop / "work" / phase_id
    phase_status_path = phase_dir / "phase_status.md"
    if phase_status_path.exists():
        previous = phase_status_path.read_text(encoding="utf-8", errors="replace").rstrip()
    else:
        previous = f"# phase: {phase_id}"

    note = (
        "\n\n## EXECUTE Auto-Promote To EXECUTE_SELF_REVIEW\n\n"
        f"Time: {timestamp}\n\n"
        "Reason: phase-bound `result.md` exists for the active execute phase. "
        "Controller hardening promoted the state to `EXECUTE_SELF_REVIEW` "
        "without waiting for prompt-level action.\n"
    )
    if "## EXECUTE Auto-Promote To EXECUTE_SELF_REVIEW" not in previous:
        _atomic_write_text(phase_status_path, previous + note)

    return {
        **status,
        "ok": True,
        "action": "promoted_execute_self_review",
        "promoted": True,
        "state_path": str(state_path),
        "phase_status_path": str(phase_status_path),
    }


def scan_stale_artifacts(
    phase_dir: str | Path,
    *,
    current_context_bundle: str,
    candidate_files: tuple[str, ...] = STALE_CANDIDATE_FILES,
) -> dict[str, Any]:
    phase = Path(phase_dir)
    stale_files: list[str] = []
    active_files: list[str] = []
    missing_files: list[str] = []

    for name in candidate_files:
        path = phase / name
        if not path.exists():
            missing_files.append(name)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if current_context_bundle in text:
            active_files.append(name)
        else:
            stale_files.append(name)

    return {
        "phase_dir": str(phase),
        "current_context_bundle": current_context_bundle,
        "stale_files": stale_files,
        "active_files": active_files,
        "missing_files": missing_files,
    }


def generate_shard_resume_plan(
    *,
    benchmark: str,
    data_path: str,
    baseline: str,
    run_id_prefix: str,
    limit: int,
    shard_size: int,
    comparison_report: str | None = None,
) -> str:
    lines = [
        "# Shard Resume Plan",
        "",
        "Run shards only after the monolithic 50-case run is confirmed stalled or invalid.",
        "",
    ]
    shard_count = math.ceil(limit / shard_size)
    for shard_idx in range(shard_count):
        start = shard_idx * shard_size + 1
        end = min(limit, (shard_idx + 1) * shard_size)
        run_id = f"{run_id_prefix}_s{shard_idx + 1:02d}_{start:03d}_{end:03d}"
        comparison = f" --comparison-report {comparison_report}" if comparison_report else ""
        lines.append(
            "MEMORYOS_MEMORY_ARCH=v3 uv run memoryos eval public "
            f"--benchmark {benchmark} "
            f"--data-path {data_path} "
            f"--baseline {baseline} "
            f"--limit {end - start + 1} "
            "--llm-answer --llm-judge"
            f"{comparison} "
            f"--run-id {run_id}"
        )
    return "\n".join(lines) + "\n"


def write_phase_status(
    loop_root: str | Path,
    phase_id: str,
    statuses: list[dict[str, Any]],
    *,
    ack_gate: dict[str, Any] | None = None,
    stale_index: dict[str, Any] | None = None,
) -> dict[str, Path]:
    loop = Path(loop_root)
    phase_dir = loop / "work" / phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase_id": phase_id,
        "eval_runs": statuses,
        "ack_gate": ack_gate,
        "stale_index": stale_index,
    }
    json_path = phase_dir / "eval_heartbeat.json"
    md_path = phase_dir / "eval_heartbeat.md"
    status_path = phase_dir / f"{phase_id}_status.md"
    _atomic_write_json(json_path, payload)

    lines = [f"# {phase_id} Eval Heartbeat", ""]
    for status in statuses:
        lines.append(
            f"- {status.get('benchmark')} `{status.get('run_id')}`: "
            f"{status.get('state')} rows={status.get('rows_done', 0)} "
            f"pass={status.get('pass_count', 0)} fail={status.get('fail_count', 0)} "
            f"reason={status.get('reason')}"
        )
    if ack_gate is not None:
        lines.append("")
        lines.append(f"- ack_gate: {'ok' if ack_gate.get('ok') else 'blocked'}")
        for blocker in ack_gate.get("blockers", []):
            lines.append(f"  - {blocker}")
    md = "\n".join(lines) + "\n"
    _atomic_write_text(md_path, md)
    _atomic_write_text(status_path, md)
    return {"json": json_path, "markdown": md_path, "status": status_path}


MasterSlaveSummary = Callable[[Path], dict[str, Any]]
MasterSlaveWriter = Callable[[Path, dict[str, Any]], Any]


def run_phase_hardening(
    loop_root: str | Path,
    eval_root: str | Path,
    phase_id: str,
    *,
    write: bool = False,
    summarize_master_slave: MasterSlaveSummary | None = None,
    write_master_slave_status: MasterSlaveWriter | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    _ = Path(eval_root)
    context_bundle = f"work/{phase_id}/context_bundle.md"
    statuses: list[dict[str, Any]] = []
    ack_gate = check_state_ack_consistency(loop, phase_id)
    review_eval_gate = check_review_eval_decision(loop, phase_id)
    execute_goal_gate = check_execute_goal_contract(loop, phase_id)
    if write:
        execute_completion_gate = promote_execute_to_self_review(loop)
    else:
        execute_completion_gate = check_execute_completion_gate(loop)
    stale_index = scan_stale_artifacts(
        loop / "work" / phase_id,
        current_context_bundle=context_bundle,
    )
    config_gate = check_config_blueprint_consistency(loop)
    state_order_gate = check_state_phase_order(loop)
    master_slave = summarize_master_slave(loop) if summarize_master_slave else None
    if write:
        write_phase_status(loop, phase_id, statuses, ack_gate=ack_gate, stale_index=stale_index)
        if master_slave is not None and write_master_slave_status is not None:
            write_master_slave_status(loop, master_slave)
    return {
        "phase_id": phase_id,
        "eval_runs": statuses,
        "ack_gate": ack_gate,
        "review_eval_gate": review_eval_gate,
        "execute_goal_gate": execute_goal_gate,
        "execute_completion_gate": execute_completion_gate,
        "stale_index": stale_index,
        "config_gate": config_gate,
        "state_order_gate": state_order_gate,
        "master_slave": master_slave,
    }


__all__ = [
    "PROMOTION_PASS_VERDICTS",
    "STALE_CANDIDATE_FILES",
    "check_config_blueprint_consistency",
    "check_execute_bootstrap_gate",
    "check_execute_completion_gate",
    "check_execute_goal_contract",
    "check_review_eval_decision",
    "check_state_ack_consistency",
    "check_state_phase_order",
    "generate_shard_resume_plan",
    "promote_dispatch_to_execute",
    "promote_execute_to_self_review",
    "run_phase_hardening",
    "scan_stale_artifacts",
    "write_phase_status",
]
