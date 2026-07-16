"""Read-only runtime evidence and fail-closed guards for offline data mutation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from xmuse.data_contracts import DataError
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_inspection import WorkroomStatusInspection, inspect_workroom_status
from xmuse_core.runtime.processes import discover_xmuse_runtime_processes

REPO_ROOT = Path(__file__).resolve().parents[1]

_AUTHORITY_SERVICES = frozenset(
    {
        "execution_controller",
        "room_runner",
        "room_mcp",
        "runner",
        "mcp",
        "chat_api",
        "dashboard_api",
        "memoryos",
    }
)


class ProcessDiscovery(Protocol):
    def __call__(
        self,
        proc_root: Path = Path("/proc"),
        *,
        xmuse_root: Path | None = None,
        workroom_generation: str | None = None,
    ) -> dict[str, Any]: ...


RuntimeProbe = Callable[[Path], Mapping[str, Any]]


def runtime_probe(
    root: Path,
    *,
    repo_root: Path = REPO_ROOT,
    inspector: Callable[
        [WorkroomPaths, WorkroomDependencies], WorkroomStatusInspection
    ] = inspect_workroom_status,
    discover: ProcessDiscovery = discover_xmuse_runtime_processes,
) -> dict[str, Any]:
    """Read managed, root-scoped, and unscoped authority-process evidence."""

    runtime_root = root.expanduser().resolve()
    paths = WorkroomPaths.resolve(runtime_root, repo_root)
    try:
        managed = inspector(paths, WorkroomDependencies(repo_root=repo_root)).projection
    except WorkroomError:
        managed = {
            "schema_version": "xmuse_workroom_status/v2",
            "state": "error",
            "manager_live": False,
            "services": [],
        }
    return {
        "managed": managed,
        "inventory": discover(xmuse_root=runtime_root),
        # Direct and retired entrypoints can omit XMUSE_ROOT.  A second global
        # read is required so destructive operations fail closed for them.
        "global_inventory": discover(),
    }


def assert_runtime_stopped(
    root: Path,
    *,
    probe: RuntimeProbe = runtime_probe,
) -> None:
    """Reject mutation unless every authority-capable runtime is absent."""

    try:
        evidence = probe(root)
    except (OSError, ValueError, WorkroomError) as exc:
        raise DataError(
            "workroom_state_unverifiable",
            "Workroom runtime state cannot be verified",
        ) from exc
    managed = _mapping(evidence.get("managed"))
    if managed.get("state") == "error":
        raise DataError(
            "workroom_state_unverifiable",
            "Workroom manifest is invalid; runtime state cannot be verified",
        )

    live_services = [service for service in _services(managed) if service.get("live") is True]
    scoped_services = _services(_mapping(evidence.get("inventory")))
    global_services = [
        service
        for service in _services(_mapping(evidence.get("global_inventory")))
        if service.get("service") in _AUTHORITY_SERVICES
    ]
    if managed.get("manager_live") is True or live_services or scoped_services or global_services:
        raise DataError(
            "workroom_running",
            "restore and compact require a fully stopped Workroom",
            pids=_service_pids((*live_services, *scoped_services, *global_services)),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _services(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    services = value.get("services")
    if not isinstance(services, list):
        return []
    return [item for item in services if isinstance(item, Mapping)]


def _service_pids(services: tuple[Mapping[str, Any], ...]) -> list[int]:
    pids: set[int] = set()
    for service in services:
        candidates = service.get("pids")
        if isinstance(candidates, list):
            pids.update(
                pid for pid in candidates if isinstance(pid, int) and not isinstance(pid, bool)
            )
        pid = service.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool):
            pids.add(pid)
    return sorted(pids)


__all__ = ["ProcessDiscovery", "RuntimeProbe", "assert_runtime_stopped", "runtime_probe"]
