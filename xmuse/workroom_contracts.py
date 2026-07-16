"""Dependency and path contracts for the local Workroom coordinator."""

from __future__ import annotations

import fcntl
import os
import secrets
import shutil
import signal
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse.workroom_processes import (
    ManagedProcess,
    ProcessIdentity,
    ProcessSpec,
    http_json,
    http_ready,
    inspect_process,
    port_available,
    spawn_process,
)
from xmuse_core.runtime.root_contract import RuntimeRootPaths

WORKROOM_REPO_ROOT = Path(__file__).resolve().parents[1]


class WorkroomError(RuntimeError):
    """A stable, user-facing Workroom lifecycle error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ShutdownController(Protocol):
    def install(self) -> None: ...

    def requested(self) -> bool: ...

    def restore(self) -> None: ...


class SignalShutdownController:
    def __init__(self) -> None:
        self._requested = False
        self._previous: dict[int, Any] = {}

    def install(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)

    def _handle(self, _signum: int, _frame: Any) -> None:
        self._requested = True

    def requested(self) -> bool:
        return self._requested

    def restore(self) -> None:
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)
        self._previous.clear()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stop_runtime_generation(root: Path, generation: str) -> Mapping[str, Any]:
    from xmuse.chat_api_runtime import stop_workroom_room_runtime

    return stop_workroom_room_runtime(root, generation=generation)


@dataclass
class WorkroomDependencies:
    repo_root: Path = WORKROOM_REPO_ROOT
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    spawn: Callable[[ProcessSpec], ManagedProcess] = spawn_process
    inspect_process: Callable[[int], ProcessIdentity | None] = inspect_process
    port_available: Callable[[str, int], bool] = port_available
    http_ready: Callable[[str], bool] = http_ready
    http_json: Callable[[str], Mapping[str, Any] | None] = http_json
    which: Callable[[str], str | None] = shutil.which
    signal_pid: Callable[[int, int], None] = os.kill
    signal_group: Callable[[int, int], None] = os.killpg
    stop_runtime: Callable[[Path, str], Mapping[str, Any]] = _stop_runtime_generation
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], str] = _utc_now
    generation_factory: Callable[[], str] = lambda: uuid.uuid4().hex
    token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32)
    memory_key_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32)
    current_pid: Callable[[], int] = os.getpid
    shutdown_controller_factory: Callable[[], ShutdownController] = SignalShutdownController


@dataclass(frozen=True)
class WorkroomPaths:
    xmuse_root: Path
    repo_root: Path
    frontend_dir: Path
    standalone_dir: Path
    standalone_server: Path
    static_source: Path
    static_destination: Path
    public_source: Path
    public_destination: Path
    runner_pid_file: Path
    mcp_pid_file: Path
    manifest: Path
    lock: Path
    data_operation_journal: Path
    room_runner_status_file: Path
    legacy_runner_pid_file: Path
    legacy_mcp_pid_file: Path
    memoryos_status_file: Path
    memoryos_derived_dir: Path

    @classmethod
    def resolve(cls, xmuse_root: Path, repo_root: Path) -> WorkroomPaths:
        root = xmuse_root.expanduser().resolve()
        authority = RuntimeRootPaths.resolve(root, fallback=root)
        repository = repo_root.expanduser().resolve()
        frontend = repository / "frontend"
        standalone = frontend / ".next" / "standalone"
        return cls(
            xmuse_root=root,
            repo_root=repository,
            frontend_dir=frontend,
            standalone_dir=standalone,
            standalone_server=standalone / "server.js",
            static_source=frontend / ".next" / "static",
            static_destination=standalone / ".next" / "static",
            public_source=frontend / "public",
            public_destination=standalone / "public",
            runner_pid_file=authority.room_runner_pid,
            mcp_pid_file=authority.room_mcp_pid,
            manifest=authority.manifest,
            lock=authority.lifecycle_lock,
            data_operation_journal=authority.data_operation_journal,
            room_runner_status_file=authority.room_runner_status,
            legacy_runner_pid_file=root / "workroom_peer_runtime.pid.json",
            legacy_mcp_pid_file=root / "workroom_mcp_server.pid.json",
            memoryos_status_file=authority.memoryos_status,
            memoryos_derived_dir=authority.memoryos_derived,
        )


@contextmanager
def workroom_lifecycle_lock(paths: WorkroomPaths) -> Iterator[None]:
    """Serialize one root's lifecycle mutations without owning their state machine."""

    paths.xmuse_root.mkdir(parents=True, exist_ok=True)
    with paths.lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
