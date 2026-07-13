"""Durable infrastructure controls for Room observation delivery.

This module deliberately does not complete an Agent observation.  It records
delivery attempts and operator controls beside Room authority so cancellation,
retry, and late-outcome fencing cannot be confused with an Agent outcome.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_attempt_ledger import (
    ATTEMPT_ACTIVE_STATES,
    ClaimAttemptRecord,
    attempt_by_id_conn,
    attempt_by_number_conn,
    attempt_view,
    insert_claim_attempt_conn,
    pending_cancel_observation_ids_conn,
    pending_provider_cleanup_observation_ids_conn,
    pending_runner_recovery_observation_ids_conn,
    public_attempt_view,
)
from xmuse_core.chat.room_batches import (
    batch_member_ids,
    batch_row_for_observation,
    canonical_observation_id,
)
from xmuse_core.chat.room_control_schema import (
    RoomControlError,
    create_room_restore_fence_schema,
)
from xmuse_core.chat.room_control_schema import (
    create_room_control_schema as create_room_control_schema,
)
from xmuse_core.chat.room_database import RoomDatabase

CONTROL_STATES = frozenset(
    {"active", "cancel_requested", "cancel_pending", "cancelled", "exhausted"}
)
RUNNER_RECOVERY_STATES = frozenset({"none", "fenced", "cleanup_pending", "recovered"})
RUNNER_RECOVERY_REASON = "room_runner_boot_lost"


def _now(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise RoomControlError("room_control_now_timezone_required")
    return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _positive_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RoomControlError(code)
    return value


def _observation(conn: sqlite3.Connection, observation_id: str) -> sqlite3.Row:
    row = conn.execute(
        "select * from room_observations where observation_id = ?", (observation_id,)
    ).fetchone()
    if row is None:
        raise RoomControlError("room_observation_not_found")
    if row["delivery_mode"] != "active":
        raise RoomControlError("room_observation_not_controllable")
    return row


def _attempt(conn: sqlite3.Connection, attempt_id: str | None) -> sqlite3.Row | None:
    return attempt_by_id_conn(conn, attempt_id)


def _attempt_view(
    row: sqlite3.Row | None, *, include_reconcile_binding: bool = False
) -> dict[str, Any] | None:
    return attempt_view(row, include_reconcile_binding=include_reconcile_binding)


def _public_attempt_view(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return public_attempt_view(row)


def _control_view(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _projection_event(*, observation_id: str, state: str, change: str) -> dict[str, Any]:
    return {
        "event_type": "projection.changed",
        "resource_ref": f"room-observation:{observation_id}",
        "source_authority": "room_observation_controls",
        # This is invalidation metadata, not an attempt/control ledger view.
        "source_ref": observation_id,
        "payload": {
            "kind": "room_observation_control_changed",
            "observation_id": observation_id,
            "control_state": state,
            "change": change,
        },
        "projection_only": True,
        "proof_boundary": "derived_from_room_control_authority",
    }


def _record_projection_event_conn(
    conn: sqlite3.Connection,
    *,
    descriptor: dict[str, Any],
    client_action_id: str | None,
    now: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    if conversation_id is None:
        conversation_id = str(
            conn.execute(
                "select conversation_id from room_observations where observation_id = ?",
                (descriptor["payload"]["observation_id"],),
            ).fetchone()[0]
        )
    seq = int(
        conn.execute(
            "select coalesce(max(seq), 0) + 1 from chat_frontend_events where conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
    )
    event_id = _id("fevt")
    conn.execute(
        """insert into chat_frontend_events
        (event_id, conversation_id, seq, event_type, resource_ref,
         source_authority, source_ref, payload_json, client_action_id,
         created_at, projection_only, proof_boundary)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            event_id,
            conversation_id,
            seq,
            descriptor["event_type"],
            descriptor["resource_ref"],
            descriptor["source_authority"],
            descriptor["source_ref"],
            _json(descriptor["payload"]),
            client_action_id,
            now,
            "frontend_event_not_authority",
        ),
    )
    return {**descriptor, "event_id": event_id, "sequence": seq}


def effective_attempt_limit(
    conn: sqlite3.Connection, observation_id: str, base_attempt_limit: int
) -> int:
    base = _positive_int(base_attempt_limit, "room_attempt_limit_invalid")
    observation_id = canonical_observation_id(conn, observation_id)
    row = _observation(conn, observation_id)
    return base + int(row["manual_retry_budget"])


def _runner_identity(
    runner_generation: str | None,
    runner_boot_id: str | None,
    *,
    required: bool = False,
) -> tuple[str | None, str | None]:
    if runner_generation is None and runner_boot_id is None:
        if required:
            raise RoomControlError("room_runner_attempt_identity_required")
        return None, None
    if runner_generation is None or runner_boot_id is None:
        raise RoomControlError("room_runner_attempt_identity_incomplete")
    if (
        not isinstance(runner_generation, str)
        or not isinstance(runner_boot_id, str)
        or not runner_generation.strip()
        or not runner_boot_id.strip()
        or len(runner_generation.strip()) > 128
        or len(runner_boot_id.strip()) > 128
    ):
        raise RoomControlError("room_runner_attempt_identity_invalid")
    return runner_generation.strip(), runner_boot_id.strip()


