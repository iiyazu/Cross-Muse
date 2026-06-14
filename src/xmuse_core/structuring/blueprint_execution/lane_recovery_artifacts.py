from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    LaneRecoveryDecision,
)


class LaneRecoveryArtifactError(ValueError):
    """Raised when a durable lane recovery artifact is unreadable or invalid."""


def lane_recovery_artifact_path(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
) -> Path:
    return (
        Path(base_dir)
        / "lane_graphs"
        / f"{_artifact_path_id(graph_id)}.{_artifact_path_id(lane_id)}.recovery.json"
    )


def load_lane_recovery_decisions(
    base_dir: Path,
    *,
    graph_id: str,
    lane_ids: list[str],
) -> list[LaneRecoveryDecision]:
    decisions: list[LaneRecoveryDecision] = []
    for lane_id in lane_ids:
        decision = load_lane_recovery_decision(
            base_dir,
            graph_id=graph_id,
            lane_id=lane_id,
        )
        if decision is not None:
            decisions.append(decision)
    return decisions


def load_lane_recovery_decision(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
) -> LaneRecoveryDecision | None:
    path = lane_recovery_artifact_path(base_dir, graph_id=graph_id, lane_id=lane_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaneRecoveryArtifactError(
            f"lane recovery artifact is invalid: {path.name}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("decision"), dict):
        raise LaneRecoveryArtifactError(
            f"lane recovery artifact is invalid: {path.name}"
        )
    try:
        return LaneRecoveryDecision.model_validate(payload["decision"])
    except ValidationError as exc:
        raise LaneRecoveryArtifactError(str(exc)) from exc


def _artifact_path_id(value: str) -> str:
    safe_id = _artifact_safe_id(value)
    if not value.strip() or safe_id != value or value in {".", ".."}:
        raise ValueError(f"unsafe artifact id: {value}")
    return safe_id


def _artifact_safe_id(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value
    )
