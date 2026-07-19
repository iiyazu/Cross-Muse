#!/usr/bin/env python3
"""Compose and supervise the local xmuse Workroom application."""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from xmuse.workroom_contracts import (
    WORKROOM_REPO_ROOT,
    WorkroomDependencies,
    WorkroomError,
    WorkroomPaths,
    workroom_lifecycle_lock,
)
from xmuse.workroom_inspection import inspect_workroom_doctor, inspect_workroom_status
from xmuse.workroom_manifest import ManifestError as ManifestLeafError
from xmuse.workroom_manifest import (
    atomic_write_manifest,
    base_manifest,
    read_manifest,
    update_manifest,
    write_if_generation_current,
)
from xmuse.workroom_memoryos import MemoryOSRuntimeControl
from xmuse.workroom_memoryos_runtime import (
    MEMORYOS_PORT as MEMORYOS_PORT,
)
from xmuse.workroom_memoryos_runtime import (
    MemoryOSRuntimeCoordinator,
    record_memoryos_disabled,
    stop_recorded_memoryos,
)
from xmuse.workroom_memoryos_runtime import (
    write_memoryos_status as write_memoryos_status,
)
from xmuse.workroom_processes import (
    ManagedProcess as ManagedProcess,
)
from xmuse.workroom_processes import (
    ProcessIdentity,
    identity_matches,
    port_available,
    service_is_live,
)
from xmuse.workroom_processes import (
    ProcessSpec as ProcessSpec,
)
from xmuse.workroom_services import (
    CHAT_API_HOST,
    CHAT_API_PORT,
    FRONTEND_HOST,
    FRONTEND_PORT,
    RequiredServiceRuntime,
    WorkroomServicesCoordinator,
)
from xmuse_core.chat.room_execution_profiles import (
    RoomExecutionProfileError,
    get_execution_gate_profile,
)
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.runtime.root_contract import (
    DATA_OPERATION_JOURNAL_NAME as DATA_OPERATION_JOURNAL_NAME,
)
from xmuse_core.runtime.root_contract import WORKROOM_LIFECYCLE_LOCK_NAME, WORKROOM_MANIFEST_NAME

SCHEMA_VERSION = "xmuse_workroom_runtime/v1"
STATUS_SCHEMA_VERSION = "xmuse_workroom_status/v2"
DOCTOR_SCHEMA_VERSION = "xmuse_workroom_doctor/v1"
COMMAND_SCHEMA_VERSION = "xmuse_workroom_command/v1"
MEMORYOS_HEARTBEAT_INTERVAL_S = 5.0
REPO_ROOT = WORKROOM_REPO_ROOT
DEFAULT_EXECUTION_PROFILE_ID = "xmuse-monorepo/v2"
DEFAULT_XMUSE_ROOT = default_xmuse_root(REPO_ROOT / "xmuse")
MANIFEST_NAME = WORKROOM_MANIFEST_NAME
LOCK_NAME = WORKROOM_LIFECYCLE_LOCK_NAME


class ManifestError(WorkroomError):
    """Stable public wrapper around manifest leaf errors."""


def _package_version() -> str:
    try:
        return importlib.metadata.version("xmuse")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


_port_available = port_available
_lifecycle_lock = workroom_lifecycle_lock


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return read_manifest(path, schema_version=SCHEMA_VERSION)
    except ManifestLeafError as exc:
        raise ManifestError(exc.code, str(exc)) from exc


def _atomic_write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_manifest(path, payload)


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), sort_keys=True))


def _error_payload(command: str, exc: WorkroomError) -> dict[str, Any]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "command": command,
        "state": "error",
        "error": {"code": exc.code, "message": str(exc)},
    }


def _identity_matches(
    record: Mapping[str, Any],
    inspector: Callable[[int], ProcessIdentity | None],
    *,
    require_scope: bool,
) -> bool:
    del require_scope
    return identity_matches(record, inspector)


def _manager_is_live(manifest: Mapping[str, Any], deps: WorkroomDependencies) -> bool:
    manager = manifest.get("manager")
    return isinstance(manager, Mapping) and _identity_matches(
        manager,
        deps.inspect_process,
        require_scope=False,
    )


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


