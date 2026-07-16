#!/usr/bin/env python3
"""Run the isolated, Room-only xmuse participant runtime."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import math
import os
import re
import shutil
import signal
import stat
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse.room_runner_composition import (
    RoomRuntimeComposition,
    compose_room_runtime,
)
from xmuse.room_runner_memory import (
    compose_room_runner_memory,
    run_room_memory_pump,
)
from xmuse_core.agents.codex_app_server_transport import CODEX_ROOM_READ_ONLY_SANDBOX
from xmuse_core.agents.room_codex_launcher import build_room_launchers
from xmuse_core.chat.room_codex_native_runtime import (
    run_room_codex_native_loop,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_review_store import RoomExecutionReviewStore
from xmuse_core.chat.room_runtime import (
    ROOM_MCP_PATH,
    ROOM_MCP_SURFACE,
    ROOM_RUNNER_HEARTBEAT_INTERVAL_S,
    ROOM_RUNNER_READINESS_KEYS,
    RoomRunnerStatusError,
    read_process_start_identity,
    room_runner_lock_path,
    run_room_participant_host_loop,
    write_room_runner_status,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.runtime.data_guard import assert_data_operation_complete
from xmuse_core.runtime.paths import default_xmuse_root, resolve_xmuse_root
from xmuse_core.skills.catalog import SkillCatalog

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XMUSE_ROOT = default_xmuse_root(REPO_ROOT / "xmuse")
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8100
DEFAULT_MAX_CONCURRENT_ROOMS = 4
DEFAULT_DELIVERY_TIMEOUT_S = 180.0
DEFAULT_CLEANUP_GRACE_S = 8.0
MCP_STARTUP_PROBE_TIMEOUT_S = 10.0
MCP_REQUEST_TIMEOUT_S = 1.0
ROOM_OUTCOME_TOOL = "chat_room_submit_outcome"
ROOM_CODEX_HOME_RELATIVE = Path("runtime") / "room-codex-home"
CODEX_AUTH_FILE_NAME = "auth.json"
_SAFE_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

logger = logging.getLogger(__name__)


class RoomRunnerError(RuntimeError):
    """Stable Room Runner process failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@contextmanager
