"""Durable, attempt-local Agent Skill decisions for Room delivery."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_skill_schema import (
    create_room_skill_decision_schema as create_room_skill_decision_schema,
)
from xmuse_core.skills.models import (
    RoomSkillActivation,
    SkillDecision,
    SkillDecisionRecord,
)


class RoomSkillDecisionError(ValueError):
    """Stable failure raised by the Room Skill decision authority."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise RoomSkillDecisionError("room_skill_binding_lost")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _selection_values(selection: SkillDecision) -> tuple[Any, ...]:
    return (
        selection.selector_version,
        selection.participant_role_snapshot,
        selection.selection_input_sha256,
        selection.decision,
        selection.skill_id,
        selection.skill_version,
        selection.skill_content_sha256,
        selection.skill_instructions_sha256,
        selection.catalog_sha256,
        selection.selection_reason,
        _json(list(selection.matched_terms)),
    )


def _record(row: sqlite3.Row) -> SkillDecisionRecord:
    try:
        matched_terms = tuple(json.loads(row["matched_terms_json"]))
    except (TypeError, ValueError) as exc:
        raise RoomSkillDecisionError("room_skill_binding_conflict") from exc
    return SkillDecisionRecord(
        attempt_id=row["attempt_id"],
        selection=SkillDecision(
            selector_version=row["selector_version"],
            participant_role_snapshot=row["participant_role_snapshot"],
            selection_input_sha256=row["selection_input_sha256"],
            decision=row["decision"],
            skill_id=row["skill_id"],
            skill_version=row["skill_version"],
            skill_content_sha256=row["skill_content_sha256"],
            skill_instructions_sha256=row["skill_instructions_sha256"],
            catalog_sha256=row["catalog_sha256"],
            selection_reason=row["selection_reason"],
            matched_terms=matched_terms,
        ),
        context_payload_sha256=row["context_payload_sha256"],
        context_submitted_at=row["context_submitted_at"],
    )


def _row(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from room_attempt_skill_decisions where attempt_id = ?", (attempt_id,)
    ).fetchone()


