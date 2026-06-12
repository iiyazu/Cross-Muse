from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.release_readiness import ProofLevel


def capture_goal_stage_evidence(
    *,
    run_id: str,
    output_path: str | Path,
    stage_results: tuple[str | Path, ...],
) -> dict[str, Any]:
    """Convert goal-stage runner results into replay section evidence.

    This indexes stage harness outputs only. It does not make stage result files
    authoritative for lane status, review truth, GitHub truth, or release gates.
    """
    output = Path(output_path)
    rows = [_stage_result_row(Path(path)) for path in stage_results]
    non_ok = [row for row in rows if row["status"] != "ok"]
    status = "ok" if rows and not non_ok else "blocked"
    proof_level: ProofLevel = "contract_proof" if status == "ok" else "manual_gap"
    blocked_reason = None
    next_action = None
    if status != "ok":
        blocked_reason = _blocked_reason(rows=rows, non_ok=non_ok)
        next_action = (
            "Resolve non-ok goal stage results before claiming overnight stage completion."
        )

    payload: dict[str, Any] = {
        "schema_version": "xmuse.production_evidence.v1",
        "generated_at": _utc_now(),
        "stage_id": _first_stage_id(rows),
        "action": "goal_stage_results_indexed",
        "status": status,
        "proof_level": proof_level,
        "source_authority": "goal_stage_harness",
        "source_refs": _source_refs(run_id=run_id, rows=rows),
        "target_refs": ["overnight_replay_section:stage_evidence"],
        "commands": _commands(rows),
        "test_results": [],
        "artifacts": _artifacts(rows),
        "blocked_reason": blocked_reason,
        "owner": "codex",
        "next_action": next_action,
        "summary": _summary(rows),
        "stage_results": [_public_stage_result(row) for row in rows],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _stage_result_row(path: Path) -> dict[str, Any]:
    payload = _load_stage_result(path)
    stage_id = _clean_text(payload.get("stage_id")) or "unknown"
    status = _stage_status(payload.get("status"))
    row: dict[str, Any] = {
        "stage_id": stage_id,
        "status": status,
        "engine": _clean_text(payload.get("engine")) or "unknown",
        "returncode": payload.get("returncode"),
        "attempt": payload.get("attempt"),
        "result_path": str(path),
    }
    issues = _issue_messages(payload.get("issues"))
    if issues:
        row["issues"] = issues
    artifacts = _related_artifacts(path=path, payload=payload)
    if artifacts:
        row["_artifacts"] = artifacts
    command = _command(payload.get("command"))
    if command:
        row["_command"] = command
    return row


def _load_stage_result(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"goal stage result does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"goal stage result is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"goal stage result must be a JSON object: {path}")
    return payload


def _stage_status(value: object) -> str:
    if value in {"ok", "retry", "blocked"}:
        return str(value)
    return "blocked"


def _related_artifacts(*, path: Path, payload: dict[str, Any]) -> list[str]:
    artifacts: list[str] = [str(path)]
    for related in (
        path.parent / f"{path.name}.prompt.txt",
        path.parent / f"{path.name}.manifest.jsonl",
    ):
        if related.exists():
            artifacts.append(str(related))
    stdout_path = _clean_text(payload.get("agent_stdout_path"))
    if stdout_path and Path(stdout_path).exists():
        artifacts.append(stdout_path)
    return _dedupe(artifacts)


def _artifacts(rows: list[dict[str, Any]]) -> list[str]:
    artifacts: list[str] = []
    for row in rows:
        value = row.get("_artifacts")
        if isinstance(value, list):
            artifacts.extend(item for item in value if isinstance(item, str))
    return _dedupe(artifacts)


def _source_refs(*, run_id: str, rows: list[dict[str, Any]]) -> list[str]:
    refs = [f"goal_run:{run_id}"]
    for row in rows:
        stage_id = _clean_text(row.get("stage_id")) or "unknown"
        result_path = _clean_text(row.get("result_path"))
        refs.append(f"goal_stage:{stage_id}")
        if result_path:
            refs.append(f"goal_stage_result:{result_path}")
    return _dedupe(refs)


def _commands(rows: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for row in rows:
        command = row.get("_command")
        if isinstance(command, list) and all(isinstance(item, str) for item in command):
            commands.append(" ".join(command))
    return _dedupe(commands)


def _command(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _issue_messages(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        message = _clean_text(item.get("message"))
        if message:
            messages.append(message)
    return messages


def _public_stage_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if not key.startswith("_")
    }


def _summary(rows: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        status = _clean_text(row.get("status")) or "blocked"
        counts[status] = counts.get(status, 0) + 1
    count_parts = [
        f"{status}={count}"
        for status, count in counts.items()
        if count
    ]
    return (
        f"Goal stage harness indexed {len(rows)} result(s): "
        f"{', '.join(count_parts) if count_parts else 'none'}."
    )


def _blocked_reason(
    *,
    rows: list[dict[str, Any]],
    non_ok: list[dict[str, Any]],
) -> str:
    if not rows:
        return "goal stage evidence has no stage result artifacts"
    pairs = [
        f"{row.get('stage_id', 'unknown')}={row.get('status', 'blocked')}"
        for row in non_ok
    ]
    return "goal stage results include non-ok stages: " + ", ".join(pairs)


def _first_stage_id(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "S1"
    return _clean_text(rows[0].get("stage_id")) or "unknown"


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
