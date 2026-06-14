from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REQUIRED_PROOF_BY_KIND = {
    "local_validation": "contract_proof",
    "internal_review": "internal_review_proof",
    "live_memoryos": "live_service_proof",
    "github_server_truth": "server_side_enforcement_proof",
    "github_merge_truth": "server_side_merge_proof",
    "real_provider": "real_provider_proof",
    "natural_deliberation": "real_provider_proof",
}

_PRODUCTION_PROOFS = {
    "live_service_proof",
    "server_side_enforcement_proof",
    "server_side_merge_proof",
    "real_provider_proof",
}

_CONTAMINATION_MARKERS = (
    "fake",
    "fixture",
    "stdout_fallback",
    "local_only",
    "contract_proof",
    "fake_runtime_proof",
)


def capture_proof_contamination_audit(
    *,
    artifacts_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    artifacts_root = Path(artifacts_dir)
    payloads = _load_gate_payloads(artifacts_root)
    findings: list[dict[str, Any]] = []
    for path, payload in payloads:
        findings.extend(_audit_payload(path=path, payload=payload))

    if not payloads:
        decision = "not_evaluated"
    elif findings:
        decision = "contaminated"
    else:
        decision = "clean"

    report = {
        "schema_version": "xmuse.proof_contamination_audit.v1",
        "generated_at": _utc_now(),
        "artifacts_dir": str(artifacts_root),
        "artifact_count": len(payloads),
        "decision": decision,
        "finding_count": len(findings),
        "findings": findings,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _load_gate_payloads(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if _text(payload.get("gate_id")) is None:
            continue
        payloads.append((path, payload))
    return payloads


def _audit_payload(
    *,
    path: Path,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    gate_id = _text(payload.get("gate_id")) or "<missing>"
    kind = _text(payload.get("kind") or payload.get("release_gate_kind")) or "<missing>"
    status = _text(payload.get("status")) or "<missing>"
    proof_level = _text(payload.get("proof_level")) or "manual_gap"

    required_proof = _REQUIRED_PROOF_BY_KIND.get(kind)
    if status == "ok" and required_proof is not None and proof_level != required_proof:
        findings.append(
            _finding(
                path=path,
                gate_id=gate_id,
                kind=kind,
                code="weak_proof_for_production_gate",
                summary=f"{kind} requires {required_proof}, got {proof_level}.",
            )
        )

    marker = _contamination_marker(payload)
    if status == "ok" and proof_level in _PRODUCTION_PROOFS and marker is not None:
        findings.append(
            _finding(
                path=path,
                gate_id=gate_id,
                kind=kind,
                code="fake_marker_in_production_proof",
                summary=(
                    "Production proof contains fake/local/stdout contamination "
                    f"marker: {marker}."
                ),
            )
        )

    if _claims_pr_merged(payload, kind=kind) and not _has_merge_truth(payload):
        findings.append(
            _finding(
                path=path,
                gate_id=gate_id,
                kind=kind,
                code="pr_merged_without_merge_truth",
                summary="pr_merged requires server_side_merge_proof and can_emit_pr_merged=true.",
            )
        )

    return findings


def _finding(
    *,
    path: Path,
    gate_id: str,
    kind: str,
    code: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "severity": "critical",
        "code": code,
        "gate_id": gate_id,
        "kind": kind,
        "artifact_path": str(path),
        "summary": summary,
    }


def _contamination_marker(payload: dict[str, Any]) -> str | None:
    searchable = " ".join(
        item.lower()
        for item in (
            _text(payload.get("summary")),
            _text(payload.get("attempted_command")),
            *_string_list(payload.get("commands")),
            *_string_list(payload.get("source_refs")),
            *_string_list(payload.get("artifacts")),
        )
        if item is not None
    )
    for marker in _CONTAMINATION_MARKERS:
        if marker in searchable:
            return marker
    return None


def _claims_pr_merged(payload: dict[str, Any], *, kind: str) -> bool:
    if kind == "github_merge_truth":
        return True
    fact_state = _text(payload.get("fact_state"))
    if fact_state == "pr_merged":
        return True
    return _text(payload.get("summary")) is not None and "pr_merged" in (
        _text(payload.get("summary")) or ""
    )


def _has_merge_truth(payload: dict[str, Any]) -> bool:
    return (
        _text(payload.get("proof_level")) == "server_side_merge_proof"
        and payload.get("can_emit_pr_merged") is True
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
