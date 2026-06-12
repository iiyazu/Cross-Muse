from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel

SUPERVISOR_EVIDENCE_ACTION = "overnight_supervisor_checkpoint"
SUPERVISOR_EVIDENCE_AUTHORITY = "overnight_operator_supervisor"


def capture_overnight_supervisor_evidence(
    *,
    snapshot_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    snapshot_file = Path(snapshot_path)
    snapshot = _load_supervisor_snapshot(snapshot_file)
    evidence = build_overnight_supervisor_evidence(
        snapshot=snapshot,
        snapshot_path=snapshot_file,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_overnight_supervisor_evidence(
    *,
    snapshot: dict[str, Any],
    snapshot_path: str | Path,
) -> dict[str, object]:
    run_id = _text(snapshot.get("run_id")) or "unknown"
    stages = _dict_rows(snapshot.get("stages"))
    heartbeats = _dict_rows(snapshot.get("heartbeats"))
    checkpoints = _dict_rows(snapshot.get("checkpoints"))
    manual_gaps = _dict_rows(snapshot.get("manual_gaps"))
    production_evidence = _dict_rows(snapshot.get("production_evidence"))
    stage_id = _selected_stage_id(
        checkpoints=checkpoints,
        stages=stages,
        current_stage_id=_text(snapshot.get("current_stage_id")),
    )
    blocked_reason = _supervisor_blocked_reason(
        heartbeats=heartbeats,
        checkpoints=checkpoints,
    )
    if blocked_reason is None:
        status: ProductionEvidenceStatus = "ok"
        proof_level: ProofLevel = "contract_proof"
        next_action = None
    else:
        status = "manual_gap"
        proof_level = "manual_gap"
        next_action = _supervisor_next_action(blocked_reason)
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=SUPERVISOR_EVIDENCE_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=SUPERVISOR_EVIDENCE_AUTHORITY,
        source_refs=tuple(
            _dedupe(
                [
                    f"overnight_supervisor:{run_id}",
                    *[
                        f"goal:stage:{stage['stage_id']}"
                        for stage in stages
                        if _text(stage.get("stage_id")) is not None
                    ],
                ]
            )
        ),
        commands=tuple(_commands(production_evidence=production_evidence)),
        test_results=tuple(_test_results(production_evidence=production_evidence)),
        artifacts=tuple(
            _artifacts(
                snapshot_path=Path(snapshot_path),
                production_evidence=production_evidence,
            )
        ),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=next_action,
        summary=_summary(
            heartbeat_count=len(heartbeats),
            checkpoint_count=len(checkpoints),
            manual_gap_count=len(manual_gaps),
        ),
    )
    return envelope.model_dump()


def _load_supervisor_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "xmuse.overnight_supervisor.v1"
    ):
        raise ValueError(f"{path}: expected xmuse.overnight_supervisor.v1")
    return payload


def _selected_stage_id(
    *,
    checkpoints: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    current_stage_id: str | None,
) -> str:
    for row in reversed(checkpoints):
        stage_id = _text(row.get("stage_id"))
        if stage_id is not None:
            return stage_id
    if current_stage_id is not None:
        return current_stage_id
    for stage in reversed(stages):
        stage_id = _text(stage.get("stage_id"))
        if stage_id is not None:
            return stage_id
    return "supervisor"


def _supervisor_blocked_reason(
    *,
    heartbeats: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
) -> str | None:
    if not checkpoints:
        return "overnight supervisor snapshot has no checkpoint evidence"
    if not heartbeats:
        return "overnight supervisor snapshot has no heartbeat evidence"
    return None


def _supervisor_next_action(blocked_reason: str) -> str:
    if "heartbeat" in blocked_reason:
        return "Record a supervisor heartbeat and regenerate supervisor replay evidence."
    return "Record a supervisor checkpoint and regenerate supervisor replay evidence."


def _commands(
    *,
    production_evidence: list[dict[str, Any]],
) -> list[str]:
    commands: list[str] = []
    for evidence in production_evidence:
        commands.extend(_string_list(evidence.get("commands")))
    return _dedupe(commands)


def _test_results(
    *,
    production_evidence: list[dict[str, Any]],
) -> list[str]:
    results: list[str] = []
    for evidence in production_evidence:
        results.extend(_string_list(evidence.get("test_results")))
    return _dedupe(results)


def _artifacts(
    *,
    snapshot_path: Path,
    production_evidence: list[dict[str, Any]],
) -> list[str]:
    artifacts = [str(snapshot_path)]
    for evidence in production_evidence:
        artifacts.extend(_string_list(evidence.get("artifacts")))
    return _dedupe(artifacts)


def _summary(
    *,
    heartbeat_count: int,
    checkpoint_count: int,
    manual_gap_count: int,
) -> str:
    return (
        "Supervisor captured "
        f"{heartbeat_count} heartbeat(s), "
        f"{checkpoint_count} checkpoint(s), and "
        f"{manual_gap_count} manual gap(s)."
    )


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str | None:
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
