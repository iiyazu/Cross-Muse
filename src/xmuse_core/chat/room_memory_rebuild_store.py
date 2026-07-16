"""Durable operator ledger and authority reset for MemoryOS index rebuilds.

MemoryOS is derived state.  This module records the user authorization and the
resumable phase, while keeping Room activities, approvals, recall receipts, and
delivery audit authoritative in ``chat.db``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase

MEMORY_REBUILD_ACTION_SCHEMA = "room_memory_rebuild_action/v1"
MEMORY_REBUILD_PROOF_BOUNDARY = "operator_action_receipt_not_room_or_memory_index_authority"

MemoryRebuildStatus = Literal["requested", "applied", "rejected", "failed"]
MemoryRebuildPhase = Literal[
    "requested",
    "stopping",
    "stopped",
    "cache_cleared",
    "authority_reset",
    "restarting",
    "replaying",
    "complete",
]

_STATUSES = frozenset({"requested", "applied", "rejected", "failed"})
_PHASES = (
    "requested",
    "stopping",
    "stopped",
    "cache_cleared",
    "authority_reset",
    "restarting",
    "replaying",
    "complete",
)
_PHASE_INDEX = {phase: index for index, phase in enumerate(_PHASES)}
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")


class RoomMemoryRebuildError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bounded_text(value: object, code: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise RoomMemoryRebuildError(code)
    return value.strip()


def _safe_code(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else fallback


def _reset_result(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None

    def count(name: str) -> int:
        item = value.get(name)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            return 0
        return item

    return {
        "cache_cleared": value.get("cache_cleared") is True,
        "bindings_reset": count("bindings_reset"),
        "deliveries_reopened": count("deliveries_reopened"),
        "claimed_attempts_fenced": count("claimed_attempts_fenced"),
        "candidates_requeued": count("candidates_requeued"),
    }


def safe_memory_rebuild_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact browser-safe operator action receipt."""

    before = action.get("before")
    before = before if isinstance(before, Mapping) else {}
    after = action.get("after")
    after = after if isinstance(after, Mapping) else {}
    return {
        "schema_version": MEMORY_REBUILD_ACTION_SCHEMA,
        "action_id": action.get("action_id"),
        "client_action_id": action.get("client_action_id"),
        "status": action.get("status"),
        "phase": action.get("phase"),
        "reason_code": action.get("reason_code"),
        "before": {"state": before.get("state"), "code": before.get("code")},
        "after": {"state": after.get("state"), "code": after.get("code")},
        "result": _reset_result(action.get("result")),
        "requested_at": action.get("requested_at"),
        "applied_at": action.get("applied_at"),
        "proof_boundary": MEMORY_REBUILD_PROOF_BOUNDARY,
    }


