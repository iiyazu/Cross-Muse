"""Controller authority for exact-patch execution runs."""

from __future__ import annotations

# ruff: noqa: F401
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_common import RUN_TRANSITIONS as _RUN_TRANSITIONS
from xmuse_core.chat.room_execution_common import TERMINAL_RUN_STATES, RoomExecutionStoreError
from xmuse_core.chat.room_execution_common import decode_json as _decode
from xmuse_core.chat.room_execution_common import new_id as _id
from xmuse_core.chat.room_execution_common import require_digest as _require_digest
from xmuse_core.chat.room_execution_common import require_text as _require_text
from xmuse_core.chat.room_execution_common import timestamp as _timestamp
from xmuse_core.chat.room_execution_contracts import canonical_execution_path
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_promotion import (
    mark_promotion_applying_conn,
    normalize_promotion_entries,
    prepare_promotion_journal_conn,
    resolve_promotion_journal_conn,
)
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_execution_runs import (
    advance_run_conn,
    assert_controller_conn,
    bound_run_conn,
    claim_requested_run_conn,
    controller_identity,
    reclaim_run_controller_conn,
    record_gate_evidence_conn,
)
from xmuse_core.chat.room_execution_runs import (
    required_gate_plan_for_run_conn as _required_gate_plan_for_run_conn,
)
from xmuse_core.chat.room_execution_terminal import finalize_run_conn
from xmuse_core.chat.room_execution_views import candidate_view_conn as _candidate_view_conn
from xmuse_core.chat.room_execution_views import run_view_conn as _run_view_conn


