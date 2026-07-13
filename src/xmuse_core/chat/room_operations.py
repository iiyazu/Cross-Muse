"""Safe Operations read model and durable local runtime action ledger."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.memoryos_supervisor import (
    memoryos_incident_guard,
    memoryos_rebuildability,
    safe_memoryos_status,
)
from xmuse_core.chat.room_database import RoomDatabase, RoomDatabaseError
from xmuse_core.chat.room_memory_rebuild_store import RoomMemoryRebuildActionStore
from xmuse_core.chat.room_operations_schema import (
    create_room_operations_schema as create_room_operations_schema,
)

OPERATIONS_SCHEMA = "room_operations_projection/v2"
RECOVER_RESULT_SCHEMA = "room_runtime_recover/v1"
_ACTION_STATUSES = frozenset({"requested", "applied", "rejected", "failed"})
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_RECOVERABLE_RUNNER_CODES = frozenset(
    {
        "room_runner_heartbeat_stale",
        "room_runner_heartbeat_in_future",
        "room_runner_boot_id_invalid",
        "room_runner_error_invalid",
        "room_runner_failed_error_missing",
        "room_runner_generation_invalid",
        "room_runner_host_invalid",
        "room_runner_mcp_invalid",
        "room_runner_pid_invalid",
        "room_runner_proof_boundary_invalid",
        "room_runner_readiness_invalid",
        "room_runner_ready_invalid",
        "room_runner_root_mismatch",
        "room_runner_start_identity_invalid",
        "room_runner_state_invalid",
        "room_runner_status_missing",
        "room_runner_status_invalid_json",
        "room_runner_status_invalid_shape",
        "room_runner_status_schema_mismatch",
        "room_runner_status_symlink_rejected",
        "room_runner_status_too_large",
        "room_runner_status_unreadable",
        "room_runner_generation_mismatch",
        "room_runner_pid_mismatch",
        "room_runner_start_identity_mismatch",
        "room_runner_timestamp_invalid",
        "room_runner_timestamp_order_invalid",
        "room_runner_readiness_incomplete",
        "room_runner_ready_with_error",
        "room_runner_state_not_ready",
    }
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_code(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else fallback


def runtime_incident_guard(runtime: Mapping[str, Any]) -> str:
    """Hash private topology into an opaque, stable guard without projecting inputs."""

    services = runtime.get("services")
    services = services if isinstance(services, Mapping) else {}
    runner = services.get("room_runner")
    runner = runner if isinstance(runner, Mapping) else {}
    mcp = services.get("room_mcp")
    mcp = mcp if isinstance(mcp, Mapping) else {}
    host = runtime.get("host")
    host = host if isinstance(host, Mapping) else {}
    private = {
        "generation": runtime.get("generation"),
        "boot_id": runtime.get("boot_id"),
        "state": runtime.get("state"),
        "code": runtime.get("code"),
        "runner_pids": runner.get("pids"),
        "runner_code": runner.get("assessment_code"),
        "mcp_pids": mcp.get("pids"),
        "mcp_ready": mcp.get("ready"),
        "host_state": host.get("state"),
        "host_code": host.get("code"),
    }
    return f"incident_{_canonical_hash(private)[:32]}"


def runtime_recoverability(runtime: Mapping[str, Any]) -> dict[str, Any]:
    state = str(runtime.get("state") or "unknown")
    code = _safe_code(runtime.get("code"), "room_runtime_unverifiable")
    services = runtime.get("services")
    services = services if isinstance(services, Mapping) else {}
    runner = services.get("room_runner")
    runner = runner if isinstance(runner, Mapping) else {}
    mcp = services.get("room_mcp")
    mcp = mcp if isinstance(mcp, Mapping) else {}
    host = runtime.get("host")
    host = host if isinstance(host, Mapping) else {}
    host_state = str(host.get("state") or "unknown")

    available = False
    mode: Literal["start", "restart"] = "restart"
    if state == "stopped":
        available = True
        mode = "start"
    elif state not in {"starting", "stopping", "ready"}:
        runner_code = str(runner.get("assessment_code") or code)
        duplicate = code in {"duplicate_room_runner", "duplicate_room_mcp"}
        runner_receipt = runner_code in _RECOVERABLE_RUNNER_CODES
        mcp_failed = bool(runner.get("ready")) and not bool(mcp.get("ready"))
        available = duplicate or runner_receipt or mcp_failed
    if host_state == "blocked" and state not in {"starting", "stopping"}:
        available = True
    if runtime.get("ready") is True and host_state != "blocked":
        available = False
    return {
        "available": available,
        "mode": mode,
        "guard": runtime_incident_guard(runtime),
        "state": state,
        "code": code,
    }


def _safe_host(runtime: Mapping[str, Any]) -> dict[str, Any]:
    raw = runtime.get("host")
    raw = raw if isinstance(raw, Mapping) else {}
    state = str(raw.get("state") or "unknown")
    if state not in {"healthy", "attention", "blocked", "unknown"}:
        state = "unknown"
    return {
        "state": state,
        "code": _safe_code(raw.get("code"), "room_host_unknown"),
        "active_delivery_count": _nonnegative_int(raw.get("active_delivery_count")),
        "retained_cleanup_count": _nonnegative_int(raw.get("retained_cleanup_count")),
    }


def _nonnegative_int(value: Any) -> int:
    valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return int(value) if valid else 0


def _safe_runtime(runtime: Mapping[str, Any]) -> dict[str, Any]:
    services = runtime.get("services")
    services = services if isinstance(services, Mapping) else {}

    def component(name: str) -> dict[str, str]:
        raw = services.get(name)
        raw = raw if isinstance(raw, Mapping) else {}
        code: Any
        if raw.get("ready") is True:
            state = "healthy"
            code = "ready"
        elif raw.get("live") is True:
            state = "blocked"
            code = raw.get("assessment_code") if name == "room_runner" else "room_mcp_not_ready"
        else:
            state = "stopped"
            code = f"{name}_stopped"
        return {
            "state": state,
            "code": _safe_code(code, f"{name}_not_ready"),
        }

    return {
        "runner": component("room_runner"),
        "mcp": component("room_mcp"),
        "host": _safe_host(runtime),
    }


def _safe_memory_runtime(runtime: Mapping[str, Any] | None) -> dict[str, Any]:
    safe = safe_memoryos_status(runtime)
    return {
        "enabled": safe.get("enabled") is True,
        "state": str(safe.get("state") or "unknown"),
        "code": _safe_code(safe.get("code"), "memoryos_status_unverifiable"),
        "consecutive_restart_count": _nonnegative_int(safe.get("consecutive_restart_count")),
        "next_retry_at": safe.get("next_retry_at")
        if isinstance(safe.get("next_retry_at"), str)
        else None,
        "last_healthy_at": safe.get("last_healthy_at")
        if isinstance(safe.get("last_healthy_at"), str)
        else None,
    }


def _memory_incidents(
    runtime: Mapping[str, Any],
    *,
    safe: Mapping[str, Any],
    rebuild: Mapping[str, Any],
    pending: bool,
) -> list[dict[str, Any]]:
    if safe.get("enabled") is not True or safe.get("state") in {"disabled", "ready"}:
        return []
    code = _safe_code(safe.get("code"), "memoryos_status_unverifiable")
    available = bool(rebuild.get("available")) and not pending
    incident_id = (
        str(rebuild.get("incident_id"))
        if isinstance(rebuild.get("incident_id"), str)
        else f"incident_{_canonical_hash({'memory': memoryos_incident_guard(runtime)})[:32]}"
    )
    state = str(safe.get("state") or "degraded")
    if state == "rebuilding" or pending:
        title = "MemoryOS derived index is rebuilding"
        detail = "Room delivery remains available while the derived archive index is rebuilt."
    elif state == "recovering":
        title = "MemoryOS is recovering"
        detail = "Room delivery remains available while the optional memory sidecar retries."
    else:
        title = "Optional memory index is degraded"
        detail = "Room causal delivery remains available while archive sync and recall wait."
    return [
        {
            "incident_id": incident_id,
            "kind": "memory",
            "severity": "attention",
            "code": code,
            "title": title,
            "detail": detail,
            "started_at": None,
            "conversation_id": None,
            "conversation_title": None,
            "participant_id": None,
            "participant_display_name": None,
            "observation_id": None,
            "next_action": "rebuild_memory_index" if available else "wait",
        }
    ]


def _runtime_incidents(
    runtime: Mapping[str, Any], safe_runtime: Mapping[str, Any], recover: Mapping[str, Any]
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    state = str(runtime.get("state") or "unknown")
    code = _safe_code(runtime.get("code"), "room_runtime_unverifiable")
    guard = str(recover["guard"])
    null_refs = {
        "conversation_id": None,
        "conversation_title": None,
        "participant_id": None,
        "participant_display_name": None,
        "observation_id": None,
    }
    if state != "ready":
        incidents.append(
            {
                "incident_id": guard,
                "kind": "runtime",
                "severity": "blocked",
                "code": code,
                "title": "Room runtime needs attention",
                "detail": "The local Room runtime is not ready.",
                "started_at": None,
                **null_refs,
                "next_action": "recover_runtime" if recover["available"] else "wait",
            }
        )
    host = safe_runtime["host"]
    if host["state"] in {"blocked", "attention"}:
        host_code = str(host["code"])
        host_incident_id = f"incident_{_canonical_hash({'guard': guard, 'host': host_code})[:32]}"
        if host["state"] == "blocked":
            host_title = "Room host is blocked"
            host_detail = "The Room host reported a durable operational condition."
        elif host_code == "room_memory_degraded":
            host_title = "Optional memory index is degraded"
            host_detail = (
                "Room causal delivery remains available while archive sync and recall "
                "wait for MemoryOS."
            )
        else:
            host_title = "Room host cleanup is pending"
            host_detail = "The Room host reported a durable operational condition."
        incidents.append(
            {
                "incident_id": host_incident_id,
                "kind": "host",
                "severity": host["state"],
                "code": host_code,
                "title": host_title,
                "detail": host_detail,
                "started_at": None,
                **null_refs,
                "next_action": "repair_then_recover" if host["state"] == "blocked" else "wait",
            }
        )
    return incidents


def _observation_rows(
    db_path: Path,
) -> tuple[dict[str, int], int, list[dict[str, Any]]]:
    zero = {
        "recovery_pending": 0,
        "cancel_pending": 0,
        "provider_cleanup_pending": 0,
        "exhausted": 0,
    }
    if not db_path.is_file():
        return zero, 0, []
    with RoomDatabase(db_path).connect(readonly=True) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("select name from sqlite_schema where type = 'table'")
        }
        required = {
            "room_observations",
            "room_observation_attempts",
            "participants",
            "conversations",
        }
        if not required.issubset(tables):
            return zero, 0, []
        has_batches = {
            "room_observation_batches",
            "room_observation_batch_members",
        }.issubset(tables)
        batch_join = (
            "left join room_observation_batch_members batch_member "
            "on batch_member.observation_id = o.observation_id "
            "left join room_observation_batches batch "
            "on batch.batch_id = batch_member.batch_id"
            if has_batches
            else ""
        )
        canonical_predicate = (
            "and (batch.primary_observation_id is null "
            "or batch.primary_observation_id = o.observation_id)"
            if has_batches
            else ""
        )
        aggregate = conn.execute(
            f"""
            select
              coalesce(sum(case when a.recovery_state in ('fenced','cleanup_pending')
                                then 1 else 0 end), 0) as recovery_pending,
              coalesce(sum(case when o.control_state in ('cancel_requested','cancel_pending')
                                then 1 else 0 end), 0) as cancel_pending,
              coalesce(sum(case when a.provider_phase = 'cleanup_pending'
                                then 1 else 0 end), 0) as provider_cleanup_pending,
              coalesce(sum(case when o.control_state = 'exhausted'
                                then 1 else 0 end), 0) as exhausted,
              coalesce(sum(case when a.reason_code = 'room_skill_catalog_drift'
                                  or a.recovery_state in ('fenced','cleanup_pending')
                                  or o.control_state in (
                                      'cancel_requested','cancel_pending','exhausted'
                                  )
                                  or a.provider_phase = 'cleanup_pending'
                                then 1 else 0 end), 0) as incident_total
              from room_observations o
              join participants p on p.participant_id = o.participant_id
              left join room_observation_attempts a
                on a.attempt_id = o.current_attempt_id
              {batch_join}
             where o.status <> 'completed'
               and p.cli_kind = 'codex'
               {canonical_predicate}
            """
        ).fetchone()
        assert aggregate is not None
        counts = {key: int(aggregate[key]) for key in zero}
        incident_total = int(aggregate["incident_total"])
        rows = conn.execute(
            f"""
            select o.observation_id, o.conversation_id, c.title as conversation_title,
                   o.participant_id, p.display_name as participant_display_name,
                   o.control_state, o.status as observation_status, o.updated_at,
                   a.state as attempt_state, a.reason_code as attempt_reason_code,
                   a.provider_phase, a.provider_phase_updated_at,
                   a.recovery_state, a.recovery_started_at
              from room_observations o
              join conversations c on c.id = o.conversation_id
              join participants p on p.participant_id = o.participant_id
              left join room_observation_attempts a on a.attempt_id = o.current_attempt_id
              {batch_join}
             where o.status <> 'completed'
               and p.cli_kind = 'codex'
               {canonical_predicate}
               and (a.reason_code = 'room_skill_catalog_drift'
                    or o.control_state in ('cancel_requested','cancel_pending','exhausted')
                    or a.recovery_state in ('fenced','cleanup_pending')
                    or a.provider_phase = 'cleanup_pending')
             order by case
                        when a.reason_code = 'room_skill_catalog_drift' then 1
                        when a.recovery_state in ('fenced','cleanup_pending') then 2
                        when o.control_state in ('cancel_requested','cancel_pending') then 3
                        when a.provider_phase = 'cleanup_pending' then 4
                        else 5
                      end asc,
                      coalesce(
                        a.recovery_started_at, a.provider_phase_updated_at, o.updated_at
                      ) asc,
                      o.observation_id asc
             limit 20
            """
        ).fetchall()
    incidents: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        skill_blocker = item.get("attempt_reason_code") == "room_skill_catalog_drift"
        recovery = item.get("recovery_state") in {"fenced", "cleanup_pending"}
        cancel = item.get("control_state") in {"cancel_requested", "cancel_pending"}
        provider = item.get("provider_phase") == "cleanup_pending"
        if skill_blocker:
            code, title, detail, next_action, started = (
                str(item["attempt_reason_code"]),
                "Agent Skill runtime is blocked",
                "The selected Agent cannot continue until its Skill runtime is repaired.",
                "repair_then_recover",
                item.get("updated_at"),
            )
        elif recovery:
            code, title, detail, next_action, started = (
                "room_runner_recovery_cleanup_pending",
                "Runner recovery cleanup is pending",
                "A fenced delivery is waiting for provider cleanup.",
                "wait",
                item.get("recovery_started_at"),
            )
        elif cancel:
            code, title, detail, next_action, started = (
                "room_observation_cancel_pending",
                "Agent cancellation is pending",
                "The selected Agent delivery is still being cleaned up.",
                "open_room",
                item.get("updated_at"),
            )
        elif provider:
            code, title, detail, next_action, started = (
                "room_provider_cleanup_pending",
                "Provider cleanup is pending",
                "The selected Agent delivery cannot continue until cleanup is proven.",
                "wait",
                item.get("provider_phase_updated_at"),
            )
        else:
            code, title, detail, next_action, started = (
                "room_observation_exhausted",
                "Agent attempt budget is exhausted",
                "A manual retry is available from the Room inspector.",
                "retry_observation",
                item.get("updated_at"),
            )
        safe_refs = {
            "conversation_id": item["conversation_id"],
            "conversation_title": item["conversation_title"],
            "participant_id": item["participant_id"],
            "participant_display_name": item["participant_display_name"],
            "observation_id": item["observation_id"],
        }
        incidents.append(
            {
                "incident_id": f"incident_{_canonical_hash({'code': code, **safe_refs})[:32]}",
                "kind": "observation",
                "severity": "blocked" if skill_blocker else "attention",
                "code": code,
                "title": title,
                "detail": detail,
                "started_at": started,
                **safe_refs,
                "next_action": next_action,
            }
        )
    return counts, incident_total, incidents


def build_room_operations_projection(
    db_path: Path | str,
    runtime: Mapping[str, Any],
    *,
    memory_runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    safe_runtime = _safe_runtime(runtime)
    recover = runtime_recoverability(runtime)
    memory_private = memory_runtime or safe_memoryos_status(None)
    safe_memory = _safe_memory_runtime(memory_private)
    safe_runtime = {**safe_runtime, "memory": safe_memory}
    memory_rebuild = memoryos_rebuildability(memory_private)
    try:
        latest_memory_action = RoomMemoryRebuildActionStore(db_path).latest()
    except (OSError, sqlite3.Error, RoomDatabaseError, ValueError):
        latest_memory_action = None
    pending_memory_action = bool(
        latest_memory_action is not None and latest_memory_action.get("status") == "requested"
    )
    same_terminal_incident = bool(
        latest_memory_action is not None
        and latest_memory_action.get("status") != "requested"
        and latest_memory_action.get("_incident_guard") == memory_rebuild.get("incident_id")
    )
    db_counts, observation_incident_total, observation_incidents = _observation_rows(Path(db_path))
    counts = {
        "active_delivery": safe_runtime["host"]["active_delivery_count"],
        "retained_cleanup": safe_runtime["host"]["retained_cleanup_count"],
        **db_counts,
    }
    memory_incidents = _memory_incidents(
        memory_private,
        safe=safe_memory,
        rebuild=memory_rebuild,
        pending=pending_memory_action,
    )
    runtime_incidents = _runtime_incidents(runtime, safe_runtime, recover)
    if memory_incidents:
        runtime_incidents = [
            item
            for item in runtime_incidents
            if not (item["kind"] == "host" and item["code"] == "room_memory_degraded")
        ]
    incidents = runtime_incidents + memory_incidents + observation_incidents
    abnormal_count = any(
        counts[key] > 0
        for key in (
            "retained_cleanup",
            "recovery_pending",
            "cancel_pending",
            "provider_cleanup_pending",
            "exhausted",
        )
    )
    severity = (
        "blocked"
        if any(item["severity"] == "blocked" for item in incidents)
        else "attention"
        if incidents or abnormal_count
        else "healthy"
    )
    return {
        "schema_version": OPERATIONS_SCHEMA,
        "generated_at": _timestamp(),
        "overall": severity,
        "runtime": safe_runtime,
        "counts": counts,
        "incident_total": len(incidents) - len(observation_incidents) + observation_incident_total,
        "incidents": incidents[:20],
        "actions": {
            "recover_runtime": {
                "available": bool(recover["available"]),
                "method": "POST",
                "href": "/api/chat/operator/room-runtime/recover",
                "expected_incident_id": recover["guard"] if recover["available"] else "",
                "mode": recover["mode"],
                "confirmation_required": True,
            },
            "rebuild_memory_index": {
                "available": bool(memory_rebuild.get("available"))
                and not pending_memory_action
                and not same_terminal_incident,
                "pending": pending_memory_action,
                "status": (
                    str(latest_memory_action.get("status"))
                    if latest_memory_action is not None
                    else None
                ),
                "phase": (
                    str(latest_memory_action.get("phase"))
                    if latest_memory_action is not None
                    else None
                ),
                "method": "POST",
                "href": "/api/chat/operator/memory-runtime/rebuild",
                "expected_incident_id": (
                    memory_rebuild.get("incident_id")
                    if memory_rebuild.get("available")
                    and not pending_memory_action
                    and not same_terminal_incident
                    else None
                ),
                "confirmation_required": True,
            },
        },
        "proof_boundary": "derived_from_room_runtime_and_chat_db_not_authority",
    }


class RoomRuntimeOperatorActionStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def reserve(
        self,
        *,
        client_action_id: str,
        request_fingerprint: str,
        incident_guard: str,
        before_state: str,
        before_code: str,
    ) -> tuple[dict[str, Any], bool]:
        stamp = _timestamp()
        with self._connect() as conn:
            conn.execute("begin immediate")
            existing = conn.execute(
                "select * from room_runtime_operator_actions where client_action_id = ?",
                (client_action_id,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request_fingerprint:
                    raise ValueError("room_runtime_action_idempotency_conflict")
                conn.commit()
                return self._view(row), False
            inflight = conn.execute(
                """select client_action_id from room_runtime_operator_actions
                     where status = 'requested' limit 1"""
            ).fetchone()
            status = "rejected" if inflight is not None else "requested"
            reason = "room_runtime_recovery_in_progress" if inflight is not None else None
            action_id = f"rta_{uuid.uuid4().hex}"
            conn.execute(
                """insert into room_runtime_operator_actions (
                    action_id, client_action_id, operator_identity, request_fingerprint,
                    incident_guard, status, before_state, before_code, reason_code,
                    requested_at, updated_at
                ) values (?, ?, 'operator:local', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id,
                    client_action_id,
                    request_fingerprint,
                    incident_guard,
                    status,
                    before_state,
                    before_code,
                    reason,
                    stamp,
                    stamp,
                ),
            )
            row = conn.execute(
                "select * from room_runtime_operator_actions where action_id = ?", (action_id,)
            ).fetchone()
            conn.commit()
        assert row is not None
        return self._view(dict(row)), True

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
        if status not in _ACTION_STATUSES - {"requested"}:
            raise ValueError("room_runtime_action_status_invalid")
        stamp = _timestamp()
        encoded = (
            json.dumps(dict(result), sort_keys=True, separators=(",", ":")) if result else None
        )
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select * from room_runtime_operator_actions where client_action_id = ?",
                (client_action_id,),
            ).fetchone()
            if row is None:
                raise ValueError("room_runtime_action_not_found")
            if row["status"] != "requested":
                conn.commit()
                return self._view(dict(row))
            conn.execute(
                """update room_runtime_operator_actions
                      set status = ?, after_state = ?, after_code = ?, result_json = ?,
                          reason_code = ?, applied_at = ?, updated_at = ?
                    where client_action_id = ? and status = 'requested'""",
                (
                    status,
                    after_state,
                    after_code,
                    encoded,
                    reason_code,
                    stamp,
                    stamp,
                    client_action_id,
                ),
            )
            updated = conn.execute(
                "select * from room_runtime_operator_actions where client_action_id = ?",
                (client_action_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return self._view(dict(updated))

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    @staticmethod
    def _view(row: Mapping[str, Any]) -> dict[str, Any]:
        result = json.loads(row["result_json"]) if row.get("result_json") else None
        return {
            "schema_version": RECOVER_RESULT_SCHEMA,
            "action_id": row["action_id"],
            "client_action_id": row["client_action_id"],
            "status": row["status"],
            "before": {"state": row["before_state"], "code": row["before_code"]},
            "after": {"state": row.get("after_state"), "code": row.get("after_code")},
            "reason_code": row.get("reason_code"),
            "result": result,
            "requested_at": row["requested_at"],
            "applied_at": row.get("applied_at"),
        }
