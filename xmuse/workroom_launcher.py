"""Detached launcher for the existing foreground Workroom manager."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from xmuse.workroom import COMMAND_SCHEMA_VERSION, workroom_status
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths

FRONTEND_URL = "http://127.0.0.1:3000"
MAX_MANAGED_CACHE_FILES = 1_024
MAX_MANAGED_CACHE_BYTES = 256 * 1024 * 1024


class ManagedMemoryOSError(RuntimeError):
    """Stable managed companion preparation failure."""


class ManagerProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def _spawn_manager(argv: Sequence[str]) -> ManagerProcess:
    return subprocess.Popen(  # noqa: S603 - argv is entirely server-owned
        tuple(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _managed_memoryos_executable() -> Path | None:
    candidate = Path(sys.prefix).parent / "memoryos" / ".venv" / "bin" / "memoryos"
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _prepare_managed_memoryos_cache(executable: Path, runtime_root: Path) -> None:
    try:
        companion = executable.resolve(strict=True).parents[2]
        source = (companion / "payload" / "memoryos" / "model-cache").resolve(strict=True)
        source.relative_to(companion)
    except (OSError, IndexError, ValueError) as exc:
        raise ManagedMemoryOSError("managed_memoryos_cache_missing") from exc
    if not source.is_dir() or source.is_symlink():
        raise ManagedMemoryOSError("managed_memoryos_cache_invalid")
    files = 0
    total_bytes = 0
    for candidate in source.rglob("*"):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ManagedMemoryOSError("managed_memoryos_cache_invalid")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or candidate.name.endswith(".incomplete"):
            raise ManagedMemoryOSError("managed_memoryos_cache_invalid")
        files += 1
        total_bytes += metadata.st_size
        if files > MAX_MANAGED_CACHE_FILES or total_bytes > MAX_MANAGED_CACHE_BYTES:
            raise ManagedMemoryOSError("managed_memoryos_cache_unbounded")
    runtime = runtime_root.expanduser().resolve() / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = runtime / "fastembed-cache"
    if destination.is_symlink():
        raise ManagedMemoryOSError("managed_memoryos_cache_invalid")
    staging = runtime / f".fastembed-cache-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
    except OSError as exc:
        raise ManagedMemoryOSError("managed_memoryos_cache_unavailable") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@dataclass(frozen=True)
class WorkroomLaunchDependencies:
    spawn_manager: Callable[[Sequence[str]], ManagerProcess] = _spawn_manager
    status: Callable[[WorkroomPaths, WorkroomDependencies], tuple[int, Mapping[str, object]]] = (
        lambda paths, dependencies: workroom_status(paths, dependencies, emit=False)
    )
    open_browser: Callable[[str], bool] = webbrowser.open
    resolve_managed_memoryos: Callable[[], Path | None] = _managed_memoryos_executable
    prepare_managed_memoryos_cache: Callable[[Path, Path], None] = _prepare_managed_memoryos_cache
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    python_executable: str = field(default_factory=lambda: sys.executable)


@dataclass(frozen=True)
class WorkroomLaunchRequest:
    root: Path
    readiness_timeout_s: float
    stop_timeout_s: float
    workspace: Path | None = None
    execution_profile: str | None = None
    memory: bool = False
    memoryos_executable: Path | None = None
    memory_profile: str | None = None
    open_browser: bool = True


def _payload(*, state: str, **values: object) -> dict[str, object]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "command": "launch",
        "state": state,
        **values,
    }


def _error(code: str, message: str) -> tuple[int, dict[str, object]]:
    return 1, _payload(state="error", error={"code": code, "message": message})


def _start_argv(
    request: WorkroomLaunchRequest,
    dependencies: WorkroomLaunchDependencies,
) -> tuple[tuple[str, ...] | None, tuple[int, dict[str, object]] | None]:
    memoryos = request.memoryos_executable
    if request.memory:
        memoryos = memoryos or dependencies.resolve_managed_memoryos()
        if memoryos is None:
            return None, _error(
                "memoryos_executable_required",
                "--memory requires an explicit or managed MemoryOS executable",
            )
        if not memoryos.is_file() or not os.access(memoryos, os.X_OK):
            return None, _error(
                "memoryos_executable_invalid",
                "the selected MemoryOS executable does not exist",
            )

    argv = [
        dependencies.python_executable,
        "-m",
        "xmuse.workroom_cli",
        "start",
        "--root",
        str(request.root),
        "--readiness-timeout-s",
        str(request.readiness_timeout_s),
        "--stop-timeout-s",
        str(request.stop_timeout_s),
    ]
    if request.workspace is not None:
        argv.extend(("--workspace", str(request.workspace)))
    if request.execution_profile is not None:
        argv.extend(("--execution-profile", request.execution_profile))
    if request.memory:
        assert memoryos is not None
        argv.extend(("--memory", "--memoryos-executable", str(memoryos)))
    if request.memory_profile is not None:
        argv.extend(("--memory-profile", request.memory_profile))
    return tuple(argv), None


def _open_if_requested(
    request: WorkroomLaunchRequest,
    dependencies: WorkroomLaunchDependencies,
) -> bool | None:
    if not request.open_browser:
        return None
    return dependencies.open_browser(FRONTEND_URL)


def _stop_created_manager(process: ManagerProcess, *, timeout_s: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_s)


def launch_workroom(
    paths: WorkroomPaths,
    workroom_dependencies: WorkroomDependencies,
    request: WorkroomLaunchRequest,
    *,
    dependencies: WorkroomLaunchDependencies | None = None,
) -> tuple[int, dict[str, object]]:
    """Start the foreground manager in a detached child and wait for its existing receipt."""

    deps = dependencies or WorkroomLaunchDependencies()
    _status_code, initial = deps.status(paths, workroom_dependencies)
    initial_state = initial.get("state")
    if initial_state == "ready":
        browser_opened = _open_if_requested(request, deps)
        return 0, _payload(
            state="ready",
            already_running=True,
            frontend_url=FRONTEND_URL,
            browser_opened=browser_opened,
        )
    if initial_state not in {"stopped", "stale"}:
        return _error(
            "workroom_not_launchable",
            f"the existing Workroom is {initial_state or 'unknown'}; inspect status before launch",
        )

    argv, argument_error = _start_argv(request, deps)
    if argument_error is not None:
        return argument_error
    assert argv is not None
    if (
        request.memory
        and request.memoryos_executable is None
        and request.memory_profile != "archive-only"
    ):
        managed_memoryos = deps.resolve_managed_memoryos()
        assert managed_memoryos is not None
        try:
            deps.prepare_managed_memoryos_cache(managed_memoryos, request.root)
        except ManagedMemoryOSError as exc:
            return _error(exc.args[0], "the managed MemoryOS model cache is unavailable")
    try:
        process = deps.spawn_manager(argv)
    except OSError:
        return _error("manager_spawn_failed", "could not start the Workroom manager")

    deadline = deps.monotonic() + request.readiness_timeout_s
    while deps.monotonic() < deadline:
        _status_code, current = deps.status(paths, workroom_dependencies)
        if current.get("state") == "ready":
            browser_opened = _open_if_requested(request, deps)
            return 0, _payload(
                state="ready",
                already_running=False,
                frontend_url=FRONTEND_URL,
                browser_opened=browser_opened,
            )
        return_code = process.poll()
        if return_code is not None:
            _status_code, final = deps.status(paths, workroom_dependencies)
            if final.get("state") == "ready":
                browser_opened = _open_if_requested(request, deps)
                return 0, _payload(
                    state="ready",
                    already_running=False,
                    frontend_url=FRONTEND_URL,
                    browser_opened=browser_opened,
                )
            return _error(
                "manager_exited_before_ready",
                f"the Workroom manager exited before readiness (code {return_code})",
            )
        deps.sleep(0.1)

    _status_code, final = deps.status(paths, workroom_dependencies)
    if final.get("state") == "ready":
        browser_opened = _open_if_requested(request, deps)
        return 0, _payload(
            state="ready",
            already_running=False,
            frontend_url=FRONTEND_URL,
            browser_opened=browser_opened,
        )
    try:
        _stop_created_manager(process, timeout_s=request.stop_timeout_s)
    except (OSError, subprocess.TimeoutExpired):
        return _error(
            "launch_cleanup_failed",
            "readiness timed out and the created manager could not be stopped safely",
        )
    return _error("launch_readiness_timeout", "the Workroom did not become ready in time")
