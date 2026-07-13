"""Durable action ordering and conservative delivery holds for native Codex."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from xmuse_core.agents.codex_native_contract import (
    CAPABILITY_IDS,
    CodexNativeContractError,
    normalize_native_safe_request,
)
from xmuse_core.chat.room_database import FRONTEND_EVENT_PROOF_BOUNDARY, RoomDatabase

HoldState = Literal[
    "reconciling",
    "accepting",
    "goal_active",
    "turn_active",
    "session_conflict",
    "native_unavailable",
]
ActionStatus = Literal["requested", "applying", "applied", "rejected", "failed"]
_HOLD_STATES = frozenset(
    {
        "reconciling",
        "accepting",
        "goal_active",
        "turn_active",
        "session_conflict",
        "native_unavailable",
    }
)
_FINAL_ACTION_STATUSES = frozenset({"applied", "rejected", "failed"})
_ACK_KEYS = frozenset(
    {"native_method", "acknowledged", "native_error_code", "observed_guard", "event_count"}
)
_MAX_JSON_BYTES = 8 * 1024


class RoomCodexBridgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RoomCodexBridgeStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def begin_reconcile(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        session_guard: str,
        reason_code: str = "codex_native_reconcile_required",
    ) -> dict[str, object]:
        guard = _guard(session_guard, required=True)
        assert guard is not None
        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            _participant(conn, conversation_id, participant_id)
            prior = conn.execute(
                "select * from room_codex_delivery_holds where participant_id = ?",
                (participant_id,),
            ).fetchone()
            revision = int(prior["hold_revision"]) + 1 if prior is not None else 1
            next_control_seq = int(prior["next_control_seq"]) if prior is not None else 0
            created_at = str(prior["created_at"]) if prior is not None else stamp
            conn.execute(
                """insert into room_codex_delivery_holds
                   (participant_id, conversation_id, hold_revision, next_control_seq, state,
                    session_guard, reason_code, created_at, updated_at)
                   values (?, ?, ?, ?, 'reconciling', ?, ?, ?, ?)
                   on conflict(participant_id) do update set
                       conversation_id = excluded.conversation_id,
                       hold_revision = excluded.hold_revision,
                       state = 'reconciling', session_guard = excluded.session_guard,
                       goal_guard = null, settings_guard = null, active_turn_guard = null,
                       reason_code = excluded.reason_code, observed_at = null,
                       updated_at = excluded.updated_at""",
                (
                    participant_id,
                    conversation_id,
                    revision,
                    next_control_seq,
                    guard,
                    reason_code,
                    created_at,
                    stamp,
                ),
            )
            _append_projection_event(conn, conversation_id, participant_id, "hold", stamp)
            row = _hold_row(conn, participant_id)
            conn.commit()
        return _hold_view(row)

    def apply_native_snapshot(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        expected_session_guard: str,
        state: HoldState,
        goal_guard: str | None,
        settings_guard: str | None,
        active_turn_guard: str | None,
        reason_code: str | None = None,
    ) -> dict[str, object]:
        if state not in _HOLD_STATES:
            raise RoomCodexBridgeError("codex_native_hold_state_invalid")
        expected = _guard(expected_session_guard, required=True)
        assert expected is not None
        goal = _guard(goal_guard)
        settings = _guard(settings_guard)
        turn = _guard(active_turn_guard)
        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            row = _hold_row(conn, participant_id)
            if row["conversation_id"] != conversation_id:
                raise RoomCodexBridgeError("codex_native_participant_room_mismatch")
            if row["session_guard"] != expected:
                raise RoomCodexBridgeError("codex_native_session_guard_conflict")
            conn.execute(
                """update room_codex_delivery_holds
                   set hold_revision = hold_revision + 1, state = ?, goal_guard = ?,
                       settings_guard = ?, active_turn_guard = ?, reason_code = ?,
                       observed_at = ?, updated_at = ? where participant_id = ?""",
                (state, goal, settings, turn, reason_code, stamp, stamp, participant_id),
            )
            _append_projection_event(conn, conversation_id, participant_id, "snapshot", stamp)
            updated = _hold_row(conn, participant_id)
            conn.commit()
        return _hold_view(updated)

    def request_action(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        capability_id: str,
        safe_request: Mapping[str, object],
        client_action_id: str,
        expected_session_guard: str,
        expected_goal_guard: str | None = None,
        expected_settings_guard: str | None = None,
        expected_turn_guard: str | None = None,
        confirmed_pending_observations: bool = False,
        operator_identity: str = "operator:local",
    ) -> tuple[dict[str, object], bool]:
        if capability_id not in CAPABILITY_IDS:
            raise RoomCodexBridgeError("codex_native_capability_forbidden")
        action_key = _identifier(client_action_id, "codex_native_client_action_invalid", 128)
        operator = _identifier(operator_identity, "codex_native_operator_invalid", 128)
        session = _guard(expected_session_guard, required=True)
        assert session is not None
        goal = _guard(expected_goal_guard)
        settings = _guard(expected_settings_guard)
        turn = _guard(expected_turn_guard)
        if not isinstance(confirmed_pending_observations, bool):
            raise RoomCodexBridgeError("codex_native_confirmation_invalid")
        _require_capability_guards(
            capability_id,
            goal=goal,
            settings=settings,
            turn=turn,
        )
        raw_request_json = _bounded_json(dict(safe_request), "codex_native_request_too_large")
        fingerprint = _digest(
            {
                "conversation_id": conversation_id,
                "participant_id": participant_id,
                "capability_id": capability_id,
                "request": json.loads(raw_request_json),
                "session_guard": session,
                "goal_guard": goal,
                "settings_guard": settings,
                "turn_guard": turn,
                "confirmed_pending_observations": confirmed_pending_observations,
            }
        )
        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            _participant(conn, conversation_id, participant_id)
            prior = conn.execute(
                """select * from room_codex_bridge_actions
                   where participant_id = ? and operator_identity = ?
                     and client_action_id = ?""",
                (participant_id, operator, action_key),
            ).fetchone()
            if prior is not None:
                if prior["request_fingerprint"] != fingerprint:
                    raise RoomCodexBridgeError("codex_native_action_idempotency_conflict")
                conn.commit()
                return _action_view(prior, include_request=False), False
            try:
                normalized_request = normalize_native_safe_request(capability_id, safe_request)
            except CodexNativeContractError as exc:
                raise RoomCodexBridgeError(exc.code) from exc
            request_json = _bounded_json(
                normalized_request, "codex_native_request_too_large"
            )
            hold = _hold_row(conn, participant_id)
            _verify_guards(hold, session=session, goal=goal, settings=settings, turn=turn)
            _verify_capability_hold(hold, capability_id)
            if capability_id == "goal_set":
                _verify_goal_set_observation_policy(
                    conn,
                    participant_id,
                    confirmed_pending_observations=confirmed_pending_observations,
                )
            if capability_id in {"turn_steer", "turn_interrupt"} and _has_live_delivery(
                conn, participant_id
            ):
                raise RoomCodexBridgeError("codex_native_room_turn_conflict")
            control_seq = int(hold["next_control_seq"]) + 1
            action_id = f"codex_action_{uuid.uuid4().hex}"
            conn.execute(
                """insert into room_codex_bridge_actions
                   (action_id, conversation_id, participant_id, control_seq,
                    client_action_id, operator_identity, request_fingerprint,
                    capability_id, expected_session_guard, expected_goal_guard,
                    expected_settings_guard, expected_turn_guard, request_json,
                    status, requested_at, updated_at)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?)""",
                (
                    action_id,
                    conversation_id,
                    participant_id,
                    control_seq,
                    action_key,
                    operator,
                    fingerprint,
                    capability_id,
                    session,
                    goal,
                    settings,
                    turn,
                    request_json,
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                """update room_codex_delivery_holds
                   set next_control_seq = ?, hold_revision = hold_revision + 1,
                       state = 'reconciling', reason_code = 'codex_native_action_pending',
                       updated_at = ? where participant_id = ?""",
                (control_seq, stamp, participant_id),
            )
            _append_projection_event(conn, conversation_id, action_id, "action", stamp)
            row = _action_row(conn, action_id)
            conn.commit()
        return _action_view(row, include_request=False), True

    def claim_next_action(self, *, runner_generation: str) -> dict[str, object] | None:
        generation = _identifier(runner_generation, "codex_native_runner_generation_invalid", 128)
        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """select candidate.* from room_codex_bridge_actions candidate
                   where candidate.status = 'requested' and not exists (
                       select 1 from room_codex_bridge_actions active
                       where active.participant_id = candidate.participant_id
                         and active.status = 'applying'
                   ) and not exists (
                       select 1 from room_codex_bridge_actions prior
                       where prior.participant_id = candidate.participant_id
                         and prior.status in ('requested','applying')
                         and prior.control_seq < candidate.control_seq
                   ) order by candidate.requested_at, candidate.participant_id,
                              candidate.control_seq limit 1"""
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            changed = conn.execute(
                """update room_codex_bridge_actions
                   set status = 'applying', runner_generation = ?, applying_at = ?,
                       updated_at = ? where action_id = ? and status = 'requested'""",
                (generation, stamp, stamp, row["action_id"]),
            ).rowcount
            if changed != 1:
                conn.rollback()
                return None
            conn.execute(
                """update room_codex_delivery_holds
                   set hold_revision = hold_revision + 1, state = 'reconciling',
                       reason_code = 'codex_native_action_applying', updated_at = ?
                   where participant_id = ?""",
                (stamp, row["participant_id"]),
            )
            claimed = _action_row(conn, str(row["action_id"]))
            conn.commit()
        return _action_view(claimed, include_request=True)

    def fence_interrupted_actions(self) -> int:
        """Fail in-flight native calls whose result cannot be proved after restart.

        Replaying an App Server mutation is unsafe: a completed ``turn/start`` may
        already have emitted output even when xmuse crashed before recording its ack.
        The new Runner reconciles current native state and requires a new operator
        action instead of guessing or duplicating the mutation.
        """

        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """select action_id, conversation_id, participant_id
                   from room_codex_bridge_actions
                   where status = 'applying' order by requested_at, action_id"""
            ).fetchall()
            for row in rows:
                conn.execute(
                    """update room_codex_bridge_actions
                       set status = 'failed', reason_code = ?, completed_at = ?,
                           updated_at = ? where action_id = ? and status = 'applying'""",
                    (
                        "codex_native_action_result_unknown",
                        stamp,
                        stamp,
                        row["action_id"],
                    ),
                )
                _append_projection_event(
                    conn,
                    str(row["conversation_id"]),
                    str(row["action_id"]),
                    "action",
                    stamp,
                )
                conn.execute(
                    """update room_codex_delivery_holds
                       set hold_revision = hold_revision + 1, state = 'reconciling',
                           reason_code = 'codex_native_reconcile_required', updated_at = ?
                       where participant_id = ?""",
                    (stamp, row["participant_id"]),
                )
            conn.commit()
        return len(rows)

    def get_hold(self, participant_id: str) -> dict[str, object] | None:
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            row = conn.execute(
                "select * from room_codex_delivery_holds where participant_id = ?",
                (participant_id,),
            ).fetchone()
        return _hold_view(row) if row is not None else None

    def participant_has_unfinished_action(self, participant_id: str) -> bool:
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            row = conn.execute(
                """select 1 from room_codex_bridge_actions
                   where participant_id = ? and status in ('requested','applying') limit 1""",
                (participant_id,),
            ).fetchone()
        return row is not None

    def list_room_holds(self, conversation_id: str) -> list[dict[str, object]]:
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_codex_delivery_holds
                   where conversation_id = ? order by participant_id""",
                (conversation_id,),
            ).fetchall()
        return [_hold_view(row) for row in rows]

    def list_room_actions(
        self,
        conversation_id: str,
        *,
        participant_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise RoomCodexBridgeError("codex_native_action_limit_invalid")
        params: list[object] = [conversation_id]
        participant_clause = ""
        if participant_id is not None:
            participant_clause = " and participant_id = ?"
            params.append(participant_id)
        params.append(limit)
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            rows = conn.execute(
                f"""select * from room_codex_bridge_actions
                    where conversation_id = ?{participant_clause}
                    order by control_seq desc, requested_at desc limit ?""",  # noqa: S608
                params,
            ).fetchall()
        return [_action_view(row, include_request=False) for row in rows]

    def room_participant_work_counts(
        self, conversation_id: str
    ) -> dict[str, dict[str, int]]:
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            rows = conn.execute(
                """select p.participant_id,
                          coalesce(sum(case when o.status <> 'completed' then 1 else 0 end), 0)
                              as unresolved_count,
                          coalesce(sum(case when a.state in ('claimed','delivering')
                                                or a.provider_phase in
                                                   ('ensure_started','bound','cleanup_pending')
                                                or a.recovery_state in
                                                   ('fenced','cleanup_pending')
                                            then 1 else 0 end), 0) as active_attempt_count
                   from participants p
                   left join room_observations o
                     on o.participant_id = p.participant_id
                   left join room_observation_attempts a
                     on a.attempt_id = o.current_attempt_id
                   where p.conversation_id = ? and p.status = 'active'
                     and p.cli_kind = 'codex' and p.role <> 'init'
                   group by p.participant_id order by p.participant_id""",
                (conversation_id,),
            ).fetchall()
        return {
            str(row["participant_id"]): {
                "unresolved_count": int(row["unresolved_count"]),
                "active_attempt_count": int(row["active_attempt_count"]),
            }
            for row in rows
        }

    def complete_action(
        self,
        *,
        action_id: str,
        runner_generation: str,
        status: Literal["applied", "rejected", "failed"],
        reason_code: str | None,
        ack_summary: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if status not in _FINAL_ACTION_STATUSES:
            raise RoomCodexBridgeError("codex_native_action_status_invalid")
        action = _identifier(action_id, "codex_native_action_invalid", 128)
        generation = _identifier(runner_generation, "codex_native_runner_generation_invalid", 128)
        summary = _ack_summary(ack_summary)
        stamp = _timestamp()
        with RoomDatabase(self._path).connect() as conn:
            conn.execute("begin immediate")
            row = _action_row(conn, action)
            if row["status"] in _FINAL_ACTION_STATUSES:
                conn.commit()
                return _action_view(row, include_request=False)
            if row["status"] != "applying" or row["runner_generation"] != generation:
                raise RoomCodexBridgeError("codex_native_action_claim_lost")
            conn.execute(
                """update room_codex_bridge_actions set status = ?, reason_code = ?,
                       ack_summary_json = ?, completed_at = ?, updated_at = ?
                   where action_id = ? and status = 'applying' and runner_generation = ?""",
                (status, reason_code, summary, stamp, stamp, action, generation),
            )
            _append_projection_event(conn, str(row["conversation_id"]), action, "action", stamp)
            updated = _action_row(conn, action)
            conn.commit()
        return _action_view(updated, include_request=False)

    def participant_accepts_delivery(self, participant_id: str) -> bool:
        with RoomDatabase(self._path).connect(readonly=True) as conn:
            row = conn.execute(
                "select state from room_codex_delivery_holds where participant_id = ?",
                (participant_id,),
            ).fetchone()
        return row is not None and row["state"] == "accepting"


def opaque_guard(*parts: str) -> str:
    canonical = "\0".join(parts).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _participant(
    conn: sqlite3.Connection, conversation_id: str, participant_id: str
) -> sqlite3.Row:
    row = conn.execute(
        "select * from participants where participant_id = ?", (participant_id,)
    ).fetchone()
    if row is None:
        raise RoomCodexBridgeError("codex_native_participant_not_found")
    if row["conversation_id"] != conversation_id:
        raise RoomCodexBridgeError("codex_native_participant_room_mismatch")
    if row["cli_kind"] != "codex" or row["status"] != "active":
        raise RoomCodexBridgeError("codex_native_participant_unavailable")
    return row


def _verify_guards(
    hold: sqlite3.Row,
    *,
    session: str,
    goal: str | None,
    settings: str | None,
    turn: str | None,
) -> None:
    if hold["state"] in {"session_conflict", "native_unavailable"} or (
        hold["state"] == "reconciling"
        and hold["reason_code"] != "codex_native_action_pending"
    ):
        raise RoomCodexBridgeError("codex_native_session_conflict")
    for column, expected in (
        ("session_guard", session),
        ("goal_guard", goal),
        ("settings_guard", settings),
        ("active_turn_guard", turn),
    ):
        if expected is not None and hold[column] != expected:
            raise RoomCodexBridgeError(f"codex_native_{column}_conflict")


def _require_capability_guards(
    capability_id: str,
    *,
    goal: str | None,
    settings: str | None,
    turn: str | None,
) -> None:
    if capability_id in {"goal_set", "goal_pause", "goal_resume", "goal_clear"} and goal is None:
        raise RoomCodexBridgeError("codex_native_goal_guard_required")
    if capability_id == "settings_update" and settings is None:
        raise RoomCodexBridgeError("codex_native_settings_guard_required")
    if capability_id in {"turn_steer", "turn_interrupt"} and turn is None:
        raise RoomCodexBridgeError("codex_native_turn_guard_required")


def _verify_capability_hold(hold: sqlite3.Row, capability_id: str) -> None:
    state = str(hold["state"])
    if capability_id in {"turn_steer", "turn_interrupt"}:
        if hold["active_turn_guard"] is None:
            raise RoomCodexBridgeError("codex_native_turn_conflict")
        return
    if capability_id == "goal_pause":
        if state != "goal_active":
            raise RoomCodexBridgeError("codex_native_goal_conflict")
        return
    if capability_id in {"goal_get", "models_list"}:
        return
    if state != "accepting":
        raise RoomCodexBridgeError("codex_native_action_state_conflict")


def _verify_goal_set_observation_policy(
    conn: sqlite3.Connection,
    participant_id: str,
    *,
    confirmed_pending_observations: bool,
) -> None:
    if _has_live_delivery(conn, participant_id):
        raise RoomCodexBridgeError("codex_native_delivery_conflict")
    pending = conn.execute(
        """select 1 from room_observations
           where participant_id = ? and status <> 'completed' limit 1""",
        (participant_id,),
    ).fetchone()
    if pending is not None and not confirmed_pending_observations:
        raise RoomCodexBridgeError(
            "codex_native_pending_observations_confirmation_required"
        )


def _has_live_delivery(conn: sqlite3.Connection, participant_id: str) -> bool:
    active = conn.execute(
        """select 1 from room_observation_attempts
           where participant_id = ? and (
               state in ('claimed','delivering','cancel_requested','cancel_pending')
               or provider_phase in ('ensure_started','bound','cleanup_pending')
               or recovery_state in ('fenced','cleanup_pending')
           ) limit 1""",
        (participant_id,),
    ).fetchone()
    return active is not None


def _hold_row(conn: sqlite3.Connection, participant_id: str) -> sqlite3.Row:
    row = conn.execute(
        "select * from room_codex_delivery_holds where participant_id = ?",
        (participant_id,),
    ).fetchone()
    if row is None:
        raise RoomCodexBridgeError("codex_native_reconcile_required")
    return row


def _action_row(conn: sqlite3.Connection, action_id: str) -> sqlite3.Row:
    row = conn.execute(
        "select * from room_codex_bridge_actions where action_id = ?", (action_id,)
    ).fetchone()
    if row is None:
        raise RoomCodexBridgeError("codex_native_action_not_found")
    return row


def _hold_view(row: sqlite3.Row) -> dict[str, object]:
    return {
        "participant_id": row["participant_id"],
        "conversation_id": row["conversation_id"],
        "hold_revision": int(row["hold_revision"]),
        "state": row["state"],
        "session_guard": row["session_guard"],
        "goal_guard": row["goal_guard"],
        "settings_guard": row["settings_guard"],
        "active_turn_guard": row["active_turn_guard"],
        "reason_code": row["reason_code"],
        "observed_at": row["observed_at"],
        "updated_at": row["updated_at"],
    }


def _action_view(row: sqlite3.Row, *, include_request: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "action_id": row["action_id"],
        "conversation_id": row["conversation_id"],
        "participant_id": row["participant_id"],
        "control_seq": int(row["control_seq"]),
        "client_action_id": row["client_action_id"],
        "capability_id": row["capability_id"],
        "expected_session_guard": row["expected_session_guard"],
        "expected_goal_guard": row["expected_goal_guard"],
        "expected_settings_guard": row["expected_settings_guard"],
        "expected_turn_guard": row["expected_turn_guard"],
        "status": row["status"],
        "reason_code": row["reason_code"],
        "ack_summary": json.loads(row["ack_summary_json"]) if row["ack_summary_json"] else None,
        "requested_at": row["requested_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }
    if include_request:
        result["safe_request"] = json.loads(row["request_json"])
    return result


def _append_projection_event(
    conn: sqlite3.Connection,
    conversation_id: str,
    resource_ref: str,
    change_type: str,
    stamp: str,
) -> None:
    seq = int(
        conn.execute(
            "select coalesce(max(seq), 0) + 1 from chat_frontend_events where conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
    )
    conn.execute(
        """insert into chat_frontend_events
           (event_id, conversation_id, seq, event_type, resource_ref, source_authority,
            source_ref, payload_json, created_at, projection_only, proof_boundary)
           values (?, ?, ?, 'projection.changed', ?, 'chat.db:room_codex_bridge', ?, ?, ?, 1, ?)""",
        (
            f"frontend_event_{uuid.uuid4().hex}",
            conversation_id,
            seq,
            resource_ref,
            resource_ref,
            _bounded_json({"change_type": change_type}, "codex_native_event_invalid"),
            stamp,
            FRONTEND_EVENT_PROOF_BOUNDARY,
        ),
    )


def _ack_summary(value: Mapping[str, object] | None) -> str | None:
    if value is None:
        return None
    if set(value) - _ACK_KEYS:
        raise RoomCodexBridgeError("codex_native_ack_summary_invalid")
    if any(not isinstance(item, (str, int, bool, type(None))) for item in value.values()):
        raise RoomCodexBridgeError("codex_native_ack_summary_invalid")
    return _bounded_json(dict(value), "codex_native_ack_summary_invalid")


def _guard(value: object, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise RoomCodexBridgeError("codex_native_guard_invalid")
    return value


def _identifier(value: object, code: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise RoomCodexBridgeError(code)
    clean = value.strip()
    if not clean or len(clean.encode("utf-8")) > maximum:
        raise RoomCodexBridgeError(code)
    return clean


def _bounded_json(value: object, code: str) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RoomCodexBridgeError(code) from exc
    if len(encoded.encode("utf-8")) > _MAX_JSON_BYTES:
        raise RoomCodexBridgeError(code)
    return encoded


def _digest(value: object) -> str:
    encoded = _bounded_json(value, "codex_native_request_invalid").encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "RoomCodexBridgeError",
    "RoomCodexBridgeStore",
    "opaque_guard",
]
