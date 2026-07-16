"""Read-only Workroom status and prerequisite evidence coordinator.

This module reads already-published process and runtime evidence.  It owns no
lifecycle lock, process signal, child spawn, manifest write, or recovery loop.
The returned projections deliberately omit process identities, generations,
local paths, URLs, and credentials.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_manifest import ManifestError as ManifestLeafError
from xmuse.workroom_manifest import read_manifest
from xmuse.workroom_processes import identity_matches, service_is_live
from xmuse.workroom_status import STATUS_SCHEMA_VERSION, build_status_projection
from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_HOST,
    MEMORYOS_PORT,
    assess_memoryos_status,
    safe_memoryos_status,
)
from xmuse_core.chat.room_runtime import assess_room_runner_status
from xmuse_core.chat.room_runtime_supervisor import room_mcp_health_ready

DOCTOR_SCHEMA_VERSION = "xmuse_workroom_doctor/v1"
MANIFEST_SCHEMA_VERSION = "xmuse_workroom_runtime/v1"
CHAT_API_HOST = "127.0.0.1"
CHAT_API_PORT = 8201
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 3000
_MAX_RECEIPT_BYTES = 64 * 1024


@dataclass(frozen=True)
class WorkroomStatusInspection:
    """Safe status projection plus non-serialized CLI compatibility evidence."""

    exit_code: int
    projection: dict[str, Any]
    manifest_generation: str | None = None


def inspect_workroom_status(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> WorkroomStatusInspection:
    """Read and assemble the safe ``xmuse_workroom_status/v2`` projection."""

    manifest = _read_manifest(paths.manifest)
    if manifest is None:
        return WorkroomStatusInspection(
            exit_code=1,
            projection={
                "schema_version": STATUS_SCHEMA_VERSION,
                "state": "stopped",
                "services": [],
            },
        )

    services = manifest.get("services")
    service_records = services if isinstance(services, Mapping) else {}
    required_statuses = [
        _service_status(
            name,
            service_records.get(name),
            manifest=manifest,
            paths=paths,
            deps=deps,
        )
        for name in ("frontend", "chat_api")
    ]

    runner_pid_file, mcp_pid_file, runner_status_file = _supervised_paths(manifest, paths)
    required_statuses.extend(
        (
            _room_runner_status(
                runner_pid_file,
                runner_status_file,
                manifest=manifest,
                paths=paths,
                deps=deps,
            ),
            _room_mcp_status(
                mcp_pid_file,
                manifest=manifest,
                paths=paths,
                deps=deps,
            ),
        )
    )
    memory_status = _memoryos_status(manifest=manifest, paths=paths, deps=deps)
    exit_code, projection = build_status_projection(
        manifest,
        manager_live=_manager_is_live(manifest, deps),
        required_services=required_statuses,
        optional_services=(memory_status,),
        # Every status above is already an explicit allow-list.  Keeping this
        # false preserves safe MemoryOS recovery/profile fields that the generic
        # service projector does not know about.
        sanitize_services=False,
    )
    generation = manifest.get("generation")
    return WorkroomStatusInspection(
        exit_code=exit_code,
        projection=projection,
        manifest_generation=generation if isinstance(generation, str) else None,
    )


def inspect_workroom_doctor(
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> tuple[int, dict[str, Any]]:
    """Return safe, read-only Workroom prerequisite checks."""

    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    node = deps.which("node")
    add("node", "ok" if node else "blocker", "available" if node else "not_found")
    codex = deps.which("codex")
    add("codex", "ok" if codex else "blocker", "available" if codex else "not_found")
    add(
        "standalone_build",
        "ok" if paths.standalone_server.is_file() else "blocker",
        "available" if paths.standalone_server.is_file() else "missing",
    )
    add(
        "static_assets",
        "ok" if paths.static_source.is_dir() else "blocker",
        "available" if paths.static_source.is_dir() else "missing",
    )
    writable_parent = _nearest_existing_parent(paths.xmuse_root)
    root_writable = os.access(writable_parent, os.W_OK)
    add(
        "runtime_root",
        "ok" if root_writable else "blocker",
        "writable" if root_writable else "not_writable",
    )
    own_identity = deps.inspect_process(deps.current_pid())
    add(
        "process_identity",
        "ok" if own_identity is not None else "blocker",
        "available" if own_identity is not None else "unavailable",
    )

    try:
        manifest = _read_manifest(paths.manifest)
        manifest_valid = True
    except WorkroomError:
        manifest = None
        manifest_valid = False
    add("manifest", "ok" if manifest_valid else "blocker", "valid" if manifest_valid else "invalid")
    journal_active = paths.data_operation_journal.exists()
    add(
        "data_operation",
        "blocker" if journal_active else "ok",
        "active" if journal_active else "clear",
    )

    live_owned_ports = _live_owned_ports(manifest, paths=paths, deps=deps)
    for name, host, port in (
        ("chat_api_port", CHAT_API_HOST, CHAT_API_PORT),
        ("frontend_port", FRONTEND_HOST, FRONTEND_PORT),
    ):
        available = port in live_owned_ports or deps.port_available(host, port)
        add(name, "ok" if available else "blocker", f"{host}:{port}")

    blockers = [check for check in checks if check["status"] == "blocker"]
    warnings = [check for check in checks if check["status"] == "warning"]
    projection = {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "state": "blocked" if blockers else ("degraded" if warnings else "ready"),
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }
    return (1 if blockers else 0), projection


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return read_manifest(path, schema_version=MANIFEST_SCHEMA_VERSION)
    except ManifestLeafError as exc:
        raise WorkroomError(exc.code, str(exc)) from exc


def _manager_is_live(manifest: Mapping[str, Any], deps: WorkroomDependencies) -> bool:
    manager = manifest.get("manager")
    return isinstance(manager, Mapping) and identity_matches(manager, deps.inspect_process)


def _service_status(
    name: str,
    record: object,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    generation = manifest.get("generation")
    if not isinstance(record, Mapping) or not isinstance(generation, str):
        return {"service": name, "state": "missing", "live": False, "ready": False}
    live = service_is_live(
        record,
        generation=generation,
        xmuse_root=paths.xmuse_root,
        inspector=deps.inspect_process,
    )
    url = record.get("url")
    ready = live and isinstance(url, str) and deps.http_ready(url)
    return {
        "service": name,
        "state": "ready" if ready else ("running" if live else "stopped"),
        "live": live,
        "ready": ready,
    }


def _supervised_paths(manifest: Mapping[str, Any], paths: WorkroomPaths) -> tuple[Path, Path, Path]:
    supervised = manifest.get("supervised")
    configured = supervised if isinstance(supervised, Mapping) else {}
    runner = configured.get("room_runner_pid_file")
    mcp = configured.get("room_mcp_pid_file")
    status = configured.get("room_runner_status_file")
    return (
        Path(runner) if isinstance(runner, str) else paths.runner_pid_file,
        Path(mcp) if isinstance(mcp, str) else paths.mcp_pid_file,
        Path(status) if isinstance(status, str) else paths.room_runner_status_file,
    )


def _read_receipt(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_RECEIPT_BYTES:
            return None
        payload = json.loads(raw)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _room_runner_status(
    pid_file: Path,
    status_file: Path,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    payload = _read_receipt(pid_file)
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
    assessment = assess_room_runner_status(
        paths.xmuse_root,
        expected_generation=generation if isinstance(generation, str) else "",
        expected_pid=pid if isinstance(pid, int) else None,
        expected_start_identity=expected_start if isinstance(expected_start, str) else None,
        now=deps.now(),
        process_identity_reader=(
            lambda candidate_pid: (
                identity.start_identity if identity is not None and candidate_pid == pid else None
            )
        ),
        status_path=status_file,
    )
    ready = live and assessment.get("ready") is True
    host = assessment.get("host")
    safe_host = (
        {
            key: host[key]
            for key in (
                "state",
                "code",
                "active_delivery_count",
                "retained_cleanup_count",
            )
            if key in host
        }
        if isinstance(host, Mapping)
        else None
    )
    result: dict[str, Any] = {
        "service": "room_runner",
        "state": "ready" if ready else ("running" if live else "stopped"),
        "live": live,
        "ready": ready,
    }
    code = assessment.get("code")
    if isinstance(code, str):
        result["code"] = code
    if safe_host is not None:
        result["host"] = safe_host
    return result


def _room_mcp_status(
    pid_file: Path,
    *,
    manifest: Mapping[str, Any],
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> dict[str, Any]:
    payload = _read_receipt(pid_file)
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
    port = _command_int_arg(payload, "--port")
    url = f"http://127.0.0.1:{port}/health" if port is not None else None
    health = deps.http_json(url) if live and url is not None else None
    ready = live and room_mcp_health_ready(health)
    result: dict[str, Any] = {
        "service": "room_mcp",
        "state": "ready" if ready else ("running" if live else "stopped"),
        "live": live,
        "ready": ready,
    }
    surface = health.get("surface") if isinstance(health, Mapping) else None
    if isinstance(surface, str):
        result["surface"] = surface
    return result


def _command_int_arg(payload: Mapping[str, Any] | None, flag: str) -> int | None:
    command = payload.get("command") if isinstance(payload, Mapping) else None
    if not isinstance(command, list):
        return None
    for index, item in enumerate(command):
        candidate: object | None = None
        if item == flag and index + 1 < len(command):
            candidate = command[index + 1]
        elif isinstance(item, str) and item.startswith(f"{flag}="):
            candidate = item.split("=", 1)[1]
        if candidate is None:
            continue
        if isinstance(candidate, bool) or not isinstance(candidate, (int, str)):
            return None
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            return None
        return value if 0 < value <= 65_535 else None
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
        assessed = safe_memoryos_status(None)
        return {"service": "memoryos", "live": False, "ready": True, **assessed}

    services = manifest.get("services")
    record = services.get("memoryos") if isinstance(services, Mapping) else None
    generation = manifest.get("generation")
    live = (
        isinstance(record, Mapping)
        and isinstance(generation, str)
        and service_is_live(
            record,
            generation=generation,
            xmuse_root=paths.xmuse_root,
            inspector=deps.inspect_process,
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
    allowed = {
        key: assessed[key]
        for key in (
            "enabled",
            "state",
            "code",
            "heartbeat_at",
            "started_at",
            "consecutive_restart_count",
            "next_retry_at",
            "last_healthy_at",
            "profile",
        )
        if key in assessed
    }
    return {
        "service": "memoryos",
        "live": live,
        "ready": assessed.get("state") == "ready",
        **allowed,
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _live_owned_ports(
    manifest: Mapping[str, Any] | None,
    *,
    paths: WorkroomPaths,
    deps: WorkroomDependencies,
) -> set[int]:
    if manifest is None:
        return set()
    generation = manifest.get("generation")
    services = manifest.get("services")
    if not isinstance(generation, str) or not isinstance(services, Mapping):
        return set()
    ports: set[int] = set()
    for record in services.values():
        if (
            isinstance(record, Mapping)
            and service_is_live(
                record,
                generation=generation,
                xmuse_root=paths.xmuse_root,
                inspector=deps.inspect_process,
            )
            and isinstance(record.get("port"), int)
        ):
            ports.add(record["port"])
    return ports


__all__ = [
    "DOCTOR_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "WorkroomStatusInspection",
    "inspect_workroom_doctor",
    "inspect_workroom_status",
]
