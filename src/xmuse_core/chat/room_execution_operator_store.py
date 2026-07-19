"""Operator authority for exact-patch execution actions."""

from __future__ import annotations

# ruff: noqa: F401
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_actions import (
    complete_execution_action_conn,
    replay_execution_action,
    reserve_execution_action_conn,
)
from xmuse_core.chat.room_execution_actions import (
    operator_decision_fingerprint as _operator_decision_fingerprint,
)
from xmuse_core.chat.room_execution_candidates import (
    _ensure_policy_conn,
    patch_from_candidate,
    workspace_guard_digest,
)
from xmuse_core.chat.room_execution_candidates import policy_view as _policy_view
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_common import decode_json as _decode
from xmuse_core.chat.room_execution_common import digest as _digest
from xmuse_core.chat.room_execution_common import require_digest as _require_digest
from xmuse_core.chat.room_execution_common import require_text as _require_text
from xmuse_core.chat.room_execution_common import timestamp as _timestamp
from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_events import record_execution_event_conn
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_runs import authorize_execution_conn
from xmuse_core.chat.room_execution_runs import trusted_gate_plan as _trusted_gate_plan
from xmuse_core.chat.room_execution_terminal import finalize_run_conn
from xmuse_core.chat.room_execution_views import run_view_conn as _run_view_conn


