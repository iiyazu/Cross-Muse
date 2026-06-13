from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.providers.god_cli_registry import (
    GodCliCapability,
    GodCliRegistration,
    GodCliRegistry,
    ProofLevel,
)
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionRecord

SCHEMA_VERSION = "xmuse.god_runtime_continuity.v1"


def build_selected_god_runtime_continuity_view(
    *,
    conversation_id: str,
    selections: Sequence[GodCliSelectionRecord],
    sessions: Sequence[GodSessionRecord],
    god_cli_registry: GodCliRegistry,
    now_utc: str | None = None,
    heartbeat_ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Build a read-only selected-GOD runtime continuity envelope."""
    conversation = _required_text(conversation_id, "conversation_id")
    now = _parse_utc(now_utc) or datetime.now(UTC)
    matching_selections = [
        selection for selection in selections if selection.conversation_id == conversation
    ]
    items: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    source_refs: list[str] = []
    source_authority: list[str] = ["god_cli_selection_store", "god_cli_registry"]

    for selection in matching_selections:
        registration = _registration_for_selection(god_cli_registry, selection)
        selection_ref = f"god_cli_selection:{selection.conversation_id}"
        registration_ref = (
            f"god_cli_registration:{registration.cli_id}"
            if registration is not None
            else f"god_cli_registration:{selection.cli_id}"
        )
        selected_sessions = _matching_sessions(
            conversation_id=conversation,
            registration=registration,
            selection=selection,
            sessions=sessions,
        )
        if selected_sessions:
            _append_unique(source_authority, "god_session_registry")
            for session in selected_sessions:
                item = _build_item(
                    selection=selection,
                    registration=registration,
                    session=session,
                    selection_ref=selection_ref,
                    registration_ref=registration_ref,
                    now=now,
                    heartbeat_ttl_seconds=heartbeat_ttl_seconds,
                )
                items.append(item)
                _extend_unique(source_refs, item["source_refs"])
                if item["waiting_reason"] is not None:
                    blockers.append(
                        {
                            "reason": item["waiting_reason"],
                            "source_refs": item["source_refs"],
                        }
                    )
            continue

        item = _missing_session_item(
            selection=selection,
            registration=registration,
            selection_ref=selection_ref,
            registration_ref=registration_ref,
        )
        items.append(item)
        _extend_unique(source_refs, item["source_refs"])
        blockers.append(
            {
                "reason": item["waiting_reason"],
                "source_refs": item["source_refs"],
            }
        )

    if not matching_selections:
        blockers.append(
            {
                "reason": "selected GOD CLI unavailable",
                "source_refs": [f"conversation:{conversation}"],
            }
        )
        source_refs.append(f"conversation:{conversation}")

    manual_gap_reason = _manual_gap_reason(items, blockers)
    proof_level = _view_proof_level(items, blockers)
    fact_state = "observed"
    if blockers:
        fact_state = "blocked"
    if not items:
        fact_state = "manual_gap"

    return {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "conversation_id": conversation,
        "source_authority": source_authority,
        "proof_level": proof_level,
        "fact_state": fact_state,
        "manual_gap_reason": manual_gap_reason,
        "source_refs": source_refs,
        "blockers": blockers,
        "items": items,
    }


def _build_item(
    *,
    selection: GodCliSelectionRecord,
    registration: GodCliRegistration | None,
    session: GodSessionRecord,
    selection_ref: str,
    registration_ref: str,
    now: datetime,
    heartbeat_ttl_seconds: int,
) -> dict[str, Any]:
    source_refs = [selection_ref, registration_ref, f"god_session:{session.god_session_id}"]
    provider_session_ready = bool(session.provider_session_id)
    if session.provider_session_id:
        source_refs.append(f"provider_session:{session.provider_session_id}")
    effective_session_status = _effective_session_status(
        session,
        provider_session_ready=provider_session_ready,
    )
    heartbeat_freshness = _heartbeat_freshness(
        session.last_heartbeat_at_utc,
        now=now,
        ttl_seconds=heartbeat_ttl_seconds,
    )
    if session.last_heartbeat_at_utc:
        source_refs.append(f"god_session_heartbeat:{session.god_session_id}")
    waiting_reason = _waiting_reason(
        registration=registration,
        session=session,
        effective_session_status=effective_session_status,
        provider_session_ready=provider_session_ready,
        heartbeat_freshness=heartbeat_freshness,
    )
    has_peer_god = _has_peer_god(registration)
    proof_level = _item_proof_level(
        registration=registration,
        provider_session_ready=provider_session_ready,
        waiting_reason=waiting_reason,
    )
    return {
        "god_id": session.agent_name,
        "cli_id": selection.cli_id,
        "selected": True,
        "role": session.role,
        "participant_id": session.participant_id,
        "provider_profile_ref": registration.provider_profile_ref
        if registration is not None
        else None,
        "provider_session_id": session.provider_session_id,
        "provider_session_kind": session.provider_session_kind,
        "provider_binding_status": session.provider_binding_status,
        "capability_scope": _capability_scope(registration),
        "allowed_speech_acts": list(registration.allowed_speech_acts)
        if registration is not None
        else [],
        "session_status": session.status,
        "effective_session_status": effective_session_status,
        "heartbeat_freshness": heartbeat_freshness,
        "last_heartbeat_at_utc": session.last_heartbeat_at_utc,
        "waiting_reason": waiting_reason,
        "proof_level": proof_level,
        "bounded": not has_peer_god,
        "peer_god_ready": bool(has_peer_god and provider_session_ready and waiting_reason is None),
        "provider_session_ready": provider_session_ready,
        "model": session.model,
        "feature_scope_id": session.feature_scope_id,
        "source_refs": source_refs,
        "selection": _selection_summary(selection),
    }


def _missing_session_item(
    *,
    selection: GodCliSelectionRecord,
    registration: GodCliRegistration | None,
    selection_ref: str,
    registration_ref: str,
) -> dict[str, Any]:
    reason = (
        "selected GOD CLI registration unavailable"
        if registration is None
        else "selected GOD CLI has no active session"
    )
    source_refs = [selection_ref, registration_ref]
    return {
        "god_id": None,
        "cli_id": selection.cli_id,
        "selected": True,
        "role": None,
        "participant_id": None,
        "provider_profile_ref": registration.provider_profile_ref
        if registration is not None
        else None,
        "provider_session_id": None,
        "provider_session_kind": None,
        "provider_binding_status": None,
        "capability_scope": _capability_scope(registration),
        "allowed_speech_acts": list(registration.allowed_speech_acts)
        if registration is not None
        else [],
        "session_status": "missing",
        "effective_session_status": "missing",
        "heartbeat_freshness": "unknown",
        "waiting_reason": reason,
        "proof_level": "manual_gap",
        "bounded": not _has_peer_god(registration),
        "peer_god_ready": False,
        "provider_session_ready": False,
        "model": None,
        "feature_scope_id": None,
        "source_refs": source_refs,
        "selection": _selection_summary(selection),
    }


def _registration_for_selection(
    registry: GodCliRegistry,
    selection: GodCliSelectionRecord,
) -> GodCliRegistration | None:
    try:
        return registry.get(selection.cli_id)
    except KeyError:
        return None


def _matching_sessions(
    *,
    conversation_id: str,
    registration: GodCliRegistration | None,
    selection: GodCliSelectionRecord,
    sessions: Sequence[GodSessionRecord],
) -> list[GodSessionRecord]:
    matches: list[GodSessionRecord] = []
    for session in sessions:
        if session.conversation_id != conversation_id:
            continue
        if session.agent_name == selection.cli_id:
            matches.append(session)
            continue
        if registration is not None and session.runtime == registration.command_family:
            matches.append(session)
    return sorted(matches, key=lambda item: item.god_session_id)


def _waiting_reason(
    *,
    registration: GodCliRegistration | None,
    session: GodSessionRecord,
    effective_session_status: str,
    provider_session_ready: bool,
    heartbeat_freshness: str,
) -> str | None:
    if registration is None:
        return "selected GOD CLI registration unavailable"
    if effective_session_status not in {
        "active",
        "ready",
        "running",
        "provider_bound_active",
    }:
        return f"GOD session status is {session.status}"
    if not provider_session_ready:
        return "provider session metadata unavailable"
    if heartbeat_freshness == "stale":
        return "GOD session heartbeat stale"
    if heartbeat_freshness == "invalid":
        return "GOD session heartbeat timestamp invalid"
    if GodCliCapability.PEER_GOD not in registration.capabilities:
        return "selected CLI lacks peer_god capability"
    return None


def _effective_session_status(
    session: GodSessionRecord,
    *,
    provider_session_ready: bool,
) -> str:
    if (
        session.status == "starting"
        and provider_session_ready
        and session.provider_binding_status == "active"
    ):
        return "provider_bound_active"
    return session.status


def _item_proof_level(
    *,
    registration: GodCliRegistration | None,
    provider_session_ready: bool,
    waiting_reason: str | None,
) -> ProofLevel:
    if registration is None:
        return "manual_gap"
    if not provider_session_ready:
        return "manual_gap"
    if waiting_reason == "selected GOD CLI registration unavailable":
        return "manual_gap"
    if waiting_reason in {
        "GOD session heartbeat stale",
        "GOD session heartbeat timestamp invalid",
    }:
        return "manual_gap"
    return registration.proof_level


def _view_proof_level(
    items: Sequence[dict[str, Any]],
    blockers: Sequence[dict[str, Any]],
) -> ProofLevel:
    if any(item.get("proof_level") == "manual_gap" for item in items):
        return "manual_gap"
    if blockers and not items:
        return "manual_gap"
    if items and all(item.get("proof_level") == "real_provider_proof" for item in items):
        return "real_provider_proof"
    return "contract_proof"


def _manual_gap_reason(
    items: Sequence[dict[str, Any]],
    blockers: Sequence[dict[str, Any]],
) -> str | None:
    for item in items:
        if item.get("proof_level") == "manual_gap":
            reason = item.get("waiting_reason")
            return reason if isinstance(reason, str) and reason.strip() else "manual gap"
    if not items and blockers:
        reason = blockers[0].get("reason")
        return reason if isinstance(reason, str) and reason.strip() else "manual gap"
    return None


def _has_peer_god(registration: GodCliRegistration | None) -> bool:
    return bool(registration and GodCliCapability.PEER_GOD in registration.capabilities)


def _capability_scope(registration: GodCliRegistration | None) -> list[str]:
    if registration is None:
        return []
    return [capability.value for capability in registration.capabilities]


def _selection_summary(selection: GodCliSelectionRecord) -> dict[str, str]:
    return {
        "selected_by": selection.selected_by,
        "audit_id": selection.audit_id,
        "selected_at_utc": selection.selected_at_utc,
        "proof_level": selection.proof_level,
    }


def _heartbeat_freshness(
    value: str | None,
    *,
    now: datetime,
    ttl_seconds: int,
) -> str:
    heartbeat_at = _parse_utc(value)
    if heartbeat_at is None:
        return "unknown" if value is None else "invalid"
    if ttl_seconds <= 0:
        return "fresh"
    if (now - heartbeat_at).total_seconds() <= ttl_seconds:
        return "fresh"
    return "stale"


def _parse_utc(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _extend_unique(items: list[str], values: Sequence[str]) -> None:
    for value in values:
        _append_unique(items, value)