def record_room_claim_attempt(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    base_attempt_limit: int,
    runner_generation: str | None = None,
    runner_boot_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a RoomKernel claim inside the claim's existing transaction."""

    normalized_generation, normalized_boot_id = _runner_identity(
        runner_generation,
        runner_boot_id,
    )
    observation_id = canonical_observation_id(conn, observation_id)
    row = _observation(conn, observation_id)
    batch = batch_row_for_observation(conn, observation_id)
    if row["control_state"] != "active" or row["status"] != "claimed":
        raise RoomControlError("room_observation_not_claimable")
    if not row["lease_owner"] or not row["lease_token"] or not row["expires_at"]:
        raise RoomControlError("room_observation_claim_incomplete")
    attempt_number = int(row["attempt_count"])
    if attempt_number <= 0:
        raise RoomControlError("room_observation_claim_incomplete")
    limit = effective_attempt_limit(conn, observation_id, base_attempt_limit)
    if attempt_number > limit:
        raise RoomControlError("room_observation_attempts_exhausted")
    existing = attempt_by_number_conn(
        conn,
        observation_id=observation_id,
        attempt_number=attempt_number,
    )
    token_digest = _digest(row["lease_token"])
    if existing is not None:
        if (
            existing["lease_owner"] != row["lease_owner"]
            or existing["lease_token_digest"] != token_digest
            or existing["runner_generation"] != normalized_generation
            or existing["runner_boot_id"] != normalized_boot_id
        ):
            raise RoomControlError("room_attempt_idempotency_conflict")
        if row["current_attempt_id"] != existing["attempt_id"]:
            member_ids = batch_member_ids(conn, observation_id)
            placeholders = ",".join("?" for _ in member_ids)
            conn.execute(
                f"update room_observations set current_attempt_id = ? "
                f"where observation_id in ({placeholders})",
                (existing["attempt_id"], *member_ids),
            )
        if batch is not None and existing["batch_id"] is None:
            conn.execute(
                "update room_observation_attempts set batch_id = ? where attempt_id = ?",
                (batch["batch_id"], existing["attempt_id"]),
            )
            existing = _attempt(conn, existing["attempt_id"])
        return _attempt_view(existing) or {}
    stamp = _now(now)
    previous = _attempt(conn, row["current_attempt_id"])
    if previous is not None and previous["state"] in {"claimed", "delivering"}:
        conn.execute(
            """update room_observation_attempts set state = 'expired',
            reason_code = 'lease_reclaimed', finished_at = ?, updated_at = ?
            where attempt_id = ?""",
            (stamp, stamp, previous["attempt_id"]),
        )
    attempt_id = _id("room_attempt")
    inserted = insert_claim_attempt_conn(
        conn,
        ClaimAttemptRecord(
            attempt_id=attempt_id,
            batch_id=batch["batch_id"] if batch is not None else None,
            conversation_id=row["conversation_id"],
            observation_id=observation_id,
            participant_id=row["participant_id"],
            attempt_number=attempt_number,
            effective_attempt_limit=limit,
            delivery_generation=attempt_number,
            lease_owner=row["lease_owner"],
            lease_token_digest=token_digest,
            runner_generation=normalized_generation,
            runner_boot_id=normalized_boot_id,
            claimed_at=row["acquired_at"] or stamp,
            expires_at=row["expires_at"],
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    member_ids = batch_member_ids(conn, observation_id)
    placeholders = ",".join("?" for _ in member_ids)
    conn.execute(
        f"update room_observations set current_attempt_id = ? "
        f"where observation_id in ({placeholders})",
        (attempt_id, *member_ids),
    )
    return _attempt_view(inserted) or {}


def bind_room_delivery(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_id: str,
    lease_token: str,
    delivery_task_id: str,
    provider_session_generation: str,
    provider_session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind an attempt to one task/session generation, idempotently."""

    row = _observation(conn, observation_id)
    attempt = _attempt(conn, attempt_id)
    if attempt is None or row["current_attempt_id"] != attempt_id:
        raise RoomControlError("room_attempt_generation_lost")
    if row["control_state"] != "active" or attempt["state"] not in {"claimed", "delivering"}:
        raise RoomControlError("room_attempt_generation_lost")
    if attempt["lease_token_digest"] != _digest(lease_token):
        raise RoomControlError("room_observation_lease_lost")
    decision = conn.execute(
        "select 1 from room_attempt_skill_decisions where attempt_id = ?", (attempt_id,)
    ).fetchone()
    if decision is None:
        raise RoomControlError("room_skill_binding_lost")
    binding = (delivery_task_id, provider_session_id, provider_session_generation)
    prior = (
        attempt["delivery_task_id"],
        attempt["provider_session_id"],
        attempt["provider_session_generation"],
    )
    if attempt["state"] == "delivering":
        if prior != binding:
            raise RoomControlError("room_attempt_binding_conflict")
        return _attempt_view(attempt) or {}
    if not delivery_task_id or not provider_session_generation:
        raise RoomControlError("room_attempt_binding_required")
    stamp = _now(now)
    conn.execute(
        """update room_observation_attempts set state = 'delivering',
        delivery_task_id = ?, provider_session_id = ?, provider_session_generation = ?,
        transport_started_at = ?, updated_at = ? where attempt_id = ?""",
        (*binding, stamp, stamp, attempt_id),
    )
    return _attempt_view(_attempt(conn, attempt_id)) or {}


def bind_room_provider_session(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_id: str,
    delivery_generation: str,
    god_session_id: str,
    provider_session_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind the exact provider session while its delivery generation is current."""

    row = _observation(conn, observation_id)
    attempt = _attempt(conn, attempt_id)
    if (
        attempt is None
        or row["current_attempt_id"] != attempt_id
        or row["control_state"] != "active"
        or attempt["state"] != "delivering"
        or attempt["provider_session_generation"] != delivery_generation
    ):
        raise RoomControlError("room_attempt_generation_lost")
    if not god_session_id or not provider_session_id:
        raise RoomControlError("room_attempt_provider_binding_required")
    existing = (attempt["god_session_id"], attempt["provider_session_id"])
    requested = (god_session_id, provider_session_id)
    if any(existing):
        if existing != requested:
            raise RoomControlError("room_attempt_provider_binding_conflict")
        if attempt["provider_phase"] == "bound":
            return _attempt_view(attempt) or {}
    stamp = _now(now)
    conn.execute(
        """update room_observation_attempts set god_session_id = ?,
        provider_session_id = ?, provider_phase = 'bound', provider_cleanup_reason = null,
        provider_phase_updated_at = ?, updated_at = ? where attempt_id = ?""",
        (god_session_id, provider_session_id, stamp, stamp, attempt_id),
    )
    return _attempt_view(_attempt(conn, attempt_id)) or {}


def mark_room_provider_ensure_started(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_id: str,
    delivery_generation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fence the crash window before a provider session may be created."""

    row = _observation(conn, observation_id)
    attempt = _attempt(conn, attempt_id)
    if (
        attempt is None
        or row["current_attempt_id"] != attempt_id
        or row["control_state"] != "active"
        or attempt["state"] != "delivering"
        or attempt["provider_session_generation"] != delivery_generation
    ):
        raise RoomControlError("room_attempt_generation_lost")
    if attempt["provider_phase"] in {"bound", "ensure_started"}:
        return _attempt_view(attempt) or {}
    if attempt["provider_phase"] != "not_started":
        raise RoomControlError("room_attempt_generation_lost")
    stamp = _now(now)
    conn.execute(
        """update room_observation_attempts set provider_phase = 'ensure_started',
        provider_cleanup_reason = null, provider_phase_updated_at = ?, updated_at = ?
        where attempt_id = ?""",
        (stamp, stamp, attempt_id),
    )
    return _attempt_view(_attempt(conn, attempt_id)) or {}


def mark_room_provider_cleanup(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_id: str,
    delivery_generation: str,
    succeeded: bool,
    reason_code: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist provider cleanup evidence for exactly one attempt generation."""

    if not reason_code:
        raise RoomControlError("room_provider_cleanup_reason_required")
    row = _observation(conn, observation_id)
    attempt = _attempt(conn, attempt_id)
    if (
        attempt is None
        or row["current_attempt_id"] != attempt_id
        or attempt["provider_session_generation"] != delivery_generation
    ):
        raise RoomControlError("room_attempt_generation_lost")
    phase = "cleanup_succeeded" if succeeded else "cleanup_pending"
    stamp = _now(now)
    conn.execute(
        """update room_observation_attempts set provider_phase = ?,
        provider_cleanup_reason = ?, provider_phase_updated_at = ?, updated_at = ?
        where attempt_id = ?""",
        (phase, reason_code, stamp, stamp, attempt_id),
    )
    return _attempt_view(_attempt(conn, attempt_id)) or {}


def assert_room_outcome_allowed(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    lease_token: str,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    """Fence an outcome in the same transaction that will commit it."""

    observation_id = canonical_observation_id(conn, observation_id)
    row = _observation(conn, observation_id)
    current_attempt_id = row["current_attempt_id"]
    current = _attempt(conn, current_attempt_id)
    if (
        row["control_state"] != "active"
        or row["status"] != "claimed"
        or not row["lease_token"]
        or row["lease_token"] != lease_token
        or current is None
        or (attempt_id is not None and attempt_id != current_attempt_id)
        or current["state"] not in {"claimed", "delivering", "failed"}
        or current["lease_token_digest"] != _digest(lease_token)
    ):
        raise RoomControlError("room_observation_lease_lost")
    return _attempt_view(current) or {}


def commit_room_outcome_attempt(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    lease_token: str,
    attempt_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark the fenced attempt complete within the Room outcome transaction."""

    current = assert_room_outcome_allowed(
        conn,
        observation_id=observation_id,
        lease_token=lease_token,
        attempt_id=attempt_id,
    )
    stamp = _now(now)
    conn.execute(
        """update room_observation_attempts set state = 'completed', reason_code = null,
        finished_at = ?, updated_at = ? where attempt_id = ?""",
        (stamp, stamp, current["attempt_id"]),
    )
    return _attempt_view(_attempt(conn, current["attempt_id"])) or {}


def _finalize_runner_recovery_conn(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_id: str,
    base_attempt_limit: int,
    stamp: str,
) -> tuple[str, str, str]:
    observation_id = canonical_observation_id(conn, observation_id)
    row = _observation(conn, observation_id)
    attempt = _attempt(conn, attempt_id)
    if attempt is None or row["current_attempt_id"] != attempt_id:
        raise RoomControlError("room_attempt_generation_lost")
    recovery_state = str(attempt["recovery_state"])
    if recovery_state == "recovered":
        return str(row["control_state"]), "runner_recovery.recovered", "replayed"
    if (
        recovery_state not in {"fenced", "cleanup_pending"}
        or attempt["recovery_reason_code"] != RUNNER_RECOVERY_REASON
    ):
        raise RoomControlError("room_runner_recovery_not_pending")
    if attempt["provider_phase"] not in {"not_started", "cleanup_succeeded"}:
        raise RoomControlError("room_runner_recovery_cleanup_unproven")
    if row["control_state"] in {"cancel_requested", "cancel_pending"}:
        raise RoomControlError("room_runner_recovery_cancel_pending")
    if row["control_state"] not in {"active", "exhausted"}:
        raise RoomControlError("room_runner_recovery_not_finalizable")

    limit = effective_attempt_limit(conn, observation_id, base_attempt_limit)
    exhausted = row["control_state"] == "exhausted" or int(row["attempt_count"]) >= limit
    next_control_state = "exhausted" if exhausted else "active"
    next_control_seq = int(row["control_seq"]) + int(
        row["control_state"] != "exhausted" and exhausted
    )
    conn.execute(
        """update room_observation_attempts set state = 'expired', reason_code = ?,
        recovery_state = 'recovered', recovery_completed_at = ?,
        finished_at = coalesce(finished_at, ?), updated_at = ? where attempt_id = ?""",
        (RUNNER_RECOVERY_REASON, stamp, stamp, stamp, attempt_id),
    )
    conn.execute(
        """update room_observations set status = 'pending', control_state = ?,
        control_seq = ?, lease_owner = null, lease_token = null, acquired_at = null,
        expires_at = null, updated_at = ? where observation_id = ?""",
        (next_control_state, next_control_seq, stamp, observation_id),
    )
    result = "exhausted" if exhausted else "pending"
    return next_control_state, f"runner_recovery.{result}", result


class RoomObservationControlStore:
    """Transaction-owning API for durable cancel/retry control commands."""

    def __init__(self, path: Path | str, *, initialize: bool = False) -> None:
        self._path = Path(path)
        # Retain the keyword for restore-call compatibility.  Schema initialization is
        # deliberately owned by RoomDatabase at process startup, never by this store.
        del initialize

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    def record_claim(
        self,
        observation_id: str,
        *,
        base_attempt_limit: int,
        runner_generation: str | None = None,
        runner_boot_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            result = record_room_claim_attempt(
                conn,
                observation_id=observation_id,
                base_attempt_limit=base_attempt_limit,
                runner_generation=runner_generation,
                runner_boot_id=runner_boot_id,
                now=now,
            )
            conn.commit()
            return result

    def bind_delivery(self, **kwargs: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            result = bind_room_delivery(conn, **kwargs)
            conn.commit()
            return result

    def bind_provider_session(self, **kwargs: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            result = bind_room_provider_session(conn, **kwargs)
            conn.commit()
            return result

    def mark_provider_ensure_started(self, **kwargs: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            result = mark_room_provider_ensure_started(conn, **kwargs)
            conn.commit()
            return result

    def mark_provider_cleanup(self, **kwargs: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("begin immediate")
            result = mark_room_provider_cleanup(conn, **kwargs)
            conn.commit()
            return result

    def fence_restored_runtime_generation(
        self,
        *,
        operation_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fence process-local delivery state in an offline restored database.

        The caller must own an offline staging database: this operation treats
        every claimed lease as belonging to a runtime generation that no longer
        exists.  Room speech, outcomes, attempts, control commands, attempt
        counts, and manual retry budgets remain authoritative and are never
        recreated.  A durable operation receipt makes exact replay a no-op.
        """

        if not isinstance(operation_id, str) or not operation_id.strip():
            raise RoomControlError("room_restore_operation_id_required")
        normalized_operation_id = operation_id.strip()
        if len(normalized_operation_id) > 256:
            raise RoomControlError("room_restore_operation_id_invalid")
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                # Restore tooling operates on an already validated offline
                # staging database and must not run ChatStore seeds/migrations.
                create_room_restore_fence_schema(conn)
                prior = conn.execute(
                    "select result_json from room_runtime_restore_fences where operation_id = ?",
                    (normalized_operation_id,),
                ).fetchone()
                if prior is not None:
                    result = json.loads(prior["result_json"])
                    conn.commit()
                    return result

                rows = conn.execute(
                    """select o.*, a.attempt_id as restore_attempt_id,
                              a.state as restore_attempt_state,
                              a.effective_attempt_limit as restore_attempt_limit,
                              a.provider_phase as restore_provider_phase,
                              a.recovery_state as restore_recovery_state
                       from room_observations o
                       join room_observation_attempts a
                         on a.attempt_id = o.current_attempt_id
                       where o.status <> 'completed'
                       order by o.conversation_id, o.observation_id"""
                ).fetchall()
                affected_observations: set[str] = set()
                affected_conversations: set[str] = set()
                reopened_pending_count = 0
                exhausted_count = 0
                pending_cancel_count = 0
                provider_cleanup_count = 0
                unsafe_provider_phases = {"ensure_started", "bound", "cleanup_pending"}

                seen_observations: set[str] = set()
                for candidate in rows:
                    observation_id = canonical_observation_id(
                        conn, str(candidate["observation_id"])
                    )
                    if observation_id in seen_observations:
                        continue
                    seen_observations.add(observation_id)
                    row = conn.execute(
                        """select o.*, a.attempt_id as restore_attempt_id,
                                  a.state as restore_attempt_state,
                                  a.effective_attempt_limit as restore_attempt_limit,
                                  a.provider_phase as restore_provider_phase,
                                  a.recovery_state as restore_recovery_state
                           from room_observations o
                           join room_observation_attempts a
                             on a.attempt_id = o.current_attempt_id
                           where o.observation_id = ? and o.status <> 'completed'""",
                        (observation_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    conversation_id = str(row["conversation_id"])
                    attempt_id = str(row["restore_attempt_id"])
                    control_state = str(row["control_state"])
                    provider_phase = str(row["restore_provider_phase"])
                    recovery_state = str(row["restore_recovery_state"])
                    changed = False

                    if provider_phase in unsafe_provider_phases:
                        conn.execute(
                            """update room_observation_attempts
                               set provider_phase = 'cleanup_succeeded',
                                   provider_cleanup_reason =
                                       'restore_transport_generation_fenced',
                                   provider_phase_updated_at = ?, updated_at = ?
                               where attempt_id = ?""",
                            (stamp, stamp, attempt_id),
                        )
                        provider_cleanup_count += 1
                        changed = True

                    if recovery_state in {"fenced", "cleanup_pending"}:
                        conn.execute(
                            """update room_observation_attempts
                               set recovery_state = 'recovered',
                                   recovery_completed_at = ?, updated_at = ?
                               where attempt_id = ?""",
                            (stamp, stamp, attempt_id),
                        )
                        changed = True

                    if control_state in {"cancel_requested", "cancel_pending"}:
                        if any(
                            row[field] is not None
                            for field in ("lease_owner", "lease_token", "acquired_at", "expires_at")
                        ):
                            conn.execute(
                                """update room_observations
                                   set lease_owner = null, lease_token = null,
                                       acquired_at = null, expires_at = null, updated_at = ?
                                   where observation_id = ?""",
                                (stamp, observation_id),
                            )
                            changed = True
                        if changed:
                            pending_cancel_count += 1
                    elif control_state == "active" and row["status"] == "claimed":
                        exhausted = int(row["attempt_count"]) >= int(row["restore_attempt_limit"])
                        conn.execute(
                            """update room_observation_attempts
                               set state = 'expired',
                                   reason_code = 'restore_runtime_generation_fenced',
                                   finished_at = coalesce(finished_at, ?), updated_at = ?
                               where attempt_id = ?""",
                            (stamp, stamp, attempt_id),
                        )
                        if exhausted:
                            conn.execute(
                                """update room_observations
                                   set control_state = 'exhausted',
                                       control_seq = control_seq + 1,
                                       lease_owner = null, lease_token = null,
                                       acquired_at = null, expires_at = null, updated_at = ?
                                   where observation_id = ?""",
                                (stamp, observation_id),
                            )
                            exhausted_count += 1
                        else:
                            conn.execute(
                                """update room_observations
                                   set status = 'pending', lease_owner = null,
                                       lease_token = null, acquired_at = null,
                                       expires_at = null, updated_at = ?
                                   where observation_id = ?""",
                                (stamp, observation_id),
                            )
                            reopened_pending_count += 1
                        changed = True

                    if changed:
                        affected_observations.add(observation_id)
                        affected_conversations.add(conversation_id)

                event_cursors: dict[str, int] = {}
                for conversation_id in sorted(affected_conversations):
                    event = _record_projection_event_conn(
                        conn,
                        descriptor={
                            "event_type": "projection.changed",
                            "resource_ref": f"room:{conversation_id}",
                            "source_authority": "room_observation_controls",
                            "source_ref": f"restore-operation:{normalized_operation_id}",
                            "payload": {
                                "kind": "room_runtime_generation_fenced",
                                "change": "restore.runtime_generation_fenced",
                            },
                            "projection_only": True,
                            "proof_boundary": "derived_from_room_control_authority",
                        },
                        client_action_id=normalized_operation_id,
                        now=stamp,
                        conversation_id=conversation_id,
                    )
                    event_cursors[conversation_id] = int(event["sequence"])

                result = {
                    "schema_version": "room_runtime_restore_fence/v1",
                    "operation_id": normalized_operation_id,
                    "applied_at": stamp,
                    "affected_observation_count": len(affected_observations),
                    "affected_conversation_count": len(affected_conversations),
                    "reopened_pending_count": reopened_pending_count,
                    "exhausted_count": exhausted_count,
                    "pending_cancel_count": pending_cancel_count,
                    "provider_cleanup_count": provider_cleanup_count,
                    "event_cursors": event_cursors,
                }
                conn.execute(
                    "insert into room_runtime_restore_fences "
                    "(operation_id, result_json, applied_at) values (?, ?, ?)",
                    (normalized_operation_id, _json(result), stamp),
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def request_cancel(
        self,
        *,
        observation_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_attempt_count: int,
        expected_control_seq: int,
        base_attempt_limit: int = 3,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._request(
            action="cancel",
            observation_id=observation_id,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_state=expected_state,
            expected_attempt_count=expected_attempt_count,
            expected_control_seq=expected_control_seq,
            base_attempt_limit=base_attempt_limit,
            now=now,
        )

    def request_retry(
        self,
        *,
        observation_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_attempt_count: int,
        expected_control_seq: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._request(
            action="retry",
            observation_id=observation_id,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_state=expected_state,
            expected_attempt_count=expected_attempt_count,
            expected_control_seq=expected_control_seq,
            base_attempt_limit=None,
            now=now,
        )

    def _request(
        self,
        *,
        action: str,
        observation_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_attempt_count: int,
        expected_control_seq: int,
        base_attempt_limit: int | None,
        now: datetime | None,
    ) -> dict[str, Any]:
        if not client_action_id or not operator_identity or expected_state not in CONTROL_STATES:
            raise RoomControlError("room_control_request_invalid")
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            observation_id = canonical_observation_id(conn, observation_id)
            fingerprint = _digest(
                _json(
                    {
                        "action": action,
                        "expected_attempt_count": expected_attempt_count,
                        "expected_control_seq": expected_control_seq,
                        "expected_state": expected_state,
                        "observation_id": observation_id,
                    }
                )
            )
            prior = conn.execute(
                """select * from room_observation_controls where observation_id = ?
                and operator_identity = ? and client_action_id = ?""",
                (observation_id, operator_identity, client_action_id),
            ).fetchone()
            if prior is not None:
                if prior["request_fingerprint"] != fingerprint:
                    raise RoomControlError("room_control_idempotency_conflict")
                conn.commit()
                if prior["status"] == "rejected":
                    raise RoomControlError(prior["reason_code"] or "room_control_request_rejected")
                return self._result(conn, prior)
            row = _observation(conn, observation_id)
            try:
                self._guard(
                    row,
                    expected_state=expected_state,
                    expected_attempt_count=expected_attempt_count,
                    expected_control_seq=expected_control_seq,
                )
                if row["status"] == "completed":
                    raise RoomControlError("room_observation_already_completed")
                if action == "cancel" and (
                    row["control_state"] != "active" or row["status"] != "claimed"
                ):
                    raise RoomControlError("room_observation_not_cancellable")
                if action == "retry":
                    if row["control_state"] not in {"cancelled", "exhausted"}:
                        raise RoomControlError("room_observation_not_retryable")
                    retry_attempt = _attempt(conn, row["current_attempt_id"])
                    if retry_attempt is not None and (
                        retry_attempt["state"] in ATTEMPT_ACTIVE_STATES
                        or retry_attempt["provider_phase"] in {"ensure_started", "cleanup_pending"}
                    ):
                        raise RoomControlError("room_observation_retry_not_settled")
            except RoomControlError as exc:
                self._record_rejected_control(
                    conn,
                    row=row,
                    action=action,
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_state=expected_state,
                    expected_attempt_count=expected_attempt_count,
                    expected_control_seq=expected_control_seq,
                    reason_code=exc.code,
                    now=stamp,
                )
                conn.commit()
                raise
            if action == "cancel":
                if not row["current_attempt_id"]:
                    assert base_attempt_limit is not None
                    record_room_claim_attempt(
                        conn,
                        observation_id=observation_id,
                        base_attempt_limit=base_attempt_limit,
                        now=now,
                    )
                    row = _observation(conn, observation_id)
                attempt = _attempt(conn, row["current_attempt_id"])
                if attempt is None or attempt["state"] not in {"claimed", "delivering"}:
                    raise RoomControlError("room_observation_not_cancellable")
                next_state = "cancel_requested"
                attempt_id = attempt["attempt_id"]
            else:
                attempt = _attempt(conn, row["current_attempt_id"])
                next_state = "active"
                attempt_id = attempt["attempt_id"] if attempt is not None else None
            seq = int(row["control_seq"]) + 1
            control_id = _id("room_control")
            status = "requested" if action == "cancel" else "applied"
            conn.execute(
                """insert into room_observation_controls
                (control_id, conversation_id, observation_id, participant_id, action,
                 client_action_id, operator_identity, request_fingerprint, expected_state,
                 expected_attempt_count, expected_control_seq, resulting_state,
                 resulting_control_seq, attempt_id, status, reason_code, requested_at,
                 frontend_event_seq, applied_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, ?, null, ?, ?)""",
                (
                    control_id,
                    row["conversation_id"],
                    observation_id,
                    row["participant_id"],
                    action,
                    client_action_id,
                    operator_identity,
                    fingerprint,
                    expected_state,
                    expected_attempt_count,
                    expected_control_seq,
                    next_state,
                    seq,
                    attempt_id,
                    status,
                    stamp,
                    stamp if action == "retry" else None,
                    stamp,
                ),
            )
            if action == "cancel":
                conn.execute(
                    """update room_observations set control_state = 'cancel_requested',
                    control_seq = ?, lease_token = null, expires_at = ?, updated_at = ?
                    where observation_id = ?""",
                    (seq, stamp, stamp, observation_id),
                )
                conn.execute(
                    """update room_observation_attempts set state = 'cancel_requested',
                    reason_code = 'operator_cancel_requested', updated_at = ?
                    where attempt_id = ?""",
                    (stamp, attempt_id),
                )
            else:
                conn.execute(
                    """update room_observations set control_state = 'active', control_seq = ?,
                    manual_retry_budget = manual_retry_budget + 1, status = 'pending',
                    lease_owner = null,
                    lease_token = null, acquired_at = null, expires_at = null,
                    current_attempt_id = null, updated_at = ?
                    where observation_id = ?""",
                    (seq, stamp, observation_id),
                )
            descriptor = _projection_event(
                observation_id=observation_id,
                state=next_state,
                change=f"{action}.{next_state}",
            )
            event = _record_projection_event_conn(
                conn,
                descriptor=descriptor,
                client_action_id=client_action_id,
                now=stamp,
            )
            conn.execute(
                "update room_observation_controls set frontend_event_seq = ? where control_id = ?",
                (event["sequence"], control_id),
            )
            control = conn.execute(
                "select * from room_observation_controls where control_id = ?", (control_id,)
            ).fetchone()
            conn.commit()
            return self._result(conn, control)

    @staticmethod
    def _record_rejected_control(
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        action: str,
        client_action_id: str,
        operator_identity: str,
        fingerprint: str,
        expected_state: str,
        expected_attempt_count: int,
        expected_control_seq: int,
        reason_code: str,
        now: str,
    ) -> None:
        conn.execute(
            """insert into room_observation_controls
            (control_id, conversation_id, observation_id, participant_id, action,
             client_action_id, operator_identity, request_fingerprint, expected_state,
             expected_attempt_count, expected_control_seq, resulting_state,
             resulting_control_seq, attempt_id, status, reason_code, requested_at,
             frontend_event_seq, applied_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rejected', ?, ?, null, null, ?)""",
            (
                _id("room_control"),
                row["conversation_id"],
                row["observation_id"],
                row["participant_id"],
                action,
                client_action_id,
                operator_identity,
                fingerprint,
                expected_state,
                expected_attempt_count,
                expected_control_seq,
                row["control_state"],
                int(row["control_seq"]),
                row["current_attempt_id"],
                reason_code,
                now,
                now,
            ),
        )

    @staticmethod
    def _guard(
        row: sqlite3.Row,
        *,
        expected_state: str,
        expected_attempt_count: int,
        expected_control_seq: int,
    ) -> None:
        if row["control_state"] != expected_state:
            raise RoomControlError("room_control_state_conflict")
        if int(row["attempt_count"]) != expected_attempt_count:
            raise RoomControlError("room_control_attempt_conflict")
        if int(row["control_seq"]) != expected_control_seq:
            raise RoomControlError("room_control_seq_conflict")

    def mark_cancel_pending(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        expected_control_seq: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._mark_cancel(
            observation_id=observation_id,
            attempt_id=attempt_id,
            expected_control_seq=expected_control_seq,
            target="cancel_pending",
            reason_code="transport_cancel_pending",
            now=now,
        )

    def mark_cancelled(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        expected_control_seq: int,
        reason_code: str = "operator_cancelled",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._mark_cancel(
            observation_id=observation_id,
            attempt_id=attempt_id,
            expected_control_seq=expected_control_seq,
            target="cancelled",
            reason_code=reason_code,
            now=now,
        )

    def _mark_cancel(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        expected_control_seq: int,
        target: str,
        reason_code: str,
        now: datetime | None,
    ) -> dict[str, Any]:
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            observation_id = canonical_observation_id(conn, observation_id)
            row = _observation(conn, observation_id)
            allowed = (
                {"cancel_requested"}
                if target == "cancel_pending"
                else {"cancel_requested", "cancel_pending"}
            )
            if (
                row["control_state"] not in allowed
                or row["current_attempt_id"] != attempt_id
                or int(row["control_seq"]) != expected_control_seq
            ):
                raise RoomControlError("room_attempt_generation_lost")
            attempt = _attempt(conn, attempt_id)
            if attempt is None:
                raise RoomControlError("room_attempt_generation_lost")
            if target == "cancelled" and attempt["provider_phase"] not in {
                "not_started",
                "cleanup_succeeded",
            }:
                raise RoomControlError("room_provider_cleanup_unproven")
            seq = int(row["control_seq"]) + 1
            conn.execute(
                """update room_observations set control_state = ?, control_seq = ?,
                lease_owner = null, lease_token = null, expires_at = null, updated_at = ?
                where observation_id = ?""",
                (target, seq, stamp, observation_id),
            )
            conn.execute(
                """update room_observation_attempts set state = ?, reason_code = ?,
                finished_at = case when ? = 'cancelled' then ? else finished_at end,
                recovery_state = case
                    when ? = 'cancelled'
                     and recovery_state in ('fenced','cleanup_pending')
                    then 'recovered' else recovery_state end,
                recovery_completed_at = case
                    when ? = 'cancelled'
                     and recovery_state in ('fenced','cleanup_pending')
                    then ? else recovery_completed_at end,
                updated_at = ? where attempt_id = ?""",
                (
                    target,
                    reason_code,
                    target,
                    stamp,
                    target,
                    target,
                    stamp,
                    stamp,
                    attempt_id,
                ),
            )
            conn.execute(
                """update room_observation_controls set status = 'applied',
                resulting_state = ?, resulting_control_seq = ?, reason_code = ?,
                applied_at = coalesce(applied_at, ?), updated_at = ?
                where observation_id = ? and action = 'cancel' and attempt_id = ?
                and status in ('requested','applied')""",
                (target, seq, reason_code, stamp, stamp, observation_id, attempt_id),
            )
            event = _record_projection_event_conn(
                conn,
                descriptor=_projection_event(
                    observation_id=observation_id,
                    state=target,
                    change=target,
                ),
                client_action_id=None,
                now=stamp,
            )
            conn.commit()
            return self.projection(observation_id) | {
                "event_cursor": event["sequence"],
                "projection_event": event,
            }

    def mark_exhausted(
        self,
        *,
        observation_id: str,
        base_attempt_limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            observation_id = canonical_observation_id(conn, observation_id)
            row = _observation(conn, observation_id)
            limit = effective_attempt_limit(conn, observation_id, base_attempt_limit)
            if row["status"] == "completed":
                raise RoomControlError("room_observation_already_completed")
            if row["control_state"] != "active" or int(row["attempt_count"]) < limit:
                raise RoomControlError("room_observation_not_exhausted")
            current = _attempt(conn, row["current_attempt_id"])
            if current is not None and current["state"] in {"claimed", "delivering"}:
                expires_at = datetime.fromisoformat(current["expires_at"].replace("Z", "+00:00"))
                if expires_at > datetime.fromisoformat(stamp.replace("Z", "+00:00")):
                    raise RoomControlError("room_observation_attempt_live")
                conn.execute(
                    """update room_observation_attempts set state = 'expired',
                    reason_code = 'attempts_exhausted', finished_at = ?, updated_at = ?
                    where attempt_id = ?""",
                    (stamp, stamp, current["attempt_id"]),
                )
            seq = int(row["control_seq"]) + 1
            conn.execute(
                """update room_observations set control_state = 'exhausted',
                control_seq = ?, lease_owner = null, lease_token = null, expires_at = null,
                updated_at = ? where observation_id = ?""",
                (seq, stamp, observation_id),
            )
            event = _record_projection_event_conn(
                conn,
                descriptor=_projection_event(
                    observation_id=observation_id,
                    state="exhausted",
                    change="exhausted",
                ),
                client_action_id=None,
                now=stamp,
            )
            conn.commit()
            return self.projection(observation_id) | {
                "event_cursor": event["sequence"],
                "projection_event": event,
            }

    def effective_limit(self, observation_id: str, base_attempt_limit: int) -> int:
        with self._connect() as conn:
            return effective_attempt_limit(conn, observation_id, base_attempt_limit)

    def reconcile_attempt_limit(self, base_attempt_limit: int) -> int:
        """Reopen exhausted observations when the configured policy now permits work."""

        base = _positive_int(base_attempt_limit, "room_attempt_limit_invalid")
        stamp = _now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            changed = conn.execute(
                """update room_observations set control_state = 'active',
                control_seq = control_seq + 1, status = 'pending',
                lease_owner = null, lease_token = null, acquired_at = null,
                expires_at = null, current_attempt_id = null, updated_at = ?
                where control_state = 'exhausted'
                  and status <> 'completed'
                  and attempt_count < (? + manual_retry_budget)
                  and not exists (
                      select 1 from room_observation_batch_members bm
                      join room_observation_batches b on b.batch_id = bm.batch_id
                      where bm.observation_id = room_observations.observation_id
                        and b.primary_observation_id <> room_observations.observation_id
                  )
                  and not exists (
                      select 1 from room_observation_attempts a
                      where a.attempt_id = room_observations.current_attempt_id
                        and a.provider_phase in ('ensure_started', 'cleanup_pending')
                  )""",
                (stamp, base),
            ).rowcount
            conn.commit()
            return int(changed)

    def finish_attempt(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        reason_code: str,
        base_attempt_limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a transport terminal state and materialize exhaustion."""

        if not reason_code:
            raise RoomControlError("room_attempt_reason_required")
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            observation_id = canonical_observation_id(conn, observation_id)
            row = _observation(conn, observation_id)
            attempt = _attempt(conn, attempt_id)
            if attempt is None or row["current_attempt_id"] != attempt_id:
                raise RoomControlError("room_attempt_generation_lost")
            if row["status"] == "completed" or attempt["state"] == "completed":
                conn.commit()
                return self.projection(observation_id)
            if row["control_state"] != "active":
                conn.commit()
                return self.projection(observation_id)
            conn.execute(
                """update room_observation_attempts set state = 'failed',
                reason_code = ?, finished_at = ?, updated_at = ? where attempt_id = ?""",
                (reason_code, stamp, stamp, attempt_id),
            )
            limit = effective_attempt_limit(conn, observation_id, base_attempt_limit)
            exhausted = int(row["attempt_count"]) >= limit
            if exhausted:
                seq = int(row["control_seq"]) + 1
                conn.execute(
                    """update room_observations set control_state = 'exhausted',
                    control_seq = ?, lease_owner = null, lease_token = null,
                    expires_at = null, updated_at = ?
                    where observation_id = ?""",
                    (seq, stamp, observation_id),
                )
            event = _record_projection_event_conn(
                conn,
                descriptor=_projection_event(
                    observation_id=observation_id,
                    state="exhausted" if exhausted else "active",
                    change="attempt.exhausted" if exhausted else "attempt.failed",
                ),
                client_action_id=None,
                now=stamp,
            )
            conn.commit()
        return self.projection(observation_id) | {
            "event_cursor": event["sequence"],
            "projection_event": event,
        }

    def fail_unstarted_attempt(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        expected_lease_token: str,
        reason_code: str,
        base_attempt_limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fail and release an attempt proven not to have entered Provider runtime."""

        if not reason_code:
            raise RoomControlError("room_attempt_reason_required")
        stamp = _now(now)
        limit_base = _positive_int(base_attempt_limit, "room_attempt_limit_invalid")
        with self._connect() as conn:
            conn.execute("begin immediate")
            observation_id = canonical_observation_id(conn, observation_id)
            row = _observation(conn, observation_id)
            attempt = _attempt(conn, attempt_id)
            if attempt is None or row["current_attempt_id"] != attempt_id:
                raise RoomControlError("room_skill_unstarted_failure_lost")

            receipt = conn.execute(
                "select context_payload_sha256 from room_attempt_skill_decisions "
                "where attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            has_receipt = receipt is not None and receipt["context_payload_sha256"] is not None

            # Exact replay is the only terminal state accepted. It must not append an event.
            if attempt["state"] == "failed":
                if (
                    attempt["reason_code"] == reason_code
                    and attempt["provider_phase"] == "not_started"
                    and not has_receipt
                    and row["control_state"] in {"active", "exhausted"}
                    and row["status"] in {"pending", "claimed"}
                    and row["lease_owner"] is None
                    and row["lease_token"] is None
                    and row["expires_at"] is None
                ):
                    conn.commit()
                    return self.projection(observation_id)
                raise RoomControlError("room_skill_unstarted_failure_lost")

            if (
                row["control_state"] != "active"
                or row["status"] != "claimed"
                or not expected_lease_token
                or row["lease_token"] != expected_lease_token
                or attempt["lease_token_digest"] != _digest(expected_lease_token)
                or attempt["state"] not in {"claimed", "delivering"}
                or attempt["provider_phase"] != "not_started"
                or has_receipt
            ):
                raise RoomControlError("room_skill_unstarted_failure_lost")

            conn.execute(
                """update room_observation_attempts set state = 'failed', reason_code = ?,
                finished_at = ?, updated_at = ? where attempt_id = ?""",
                (reason_code, stamp, stamp, attempt_id),
            )
            limit = effective_attempt_limit(conn, observation_id, limit_base)
            exhausted = int(row["attempt_count"]) >= limit
            if exhausted:
                conn.execute(
                    """update room_observations set control_state = 'exhausted',
                    control_seq = control_seq + 1, lease_owner = null, lease_token = null,
                    acquired_at = null, expires_at = null, updated_at = ?
                    where observation_id = ?""",
                    (stamp, observation_id),
                )
            else:
                conn.execute(
                    """update room_observations set status = 'pending',
                    lease_owner = null, lease_token = null, acquired_at = null,
                    expires_at = null, updated_at = ?
                    where observation_id = ?""",
                    (stamp, observation_id),
                )
            event = _record_projection_event_conn(
                conn,
                descriptor=_projection_event(
                    observation_id=observation_id,
                    state="exhausted" if exhausted else "active",
                    change="attempt.exhausted" if exhausted else "attempt.failed",
                ),
                client_action_id=None,
                now=stamp,
            )
            conn.commit()
        return self.projection(observation_id) | {
            "event_cursor": event["sequence"],
            "projection_event": event,
        }

    def fence_prior_runner_attempts(
        self,
        *,
        current_runner_generation: str,
        current_runner_boot_id: str,
        base_attempt_limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fence current attempts owned by a prior confirmed-dead Room Runner boot.

        The caller must hold the root-scoped Room Runner process lock.  A rotated,
        immediately expired lease fences late provider outcomes in this transaction.
        Attempts without explicit Room Runner ownership are legacy/compat authority
        and deliberately retain their ordinary lease-expiry semantics.
        """

        generation, boot_id = _runner_identity(
            current_runner_generation,
            current_runner_boot_id,
            required=True,
        )
        assert generation is not None and boot_id is not None
        base = _positive_int(base_attempt_limit, "room_attempt_limit_invalid")
        stamp = _now(now)
        event_cursors: dict[str, int] = {}
        fenced_count = 0
        cleanup_pending_count = 0
        recovered_count = 0
        pending_count = 0
        exhausted_count = 0
        cancel_pending_count = 0
        with self._connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """select o.observation_id, o.control_state, a.attempt_id,
                          a.provider_phase
                   from room_observations o
                   join room_observation_attempts a
                     on a.attempt_id = o.current_attempt_id
                   where o.status <> 'completed'
                     and a.runner_generation is not null
                     and a.runner_boot_id is not null
                     and a.runner_boot_id <> ?
                     and a.recovery_state = 'none'
                     and a.state in (
                         'claimed','delivering','cancel_requested','cancel_pending'
                     )
                   order by o.conversation_id, o.observation_id""",
                (boot_id,),
            ).fetchall()
            seen_observations: set[str] = set()
            for candidate in rows:
                observation_id = canonical_observation_id(conn, str(candidate["observation_id"]))
                if observation_id in seen_observations:
                    continue
                seen_observations.add(observation_id)
                candidate = conn.execute(
                    """select o.observation_id, o.control_state, a.attempt_id,
                              a.provider_phase
                       from room_observations o
                       join room_observation_attempts a
                         on a.attempt_id = o.current_attempt_id
                       where o.observation_id = ? and o.status <> 'completed'
                         and a.runner_generation is not null
                         and a.runner_boot_id is not null
                         and a.runner_boot_id <> ?
                         and a.recovery_state = 'none'
                         and a.state in (
                             'claimed','delivering','cancel_requested','cancel_pending'
                         )""",
                    (observation_id, boot_id),
                ).fetchone()
                if candidate is None:
                    continue
                attempt_id = str(candidate["attempt_id"])
                control_state = str(candidate["control_state"])
                provider_phase = str(candidate["provider_phase"])
                requires_cleanup = provider_phase not in {
                    "not_started",
                    "cleanup_succeeded",
                }
                recovery_state = "cleanup_pending" if requires_cleanup else "fenced"
                fence_token = _id("lease_fence")
                conn.execute(
                    """update room_observations set lease_owner = ?, lease_token = ?,
                    expires_at = ?, updated_at = ? where observation_id = ?""",
                    (
                        f"room-recovery:{generation}:{boot_id}",
                        fence_token,
                        stamp,
                        stamp,
                        observation_id,
                    ),
                )
                conn.execute(
                    """update room_observation_attempts set recovery_state = ?,
                    recovery_reason_code = ?, recovery_started_at = ?,
                    recovery_completed_at = null,
                    provider_phase = case when ? then 'cleanup_pending' else provider_phase end,
                    provider_cleanup_reason = case when ? then ? else provider_cleanup_reason end,
                    provider_phase_updated_at = case
                        when ? then ? else provider_phase_updated_at end,
                    updated_at = ? where attempt_id = ? and recovery_state = 'none'""",
                    (
                        recovery_state,
                        RUNNER_RECOVERY_REASON,
                        stamp,
                        requires_cleanup,
                        requires_cleanup,
                        RUNNER_RECOVERY_REASON,
                        requires_cleanup,
                        stamp,
                        stamp,
                        attempt_id,
                    ),
                )
                fenced_count += 1
                change = "runner_recovery.cleanup_pending"
                event_state = control_state
                if control_state in {"cancel_requested", "cancel_pending"}:
                    cancel_pending_count += 1
                    if requires_cleanup:
                        cleanup_pending_count += 1
                    else:
                        change = "runner_recovery.fenced"
                elif requires_cleanup:
                    cleanup_pending_count += 1
                else:
                    event_state, change, result = _finalize_runner_recovery_conn(
                        conn,
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        base_attempt_limit=base,
                        stamp=stamp,
                    )
                    recovered_count += 1
                    if result == "pending":
                        pending_count += 1
                    elif result == "exhausted":
                        exhausted_count += 1
                event = _record_projection_event_conn(
                    conn,
                    descriptor=_projection_event(
                        observation_id=observation_id,
                        state=event_state,
                        change=change,
                    ),
                    client_action_id=None,
                    now=stamp,
                )
                event_cursors[observation_id] = int(event["sequence"])
            conn.commit()
        return {
            "schema_version": "room_runner_recovery_fence/v1",
            "fenced_count": fenced_count,
            "cleanup_pending_count": cleanup_pending_count,
            "recovered_count": recovered_count,
            "pending_count": pending_count,
            "exhausted_count": exhausted_count,
            "cancel_pending_count": cancel_pending_count,
            "event_cursors": event_cursors,
        }

    def list_pending_runner_recoveries(self) -> list[dict[str, Any]]:
        """Return active/exhausted boot-loss recoveries needing exact cleanup/finalize."""

        with self._connect() as conn:
            observation_ids = pending_runner_recovery_observation_ids_conn(
                conn,
                reason_code=RUNNER_RECOVERY_REASON,
            )
            results = []
            for observation_id in observation_ids:
                observation = _observation(conn, observation_id)
                attempt = _attempt(conn, observation["current_attempt_id"])
                results.append(
                    self.projection(observation_id)
                    | {"reconcile_binding": _attempt_view(attempt, include_reconcile_binding=True)}
                )
        return results

    def finalize_runner_recovery(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        base_attempt_limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Reopen or exhaust a fenced attempt after provider cleanup is proven."""

        base = _positive_int(base_attempt_limit, "room_attempt_limit_invalid")
        stamp = _now(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            state, change, result = _finalize_runner_recovery_conn(
                conn,
                observation_id=observation_id,
                attempt_id=attempt_id,
                base_attempt_limit=base,
                stamp=stamp,
            )
            if result == "replayed":
                conn.commit()
                return self.projection(observation_id)
            event = _record_projection_event_conn(
                conn,
                descriptor=_projection_event(
                    observation_id=observation_id,
                    state=state,
                    change=change,
                ),
                client_action_id=None,
                now=stamp,
            )
            conn.commit()
        return self.projection(observation_id) | {
            "event_cursor": event["sequence"],
            "projection_event": event,
        }

    def list_pending_cancels(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            observation_ids = pending_cancel_observation_ids_conn(conn)
            results = []
            for observation_id in observation_ids:
                observation = _observation(conn, observation_id)
                attempt = _attempt(conn, observation["current_attempt_id"])
                results.append(
                    self.projection(observation_id)
                    | {"reconcile_binding": _attempt_view(attempt, include_reconcile_binding=True)}
                )
        return results

    def list_pending_provider_cleanups(self) -> list[dict[str, Any]]:
        """Return unsafe provider generations that block claim or manual retry."""

        with self._connect() as conn:
            observation_ids = pending_provider_cleanup_observation_ids_conn(conn)
        return [self.reconcile_state(observation_id) for observation_id in observation_ids]

    def reconcile_state(self, observation_id: str) -> dict[str, Any]:
        """Return internal cleanup evidence for the Host, never for browser projection."""

        with self._connect() as conn:
            observation_id = canonical_observation_id(conn, observation_id)
            observation = _observation(conn, observation_id)
            attempt = _attempt(conn, observation["current_attempt_id"])
            binding = _attempt_view(attempt, include_reconcile_binding=True)
        return self.projection(observation_id) | {"reconcile_binding": binding}

    def projection(self, observation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            observation_id = canonical_observation_id(conn, observation_id)
            row = _observation(conn, observation_id)
            attempt = _attempt(conn, row["current_attempt_id"])
            can_cancel = (
                row["control_state"] == "active"
                and row["status"] == "claimed"
                and attempt is not None
                and attempt["state"] in {"claimed", "delivering"}
            )
            can_retry = row["control_state"] in {"cancelled", "exhausted"} and (
                attempt is None
                or (
                    attempt["state"] not in ATTEMPT_ACTIVE_STATES
                    and attempt["provider_phase"] not in {"ensure_started", "cleanup_pending"}
                )
            )
            return {
                "schema_version": "room_observation_control_projection/v1",
                "observation_id": observation_id,
                "conversation_id": row["conversation_id"],
                "participant_id": row["participant_id"],
                "observation_status": row["status"],
                "control_state": row["control_state"],
                "control_seq": int(row["control_seq"]),
                "attempt_count": int(row["attempt_count"]),
                "manual_retry_budget": int(row["manual_retry_budget"]),
                "current_attempt": _public_attempt_view(attempt),
                "actions": {
                    "cancel": {
                        "available": can_cancel,
                        "expected_state": row["control_state"],
                        "expected_attempt_count": int(row["attempt_count"]),
                        "expected_control_seq": int(row["control_seq"]),
                    },
                    "retry": {
                        "available": can_retry,
                        "expected_state": row["control_state"],
                        "expected_attempt_count": int(row["attempt_count"]),
                        "expected_control_seq": int(row["control_seq"]),
                    },
                },
            }

    def _result(self, conn: sqlite3.Connection, control: sqlite3.Row) -> dict[str, Any]:
        row = _observation(conn, control["observation_id"])
        return {
            "control": _control_view(control),
            "projection": self.projection(control["observation_id"]),
            "event_cursor": control["frontend_event_seq"],
            "projection_event": _projection_event(
                observation_id=control["observation_id"],
                state=row["control_state"],
                change=f"{control['action']}.{row['control_state']}",
            ),
        }