def _manifest_has_live_services(
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> bool:
    generation = manifest.get("generation")
    services = manifest.get("services")
    if not isinstance(generation, str) or not isinstance(services, Mapping):
        return False
    return any(
        isinstance(record, Mapping)
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


def reconcile_memoryos_runtime(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    lifecycle_locked: bool = False,
) -> dict[str, Any]:
    """Compatibility entrypoint delegated to the MemoryOS coordinator."""

    return MemoryOSRuntimeCoordinator(
        control=control,
        manifest=manifest,
        paths=paths,
        deps=deps,
    ).reconcile(lifecycle_locked=lifecycle_locked)


def _reconcile_optional_memoryos_runtime(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    lifecycle_locked: bool = False,
) -> dict[str, Any]:
    return MemoryOSRuntimeCoordinator(
        control=control,
        manifest=manifest,
        paths=paths,
        deps=deps,
    ).reconcile_optional(lifecycle_locked=lifecycle_locked)


def reconcile_memoryos_rebuild_action(
    control: MemoryOSRuntimeControl,
    *,
    manifest: dict[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    action_store: Any,
    lifecycle_locked: bool = False,
    stop_timeout_s: float = 10.0,
) -> dict[str, Any] | None:
    """Compatibility entrypoint delegated to the guarded rebuild coordinator."""

    return MemoryOSRuntimeCoordinator(
        control=control,
        manifest=manifest,
        paths=paths,
        deps=deps,
        _rebuild_store=action_store,
    ).reconcile_rebuild_action(
        lifecycle_locked=lifecycle_locked,
        stop_timeout_s=stop_timeout_s,
    )


def _validate_start_configuration(
    paths: WorkroomPaths,
    *,
    execution_workspace: Path | None,
    execution_profile_id: str | None,
    memory_profile: str,
) -> tuple[Path, str, Any]:
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
    return workspace, resolved_profile_id, execution_profile


def _stop_generation_runtime(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    generation: str,
) -> None:
    try:
        deps.stop_runtime(paths.xmuse_root, generation)
    except Exception as exc:
        raise WorkroomError(
            "runtime_stop_failed",
            f"could not stop the generation-scoped peer runtime: {exc}",
        ) from exc


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
    memory_disabled_code: str | None = None,
) -> int:
    controller = deps.shutdown_controller_factory()
    services = WorkroomServicesCoordinator(paths, deps)
    manifest: dict[str, Any] | None = None
    service_runtime: RequiredServiceRuntime | None = None
    memory_runtime: MemoryOSRuntimeCoordinator | None = None
    controller_installed = False
    try:
        workspace, resolved_profile_id, execution_profile = _validate_start_configuration(
            paths,
            execution_workspace=execution_workspace,
            execution_profile_id=execution_profile_id,
            memory_profile=memory_profile,
        )
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
                    _stop_generation_runtime(paths, deps, previous_generation)

            node = services.preflight()
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
            services.sync_assets()
            controller.install()
            controller_installed = True

            memory_binding = None
            if memory_enabled:
                if memoryos_executable is None:
                    raise WorkroomError(
                        "memoryos_executable_required",
                        "--memory requires --memoryos-executable",
                    )
                memory_runtime = MemoryOSRuntimeCoordinator.create(
                    executable=memoryos_executable,
                    profile=memory_profile,
                    api_key=deps.memory_key_factory(),
                    manifest=manifest,
                    paths=paths,
                    deps=deps,
                )
                memory_runtime.reconcile_optional(lifecycle_locked=True)
                memory_binding = memory_runtime.chat_api_binding()
            else:
                record_memoryos_disabled(manifest, paths, deps, code=memory_disabled_code)

            def record_service(name: str, record: dict[str, Any]) -> None:
                assert manifest is not None
                service_records = manifest.setdefault("services", {})
                if not isinstance(service_records, dict):
                    raise WorkroomError(
                        "invalid_manifest",
                        "Workroom services manifest is invalid",
                    )
                service_records[name] = record
                _update_manifest(manifest, deps)
                _atomic_write_manifest(paths.manifest, manifest)

            service_runtime = services.start(
                node=node,
                generation=generation,
                operator_token=deps.token_factory(),
                execution_workspace=workspace,
                execution_profile_id=resolved_profile_id,
                readiness_timeout_s=readiness_timeout_s,
                record_service=record_service,
                memoryos_url=memory_binding.url if memory_binding is not None else None,
                memoryos_api_key=(memory_binding.api_key if memory_binding is not None else None),
                memoryos_profile=memory_profile,
                cleanup_timeout_s=stop_timeout_s,
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

        assert service_runtime is not None
        exit_error: WorkroomError | None = None
        next_memory_heartbeat = deps.monotonic()
        while not controller.requested():
            for name, process in service_runtime.processes_by_name().items():
                return_code = process.poll()
                if return_code is not None:
                    exit_error = WorkroomError(
                        "service_exited",
                        f"{name} exited unexpectedly (code {return_code})",
                    )
                    break
            if exit_error is not None:
                break
            if memory_runtime is not None and deps.monotonic() >= next_memory_heartbeat:
                rebuild_result: Mapping[str, Any] | None
                try:
                    rebuild_result = memory_runtime.reconcile_rebuild_action(
                        stop_timeout_s=stop_timeout_s,
                    )
                except Exception:
                    memory_runtime.record_status(
                        state="degraded",
                        code="memoryos_rebuild_reconcile_failed",
                    )
                    rebuild_result = {"status": "requested"}
                if rebuild_result is None or rebuild_result.get("status") != "requested":
                    memory_runtime.reconcile_optional()
                next_memory_heartbeat = deps.monotonic() + MEMORYOS_HEARTBEAT_INTERVAL_S
                retry_deadline = memory_runtime.control.next_retry_monotonic
                if retry_deadline is not None:
                    next_memory_heartbeat = min(next_memory_heartbeat, retry_deadline)
            deps.sleep(0.2)

        _write_if_generation_current(paths, manifest, deps, state="stopping")
        services.stop(manifest, timeout_s=stop_timeout_s)
        _stop_generation_runtime(paths, deps, str(manifest["generation"]))
        if memory_runtime is not None:
            memory_stop = stop_recorded_memoryos(
                manifest,
                paths,
                deps,
                timeout_s=stop_timeout_s,
            )
            if not bool(memory_stop.get("stopped")):
                code = str(memory_stop.get("code") or "memoryos_stop_failed")
                raise WorkroomError(code, "could not stop MemoryOS safely")
            memory_runtime.finalize_after_stop()
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
            with suppress(Exception):
                services.stop(manifest, timeout_s=stop_timeout_s)
            cleanup_generation = manifest.get("generation")
            if isinstance(cleanup_generation, str):
                with suppress(Exception):
                    _stop_generation_runtime(paths, deps, cleanup_generation)
            if memory_runtime is not None:
                with suppress(Exception):
                    stop_recorded_memoryos(
                        manifest,
                        paths,
                        deps,
                        timeout_s=stop_timeout_s,
                    )
                with suppress(Exception):
                    memory_runtime.finalize_after_stop()
            manifest["failure"] = {"code": failure.code, "message": str(failure)}
            with suppress(Exception):
                _write_if_generation_current(paths, manifest, deps, state="failed")
        _emit(_error_payload("start", failure))
        return 1
    finally:
        if controller_installed:
            controller.restore()


def workroom_status(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
    *,
    emit: bool = True,
) -> tuple[int, dict[str, Any]]:
    try:
        inspection = inspect_workroom_status(paths, deps)
    except WorkroomError as exc:
        payload = _error_payload("status", exc)
        if emit:
            _emit(payload)
        return 2, payload
    if emit:
        _emit(inspection.projection)
    return inspection.exit_code, inspection.projection


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
    services = WorkroomServicesCoordinator(paths, deps)
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

        if manager_live and isinstance(manager, Mapping):
            manager_live = not services.stop_manager(manager, timeout_s=timeout_s)

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

        stopped_services = services.stop(manifest, timeout_s=timeout_s)
        if not isinstance(generation, str):
            raise WorkroomError("invalid_manifest", "Workroom generation is invalid")
        _stop_generation_runtime(paths, deps, generation)
        memory_result = stop_recorded_memoryos(manifest, paths, deps, timeout_s=timeout_s)
        if not bool(memory_result.get("stopped")):
            code = str(memory_result.get("code") or "memoryos_stop_failed")
            raise WorkroomError(code, "could not stop MemoryOS safely")
        if memory_result.get("code") == "memoryos_stopped":
            stopped_services.append("memoryos")
        if manager_live:
            raise WorkroomError("stop_timeout", "could not stop the Workroom manager safely")
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


def doctor_workroom(paths: WorkroomPaths, deps: WorkroomDependencies) -> int:
    exit_code, payload = inspect_workroom_doctor(paths, deps)
    _emit(payload)
    return exit_code