def _authority(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
    row = conn.execute(
        """select t.*, o.status observation_status, o.control_state,
                  o.current_attempt_id, o.lease_token, o.expires_at observation_expires_at,
                  p.role participant_role, p.cli_kind participant_cli_kind,
                  a.payload_json activity_payload_json
           from room_observation_attempts t
           join room_observations o on o.observation_id = t.observation_id
           join participants p on p.participant_id = o.participant_id
           join room_activities a on a.activity_id = o.activity_id
           where t.attempt_id = ?""",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise RoomSkillDecisionError("room_skill_binding_lost")
    return row


def _assert_live_authority(row: sqlite3.Row, *, attempt_id: str, now: datetime) -> None:
    expires_at = row["observation_expires_at"]
    if (
        row["current_attempt_id"] != attempt_id
        or row["observation_status"] != "claimed"
        or row["participant_cli_kind"] != "codex"
        or row["control_state"] != "active"
        or row["state"] not in {"claimed", "delivering"}
        or not row["lease_token"]
        or not expires_at
        or row["lease_token_digest"] != _digest(row["lease_token"])
        or _parse_timestamp(expires_at) <= now.astimezone(UTC)
    ):
        raise RoomSkillDecisionError("room_skill_binding_lost")


def _source_text(row: sqlite3.Row) -> str:
    try:
        payload = json.loads(row["activity_payload_json"])
    except (TypeError, ValueError) as exc:
        raise RoomSkillDecisionError("room_skill_binding_lost") from exc
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, str):
        raise RoomSkillDecisionError("room_skill_binding_lost")
    return content


def _event(conn: sqlite3.Connection, *, observation_id: str, change: str, stamp: str) -> None:
    # Import here to keep this additive module independent from control initialization.
    from xmuse_core.chat.room_controls import _record_projection_event_conn

    _record_projection_event_conn(
        conn,
        descriptor={
            "event_type": "projection.changed",
            "resource_ref": f"room-observation:{observation_id}",
            "source_authority": "room_attempt_skill_decisions",
            "source_ref": observation_id,
            "payload": {"observation_id": observation_id, "change": change},
            "projection_only": True,
            "proof_boundary": "derived_from_room_skill_decision_authority",
        },
        client_action_id=None,
        now=stamp,
    )


class RoomAttemptSkillDecisionStore:
    """Transaction-owning API for decision binding and context receipts."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    def bind_for_attempt(
        self, *, attempt_id: str, catalog: Any, now: datetime
    ) -> SkillDecisionRecord:
        stamp = _timestamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            authority = _authority(conn, attempt_id)
            _assert_live_authority(authority, attempt_id=attempt_id, now=now)
            selection = catalog.select(
                participant_role=authority["participant_role"],
                source_text=_source_text(authority),
            )
            if selection.participant_role_snapshot != authority["participant_role"]:
                raise RoomSkillDecisionError("room_skill_binding_conflict")
            values = _selection_values(selection)
            existing = _row(conn, attempt_id)
            if existing is not None:
                if (
                    tuple(
                        existing[key]
                        for key in (
                            "selector_version",
                            "participant_role_snapshot",
                            "selection_input_sha256",
                            "decision",
                            "skill_id",
                            "skill_version",
                            "skill_content_sha256",
                            "skill_instructions_sha256",
                            "catalog_sha256",
                            "selection_reason",
                            "matched_terms_json",
                        )
                    )
                    != values
                ):
                    raise RoomSkillDecisionError("room_skill_binding_conflict")
                conn.commit()
                return _record(existing)
            conn.execute(
                """insert into room_attempt_skill_decisions
                   (attempt_id, selector_version, participant_role_snapshot,
                    selection_input_sha256, decision, skill_id, skill_version,
                    skill_content_sha256, skill_instructions_sha256, catalog_sha256,
                    selection_reason, matched_terms_json, context_payload_sha256,
                    context_submitted_at, created_at, updated_at)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, ?, ?)""",
                (attempt_id, *values, stamp, stamp),
            )
            _event(
                conn,
                observation_id=authority["observation_id"],
                change="attempt.skill_decided",
                stamp=stamp,
            )
            result = _row(conn, attempt_id)
            assert result is not None
            conn.commit()
            return _record(result)

    def get(self, attempt_id: str) -> SkillDecisionRecord | None:
        with self._connect() as conn:
            row = _row(conn, attempt_id)
            return None if row is None else _record(row)

    def assert_activation(
        self, *, attempt_id: str, activation: RoomSkillActivation | None
    ) -> SkillDecisionRecord:
        with self._connect() as conn:
            row = _row(conn, attempt_id)
            if row is None:
                raise RoomSkillDecisionError("room_skill_binding_lost")
            record = _record(row)
        selection = record.selection
        if selection.decision == "none":
            if activation is not None:
                raise RoomSkillDecisionError("room_skill_activation_mismatch")
            return record
        if activation is None or (
            activation.skill_id,
            activation.version,
            activation.content_sha256,
            activation.instructions_sha256,
            activation.catalog_sha256,
            activation.selection_reason,
            activation.matched_terms,
            f"sha256:{hashlib.sha256(activation.instructions.encode('utf-8')).hexdigest()}",
        ) != (
            selection.skill_id,
            selection.skill_version,
            selection.skill_content_sha256,
            selection.skill_instructions_sha256,
            selection.catalog_sha256,
            selection.selection_reason,
            selection.matched_terms,
            selection.skill_instructions_sha256,
        ):
            raise RoomSkillDecisionError("room_skill_activation_mismatch")
        return record

    def mark_context_submitted(
        self, *, attempt_id: str, payload_sha256: str, now: datetime
    ) -> SkillDecisionRecord:
        if not isinstance(payload_sha256, str) or not payload_sha256:
            raise RoomSkillDecisionError("room_skill_context_receipt_conflict")
        stamp = _timestamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            authority = _authority(conn, attempt_id)
            _assert_live_authority(authority, attempt_id=attempt_id, now=now)
            if authority["state"] != "delivering":
                raise RoomSkillDecisionError("room_skill_binding_lost")
            row = _row(conn, attempt_id)
            if row is None:
                raise RoomSkillDecisionError("room_skill_binding_lost")
            if row["context_payload_sha256"] is not None:
                if row["context_payload_sha256"] != payload_sha256:
                    raise RoomSkillDecisionError("room_skill_context_receipt_conflict")
                conn.commit()
                return _record(row)
            conn.execute(
                """update room_attempt_skill_decisions
                   set context_payload_sha256 = ?, context_submitted_at = ?, updated_at = ?
                   where attempt_id = ?""",
                (payload_sha256, stamp, stamp, attempt_id),
            )
            _event(
                conn,
                observation_id=authority["observation_id"],
                change="attempt.skill_context_submitted",
                stamp=stamp,
            )
            result = _row(conn, attempt_id)
            assert result is not None
            conn.commit()
            return _record(result)
