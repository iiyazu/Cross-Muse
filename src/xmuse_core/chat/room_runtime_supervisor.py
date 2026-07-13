from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_runtime import (
    ROOM_RUNNER_HEARTBEAT_TTL_S,
    ROOM_RUNNER_STARTUP_WAIT_S,
    assess_room_runner_status,
    read_process_start_identity,
)
from xmuse_core.runtime.child_env import normalize_child_temp_env
from xmuse_core.runtime.processes import discover_xmuse_runtime_processes

ROOM_RUNTIME_SCHEMA = "workroom_room_runtime/v1"
ROOM_RUNTIME_STOP_SCHEMA = "workroom_room_runtime_stop/v1"


def room_mcp_health_ready(payload: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("status") == "ok"
        and payload.get("surface") == "room"
        and payload.get("endpoints") == {"mcp_room": "/mcp/room"}
    )


class RoomRuntimeStartError(RuntimeError):
    """A stable Room runtime supervision failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoomRuntimeSupervisorConfig:
    repo_root: Path
    xmuse_root: Path
    execution_worktree: Path
    generation: str
    mcp_port: int
    mcp_host: str = "127.0.0.1"
    max_concurrent_rooms: int = 4
    delivery_timeout_s: float = 180.0
    cleanup_grace_s: float = 8.0
    startup_wait_s: float = ROOM_RUNNER_STARTUP_WAIT_S
    heartbeat_ttl_s: float = ROOM_RUNNER_HEARTBEAT_TTL_S
    runner_pid_file: Path | None = None
    mcp_pid_file: Path | None = None
    runner_log_path: Path | None = None
    mcp_log_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.generation.strip():
            raise ValueError("Room runtime generation must not be empty")
        if self.mcp_port <= 0 or self.mcp_port > 65535:
            raise ValueError("Room MCP port must be between 1 and 65535")
        if self.startup_wait_s <= 0 or self.heartbeat_ttl_s <= 0:
            raise ValueError("Room runtime timeouts must be positive")


def room_runner_command(config: RoomRuntimeSupervisorConfig) -> list[str]:
    return [
        sys.executable,
        "xmuse/room_runner.py",
        "--xmuse-root",
        str(config.xmuse_root),
        "--generation",
        config.generation,
        "--mcp-port",
        str(config.mcp_port),
        "--max-concurrent-rooms",
        str(config.max_concurrent_rooms),
        "--delivery-timeout-s",
        str(config.delivery_timeout_s),
        "--cleanup-grace-s",
        str(config.cleanup_grace_s),
        "--worktree",
        str(config.execution_worktree),
    ]


def room_mcp_command(config: RoomRuntimeSupervisorConfig) -> list[str]:
    return [
        sys.executable,
        "xmuse/room_mcp_server.py",
        "--xmuse-root",
        str(config.xmuse_root),
        "--host",
        config.mcp_host,
        "--port",
        str(config.mcp_port),
        "--surface",
        "room",
    ]


def inspect_room_runtime(
    config: RoomRuntimeSupervisorConfig,
    *,
    now: datetime | str | None = None,
    http_health: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Return verified liveness/readiness without mutating runtime state."""

    inventory = discover_xmuse_runtime_processes(
        xmuse_root=config.xmuse_root,
        workroom_generation=config.generation,
    )
    runner_pids = _service_pids(inventory, "room_runner")
    mcp_pids = _service_pids(inventory, "room_mcp")
    runner_pid = runner_pids[0] if len(runner_pids) == 1 else None
    mcp_pid = mcp_pids[0] if len(mcp_pids) == 1 else None
    runner_identity = read_process_start_identity(runner_pid) if runner_pid is not None else None
    assessment = assess_room_runner_status(
        config.xmuse_root,
        expected_generation=config.generation,
        expected_pid=runner_pid,
        expected_start_identity=runner_identity,
        now=now,
        heartbeat_ttl_s=config.heartbeat_ttl_s,
    )
    health_reader = http_health or _read_http_json
    mcp_health = (
        health_reader(f"http://{config.mcp_host}:{config.mcp_port}/health")
        if mcp_pid is not None
        else None
    )
    mcp_ready = len(mcp_pids) == 1 and room_mcp_health_ready(mcp_health)
    runner_ready = len(runner_pids) == 1 and bool(assessment.get("ready"))
    raw_host = assessment.get("host")
    host = (
        dict(raw_host)
        if isinstance(raw_host, Mapping)
        else {
            "state": "unknown",
            "code": "room_host_unknown",
            "active_delivery_count": 0,
            "retained_cleanup_count": 0,
        }
    )
    host_blocked = host.get("state") == "blocked"
    ready = runner_ready and mcp_ready and not host_blocked
    live = bool(runner_pids or mcp_pids)
    receipt_state = str(assessment.get("state") or "unknown")
    if len(runner_pids) == 1 and receipt_state in {"starting", "stopping"}:
        state = receipt_state
        code = str(assessment.get("code") or "room_runner_state_not_ready")
    elif ready:
        state = "ready"
        code = "ready"
    elif live:
        state = "degraded"
        if len(runner_pids) > 1:
            code = "duplicate_room_runner"
        elif len(mcp_pids) > 1:
            code = "duplicate_room_mcp"
        elif host_blocked and runner_ready and mcp_ready:
            code = str(host.get("code") or "room_host_blocked")
        elif runner_pids and not runner_ready:
            code = str(assessment.get("code") or "room_runner_not_ready")
        else:
            code = "room_mcp_not_ready"
    else:
        state = "stopped"
        code = "room_runtime_stopped"
    status_payload = assessment.get("status")
    boot_id = status_payload.get("boot_id") if isinstance(status_payload, Mapping) else None
    return {
        "schema_version": ROOM_RUNTIME_SCHEMA,
        "state": state,
        "code": code,
        "ready": ready,
        "generation": config.generation,
        "boot_id": boot_id,
        "host": host,
        "services": {
            "room_runner": {
                "live": bool(runner_pids),
                "ready": runner_ready,
                "pids": runner_pids,
                "assessment_code": assessment.get("code"),
            },
            "room_mcp": {
                "live": bool(mcp_pids),
                "ready": mcp_ready,
                "pids": mcp_pids,
                "surface": mcp_health.get("surface") if isinstance(mcp_health, Mapping) else None,
            },
        },
        "authority": "backend_supervised_process",
    }


