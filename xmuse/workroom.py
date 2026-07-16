#!/usr/bin/env python3
"""Run and inspect the local xmuse Workroom application."""

from __future__ import annotations

import fcntl
import importlib.metadata
import json
import os
import shutil
import signal
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Literal, cast

from xmuse.workroom_contracts import (
    WORKROOM_REPO_ROOT,
    WorkroomDependencies,
    WorkroomPaths,
)
from xmuse.workroom_manifest import (
    ManifestError as ManifestLeafError,
)
from xmuse.workroom_manifest import (
    atomic_write_manifest,
    base_manifest,
    read_manifest,
    update_manifest,
    write_if_generation_current,
)
from xmuse.workroom_memoryos import (
    MemoryOSRuntimeControl,
    defer_memoryos_for_unknown_port,
    mark_memoryos_healthy,
    memoryos_record_for_identity,
    prepare_memoryos_spawn,
    retry_wall_time,
    schedule_memoryos_recovery,
    set_memoryos_rebuilding,
)
from xmuse.workroom_processes import (
    ManagedProcess,
    ProcessIdentity,
    ProcessLifecycleError,
    ProcessSpec,
    identity_matches,
    port_available,
    record_process,
    service_is_live,
    stop_service_record,
    stop_spawned_processes,
)
from xmuse.workroom_status import build_status_projection
from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_HOST,
    MEMORYOS_PORT,
    MEMORYOS_RUNTIME_SCHEMA,
    MemoryOSSupervisorError,
    assess_memoryos_status,
    clear_memoryos_derived_cache,
    memoryos_child_environment,
    memoryos_command,
    memoryos_incident_guard,
    memoryos_rebuildability,
    prepare_memoryos_derived_cache,
    read_memoryos_status,
    resolve_memoryos_executable,
    safe_memoryos_status,
    write_memoryos_status,
)
from xmuse_core.chat.room_execution_profiles import (
    RoomExecutionProfileError,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_memory_rebuild_store import RoomMemoryRebuildActionStore
from xmuse_core.chat.room_runtime import (
    assess_room_runner_status,
)
from xmuse_core.chat.room_runtime_supervisor import room_mcp_health_ready
from xmuse_core.runtime.child_env import normalize_child_temp_env
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.runtime.root_contract import (
    DATA_OPERATION_JOURNAL_NAME as DATA_OPERATION_JOURNAL_NAME,
)
from xmuse_core.runtime.root_contract import WORKROOM_LIFECYCLE_LOCK_NAME, WORKROOM_MANIFEST_NAME

SCHEMA_VERSION = "xmuse_workroom_runtime/v1"
STATUS_SCHEMA_VERSION = "xmuse_workroom_status/v2"
DOCTOR_SCHEMA_VERSION = "xmuse_workroom_doctor/v1"
COMMAND_SCHEMA_VERSION = "xmuse_workroom_command/v1"
CHAT_API_HOST = "127.0.0.1"
CHAT_API_PORT = 8201
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 3000
MEMORYOS_HEARTBEAT_INTERVAL_S = 5.0
REPO_ROOT = WORKROOM_REPO_ROOT
DEFAULT_EXECUTION_PROFILE_ID = "xmuse-monorepo/v2"
DEFAULT_XMUSE_ROOT = default_xmuse_root(REPO_ROOT / "xmuse")
MANIFEST_NAME = WORKROOM_MANIFEST_NAME
LOCK_NAME = WORKROOM_LIFECYCLE_LOCK_NAME


class WorkroomError(RuntimeError):
    """A stable, user-facing Workroom lifecycle error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ManifestError(WorkroomError):
    pass


def _package_version() -> str:
    try:
        return importlib.metadata.version("xmuse")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


_port_available = port_available


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return read_manifest(path, schema_version=SCHEMA_VERSION)
    except ManifestLeafError as exc:
        raise ManifestError(exc.code, str(exc)) from exc


def _atomic_write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_manifest(path, payload)


@contextmanager
def _lifecycle_lock(paths: WorkroomPaths) -> Iterator[None]:
    paths.xmuse_root.mkdir(parents=True, exist_ok=True)
    with paths.lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _error_payload(command: str, exc: WorkroomError) -> dict[str, Any]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "command": command,
        "state": "error",
        "error": {"code": exc.code, "message": str(exc)},
    }


def _manager_is_live(manifest: Mapping[str, Any], deps: WorkroomDependencies) -> bool:
    manager = manifest.get("manager")
    if not isinstance(manager, dict):
        return False
    return _identity_matches(manager, deps.inspect_process, require_scope=False)


def _service_is_live(
    record: Mapping[str, Any],
    *,
    generation: str,
    xmuse_root: Path,
    deps: WorkroomDependencies,
) -> bool:
    return service_is_live(
        record,
        generation=generation,
        xmuse_root=xmuse_root,
        inspector=deps.inspect_process,
    )


def _identity_matches(
    record: Mapping[str, Any],
    inspector: Callable[[int], ProcessIdentity | None],
    *,
    require_scope: bool,
) -> bool:
    del require_scope
    return identity_matches(record, inspector)


def _manifest_has_live_services(
    manifest: Mapping[str, Any], paths: WorkroomPaths, deps: WorkroomDependencies
) -> bool:
    generation = manifest.get("generation")
    services = manifest.get("services")
    if not isinstance(generation, str) or not isinstance(services, dict):
        return False
    return any(
        isinstance(record, dict)
        and _service_is_live(
            record,
            generation=generation,
            xmuse_root=paths.xmuse_root,
            deps=deps,
        )
        for record in services.values()
    )


def _base_manifest(
    paths: WorkroomPaths,
    *,
    generation: str,
    manager_identity: ProcessIdentity,
    deps: WorkroomDependencies,
    execution_workspace: Path | None = None,
    execution_profile_id: str = DEFAULT_EXECUTION_PROFILE_ID,
    memory_enabled: bool = False,
) -> dict[str, Any]:
    stamp = deps.now()
    workspace = (execution_workspace or paths.repo_root).expanduser().resolve()
    profile = get_execution_gate_profile(execution_profile_id)
    return base_manifest(
        generation=generation,
        version=_package_version(),
        started_at=stamp,
        repo_root=paths.repo_root,
        xmuse_root=paths.xmuse_root,
        manager_pid=deps.current_pid(),
        manager_start_identity=manager_identity.start_identity,
        runner_pid_file=paths.runner_pid_file,
        mcp_pid_file=paths.mcp_pid_file,
        runner_status_file=paths.room_runner_status_file,
        execution_workspace=workspace,
        execution_gate_profile=profile.safe_reference(),
        memory_enabled=memory_enabled,
    )


def _update_manifest(
    manifest: dict[str, Any],
    deps: WorkroomDependencies,
    *,
    state: str | None = None,
) -> None:
    updated = update_manifest(manifest, updated_at=deps.now(), state=state)
    manifest.clear()
    manifest.update(updated)


def _record_process(
    process: ManagedProcess,
    *,
    service: str,
    generation: str,
    host: str,
    port: int,
    url: str,
    log_path: Path,
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    try:
        return record_process(
            process,
            service=service,
            generation=generation,
            host=host,
            port=port,
            url=url,
            log_path=log_path,
            xmuse_root=paths.xmuse_root,
            inspector=deps.inspect_process,
            monotonic=deps.monotonic,
            sleep=deps.sleep,
            timeout_s=timeout_s,
        )
    except ProcessLifecycleError as exc:
        raise WorkroomError(exc.code, str(exc)) from exc


def _wait_for_ready(
    *,
    service: str,
    url: str,
    process: ManagedProcess,
    timeout_s: float,
    deps: WorkroomDependencies,
) -> None:
    deadline = deps.monotonic() + timeout_s
    while True:
        return_code = process.poll()
        if return_code is not None:
            raise WorkroomError(
                "service_exited",
                f"{service} exited before readiness (code {return_code})",
            )
        if deps.http_ready(url):
            return
        if deps.monotonic() >= deadline:
            raise WorkroomError(
                "readiness_timeout",
                f"{service} did not become ready within {timeout_s:g} seconds",
            )
        deps.sleep(0.1)


def _replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)


def _sync_standalone_assets(paths: WorkroomPaths) -> None:
    _replace_tree(paths.static_source, paths.static_destination)
    _replace_tree(paths.public_source, paths.public_destination)


def _preflight_start(paths: WorkroomPaths, deps: WorkroomDependencies) -> str:
    if paths.data_operation_journal.exists():
        raise WorkroomError(
            "data_operation_incomplete",
            "an interrupted xmuse-data operation must be recovered before Workroom start",
        )
    node = deps.which("node")
    if not node:
        raise WorkroomError("node_missing", "Node.js is required to run the Workroom frontend")
    if not deps.which("codex"):
        raise WorkroomError(
            "codex_missing",
            "Codex CLI is required to run Workroom Room Agents",
        )
    if not paths.standalone_server.is_file():
        raise WorkroomError(
            "standalone_build_missing",
            "frontend/.next/standalone/server.js is missing; run npm run build in frontend",
        )
    if not paths.static_source.is_dir():
        raise WorkroomError(
            "static_assets_missing",
            "frontend/.next/static is missing; run npm run build in frontend",
        )
    for service, host, port in (
        ("chat_api", CHAT_API_HOST, CHAT_API_PORT),
        ("frontend", FRONTEND_HOST, FRONTEND_PORT),
    ):
        if not deps.port_available(host, port):
            raise WorkroomError(
                "port_in_use",
                f"{service} port is already in use: {host}:{port}",
            )
    return node


def _child_environment(
    deps: WorkroomDependencies,
    paths: WorkroomPaths,
    *,
    generation: str,
    token: str,
    service: str,
) -> dict[str, str]:
    environment = normalize_child_temp_env(deps.environ)
    environment.update(
        {
            "XMUSE_ROOT": str(paths.xmuse_root),
            "XMUSE_OPERATOR_TOKEN": token,
            "XMUSE_WORKROOM_MANAGED": "1",
            "XMUSE_WORKROOM_GENERATION": generation,
            "XMUSE_WORKROOM_SERVICE": service,
        }
    )
    return environment


def _spawn_chat_api(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    generation: str,
    token: str,
    execution_workspace: Path,
    execution_profile_id: str,
    memoryos_url: str | None = None,
    memoryos_api_key: str | None = None,
    memoryos_profile: str = "full-local",
) -> tuple[ManagedProcess, ProcessSpec]:
    log_path = paths.xmuse_root / "logs" / "workroom-chat-api.log"
    environment = _child_environment(
        deps, paths, generation=generation, token=token, service="chat_api"
    )
    environment["PYTHONUNBUFFERED"] = "1"
    environment["XMUSE_CHAT_API_URL"] = f"http://{CHAT_API_HOST}:{CHAT_API_PORT}"
    environment["XMUSE_WORKSPACE_ROOT"] = str(execution_workspace)
    environment["XMUSE_EXECUTION_PROFILE_ID"] = execution_profile_id
    if memoryos_url is not None and memoryos_api_key is not None:
        environment["XMUSE_MEMORYOS_URL"] = memoryos_url
        environment["XMUSE_MEMORYOS_API_KEY"] = memoryos_api_key
        environment["XMUSE_MEMORYOS_PROFILE"] = memoryos_profile
    spec = ProcessSpec(
        service="chat_api",
        command=(sys.executable, "-m", "xmuse.chat_api"),
        cwd=paths.repo_root,
        env=environment,
        log_path=log_path,
    )
    return deps.spawn(spec), spec


def _spawn_memoryos(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    executable: Path,
    generation: str,
    api_key: str,
    profile: str = "full-local",
) -> tuple[ManagedProcess, ProcessSpec]:
    prepare_memoryos_derived_cache(paths.xmuse_root)
    environment = memoryos_child_environment(
        deps.environ,
        xmuse_root=paths.xmuse_root,
        generation=generation,
        api_key=api_key,
        profile=profile,
    )
    spec = ProcessSpec(
        service="memoryos",
        command=memoryos_command(executable),
        # Upstream Settings reads a cwd-local .env.  The derived directory is
        # deliberately empty of user configuration and is safe to rebuild.
        cwd=paths.memoryos_derived_dir,
        env=environment,
        log_path=paths.xmuse_root / "logs" / "workroom-memoryos.log",
    )
    return deps.spawn(spec), spec


def _retry_wall_time(now: str, delay_s: int) -> str:
    return retry_wall_time(now, delay_s)


def _write_memoryos_control_status(
    control: MemoryOSRuntimeControl,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    state: str,
    code: str,
) -> dict[str, Any]:
    generation = manifest.get("generation")
    record = control.record
    try:
        return write_memoryos_status(
            paths.xmuse_root,
            enabled=True,
            state=state,  # type: ignore[arg-type]
            code=code,
            generation=generation if isinstance(generation, str) else None,
            pid=record.get("pid") if isinstance(record, Mapping) else None,
            start_identity=(record.get("start_identity") if isinstance(record, Mapping) else None),
            started_at=control.started_at,
            consecutive_restart_count=control.consecutive_restart_count,
            next_retry_at=control.next_retry_at,
            last_healthy_at=control.last_healthy_at,
            profile=control.profile,
        )
    except Exception:
        return {
            "schema_version": MEMORYOS_RUNTIME_SCHEMA,
            "enabled": True,
            "state": "degraded",
            "code": "memoryos_status_write_failed",
            "consecutive_restart_count": control.consecutive_restart_count,
            "next_retry_at": control.next_retry_at,
            "last_healthy_at": control.last_healthy_at,
        }


def _schedule_memoryos_recovery(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    code: str,
) -> dict[str, Any]:
    decision = schedule_memoryos_recovery(
        control,
        code=code,
        monotonic_now=deps.monotonic(),
        wall_time_now=deps.now(),
    )
    services = manifest.get("services")
    if isinstance(services, dict) and "memoryos" in services:
        services.pop("memoryos", None)
        _update_manifest(manifest, deps)
        _atomic_write_manifest(paths.manifest, manifest)
    return _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state=decision.state,
        code=decision.code,
    )


def _defer_memoryos_for_unknown_port(
    control: MemoryOSRuntimeControl,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    decision = defer_memoryos_for_unknown_port(
        control,
        monotonic_now=deps.monotonic(),
        wall_time_now=deps.now(),
    )
    return _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state=decision.state,
        code=decision.code,
    )


def _memoryos_record_for_identity(
    process: ManagedProcess,
    identity: ProcessIdentity,
    *,
    generation: str,
    paths: WorkroomPaths,
) -> dict[str, Any] | None:
    return memoryos_record_for_identity(
        process,
        identity,
        generation=generation,
        xmuse_root=paths.xmuse_root,
    )


def _publish_memoryos_record(
    manifest: dict[str, Any],
    record: Mapping[str, Any],
    deps: WorkroomDependencies,
    paths: WorkroomPaths,
) -> None:
    services = manifest.setdefault("services", {})
    if not isinstance(services, dict):
        raise WorkroomError("invalid_manifest", "Workroom services manifest is invalid")
    services["memoryos"] = dict(record)
    _update_manifest(manifest, deps)
    _atomic_write_manifest(paths.manifest, manifest)


def _attempt_memoryos_spawn(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    generation = manifest.get("generation")
    if not isinstance(generation, str) or not generation:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_generation_invalid",
        )
    decision = prepare_memoryos_spawn(control, started_at=deps.now())
    _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state=decision.state,
        code=decision.code,
    )
    try:
        process, _spec = _spawn_memoryos(
            paths,
            deps,
            executable=control.executable,
            generation=generation,
            api_key=control.api_key,
            profile=control.profile,
        )
    except MemoryOSSupervisorError as exc:
        return _schedule_memoryos_recovery(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            code=exc.code,
        )
    except (OSError, WorkroomError):
        return _schedule_memoryos_recovery(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            code="memoryos_spawn_failed",
        )
    control.process = process
    if process.poll() is not None:
        return _schedule_memoryos_recovery(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            code="memoryos_process_exited",
        )
    try:
        identity = deps.inspect_process(process.pid)
    except Exception:
        identity = None
    if identity is None:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_process_identity_unavailable",
        )
    record = _memoryos_record_for_identity(
        process,
        identity,
        generation=generation,
        paths=paths,
    )
    if record is None:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_process_identity_mismatch",
        )
    control.record = record
    _publish_memoryos_record(manifest, record, deps, paths)
    return _assess_live_memoryos(control, manifest=manifest, paths=paths, deps=deps)


def _assess_live_memoryos(
    control: MemoryOSRuntimeControl,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    process = control.process
    record = control.record
    generation = manifest.get("generation")
    if process is None or not isinstance(record, Mapping) or not isinstance(generation, str):
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_process_identity_unavailable",
        )
    try:
        identity = deps.inspect_process(process.pid)
    except Exception:
        identity = None
    if identity is None:
        control.healthy_since_monotonic = None
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_process_identity_unavailable",
        )
    observed = _memoryos_record_for_identity(process, identity, generation=generation, paths=paths)
    if observed is None or observed.get("start_identity") != record.get("start_identity"):
        control.healthy_since_monotonic = None
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_process_identity_mismatch",
        )
    try:
        healthy = deps.http_ready(f"{control.url}/health")
    except Exception:
        healthy = False
    if not healthy:
        control.healthy_since_monotonic = None
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_health_unavailable",
        )
    if control.profile == "full-local":
        try:
            health_payload = deps.http_json(f"{control.url}/health")
        except Exception:
            health_payload = None
        capabilities = (
            health_payload.get("capabilities") if isinstance(health_payload, Mapping) else None
        )
        hybrid = capabilities.get("hybrid") if isinstance(capabilities, Mapping) else None
        full_local_ready = (
            isinstance(capabilities, Mapping)
            and isinstance(hybrid, Mapping)
            and hybrid.get("lexical") is True
            and hybrid.get("semantic") is True
            and hybrid.get("rrf") is True
            and capabilities.get("message_ingest") is True
            and capabilities.get("agentic_advisory") is True
            and capabilities.get("paging") is True
        )
        if not full_local_ready:
            control.healthy_since_monotonic = None
            return _write_memoryos_control_status(
                control,
                manifest=manifest,
                paths=paths,
                deps=deps,
                state="degraded",
                code="memoryos_full_local_capability_missing",
            )
    decision = mark_memoryos_healthy(
        control,
        monotonic_now=deps.monotonic(),
        wall_time_now=deps.now(),
    )
    return _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state=decision.state,
        code=decision.code,
    )


def _reconcile_memoryos_runtime_locked(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    if control.rebuild_blocked_code is not None:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code=control.rebuild_blocked_code,
        )
    if control.rebuilding:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="rebuilding",
            code="memoryos_rebuilding",
        )
    process = control.process
    if process is not None:
        if process.poll() is not None:
            if control.next_retry_monotonic is None:
                return _schedule_memoryos_recovery(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    code="memoryos_process_exited",
                )
        elif control.record is None:
            generation = manifest.get("generation")
            try:
                identity = deps.inspect_process(process.pid)
            except Exception:
                identity = None
            if identity is None:
                return _write_memoryos_control_status(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    state="degraded",
                    code="memoryos_process_identity_unavailable",
                )
            record = (
                _memoryos_record_for_identity(
                    process,
                    identity,
                    generation=generation,
                    paths=paths,
                )
                if isinstance(generation, str)
                else None
            )
            if record is None:
                return _write_memoryos_control_status(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    state="degraded",
                    code="memoryos_process_identity_mismatch",
                )
            control.record = record
            _publish_memoryos_record(manifest, record, deps, paths)
            return _assess_live_memoryos(control, manifest=manifest, paths=paths, deps=deps)
        else:
            return _assess_live_memoryos(control, manifest=manifest, paths=paths, deps=deps)

    deadline = control.next_retry_monotonic
    if deadline is not None and deps.monotonic() < deadline:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state=control.retry_state or "recovering",
            code=control.retry_code or "memoryos_recovering",
        )
    services = manifest.get("services")
    unmanaged = services.get("memoryos") if isinstance(services, Mapping) else None
    if isinstance(unmanaged, Mapping):
        pid = unmanaged.get("pid")
        try:
            identity = deps.inspect_process(pid) if isinstance(pid, int) else None
        except Exception:
            identity = None
        code = "memoryos_process_identity_unavailable"
        if identity is not None and identity.start_identity != unmanaged.get("start_identity"):
            code = "memoryos_process_identity_mismatch"
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code=code,
        )
    if not deps.port_available(MEMORYOS_HOST, MEMORYOS_PORT):
        return _defer_memoryos_for_unknown_port(control, manifest=manifest, paths=paths, deps=deps)
    return _attempt_memoryos_spawn(control, manifest=manifest, paths=paths, deps=deps)


def reconcile_memoryos_runtime(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    lifecycle_locked: bool = False,
) -> dict[str, Any]:
    """Reconcile one optional child without ever replacing an unverified live PID."""

    def reconcile_if_current() -> dict[str, Any]:
        current = _read_manifest(paths.manifest)
        if (
            current is None
            or current.get("generation") != manifest.get("generation")
            or current.get("state") in {"stopping", "stopped", "failed"}
        ):
            return {
                "schema_version": MEMORYOS_RUNTIME_SCHEMA,
                "enabled": True,
                "state": "stopped",
                "code": "memoryos_reconcile_not_current",
            }
        return _reconcile_memoryos_runtime_locked(
            control, manifest=manifest, paths=paths, deps=deps
        )

    if lifecycle_locked:
        return reconcile_if_current()
    with _lifecycle_lock(paths):
        return reconcile_if_current()


def _reconcile_optional_memoryos_runtime(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    lifecycle_locked: bool = False,
) -> dict[str, Any]:
    """Keep optional-sidecar failures outside required Workroom readiness."""

    try:
        return reconcile_memoryos_runtime(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            lifecycle_locked=lifecycle_locked,
        )
    except Exception:
        return _write_memoryos_control_status(
            control,
            manifest=manifest,
            paths=paths,
            deps=deps,
            state="degraded",
            code="memoryos_reconcile_failed",
        )


def _memoryos_rebuild_failure(
    action_store: RoomMemoryRebuildActionStore,
    action: Mapping[str, Any],
    *,
    control: MemoryOSRuntimeControl,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    status: str,
    reason_code: str,
) -> dict[str, Any]:
    set_memoryos_rebuilding(control, False)
    control.rebuild_blocked_code = None
    _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state="degraded",
        code=reason_code,
    )
    return action_store.finish(
        client_action_id=str(action["client_action_id"]),
        status=status,  # type: ignore[arg-type]
        after_state="degraded",
        after_code=reason_code,
        reason_code=reason_code,
    )


def _memoryos_rebuild_blocked(
    action: Mapping[str, Any],
    *,
    control: MemoryOSRuntimeControl,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    reason_code: str,
) -> dict[str, Any]:
    """Keep a post-authorization action pending without restarting its cache."""

    set_memoryos_rebuilding(control, True)
    control.rebuild_blocked_code = reason_code
    _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state="degraded",
        code=reason_code,
    )
    return dict(action)


def _stop_memoryos_for_rebuild(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    timeout_s: float,
) -> None:
    generation = manifest.get("generation")
    if not isinstance(generation, str) or not generation:
        raise WorkroomError(
            "memoryos_rebuild_generation_invalid",
            "cannot prove the Workroom generation for a MemoryOS rebuild",
        )
    services = manifest.get("services")
    manifest_record = services.get("memoryos") if isinstance(services, dict) else None
    record = control.record if isinstance(control.record, Mapping) else manifest_record
    process = control.process

    if process is not None and process.poll() is None:
        if not isinstance(record, Mapping) or not _record_matches_live_process(
            record,
            generation=generation,
            xmuse_root=paths.xmuse_root,
            deps=deps,
        ):
            if process.poll() is None:
                raise WorkroomError(
                    "memoryos_rebuild_process_unverifiable",
                    "cannot safely identify the live MemoryOS process",
                )
        elif not _stop_service_record(
            record,
            generation=generation,
            paths=paths,
            deps=deps,
            timeout_s=timeout_s,
        ):
            raise WorkroomError(
                "memoryos_rebuild_stop_timeout",
                "MemoryOS did not stop before the rebuild deadline",
            )
    elif process is None and isinstance(record, Mapping):
        pid = record.get("pid")
        if not isinstance(pid, int):
            raise WorkroomError(
                "memoryos_rebuild_process_unverifiable",
                "cannot safely identify the MemoryOS process",
            )
        try:
            identity = deps.inspect_process(pid)
        except Exception as exc:
            raise WorkroomError(
                "memoryos_rebuild_process_unverifiable",
                "cannot inspect the MemoryOS process identity",
            ) from exc
        if identity is not None:
            if not _record_matches_live_process(
                record,
                generation=generation,
                xmuse_root=paths.xmuse_root,
                deps=deps,
            ):
                raise WorkroomError(
                    "memoryos_rebuild_process_unverifiable",
                    "the recorded MemoryOS identity no longer matches",
                )
            if not _stop_service_record(
                record,
                generation=generation,
                paths=paths,
                deps=deps,
                timeout_s=timeout_s,
            ):
                raise WorkroomError(
                    "memoryos_rebuild_stop_timeout",
                    "MemoryOS did not stop before the rebuild deadline",
                )

    if not deps.port_available(MEMORYOS_HOST, MEMORYOS_PORT):
        raise WorkroomError(
            "memoryos_rebuild_port_occupied",
            "the fixed MemoryOS port is still occupied",
        )
    control.process = None
    control.record = None
    control.started_at = None
    control.next_retry_monotonic = None
    control.next_retry_at = None
    control.retry_state = None
    control.retry_code = None
    control.rebuild_blocked_code = None
    if isinstance(services, dict):
        services.pop("memoryos", None)
        _update_manifest(manifest, deps)
        _atomic_write_manifest(paths.manifest, manifest)
    _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state="rebuilding",
        code="memoryos_rebuilding",
    )


def reconcile_memoryos_rebuild_action(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    action_store: RoomMemoryRebuildActionStore,
    lifecycle_locked: bool = False,
    stop_timeout_s: float = 10.0,
) -> dict[str, Any] | None:
    """Advance at most one durable, generation-fenced rebuild phase."""

    def reconcile_if_current() -> dict[str, Any] | None:
        current_manifest = _read_manifest(paths.manifest)
        generation = manifest.get("generation")
        if (
            current_manifest is None
            or current_manifest.get("generation") != generation
            or current_manifest.get("state") in {"stopping", "stopped", "failed"}
        ):
            return None
        action = action_store.next_requested()
        if action is None:
            if control.rebuilding:
                set_memoryos_rebuilding(control, False)
            return None
        phase = action.get("phase")
        action_generation = action.get("_runtime_generation")
        if (
            phase == "requested"
            and action_generation is not None
            and action_generation != generation
        ):
            return _memoryos_rebuild_failure(
                action_store,
                action,
                control=control,
                manifest=manifest,
                paths=paths,
                deps=deps,
                status="rejected",
                reason_code="memoryos_rebuild_generation_changed",
            )
        client_action_id = str(action["client_action_id"])
        if phase == "requested":
            receipt = read_memoryos_status(paths.xmuse_root)
            rebuildability = memoryos_rebuildability(receipt or {})
            guard_matches = (
                receipt is not None
                and receipt.get("generation") == generation
                and memoryos_incident_guard(receipt) == action.get("_incident_guard")
            )
            if not guard_matches:
                return _memoryos_rebuild_failure(
                    action_store,
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    status="rejected",
                    reason_code="memoryos_rebuild_incident_changed",
                )
            if not rebuildability.get("available"):
                return _memoryos_rebuild_failure(
                    action_store,
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    status="rejected",
                    reason_code="memoryos_rebuild_not_available",
                )
            control.rebuild_blocked_code = None
            set_memoryos_rebuilding(control, True)
            return action_store.advance(
                client_action_id=client_action_id,
                expected_phase="requested",
                phase="stopping",
            )

        if phase == "stopping":
            set_memoryos_rebuilding(control, True)
            try:
                _stop_memoryos_for_rebuild(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    timeout_s=stop_timeout_s,
                )
            except WorkroomError as exc:
                return _memoryos_rebuild_failure(
                    action_store,
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    status="failed",
                    reason_code=exc.code,
                )
            return action_store.advance(
                client_action_id=client_action_id,
                expected_phase="stopping",
                phase="stopped",
            )

        if phase == "stopped":
            set_memoryos_rebuilding(control, True)
            control.rebuild_blocked_code = None
            try:
                _stop_memoryos_for_rebuild(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    timeout_s=stop_timeout_s,
                )
                cache_cleared = clear_memoryos_derived_cache(paths.xmuse_root)
            except (MemoryOSSupervisorError, WorkroomError) as exc:
                return _memoryos_rebuild_blocked(
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    reason_code=exc.code,
                )
            return action_store.advance(
                client_action_id=client_action_id,
                expected_phase="stopped",
                phase="cache_cleared",
                result={"cache_cleared": cache_cleared},
            )

        if phase == "cache_cleared":
            set_memoryos_rebuilding(control, True)
            control.rebuild_blocked_code = None
            try:
                _stop_memoryos_for_rebuild(
                    control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    timeout_s=stop_timeout_s,
                )
                clear_memoryos_derived_cache(paths.xmuse_root)
            except (MemoryOSSupervisorError, WorkroomError) as exc:
                return _memoryos_rebuild_blocked(
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    reason_code=exc.code,
                )
            return action_store.reset_authority(client_action_id=client_action_id)

        if phase == "authority_reset":
            control.rebuild_blocked_code = None
            set_memoryos_rebuilding(control, False)
            return action_store.advance(
                client_action_id=client_action_id,
                expected_phase="authority_reset",
                phase="restarting",
            )

        if phase == "restarting":
            control.rebuild_blocked_code = None
            status = _reconcile_optional_memoryos_runtime(
                control,
                manifest=manifest,
                paths=paths,
                deps=deps,
                lifecycle_locked=True,
            )
            if status.get("state") != "ready":
                return action
            return action_store.advance(
                client_action_id=client_action_id,
                expected_phase="restarting",
                phase="replaying",
            )

        if phase == "replaying":
            status = _reconcile_optional_memoryos_runtime(
                control,
                manifest=manifest,
                paths=paths,
                deps=deps,
                lifecycle_locked=True,
            )
            if status.get("state") != "ready":
                return action
            replay = action_store.replay_status()
            if replay.get("conflict", 0) > 0:
                return _memoryos_rebuild_failure(
                    action_store,
                    action,
                    control=control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    status="failed",
                    reason_code="memoryos_rebuild_replay_conflict",
                )
            if all(value == 0 for value in replay.values()):
                return action_store.finish(
                    client_action_id=client_action_id,
                    status="applied",
                    after_state="ready",
                    after_code="ready",
                    reason_code=None,
                )
            return action
        return action

    if lifecycle_locked:
        return reconcile_if_current()
    with _lifecycle_lock(paths):
        return reconcile_if_current()


def _finalize_memoryos_control_after_stop(
    control: MemoryOSRuntimeControl | None,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> None:
    if control is None:
        return
    process = control.process
    safely_stopped = process is None or process.poll() is not None
    if not safely_stopped and isinstance(control.record, Mapping):
        generation = manifest.get("generation")
        safely_stopped = not (
            isinstance(generation, str)
            and _service_is_live(
                control.record,
                generation=generation,
                xmuse_root=paths.xmuse_root,
                deps=deps,
            )
        )
    control.next_retry_monotonic = None
    control.next_retry_at = None
    control.retry_state = None
    control.retry_code = None
    if safely_stopped:
        control.process = None
        control.record = None
    _write_memoryos_control_status(
        control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        state="stopped" if safely_stopped else "degraded",
        code=("memoryos_stopped" if safely_stopped else "memoryos_process_identity_unavailable"),
    )


def _spawn_frontend(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    node: str,
    generation: str,
    token: str,
) -> tuple[ManagedProcess, ProcessSpec]:
    log_path = paths.xmuse_root / "logs" / "workroom-frontend.log"
    environment = _child_environment(
        deps, paths, generation=generation, token=token, service="frontend"
    )
    environment.update(
        {
            "HOSTNAME": FRONTEND_HOST,
            "PORT": str(FRONTEND_PORT),
            "NODE_ENV": "production",
            "XMUSE_CHAT_API_BASE_URL": (f"http://{CHAT_API_HOST}:{CHAT_API_PORT}/api/chat"),
        }
    )
    spec = ProcessSpec(
        service="frontend",
        command=(node, str(paths.standalone_server)),
        cwd=paths.standalone_dir,
        env=environment,
        log_path=log_path,
    )
    return deps.spawn(spec), spec


def _record_matches_live_process(
    record: Mapping[str, Any],
    *,
    generation: str,
    xmuse_root: Path,
    deps: WorkroomDependencies,
) -> bool:
    return _service_is_live(
        record,
        generation=generation,
        xmuse_root=xmuse_root,
        deps=deps,
    )


def _stop_service_record(
    record: Mapping[str, Any],
    *,
    generation: str,
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    timeout_s: float,
) -> bool:
    return stop_service_record(
        record,
        generation=generation,
        xmuse_root=paths.xmuse_root,
        inspector=deps.inspect_process,
        signal_group=deps.signal_group,
        monotonic=deps.monotonic,
        sleep=deps.sleep,
        timeout_s=timeout_s,
    )


def _stop_manifest_services(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    timeout_s: float,
) -> list[str]:
    generation = manifest.get("generation")
    services = manifest.get("services")
    if not isinstance(generation, str) or not isinstance(services, dict):
        return []
    stopped: list[str] = []
    for name in ("frontend", "chat_api"):
        record = services.get(name)
        if not isinstance(record, dict):
            continue
        if not _stop_service_record(
            record,
            generation=generation,
            paths=paths,
            deps=deps,
            timeout_s=timeout_s,
        ):
            raise WorkroomError("stop_timeout", f"could not stop {name} safely")
        stopped.append(name)
    try:
        deps.stop_runtime(paths.xmuse_root, generation)
    except Exception as exc:
        raise WorkroomError(
            "runtime_stop_failed",
            f"could not stop the generation-scoped peer runtime: {exc}",
        ) from exc
    memory_record = services.get("memoryos")
    if isinstance(memory_record, dict):
        if not _stop_service_record(
            memory_record,
            generation=generation,
            paths=paths,
            deps=deps,
            timeout_s=timeout_s,
        ):
            raise WorkroomError("stop_timeout", "could not stop memoryos safely")
        stopped.append("memoryos")
        with suppress(Exception):
            write_memoryos_status(
                paths.xmuse_root,
                enabled=True,
                state="stopped",
                code="memoryos_stopped",
                generation=generation,
            )
    return stopped


def _stop_spawned_processes(
    processes: Sequence[ManagedProcess],
    deps: WorkroomDependencies,
    *,
    timeout_s: float = 2.0,
) -> None:
    stop_spawned_processes(
        processes,
        signal_group=deps.signal_group,
        monotonic=deps.monotonic,
        sleep=deps.sleep,
        timeout_s=timeout_s,
    )


def _write_if_generation_current(
    paths: WorkroomPaths,
    manifest: dict[str, Any],
    deps: WorkroomDependencies,
    *,
    state: str,
) -> bool:
    with _lifecycle_lock(paths):
        now = deps.now()
        try:
            updated = write_if_generation_current(
                paths.manifest,
                manifest,
                state=state,
                updated_at=now,
                terminal_at=now,
            )
        except ManifestLeafError as exc:
            raise ManifestError(exc.code, str(exc)) from exc
        if updated is None:
            return False
        manifest.clear()
        manifest.update(updated)
        return True


def start_workroom(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    readiness_timeout_s: float,
    stop_timeout_s: float,
    execution_workspace: Path | None = None,
    execution_profile_id: str | None = None,
    memory_enabled: bool = False,
    memoryos_executable: Path | None = None,
    memory_profile: str = "full-local",
) -> int:
    controller = deps.shutdown_controller_factory()
    manifest: dict[str, Any] | None = None
    spawned_processes: list[ManagedProcess] = []
    memory_control: MemoryOSRuntimeControl | None = None
    memory_action_store: RoomMemoryRebuildActionStore | None = None
    controller_installed = False
    try:
        workspace = (
            paths.repo_root
            if execution_workspace is None
            else execution_workspace.expanduser().resolve()
        )
        if not workspace.is_dir():
            raise WorkroomError(
                "execution_workspace_unavailable",
                "the configured execution workspace is not an existing directory",
            )
        if workspace != paths.repo_root and execution_profile_id is None:
            raise WorkroomError(
                "execution_profile_required",
                "a non-default workspace requires an explicit --execution-profile",
            )
        if memory_profile not in {"archive-only", "full-local"}:
            raise WorkroomError(
                "memory_profile_invalid",
                "memory profile must be archive-only or full-local",
            )
        resolved_profile_id = execution_profile_id or DEFAULT_EXECUTION_PROFILE_ID
        try:
            execution_profile = get_execution_gate_profile(resolved_profile_id)
        except RoomExecutionProfileError as exc:
            raise WorkroomError(
                exc.code,
                "the configured execution profile is not a fixed server profile",
            ) from exc
        with _lifecycle_lock(paths):
            existing = _read_manifest(paths.manifest)
            if existing is not None and (
                _manager_is_live(existing, deps)
                or _manifest_has_live_services(existing, paths, deps)
            ):
                raise WorkroomError(
                    "already_running",
                    "a managed Workroom generation is already running",
                )
            if existing is not None:
                previous_generation = existing.get("generation")
                if isinstance(previous_generation, str) and previous_generation:
                    try:
                        deps.stop_runtime(paths.xmuse_root, previous_generation)
                    except Exception as exc:
                        raise WorkroomError(
                            "runtime_reclaim_failed",
                            "could not reclaim the stale Workroom runtime generation",
                        ) from exc
            node = _preflight_start(paths, deps)
            manager_identity = deps.inspect_process(deps.current_pid())
            if manager_identity is None:
                raise WorkroomError(
                    "process_identity_unavailable",
                    "cannot establish the launcher process identity from /proc",
                )
            generation = deps.generation_factory()
            manifest = _base_manifest(
                paths,
                generation=generation,
                manager_identity=manager_identity,
                deps=deps,
                execution_workspace=workspace,
                execution_profile_id=resolved_profile_id,
                memory_enabled=memory_enabled,
            )
            _atomic_write_manifest(paths.manifest, manifest)
            _sync_standalone_assets(paths)

            controller.install()
            controller_installed = True
            token = deps.token_factory()
            memory_key: str | None = None
            memory_url: str | None = None
            if memory_enabled:
                if memoryos_executable is None:
                    raise WorkroomError(
                        "memoryos_executable_required",
                        "--memory requires --memoryos-executable",
                    )
                try:
                    executable = resolve_memoryos_executable(memoryos_executable)
                except (FileNotFoundError, OSError, MemoryOSSupervisorError) as exc:
                    code = getattr(exc, "code", "memoryos_executable_invalid")
                    raise WorkroomError(
                        str(code), "the configured MemoryOS executable is invalid"
                    ) from exc
                memory_key = deps.memory_key_factory()
                memory_url = f"http://{MEMORYOS_HOST}:{MEMORYOS_PORT}"
                memory_control = MemoryOSRuntimeControl(
                    executable=executable,
                    api_key=memory_key,
                    url=memory_url,
                    profile=cast(Literal["archive-only", "full-local"], memory_profile),
                )
                _reconcile_optional_memoryos_runtime(
                    memory_control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    lifecycle_locked=True,
                )
            else:
                _refresh_memoryos_status(
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                    started_at=None,
                )
            chat_api, chat_api_spec = _spawn_chat_api(
                paths,
                deps,
                generation=generation,
                token=token,
                execution_workspace=workspace,
                execution_profile_id=resolved_profile_id,
                memoryos_url=memory_url,
                memoryos_api_key=memory_key,
                memoryos_profile=memory_profile,
            )
            spawned_processes.append(chat_api)
            chat_record = _record_process(
                chat_api,
                service="chat_api",
                generation=generation,
                host=CHAT_API_HOST,
                port=CHAT_API_PORT,
                url=f"http://{CHAT_API_HOST}:{CHAT_API_PORT}/health",
                log_path=chat_api_spec.log_path,
                paths=paths,
                deps=deps,
            )
            manifest["services"]["chat_api"] = chat_record
            _update_manifest(manifest, deps)
            _atomic_write_manifest(paths.manifest, manifest)
            _wait_for_ready(
                service="chat_api",
                url=chat_record["url"],
                process=chat_api,
                timeout_s=readiness_timeout_s,
                deps=deps,
            )
            if memory_control is not None:
                memory_action_store = RoomMemoryRebuildActionStore(paths.xmuse_root / "chat.db")

            frontend, frontend_spec = _spawn_frontend(
                paths,
                deps,
                node=node,
                generation=generation,
                token=token,
            )
            spawned_processes.append(frontend)
            frontend_record = _record_process(
                frontend,
                service="frontend",
                generation=generation,
                host=FRONTEND_HOST,
                port=FRONTEND_PORT,
                url=f"http://{FRONTEND_HOST}:{FRONTEND_PORT}",
                log_path=frontend_spec.log_path,
                paths=paths,
                deps=deps,
            )
            manifest["services"]["frontend"] = frontend_record
            _update_manifest(manifest, deps)
            _atomic_write_manifest(paths.manifest, manifest)
            _wait_for_ready(
                service="frontend",
                url=frontend_record["url"],
                process=frontend,
                timeout_s=readiness_timeout_s,
                deps=deps,
            )
            _update_manifest(manifest, deps, state="ready")
            _atomic_write_manifest(paths.manifest, manifest)

        _emit(
            {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "command": "start",
                "state": "ready",
                "generation": manifest["generation"],
                "frontend_url": f"http://{FRONTEND_HOST}:{FRONTEND_PORT}",
                "chat_api_url": f"http://{CHAT_API_HOST}:{CHAT_API_PORT}",
                "execution_profile": execution_profile.safe_reference(),
                "manifest_path": str(paths.manifest),
            }
        )

        exit_error: WorkroomError | None = None
        services_by_name = {"chat_api": chat_api, "frontend": frontend}
        next_memory_heartbeat = deps.monotonic()
        while not controller.requested():
            for name, process in services_by_name.items():
                return_code = process.poll()
                if return_code is not None:
                    exit_error = WorkroomError(
                        "service_exited",
                        f"{name} exited unexpectedly (code {return_code})",
                    )
                    break
            if exit_error is not None:
                break
            if memory_control is not None and deps.monotonic() >= next_memory_heartbeat:
                rebuild_result: Mapping[str, Any] | None = None
                if memory_action_store is not None:
                    try:
                        rebuild_result = reconcile_memoryos_rebuild_action(
                            memory_control,
                            manifest=manifest,
                            paths=paths,
                            deps=deps,
                            action_store=memory_action_store,
                            stop_timeout_s=stop_timeout_s,
                        )
                    except Exception:
                        _write_memoryos_control_status(
                            memory_control,
                            manifest=manifest,
                            paths=paths,
                            deps=deps,
                            state="degraded",
                            code="memoryos_rebuild_reconcile_failed",
                        )
                        # A ledger read/phase failure must never fall through to
                        # an automatic spawn against potentially partial cache state.
                        rebuild_result = {"status": "requested"}
                if rebuild_result is None or rebuild_result.get("status") != "requested":
                    _reconcile_optional_memoryos_runtime(
                        memory_control,
                        manifest=manifest,
                        paths=paths,
                        deps=deps,
                    )
                now_monotonic = deps.monotonic()
                next_memory_heartbeat = now_monotonic + MEMORYOS_HEARTBEAT_INTERVAL_S
                retry_deadline = memory_control.next_retry_monotonic
                if retry_deadline is not None:
                    next_memory_heartbeat = min(next_memory_heartbeat, retry_deadline)
            deps.sleep(0.2)

        _write_if_generation_current(paths, manifest, deps, state="stopping")
        _stop_manifest_services(manifest, paths, deps, timeout_s=stop_timeout_s)
        with suppress(Exception):
            _finalize_memoryos_control_after_stop(
                memory_control,
                manifest=manifest,
                paths=paths,
                deps=deps,
            )
        final_state = "failed" if exit_error is not None else "stopped"
        if exit_error is not None:
            manifest["failure"] = {"code": exit_error.code, "message": str(exit_error)}
        _write_if_generation_current(paths, manifest, deps, state=final_state)
        _emit(
            {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "command": "start",
                "state": final_state,
                "generation": manifest["generation"],
            }
        )
        return 1 if exit_error is not None else 0
    except Exception as raw_exc:
        failure = (
            raw_exc
            if isinstance(raw_exc, WorkroomError)
            else WorkroomError("start_failed", str(raw_exc) or raw_exc.__class__.__name__)
        )
        if manifest is not None:
            try:
                _stop_manifest_services(manifest, paths, deps, timeout_s=stop_timeout_s)
            except Exception:
                pass
            with suppress(Exception):
                _finalize_memoryos_control_after_stop(
                    memory_control,
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                )
            _stop_spawned_processes(spawned_processes, deps)
            manifest["failure"] = {"code": failure.code, "message": str(failure)}
            try:
                _write_if_generation_current(paths, manifest, deps, state="failed")
            except Exception:
                pass
        _emit(_error_payload("start", failure))
        return 1
    finally:
        if controller_installed:
            controller.restore()


def _service_status(
    name: str,
    record: Mapping[str, Any] | None,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    generation = manifest.get("generation")
    if not isinstance(record, dict) or not isinstance(generation, str):
        return {"service": name, "state": "missing", "live": False, "ready": False}
    live = _service_is_live(
        record,
        generation=generation,
        xmuse_root=paths.xmuse_root,
        deps=deps,
    )
    url = record.get("url")
    ready = live and isinstance(url, str) and deps.http_ready(url)
    return {
        "service": name,
        "state": "ready" if ready else ("running" if live else "stopped"),
        "live": live,
        "ready": ready,
        "pid": record.get("pid"),
        "port": record.get("port"),
        "url": url,
    }


def _read_pid_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _supervised_room_runner_status(
    pid_file: Path,
    status_file: Path,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    payload = _read_pid_payload(pid_file)
    pid = payload.get("pid") if payload is not None else None
    expected_start = payload.get("start_identity") if payload is not None else None
    generation = manifest.get("generation")
    identity = deps.inspect_process(pid) if isinstance(pid, int) else None
    live = (
        identity is not None
        and isinstance(expected_start, str)
        and identity.start_identity == expected_start
        and isinstance(generation, str)
        and identity.environment.get("XMUSE_ROOT") == str(paths.xmuse_root)
        and identity.environment.get("XMUSE_WORKROOM_GENERATION") == generation
        and identity.environment.get("XMUSE_WORKROOM_SERVICE") == "room_runner"
    )
    status = _read_pid_payload(status_file)
    assessment = assess_room_runner_status(
        paths.xmuse_root,
        expected_generation=generation if isinstance(generation, str) else "",
        expected_pid=pid if isinstance(pid, int) else None,
        expected_start_identity=(expected_start if isinstance(expected_start, str) else None),
        now=deps.now(),
        process_identity_reader=(
            lambda candidate_pid: (
                identity.start_identity if identity is not None and candidate_pid == pid else None
            )
        ),
        status_path=status_file,
    )
    receipt_ready = live and assessment.get("ready") is True
    return {
        "service": "room_runner",
        "state": "ready" if receipt_ready else ("running" if live else "stopped"),
        "live": live,
        "ready": receipt_ready,
        "code": assessment.get("code"),
        "host": assessment.get("host"),
        "pid": pid,
        "pid_file": str(pid_file),
        "boot_id": status.get("boot_id") if isinstance(status, dict) else None,
    }


def _supervised_room_mcp_status(
    pid_file: Path,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    payload = _read_pid_payload(pid_file)
    pid = payload.get("pid") if payload is not None else None
    expected_start = payload.get("start_identity") if payload is not None else None
    generation = manifest.get("generation")
    identity = deps.inspect_process(pid) if isinstance(pid, int) else None
    live = (
        identity is not None
        and isinstance(expected_start, str)
        and identity.start_identity == expected_start
        and isinstance(generation, str)
        and identity.environment.get("XMUSE_ROOT") == str(paths.xmuse_root)
        and identity.environment.get("XMUSE_WORKROOM_GENERATION") == generation
        and identity.environment.get("XMUSE_WORKROOM_SERVICE") == "room_mcp"
    )
    port = _pid_command_int_arg(payload, "--port")
    url = f"http://127.0.0.1:{port}/health" if port is not None else None
    health = deps.http_json(url) if live and url is not None else None
    ready = live and room_mcp_health_ready(health)
    return {
        "service": "room_mcp",
        "state": "ready" if ready else ("running" if live else "stopped"),
        "live": live,
        "ready": ready,
        "pid": pid,
        "pid_file": str(pid_file),
        "port": port,
        "url": url,
        "surface": health.get("surface") if isinstance(health, Mapping) else None,
    }


def _pid_command_int_arg(payload: Mapping[str, Any] | None, flag: str) -> int | None:
    command = payload.get("command") if isinstance(payload, Mapping) else None
    if not isinstance(command, list):
        return None
    for index, item in enumerate(command):
        if item == flag and index + 1 < len(command):
            try:
                value = int(command[index + 1])
            except (TypeError, ValueError):
                return None
            return value if 0 < value <= 65535 else None
        if isinstance(item, str) and item.startswith(f"{flag}="):
            try:
                value = int(item.split("=", 1)[1])
            except ValueError:
                return None
            return value if 0 < value <= 65535 else None
    return None


def _memoryos_status(
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    features = manifest.get("features")
    enabled = isinstance(features, Mapping) and features.get("memoryos") is True
    if not enabled:
        return {
            "service": "memoryos",
            "live": False,
            "ready": True,
            **safe_memoryos_status(None),
        }
    services = manifest.get("services")
    record = services.get("memoryos") if isinstance(services, Mapping) else None
    generation = manifest.get("generation")
    live = (
        isinstance(record, Mapping)
        and isinstance(generation, str)
        and _service_is_live(
            record,
            generation=generation,
            xmuse_root=paths.xmuse_root,
            deps=deps,
        )
    )
    ready_probe = live and deps.http_ready(f"http://{MEMORYOS_HOST}:{MEMORYOS_PORT}/health")
    assessed = assess_memoryos_status(
        paths.xmuse_root,
        expected_generation=generation if isinstance(generation, str) else None,
        live=live,
        ready_probe=ready_probe,
        now=deps.now(),
    )
    return {
        "service": "memoryos",
        "live": live,
        "ready": assessed.get("state") == "ready",
        **assessed,
    }


def _refresh_memoryos_status(
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    started_at: str | None,
) -> dict[str, Any]:
    """Refresh safe optional-sidecar evidence; never raise into Workroom supervision."""

    try:
        features = manifest.get("features")
        enabled = isinstance(features, Mapping) and features.get("memoryos") is True
        generation = manifest.get("generation")
        if not enabled:
            return write_memoryos_status(
                paths.xmuse_root,
                enabled=False,
                state="disabled",
                code="memoryos_disabled",
                generation=generation if isinstance(generation, str) else None,
            )
        services = manifest.get("services")
        record = services.get("memoryos") if isinstance(services, Mapping) else None
        live = (
            isinstance(record, Mapping)
            and isinstance(generation, str)
            and _service_is_live(
                record,
                generation=generation,
                xmuse_root=paths.xmuse_root,
                deps=deps,
            )
        )
        healthy = live and deps.http_ready(f"http://{MEMORYOS_HOST}:{MEMORYOS_PORT}/health")
        prior_status = read_memoryos_status(paths.xmuse_root)
        profile = prior_status.get("profile") if isinstance(prior_status, Mapping) else None
        if healthy and profile == "full-local":
            try:
                payload = deps.http_json(f"http://{MEMORYOS_HOST}:{MEMORYOS_PORT}/health")
            except Exception:
                payload = None
            capabilities = payload.get("capabilities") if isinstance(payload, Mapping) else None
            hybrid = capabilities.get("hybrid") if isinstance(capabilities, Mapping) else None
            healthy = (
                isinstance(capabilities, Mapping)
                and isinstance(hybrid, Mapping)
                and hybrid.get("lexical") is True
                and hybrid.get("semantic") is True
                and hybrid.get("rrf") is True
                and capabilities.get("message_ingest") is True
                and capabilities.get("agentic_advisory") is True
                and capabilities.get("paging") is True
            )
        return write_memoryos_status(
            paths.xmuse_root,
            enabled=True,
            state="ready" if healthy else "degraded",
            code="ready"
            if healthy
            else ("memoryos_health_unavailable" if live else "memoryos_process_stopped"),
            generation=generation if isinstance(generation, str) else None,
            pid=(record.get("pid") if isinstance(record, Mapping) else None),
            start_identity=(record.get("start_identity") if isinstance(record, Mapping) else None),
            started_at=started_at,
        )
    except Exception:
        # A receipt failure cannot make the required Room runtime unavailable.
        return {
            "schema_version": MEMORYOS_RUNTIME_SCHEMA,
            "enabled": True,
            "state": "degraded",
            "code": "memoryos_status_write_failed",
        }


def workroom_status(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    emit: bool = True,
) -> tuple[int, dict[str, Any]]:
    try:
        manifest = _read_manifest(paths.manifest)
    except ManifestError as exc:
        payload = _error_payload("status", exc)
        if emit:
            _emit(payload)
        return 2, payload
    if manifest is None:
        payload = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "state": "stopped",
            "manifest_path": str(paths.manifest),
            "services": [],
        }
        if emit:
            _emit(payload)
        return 1, payload
    services = manifest.get("services")
    service_records = services if isinstance(services, dict) else {}
    statuses = [
        _service_status(
            name,
            service_records.get(name),
            manifest=manifest,
            paths=paths,
            deps=deps,
        )
        for name in ("frontend", "chat_api")
    ]
    supervised = manifest.get("supervised")
    supervised_config = supervised if isinstance(supervised, dict) else {}
    configured_runner = supervised_config.get("room_runner_pid_file")
    configured_mcp = supervised_config.get("room_mcp_pid_file")
    configured_status = supervised_config.get("room_runner_status_file")
    runner_pid_file = (
        Path(configured_runner) if isinstance(configured_runner, str) else paths.runner_pid_file
    )
    mcp_pid_file = Path(configured_mcp) if isinstance(configured_mcp, str) else paths.mcp_pid_file
    runner_status_file = (
        Path(configured_status)
        if isinstance(configured_status, str)
        else paths.room_runner_status_file
    )
    statuses.append(
        _supervised_room_runner_status(
            runner_pid_file,
            runner_status_file,
            manifest=manifest,
            paths=paths,
            deps=deps,
        )
    )
    statuses.append(
        _supervised_room_mcp_status(
            mcp_pid_file,
            manifest=manifest,
            paths=paths,
            deps=deps,
        )
    )
    required_statuses = list(statuses)
    statuses.append(_memoryos_status(manifest=manifest, paths=paths, deps=deps))
    exit_code, payload = build_status_projection(
        manifest,
        manager_live=_manager_is_live(manifest, deps),
        required_services=required_statuses,
        optional_services=statuses[len(required_statuses) :],
        sanitize_services=False,
    )
    payload.update(
        {
            "generation": manifest.get("generation"),
            "manifest_path": str(paths.manifest),
        }
    )
    if emit:
        _emit(payload)
    return exit_code, payload


def stop_workroom(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    timeout_s: float,
) -> int:
    if not paths.manifest.is_file():
        _emit(
            {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "command": "stop",
                "state": "stopped",
                "already_stopped": True,
            }
        )
        return 0
    try:
        with _lifecycle_lock(paths):
            manifest = _read_manifest(paths.manifest)
            if manifest is None:
                return 0
            generation = manifest.get("generation")
            manager = manifest.get("manager")
            manager_live = _manager_is_live(manifest, deps)
            _update_manifest(manifest, deps, state="stopping")
            _atomic_write_manifest(paths.manifest, manifest)
        if manager_live and isinstance(manager, dict) and isinstance(manager.get("pid"), int):
            try:
                deps.signal_pid(manager["pid"], signal.SIGTERM)
            except ProcessLookupError:
                manager_live = False
            deadline = deps.monotonic() + timeout_s
            while manager_live and deps.monotonic() < deadline:
                if not _manager_is_live(manifest, deps):
                    manager_live = False
                    break
                deps.sleep(0.05)

        current = _read_manifest(paths.manifest)
        if (
            current is not None
            and current.get("generation") == generation
            and current.get("state") == "stopped"
            and not _manifest_has_live_services(current, paths, deps)
        ):
            _emit(
                {
                    "schema_version": COMMAND_SCHEMA_VERSION,
                    "command": "stop",
                    "state": "stopped",
                    "generation": generation,
                }
            )
            return 0

        stopped_services = _stop_manifest_services(manifest, paths, deps, timeout_s=timeout_s)
        if manager_live and isinstance(manager, dict) and isinstance(manager.get("pid"), int):
            try:
                deps.signal_pid(manager["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        _write_if_generation_current(paths, manifest, deps, state="stopped")
        _emit(
            {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "command": "stop",
                "state": "stopped",
                "generation": generation,
                "stopped_services": stopped_services,
            }
        )
        return 0
    except WorkroomError as exc:
        _emit(_error_payload("stop", exc))
        return 1


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def doctor_workroom(paths: WorkroomPaths, deps: WorkroomDependencies) -> int:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    node = deps.which("node")
    add("node", "ok" if node else "blocker", node or "Node.js was not found on PATH")
    codex = deps.which("codex")
    add(
        "codex",
        "ok" if codex else "blocker",
        codex or "Codex CLI was not found; Room Agents cannot run",
    )
    add(
        "standalone_build",
        "ok" if paths.standalone_server.is_file() else "blocker",
        str(paths.standalone_server),
    )
    add(
        "static_assets",
        "ok" if paths.static_source.is_dir() else "blocker",
        str(paths.static_source),
    )
    writable_parent = _nearest_existing_parent(paths.xmuse_root)
    add(
        "runtime_root",
        "ok" if os.access(writable_parent, os.W_OK) else "blocker",
        str(paths.xmuse_root),
    )
    own_identity = deps.inspect_process(deps.current_pid())
    add(
        "process_identity",
        "ok" if own_identity is not None else "blocker",
        own_identity.start_identity if own_identity is not None else "/proc identity unavailable",
    )
    try:
        manifest = _read_manifest(paths.manifest)
        manifest_valid = True
    except ManifestError:
        manifest = None
        manifest_valid = False
    add(
        "manifest",
        "ok" if manifest_valid else "blocker",
        str(paths.manifest),
    )
    add(
        "data_operation",
        "blocker" if paths.data_operation_journal.exists() else "ok",
        str(paths.data_operation_journal),
    )
    live_owned_ports: set[int] = set()
    if manifest is not None:
        generation = manifest.get("generation")
        services = manifest.get("services")
        if isinstance(generation, str) and isinstance(services, dict):
            for record in services.values():
                if (
                    isinstance(record, dict)
                    and _service_is_live(
                        record,
                        generation=generation,
                        xmuse_root=paths.xmuse_root,
                        deps=deps,
                    )
                    and isinstance(record.get("port"), int)
                ):
                    live_owned_ports.add(record["port"])
    for name, host, port in (
        ("chat_api_port", CHAT_API_HOST, CHAT_API_PORT),
        ("frontend_port", FRONTEND_HOST, FRONTEND_PORT),
    ):
        available = port in live_owned_ports or deps.port_available(host, port)
        add(name, "ok" if available else "blocker", f"{host}:{port}")
    blockers = [check for check in checks if check["status"] == "blocker"]
    warnings = [check for check in checks if check["status"] == "warning"]
    payload = {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "state": "blocked" if blockers else ("degraded" if warnings else "ready"),
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }
    _emit(payload)
    return 1 if blockers else 0
