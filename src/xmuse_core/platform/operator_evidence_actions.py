from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ProofLevel = Literal[
    "contract_proof",
    "fake_runtime_proof",
    "live_service_proof",
    "server_side_enforcement_proof",
    "server_side_merge_proof",
    "real_provider_proof",
    "manual_gap",
]
ActionStatus = Literal["ok", "partial", "manual_gap"]

SPEECH_ACTS = {
    "propose",
    "ask",
    "challenge",
    "object",
    "vote",
    "decide",
    "handoff",
    "evidence",
    "retract",
}


@dataclass(frozen=True)
class EvidenceActionResult:
    action: str
    status: ActionStatus
    proof_level: ProofLevel
    fact_state: str
    conversation_id: str | None = None
    source_refs: list[str] = field(default_factory=list)
    target_refs: list[str] = field(default_factory=list)
    artifact_path: str | None = None
    manual_gap_reason: str | None = None
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(default_factory=lambda: _utcnow())

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def export_deliberation_transcript(
    *,
    conversation_id: str,
    messages: list[dict[str, Any]],
    artifact_path: Path | None = None,
    proof_level: str = "contract_proof",
    natural_deliberation: bool = False,
) -> EvidenceActionResult:
    rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    source_refs: list[str] = []
    target_refs: list[str] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        envelope = _message_envelope(message)
        speech_act = _speech_act(envelope)
        if speech_act is None:
            continue
        message_id = _text(message.get("id") or message.get("message_id"))
        row_source_refs = _refs(envelope, "source_refs", "source_ref")
        row_target_refs = _refs(envelope, "target_refs", "target_ref")
        if message_id is not None:
            _append_unique(source_refs, f"message:{message_id}")
        for ref in row_source_refs:
            _append_unique(source_refs, ref)
        for ref in row_target_refs:
            _append_unique(target_refs, ref)

        blocking = _is_blocking(envelope)
        row = {
            "message_id": message_id,
            "conversation_id": _text(message.get("conversation_id")) or conversation_id,
            "god_id": _text(envelope.get("god_id")) or _text(message.get("god_id")),
            "provider_id": _text(envelope.get("provider_id")) or _text(message.get("provider_id")),
            "author": _text(message.get("author")),
            "speech_act": speech_act,
            "decision_scope": _text(envelope.get("decision_scope")),
            "source_refs": row_source_refs,
            "target_refs": row_target_refs,
            "blocking": blocking,
            "created_at": _text(message.get("created_at")),
        }
        for metadata_key in ("cli_id", "provider_profile", "session_id"):
            metadata_value = _text(envelope.get(metadata_key)) or _text(
                message.get(metadata_key)
            )
            if metadata_value is not None:
                row[metadata_key] = metadata_value
        rows.append(row)
        if blocking:
            blockers.append(
                {
                    "message_id": message_id,
                    "reason": _blocker_reason(envelope, message),
                    "target_refs": row_target_refs,
                }
            )

    if not rows:
        return EvidenceActionResult(
            action="transcript_export",
            status="manual_gap",
            proof_level="manual_gap",
            fact_state="manual_gap",
            conversation_id=conversation_id,
            manual_gap_reason="structured deliberation transcript unavailable",
            summary="No structured deliberation messages were available to export.",
        )

    normalized_proof = _normalize_proof_level(proof_level)
    fact_state = "blocked" if blockers else "observed"
    artifact_path_text = None
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "schema_version": "xmuse.operator_transcript.v1",
            "conversation_id": conversation_id,
            "proof_level": normalized_proof,
            "fact_state": fact_state,
            "natural_deliberation": natural_deliberation,
            "source_refs": source_refs,
            "target_refs": target_refs,
            "messages": rows,
            "blockers": blockers,
            "created_at": _utcnow(),
        }
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        artifact_path_text = str(artifact_path)

    return EvidenceActionResult(
        action="transcript_export",
        status="ok",
        proof_level=normalized_proof,
        fact_state=fact_state,
        conversation_id=conversation_id,
        source_refs=source_refs,
        target_refs=target_refs,
        artifact_path=artifact_path_text,
        summary=f"Exported {len(rows)} structured deliberation messages.",
        payload={"message_count": len(rows), "blocker_count": len(blockers)},
    )


def build_github_truth_action(
    *,
    conversation_id: str | None,
    github: dict[str, Any] | None,
) -> EvidenceActionResult:
    return _section_action(
        action="github_truth_load",
        conversation_id=conversation_id,
        section=github,
        default_gap="GitHub truth unavailable",
    )


def build_memory_trace_action(
    *,
    conversation_id: str | None,
    memory: dict[str, Any] | None,
) -> EvidenceActionResult:
    return _section_action(
        action="memory_trace_load",
        conversation_id=conversation_id,
        section=memory,
        default_gap="memory trace unavailable",
    )


