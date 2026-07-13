from __future__ import annotations

import fcntl
import json
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from xmuse_core.chat.room_runtime import read_room_runner_status
from xmuse_core.chat.room_runtime_supervisor import (
    ROOM_RUNTIME_SCHEMA,
    RoomRuntimeStartError,
    RoomRuntimeSupervisorConfig,
    ensure_room_runtime,
    inspect_room_runtime,
    stop_room_runtime,
    stop_runtime_pids,
)
from xmuse_core.runtime.processes import discover_xmuse_runtime_processes

REPO_ROOT = Path(__file__).resolve().parents[1]
WorkroomRuntimeStarter = Callable[[Path, Path], dict[str, object]]
WorkroomRuntimeStopper = Callable[[Path], dict[str, object]]
WorkroomRuntimeInspector = Callable[[Path, Path], dict[str, object]]
WorkroomRuntimeRecoverer = Callable[[Path, Path, str], dict[str, object]]
_WORKROOM_RUNTIME_START_LOCK_NAME = ".workroom_room_runtime.start.lock"
_WORKROOM_RUNTIME_THREAD_LOCKS: dict[str, threading.Lock] = {}
_WORKROOM_RUNTIME_THREAD_LOCKS_GUARD = threading.Lock()
_DIRECT_RUNTIME_GENERATIONS: dict[str, str] = {}
logger = logging.getLogger(__name__)


def _workroom_mcp_port(base_dir: Path) -> int:
    for path, flag in (
        (base_dir / "workroom_room_runner.pid.json", "--mcp-port"),
        (base_dir / "workroom_room_mcp.pid.json", "--port"),
        (base_dir / "workroom_peer_runtime.pid.json", "--mcp-port"),
        (base_dir / "workroom_mcp_server.pid.json", "--port"),
    ):
        payload = _read_json_file(path, {})
        port = _command_int_arg(payload.get("command"), flag)
        if port is not None:
            return port
    if _loopback_port_available(8100):
        return 8100
    return _allocate_loopback_port()


def _command_int_arg(command: Any, flag: str) -> int | None:
    if not isinstance(command, list):
        return None
    for index, item in enumerate(command):
        if item == flag and index + 1 < len(command):
            try:
                value = int(str(command[index + 1]))
            except ValueError:
                return None
            return value if value > 0 else None
        if isinstance(item, str) and item.startswith(f"{flag}="):
            try:
                value = int(item.split("=", 1)[1])
            except ValueError:
                return None
            return value if value > 0 else None
    return None