def reset_room_memory_index_conn(
    conn: sqlite3.Connection,
    *,
    reason_code: str,
    stamp: str | None = None,
) -> dict[str, int]:
    """Reset only rebuildable MemoryOS bindings/outbox in a caller transaction."""

    if not conn.in_transaction:
        raise RoomMemoryRebuildError("room_memory_rebuild_transaction_required")
    reason = _safe_code(reason_code, "room_memory_rebuild_required")
    current = stamp or _timestamp()
    tables = {
        str(row[0]) for row in conn.execute("select name from sqlite_schema where type = 'table'")
    }
    required = {
        "room_memory_bindings",
        "room_memory_candidates",
        "room_memory_outbox",
        "room_memory_deliveries",
        "room_activities",
    }
    if not required.issubset(tables):
        return {
            "bindings_reset": 0,
            "deliveries_reopened": 0,
            "claimed_attempts_fenced": 0,
            "candidates_requeued": 0,
        }

    claimed_attempts = int(
        conn.execute(
            "select count(*) from room_memory_deliveries where state = 'claimed'"
        ).fetchone()[0]
    )
    conn.execute(
        """update room_memory_deliveries
           set state = 'failed', reason_code = ?,
               finished_at = coalesce(finished_at, ?), updated_at = ?
           where state = 'claimed'""",
        (reason, current, current),
    )
    bindings_reset = conn.execute(
        """update room_memory_bindings
           set session_id = null, session_state = 'unbound',
               session_request_id = null, session_retry_count = 0,
               session_retry_not_before = null,
               attachment_id = null, attachment_state = 'pending',
               attachment_request_id = null, attachment_retry_count = 0,
               attachment_retry_not_before = null,
               revision = revision + 1, updated_at = ?""",
        (current,),
    ).rowcount
    conn.execute(
        """insert or ignore into room_memory_outbox
           (outbox_id, conversation_id, activity_id, candidate_id, document_id,
            target_scope, state, attempt_count, created_at, updated_at)
           select 'memory_outbox_activity_' || activity_id, conversation_id, activity_id,
                  null, 'xmuse-room-activity-' || activity_id, 'room', 'pending', 0,
                  created_at, ?
             from room_activities where visibility = 'room'""",
        (current,),
    )
    conn.execute(
        """insert or ignore into room_memory_outbox
           (outbox_id, conversation_id, activity_id, candidate_id, document_id,
            target_scope, state, attempt_count, created_at, updated_at)
           select 'memory_outbox_candidate_' || candidate_id, conversation_id, null,
                  candidate_id, 'xmuse-room-memory-candidate-' || candidate_id,
                  target_scope, 'pending', 0, created_at, ?
             from room_memory_candidates where approval_state = 'approved'""",
        (current,),
    )
    deliveries_reopened = conn.execute(
        """update room_memory_outbox
           set state = 'pending', lease_owner = null, lease_token = null,
               acquired_at = null, expires_at = null, current_delivery_id = null,
               reason_code = ?, next_attempt_at = null, delivered_at = null,
               updated_at = ?
           where activity_id is not null
              or candidate_id in (
                   select candidate_id from room_memory_candidates
                   where approval_state = 'approved'
              )""",
        (reason, current),
    ).rowcount
    # Message ingest has its own idempotency ledger and must be reopened
    # independently from the archival-document outbox.  Older databases do not
    # have these additive tables, so restore remains backward compatible.
    if {
        "room_memory_message_outbox",
        "room_memory_message_deliveries",
    }.issubset(tables):
        conn.execute(
            """update room_memory_message_deliveries
               set state = 'failed', reason_code = ?,
                   finished_at = coalesce(finished_at, ?), updated_at = ?
               where state = 'claimed'""",
            (reason, current, current),
        )
        conn.execute(
            """update room_memory_message_outbox
               set state = 'pending', lease_owner = null, lease_token = null,
                   acquired_at = null, expires_at = null, current_delivery_id = null,
                   reason_code = ?, next_attempt_at = null, delivered_at = null,
                   updated_at = ?""",
            (reason, current),
        )
    conn.execute(
        """update room_memory_outbox
           set state = 'failed', lease_owner = null, lease_token = null,
               acquired_at = null, expires_at = null, current_delivery_id = null,
               reason_code = 'room_memory_candidate_not_approved',
               next_attempt_at = null, delivered_at = null, updated_at = ?
           where candidate_id in (
               select candidate_id from room_memory_candidates
               where approval_state <> 'approved'
           )""",
        (current,),
    )
    candidates_requeued = int(
        conn.execute(
            """select count(*) from room_memory_candidates
               where approval_state = 'approved'"""
        ).fetchone()[0]
    )
    conn.execute(
        """update room_memory_candidates
           set publish_state = case
                   when approval_state = 'approved' then 'queued'
                   else 'not_queued'
               end,
               reason_code = case
                   when approval_state = 'approved' then ?
                   else reason_code
               end,
               revision = revision + 1, updated_at = ?""",
        (reason, current),
    )
    return {
        "bindings_reset": int(bindings_reset),
        "deliveries_reopened": int(deliveries_reopened),
        "claimed_attempts_fenced": claimed_attempts,
        "candidates_requeued": candidates_requeued,
    }


