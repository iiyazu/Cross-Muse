"""Room process discovery plus conservative detection of retired authority processes.

Old executable names remain recognizable only so offline data operations fail closed while
an earlier installed generation may still hold the same runtime root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROCESS_SERVICE_ORDER = (
    "execution_controller",
    "room_runner",
    "room_mcp",
    "memoryos",
    "runner",
    "mcp",
    "dashboard_api",
    "chat_api",
    "codex_app_server",
    "codex_worker",
)
PROCESS_SERVICE_METADATA: dict[str, dict[str, Any]] = {
    "execution_controller": {
        "label": "room_execution_controller",
        "category": "privileged_worker",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse exact-patch execution controller",
    },
    "room_runner": {
        "label": "room_runner",
        "category": "room_runtime",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse Room runner",
    },
    "room_mcp": {
        "label": "room_mcp_server",
        "category": "room_runtime",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "subject": "xmuse Room MCP server",
    },
    "memoryos": {
        "label": "memoryos_archive_sidecar",
        "category": "derived_index",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "subject": "xmuse MemoryOS archive sidecar",
    },
    "runner": {
        "label": "platform_runner",
        "category": "runtime_core",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "missing_severity": "degraded",
        "subject": "xmuse platform runner",
    },
    "mcp": {
        "label": "mcp_server",
        "category": "runtime_core",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "missing_severity": "degraded",
        "subject": "xmuse MCP server",
    },
    "dashboard_api": {
        "label": "dashboard_api",
        "category": "read_api",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "subject": "xmuse dashboard API",
    },
    "chat_api": {
        "label": "chat_api",
        "category": "read_api",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "subject": "xmuse chat API",
    },
    "codex_app_server": {
        "label": "codex_app_server",
        "category": "session_transport",
        "writer_capable": False,
        "subject": "Codex app-server",
    },
    "codex_worker": {
        "label": "codex_worker",
        "category": "worker",
        "writer_capable": False,
        "subject": "repo-local Codex worker",
    },
}


def build_process_inventory(
    *,
    runner_pids: list[int] | None = None,
    mcp_pids: list[int] | None = None,
    services: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """Build compact process inventory rows and evidence from known PID groups."""
    service_pids: dict[str, set[int]] = {}
    for service_name, pids in (services or {}).items():
        if service_name not in PROCESS_SERVICE_METADATA:
            raise ValueError(f"unknown process service: {service_name}")
        service_pids[service_name] = _pid_set(pids)
    if runner_pids is not None:
        service_pids["runner"] = _pid_set(runner_pids)
    if mcp_pids is not None:
        service_pids["mcp"] = _pid_set(mcp_pids)
    return _finalize_process_inventory(service_pids)


def discover_xmuse_runtime_processes(
    proc_root: Path = Path("/proc"),
    *,
    xmuse_root: Path | None = None,
    workroom_generation: str | None = None,
) -> dict[str, Any]:
    """Discover current Room processes and retired names relevant to data safety."""
    service_pids: dict[str, set[int]] = {}
    ppid_by_pid: dict[int, int] = {}
    if not proc_root.exists():
        return build_process_inventory(runner_pids=[], mcp_pids=[])

    current_pid = os.getpid()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == current_pid:
            continue
        args = _read_proc_cmdline(entry / "cmdline")
        if not args:
            continue
        service_name = _classify_runtime_process(args)
        if service_name is None:
            continue
        environ = _read_proc_environ(entry / "environ")
        if not _matches_xmuse_root(entry, args, environ, xmuse_root):
            continue
        if (
            workroom_generation is not None
            and environ.get("XMUSE_WORKROOM_GENERATION") != workroom_generation
        ):
            continue
        ppid_by_pid[pid] = _read_proc_ppid(entry / "status")
        service_pids.setdefault(service_name, set()).add(pid)

    deduped_service_pids = {
        service_name: _dedupe_wrapper_processes(pids, ppid_by_pid)
        for service_name, pids in service_pids.items()
    }
    return _finalize_process_inventory(deduped_service_pids)


def list_live_pids(proc_root: Path = Path("/proc")) -> set[int]:
    if not proc_root.exists():
        return set()
    pids: set[int] = set()
    for entry in proc_root.iterdir():
        if entry.name.isdigit():
            pids.add(int(entry.name))
    return pids


def discover_xmuse_processes(
    proc_root: Path = Path("/proc"),
    *,
    xmuse_root: Path | None = None,
    workroom_generation: str | None = None,
) -> tuple[list[int], list[int]]:
    inventory = discover_xmuse_runtime_processes(
        proc_root,
        xmuse_root=xmuse_root,
        workroom_generation=workroom_generation,
    )
    return list(inventory["runner_pids"]), list(inventory["mcp_pids"])


def process_warnings(
    *,
    runner_count: int,
    mcp_count: int,
    process_inventory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if process_inventory is not None:
        observed_warnings = process_inventory.get("warnings")
        if isinstance(observed_warnings, list):
            return [warning for warning in observed_warnings if isinstance(warning, dict)]
    warnings: list[dict[str, Any]] = []
    if runner_count == 0:
        warnings.append(
            {
                "code": "missing_runner_process",
                "severity": "degraded",
                "message": "no xmuse platform runner process is running",
                "count": runner_count,
            }
        )
    elif runner_count > 1:
        warnings.append(
            {
                "code": "duplicate_runner_processes",
                "severity": "hard",
                "message": "multiple xmuse platform runner processes are running",
                "count": runner_count,
            }
        )
    if mcp_count == 0:
        warnings.append(
            {
                "code": "missing_mcp_process",
                "severity": "degraded",
                "message": "no xmuse MCP server process is running",
                "count": mcp_count,
            }
        )
    elif mcp_count > 1:
        warnings.append(
            {
                "code": "duplicate_mcp_processes",
                "severity": "degraded",
                "message": "multiple xmuse MCP server processes are running",
                "count": mcp_count,
            }
        )
    return warnings


def _read_proc_cmdline(path: Path) -> list[str]:
    try:
        content = path.read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in content.split(b"\0") if part]


def _read_proc_environ(path: Path) -> dict[str, str]:
    try:
        content = path.read_bytes()
    except OSError:
        return {}
    environ: dict[str, str] = {}
    for part in content.split(b"\0"):
        if not part or b"=" not in part:
            continue
        key, value = part.split(b"=", 1)
        environ[key.decode("utf-8", errors="replace")] = value.decode(
            "utf-8",
            errors="replace",
        )
    return environ


def _read_proc_ppid(path: Path) -> int:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _dedupe_wrapper_processes(
    pids: set[int],
    ppid_by_pid: dict[int, int],
) -> set[int]:
    parent_pids = {ppid_by_pid.get(pid, 0) for pid in pids}
    return {pid for pid in pids if pid not in parent_pids}


def _classify_runtime_process(args: list[str]) -> str | None:
    if _is_execution_controller_cmd(args):
        return "execution_controller"
    if _is_room_runner_cmd(args):
        return "room_runner"
    if _is_platform_runner_cmd(args):
        return "runner"
    if _is_room_mcp_server_cmd(args):
        return "room_mcp"
    if _is_memoryos_server_cmd(args):
        return "memoryos"
    if _is_mcp_server_cmd(args):
        return "room_mcp" if _command_arg_value(args, "--surface") == "room" else "mcp"
    if _matches_script_args(args, "dashboard_api.py"):
        return "dashboard_api"
    if _is_chat_api_cmd(args):
        return "chat_api"
    if _is_codex_app_server_cmd(args):
        return "codex_app_server"
    if _is_codex_worker_cmd(args):
        return "codex_worker"
    return None


def _matches_xmuse_root(
    proc_entry: Path,
    args: list[str],
    environ: dict[str, str],
    xmuse_root: Path | None,
) -> bool:
    if xmuse_root is None:
        return True
    target = _normalized_path_text(xmuse_root)
    markers = _xmuse_root_markers(args, environ)
    if not markers:
        cwd = _read_proc_cwd(proc_entry / "cwd")
        return cwd is not None and _normalized_path_text(cwd) == target
    return any(_normalized_path_text(marker) == target for marker in markers)


def _read_proc_cwd(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        return None


def _xmuse_root_markers(args: list[str], environ: dict[str, str]) -> list[str | Path]:
    markers: list[str | Path] = []
    env_root = environ.get("XMUSE_ROOT")
    if env_root:
        markers.append(env_root)
    for index, arg in enumerate(args):
        if arg == "--xmuse-root" and index + 1 < len(args):
            markers.append(args[index + 1])
        elif arg.startswith("--xmuse-root="):
            markers.append(arg.split("=", 1)[1])
    return markers


def _normalized_path_text(value: str | Path) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(value)


def _is_platform_runner_cmd(args: list[str]) -> bool:
    if "--health-once" in args:
        return False
    return any(_matches_script_arg(arg, "platform_runner.py") for arg in args) or any(
        Path(arg).name in {"xmuse-platform-runner", "xmuse-compat-platform-runner"} for arg in args
    )


def _is_room_runner_cmd(args: list[str]) -> bool:
    return (
        any(_matches_script_arg(arg, "room_runner.py") for arg in args)
        or any(Path(arg).name == "xmuse-room-runner" for arg in args)
        or ("-m" in args and "xmuse.room_runner" in args)
    )


def _is_execution_controller_cmd(args: list[str]) -> bool:
    return (
        any(_matches_script_arg(arg, "room_execution_controller.py") for arg in args)
        or any(Path(arg).name == "xmuse-room-execution-controller" for arg in args)
        or ("-m" in args and "xmuse.room_execution_controller" in args)
    )


def _command_arg_value(args: list[str], flag: str) -> str | None:
    for index, item in enumerate(args):
        if item == flag and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(f"{flag}="):
            return item.split("=", 1)[1]
    return None


def _is_mcp_server_cmd(args: list[str]) -> bool:
    return (
        any(_matches_script_arg(arg, "mcp_server.py") for arg in args)
        or any(Path(arg).name in {"xmuse-mcp-server", "xmuse-compat-mcp-server"} for arg in args)
        or ("-m" in args and "xmuse.mcp_server" in args)
        or _is_python_inline_app_cmd(args, "xmuse.mcp_server")
    )


def _is_room_mcp_server_cmd(args: list[str]) -> bool:
    return (
        any(_matches_script_arg(arg, "room_mcp_server.py") for arg in args)
        or (
            any(Path(arg).name == "xmuse-mcp-server" for arg in args)
            and _command_arg_value(args, "--surface") != "compat"
        )
        or ("-m" in args and "xmuse.room_mcp_server" in args)
        or _is_python_inline_app_cmd(args, "xmuse.room_mcp_server")
    )


def _is_chat_api_cmd(args: list[str]) -> bool:
    return (
        _matches_script_args(args, "chat_api.py")
        or any(Path(arg).name == "xmuse-chat-api" for arg in args)
        or _is_python_inline_app_cmd(args, "xmuse.chat_api")
    )


def _is_memoryos_server_cmd(args: list[str]) -> bool:
    return any(
        Path(item).name == "memoryos" and index + 1 < len(args) and args[index + 1] == "api"
        for index, item in enumerate(args)
    )


def _is_python_inline_app_cmd(args: list[str], module_name: str) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    text = " ".join(args)
    return (
        executable.startswith("python")
        and "-c" in args
        and module_name in text
        and "create_app" in text
    )


def _matches_script_arg(arg: str, script_name: str) -> bool:
    normalized = arg.replace("\\", "/")
    return (
        normalized == script_name
        or normalized == f"xmuse/{script_name}"
        or normalized.endswith(f"/{script_name}")
        or normalized.endswith(f"/xmuse/{script_name}")
    )


def _matches_script_args(args: list[str], *script_names: str) -> bool:
    return any(
        _matches_script_arg(arg, script_name) for arg in args for script_name in script_names
    )


def _is_codex_app_server_cmd(args: list[str]) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    return executable == "codex" and "app-server" in args[1:]


def _is_codex_worker_cmd(args: list[str]) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    if executable == "codex" and "exec" in args[1:]:
        return True
    return "codex exec" in " ".join(args)


def _pid_set(pids: list[int] | None) -> set[int]:
    if pids is None:
        return set()
    return {pid for pid in pids if isinstance(pid, int) and not isinstance(pid, bool)}


def _finalize_process_inventory(
    service_pids: dict[str, set[int]],
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    hard: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    counts_by_service: dict[str, int] = {"runner": 0, "mcp": 0}

    for service_name in PROCESS_SERVICE_ORDER:
        meta = PROCESS_SERVICE_METADATA[service_name]
        pids = sorted(service_pids.get(service_name, set()))
        if pids:
            counts_by_service[service_name] = len(pids)
            services.append(
                {
                    "service": service_name,
                    "label": meta["label"],
                    "category": meta["category"],
                    "writer_capable": meta["writer_capable"],
                    "count": len(pids),
                    "pids": pids,
                    "state": "multiple" if len(pids) > 1 else "running",
                }
            )
        severity = meta.get("missing_severity")
        if not pids and isinstance(severity, str):
            warning = _process_warning_item(
                service_name=service_name,
                severity=severity,
                count=0,
                pids=[],
                duplicate=False,
            )
            warnings.append(warning)
            if severity == "hard":
                hard.append(warning)
            else:
                degraded.append(warning)
        duplicate_severity = meta.get("duplicate_severity")
        if len(pids) > 1 and isinstance(duplicate_severity, str):
            warning = _process_warning_item(
                service_name=service_name,
                severity=duplicate_severity,
                count=len(pids),
                pids=pids,
                duplicate=True,
            )
            warnings.append(warning)
            if duplicate_severity == "hard":
                hard.append(warning)
            else:
                degraded.append(warning)

    runner_pids = service_pids.get("runner", set()) | service_pids.get("room_runner", set())
    mcp_pids = service_pids.get("mcp", set()) | service_pids.get("room_mcp", set())
    return {
        # Compatibility aggregates intentionally include both the retired broad
        # runtime and the default Room-only runtime.  Callers that need to
        # distinguish them must consume ``services``/``counts_by_service``.
        "runner_pids": sorted(runner_pids),
        "mcp_pids": sorted(mcp_pids),
        "services": services,
        "counts_by_service": counts_by_service,
        "warnings": warnings,
        "evidence": {
            "hard": hard,
            "degraded": degraded,
        },
    }


def _process_warning_item(
    *,
    service_name: str,
    severity: str,
    count: int,
    pids: list[int],
    duplicate: bool,
) -> dict[str, Any]:
    meta = PROCESS_SERVICE_METADATA[service_name]
    code = f"duplicate_{service_name}_processes" if duplicate else f"missing_{service_name}_process"
    subject = str(meta["subject"])
    message = (
        f"multiple {subject} processes are running"
        if duplicate
        else f"no {subject} process is running"
    )
    warning = {
        "code": code,
        "severity": severity,
        "message": message,
        "count": count,
    }
    if pids:
        warning["pids"] = pids
    warning["service"] = service_name
    return warning
