from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.platform.run_health import build_run_health_model, discover_xmuse_processes


class RunnerStartError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerSupervisorConfig:
    repo_root: Path
    pid_file: Path
    lanes_path: Path | None = None
    log_path: Path | None = None
    max_hours: float = 10.0
    max_concurrent: int = 4
    god_runtime: str = "codex"
    peer_chat: bool = True
    persistent_review_god: bool = True
    persistent_execute_god: bool = False
    mcp_port: int = 8100


def write_pid_file(
    pid_file: Path,
    *,
    pid: int,
    command: Sequence[str],
    log_path: Path,
) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(
        json.dumps(
            {
                "pid": pid,
                "command": list(command),
                "log_path": str(log_path),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def read_pid_file(pid_file: Path) -> dict[str, Any] | None:
    if not pid_file.exists():
        return None
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"pid file is not a JSON object: {pid_file}")
    return payload


def start_runner(
    config: RunnerSupervisorConfig,
    *,
    replace: bool = False,
    stop_timeout_s: float = 10.0,
    discover_processes: Callable[[], tuple[list[int], list[int]]] = discover_xmuse_processes,
    terminate_process: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
    popen: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    runner_pids, _mcp_pids = discover_processes()
    if runner_pids and not replace:
        raise RunnerStartError(
            "runner already running; use --replace to stop existing runner first"
        )
    if runner_pids and replace:
        for pid in runner_pids:
            terminate_process(pid, signal.SIGTERM)
        _wait_for_runner_exit(
            discover_processes=discover_processes,
            sleep=sleep,
            timeout_s=stop_timeout_s,
        )

    command = runner_command(config)
    log_path = _resolve_log_path(config)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab")
    try:
        process = popen(
            command,
            cwd=config.repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()

    write_pid_file(
        config.pid_file,
        pid=int(process.pid),
        command=command,
        log_path=log_path,
    )
    return {"pid": int(process.pid), "command": command, "log_path": str(log_path)}


def _wait_for_runner_exit(
    *,
    discover_processes: Callable[[], tuple[list[int], list[int]]],
    sleep: Callable[[float], None],
    timeout_s: float,
) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        runner_pids, _mcp_pids = discover_processes()
        if not runner_pids:
            return
        if time.monotonic() >= deadline:
            raise RunnerStartError(
                "existing runner did not stop after SIGTERM; refusing duplicate start"
            )
        sleep(0.2)


def runner_status(
    config: RunnerSupervisorConfig,
    *,
    runner_pids: list[int] | None = None,
    mcp_pids: list[int] | None = None,
    live_pids: set[int] | None = None,
) -> dict[str, Any]:
    lanes_path = config.lanes_path or config.repo_root / "xmuse" / "feature_lanes.json"
    health = build_run_health_model(
        lanes_path,
        runner_pids=runner_pids,
        mcp_pids=mcp_pids,
        live_pids=live_pids,
        xmuse_root=config.repo_root / "xmuse",
    )
    return {
        "pid_file": read_pid_file(config.pid_file),
        "health": health,
    }


def runner_command(config: RunnerSupervisorConfig) -> list[str]:
    command = [
        sys.executable,
        "xmuse/platform_runner.py",
        "--max-hours",
        str(config.max_hours),
        "--max-concurrent",
        str(config.max_concurrent),
        "--god-runtime",
        config.god_runtime,
        "--mcp-port",
        str(config.mcp_port),
    ]
    if config.peer_chat:
        command.append("--peer-chat")
    if config.persistent_review_god:
        command.append("--persistent-review-god")
    if config.persistent_execute_god:
        command.append("--persistent-execute-god")
    return command


def _resolve_log_path(config: RunnerSupervisorConfig) -> Path:
    if config.log_path is not None:
        return config.log_path
    return config.repo_root / "xmuse" / "logs" / "platform_runner.supervisor.log"