class RoomMemoryRebuildActionStore:
    """Narrow durable ledger consumed by the Workroom manager."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def reserve(
        self,
        *,
        client_action_id: str,
        request_fingerprint: str,
        incident_guard: str,
        runtime_generation: str | None = None,
        before_state: str,
        before_code: str,
    ) -> tuple[dict[str, Any], bool]:
        client = _bounded_text(
            client_action_id, "room_memory_rebuild_client_action_invalid", maximum=200
        )
        fingerprint = _bounded_text(
            request_fingerprint, "room_memory_rebuild_fingerprint_invalid", maximum=128
        )
        guard = _bounded_text(incident_guard, "room_memory_rebuild_incident_invalid", maximum=200)
        generation = (
            _bounded_text(
                runtime_generation,
                "room_memory_rebuild_generation_invalid",
                maximum=200,
            )
            if runtime_generation is not None
            else None
        )
        stamp = _timestamp()
        with self._connect() as conn:
            conn.execute("begin immediate")
            existing = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client,),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    conn.rollback()
                    raise RoomMemoryRebuildError("room_memory_rebuild_idempotency_conflict")
                result = self._view(existing)
                conn.commit()
                return result, False
            inflight = conn.execute(
                """select action_id from room_memory_rebuild_actions
                   where status = 'requested' limit 1"""
            ).fetchone()
            status: MemoryRebuildStatus = "rejected" if inflight is not None else "requested"
            reason = "room_memory_rebuild_in_progress" if inflight is not None else None
            action_id = f"mra_{uuid.uuid4().hex}"
            conn.execute(
                """insert into room_memory_rebuild_actions
                   (action_id, client_action_id, operator_identity, request_fingerprint,
                    incident_guard, runtime_generation, status, phase, revision,
                    before_state, before_code,
                    reason_code, requested_at, applied_at, updated_at)
                   values (?, ?, 'operator:local', ?, ?, ?, ?, 'requested', 0,
                           ?, ?, ?, ?, ?, ?)""",
                (
                    action_id,
                    client,
                    fingerprint,
                    guard,
                    generation,
                    status,
                    _safe_code(before_state, "unknown"),
                    _safe_code(before_code, "memoryos_status_unverifiable"),
                    reason,
                    stamp,
                    stamp if status == "rejected" else None,
                    stamp,
                ),
            )
            row = conn.execute(
                "select * from room_memory_rebuild_actions where action_id = ?",
                (action_id,),
            ).fetchone()
            conn.commit()
        assert row is not None
        return self._view(row), True

    def get(self, client_action_id: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
        return self._view(row) if row is not None else None

    def latest(self) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   order by (status = 'requested') desc, requested_at desc, action_id desc
                   limit 1"""
            ).fetchone()
        return self._view(row) if row is not None else None

    def next_requested(self) -> dict[str, Any] | None:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   where status = 'requested'
                   order by requested_at, action_id limit 1"""
            ).fetchone()
        return self._view(row) if row is not None else None

    def advance(
        self,
        *,
        client_action_id: str,
        expected_phase: MemoryRebuildPhase,
        phase: MemoryRebuildPhase,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if expected_phase not in _PHASE_INDEX or phase not in _PHASE_INDEX:
            raise RoomMemoryRebuildError("room_memory_rebuild_phase_invalid")
        if _PHASE_INDEX[phase] != _PHASE_INDEX[expected_phase] + 1:
            raise RoomMemoryRebuildError("room_memory_rebuild_phase_invalid")
        stamp = _timestamp()
        encoded = (
            json.dumps(_reset_result(result), sort_keys=True, separators=(",", ":"))
            if result is not None
            else None
        )
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            if row is None:
                raise RoomMemoryRebuildError("room_memory_rebuild_action_not_found")
            if row["status"] != "requested" or row["phase"] != expected_phase:
                conn.rollback()
                return self._view(row)
            conn.execute(
                """update room_memory_rebuild_actions
                   set phase = ?, revision = revision + 1,
                       result_json = coalesce(?, result_json), updated_at = ?
                   where client_action_id = ? and status = 'requested' and phase = ?""",
                (phase, encoded, stamp, client_action_id, expected_phase),
            )
            updated = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return self._view(updated)

    def reset_authority(
        self,
        *,
        client_action_id: str,
        reason_code: str = "room_memory_operator_rebuild_required",
    ) -> dict[str, Any]:
        stamp = _timestamp()
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            if row is None:
                raise RoomMemoryRebuildError("room_memory_rebuild_action_not_found")
            if row["status"] != "requested" or row["phase"] != "cache_cleared":
                conn.rollback()
                return self._view(row)
            counts = reset_room_memory_index_conn(conn, reason_code=reason_code, stamp=stamp)
            prior_result = json.loads(row["result_json"]) if row["result_json"] else {}
            result = {**prior_result, **counts}
            conn.execute(
                """update room_memory_rebuild_actions
                   set phase = 'authority_reset', revision = revision + 1,
                       result_json = ?, updated_at = ?
                   where client_action_id = ? and status = 'requested'
                     and phase = 'cache_cleared'""",
                (
                    json.dumps(_reset_result(result), sort_keys=True, separators=(",", ":")),
                    stamp,
                    client_action_id,
                ),
            )
            updated = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return self._view(updated)

    def finish(
        self,
        *,
        client_action_id: str,
        status: Literal["applied", "rejected", "failed"],
        after_state: str,
        after_code: str,
        reason_code: str | None,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in _STATUSES - {"requested"}:
            raise RoomMemoryRebuildError("room_memory_rebuild_status_invalid")
        stamp = _timestamp()
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            if row is None:
                raise RoomMemoryRebuildError("room_memory_rebuild_action_not_found")
            if row["status"] != "requested":
                conn.commit()
                return self._view(row)
            prior_result = json.loads(row["result_json"]) if row["result_json"] else {}
            merged = {**prior_result, **dict(result or {})}
            encoded_result = (
                json.dumps(_reset_result(merged), sort_keys=True, separators=(",", ":"))
                if prior_result or result is not None
                else None
            )
            conn.execute(
                """update room_memory_rebuild_actions
                   set status = ?, phase = 'complete', revision = revision + 1,
                       after_state = ?, after_code = ?, reason_code = ?, result_json = ?,
                       applied_at = ?, updated_at = ?
                   where client_action_id = ? and status = 'requested'""",
                (
                    status,
                    _safe_code(after_state, "unknown"),
                    _safe_code(after_code, "memoryos_status_unverifiable"),
                    _safe_code(reason_code, "memoryos_rebuild_failed")
                    if reason_code is not None
                    else None,
                    encoded_result,
                    stamp,
                    stamp,
                    client_action_id,
                ),
            )
            updated = conn.execute(
                """select * from room_memory_rebuild_actions
                   where client_action_id = ?""",
                (client_action_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return self._view(updated)

    def replay_status(self) -> dict[str, int]:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """select
                     (select count(*) from room_memory_bindings
                       where session_state <> 'bound' or attachment_state <> 'attached')
                       as bindings_pending,
                     (select count(*) from room_memory_outbox o
                       where o.state = 'pending' and (
                         o.activity_id is not null or o.candidate_id in (
                           select candidate_id from room_memory_candidates
                           where approval_state = 'approved'
                         )
                       ))
                       as pending,
                     (select count(*) from room_memory_outbox o
                       where o.state = 'claimed' and (
                         o.activity_id is not null or o.candidate_id in (
                           select candidate_id from room_memory_candidates
                           where approval_state = 'approved'
                         )
                       ))
                       as claimed,
                     (select count(*) from room_memory_outbox o
                       where o.state = 'failed' and (
                         o.activity_id is not null or o.candidate_id in (
                           select candidate_id from room_memory_candidates
                           where approval_state = 'approved'
                         )
                       ))
                       as failed,
                     (select count(*) from room_memory_outbox o
                       where o.state = 'conflict' and (
                         o.activity_id is not null or o.candidate_id in (
                           select candidate_id from room_memory_candidates
                           where approval_state = 'approved'
                         )
                       ))
                       as conflict"""
            ).fetchone()
        assert row is not None
        return {key: int(row[key]) for key in row.keys()}

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect(readonly=readonly)

    @staticmethod
    def _view(row: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(row)
        raw_result = json.loads(record["result_json"]) if record.get("result_json") else None
        return {
            "schema_version": MEMORY_REBUILD_ACTION_SCHEMA,
            "action_id": record["action_id"],
            "client_action_id": record["client_action_id"],
            "status": record["status"],
            "phase": record["phase"],
            "reason_code": record.get("reason_code"),
            "before": {
                "state": record.get("before_state"),
                "code": record.get("before_code"),
            },
            "after": {
                "state": record.get("after_state"),
                "code": record.get("after_code"),
            },
            "result": _reset_result(raw_result),
            "requested_at": record["requested_at"],
            "applied_at": record.get("applied_at"),
            "proof_boundary": MEMORY_REBUILD_PROOF_BOUNDARY,
            # The guard/revision stay server-side for manager reconciliation.
            "_incident_guard": record["incident_guard"],
            "_runtime_generation": record.get("runtime_generation"),
            "_revision": int(record["revision"]),
        }