def _loopback_port_available(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return False
    except OSError:
        return True


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _workroom_runtime_thread_lock(base_dir: Path) -> threading.Lock:
    key = str(base_dir.resolve())
    with _WORKROOM_RUNTIME_THREAD_LOCKS_GUARD:
        return _WORKROOM_RUNTIME_THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _locked_workroom_runtime_start(base_dir: Path) -> Iterator[None]:
    """Serialize runtime discovery and startup for one XMUSE_ROOT."""
    base_dir.mkdir(parents=True, exist_ok=True)
    lock_path = base_dir / _WORKROOM_RUNTIME_START_LOCK_NAME
    with _workroom_runtime_thread_lock(base_dir):
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _workroom_room_generation(base_dir: Path) -> str:
    managed = os.environ.get("XMUSE_WORKROOM_GENERATION", "").strip()
    if managed:
        return managed
    status = read_room_runner_status(base_dir)
    if isinstance(status, dict):
        generation = status.get("generation")
        if isinstance(generation, str) and generation.strip():
            return generation
    for name in ("workroom_room_runner.pid.json", "workroom_room_mcp.pid.json"):
        payload = _read_json_file(base_dir / name, {})
        generation = payload.get("generation") if isinstance(payload, dict) else None
        if isinstance(generation, str) and generation.strip():
            return generation
    key = str(base_dir.resolve())
    return _DIRECT_RUNTIME_GENERATIONS.setdefault(key, uuid.uuid4().hex)


def _workroom_room_runtime_config(
    base_dir: Path,
    execution_root: Path,
    *,
    generation: str | None = None,
) -> RoomRuntimeSupervisorConfig:
    return RoomRuntimeSupervisorConfig(
        repo_root=REPO_ROOT,
        xmuse_root=base_dir,
        execution_worktree=execution_root,
        generation=generation or _workroom_room_generation(base_dir),
        mcp_port=_workroom_mcp_port(base_dir),
        delivery_timeout_s=180.0,
        runner_pid_file=base_dir / "workroom_room_runner.pid.json",
        mcp_pid_file=base_dir / "workroom_room_mcp.pid.json",
        runner_log_path=base_dir / "logs" / "workroom-room-runner.log",
        mcp_log_path=base_dir / "logs" / "workroom-room-mcp.log",
    )


def inspect_workroom_room_runtime(
    base_dir: Path,
    execution_root: Path = REPO_ROOT,
    *,
    generation: str | None = None,
) -> dict[str, object]:
    config = _workroom_room_runtime_config(
        base_dir,
        execution_root,
        generation=generation,
    )
    return inspect_room_runtime(config)


def ensure_workroom_room_runtime(
    base_dir: Path,
    execution_root: Path,
) -> dict[str, object]:
    """Single-flight entrypoint for the default Room-only runtime."""

    with _locked_workroom_runtime_start(base_dir):
        config = _workroom_room_runtime_config(base_dir, execution_root)
        try:
            return ensure_room_runtime(config)
        except RoomRuntimeStartError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc


def _inventory_service_pids(
    base_dir: Path,
    service_name: str,
    *,
    generation: str | None,
) -> list[int]:
    inventory = discover_xmuse_runtime_processes(
        xmuse_root=base_dir,
        workroom_generation=generation,
    )
    for service in inventory.get("services", []):
        if isinstance(service, dict) and service.get("service") == service_name:
            return [pid for pid in service.get("pids", []) if isinstance(pid, int)]
    return []


def stop_workroom_room_runtime(
    base_dir: Path,
    *,
    generation: str | None = None,
) -> dict[str, object]:
    """Stop new Room services and any same-scope legacy supervised services."""

    with _locked_workroom_runtime_start(base_dir):
        return _stop_workroom_room_runtime_locked(base_dir, generation=generation)


def _stop_workroom_room_runtime_locked(
    base_dir: Path,
    *,
    generation: str | None = None,
) -> dict[str, object]:
    resolved_generation = generation or _workroom_room_generation(base_dir)
    config = _workroom_room_runtime_config(
        base_dir,
        REPO_ROOT,
        generation=resolved_generation,
    )
    room = stop_room_runtime(config)

    legacy_pids = [
        *_inventory_service_pids(base_dir, "runner", generation=resolved_generation),
        *_inventory_service_pids(base_dir, "mcp", generation=resolved_generation),
    ]
    legacy_remaining = stop_runtime_pids(legacy_pids)
    if not legacy_remaining:
        (base_dir / "workroom_peer_runtime.pid.json").unlink(missing_ok=True)
        (base_dir / "workroom_mcp_server.pid.json").unlink(missing_ok=True)
    remaining = [*room.get("remaining_pids", []), *legacy_remaining]
    return {
        "schema_version": "workroom_room_runtime_stop/v1",
        "state": "stopped" if not remaining else "error",
        "generation": generation or resolved_generation,
        "room": room,
        "legacy": {
            "state": "stopped" if not legacy_remaining else "error",
            "term_pids": legacy_pids,
            "remaining_pids": legacy_remaining,
        },
        "authority": "backend_supervised_process",
    }


def recover_workroom_room_runtime(
    base_dir: Path,
    execution_root: Path,
    expected_incident_id: str,
) -> dict[str, object]:
    """Guard and recover one stable stopped/degraded Room runtime topology."""

    from xmuse_core.chat.room_operations import (
        runtime_incident_guard,
        runtime_recoverability,
    )

    with _locked_workroom_runtime_start(base_dir):
        config = _workroom_room_runtime_config(base_dir, execution_root)
        current = inspect_room_runtime(config)
        recoverability = runtime_recoverability(current)
        current_guard = runtime_incident_guard(current)
        if current_guard != expected_incident_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "room_runtime_incident_changed",
                    "message": "Room runtime state changed; refresh operations before recovering",
                },
            )
        if not recoverability["available"]:
            unverifiable_codes = {
                "room_runtime_unverifiable",
                "room_runner_process_identity_mismatch",
                "room_runner_process_not_live",
            }
            http_status = 503 if current.get("code") in unverifiable_codes else 409
            raise HTTPException(
                status_code=http_status,
                detail={
                    "code": "room_runtime_not_recoverable",
                    "message": "Room runtime recovery is not currently safe",
                },
            )
        before = {
            "state": str(current.get("state") or "unknown"),
            "code": str(current.get("code") or "room_runtime_unverifiable"),
        }
        if current.get("state") != "stopped":
            stopped = _stop_workroom_room_runtime_locked(
                base_dir,
                generation=config.generation,
            )
            if stopped.get("state") != "stopped":
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "room_runtime_stop_failed",
                        "message": "Room runtime could not be identity-fenced",
                    },
                )
        try:
            after = ensure_room_runtime(config)
        except RoomRuntimeStartError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        if after.get("ready") is not True:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": str(after.get("code") or "room_runtime_recovery_failed"),
                    "message": "Room runtime did not become ready after recovery",
                },
            )
        return {
            "schema_version": "workroom_room_runtime_recover/v1",
            "status": "applied",
            "before": before,
            "after": {
                "state": "ready",
                "code": str(after.get("code") or "ready"),
            },
        }


def should_autostart_workroom_runtime(
    request: Request,
    *,
    explicit_runtime_starter: bool,
) -> bool:
    if explicit_runtime_starter:
        return True
    return (request.client.host if request.client else "") != "testclient"


def start_workroom_runtime_for_message(
    runtime_starter: WorkroomRuntimeStarter,
    root: Path,
    execution_root: Path,
) -> dict[str, object]:
    try:
        return runtime_starter(root, execution_root)
    except HTTPException as exc:
        return {
            "schema_version": ROOM_RUNTIME_SCHEMA,
            "state": "error",
            "source": "message_autostart",
            "status_code": exc.status_code,
            "detail": exc.detail,
            "authority": "backend_supervised_process",
        }
    except Exception as exc:
        return {
            "schema_version": ROOM_RUNTIME_SCHEMA,
            "state": "error",
            "source": "message_autostart",
            "status_code": 500,
            "detail": {
                "code": "workroom_runtime_start_failed",
                "message": str(exc),
            },
            "authority": "backend_supervised_process",
        }


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
