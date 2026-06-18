from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROCESS_SERVICE_ORDER = (
    "runner",
    "mcp",
    "dashboard_api",
    "chat_api",
    "master_loop_runner",
    "xmuse_main_runner",
    "overnight_runner",
    "scheduler_monitor",
    "start_scheduler_monitor",
    "god_launcher",
    "master_review_runner",
    "integrated_test_runner",
    "master_merge_runner",
    "persistent_god_shim",
    "codex_app_server",
    "raylet",
    "gcs_server",
    "ray_worker",
    "codex_worker",
    "opencode_worker",
)
PROCESS_SERVICE_METADATA: dict[str, dict[str, Any]] = {
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
    "master_loop_runner": {
        "label": "master_loop",
        "category": "legacy_runner",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse legacy master loop runner",
    },
    "xmuse_main_runner": {
        "label": "xmuse_main",
        "category": "legacy_runner",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse legacy xmuse_main runner",
    },
    "overnight_runner": {
        "label": "overnight_runner",
        "category": "legacy_runner",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse overnight runner",
    },
    "scheduler_monitor": {
        "label": "scheduler_monitor",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "degraded",
        "subject": "xmuse scheduler monitor",
    },
    "start_scheduler_monitor": {
        "label": "start_scheduler_monitor",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "degraded",
        "subject": "xmuse scheduler monitor starter",
    },
    "god_launcher": {
        "label": "god_launcher",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse GOD launcher",
    },
    "master_review_runner": {
        "label": "master_review_runner",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "degraded",
        "subject": "xmuse master review runner",
    },
    "integrated_test_runner": {
        "label": "integrated_test_runner",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "degraded",
        "subject": "xmuse integrated test runner",
    },
    "master_merge_runner": {
        "label": "master_merge_runner",
        "category": "control_plane",
        "writer_capable": True,
        "duplicate_severity": "hard",
        "subject": "xmuse master merge runner",
    },
    "persistent_god_shim": {
        "label": "codex_persistent",
        "category": "session_shim",
        "writer_capable": True,
        "subject": "xmuse persistent GOD shim",
    },
    "codex_app_server": {
        "label": "codex_app_server",
        "category": "session_transport",
        "writer_capable": False,
        "subject": "Codex app-server",
    },
    "raylet": {
        "label": "raylet",
        "category": "ray_runtime",
        "writer_capable": False,
        "subject": "Ray raylet",
    },
    "gcs_server": {
        "label": "gcs_server",
        "category": "ray_runtime",
        "writer_capable": False,
        "subject": "Ray GCS server",
    },
    "ray_worker": {
        "label": "ray_worker",
        "category": "ray_runtime",
        "writer_capable": False,
        "subject": "Ray worker",
    },
    "codex_worker": {
        "label": "codex_worker",
        "category": "worker",
        "writer_capable": False,
        "subject": "repo-local Codex worker",
    },
    "opencode_worker": {
        "label": "opencode_worker",
        "category": "worker",
        "writer_capable": False,
        "subject": "repo-local OpenCode worker",
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
) -> dict[str, Any]:
    """Discover compact runtime process inventory for xmuse control-plane roles."""
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
) -> tuple[list[int], list[int]]:
    inventory = discover_xmuse_runtime_processes(proc_root)
    return list(inventory["runner_pids"]), list(inventory["mcp_pids"])


def process_warnings(
    *,
    runner_count: int,
    mcp_count: int,
    process_inventory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if process_inventory is not None:
        warnings = process_inventory.get("warnings")
        if isinstance(warnings, list):
            return [warning for warning in warnings if isinstance(warning, dict)]
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
    return [
        part.decode("utf-8", errors="replace")
        for part in content.split(b"\0")
        if part
    ]


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
    if _is_platform_runner_cmd(args):
        return "runner"
    if _is_mcp_server_cmd(args):
        return "mcp"
    if _matches_script_args(args, "dashboard_api.py"):
        return "dashboard_api"
    if _matches_script_args(args, "chat_api.py"):
        return "chat_api"
    if _matches_script_args(args, "master_loop.py"):
        return "master_loop_runner"
    if _matches_script_args(args, "xmuse_main.py"):
        return "xmuse_main_runner"
    if _matches_script_args(args, "overnight_runner.sh"):
        return "overnight_runner"
    if _matches_script_args(args, "scheduler_monitor.sh"):
        return "scheduler_monitor"
    if _matches_script_args(args, "start_scheduler_monitor.sh"):
        return "start_scheduler_monitor"
    if _matches_script_args(args, "god_launcher.sh"):
        return "god_launcher"
    if _matches_script_args(args, "master_review_runner.py"):
        return "master_review_runner"
    if _matches_script_args(args, "integrated_test_runner.py"):
        return "integrated_test_runner"
    if _matches_script_args(args, "master_merge_runner.py"):
        return "master_merge_runner"
    if _is_persistent_god_shim_cmd(args):
        return "persistent_god_shim"
    if _is_codex_app_server_cmd(args):
        return "codex_app_server"
    if _is_raylet_cmd(args):
        return "raylet"
    if _is_gcs_server_cmd(args):
        return "gcs_server"
    if _is_ray_worker_cmd(args):
        return "ray_worker"
    if _is_codex_worker_cmd(args):
        return "codex_worker"
    if _is_opencode_worker_cmd(args):
        return "opencode_worker"
    return None


def _is_platform_runner_cmd(args: list[str]) -> bool:
    if "--health-once" in args:
        return False
    return any(_matches_script_arg(arg, "platform_runner.py") for arg in args) or any(
        Path(arg).name == "xmuse-platform-runner" for arg in args
    )


def _is_mcp_server_cmd(args: list[str]) -> bool:
    return (
        any(_matches_script_arg(arg, "mcp_server.py") for arg in args)
        or any(Path(arg).name == "xmuse-mcp-server" for arg in args)
        or ("-m" in args and "xmuse.mcp_server" in args)
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
        _matches_script_arg(arg, script_name)
        for arg in args
        for script_name in script_names
    )


def _is_persistent_god_shim_cmd(args: list[str]) -> bool:
    return _matches_script_args(args, "codex_persistent.py") or (
        "-m" in args and "xmuse_core.agents.codex_persistent" in args
    )


def _is_codex_app_server_cmd(args: list[str]) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    return executable == "codex" and "app-server" in args[1:]


def _is_raylet_cmd(args: list[str]) -> bool:
    return any(Path(arg).name == "raylet" for arg in args)


def _is_gcs_server_cmd(args: list[str]) -> bool:
    return any(Path(arg).name == "gcs_server" for arg in args)


def _is_ray_worker_cmd(args: list[str]) -> bool:
    return any(arg.startswith("ray::") for arg in args)


def _is_codex_worker_cmd(args: list[str]) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    if executable == "codex" and "exec" in args[1:]:
        return True
    return "codex exec" in " ".join(args)


def _is_opencode_worker_cmd(args: list[str]) -> bool:
    if not args:
        return False
    executable = Path(args[0]).name
    if executable == "opencode" and "run" in args[1:]:
        return True
    return "opencode run" in " ".join(args)


def _pid_set(pids: list[int] | None) -> set[int]:
    if pids is None:
        return set()
    return {
        pid
        for pid in pids
        if isinstance(pid, int) and not isinstance(pid, bool)
    }


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

    return {
        "runner_pids": sorted(service_pids.get("runner", set())),
        "mcp_pids": sorted(service_pids.get("mcp", set())),
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
    code = (
        f"duplicate_{service_name}_processes"
        if duplicate
        else f"missing_{service_name}_process"
    )
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
