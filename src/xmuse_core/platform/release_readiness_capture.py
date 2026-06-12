from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.release_readiness import (
    GateStatus,
    ProofLevel,
    ReleaseGateEvidence,
    ReleaseGateKind,
    evaluate_release_readiness,
)

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD)[A-Z0-9_]*=)([^\s]+)"
    ),
    re.compile(r"(?i)\b(--(?:api-key|token|secret|password)\s+)([^\s]+)"),
    re.compile(r"(?i)\b(authorization:\s*bearer\s+)([^\s]+)"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+\b"),
    re.compile(r"\b(?:secret|token)[-_][A-Za-z0-9._-]+\b", re.IGNORECASE),
)


def capture_release_readiness(
    *,
    artifacts_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    artifacts_root = Path(artifacts_dir)
    gates = load_release_gate_artifacts(artifacts_root)
    readiness = evaluate_release_readiness(gates).model_dump()
    report = _redact_value(
        {
            "schema_version": "xmuse.release_readiness_report.v1",
            "generated_at": _utc_now(),
            "artifacts_dir": str(artifacts_root),
            "artifact_count": len(gates),
            **readiness,
        }
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def load_release_gate_artifacts(artifacts_dir: str | Path) -> list[ReleaseGateEvidence]:
    root = Path(artifacts_dir)
    if not root.exists():
        return []
    gates: list[ReleaseGateEvidence] = []
    for path in sorted(root.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "gate_id" not in payload:
            continue
        gates.append(_gate_from_payload(payload, source_path=path))
    return _deduplicate_gates(gates)


def _deduplicate_gates(gates: list[ReleaseGateEvidence]) -> list[ReleaseGateEvidence]:
    selected: dict[str, ReleaseGateEvidence] = {}
    for gate in gates:
        current = selected.get(gate.gate_id)
        if current is None or _gate_score(gate) > _gate_score(current):
            selected[gate.gate_id] = gate
    return [selected[gate_id] for gate_id in sorted(selected)]


def _gate_score(gate: ReleaseGateEvidence) -> tuple[int, int, int, int, str]:
    readiness = evaluate_release_readiness([gate])
    return (
        1 if not readiness.blockers else 0,
        _status_score(gate.status),
        _proof_score(gate.proof_level),
        1 if gate.configured else 0,
        gate.summary,
    )


def _status_score(status: GateStatus) -> int:
    return {
        "ok": 3,
        "blocked": 2,
        "manual_gap": 1,
        "not_evaluated": 0,
    }[status]


def _proof_score(proof_level: ProofLevel) -> int:
    return {
        "server_side_merge_proof": 8,
        "server_side_enforcement_proof": 7,
        "real_provider_proof": 6,
        "live_service_proof": 5,
        "internal_review_proof": 4,
        "contract_proof": 3,
        "fake_runtime_proof": 2,
        "manual_gap": 1,
    }[proof_level]


def _gate_from_payload(
    payload: dict[str, Any],
    *,
    source_path: Path,
) -> ReleaseGateEvidence:
    gate_id = _required_text(payload, "gate_id", source_path=source_path)
    kind = ReleaseGateKind(_required_text(_kind_payload(payload), "kind", source_path=source_path))
    configured = _bool(payload.get("configured"), default=True)
    required = _bool(payload.get("required"), default=True)
    status = _status(payload.get("status"), blocked_reason=payload.get("blocked_reason"))
    proof_level = _proof_level(payload.get("proof_level"))
    commands = _string_list(payload.get("commands"))
    attempted_command = _text(payload.get("attempted_command"))
    if attempted_command is None and commands:
        attempted_command = "\n".join(commands)
    return ReleaseGateEvidence(
        gate_id=gate_id,
        kind=kind,
        configured=configured,
        required=required,
        status=status,
        proof_level=proof_level,
        owner=_text(payload.get("owner")) or "operator",
        summary=_text(payload.get("summary"))
        or _text(payload.get("blocked_reason"))
        or f"release gate artifact {source_path.name}",
        attempted_command=attempted_command,
        next_action=_text(payload.get("next_action")),
        source_refs=tuple(_string_list(payload.get("source_refs"))),
        artifacts=tuple(_string_list(payload.get("artifacts"))),
    )


def _kind_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": payload.get("kind")
        or payload.get("release_gate_kind")
        or payload.get("gate_kind")
    }


def _required_text(
    payload: dict[str, Any],
    key: str,
    *,
    source_path: Path,
) -> str:
    value = _text(payload.get(key))
    if value is None:
        raise ValueError(f"{source_path}: missing {key}")
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _status(value: Any, *, blocked_reason: Any) -> GateStatus:
    if value in {"ok", "blocked", "manual_gap", "not_evaluated"}:
        return value
    if _text(blocked_reason):
        return "blocked"
    return "not_evaluated"


def _proof_level(value: Any) -> ProofLevel:
    if value in {
        "contract_proof",
        "fake_runtime_proof",
        "live_service_proof",
        "server_side_enforcement_proof",
        "server_side_merge_proof",
        "real_provider_proof",
        "internal_review_proof",
        "manual_gap",
    }:
        return value
    return "manual_gap"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS[:3]:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    for pattern in _SECRET_PATTERNS[3:]:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