def ensure_room_runtime(
    config: RoomRuntimeSupervisorConfig,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    signal_process: Callable[[int, int], None] = os.kill,
    signal_group: Callable[[int, int], None] = os.killpg,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    http_health: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Ensure one Room MCP/runner generation, never replacing a live stale runner."""

    initial = inspect_room_runtime(config, http_health=http_health)
    if initial["ready"]:
        return {**initial, "source": "existing_process"}

    runner = initial["services"]["room_runner"]
    mcp = initial["services"]["room_mcp"]
    if runner["live"]:
        # A live runner with a stale or otherwise invalid receipt is diagnostic
        # evidence, not permission to kill it.  This prevents a slow host loop
        # from being mistaken for a dead process and duplicated.
        return {**initial, "source": "live_process_degraded"}
    if len(mcp["pids"]) > 1 or (mcp["live"] and not mcp["ready"]):
        return {**initial, "source": "live_process_degraded"}

    orphan_transports = _room_transport_pids(config)
    remaining_orphans = _stop_pids(
        orphan_transports,
        signal_process=signal_process,
        signal_group=signal_group,
        sleep=sleep,
        monotonic=monotonic,
        terminate_timeout_s=2.0,
        kill_timeout_s=2.0,
    )
    if remaining_orphans:
        raise RoomRuntimeStartError(
            "room_transport_cleanup_failed",
            "orphaned Room transport processes could not be fenced before restart",
        )

    started: list[tuple[Any, Path]] = []
    health_reader = http_health or _read_http_json
    startup_deadline = monotonic() + config.startup_wait_s
    try:
        if not mcp["live"]:
            mcp_process = _spawn_service(
                config,
                service="room_mcp",
                command=room_mcp_command(config),
                log_path=_mcp_log_path(config),
                popen=popen,
            )
            started.append((mcp_process, _mcp_pid_file(config)))
            mcp_start_identity = _wait_for_process_identity(
                int(mcp_process.pid),
                process=mcp_process,
                deadline=startup_deadline,
                sleep=sleep,
                monotonic=monotonic,
            )
            _write_pid_receipt(
                _mcp_pid_file(config),
                pid=int(mcp_process.pid),
                generation=config.generation,
                start_identity=mcp_start_identity,
                command=room_mcp_command(config),
                log_path=_mcp_log_path(config),
            )
            _wait_for_mcp_ready(
                config,
                process=mcp_process,
                health_reader=health_reader,
                deadline=startup_deadline,
                sleep=sleep,
                monotonic=monotonic,
            )

        runner_process = _spawn_service(
            config,
            service="room_runner",
            command=room_runner_command(config),
            log_path=_runner_log_path(config),
            popen=popen,
        )
        started.append((runner_process, _runner_pid_file(config)))
        start_identity = _wait_for_process_identity(
            int(runner_process.pid),
            process=runner_process,
            deadline=startup_deadline,
            sleep=sleep,
            monotonic=monotonic,
        )
        _write_pid_receipt(
            _runner_pid_file(config),
            pid=int(runner_process.pid),
            generation=config.generation,
            start_identity=start_identity,
            command=room_runner_command(config),
            log_path=_runner_log_path(config),
        )
        result = _wait_for_room_runner_ready(
            config,
            process=runner_process,
            expected_start_identity=start_identity,
            deadline=startup_deadline,
            sleep=sleep,
            monotonic=monotonic,
            http_health=health_reader,
        )
        return {**result, "source": "started_process"}
    except BaseException:
        for process, pid_file in reversed(started):
            _terminate_process(
                process,
                signal_process=signal_process,
                signal_group=signal_group,
                sleep=sleep,
                monotonic=monotonic,
            )
            if not _process_running(process):
                pid_file.unlink(missing_ok=True)
        raise


def stop_room_runtime(
    config: RoomRuntimeSupervisorConfig,
    *,
    signal_process: Callable[[int, int], None] = os.kill,
    signal_group: Callable[[int, int], None] = os.killpg,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    inventory = discover_xmuse_runtime_processes(
        xmuse_root=config.xmuse_root,
        workroom_generation=config.generation,
    )
    ordered = [
        *_service_pids(inventory, "room_runner"),
        *_room_transport_pids(config),
        *_service_pids(inventory, "room_mcp"),
    ]
    remaining = _stop_pids(
        ordered,
        signal_process=signal_process,
        signal_group=signal_group,
        sleep=sleep,
        monotonic=monotonic,
    )
    if not remaining:
        _runner_pid_file(config).unlink(missing_ok=True)
        _mcp_pid_file(config).unlink(missing_ok=True)
    return {
        "schema_version": ROOM_RUNTIME_STOP_SCHEMA,
        "state": "stopped" if not remaining else "error",
        "generation": config.generation,
        "term_pids": ordered,
        "remaining_pids": remaining,
        "authority": "backend_supervised_process",
    }


def stop_runtime_pids(
    pids: Sequence[int],
    *,
    signal_process: Callable[[int, int], None] = os.kill,
    signal_group: Callable[[int, int], None] = os.killpg,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[int]:
    """Identity-fenced, process-group-aware stop for scoped supervisor cleanup."""

    return _stop_pids(
        pids,
        signal_process=signal_process,
        signal_group=signal_group,
        sleep=sleep,
        monotonic=monotonic,
    )


def _service_pids(inventory: Mapping[str, Any], service_name: str) -> list[int]:
    for item in inventory.get("services", []):
        if isinstance(item, Mapping) and item.get("service") == service_name:
            return [pid for pid in item.get("pids", []) if isinstance(pid, int)]
    return []


def _room_transport_pids(config: RoomRuntimeSupervisorConfig) -> list[int]:
    inventory = discover_xmuse_runtime_processes(
        xmuse_root=config.xmuse_root,
        workroom_generation=config.generation,
    )
    candidates = [
        *_service_pids(inventory, "codex_app_server"),
        *_service_pids(inventory, "codex_worker"),
    ]
    return [
        pid
        for pid in candidates
        if _read_process_environment(pid).get("XMUSE_WORKROOM_SERVICE") == "room_runner"
    ]


def _read_process_environment(pid: int) -> dict[str, str]:
    try:
        content = (Path("/proc") / str(pid) / "environ").read_bytes()
    except OSError:
        return {}
    environment: dict[str, str] = {}
    for item in content.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment[key.decode(errors="replace")] = value.decode(errors="replace")
    return environment


def _spawn_service(
    config: RoomRuntimeSupervisorConfig,
    *,
    service: str,
    command: Sequence[str],
    log_path: Path,
    popen: Callable[..., Any],
) -> Any:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = normalize_child_temp_env(os.environ)
    environment.pop("XMUSE_OPERATOR_TOKEN", None)
    if service != "room_runner":
        environment.pop("XMUSE_MEMORYOS_URL", None)
        environment.pop("XMUSE_MEMORYOS_API_KEY", None)
    for key in tuple(environment):
        if key.startswith("NEXT_PUBLIC_") and "TOKEN" in key.upper():
            environment.pop(key, None)
    environment.update(
        {
            "XMUSE_ROOT": str(config.xmuse_root),
            "XMUSE_WORKROOM_GENERATION": config.generation,
            "XMUSE_WORKROOM_SERVICE": service,
            "PYTHONUNBUFFERED": "1",
        }
    )
    log_handle = log_path.open("ab")
    try:
        return popen(
            list(command),
            cwd=config.repo_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()


def _wait_for_mcp_ready(
    config: RoomRuntimeSupervisorConfig,
    *,
    process: Any,
    health_reader: Callable[[str], Mapping[str, Any] | None],
    deadline: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    url = f"http://{config.mcp_host}:{config.mcp_port}/health"
    while True:
        if not _process_running(process):
            raise RoomRuntimeStartError("room_mcp_exited", "Room MCP exited before readiness")
        payload = health_reader(url)
        if room_mcp_health_ready(payload):
            return
        if monotonic() >= deadline:
            raise RoomRuntimeStartError(
                "room_mcp_readiness_timeout",
                f"Room MCP did not become ready within {config.startup_wait_s:g} seconds",
            )
        sleep(0.1)


def _wait_for_room_runner_ready(
    config: RoomRuntimeSupervisorConfig,
    *,
    process: Any,
    expected_start_identity: str,
    deadline: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    http_health: Callable[[str], Mapping[str, Any] | None],
) -> dict[str, Any]:
    last_code = "room_runner_status_missing"
    while True:
        if not _process_running(process):
            raise RoomRuntimeStartError("room_runner_exited", "Room runner exited before readiness")
        assessment = assess_room_runner_status(
            config.xmuse_root,
            expected_generation=config.generation,
            expected_pid=int(process.pid),
            expected_start_identity=expected_start_identity,
            heartbeat_ttl_s=config.heartbeat_ttl_s,
        )
        last_code = str(assessment.get("code") or last_code)
        if assessment.get("ready"):
            result = inspect_room_runtime(config, http_health=http_health)
            if result["ready"]:
                return result
        if monotonic() >= deadline:
            raise RoomRuntimeStartError(
                "room_runner_readiness_timeout",
                "Room runner did not produce a valid ready receipt "
                f"within {config.startup_wait_s:g} seconds ({last_code})",
            )
        sleep(0.1)


def _wait_for_process_identity(
    pid: int,
    *,
    process: Any,
    deadline: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> str:
    while True:
        identity = read_process_start_identity(pid)
        if identity:
            return identity
        if not _process_running(process):
            raise RoomRuntimeStartError(
                "room_runner_exited", "Room runner exited before identity was established"
            )
        if monotonic() >= deadline:
            raise RoomRuntimeStartError(
                "room_runner_identity_timeout",
                "Room runner process identity could not be established",
            )
        sleep(0.05)


def _stop_pids(
    pids: Sequence[int],
    *,
    signal_process: Callable[[int, int], None],
    signal_group: Callable[[int, int], None],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    terminate_timeout_s: float = 5.0,
    kill_timeout_s: float = 2.0,
) -> list[int]:
    identities = {
        pid: identity for pid in pids if (identity := read_process_start_identity(pid)) is not None
    }
    for pid in pids:
        _signal_fenced_process(
            pid,
            identities.get(pid),
            signal.SIGTERM,
            signal_process=signal_process,
            signal_group=signal_group,
        )
    remaining = _wait_live_pids(
        identities,
        sleep=sleep,
        monotonic=monotonic,
        timeout_s=terminate_timeout_s,
    )
    if remaining:
        for pid in remaining:
            _signal_fenced_process(
                pid,
                identities.get(pid),
                getattr(signal, "SIGKILL", signal.SIGTERM),
                signal_process=signal_process,
                signal_group=signal_group,
            )
        remaining = _wait_live_pids(
            {pid: identities[pid] for pid in remaining},
            sleep=sleep,
            monotonic=monotonic,
            timeout_s=kill_timeout_s,
        )
    return remaining


def _wait_live_pids(
    identities: Mapping[int, str],
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    timeout_s: float,
) -> list[int]:
    deadline = monotonic() + timeout_s
    while True:
        remaining = [
            pid
            for pid, identity in identities.items()
            if read_process_start_identity(pid) == identity
        ]
        if not remaining or monotonic() >= deadline:
            return remaining
        sleep(0.1)


def _terminate_process(
    process: Any,
    *,
    signal_process: Callable[[int, int], None],
    signal_group: Callable[[int, int], None],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    if not _process_running(process):
        return
    _stop_pids(
        [int(process.pid)],
        signal_process=signal_process,
        signal_group=signal_group,
        sleep=sleep,
        monotonic=monotonic,
        terminate_timeout_s=2.0,
        kill_timeout_s=2.0,
    )


def _signal_fenced_process(
    pid: int,
    expected_start_identity: str | None,
    signum: int,
    *,
    signal_process: Callable[[int, int], None],
    signal_group: Callable[[int, int], None],
) -> None:
    if expected_start_identity is None:
        return
    if read_process_start_identity(pid) != expected_start_identity:
        return
    try:
        pgid = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        return
    try:
        if pgid == pid:
            signal_group(pgid, signum)
        else:
            signal_process(pid, signum)
    except ProcessLookupError:
        pass


def _process_running(process: Any) -> bool:
    poll = getattr(process, "poll", None)
    return not callable(poll) or poll() is None


def _read_http_json(url: str) -> Mapping[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:  # noqa: S310
            if int(response.status) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _write_pid_receipt(
    path: Path,
    *,
    pid: int,
    generation: str,
    command: Sequence[str],
    log_path: Path,
    start_identity: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "pid": pid,
        "generation": generation,
        "command": list(command),
        "log_path": str(log_path),
    }
    if start_identity is not None:
        payload["start_identity"] = start_identity
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _runner_pid_file(config: RoomRuntimeSupervisorConfig) -> Path:
    return config.runner_pid_file or config.xmuse_root / "workroom_room_runner.pid.json"


def _mcp_pid_file(config: RoomRuntimeSupervisorConfig) -> Path:
    return config.mcp_pid_file or config.xmuse_root / "workroom_room_mcp.pid.json"


def _runner_log_path(config: RoomRuntimeSupervisorConfig) -> Path:
    return config.runner_log_path or config.xmuse_root / "logs" / "workroom-room-runner.log"


def _mcp_log_path(config: RoomRuntimeSupervisorConfig) -> Path:
    return config.mcp_log_path or config.xmuse_root / "logs" / "workroom-room-mcp.log"
