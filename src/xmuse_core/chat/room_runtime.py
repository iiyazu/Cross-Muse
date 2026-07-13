"""Room-only runtime loop and process-readiness receipt helpers.

The receipt is deliberately operational evidence, not Room or provider truth.  Durable
conversation authority remains in ``chat.db``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import tempfile
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ROOM_RUNNER_STATUS_SCHEMA_V1 = "room_runner_status/v1"
ROOM_RUNNER_STATUS_SCHEMA = "room_runner_status/v2"
ROOM_RUNNER_STATUS_NAME = "room-runner-status.json"
ROOM_RUNNER_LOCK_NAME = ".xmuse-room-runner.lock"
ROOM_RUNNER_HEARTBEAT_INTERVAL_S = 5.0
ROOM_RUNNER_HEARTBEAT_TTL_S = 20.0
ROOM_RUNNER_STARTUP_WAIT_S = 15.0
ROOM_RUNNER_PROOF_BOUNDARY = "room_runner_status_not_room_or_provider_outcome_authority"
ROOM_MCP_SURFACE = "room"
ROOM_MCP_PATH = "/mcp/room"
ROOM_RUNNER_READINESS_KEYS = (
    "chat_db",
    "skill_catalog",
    "mcp_health",
    "mcp_tools",
    "persistent_launcher",
    "host_loop",
)

RoomRunnerState = Literal["starting", "ready", "stopping", "stopped", "failed"]

_STATES = frozenset({"starting", "ready", "stopping", "stopped", "failed"})
_STATUS_KEYS_V1 = frozenset(
    {
        "schema_version",
        "generation",
        "xmuse_root",
        "pid",
        "start_identity",
        "boot_id",
        "state",
        "started_at",
        "updated_at",
        "heartbeat_at",
        "mcp",
        "readiness",
        "error",
        "proof_boundary",
    }
)
_STATUS_KEYS_V2 = (_STATUS_KEYS_V1 - {"xmuse_root"}) | {"host"}
_HOST_STATES = frozenset({"healthy", "attention", "blocked"})
_HOST_ATTENTION_CODES = frozenset({"room_transport_cleanup_pending", "room_memory_degraded"})
_HOST_KEYS = frozenset({"state", "code", "active_delivery_count", "retained_cleanup_count"})
_UNKNOWN_HOST = {
    "state": "unknown",
    "code": "room_runner_host_health_unknown",
    "active_delivery_count": 0,
    "retained_cleanup_count": 0,
}
_MAX_HOST_COUNT = 2**31 - 1
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_MAX_STATUS_BYTES = 64 * 1024

logger = logging.getLogger(__name__)


class RoomRunnerStatusError(RuntimeError):
    """A stable failure while reading or writing a Room Runner receipt."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def room_runner_status_path(xmuse_root: Path | str) -> Path:
    return Path(xmuse_root).expanduser().resolve() / ROOM_RUNNER_STATUS_NAME


def room_runner_lock_path(xmuse_root: Path | str) -> Path:
    return Path(xmuse_root).expanduser().resolve() / ROOM_RUNNER_LOCK_NAME


def read_process_start_identity(pid: int) -> str | None:
    """Return the Linux process start identity used to fence PID reuse."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        stat_text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    command_end = stat_text.rfind(")")
    if command_end < 0:
        return None
    fields_after_command = stat_text[command_end + 2 :].split()
    try:
        process_state = fields_after_command[0]
        start_ticks = fields_after_command[19]
    except IndexError:
        return None
    if process_state in {"Z", "X", "x"}:
        return None
    if not start_ticks.isdigit():
        return None
    return f"linux-proc-starttime:{start_ticks}"


def read_room_runner_status(xmuse_root: Path | str) -> dict[str, Any] | None:
    """Read a bounded receipt without treating it as authority."""

    return _read_room_runner_status_file(room_runner_status_path(xmuse_root))


def _read_room_runner_status_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        if path.is_symlink():
            raise RoomRunnerStatusError("room_runner_status_symlink_rejected")
        raw = path.read_bytes()
    except RoomRunnerStatusError:
        raise
    except OSError as exc:
        raise RoomRunnerStatusError("room_runner_status_unreadable") from exc
    if len(raw) > _MAX_STATUS_BYTES:
        raise RoomRunnerStatusError("room_runner_status_too_large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoomRunnerStatusError("room_runner_status_invalid_json") from exc
    if not isinstance(payload, dict):
        raise RoomRunnerStatusError("room_runner_status_invalid_shape")
    return payload


def write_room_runner_status(
    xmuse_root: Path | str,
    *,
    generation: str,
    pid: int,
    start_identity: str,
    boot_id: str,
    state: RoomRunnerState,
    started_at: str,
    mcp_port: int,
    readiness: Mapping[str, bool],
    host: Mapping[str, Any],
    error_code: str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Atomically replace the Room Runner operational receipt."""

    root = Path(xmuse_root).expanduser().resolve()
    stamp = _timestamp(now)
    payload: dict[str, Any] = {
        "schema_version": ROOM_RUNNER_STATUS_SCHEMA,
        "generation": generation,
        "pid": pid,
        "start_identity": start_identity,
        "boot_id": boot_id,
        "state": state,
        "started_at": started_at,
        "updated_at": stamp,
        "heartbeat_at": stamp,
        "mcp": {
            "surface": ROOM_MCP_SURFACE,
            "path": ROOM_MCP_PATH,
            "port": mcp_port,
        },
        "readiness": dict(readiness),
        "host": dict(host),
        "error": {"code": error_code} if error_code is not None else None,
        "proof_boundary": ROOM_RUNNER_PROOF_BOUNDARY,
    }
    code = _status_shape_error(payload, expected_root=root)
    if code is not None:
        raise RoomRunnerStatusError(code)

    root.mkdir(parents=True, exist_ok=True)
    path = room_runner_status_path(root)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=root,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)
    return payload


