from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def capture_memoryos_live_release_gate(
    *,
    artifact_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    payload, load_error = _load_artifact(artifact)
    gate = build_memoryos_live_release_gate(
        payload,
        artifact_path=artifact,
        load_error=load_error,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate


def build_memoryos_live_release_gate(
    trace_artifact: dict[str, Any] | None,
    *,
    artifact_path: str | Path,
    load_error: str | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    if trace_artifact is None:
        return _blocked_gate(
            summary=load_error or "MemoryOS Lite trace artifact is unavailable.",
            artifact_path=artifact,
            source_refs=[],
            proof_level="manual_gap",
        )

    source_refs = _source_refs(trace_artifact)
    schema_version = _text(trace_artifact.get("schema_version"))
    if schema_version != "xmuse.memoryos_lite_trace.v1":
        return _blocked_gate(
            summary=(
                "MemoryOS Lite trace artifact schema_version must be "
                "xmuse.memoryos_lite_trace.v1."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    proof_level = _text(trace_artifact.get("proof_level"))
    if proof_level != "live_service_proof":
        return _blocked_gate(
            summary=(
                "MemoryOS Lite live gate requires live_service_proof; got "
                f"{proof_level or '<missing>'}."
            ),
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    namespace_uri = _text(trace_artifact.get("namespace_uri"))
    session_id = _text(trace_artifact.get("session_id"))
    if namespace_uri is None or not namespace_uri.startswith("memory://"):
        return _blocked_gate(
            summary="MemoryOS Lite live trace requires a memory:// namespace_uri.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )
    if session_id is None:
        return _blocked_gate(
            summary="MemoryOS Lite live trace requires a session_id.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    trace_events = _dicts(trace_artifact.get("trace_events"))
    if not trace_events:
        return _blocked_gate(
            summary="MemoryOS Lite live trace requires non-empty trace events.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )
    if any(_is_fake_or_fixture_event(event) for event in trace_events):
        return _blocked_gate(
            summary="MemoryOS Lite live trace rejects fake, fixture, or local trace events.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    estimated_tokens = trace_artifact.get("estimated_tokens")
    if estimated_tokens is not None and (
        isinstance(estimated_tokens, bool)
        or not isinstance(estimated_tokens, int)
        or estimated_tokens < 0
    ):
        return _blocked_gate(
            summary="MemoryOS Lite live trace estimated_tokens must be a non-negative integer.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    blockers = _dicts(trace_artifact.get("blockers"))
    if _text(trace_artifact.get("fact_state")) == "blocked" or blockers:
        return _blocked_gate(
            summary=f"MemoryOS Lite live trace has {len(blockers) or 1} unresolved blockers.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="live_service_proof",
            next_action="Resolve MemoryOS Lite trace blockers before release readiness.",
        )

    return _ok_gate(
        summary=(
            "MemoryOS Lite live trace captured live service proof for "
            f"{namespace_uri} session {session_id}."
        ),
        artifact_path=artifact,
        source_refs=source_refs,
    )


def _load_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"MemoryOS Lite trace artifact does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"MemoryOS Lite trace artifact could not be read: {exc}."
    if not isinstance(payload, dict):
        return None, "MemoryOS Lite trace artifact must be a JSON object."
    return payload, None


def _ok_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
) -> dict[str, Any]:
    return _gate(
        status="ok",
        proof_level="live_service_proof",
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action="Attach this MemoryOS Lite live gate to release readiness.",
    )


def _blocked_gate(
    *,
    summary: str,
    artifact_path: Path,
    source_refs: list[str],
    proof_level: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    return _gate(
        status="blocked",
        proof_level=proof_level,
        summary=summary,
        artifact_path=artifact_path,
        source_refs=source_refs,
        next_action=next_action
        or (
            "Run a live MemoryOS Lite create/ingest/build-context/trace capture "
            "and write a live trace artifact."
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
        "gate_id": "live-memoryos",
        "kind": "live_memoryos",
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "memoryos",
        "summary": summary,
        "attempted_command": "uv run xmuse-memoryos-live-gate-capture",
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [str(artifact_path)],
        "generated_at": _utc_now(),
    }


def _source_refs(trace_artifact: dict[str, Any]) -> list[str]:
    refs = _string_list(trace_artifact.get("source_refs"))
    namespace_uri = _text(trace_artifact.get("namespace_uri"))
    session_id = _text(trace_artifact.get("session_id"))
    for event in _dicts(trace_artifact.get("trace_events")):
        metadata = _dict(event.get("metadata"))
        refs.extend(_string_list(metadata.get("xmuse_source_refs")))
    if namespace_uri is not None:
        refs.append(f"memoryos:namespace:{namespace_uri}")
    if session_id is not None:
        refs.append(f"memoryos:session:{session_id}")
    return _dedupe(refs)


def _is_fake_or_fixture_event(event: dict[str, Any]) -> bool:
    kind = str(event.get("kind") or "").lower()
    source = str(event.get("source") or "").lower()
    return any(
        marker in f"{kind} {source}"
        for marker in ("fake", "fixture", "local_only", "contract")
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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
