"""Narrow supervisor for one-shot Room execution controllers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.chat.room_runtime import read_process_start_identity


class RoomExecutionSupervisorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RecoveryStore(Protocol):
    def list_controller_recovery(self, *, limit: int = 100) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class ExecutionControllerSupervisorConfig:
    repo_root: Path
    xmuse_root: Path
    execution_worktree: Path
    generation: str

    def __post_init__(self) -> None:
        if not self.generation.strip():
            raise ValueError("execution controller generation must not be empty")


@dataclass(frozen=True)
class StartedExecutionController:
    run_id: str
    controller_id: str
    pid: int
    start_identity: str
    process: Any


def execution_controller_command(
    config: ExecutionControllerSupervisorConfig, *, run_id: str
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "xmuse.room_execution_controller",
        "--xmuse-root",
        str(config.xmuse_root),
        "--worktree",
        str(config.execution_worktree),
        "--run-id",
        run_id,
    ]


def inspect_run_controller(store: RecoveryStore, run_id: str) -> dict[str, Any]:
    """Return safe liveness evidence; never infer identity from a PID alone."""

    matches = [item for item in store.list_controller_recovery() if item.get("run_id") == run_id]
    if len(matches) != 1:
        return {"state": "unknown", "code": "execution_controller_binding_unknown"}
    binding = matches[0]
    raw_pid = binding.get("controller_pid")
    expected = binding.get("controller_start_identity")
    if raw_pid is None and expected is None:
        return {"state": "unbound", "code": "execution_controller_unbound"}
    if isinstance(raw_pid, bool) or not isinstance(raw_pid, int) or not isinstance(expected, str):
        return {"state": "unknown", "code": "execution_controller_binding_invalid"}
    observed = read_process_start_identity(raw_pid)
    if observed == expected:
        return {"state": "live", "code": "execution_controller_live"}
    return {"state": "dead", "code": "execution_controller_dead"}


def ensure_execution_controller(
    store: RecoveryStore,
    config: ExecutionControllerSupervisorConfig,
    *,
    run_id: str,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> StartedExecutionController | None:
    """Spawn only when the durable binding is unbound or confirmed dead."""

    assessment = inspect_run_controller(store, run_id)
    if assessment["state"] == "live":
        return None
    if assessment["state"] not in {"unbound", "dead"}:
        raise RoomExecutionSupervisorError(str(assessment["code"]))
    controller_id = f"execution_controller_{uuid.uuid4().hex}"
    environment = _controller_environment(config, controller_id=controller_id)
    try:
        process = popen(
            execution_controller_command(config, run_id=run_id),
            cwd=config.repo_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=False,
        )
    except OSError as exc:
        raise RoomExecutionSupervisorError("execution_controller_start_failed") from exc
    identity = _wait_for_identity(process, sleep=sleep, monotonic=monotonic, timeout_s=2.0)
    return StartedExecutionController(
        run_id=run_id,
        controller_id=controller_id,
        pid=int(process.pid),
        start_identity=identity,
        process=process,
    )


def stop_execution_controller(
    *,
    pid: int,
    start_identity: str,
    signal_process: Callable[[int, int], None] = os.kill,
    signal_group: Callable[[int, int], None] = os.killpg,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    terminate_timeout_s: float = 5.0,
) -> bool:
    """Identity-fenced stop; return False when cleanup remains live."""

    if read_process_start_identity(pid) != start_identity:
        return True
    try:
        pgid = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        return True
    try:
        if pgid == pid:
            signal_group(pgid, signal.SIGTERM)
        else:
            signal_process(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = monotonic() + terminate_timeout_s
    while read_process_start_identity(pid) == start_identity and monotonic() < deadline:
        sleep(0.1)
    if read_process_start_identity(pid) != start_identity:
        return True
    try:
        if pgid == pid:
            signal_group(pgid, signal.SIGKILL)
        else:
            signal_process(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    deadline = monotonic() + 2.0
    while read_process_start_identity(pid) == start_identity and monotonic() < deadline:
        sleep(0.1)
    return read_process_start_identity(pid) != start_identity


def _controller_environment(
    config: ExecutionControllerSupervisorConfig, *, controller_id: str
) -> dict[str, str]:
    environment = {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": "/tmp",
        "XMUSE_EXECUTION_CONTROLLER_ID": controller_id,
        "XMUSE_ROOT": str(config.xmuse_root),
        "XMUSE_WORKROOM_GENERATION": config.generation,
        "XMUSE_WORKROOM_SERVICE": "execution_controller",
    }
    return environment


def _wait_for_identity(
    process: Any,
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    timeout_s: float,
) -> str:
    deadline = monotonic() + timeout_s
    while True:
        identity = read_process_start_identity(int(process.pid))
        if identity:
            return identity
        poll = getattr(process, "poll", None)
        if callable(poll) and poll() is not None:
            raise RoomExecutionSupervisorError("execution_controller_exited")
        if monotonic() >= deadline:
            raise RoomExecutionSupervisorError("execution_controller_identity_timeout")
        sleep(0.05)