def assess_room_runner_status(
    xmuse_root: Path | str,
    *,
    expected_generation: str,
    expected_pid: int | None = None,
    expected_start_identity: str | None = None,
    now: datetime | str | None = None,
    heartbeat_ttl_s: float = ROOM_RUNNER_HEARTBEAT_TTL_S,
    process_identity_reader: Callable[[int], str | None] = read_process_start_identity,
    status_path: Path | str | None = None,
) -> dict[str, Any]:
    """Strictly assess whether a receipt proves this exact process is ready."""

    root = Path(xmuse_root).expanduser().resolve()
    if not _valid_id(expected_generation):
        return _assessment("room_runner_expected_generation_invalid")
    if expected_pid is not None and (
        isinstance(expected_pid, bool) or not isinstance(expected_pid, int) or expected_pid <= 0
    ):
        return _assessment("room_runner_expected_pid_invalid")
    if expected_start_identity is not None and (
        not isinstance(expected_start_identity, str)
        or re.fullmatch(r"linux-proc-starttime:[0-9]+", expected_start_identity) is None
    ):
        return _assessment("room_runner_expected_start_identity_invalid")
    if (
        isinstance(heartbeat_ttl_s, bool)
        or not isinstance(heartbeat_ttl_s, (int, float))
        or not math.isfinite(float(heartbeat_ttl_s))
        or float(heartbeat_ttl_s) <= 0
    ):
        return _assessment("room_runner_heartbeat_ttl_invalid")
    try:
        payload = _read_room_runner_status_file(
            Path(status_path).expanduser().absolute()
            if status_path is not None
            else room_runner_status_path(root)
        )
    except RoomRunnerStatusError as exc:
        return _assessment(exc.code)
    if payload is None:
        return _assessment("room_runner_status_missing")

    shape_error = _status_shape_error(payload, expected_root=root)
    if shape_error is not None:
        return _assessment(shape_error, payload=payload)
    state = str(payload["state"])
    host = _normalized_host(payload)
    if payload["generation"] != expected_generation:
        return _assessment(
            "room_runner_generation_mismatch", state=state, payload=payload, host=host
        )
    if expected_pid is not None and payload["pid"] != expected_pid:
        return _assessment("room_runner_pid_mismatch", state=state, payload=payload, host=host)
    if expected_start_identity is not None and payload["start_identity"] != expected_start_identity:
        return _assessment(
            "room_runner_start_identity_mismatch", state=state, payload=payload, host=host
        )
    try:
        observed_identity = process_identity_reader(payload["pid"])
    except Exception:
        observed_identity = None
    if observed_identity is None:
        return _assessment("room_runner_process_not_live", state=state, payload=payload, host=host)
    if observed_identity != payload["start_identity"]:
        return _assessment(
            "room_runner_process_identity_mismatch", state=state, payload=payload, host=host
        )

    stamp = _parse_timestamp(payload["heartbeat_at"])
    current = _as_datetime(now)
    age_s = (current - stamp).total_seconds()
    if age_s < -5.0:
        return _assessment(
            "room_runner_heartbeat_in_future", state=state, payload=payload, host=host
        )
    if age_s > float(heartbeat_ttl_s):
        return _assessment("room_runner_heartbeat_stale", state=state, payload=payload, host=host)
    if state != "ready":
        return _assessment("room_runner_state_not_ready", state=state, payload=payload, host=host)
    if not all(payload["readiness"].values()):
        return _assessment(
            "room_runner_readiness_incomplete", state=state, payload=payload, host=host
        )
    if payload["error"] is not None:
        return _assessment("room_runner_ready_with_error", state=state, payload=payload, host=host)
    if host["state"] == "blocked":
        return _assessment("room_runner_host_blocked", state=state, payload=payload, host=host)
    return _assessment("ready", ready=True, state=state, payload=payload, host=host)


