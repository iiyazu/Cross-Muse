from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-god-session-heartbeat",
        description="Record a guarded GOD session heartbeat in the durable registry.",
    )
    parser.add_argument("--god-session-id", required=True)
    parser.add_argument("--conversation-id")
    parser.add_argument("--participant-id")
    parser.add_argument("--status", default="active")
    parser.add_argument("--heartbeat-at-utc")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "god_sessions.json",
        help="Path to god_sessions.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "god-session-heartbeat.json",
        help="Path for the xmuse.god_session_heartbeat.v1 evidence envelope.",
    )
    args = parser.parse_args(argv)
    envelope = record_god_session_heartbeat(
        registry_path=args.registry,
        god_session_id=args.god_session_id,
        conversation_id=args.conversation_id,
        participant_id=args.participant_id,
        status=args.status,
        heartbeat_at_utc=args.heartbeat_at_utc,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": envelope["status"],
                "proof_level": envelope["proof_level"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if envelope["status"] == "ok" else 2


def record_god_session_heartbeat(
    *,
    registry_path: str | Path,
    god_session_id: str,
    conversation_id: str | None = None,
    participant_id: str | None = None,
    status: str | None = "active",
    heartbeat_at_utc: str | None = None,
) -> dict[str, object]:
    registry = GodSessionRegistry(registry_path)
    heartbeat = heartbeat_at_utc or _utc_now()
    clean_status = _text(status) or "active"
    try:
        record = registry.get(god_session_id)
    except KeyError:
        return _blocked_envelope(
            god_session_id=god_session_id,
            reason="unknown_god_session",
            heartbeat_at_utc=heartbeat,
        )
    mismatch = _guard_mismatch(
        record,
        conversation_id=conversation_id,
        participant_id=participant_id,
    )
    if mismatch is not None:
        return _blocked_envelope(
            god_session_id=god_session_id,
            reason=mismatch,
            heartbeat_at_utc=heartbeat,
            record=record,
        )
    updated = registry.record_heartbeat(
        god_session_id,
        heartbeat_at_utc=heartbeat,
        status=clean_status,
    )
    return _ok_envelope(updated)


def _ok_envelope(record: GodSessionRecord) -> dict[str, object]:
    source_refs = [f"god_session:{record.god_session_id}"]
    if record.conversation_id:
        source_refs.append(f"conversation:{record.conversation_id}")
    if record.participant_id:
        source_refs.append(f"participant:{record.participant_id}")
    return {
        "schema_version": "xmuse.god_session_heartbeat.v1",
        "generated_at": _utc_now(),
        "status": "ok",
        "proof_level": "contract_proof",
        "fact_state": "observed",
        "source_authority": "god_session_registry",
        "god_session_id": record.god_session_id,
        "conversation_id": record.conversation_id,
        "participant_id": record.participant_id,
        "session_status": record.status,
        "heartbeat_at_utc": record.last_heartbeat_at_utc,
        "source_refs": source_refs,
        "target_refs": [f"god_runtime_continuity:{record.conversation_id}"]
        if record.conversation_id
        else [],
        "blocked_reason": None,
        "next_action": None,
    }


def _blocked_envelope(
    *,
    god_session_id: str,
    reason: str,
    heartbeat_at_utc: str,
    record: GodSessionRecord | None = None,
) -> dict[str, object]:
    source_refs = [f"god_session:{god_session_id}"]
    if record is not None and record.conversation_id:
        source_refs.append(f"conversation:{record.conversation_id}")
    if record is not None and record.participant_id:
        source_refs.append(f"participant:{record.participant_id}")
    return {
        "schema_version": "xmuse.god_session_heartbeat.v1",
        "generated_at": _utc_now(),
        "status": "blocked",
        "proof_level": "manual_gap",
        "fact_state": "blocked",
        "source_authority": "god_session_registry",
        "god_session_id": god_session_id,
        "conversation_id": record.conversation_id if record is not None else None,
        "participant_id": record.participant_id if record is not None else None,
        "session_status": record.status if record is not None else None,
        "heartbeat_at_utc": heartbeat_at_utc,
        "source_refs": source_refs,
        "target_refs": [f"god_runtime_continuity:{record.conversation_id}"]
        if record is not None and record.conversation_id
        else [],
        "blocked_reason": reason,
        "next_action": (
            "Use a known GOD session id and matching conversation/participant "
            "guards, then retry heartbeat capture from the live session."
        ),
    }


def _guard_mismatch(
    record: GodSessionRecord,
    *,
    conversation_id: str | None,
    participant_id: str | None,
) -> str | None:
    clean_conversation = _text(conversation_id)
    clean_participant = _text(participant_id)
    if clean_conversation is not None and record.conversation_id != clean_conversation:
        return "conversation_guard_mismatch"
    if clean_participant is not None and record.participant_id != clean_participant:
        return "participant_guard_mismatch"
    return None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