def _room_runner_lock(xmuse_root: Path, *, generation: str) -> Iterator[None]:
    xmuse_root.mkdir(parents=True, exist_ok=True)
    path = room_runner_lock_path(xmuse_root)
    if path.is_symlink():
        raise RoomRunnerError("room_runner_lock_symlink_rejected")
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RoomRunnerError("room_runner_already_running") from exc
        try:
            handle.seek(0)
            handle.truncate()
            json.dump(
                {"generation": generation, "pid": os.getpid()},
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def run_room_runner(
    *,
    xmuse_root: Path,
    generation: str,
    mcp_port: int = DEFAULT_MCP_PORT,
    max_concurrent_rooms: int = DEFAULT_MAX_CONCURRENT_ROOMS,
    delivery_timeout_s: float = DEFAULT_DELIVERY_TIMEOUT_S,
    cleanup_grace_s: float = DEFAULT_CLEANUP_GRACE_S,
    worktree: Path | None = None,
    shutdown: asyncio.Event | None = None,
    mcp_probe: Callable[[str, int], tuple[bool, bool]] | None = None,
    executable_resolver: Callable[[str], str | None] | None = None,
) -> None:
    """Compose and run only the participant-owned Room delivery path."""

    root = xmuse_root.expanduser().resolve()
    assert_data_operation_complete(root)
    _validate_run_configuration(
        generation=generation,
        mcp_port=mcp_port,
        max_concurrent_rooms=max_concurrent_rooms,
        delivery_timeout_s=delivery_timeout_s,
        cleanup_grace_s=cleanup_grace_s,
    )
    resolved_worktree = _resolve_worktree(worktree)
    stop = shutdown or asyncio.Event()
    process_identity = read_process_start_identity(os.getpid())
    if process_identity is None:
        raise RoomRunnerError("room_runner_process_identity_unavailable")
    boot_id = uuid.uuid4().hex
    started_at = _utc_now()
    readiness = {name: False for name in ROOM_RUNNER_READINESS_KEYS}
    status_started = False
    composition: RoomRuntimeComposition | None = None
    host_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    memory_task: asyncio.Task[None] | None = None
    native_task: asyncio.Task[None] | None = None
    host_started = asyncio.Event()
    native_started = asyncio.Event()
    receipt_state: dict[str, Any] = {
        "state": "starting",
        "error_code": None,
    }
    host_not_started = {
        "state": "blocked",
        "code": "room_runner_host_not_started",
        "active_delivery_count": 0,
        "retained_cleanup_count": 0,
    }

    with _room_runner_lock(root, generation=generation):
        try:
            _write_status(
                root,
                generation=generation,
                process_identity=process_identity,
                boot_id=boot_id,
                state="starting",
                started_at=started_at,
                mcp_port=mcp_port,
                readiness=readiness,
                host=host_not_started,
            )
            status_started = True

            try:
                RoomDatabase(root / "chat.db").initialize()
                controls = RoomObservationControlStore(root / "chat.db")
                skill_decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
                execution_store = RoomExecutionReviewStore(root / "chat.db")
            except Exception as exc:
                raise RoomRunnerError("room_runner_chat_db_unavailable") from exc
            readiness["chat_db"] = True

            memory_runtime, memory_enabled = compose_room_runner_memory(
                root / "chat.db",
                worker_id=f"room-memory-{boot_id}",
            )

            try:
                skill_catalog = SkillCatalog.load_bundled()
                if not skill_catalog.descriptors:
                    raise RuntimeError("empty catalog")
            except Exception as exc:
                raise RoomRunnerError("room_runner_skill_catalog_unavailable") from exc
            readiness["skill_catalog"] = True

            try:
                mcp_health, mcp_tools = await _wait_for_room_mcp(
                    DEFAULT_MCP_HOST,
                    mcp_port,
                    probe=mcp_probe or _probe_room_mcp_once,
                )
            except Exception as exc:
                raise RoomRunnerError("room_runner_mcp_unavailable") from exc
            readiness["mcp_health"] = mcp_health
            readiness["mcp_tools"] = mcp_tools
            if not mcp_health:
                raise RoomRunnerError("room_runner_mcp_health_invalid")
            if not mcp_tools:
                raise RoomRunnerError("room_runner_mcp_tools_invalid")

            try:
                room_codex_home = _prepare_room_codex_home(root)
                launchers = build_room_launchers(
                    mcp_port=mcp_port,
                    codex_home=room_codex_home,
                )
            except RoomRunnerError:
                raise
            except Exception as exc:
                raise RoomRunnerError("room_runner_launcher_unavailable") from exc
            if not _has_room_persistent_session_launcher(launchers):
                raise RoomRunnerError("room_runner_persistent_launcher_required")
            if (executable_resolver or shutil.which)("codex") is None:
                raise RoomRunnerError("room_runner_codex_executable_unavailable")
            readiness["persistent_launcher"] = True

            try:
                composition = compose_room_runtime(
                    root=root,
                    worktree=resolved_worktree,
                    launchers=launchers,
                    controls=controls,
                    skill_decisions=skill_decisions,
                    skill_catalog=skill_catalog,
                    execution_store=execution_store,
                    memory_runtime=memory_runtime,
                    memory_enabled=memory_enabled,
                    max_concurrent_rooms=max_concurrent_rooms,
                    delivery_timeout_s=delivery_timeout_s,
                    cleanup_grace_s=cleanup_grace_s,
                    runner_generation=generation,
                    runner_boot_id=boot_id,
                )
            except Exception as exc:
                raise RoomRunnerError("room_runner_host_composition_failed") from exc
            with suppress(Exception):
                await composition.stream_projector.start()
            try:
                composition.host.fence_prior_runner_attempts()
            except Exception as exc:
                raise RoomRunnerError("room_runner_recovery_fence_failed") from exc

            _install_signal_handlers(stop)
            native_task = asyncio.create_task(
                run_room_codex_native_loop(
                    composition.native_runtime,
                    stop=stop,
                    started=native_started,
                ),
                name="xmuse-room-codex-native-bridge",
            )
            native_start_wait = asyncio.create_task(
                native_started.wait(), name="xmuse-room-codex-native-start"
            )
            try:
                await asyncio.wait(
                    {native_task, native_start_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not native_start_wait.done():
                    native_start_wait.cancel()
                await asyncio.gather(native_start_wait, return_exceptions=True)
            await asyncio.sleep(0)
            if native_task.done():
                try:
                    native_task.result()
                except Exception as exc:
                    raise RoomRunnerError("room_runner_native_bridge_failed") from exc
                raise RoomRunnerError("room_runner_native_bridge_stopped")
            host_task = asyncio.create_task(
                run_room_participant_host_loop(
                    composition.host,
                    stop=stop,
                    max_concurrent_rooms=max_concurrent_rooms,
                    started=host_started,
                ),
                name="xmuse-room-participant-host",
            )
            await host_started.wait()
            await asyncio.sleep(0)
            if host_task.done():
                try:
                    host_task.result()
                except Exception as exc:
                    raise RoomRunnerError("room_runner_host_loop_failed") from exc
                raise RoomRunnerError("room_runner_host_loop_stopped")
            readiness["host_loop"] = True
            if composition.memory_enabled:
                memory_task = asyncio.create_task(
                    run_room_memory_pump(
                        composition.memory_runtime,
                        report_attention=composition.host.set_memory_runtime_attention,
                        stop=stop,
                    ),
                    name="xmuse-room-memory-outbox",
                )
            receipt_state["state"] = "ready"
            _write_status(
                root,
                generation=generation,
                process_identity=process_identity,
                boot_id=boot_id,
                state="ready",
                started_at=started_at,
                mcp_port=mcp_port,
                readiness=readiness,
                host=composition.host.runtime_health_snapshot(),
            )
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(
                    root,
                    generation=generation,
                    process_identity=process_identity,
                    boot_id=boot_id,
                    started_at=started_at,
                    mcp_port=mcp_port,
                    readiness=readiness,
                    receipt_state=receipt_state,
                    host_health_snapshot=composition.host.runtime_health_snapshot,
                    stop=stop,
                ),
                name="xmuse-room-runner-heartbeat",
            )
            logger.info(
                "Room Runner ready generation=%s boot_id=%s max_concurrent_rooms=%d",
                generation,
                boot_id,
                max_concurrent_rooms,
            )

            shutdown_task = asyncio.create_task(stop.wait(), name="xmuse-room-runner-stop")
            try:
                done, _ = await asyncio.wait(
                    {host_task, native_task, heartbeat_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if heartbeat_task in done and not stop.is_set():
                    try:
                        heartbeat_task.result()
                    except Exception as exc:
                        if isinstance(exc, RoomRunnerError):
                            raise
                        raise RoomRunnerError("room_runner_heartbeat_failed") from exc
                    raise RoomRunnerError("room_runner_heartbeat_stopped")
                if host_task in done and not stop.is_set():
                    try:
                        host_task.result()
                    except Exception as exc:
                        raise RoomRunnerError("room_runner_host_loop_failed") from exc
                    raise RoomRunnerError("room_runner_host_loop_stopped")
                if native_task in done and not stop.is_set():
                    try:
                        native_task.result()
                    except Exception as exc:
                        raise RoomRunnerError("room_runner_native_bridge_failed") from exc
                    raise RoomRunnerError("room_runner_native_bridge_stopped")
            finally:
                if not shutdown_task.done():
                    shutdown_task.cancel()
                await asyncio.gather(shutdown_task, return_exceptions=True)

            receipt_state["state"] = "stopping"
            _write_status(
                root,
                generation=generation,
                process_identity=process_identity,
                boot_id=boot_id,
                state="stopping",
                started_at=started_at,
                mcp_port=mcp_port,
                readiness=readiness,
                host=composition.host.runtime_health_snapshot(),
            )
            stop.set()
            if host_task is not None:
                await host_task
            if native_task is not None:
                if not native_task.done():
                    native_task.cancel()
                await asyncio.gather(native_task, return_exceptions=True)
            await composition.native_runtime.shutdown()
            await composition.host.shutdown()
            await composition.session_layer.shutdown()
            receipt_state["state"] = "stopped"
            _write_status(
                root,
                generation=generation,
                process_identity=process_identity,
                boot_id=boot_id,
                state="stopped",
                started_at=started_at,
                mcp_port=mcp_port,
                readiness=readiness,
                host=composition.host.runtime_health_snapshot(),
            )
            composition = None
        except asyncio.CancelledError:
            stop.set()
            raise
        except Exception as exc:
            code = _error_code(exc)
            receipt_state["state"] = "failed"
            receipt_state["error_code"] = code
            if status_started:
                with suppress(Exception):
                    _write_status(
                        root,
                        generation=generation,
                        process_identity=process_identity,
                        boot_id=boot_id,
                        state="failed",
                        started_at=started_at,
                        mcp_port=mcp_port,
                        readiness=readiness,
                        host=(
                            composition.host.runtime_health_snapshot()
                            if composition is not None
                            else host_not_started
                        ),
                        error_code=code,
                    )
            raise RoomRunnerError(code) from exc
        finally:
            stop.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            if memory_task is not None:
                memory_task.cancel()
                await asyncio.gather(memory_task, return_exceptions=True)
            if native_task is not None and not native_task.done():
                native_task.cancel()
                await asyncio.gather(native_task, return_exceptions=True)
            if host_task is not None and not host_task.done():
                host_task.cancel()
                await asyncio.gather(host_task, return_exceptions=True)
            if composition is not None:
                with suppress(Exception):
                    await composition.stream_projector.shutdown()
                with suppress(Exception):
                    await composition.native_runtime.shutdown()
                with suppress(Exception):
                    await composition.host.shutdown()
                with suppress(Exception):
                    await composition.session_layer.shutdown()


def _prepare_room_codex_home(
    root: Path,
    *,
    source_home: Path | None = None,
) -> Path:
    """Create the persistent config-isolated Room Codex home.

    Only the authentication carrier is refreshed from the ambient Codex home.  Codex
    session state created inside this home is retained so participant-bound provider
    threads remain resumable across Room Runner restarts.
    """

    target_home = root / ROOM_CODEX_HOME_RELATIVE
    _ensure_private_directory(target_home)
    configured_source = source_home
    if configured_source is None:
        ambient = os.environ.get("CODEX_HOME")
        configured_source = Path(ambient) if ambient else Path.home() / ".codex"
    resolved_source = configured_source.expanduser().resolve()
    source_auth = resolved_source / CODEX_AUTH_FILE_NAME
    target_auth = target_home / CODEX_AUTH_FILE_NAME

    if resolved_source == target_home:
        _validate_private_auth_file(target_auth, allow_missing=True)
        return target_home

    try:
        source_metadata = source_auth.lstat()
    except FileNotFoundError:
        target_auth.unlink(missing_ok=True)
        return target_home
    except OSError as exc:
        raise RoomRunnerError("room_runner_codex_auth_unavailable") from exc
    if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISREG(source_metadata.st_mode):
        raise RoomRunnerError("room_runner_codex_auth_invalid")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{CODEX_AUTH_FILE_NAME}.",
        suffix=".tmp",
        dir=target_home,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target_handle:
            descriptor = -1
            source_descriptor = os.open(
                source_auth,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                while True:
                    block = os.read(source_descriptor, 64 * 1024)
                    if not block:
                        break
                    target_handle.write(block)
            finally:
                os.close(source_descriptor)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        os.replace(temporary_path, target_auth)
        os.chmod(target_auth, 0o600, follow_symlinks=False)
        _fsync_directory(target_home)
    except OSError as exc:
        raise RoomRunnerError("room_runner_codex_auth_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
    return target_home


def _ensure_private_directory(path: Path) -> None:
    try:
        if path.is_symlink():
            raise RoomRunnerError("room_runner_codex_home_invalid")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise RoomRunnerError("room_runner_codex_home_invalid")
        os.chmod(path, 0o700)
    except RoomRunnerError:
        raise
    except OSError as exc:
        raise RoomRunnerError("room_runner_codex_home_unavailable") from exc


def _validate_private_auth_file(path: Path, *, allow_missing: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise RoomRunnerError("room_runner_codex_auth_unavailable") from None
    except OSError as exc:
        raise RoomRunnerError("room_runner_codex_auth_unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RoomRunnerError("room_runner_codex_auth_invalid")
    try:
        os.chmod(path, 0o600, follow_symlinks=False)
    except OSError as exc:
        raise RoomRunnerError("room_runner_codex_auth_unavailable") from exc


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _heartbeat_loop(
    root: Path,
    *,
    generation: str,
    process_identity: str,
    boot_id: str,
    started_at: str,
    mcp_port: int,
    readiness: Mapping[str, bool],
    receipt_state: Mapping[str, Any],
    host_health_snapshot: Callable[[], Mapping[str, Any]],
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=ROOM_RUNNER_HEARTBEAT_INTERVAL_S)
            continue
        except TimeoutError:
            pass
        _write_status(
            root,
            generation=generation,
            process_identity=process_identity,
            boot_id=boot_id,
            state=str(receipt_state["state"]),
            started_at=started_at,
            mcp_port=mcp_port,
            readiness=readiness,
            host=host_health_snapshot(),
            error_code=receipt_state.get("error_code"),
        )


async def _wait_for_room_mcp(
    host: str,
    port: int,
    *,
    probe: Callable[[str, int], tuple[bool, bool]],
) -> tuple[bool, bool]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MCP_STARTUP_PROBE_TIMEOUT_S
    last = (False, False)
    while True:
        try:
            last = await asyncio.to_thread(probe, host, port)
        except Exception:
            last = (False, False)
        if last == (True, True):
            return last
        if loop.time() >= deadline:
            return last
        await asyncio.sleep(0.2)


def _probe_room_mcp_once(host: str, port: int) -> tuple[bool, bool]:
    health_url = f"http://{host}:{port}/health"
    room_url = f"http://{host}:{port}{ROOM_MCP_PATH}"
    try:
        with urllib.request.urlopen(health_url, timeout=MCP_REQUEST_TIMEOUT_S) as response:  # noqa: S310
            health_payload = _read_bounded_json(response)
        health_ok = (
            isinstance(health_payload, dict)
            and health_payload.get("status") == "ok"
            and health_payload.get("surface") == ROOM_MCP_SURFACE
            and health_payload.get("endpoints") == {"mcp_room": ROOM_MCP_PATH}
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        health_ok = False

    request = urllib.request.Request(  # noqa: S310
        room_url,
        data=json.dumps(
            {"jsonrpc": "2.0", "id": "room-runner-readiness", "method": "tools/list"},
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=MCP_REQUEST_TIMEOUT_S) as response:  # noqa: S310
            tools_payload = _read_bounded_json(response)
        tools = tools_payload.get("result", {}).get("tools")
        tools_ok = (
            isinstance(tools, list)
            and len(tools) == 1
            and isinstance(tools[0], dict)
            and tools[0].get("name") == ROOM_OUTCOME_TOOL
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, AttributeError):
        tools_ok = False
    return health_ok, tools_ok


_MAX_HTTP_RESPONSE_BYTES = 1024 * 1024


def _read_bounded_json(response: Any) -> Any:
    raw = response.read(_MAX_HTTP_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_HTTP_RESPONSE_BYTES:
        raise ValueError("room_runner_mcp_response_too_large")
    return json.loads(raw)


def _write_status(
    root: Path,
    *,
    generation: str,
    process_identity: str,
    boot_id: str,
    state: str,
    started_at: str,
    mcp_port: int,
    readiness: Mapping[str, bool],
    host: Mapping[str, Any],
    error_code: str | None = None,
) -> None:
    try:
        write_room_runner_status(
            root,
            generation=generation,
            pid=os.getpid(),
            start_identity=process_identity,
            boot_id=boot_id,
            state=state,  # type: ignore[arg-type]
            started_at=started_at,
            mcp_port=mcp_port,
            readiness=readiness,
            host=host,
            error_code=error_code,
        )
    except RoomRunnerStatusError as exc:
        raise RoomRunnerError(exc.code) from exc
    except OSError as exc:
        raise RoomRunnerError("room_runner_status_write_failed") from exc


def _has_room_persistent_session_launcher(launchers: Mapping[Any, object]) -> bool:
    return any(
        getattr(launcher, "supports_persistent_sessions", False) is True
        and getattr(launcher, "mcp_path", None) == ROOM_MCP_PATH
        and getattr(launcher, "sandbox_profile", None) == CODEX_ROOM_READ_ONLY_SANDBOX
        and isinstance(getattr(launcher, "codex_home", None), Path)
        and (
            callable(getattr(launcher, "spawn_persistent_session", None))
            or callable(getattr(launcher, "build_persistent_command", None))
        )
        for launcher in launchers.values()
    )


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            continue


def _resolve_worktree(value: Path | None) -> Path:
    configured = value
    if configured is None:
        override = os.environ.get("XMUSE_PEER_CHAT_WORKTREE")
        configured = Path(override) if override else REPO_ROOT
    resolved = configured.expanduser().resolve()
    if not resolved.is_dir():
        raise RoomRunnerError("room_runner_worktree_unavailable")
    return resolved


def _validate_run_configuration(
    *,
    generation: str,
    mcp_port: int,
    max_concurrent_rooms: int,
    delivery_timeout_s: float,
    cleanup_grace_s: float,
) -> None:
    if not isinstance(generation, str) or _SAFE_GENERATION.fullmatch(generation) is None:
        raise RoomRunnerError("room_runner_generation_invalid")
    if isinstance(mcp_port, bool) or not isinstance(mcp_port, int) or not (1 <= mcp_port <= 65_535):
        raise RoomRunnerError("room_runner_mcp_port_invalid")
    if (
        isinstance(max_concurrent_rooms, bool)
        or not isinstance(max_concurrent_rooms, int)
        or max_concurrent_rooms <= 0
    ):
        raise RoomRunnerError("room_runner_max_concurrent_rooms_invalid")
    for value, code, allow_zero in (
        (delivery_timeout_s, "room_runner_delivery_timeout_invalid", False),
        (cleanup_grace_s, "room_runner_cleanup_grace_invalid", False),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or (float(value) < 0 if allow_zero else float(value) <= 0)
        ):
            raise RoomRunnerError(code)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, RoomRunnerError):
        return exc.code
    if isinstance(exc, RoomRunnerStatusError):
        return exc.code
    return "room_runner_failed"


def main_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="xmuse Room-only participant runner")
    parser.add_argument("--xmuse-root", type=Path, default=DEFAULT_XMUSE_ROOT)
    parser.add_argument(
        "--generation",
        default=os.environ.get("XMUSE_WORKROOM_GENERATION"),
        help="managed Workroom generation; defaults to XMUSE_WORKROOM_GENERATION or a UUID",
    )
    parser.add_argument("--mcp-port", type=int, default=DEFAULT_MCP_PORT)
    parser.add_argument(
        "--max-concurrent-rooms",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_ROOMS,
    )
    parser.add_argument(
        "--delivery-timeout-s",
        type=float,
        default=DEFAULT_DELIVERY_TIMEOUT_S,
    )
    parser.add_argument(
        "--cleanup-grace-s",
        type=float,
        default=DEFAULT_CLEANUP_GRACE_S,
    )
    parser.add_argument("--worktree", type=Path, default=None)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = main_arg_parser().parse_args()
    root = resolve_xmuse_root(args.xmuse_root, fallback=DEFAULT_XMUSE_ROOT)
    generation = args.generation or uuid.uuid4().hex
    try:
        asyncio.run(
            run_room_runner(
                xmuse_root=root,
                generation=generation,
                mcp_port=args.mcp_port,
                max_concurrent_rooms=args.max_concurrent_rooms,
                delivery_timeout_s=args.delivery_timeout_s,
                cleanup_grace_s=args.cleanup_grace_s,
                worktree=args.worktree,
            )
        )
    except (RoomRunnerError, RoomRunnerStatusError) as exc:
        code = getattr(exc, "code", "room_runner_failed")
        logger.error("Room Runner stopped: %s", code)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
