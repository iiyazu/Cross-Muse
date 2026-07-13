"""Leaf process primitives for the local Workroom manager.

All lifecycle authority remains with ``start_workroom``.  The functions here
have no manifest writes, background loop, timer, or module-level process state.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ManagedProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...


@dataclass(frozen=True)
class ProcessIdentity:
    start_identity: str
    pgid: int
    environment: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessSpec:
    service: str
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    log_path: Path


class ProcessLifecycleError(RuntimeError):
    """Stable process-leaf error translated by the Workroom coordinator."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def spawn_process(spec: ProcessSpec) -> ManagedProcess:
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = spec.log_path.open("ab")
    try:
        return subprocess.Popen(
            list(spec.command),
            cwd=spec.cwd,
            env=dict(spec.env),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()


def inspect_process(pid: int, *, proc_root: Path = Path("/proc")) -> ProcessIdentity | None:
    proc_dir = proc_root / str(pid)
    try:
        stat_text = (proc_dir / "stat").read_text(encoding="utf-8")
        command_end = stat_text.rfind(")")
        if command_end < 0:
            return None
        fields_after_command = stat_text[command_end + 2 :].split()
        start_ticks = fields_after_command[19]
        pgid = os.getpgid(pid)
        raw_environment = (proc_dir / "environ").read_bytes()
    except (FileNotFoundError, IndexError, OSError):
        return None
    environment: dict[str, str] = {}
    for item in raw_environment.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment[key.decode(errors="replace")] = value.decode(errors="replace")
    return ProcessIdentity(
        start_identity=f"linux-proc-starttime:{start_ticks}",
        pgid=pgid,
        environment=environment,
    )


def port_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:  # noqa: S310
            if not 200 <= int(response.status) < 400:
                return False
            if url.rstrip("/").endswith("/health"):
                payload = json.loads(response.read().decode("utf-8"))
                return isinstance(payload, dict) and payload.get("status") == "ok"
            return True
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def http_json(url: str) -> Mapping[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:  # noqa: S310
            if int(response.status) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def identity_matches(
    record: Mapping[str, Any],
    inspector: Callable[[int], ProcessIdentity | None],
) -> bool:
    pid = record.get("pid")
    expected = record.get("start_identity")
    if not isinstance(pid, int) or not isinstance(expected, str) or not expected:
        return False
    identity = inspector(pid)
    return identity is not None and identity.start_identity == expected


def service_is_live(
    record: Mapping[str, Any],
    *,
    generation: str,
    xmuse_root: Path,
    inspector: Callable[[int], ProcessIdentity | None],
) -> bool:
    if not identity_matches(record, inspector):
        return False
    pid = record.get("pid")
    if not isinstance(pid, int):
        return False
    identity = inspector(pid)
    if identity is None:
        return False
    environment = identity.environment
    return (
        environment.get("XMUSE_WORKROOM_GENERATION") == generation
        and environment.get("XMUSE_ROOT") == str(xmuse_root)
        and environment.get("XMUSE_WORKROOM_SERVICE") == record.get("service")
    )


def record_process(
    process: ManagedProcess,
    *,
    service: str,
    generation: str,
    host: str,
    port: int,
    url: str,
    log_path: Path,
    xmuse_root: Path,
    inspector: Callable[[int], ProcessIdentity | None],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    deadline = monotonic() + timeout_s
    while True:
        identity = inspector(process.pid)
        if identity is not None:
            expected_env = identity.environment
            if (
                expected_env.get("XMUSE_WORKROOM_GENERATION") == generation
                and expected_env.get("XMUSE_ROOT") == str(xmuse_root)
                and expected_env.get("XMUSE_WORKROOM_SERVICE") == service
            ):
                return {
                    "service": service,
                    "pid": process.pid,
                    "pgid": identity.pgid,
                    "start_identity": identity.start_identity,
                    "generation": generation,
                    "host": host,
                    "port": port,
                    "url": url,
                    "log_path": str(log_path),
                }
        if process.poll() is not None:
            raise ProcessLifecycleError(
                "service_exited",
                f"{service} exited before its process identity was established",
            )
        if monotonic() >= deadline:
            raise ProcessLifecycleError(
                "process_identity_timeout",
                f"could not establish {service} process identity",
            )
        sleep(0.05)


def stop_service_record(
    record: Mapping[str, Any],
    *,
    generation: str,
    xmuse_root: Path,
    inspector: Callable[[int], ProcessIdentity | None],
    signal_group: Callable[[int, int], None],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    timeout_s: float,
) -> bool:
    def live() -> bool:
        return service_is_live(
            record,
            generation=generation,
            xmuse_root=xmuse_root,
            inspector=inspector,
        )

    if not live():
        return True
    pgid = record.get("pgid")
    if not isinstance(pgid, int):
        return False
    try:
        signal_group(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = monotonic() + timeout_s
    while live():
        if monotonic() >= deadline:
            try:
                signal_group(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            kill_deadline = monotonic() + 2.0
            while live():
                if monotonic() >= kill_deadline:
                    return False
                sleep(0.05)
            return True
        sleep(0.05)
    return True


def stop_spawned_processes(
    processes: Sequence[ManagedProcess],
    *,
    signal_group: Callable[[int, int], None],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    timeout_s: float = 2.0,
) -> None:
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        try:
            signal_group(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = monotonic() + timeout_s
        while process.poll() is None and monotonic() < deadline:
            sleep(0.05)
        if process.poll() is not None:
            continue
        try:
            signal_group(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            continue


__all__ = [
    "ManagedProcess",
    "ProcessIdentity",
    "ProcessLifecycleError",
    "ProcessSpec",
    "http_json",
    "http_ready",
    "identity_matches",
    "inspect_process",
    "port_available",
    "record_process",
    "service_is_live",
    "spawn_process",
    "stop_service_record",
    "stop_spawned_processes",
]