async def run_room_participant_host_loop(
    room_host: Any,
    *,
    stop: asyncio.Event,
    max_concurrent_rooms: int,
    idle_wait_s: float = 1.0,
    started: asyncio.Event | None = None,
) -> None:
    """Fairly pump distinct claimable rooms with bounded cross-room concurrency."""

    if (
        isinstance(max_concurrent_rooms, bool)
        or not isinstance(max_concurrent_rooms, int)
        or max_concurrent_rooms <= 0
    ):
        raise ValueError("room_host_max_concurrent_rooms_invalid")
    if (
        isinstance(idle_wait_s, bool)
        or not isinstance(idle_wait_s, (int, float))
        or not math.isfinite(float(idle_wait_s))
        or idle_wait_s <= 0
    ):
        raise ValueError("room_host_idle_wait_invalid")

    active: dict[str, asyncio.Task[Any]] = {}
    waiting: deque[str] = deque()
    stop_task = asyncio.create_task(stop.wait(), name="xmuse-room-host-stop")
    if started is not None:
        started.set()
    try:
        while not stop.is_set():
            _reap_room_pump_tasks(active)
            reconcile_controls = getattr(room_host, "reconcile_controls", None)
            if callable(reconcile_controls):
                await reconcile_controls()
            reconcile_runner_recoveries = getattr(room_host, "reconcile_runner_recoveries", None)
            if callable(reconcile_runner_recoveries):
                await reconcile_runner_recoveries()
            claimable = room_host.list_claimable_conversation_ids()
            claimable_set = set(claimable)
            waiting = deque(
                conversation_id
                for conversation_id in waiting
                if conversation_id in claimable_set and conversation_id not in active
            )
            queued = set(waiting)
            for conversation_id in claimable:
                if conversation_id in active or conversation_id in queued:
                    continue
                waiting.append(conversation_id)
                queued.add(conversation_id)

            while waiting and len(active) < max_concurrent_rooms:
                conversation_id = waiting.popleft()
                active[conversation_id] = asyncio.create_task(
                    _pump_room_conversation(room_host, conversation_id=conversation_id),
                    name=f"xmuse-room-pump:{conversation_id}",
                )

            waiters: set[asyncio.Task[Any]] = set(active.values())
            waiters.add(stop_task)
            await asyncio.wait(
                waiters,
                timeout=float(idle_wait_s),
                return_when=asyncio.FIRST_COMPLETED,
            )
    finally:
        for task in active.values():
            task.cancel()
        if active:
            await asyncio.gather(*active.values(), return_exceptions=True)
        if not stop_task.done():
            stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


def _reap_room_pump_tasks(active: dict[str, asyncio.Task[Any]]) -> None:
    for conversation_id, task in list(active.items()):
        if not task.done():
            continue
        active.pop(conversation_id)
        try:
            task.result()
        except asyncio.CancelledError:
            continue
        except Exception:
            logger.exception(
                "room participant host tick failed for conversation %s",
                conversation_id,
            )


async def _pump_room_conversation(room_host: Any, *, conversation_id: str) -> None:
    outcome = await room_host.pump_once(conversation_id=conversation_id)
    if outcome.deliveries:
        logger.info(
            "Room participant host delivered conversation=%s completed=%d total=%d",
            conversation_id,
            sum(item.state == "completed" for item in outcome.deliveries),
            len(outcome.deliveries),
        )