class RoomExecutionControllerStore:
    """Durable authority exposed to one-shot execution controllers."""

    _controller_identity = staticmethod(controller_identity)
    _assert_controller_conn = staticmethod(assert_controller_conn)
    _bound_run_conn = staticmethod(bound_run_conn)
    _promotion_entries = staticmethod(normalize_promotion_entries)

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)
        self._reader = RoomExecutionLedgerReader(db_path)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._reader.get_run(run_id)

    def get_policy(self, conversation_id: str) -> dict[str, Any] | None:
        return self._reader.get_policy(conversation_id)

    @staticmethod
    def _controller_material_conn(conn: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any]:
        candidate = conn.execute(
            "select * from room_execution_candidates where candidate_id = ?",
            (run["candidate_id"],),
        ).fetchone()
        authorization = conn.execute(
            "select * from room_execution_authorizations where authorization_id = ?",
            (run["authorization_id"],),
        ).fetchone()
        if candidate is None or authorization is None:
            raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
        gate_plan = _required_gate_plan_for_run_conn(conn, run)
        public = _run_view_conn(conn, run)
        public["execution_generation"] = int(run["execution_generation"])
        public["controller"] = {
            "id": run["controller_id"],
            "generation": run["controller_generation"],
            "pid": int(run["controller_pid"]),
            "start_identity": run["controller_start_identity"],
        }
        public["candidate"] = _candidate_view_conn(conn, candidate, include_patch=True)
        public["gate_plan"] = gate_plan.internal_mapping()
        public["authorization"] = {
            "authorization_id": authorization["authorization_id"],
            "mode": authorization["authorization_mode"],
            "candidate_digest": authorization["candidate_digest"],
            "candidate_revision": int(authorization["candidate_revision"]),
            "policy_revision": int(authorization["policy_revision"]),
            "risk_policy_revision": authorization["risk_policy_revision"],
            "peer_snapshot_digest": authorization["peer_snapshot_digest"],
            "workspace_guard_digest": authorization["workspace_guard_digest"],
            "risk_evidence_digest": authorization["risk_evidence_digest"],
            "status": authorization["status"],
        }
        return public

    def get_controller_material(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        execution_generation: int,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        with self._database.connect(readonly=True) as conn:
            run = conn.execute(
                "select * from room_execution_runs where run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RoomExecutionStoreError("room_execution_run_not_found")
            self._assert_controller_conn(
                run,
                controller_id=identity[0],
                controller_generation=identity[1],
                controller_pid=identity[2],
                controller_start_identity=identity[3],
                execution_generation=execution_generation,
            )
            return self._controller_material_conn(conn, run)

    def claim_requested_run(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        return self._claim_requested_run(run_id=run_id, identity=identity, now=now)

    def _claim_requested_run(
        self,
        *,
        run_id: str,
        identity: tuple[str, str, int, str],
        now: datetime | None,
    ) -> dict[str, Any]:
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                updated = claim_requested_run_conn(
                    conn,
                    run_id=run_id,
                    identity=identity,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def claim_next_requested_run(
        self,
        *,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                """select run_id from room_execution_runs
                   where state in ('requested','cancel_requested') and controller_id is null
                   order by requested_at, run_id limit 1"""
            ).fetchone()
        if row is None:
            return None
        try:
            return self._claim_requested_run(run_id=str(row["run_id"]), identity=identity, now=now)
        except RoomExecutionStoreError as exc:
            if exc.code == "room_execution_run_claim_conflict":
                return None
            raise

    def reclaim_run_controller(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        expected_execution_generation: int,
        prior_controller_id: str,
        prior_controller_generation: str,
        prior_controller_pid: int,
        prior_controller_start_identity: str,
        confirmed_dead: bool,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if confirmed_dead is not True:
            raise RoomExecutionStoreError("room_execution_takeover_death_unconfirmed")
        old = self._controller_identity(
            controller_id=prior_controller_id,
            controller_generation=prior_controller_generation,
            controller_pid=prior_controller_pid,
            controller_start_identity=prior_controller_start_identity,
        )
        new = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                updated = reclaim_run_controller_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    expected_execution_generation=expected_execution_generation,
                    old_identity=old,
                    new_identity=new,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return private bindings for a trusted supervisor's /proc identity checks."""

        clean_limit = max(1, min(int(limit), 500))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select run_id, state, revision, execution_generation, controller_id,
                          controller_generation, controller_pid, controller_start_identity,
                          updated_at
                   from room_execution_runs where state not in
                     ('cancelled','succeeded','failed','blocked')
                   order by requested_at, run_id limit ?""",
                (clean_limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "state": row["state"],
                "revision": int(row["revision"]),
                "execution_generation": int(row["execution_generation"]),
                "controller_id": row["controller_id"],
                "controller_generation": row["controller_generation"],
                "controller_pid": (
                    int(row["controller_pid"]) if row["controller_pid"] is not None else None
                ),
                "controller_start_identity": row["controller_start_identity"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def advance_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_state: str,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated = advance_run_conn(
                    conn,
                    run=run,
                    target_state=target_state,
                    reason_code=reason_code,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def record_gate_evidence(
        self,
        *,
        run_id: str,
        expected_run_state: str,
        expected_run_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        gate_id: str,
        status: Literal["running", "passed", "failed", "cancelled"],
        evidence_digest: str,
        started_at: str,
        finished_at: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_run_state,
                    expected_revision=expected_run_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated, changed = record_gate_evidence_conn(
                    conn,
                    run=run,
                    execution_generation=execution_generation,
                    gate_id=gate_id,
                    status=status,
                    evidence_digest=evidence_digest,
                    started_at=started_at,
                    finished_at=finished_at,
                    reason_code=reason_code,
                    stamp=stamp,
                )
                if not changed:
                    conn.rollback()
                    return _run_view_conn(conn, updated)
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def prepare_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_head: str,
        pre_manifest_digest: str,
        post_manifest_digest: str,
        file_entries: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        pre_manifest_digest = _require_digest(
            pre_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        post_manifest_digest = _require_digest(
            post_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        target_head = _require_text(target_head, "room_execution_target_head_invalid", maximum=64)
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="ready_to_promote",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (run["candidate_id"],),
                ).fetchone()
                if candidate is None or target_head != candidate["base_head"]:
                    raise RoomExecutionStoreError("room_execution_promotion_head_mismatch")
                authorization = conn.execute(
                    "select * from room_execution_authorizations where authorization_id = ?",
                    (run["authorization_id"],),
                ).fetchone()
                policy = conn.execute(
                    "select * from room_execution_policies where conversation_id = ?",
                    (run["conversation_id"],),
                ).fetchone()
                policy_drift = (
                    authorization is None
                    or policy is None
                    or authorization["status"] != "consumed"
                    or policy["mode"] != candidate["policy_mode_snapshot"]
                    or int(policy["revision"]) != int(authorization["policy_revision"])
                    or policy["risk_policy_revision"] != authorization["risk_policy_revision"]
                    or int(authorization["policy_revision"])
                    != int(candidate["policy_revision_snapshot"])
                    or authorization["risk_policy_revision"]
                    != candidate["risk_policy_revision_snapshot"]
                )
                if policy_drift:
                    gate_plan = _required_gate_plan_for_run_conn(conn, run)
                    evidence = {
                        str(row["gate_id"]): str(row["status"])
                        for row in conn.execute(
                            """select gate_id, status from room_execution_gate_evidence
                               where run_id = ? and execution_generation = ?""",
                            (run_id, execution_generation),
                        )
                    }
                    completed_gates = tuple(
                        gate_id
                        for gate_id in gate_plan.gate_ids
                        if evidence.get(gate_id) == "passed"
                    )
                    blocked = finalize_run_conn(
                        conn,
                        run=run,
                        terminal_state="blocked",
                        reason_code="execution_policy_guard_changed",
                        changed_files=(),
                        gate_ids=completed_gates,
                        evidence_digest=None,
                        stamp=stamp,
                    )
                    result = self._controller_material_conn(conn, blocked)
                    conn.commit()
                    return result
                entries_json = self._promotion_entries(candidate, file_entries)
                updated = prepare_promotion_journal_conn(
                    conn,
                    run_id=run_id,
                    journal_id=_id("execution_promotion"),
                    execution_generation=execution_generation,
                    target_head=target_head,
                    pre_manifest_digest=pre_manifest_digest,
                    post_manifest_digest=post_manifest_digest,
                    file_entries_json=entries_json,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def mark_promotion_applying(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="promoting",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated = mark_promotion_applying_conn(conn, run_id=run_id, stamp=stamp)
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def resolve_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        observed_manifest_digest: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        observed_manifest_digest = _require_digest(
            observed_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="promoting",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )

                def finalize_ambiguous(
                    target_conn: sqlite3.Connection,
                    target_run: sqlite3.Row,
                    digest: str,
                    target_stamp: str,
                ) -> sqlite3.Row:
                    return finalize_run_conn(
                        target_conn,
                        run=target_run,
                        terminal_state="blocked",
                        reason_code="promotion_ambiguous",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=digest,
                        stamp=target_stamp,
                    )

                resolution, updated = resolve_promotion_journal_conn(
                    conn,
                    run=run,
                    observed_manifest_digest=observed_manifest_digest,
                    stamp=stamp,
                    finalize_ambiguous=finalize_ambiguous,
                )
                result = {
                    "resolution": resolution,
                    "run": self._controller_material_conn(conn, updated),
                }
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def acknowledge_cancel(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        transport_stopped: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(transport_stopped, bool):
            raise RoomExecutionStoreError("room_execution_cancel_transport_state_invalid")
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_execution_runs where run_id = ?", (run_id,)
                ).fetchone()
                if row is None or row["state"] not in {"cancel_requested", "cancel_pending"}:
                    raise RoomExecutionStoreError("room_execution_cancel_guard_mismatch")
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=str(row["state"]),
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                if transport_stopped:
                    updated = finalize_run_conn(
                        conn,
                        run=run,
                        terminal_state="cancelled",
                        reason_code="operator_cancelled",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=None,
                        stamp=stamp,
                    )
                else:
                    if run["state"] != "cancel_requested":
                        raise RoomExecutionStoreError("room_execution_cancel_cleanup_pending")
                    conn.execute(
                        """update room_execution_runs set state = 'cancel_pending',
                           revision = revision + 1, reason_code = 'cancel_cleanup_pending',
                           updated_at = ? where run_id = ?""",
                        (stamp, run_id),
                    )
                    updated = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert updated is not None
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def finalize_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        terminal_state: Literal["succeeded", "failed", "blocked", "cancelled"],
        reason_code: str,
        changed_files: Sequence[str] = (),
        gate_ids: Sequence[str] = (),
        evidence_digest: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if terminal_state not in TERMINAL_RUN_STATES or terminal_state == "cancelled":
            raise RoomExecutionStoreError("room_execution_run_terminal_state_invalid")
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        reason_code = _require_text(reason_code, "room_execution_run_reason_required", maximum=128)
        clean_changed = tuple(canonical_execution_path(item) for item in changed_files)
        if len(clean_changed) != len(set(clean_changed)):
            raise RoomExecutionStoreError("room_execution_changed_files_invalid")
        clean_gates = tuple(
            _require_text(item, "room_execution_gate_id_invalid", maximum=128) for item in gate_ids
        )
        if len(clean_gates) != len(set(clean_gates)):
            raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
        if evidence_digest is not None:
            evidence_digest = _require_digest(
                evidence_digest, "room_execution_evidence_digest_invalid"
            )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                gate_plan = _required_gate_plan_for_run_conn(conn, run)
                if clean_gates != gate_plan.gate_ids[: len(clean_gates)]:
                    raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
                if terminal_state not in _RUN_TRANSITIONS.get(expected_state, frozenset()):
                    raise RoomExecutionStoreError("room_execution_run_transition_invalid")
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (run["candidate_id"],),
                ).fetchone()
                if candidate is None:
                    raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
                allowed = set(_decode(candidate["allowed_files_json"], []))
                if terminal_state == "succeeded":
                    journal = conn.execute(
                        "select * from room_execution_promotion_journal where run_id = ?",
                        (run_id,),
                    ).fetchone()
                    if (
                        expected_state != "promoting"
                        or journal is None
                        or journal["status"] != "applied"
                        or set(clean_changed) != allowed
                        or clean_gates != gate_plan.gate_ids
                    ):
                        raise RoomExecutionStoreError("room_execution_promotion_not_proven")
                elif clean_changed:
                    raise RoomExecutionStoreError("room_execution_changed_files_invalid")
                known_gates = {
                    str(row["gate_id"])
                    for row in conn.execute(
                        "select gate_id from room_execution_gate_evidence where run_id = ?",
                        (run_id,),
                    )
                }
                if not set(clean_gates).issubset(known_gates):
                    raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
                updated = finalize_run_conn(
                    conn,
                    run=run,
                    terminal_state=terminal_state,
                    reason_code=reason_code,
                    changed_files=clean_changed,
                    gate_ids=clean_gates,
                    evidence_digest=evidence_digest,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