class RoomExecutionOperatorStore:
    """Fixed privileged commands with direct durable transaction ownership."""

    _reserve_action_conn = staticmethod(reserve_execution_action_conn)
    _complete_action_conn = staticmethod(complete_execution_action_conn)
    _record_event_conn = staticmethod(record_execution_event_conn)
    _workspace_guard_digest = staticmethod(workspace_guard_digest)
    _authorize_conn = staticmethod(authorize_execution_conn)
    _action_replay = staticmethod(replay_execution_action)

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def set_policy(
        self,
        *,
        conversation_id: str,
        mode: Literal["manual", "consensus"],
        client_action_id: str,
        operator_identity: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if mode not in {"manual", "consensus"}:
            raise RoomExecutionStoreError("room_execution_policy_mode_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RoomExecutionStoreError("room_execution_policy_revision_invalid")
        request = {
            "conversation_id": conversation_id,
            "mode": mode,
            "expected_revision": expected_revision,
        }
        fingerprint = _digest(request)
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                if (
                    conn.execute(
                        "select 1 from conversations where id = ?", (conversation_id,)
                    ).fetchone()
                    is None
                ):
                    raise RoomExecutionStoreError("room_execution_conversation_not_found")
                policy = _ensure_policy_conn(conn, conversation_id, stamp=stamp)
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=conversation_id,
                    candidate_id=None,
                    action_type="policy_update",
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=None,
                    expected_candidate_revision=None,
                    expected_policy_revision=expected_revision,
                    expected_run_state=None,
                    expected_run_revision=None,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return _decode(action["result_json"], {})
                if (
                    conn.execute(
                        """select 1 from room_execution_runs
                           where conversation_id = ? and state = 'promoting' limit 1""",
                        (conversation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise RoomExecutionStoreError("room_execution_policy_promotion_conflict")
                if int(policy["revision"]) != expected_revision:
                    raise RoomExecutionStoreError("room_execution_policy_guard_mismatch")
                if policy["mode"] != mode:
                    conn.execute(
                        """update room_execution_policies set mode = ?, revision = revision + 1,
                           updated_at = ? where conversation_id = ? and revision = ?""",
                        (mode, stamp, conversation_id, expected_revision),
                    )
                updated = conn.execute(
                    "select * from room_execution_policies where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                assert updated is not None
                result = _policy_view(updated)
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=result,
                    reason_code=None,
                    run_id=None,
                    stamp=stamp,
                )
                self._record_event_conn(
                    conn,
                    conversation_id=conversation_id,
                    event_type="projection.changed",
                    resource_ref=f"room:execution-policy:{conversation_id}",
                    source_ref=f"room:execution-policy:{conversation_id}",
                    payload={"change": "execution.policy_changed", "revision": result["revision"]},
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def replay_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
    ) -> dict[str, Any] | None:
        """Read an exact durable decision replay without reserving an action."""

        if decision not in {"execute", "reject"}:
            raise RoomExecutionStoreError("room_execution_decision_invalid")
        client_action_id = _require_text(
            client_action_id,
            "room_execution_client_action_id_required",
        )
        operator_identity = _require_text(
            operator_identity,
            "room_execution_operator_identity_required",
        )
        expected_candidate_digest = _require_digest(
            expected_candidate_digest,
            "room_execution_candidate_digest_invalid",
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (expected_candidate_revision, expected_policy_revision)
        ):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        fingerprint = _operator_decision_fingerprint(
            candidate_id=candidate_id,
            decision=decision,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
        )
        with self._database.connect(readonly=True) as conn:
            action = conn.execute(
                """select * from room_execution_operator_actions
                   where operator_identity = ? and client_action_id = ?""",
                (operator_identity, client_action_id),
            ).fetchone()
        if action is None:
            return None
        expected_type = "candidate_execute" if decision == "execute" else "candidate_reject"
        if (
            action["candidate_id"] != candidate_id
            or action["action_type"] != expected_type
            or action["request_fingerprint"] != fingerprint
            or action["expected_candidate_digest"] != expected_candidate_digest
            or action["expected_candidate_revision"] != expected_candidate_revision
            or action["expected_policy_revision"] != expected_policy_revision
        ):
            raise RoomExecutionStoreError("room_execution_action_idempotency_conflict")
        return self._action_replay(action)

    def apply_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
        workspace_guard: ExecutionWorkspaceGuard | None = None,
        risk_evaluation: ExecutionRiskEvaluation | None = None,
        gate_plan: ExecutionGatePlan | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if decision not in {"execute", "reject"}:
            raise RoomExecutionStoreError("room_execution_decision_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        expected_candidate_digest = _require_digest(
            expected_candidate_digest, "room_execution_candidate_digest_invalid"
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (expected_candidate_revision, expected_policy_revision)
        ):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        stamp = _timestamp(now)
        fingerprint = _operator_decision_fingerprint(
            candidate_id=candidate_id,
            decision=decision,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
        )
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if candidate is None:
                    raise RoomExecutionStoreError("room_execution_candidate_not_found")
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=candidate["conversation_id"],
                    candidate_id=candidate_id,
                    action_type=(
                        "candidate_execute" if decision == "execute" else "candidate_reject"
                    ),
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=expected_candidate_digest,
                    expected_candidate_revision=expected_candidate_revision,
                    expected_policy_revision=expected_policy_revision,
                    expected_run_state=None,
                    expected_run_revision=None,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return self._action_replay(action)
                policy = _ensure_policy_conn(conn, candidate["conversation_id"], stamp=stamp)
                if (
                    candidate["candidate_digest"] != expected_candidate_digest
                    or int(candidate["revision"]) != expected_candidate_revision
                    or int(policy["revision"]) != expected_policy_revision
                    or candidate["state"] != "open"
                ):
                    reason = "room_execution_candidate_guard_mismatch"
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="rejected",
                        result={
                            "candidate_id": candidate_id,
                            "status": "rejected",
                            "reason_code": reason,
                        },
                        reason_code=reason,
                        run_id=None,
                        stamp=stamp,
                    )
                    conn.commit()
                    raise RoomExecutionStoreError(reason)
                if decision == "reject":
                    conn.execute(
                        """update room_execution_candidates set state = 'rejected',
                           consensus_state = 'invalidated', revision = revision + 1,
                           reason_code = 'operator_rejected', rejected_at = ?, updated_at = ?
                           where candidate_id = ? and state = 'open'""",
                        (stamp, stamp, candidate_id),
                    )
                    result = {
                        "candidate_id": candidate_id,
                        "state": "rejected",
                        "reason_code": "operator_rejected",
                    }
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="applied",
                        result=result,
                        reason_code=None,
                        run_id=None,
                        stamp=stamp,
                    )
                    self._record_event_conn(
                        conn,
                        conversation_id=candidate["conversation_id"],
                        event_type="projection.changed",
                        resource_ref=f"room:execution-candidate:{candidate_id}",
                        source_ref=f"room:execution-candidate:{candidate_id}",
                        payload={
                            "change": "execution.candidate_rejected",
                            "candidate_id": candidate_id,
                        },
                        client_action_id=client_action_id,
                        stamp=stamp,
                    )
                    conn.commit()
                    return result
                if workspace_guard is None:
                    raise RoomExecutionStoreError("room_execution_workspace_guard_required")
                trusted_plan = _trusted_gate_plan(candidate, gate_plan)
                workspace_digest = self._workspace_guard_digest(candidate, workspace_guard)
                risk_digest: str | None = None
                if risk_evaluation is not None:
                    risk_digest = _require_digest(
                        risk_evaluation.evidence_digest,
                        "room_execution_risk_evidence_invalid",
                    )
                    if not risk_evaluation.approved:
                        raise RoomExecutionStoreError(
                            risk_evaluation.reason_code or "room_execution_risk_rejected"
                        )
                _, run, _ = self._authorize_conn(
                    conn,
                    candidate=candidate,
                    authorization_mode="manual",
                    workspace_guard_digest=workspace_digest,
                    risk_evidence_digest=risk_digest,
                    gate_plan=trusted_plan,
                    stamp=stamp,
                )
                execute_result: dict[str, Any] = {
                    "candidate_id": candidate_id,
                    "state": "authorized",
                    "authorization_mode": "manual",
                    "run": _run_view_conn(conn, run),
                }
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=execute_result,
                    reason_code=None,
                    run_id=run["run_id"],
                    stamp=stamp,
                )
                self._record_event_conn(
                    conn,
                    conversation_id=candidate["conversation_id"],
                    event_type="projection.changed",
                    resource_ref=f"room:execution-run:{run['run_id']}",
                    source_ref=f"room:execution-candidate:{candidate_id}",
                    payload={
                        "change": "execution.run_requested",
                        "candidate_id": candidate_id,
                        "run_id": run["run_id"],
                    },
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return execute_result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def request_cancel(
        self,
        *,
        run_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if expected_state not in {
            "requested",
            "preparing",
            "staging",
            "verifying",
            "ready_to_promote",
        }:
            raise RoomExecutionStoreError("room_execution_cancel_state_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        fingerprint = _digest(
            {
                "run_id": run_id,
                "expected_state": expected_state,
                "expected_revision": expected_revision,
            }
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = conn.execute(
                    "select * from room_execution_runs where run_id = ?", (run_id,)
                ).fetchone()
                if run is None:
                    raise RoomExecutionStoreError("room_execution_run_not_found")
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=run["conversation_id"],
                    candidate_id=run["candidate_id"],
                    action_type="run_cancel",
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=None,
                    expected_candidate_revision=None,
                    expected_policy_revision=None,
                    expected_run_state=expected_state,
                    expected_run_revision=expected_revision,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return self._action_replay(action)
                if run["state"] != expected_state or int(run["revision"]) != expected_revision:
                    reason = "room_execution_run_guard_mismatch"
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="rejected",
                        result={"run_id": run_id, "status": "rejected", "reason_code": reason},
                        reason_code=reason,
                        run_id=run_id,
                        stamp=stamp,
                    )
                    conn.commit()
                    raise RoomExecutionStoreError(reason)
                if run["state"] == "requested":
                    # No controller has acquired transport or target-byte authority yet.
                    # Terminal cancellation in this transaction also wins a concurrent
                    # child claim, which will observe the terminal state and exit.
                    conn.execute(
                        """update room_execution_runs
                           set control_seq = control_seq + 1, updated_at = ?
                           where run_id = ?""",
                        (stamp, run_id),
                    )
                    pending = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert pending is not None
                    updated = finalize_run_conn(
                        conn,
                        run=pending,
                        terminal_state="cancelled",
                        reason_code="operator_cancelled_before_start",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=None,
                        stamp=stamp,
                    )
                    change = "execution.cancelled"
                else:
                    conn.execute(
                        """update room_execution_runs set state = 'cancel_requested',
                           revision = revision + 1, control_seq = control_seq + 1,
                           reason_code = 'operator_cancel_requested', updated_at = ?
                           where run_id = ?""",
                        (stamp, run_id),
                    )
                    updated = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert updated is not None
                    change = "execution.cancel_requested"
                result = _run_view_conn(conn, updated)
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=result,
                    reason_code=None,
                    run_id=run_id,
                    stamp=stamp,
                )
                self._record_event_conn(
                    conn,
                    conversation_id=run["conversation_id"],
                    event_type="projection.changed",
                    resource_ref=f"room:execution-run:{run_id}",
                    source_ref=f"room:execution-run:{run_id}",
                    payload={"change": change, "run_id": run_id},
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
