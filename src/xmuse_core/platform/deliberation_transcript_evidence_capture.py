from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.platform.natural_deliberation_release_gate import (
    build_natural_deliberation_release_gate,
)
from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel

DELIBERATION_TRANSCRIPT_ACTION = "deliberation_transcript_verified"
DELIBERATION_TRANSCRIPT_AUTHORITY = "operator_transcript_v1"


def capture_deliberation_transcript_evidence(
    *,
    run_id: str,
    transcript_artifact: str | Path,
    output_path: str | Path,
    god_runtime_artifact: str | Path | None = None,
    stage_id: str = "S5",
) -> dict[str, object]:
    transcript_path = Path(transcript_artifact)
    transcript, load_error = _load_transcript(transcript_path)
    gate = build_natural_deliberation_release_gate(
        transcript,
        artifact_path=transcript_path,
        load_error=load_error,
        god_runtime_continuity=_load_runtime(god_runtime_artifact),
        god_runtime_path=god_runtime_artifact,
        god_runtime_load_error=_runtime_load_error(god_runtime_artifact),
    )
    evidence = build_deliberation_transcript_evidence(
        run_id=run_id,
        stage_id=stage_id,
        gate=gate,
        transcript_artifact=transcript_path,
        transcript=transcript,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_deliberation_transcript_evidence(
    *,
    run_id: str,
    stage_id: str,
    gate: dict[str, Any],
    transcript_artifact: str | Path,
    transcript: dict[str, Any] | None,
) -> dict[str, object]:
    gate_status = _text(gate.get("status"))
    proof_level = _proof_level(gate.get("proof_level"))
    status = _evidence_status(gate_status=gate_status, proof_level=proof_level)
    blocked_reason = None if status == "ok" else _text(gate.get("summary"))
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=DELIBERATION_TRANSCRIPT_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=DELIBERATION_TRANSCRIPT_AUTHORITY,
        source_refs=tuple(_string_list(gate.get("source_refs"))),
        target_refs=tuple(_target_refs(transcript)),
        artifacts=tuple(_artifacts(gate=gate, transcript_artifact=transcript_artifact)),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=_text(gate.get("next_action")) if status != "ok" else None,
        summary=_text(gate.get("summary")),
    )
    return envelope.model_dump()


def _load_transcript(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"Natural deliberation transcript does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Natural deliberation transcript could not be read: {exc}."
    if not isinstance(payload, dict):
        return None, "Natural deliberation transcript must be a JSON object."
    return payload, None


def _load_runtime(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload, _error = _load_transcript(Path(path))
    return payload


def _runtime_load_error(path: str | Path | None) -> str | None:
    if path is None:
        return None
    _payload, error = _load_transcript(Path(path))
    return error


def _evidence_status(
    *,
    gate_status: str | None,
    proof_level: ProofLevel,
) -> ProductionEvidenceStatus:
    if gate_status == "ok":
        return "ok"
    if proof_level == "manual_gap":
        return "manual_gap"
    return "blocked"


def _proof_level(value: object) -> ProofLevel:
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
        return value  # type: ignore[return-value]
    return "manual_gap"


def _target_refs(transcript: dict[str, Any] | None) -> list[str]:
    if transcript is None:
        return []
    refs = _string_list(transcript.get("target_refs"))
    for message in _dict_rows(transcript.get("messages")):
        refs.extend(_string_list(message.get("target_refs")))
    return _dedupe(refs)


def _artifacts(
    *,
    gate: dict[str, Any],
    transcript_artifact: str | Path,
) -> list[str]:
    return _dedupe([str(transcript_artifact), *_string_list(gate.get("artifacts"))])


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
