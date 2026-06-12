from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def capture_internal_review_release_gate(
    *,
    artifact_path: str | Path,
    output_path: str | Path,
    expected_head_sha: str,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    payload, load_error = _load_artifact(artifact)
    gate = build_internal_review_release_gate(
        payload,
        artifact_path=artifact,
        expected_head_sha=expected_head_sha,
        load_error=load_error,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate


def build_internal_review_release_gate(
    review_artifact: dict[str, Any] | None,
    *,
    artifact_path: str | Path,
    expected_head_sha: str,
    load_error: str | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    if review_artifact is None:
        return _blocked_gate(
            summary=load_error or "Internal review artifact is unavailable.",
            artifact_path=artifact,
            source_refs=[],
        )

    review_id = _text(review_artifact.get("review_id"))
    source_refs = _source_refs(review_artifact, review_id=review_id)
    schema_version = _text(review_artifact.get("schema_version"))
    if schema_version != "xmuse.internal_review.v1":
        return _blocked_gate(
            summary="Internal review artifact schema_version must be xmuse.internal_review.v1.",
            artifact_path=artifact,
            source_refs=source_refs,
        )

    reviewer = _text(review_artifact.get("reviewer"))
    if reviewer is None:
        return _blocked_gate(
            summary="Internal review artifact is missing reviewer.",
            artifact_path=artifact,
            source_refs=source_refs,
        )

    reviewed_head_sha = _text(review_artifact.get("reviewed_head_sha"))
    if reviewed_head_sha != expected_head_sha:
        return _blocked_gate(
            summary=(
                "Internal review artifact reviewed_head_sha mismatch: "
                f"expected {expected_head_sha}, got {reviewed_head_sha or '<missing>'}."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
        )

    decision = _text(review_artifact.get("decision"))
    if decision != "approved":
        return _blocked_gate(
            summary=f"Internal review decision is {decision or '<missing>'}, not approved.",
            artifact_path=artifact,
            source_refs=source_refs,
        )

    blocking_findings = _blocking_findings(review_artifact.get("findings"))
    if blocking_findings:
        return _blocked_gate(
            summary=f"Internal review has {len(blocking_findings)} open blocking review findings.",
            artifact_path=artifact,
            source_refs=source_refs,
        )

    return _ok_gate(
        summary=_text(review_artifact.get("summary")) or "Internal review approved.",
        artifact_path=artifact,
        source_refs=source_refs,
    )


def _load_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"Internal review artifact does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Internal review artifact could not be read: {exc}."
    if not isinstance(payload, dict):
        return None, "Internal review artifact must be a JSON object."
    return payload, None


def _ok_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
) -> dict[str, Any]:
    return _gate(
        status="ok",
        proof_level="internal_review_proof",
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action="Attach this verified internal review artifact to release readiness.",
    )


def _blocked_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
) -> dict[str, Any]:
    return _gate(
        status="blocked",
        proof_level="manual_gap",
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action=(
            "Produce a verified approved xmuse.internal_review.v1 artifact for "
            "the current head SHA."
        ),
    )


def _gate(
    *,
    status: str,
    proof_level: str,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": "internal-review",
        "kind": "internal_review",
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": summary,
        "attempted_command": "uv run xmuse-internal-review-gate-capture",
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [str(artifact_path)],
        "generated_at": _utc_now(),
    }


def _source_refs(review_artifact: dict[str, Any], *, review_id: str | None) -> list[str]:
    refs = _string_list(review_artifact.get("source_refs"))
    if review_id is not None:
        refs.append(f"internal_review:{review_id}")
    return _dedupe(refs)


def _blocking_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        severity = _text(item.get("severity"))
        status = _text(item.get("status")) or "open"
        if severity in {"critical", "important"} and status not in {"resolved", "closed"}:
            findings.append(item)
    return findings


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
