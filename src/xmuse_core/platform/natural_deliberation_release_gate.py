from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def capture_natural_deliberation_release_gate(
    *,
    artifact_path: str | Path,
    output_path: str | Path,
    god_runtime_path: str | Path | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    payload, load_error = _load_artifact(artifact)
    god_runtime_payload = None
    god_runtime_load_error = None
    god_runtime_artifact = None
    if god_runtime_path is not None:
        god_runtime_artifact = Path(god_runtime_path)
        god_runtime_payload, god_runtime_load_error = _load_artifact(god_runtime_artifact)
    gate = build_natural_deliberation_release_gate(
        payload,
        artifact_path=artifact,
        load_error=load_error,
        god_runtime_continuity=god_runtime_payload,
        god_runtime_path=god_runtime_artifact,
        god_runtime_load_error=god_runtime_load_error,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate


def build_natural_deliberation_release_gate(
    transcript_artifact: dict[str, Any] | None,
    *,
    artifact_path: str | Path,
    load_error: str | None = None,
    god_runtime_continuity: dict[str, Any] | None = None,
    god_runtime_path: str | Path | None = None,
    god_runtime_load_error: str | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    runtime_artifact = Path(god_runtime_path) if god_runtime_path is not None else None
    if transcript_artifact is None:
        return _blocked_gate(
            summary=load_error or "Natural deliberation transcript artifact is unavailable.",
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=[],
            proof_level="manual_gap",
        )

    source_refs = _source_refs(transcript_artifact)
    schema_version = _text(transcript_artifact.get("schema_version"))
    if schema_version != "xmuse.operator_transcript.v1":
        return _blocked_gate(
            summary=(
                "Natural deliberation transcript schema_version must be "
                "xmuse.operator_transcript.v1."
            ),
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    proof_level = _text(transcript_artifact.get("proof_level"))
    natural_deliberation = transcript_artifact.get("natural_deliberation")
    if proof_level != "real_provider_proof" or natural_deliberation is not True:
        return _blocked_gate(
            summary=(
                "Natural GOD deliberation requires real_provider_proof and "
                "natural_deliberation=true; got "
                f"proof_level={proof_level or '<missing>'}, "
                f"natural_deliberation={natural_deliberation!r}."
            ),
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    messages = _messages(transcript_artifact.get("messages"))
    if not messages:
        return _blocked_gate(
            summary="Natural GOD deliberation transcript has no structured messages.",
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    god_ids = _ordered_unique(_text(message.get("god_id")) for message in messages)
    if len(god_ids) < 2:
        return _blocked_gate(
            summary="Natural GOD deliberation requires at least two distinct GOD participants.",
            artifact_path=artifact,
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    missing_runtime_metadata = _missing_runtime_metadata(messages, god_ids)
    if missing_runtime_metadata:
        return _blocked_gate(
            summary=(
                "Natural GOD deliberation is missing real provider session metadata for "
                f"{', '.join(missing_runtime_metadata)}."
            ),
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=source_refs,
            proof_level="manual_gap",
        )

    runtime_gate = _selected_god_runtime_gate(
        god_ids=god_ids,
        runtime=god_runtime_continuity,
        runtime_artifact=runtime_artifact,
        load_error=god_runtime_load_error,
    )
    if runtime_gate is not None:
        return _blocked_gate(
            summary=runtime_gate["summary"],
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=_dedupe([*source_refs, *runtime_gate["source_refs"]]),
            proof_level="manual_gap",
            next_action=runtime_gate["next_action"],
        )

    blockers = _blockers(transcript_artifact.get("blockers"))
    if _text(transcript_artifact.get("fact_state")) == "blocked" or blockers:
        return _blocked_gate(
            summary=f"Natural GOD deliberation has {len(blockers) or 1} unresolved blockers.",
            artifact_path=artifact,
            extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
            source_refs=source_refs,
            proof_level="real_provider_proof",
            next_action="Resolve transcript blockers before blueprint freeze or release.",
        )

    return _ok_gate(
        summary=(
            "Natural GOD deliberation transcript captured real provider proof from "
            f"{len(god_ids)} GOD participants."
        ),
        artifact_path=artifact,
        extra_artifacts=[runtime_artifact] if runtime_artifact is not None else [],
        source_refs=source_refs,
    )


def _load_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"Natural deliberation transcript does not exist: {path}."
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Natural deliberation transcript could not be read: {exc}."
    if not isinstance(payload, dict):
        return None, "Natural deliberation transcript must be a JSON object."
    return payload, None


def _ok_gate(
    *,
    summary: str,
    artifact_path: Path,
    extra_artifacts: list[Path] | None = None,
    source_refs: list[str],
) -> dict[str, Any]:
    return _gate(
        status="ok",
        proof_level="real_provider_proof",
        summary=summary,
        artifact_path=artifact_path,
        extra_artifacts=extra_artifacts or [],
        source_refs=source_refs,
        next_action="Attach this natural deliberation gate to release readiness.",
    )


def _blocked_gate(
    *,
    summary: str,
    artifact_path: Path,
    extra_artifacts: list[Path] | None = None,
    source_refs: list[str],
    proof_level: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    return _gate(
        status="blocked",
        proof_level=proof_level,
        summary=summary,
        artifact_path=artifact_path,
        extra_artifacts=extra_artifacts or [],
        source_refs=source_refs,
        next_action=next_action
        or (
            "Capture a natural multi-GOD transcript with real provider proof, "
            "provider session metadata, and no unresolved blockers."
        ),
    )


def _gate(
    *,
    status: str,
    proof_level: str,
    summary: str,
    artifact_path: Path,
    extra_artifacts: list[Path],
    source_refs: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": "natural-god-deliberation",
        "kind": "natural_deliberation",
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": summary,
        "attempted_command": "uv run xmuse-natural-deliberation-gate-capture",
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [str(path) for path in [artifact_path, *extra_artifacts]],
        "generated_at": _utc_now(),
    }


def _selected_god_runtime_gate(
    *,
    god_ids: list[str],
    runtime: dict[str, Any] | None,
    runtime_artifact: Path | None,
    load_error: str | None,
) -> dict[str, Any] | None:
    if runtime_artifact is None:
        return {
            "summary": (
                "Natural GOD deliberation requires selected GOD runtime continuity "
                "before release readiness can accept the transcript."
            ),
            "source_refs": [],
            "next_action": (
                "Capture selected GOD runtime continuity with "
                "xmuse-god-runtime-continuity-capture and rerun the natural "
                "deliberation release gate."
            ),
        }
    if runtime is None:
        return {
            "summary": load_error or "Selected GOD runtime continuity artifact is unavailable.",
            "source_refs": [],
            "next_action": (
                "Capture selected GOD runtime continuity before accepting natural "
                "multi-GOD transcript evidence."
            ),
        }
    if _text(runtime.get("schema_version")) != "xmuse.god_runtime_continuity.v1":
        return {
            "summary": (
                "Selected GOD runtime continuity schema_version must be "
                "xmuse.god_runtime_continuity.v1."
            ),
            "source_refs": _string_list(runtime.get("source_refs")),
            "next_action": "Regenerate selected GOD runtime continuity evidence.",
        }
    source_refs = _god_runtime_source_refs(runtime)
    items = _messages(runtime.get("items"))
    by_god = {_text(item.get("god_id")): item for item in items if _text(item.get("god_id"))}
    missing = [god_id for god_id in god_ids if god_id not in by_god]
    if missing:
        return {
            "summary": (
                "Selected GOD runtime continuity is missing transcript GODs: "
                f"{', '.join(missing)}."
            ),
            "source_refs": source_refs,
            "next_action": "Capture runtime continuity for every transcript GOD.",
        }
    blocked: list[str] = []
    for god_id in god_ids:
        item = by_god[god_id]
        if item.get("peer_god_ready") is not True:
            reason = _text(item.get("waiting_reason"))
            if reason is None and item.get("bounded") is True:
                reason = "selected CLI lacks peer_god capability"
            if reason is None and item.get("provider_session_ready") is not True:
                reason = "provider session metadata unavailable"
            blocked.append(f"{god_id} ({reason or 'runtime not peer-GOD ready'})")
    if blocked:
        return {
            "summary": (
                "Natural GOD deliberation selected GOD runtime is not peer-GOD ready for "
                f"{', '.join(blocked)}."
            ),
            "source_refs": source_refs,
            "next_action": (
                "Select only peer-GOD-ready runtime participants or attach stronger "
                "provider/runtime proof."
            ),
        }
    return None


def _god_runtime_source_refs(runtime: dict[str, Any]) -> list[str]:
    refs = _string_list(runtime.get("source_refs"))
    for item in _messages(runtime.get("items")):
        refs.extend(_string_list(item.get("source_refs")))
    return _dedupe(refs)


def _source_refs(transcript_artifact: dict[str, Any]) -> list[str]:
    refs = _string_list(transcript_artifact.get("source_refs"))
    conversation_id = _text(transcript_artifact.get("conversation_id"))
    if conversation_id is not None:
        refs.append(f"conversation:{conversation_id}")
    messages = _messages(transcript_artifact.get("messages"))
    for god_id in _ordered_unique(_text(message.get("god_id")) for message in messages):
        refs.append(f"god:{god_id}")
    for provider_id in _ordered_unique(_text(message.get("provider_id")) for message in messages):
        refs.append(f"provider:{provider_id}")
    return _dedupe(refs)


def _missing_runtime_metadata(
    messages: list[dict[str, Any]],
    god_ids: list[str],
) -> list[str]:
    missing: list[str] = []
    for god_id in god_ids:
        participant_messages = [
            message for message in messages if _text(message.get("god_id")) == god_id
        ]
        has_provider = any(_text(message.get("provider_id")) for message in participant_messages)
        has_session = any(_text(message.get("session_id")) for message in participant_messages)
        if not has_provider or not has_session:
            missing.append(god_id)
    return missing


def _messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _blockers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _ordered_unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is not None and value not in result:
            result.append(value)
    return result


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