def build_blocker_navigation_action(
    *,
    conversation_id: str | None,
    vision: dict[str, Any] | None,
) -> EvidenceActionResult:
    navigation_targets: list[dict[str, Any]] = []
    source_refs: list[str] = []
    target_refs: list[str] = []
    for section_name, kind in (
        ("blueprint_freeze", "blueprint"),
        ("execution", "lane"),
        ("deliberation", "deliberation"),
    ):
        section = vision.get(section_name) if isinstance(vision, dict) else None
        blockers = section.get("blockers") if isinstance(section, dict) else None
        if not isinstance(blockers, list):
            continue
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            blocker_source_refs = _list_refs(blocker.get("source_refs"))
            blocker_target_refs = _list_refs(blocker.get("target_refs"))
            for ref in blocker_source_refs:
                _append_unique(source_refs, ref)
            for ref in blocker_target_refs:
                _append_unique(target_refs, ref)
            navigation_targets.append(
                {
                    "kind": kind,
                    "label": _text(blocker.get("reason")) or _text(blocker.get("summary")) or kind,
                    "source_refs": blocker_source_refs,
                    "target_refs": blocker_target_refs,
                }
            )
    if not navigation_targets:
        return EvidenceActionResult(
            action="blocker_navigation",
            status="manual_gap",
            proof_level="manual_gap",
            fact_state="manual_gap",
            conversation_id=conversation_id,
            manual_gap_reason="blocker navigation targets unavailable",
            summary="No blocker target refs were available.",
        )
    return EvidenceActionResult(
        action="blocker_navigation",
        status="ok",
        proof_level="contract_proof",
        fact_state="observed",
        conversation_id=conversation_id,
        source_refs=source_refs,
        target_refs=target_refs,
        summary=f"Found {len(navigation_targets)} blocker navigation targets.",
        payload={"navigation_targets": navigation_targets},
    )


def _section_action(
    *,
    action: str,
    conversation_id: str | None,
    section: dict[str, Any] | None,
    default_gap: str,
) -> EvidenceActionResult:
    if not isinstance(section, dict):
        return EvidenceActionResult(
            action=action,
            status="manual_gap",
            proof_level="manual_gap",
            fact_state="manual_gap",
            conversation_id=conversation_id,
            manual_gap_reason=default_gap,
            summary=default_gap,
        )
    proof_level = _normalize_proof_level(section.get("proof_level"))
    fact_state = _text(section.get("fact_state")) or "observed"
    manual_gap_reason = _text(section.get("manual_gap_reason"))
    status: ActionStatus = "manual_gap" if proof_level == "manual_gap" else "ok"
    return EvidenceActionResult(
        action=action,
        status=status,
        proof_level=proof_level,
        fact_state=fact_state,
        conversation_id=conversation_id,
        source_refs=_list_refs(section.get("source_refs")),
        target_refs=_list_refs(section.get("target_refs")),
        manual_gap_reason=manual_gap_reason,
        summary=manual_gap_reason or f"{action} observed {fact_state}.",
        payload={key: value for key, value in section.items() if key not in _COMMON_SECTION_KEYS},
    )


_COMMON_SECTION_KEYS = {
    "proof_level",
    "fact_state",
    "source_refs",
    "target_refs",
    "manual_gap_reason",
}


def _message_envelope(message: dict[str, Any]) -> dict[str, Any]:
    envelope = message.get("envelope_json")
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except ValueError:
            envelope = {}
    return envelope if isinstance(envelope, dict) else {}


def _speech_act(envelope: dict[str, Any]) -> str | None:
    for key in ("speech_act", "act", "type"):
        value = _text(envelope.get(key))
        if value is not None and value.lower() in SPEECH_ACTS:
            return value.lower()
    return None


def _refs(envelope: dict[str, Any], plural_key: str, singular_key: str) -> list[str]:
    refs = _list_refs(envelope.get(plural_key))
    single = _text(envelope.get(singular_key))
    if single is not None:
        _append_unique(refs, single)
    return refs


def _list_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        text = _text(item)
        if text is not None:
            _append_unique(refs, text)
    return refs


def _is_blocking(envelope: dict[str, Any]) -> bool:
    if envelope.get("blocking") is True or envelope.get("blocked") is True:
        return True
    if _text(envelope.get("objection_level")) == "blocking":
        return True
    payload = envelope.get("payload")
    return isinstance(payload, dict) and (
        payload.get("blocking") is True or payload.get("blocked") is True
    )


def _blocker_reason(envelope: dict[str, Any], message: dict[str, Any]) -> str:
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        for key in ("summary", "reason", "message"):
            value = _text(payload.get(key))
            if value is not None:
                return value
    for key in ("summary", "reason", "content"):
        value = _text(envelope.get(key) or message.get(key))
        if value is not None:
            return value
    return "blocking deliberation item"


def _normalize_proof_level(value: Any) -> ProofLevel:
    text = _text(value)
    if text in {
        "contract_proof",
        "fake_runtime_proof",
        "live_service_proof",
        "server_side_enforcement_proof",
        "server_side_merge_proof",
        "real_provider_proof",
        "manual_gap",
    }:
        return text  # type: ignore[return-value]
    return "contract_proof"


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
