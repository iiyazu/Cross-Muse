from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


def export_real_provider_runtime_soak_artifact(
    *,
    chat_db_path: str | Path,
    registry_path: str | Path,
    conversation_id: str,
    fresh_inbox_item_id: str,
    resume_inbox_item_id: str,
    runtime_backend: str,
    transport: str,
    output_path: str | Path,
    run_id: str | None = None,
    source_refs: Sequence[str] = (),
) -> dict[str, Any]:
    traces = {
        trace["inbox_item_id"]: trace
        for trace in PeerTurnLatencyTraceStore(chat_db_path).list_recent(
            conversation_id,
            limit=200,
        )
    }
    participants = {
        participant.participant_id: participant
        for participant in ParticipantStore(chat_db_path).list_by_conversation(conversation_id)
    }
    sessions = _sessions_by_participant(registry_path, conversation_id)
    fresh = traces.get(fresh_inbox_item_id)
    resume = traces.get(resume_inbox_item_id)
    blockers: list[dict[str, object]] = []
    if _is_fake_or_local(runtime_backend) or _is_fake_or_local(transport):
        blockers.append(
            _blocker(
                "fake_or_local_runtime_label",
                source_refs=[f"conversation:{conversation_id}"],
            )
        )
    if fresh is None:
        blockers.append(_blocker("fresh_provider_turn_trace_missing", source_refs=[]))
    if resume is None:
        blockers.append(_blocker("resume_provider_turn_trace_missing", source_refs=[]))

    fresh_session = _session_for_trace(fresh, sessions) if fresh is not None else None
    resume_session = _session_for_trace(resume, sessions) if resume is not None else None
    fresh_provider_session_id = fresh_session.provider_session_id if fresh_session else None
    resume_provider_session_id = resume_session.provider_session_id if resume_session else None
    if fresh is not None and not fresh_provider_session_id:
        blockers.append(
            _blocker(
                "provider_session_metadata_missing",
                source_refs=[f"peer_latency:{fresh_inbox_item_id}"],
            )
        )
    if resume is not None and not resume_provider_session_id:
        blockers.append(
            _blocker(
                "provider_session_metadata_missing",
                source_refs=[f"peer_latency:{resume_inbox_item_id}"],
            )
        )
    if (
        fresh_provider_session_id
        and resume_provider_session_id
        and fresh_provider_session_id != resume_provider_session_id
    ):
        blockers.append(
            _blocker(
                "provider_session_not_reused",
                source_refs=[
                    f"peer_latency:{fresh_inbox_item_id}",
                    f"peer_latency:{resume_inbox_item_id}",
                ],
            )
        )

    turns = []
    for phase, trace in (("fresh", fresh), ("resume", resume)):
        if trace is None:
            continue
        session = _session_for_trace(trace, sessions)
        participant = _participant_for_trace(trace, participants)
        source_ref = f"peer_latency:{trace['inbox_item_id']}"
        if trace.get("delivery_mode") != "mcp_writeback":
            blockers.append(_blocker("provider_turn_not_mcp_writeback", source_refs=[source_ref]))
        if trace.get("degraded_reason") is not None:
            blockers.append(_blocker("provider_turn_degraded", source_refs=[source_ref]))
        turns.append(
            {
                "turn_id": str(trace["id"]),
                "phase": phase,
                "delivery_mode": str(trace.get("delivery_mode") or ""),
                "degraded_reason": trace.get("degraded_reason"),
                "provider_id": _provider_id(participant, session),
                "runtime_backend": runtime_backend,
                "transport": transport,
                "provider_session_id": session.provider_session_id if session else "",
                "stage_timings": trace.get("stage_timings") or {},
            }
        )

    provider_session_id = fresh_provider_session_id or resume_provider_session_id or ""
    provider_id = _provider_id(
        _participant_for_trace(fresh, participants) if fresh is not None else None,
        fresh_session or resume_session,
    )
    artifact_refs = _artifact_source_refs(
        conversation_id=conversation_id,
        source_refs=source_refs,
        sessions=[fresh_session, resume_session],
        traces=[fresh, resume],
    )
    artifact: dict[str, Any] = {
        "schema_version": "xmuse.real_provider_runtime.v1",
        "proof_level": "manual_gap" if blockers else "real_provider_proof",
        "fact_state": "blocked" if blockers else "observed",
        "run_id": run_id or f"provider-runtime-{conversation_id}",
        "conversation_id": conversation_id,
        "source_refs": artifact_refs,
        "provider_runtime": {
            "provider_id": provider_id,
            "runtime_backend": runtime_backend,
            "transport": transport,
            "provider_session_id": provider_session_id,
            "mcp_writeback": bool(
                fresh
                and resume
                and fresh.get("delivery_mode") == "mcp_writeback"
                and resume.get("delivery_mode") == "mcp_writeback"
            ),
        },
        "restart_resume": {
            "fresh_provider_session_id": fresh_provider_session_id or "",
            "resumed_provider_session_id": resume_provider_session_id or "",
            "provider_session_reused": bool(
                fresh_provider_session_id
                and resume_provider_session_id
                and fresh_provider_session_id == resume_provider_session_id
            ),
        },
        "turns": turns,
        "blockers": _dedupe_blockers(blockers),
        "captured_at": _utc_now(),
    }
    _write_json(Path(output_path), artifact)
    return artifact


def _sessions_by_participant(
    registry_path: str | Path,
    conversation_id: str,
) -> dict[str, GodSessionRecord]:
    sessions: dict[str, GodSessionRecord] = {}
    for session in GodSessionRegistry(registry_path).list():
        if session.conversation_id != conversation_id or not session.participant_id:
            continue
        sessions[session.participant_id] = session
    return sessions


def _session_for_trace(
    trace: Mapping[str, Any] | None,
    sessions: Mapping[str, GodSessionRecord],
) -> GodSessionRecord | None:
    if trace is None:
        return None
    participant_id = trace.get("participant_id")
    if not isinstance(participant_id, str):
        return None
    return sessions.get(participant_id)


def _participant_for_trace(
    trace: Mapping[str, Any] | None,
    participants: Mapping[str, Participant],
) -> Participant | None:
    if trace is None:
        return None
    participant_id = trace.get("participant_id")
    if not isinstance(participant_id, str):
        return None
    return participants.get(participant_id)


def _provider_id(participant: Participant | None, session: GodSessionRecord | None) -> str:
    if participant is not None:
        return participant.provider_id.value
    if session is not None and session.runtime:
        return "codex" if session.runtime == "codex" else session.runtime
    return ""


def _artifact_source_refs(
    *,
    conversation_id: str,
    source_refs: Sequence[str],
    sessions: Sequence[GodSessionRecord | None],
    traces: Sequence[Mapping[str, Any] | None],
) -> list[str]:
    refs = [
        f"chat:conversation:{conversation_id}",
        *[str(ref) for ref in source_refs if str(ref).strip()],
    ]
    for session in sessions:
        if session is not None:
            refs.append(f"god_session:{session.god_session_id}")
    for trace in traces:
        if trace is not None:
            refs.append(f"peer_latency:{trace['inbox_item_id']}")
    return _dedupe(refs)


def _blocker(reason: str, *, source_refs: Sequence[str]) -> dict[str, object]:
    return {
        "reason": reason,
        "source_refs": _dedupe([str(ref) for ref in source_refs if str(ref).strip()]),
    }


def _dedupe_blockers(blockers: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for blocker in blockers:
        key = json.dumps(blocker, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(blocker)
    return result


def _is_fake_or_local(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("fake", "fixture", "local", "stdout"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["export_real_provider_runtime_soak_artifact"]