def _status_shape_error(payload: Mapping[str, Any], *, expected_root: Path) -> str | None:
    schema = payload.get("schema_version")
    expected_keys = (
        _STATUS_KEYS_V1
        if schema == ROOM_RUNNER_STATUS_SCHEMA_V1
        else _STATUS_KEYS_V2
        if schema == ROOM_RUNNER_STATUS_SCHEMA
        else None
    )
    if expected_keys is None:
        return "room_runner_status_schema_mismatch"
    if set(payload) != expected_keys:
        return "room_runner_status_invalid_shape"
    if not _valid_id(payload.get("generation")):
        return "room_runner_generation_invalid"
    if schema == ROOM_RUNNER_STATUS_SCHEMA_V1:
        root = payload.get("xmuse_root")
        if not isinstance(root, str) or root != str(expected_root):
            return "room_runner_root_mismatch"
    pid = payload.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return "room_runner_pid_invalid"
    identity = payload.get("start_identity")
    if not isinstance(identity, str) or not re.fullmatch(r"linux-proc-starttime:[0-9]+", identity):
        return "room_runner_start_identity_invalid"
    if not _valid_id(payload.get("boot_id")):
        return "room_runner_boot_id_invalid"
    state = payload.get("state")
    if state not in _STATES:
        return "room_runner_state_invalid"
    try:
        started = _parse_timestamp(payload.get("started_at"))
        heartbeat = _parse_timestamp(payload.get("heartbeat_at"))
        updated = _parse_timestamp(payload.get("updated_at"))
    except (TypeError, ValueError):
        return "room_runner_timestamp_invalid"
    if heartbeat < started or updated < heartbeat:
        return "room_runner_timestamp_order_invalid"
    mcp = payload.get("mcp")
    if not isinstance(mcp, dict) or set(mcp) != {"surface", "path", "port"}:
        return "room_runner_mcp_invalid"
    port = mcp.get("port")
    if (
        mcp.get("surface") != ROOM_MCP_SURFACE
        or mcp.get("path") != ROOM_MCP_PATH
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not (1 <= port <= 65_535)
    ):
        return "room_runner_mcp_invalid"
    readiness = payload.get("readiness")
    if not isinstance(readiness, dict) or set(readiness) != set(ROOM_RUNNER_READINESS_KEYS):
        return "room_runner_readiness_invalid"
    if any(not isinstance(value, bool) for value in readiness.values()):
        return "room_runner_readiness_invalid"
    error = payload.get("error")
    if error is not None and (
        not isinstance(error, dict)
        or set(error) != {"code"}
        or not isinstance(error.get("code"), str)
        or _SAFE_ERROR.fullmatch(error["code"]) is None
    ):
        return "room_runner_error_invalid"
    if state == "failed" and error is None:
        return "room_runner_failed_error_missing"
    if state == "ready" and (error is not None or not all(readiness.values())):
        return "room_runner_ready_invalid"
    if schema == ROOM_RUNNER_STATUS_SCHEMA:
        host_error = _host_shape_error(payload.get("host"))
        if host_error is not None:
            return host_error
    if payload.get("proof_boundary") != ROOM_RUNNER_PROOF_BOUNDARY:
        return "room_runner_proof_boundary_invalid"
    return None


def _assessment(
    code: str,
    *,
    ready: bool = False,
    state: str = "unknown",
    payload: Mapping[str, Any] | None = None,
    host: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ready": ready,
        "code": code,
        "state": state,
        "status": dict(payload) if payload is not None else None,
        "host": dict(host) if host is not None else dict(_UNKNOWN_HOST),
    }


def _host_shape_error(value: Any) -> str | None:
    if not isinstance(value, dict) or set(value) != _HOST_KEYS:
        return "room_runner_host_invalid"
    if value.get("state") not in _HOST_STATES:
        return "room_runner_host_invalid"
    code = value.get("code")
    if not isinstance(code, str) or _SAFE_ERROR.fullmatch(code) is None:
        return "room_runner_host_invalid"
    if value["state"] == "healthy" and code != "ready":
        return "room_runner_host_invalid"
    if value["state"] == "attention" and code not in _HOST_ATTENTION_CODES:
        return "room_runner_host_invalid"
    if value["state"] == "blocked" and code in {
        "ready",
        "room_transport_cleanup_pending",
    }:
        return "room_runner_host_invalid"
    for key in ("active_delivery_count", "retained_cleanup_count"):
        count = value.get(key)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or count > _MAX_HOST_COUNT
        ):
            return "room_runner_host_invalid"
    return None


def _normalized_host(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") == ROOM_RUNNER_STATUS_SCHEMA_V1:
        return dict(_UNKNOWN_HOST)
    return dict(payload["host"])


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _timestamp(value: datetime | str | None) -> str:
    stamp = _as_datetime(value)
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _as_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        return _parse_timestamp(value)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("room_runner_timestamp_timezone_required")
    return value.astimezone(UTC)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("room_runner_timestamp_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("room_runner_timestamp_timezone_required")
    return parsed.astimezone(UTC)


__all__ = [
    "ROOM_MCP_PATH",
    "ROOM_MCP_SURFACE",
    "ROOM_RUNNER_HEARTBEAT_INTERVAL_S",
    "ROOM_RUNNER_HEARTBEAT_TTL_S",
    "ROOM_RUNNER_LOCK_NAME",
    "ROOM_RUNNER_PROOF_BOUNDARY",
    "ROOM_RUNNER_READINESS_KEYS",
    "ROOM_RUNNER_STARTUP_WAIT_S",
    "ROOM_RUNNER_STATUS_NAME",
    "ROOM_RUNNER_STATUS_SCHEMA",
    "ROOM_RUNNER_STATUS_SCHEMA_V1",
    "RoomRunnerStatusError",
    "assess_room_runner_status",
    "read_process_start_identity",
    "read_room_runner_status",
    "room_runner_lock_path",
    "room_runner_status_path",
    "run_room_participant_host_loop",
    "write_room_runner_status",
]
