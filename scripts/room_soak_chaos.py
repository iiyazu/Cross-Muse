#!/usr/bin/env python3
"""Run bounded multi-Room soak and chaos acceptance profiles.

The live orchestrator deliberately keeps provider text and local process identity out of
its result.  It owns a fresh ``XMUSE_ROOT``, starts the production Workroom, writes only
through the fixed Next routes, observes durable SQLite facts, injects identity-scoped
faults, verifies every Room in a real browser, and always stops what it started.

The result contract and the deterministic CI simulation live in ``xmuse_core``.  Their
imports are delayed so this script remains unit-testable without importing either runtime
at module import time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

FRONTEND_URL = "http://127.0.0.1:3000"
CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat"
LIVE_EVIDENCE_SCHEMA = "room_soak_live_evidence/v1"
BROWSER_INPUT_SCHEMA = "room_soak_browser_input/v1"
BROWSER_EVIDENCE_SCHEMA = "room_soak_browser_evidence/v1"
CLI_ERROR_SCHEMA = "room_soak_chaos_cli_error/v1"
CLI_ERROR_PROOF_BOUNDARY = "cli_failure_before_complete_soak_evidence"
REQUIRED_SERVICES = ("frontend", "chat_api", "room_runner", "room_mcp")
MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
MAX_ACTIVE_PROVIDER_DELIVERIES = 4
MAX_FIRST_CLAIM_MS = 240_000.0
MAX_FAULT_RECOVERY_MS = 45_000
CLEANUP_PROVIDER_TIMEOUT_S = 10.0
RESOURCE_SAMPLE_INTERVAL_MS = 1_000


@dataclass(frozen=True)
class LiveProfileSpec:
    profile_id: str
    room_count: int
    agents_per_room: int
    wave_count: int
    human_turns_per_room: int
    max_attempts: int | None
    minimum_duration_s: float = 0.0
    memory_recovery: bool = False


LIVE_PROFILES: dict[str, LiveProfileSpec] = {
    "live-short": LiveProfileSpec("live-short", 4, 2, 2, 2, 48),
    "live-soak": LiveProfileSpec(
        "live-soak",
        6,
        2,
        4,
        4,
        128,
        minimum_duration_s=3600.0,
    ),
    "memory-recovery": LiveProfileSpec(
        "memory-recovery",
        2,
        2,
        2,
        10,
        None,
        memory_recovery=True,
    ),
}


class SoakError(RuntimeError):
    """A stable failure that is safe to place in machine-readable evidence."""

    def __init__(self, code: str, *, blocked: bool = False) -> None:
        self.code = code
        self.blocked = blocked
        super().__init__(code)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ManagedProcess(Protocol):
    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True)
class HttpJsonResponse:
    status: int
    payload: Mapping[str, Any] | None


@dataclass(frozen=True)
class RepositorySnapshot:
    head: str
    clean: bool
    content_digest: str
    worktree_inventory_digest: str


@dataclass(frozen=True)
class ProcessSample:
    rss_bytes: int
    fd_count: int
    process_count: int
    offset_ms: int = 0


@dataclass(frozen=True)
class ProcessBinding:
    pid: int
    start_identity: str


@dataclass(frozen=True)
class BrowserVerificationRequest:
    repo_root: Path
    frontend_url: str
    room_ids: tuple[str, ...]
    artifact_dir: Path
    timeout_s: float
    environment: Mapping[str, str]


@dataclass(frozen=True)
class SoakConfig:
    repo_root: Path
    profile_id: str
    runtime_root: Path | None = None
    result_path: Path | None = None
    memoryos_executable: Path | None = None
    confirm_provider_cost: bool = False
    keep_runtime_root: bool = False
    build_frontend: bool = True
    readiness_timeout_s: float = 120.0
    settle_timeout_s: float = 1200.0
    browser_timeout_s: float = 300.0


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(124)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _spawn_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> ManagedProcess:
    return subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def _http_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    *,
    timeout_s: float,
) -> HttpJsonResponse:
    body = None
    headers = {"Accept": "application/json", "Cache-Control": "no-store"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": FRONTEND_URL,
            }
        )
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout_s)  # noqa: S310
    except urllib.error.HTTPError as exc:
        response = exc
    except (OSError, urllib.error.URLError) as exc:
        raise SoakError("soak_http_unavailable") from exc
    try:
        raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise SoakError("soak_http_response_too_large")
        parsed = json.loads(raw) if raw else None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SoakError("soak_http_response_invalid") from exc
    finally:
        response.close()
    return HttpJsonResponse(
        int(response.status),
        parsed if isinstance(parsed, Mapping) else None,
    )


def _repository_snapshot(repo_root: Path) -> RepositorySnapshot:
    def git(*args: str) -> bytes:
        return subprocess.run(
            ("git", *args),
            cwd=repo_root,
            capture_output=True,
            check=True,
        ).stdout

    head = git("rev-parse", "HEAD").decode().strip()
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    inventory = git("worktree", "list", "--porcelain", "-z")
    index = git("ls-files", "--stage", "-z")
    digest = hashlib.sha256(index)
    for raw_entry in index.split(b"\0"):
        if not raw_entry or b"\t" not in raw_entry:
            continue
        raw_name = raw_entry.split(b"\t", 1)[1]
        relative = raw_name.decode("utf-8", errors="surrogateescape")
        path = repo_root / relative
        digest.update(raw_name)
        if path.is_symlink():
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
    return RepositorySnapshot(
        head=head,
        clean=not status,
        content_digest=digest.hexdigest(),
        worktree_inventory_digest=hashlib.sha256(inventory).hexdigest(),
    )


def _process_sample(root_pid: int) -> ProcessSample:
    pending = [root_pid]
    found: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in found or not Path(f"/proc/{pid}").exists():
            continue
        found.add(pid)
        try:
            children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        except OSError:
            children = []
        pending.extend(int(item) for item in children if item.isdigit())
    page_size = os.sysconf("SC_PAGE_SIZE")
    rss = 0
    fds = 0
    for pid in found:
        try:
            resident_pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
            rss += resident_pages * page_size
        except (OSError, IndexError, ValueError):
            pass
        try:
            fds += sum(1 for _item in Path(f"/proc/{pid}/fd").iterdir())
        except OSError:
            pass
    return ProcessSample(rss, fds, len(found))


def _provider_pids(runtime_root: Path) -> tuple[int, ...]:
    return tuple(sorted({binding.pid for binding in _provider_bindings(runtime_root).values()}))


def _provider_bindings(runtime_root: Path) -> dict[str, ProcessBinding]:
    from xmuse_core.chat.room_runtime import read_process_start_identity

    try:
        payload = json.loads((runtime_root / "god_sessions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    sessions = payload.get("sessions") if isinstance(payload, Mapping) else None
    if not isinstance(sessions, list):
        return {}
    bindings: dict[str, ProcessBinding] = {}
    for item in sessions:
        if (
            not isinstance(item, Mapping)
            or not _safe_id(item.get("god_session_id"))
            or not isinstance(item.get("pid"), int)
            or isinstance(item.get("pid"), bool)
            or int(item["pid"]) <= 0
        ):
            continue
        pid = int(item["pid"])
        identity = read_process_start_identity(pid)
        if identity is not None:
            bindings[str(item["god_session_id"])] = ProcessBinding(pid, identity)
    return bindings


def _runtime_provider_pids(runtime_root: Path) -> tuple[int, ...]:
    from xmuse_core.runtime.processes import discover_xmuse_runtime_processes

    runner = _runner_process_binding(runtime_root)
    if runner is None:
        return ()
    # Isolated Room Codex processes intentionally do not inherit XMUSE_ROOT and
    # run from the read-only workspace, so root-marker discovery cannot own them.
    # Instead, classify all Codex processes and retain only descendants of the
    # start-identity-checked Runner recorded by this runtime root.
    inventory = discover_xmuse_runtime_processes()
    candidates: set[int] = set()
    services = inventory.get("services")
    if not isinstance(services, list):
        return ()
    for service in services:
        if not isinstance(service, Mapping) or service.get("service") not in {
            "codex_app_server",
            "codex_worker",
        }:
            continue
        raw_pids = service.get("pids")
        if isinstance(raw_pids, list):
            candidates.update(
                value
                for value in raw_pids
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
            )
    classified = {
        pid for pid in candidates if pid != runner.pid and _process_descends_from(pid, {runner.pid})
    }
    # The npm-installed Codex launcher is a Node wrapper.  The durable session
    # registry owns that wrapper PID while process classification sees its native
    # app-server child.  Admit the wrapper only when it is itself a Runner
    # descendant and is the ancestor of a classified Codex process.
    wrappers = {
        binding.pid
        for binding in _provider_bindings(runtime_root).values()
        if binding.pid != runner.pid
        and _process_descends_from(binding.pid, {runner.pid})
        and (
            binding.pid in classified
            or any(_process_descends_from(pid, {binding.pid}) for pid in classified)
        )
    }
    return tuple(sorted(classified | wrappers))


def _runtime_service_counts(runtime_root: Path) -> Mapping[str, int]:
    from xmuse_core.runtime.processes import discover_xmuse_runtime_processes

    inventory = discover_xmuse_runtime_processes(xmuse_root=runtime_root)
    counts = {"room_runner": 0, "room_mcp": 0, "codex": 0}
    services = inventory.get("services")
    if not isinstance(services, list):
        return counts
    for service in services:
        if not isinstance(service, Mapping):
            continue
        name = service.get("service")
        raw_pids = service.get("pids")
        pids = (
            {
                value
                for value in raw_pids
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
            }
            if isinstance(raw_pids, list)
            else set()
        )
        if name in {"room_runner", "room_mcp"}:
            counts[str(name)] = len(pids)
    counts["codex"] = len(_runtime_provider_pids(runtime_root))
    return counts


def _process_start_identity(pid: int) -> str | None:
    from xmuse_core.chat.room_runtime import read_process_start_identity

    return read_process_start_identity(pid)


def _memoryos_process_binding(runtime_root: Path) -> ProcessBinding | None:
    from xmuse_core.chat.room_runtime import read_process_start_identity

    try:
        payload = json.loads((runtime_root / "workroom-runtime.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    services = payload.get("services") if isinstance(payload, Mapping) else None
    memory = services.get("memoryos") if isinstance(services, Mapping) else None
    if not isinstance(memory, Mapping):
        return None
    pid = memory.get("pid")
    expected = memory.get("start_identity")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(expected, str)
        or not expected
        or read_process_start_identity(pid) != expected
    ):
        return None
    return ProcessBinding(pid, expected)


def _runner_process_binding(runtime_root: Path) -> ProcessBinding | None:
    from xmuse_core.chat.room_runtime import read_process_start_identity

    try:
        payload = json.loads(
            (runtime_root / "workroom_room_runner.pid.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    pid = payload.get("pid")
    expected = payload.get("start_identity")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(expected, str)
        or not expected
        or read_process_start_identity(pid) != expected
    ):
        return None
    return ProcessBinding(pid, expected)


def _default_get_profile(profile_id: str) -> Any:
    from xmuse_core.chat.room_soak_chaos import get_soak_profile

    return get_soak_profile(profile_id)


def _default_build_result(**kwargs: Any) -> dict[str, Any]:
    from xmuse_core.chat.room_soak_chaos import build_soak_result

    return build_soak_result(**kwargs)


def _default_validate_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    from xmuse_core.chat.room_soak_chaos import validate_soak_result

    return validate_soak_result(payload)


def _default_evaluate_result(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    from xmuse_core.chat.room_soak_chaos import evaluate_soak_result

    return evaluate_soak_result(payload)


def _default_write_result(path: Path, payload: Mapping[str, Any]) -> None:
    from xmuse_core.chat.room_soak_chaos import write_soak_result

    write_soak_result(path, payload)


def _default_run_ci_sim(*, runtime_root: Path) -> Mapping[str, Any]:
    from xmuse_core.chat.room_soak_ci import run_ci_sim

    return run_ci_sim(runtime_root=runtime_root)


BrowserVerifier = Callable[[BrowserVerificationRequest], Mapping[str, Any]]


@dataclass
class SoakDependencies:
    run: Callable[..., CommandResult] = _run_command
    spawn: Callable[..., ManagedProcess] = _spawn_command
    which: Callable[[str], str | None] = shutil.which
    http_json: Callable[..., HttpJsonResponse] = _http_json
    signal_pid: Callable[[int, int], None] = os.kill
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], str] = _utc_now
    port_available: Callable[[str, int], bool] = _port_available
    repository_snapshot: Callable[[Path], RepositorySnapshot] = _repository_snapshot
    process_sample: Callable[[int], ProcessSample] = _process_sample
    provider_pids: Callable[[Path], tuple[int, ...]] = _provider_pids
    provider_bindings: Callable[[Path], dict[str, ProcessBinding]] = _provider_bindings
    runtime_provider_pids: Callable[[Path], tuple[int, ...]] = _runtime_provider_pids
    runtime_service_counts: Callable[[Path], Mapping[str, int]] = _runtime_service_counts
    process_start_identity: Callable[[int], str | None] = _process_start_identity
    memoryos_process_binding: Callable[[Path], ProcessBinding | None] = _memoryos_process_binding
    runner_process_binding: Callable[[Path], ProcessBinding | None] = _runner_process_binding
    get_profile: Callable[[str], Any] = _default_get_profile
    build_result: Callable[..., dict[str, Any]] = _default_build_result
    validate_result: Callable[[Mapping[str, Any]], dict[str, Any]] = _default_validate_result
    evaluate_result: Callable[[Mapping[str, Any]], tuple[bool, tuple[str, ...]]] = (
        _default_evaluate_result
    )
    write_result: Callable[[Path, Mapping[str, Any]], None] = _default_write_result
    run_ci_sim: Callable[..., Mapping[str, Any]] = _default_run_ci_sim
    browser_verifier: BrowserVerifier | None = None


@dataclass
class _Correlation:
    conversation_id: str
    activity_id: str
    posted_monotonic: float


@dataclass(frozen=True)
class _PendingChaosEvent:
    kind: str
    reason_code: str
    started_at: float
    run_started_at: float
    recovery_ms: int
    status: Mapping[str, Any]
    active_delivery_count: int | None
    managed_reconcile: bool
    runner_count: int
    mcp_count: int


@dataclass
class _MemoryFaultProof:
    binding: ProcessBinding
    status_before: Mapping[str, Any]
    started_at: float
    run_started_at: float
    cutoff_by_room: dict[str, int]
    wave0_activity_ids: set[str]
    fault_window_activity_ids: set[str] = field(default_factory=set)
    backlog_observed: bool = False


@dataclass
class _LiveState:
    manager: ManagedProcess | None = None
    room_ids: list[str] = field(default_factory=list)
    correlations: list[_Correlation] = field(default_factory=list)
    process_samples: list[ProcessSample] = field(default_factory=list)
    chaos_events: list[dict[str, Any]] = field(default_factory=list)
    max_active_deliveries: int = 0
    max_active_posts: int = 0
    rooms_first_claimed: set[str] = field(default_factory=set)
    attempts_until_all_rooms_first_claimed: int = 0
    queued_correlations_before_host: int = 0
    memory_restart_count: int = 0
    run_started_monotonic: float | None = None
    next_resource_sample_ms: int = 0
    warmup_cutoff_ms: int | None = None
    host_delivery_evidence_seen: bool = False
    memory_fault_proof: _MemoryFaultProof | None = None
    verified_memory_evidence: dict[str, int | bool] | None = None
    browser: dict[str, int] = field(
        default_factory=lambda: {"refreshes": 0, "console_errors": 0, "page_errors": 0}
    )


def _clean_environment() -> dict[str, str]:
    denied = {
        "XMUSE_OPERATOR_TOKEN",
        "XMUSE_ROOT",
        "XMUSE_WORKROOM_GENERATION",
        "XMUSE_WORKROOM_MANAGED",
        "XMUSE_WORKROOM_SERVICE",
        "XMUSE_MEMORYOS_API_KEY",
    }
    return {key: value for key, value in os.environ.items() if key not in denied}


def _checked(
    deps: SoakDependencies,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    code: str,
    blocked: bool = False,
) -> CommandResult:
    result = deps.run(command, cwd=cwd, env=env, timeout_s=timeout_s)
    if result.returncode != 0:
        raise SoakError(code, blocked=blocked)
    return result


def _json_object(raw: str, code: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_HTTP_RESPONSE_BYTES:
        raise SoakError(code)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SoakError(code) from exc
    if not isinstance(payload, dict):
        raise SoakError(code)
    return payload


def _workroom_status(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    result = deps.run(
        ("uv", "run", "xmuse-workroom", "status", "--root", str(runtime_root)),
        cwd=config.repo_root,
        env=env,
        timeout_s=15.0,
    )
    if not result.stdout.strip():
        raise SoakError("soak_workroom_status_unavailable")
    return _json_object(result.stdout, "soak_workroom_status_invalid")


def _service(status: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    services = status.get("services")
    if isinstance(services, list):
        for item in services:
            if isinstance(item, Mapping) and item.get("service") == name:
                return item
    raise SoakError(f"soak_service_{name}_missing")


def _service_count(status: Mapping[str, Any], name: str) -> int:
    try:
        service = _service(status, name)
    except SoakError:
        return 0
    pids = service.get("pids")
    if isinstance(pids, list):
        return sum(isinstance(item, int) and not isinstance(item, bool) for item in pids)
    return int(service.get("live") is True)


def _host_active_deliveries(status: Mapping[str, Any]) -> int | None:
    host = _service(status, "room_runner").get("host")
    value = host.get("active_delivery_count") if isinstance(host, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _active_deliveries(status: Mapping[str, Any]) -> int:
    return _host_active_deliveries(status) or 0


def _required_runtime_ready(
    status: Mapping[str, Any],
    owned_counts: Mapping[str, int],
) -> bool:
    try:
        return (
            status.get("state") == "ready"
            and all(_service(status, name).get("ready") is True for name in REQUIRED_SERVICES)
            and owned_counts.get("room_runner") == 1
            and owned_counts.get("room_mcp") == 1
        )
    except SoakError:
        return False


def _wait_ready(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    deadline = deps.monotonic() + (timeout_s or config.readiness_timeout_s)
    while deps.monotonic() < deadline:
        if state.manager is not None and state.manager.poll() is not None:
            raise SoakError("soak_workroom_manager_exited")
        try:
            status = _workroom_status(config, deps, runtime_root, env)
            owned_counts = deps.runtime_service_counts(runtime_root)
            if _required_runtime_ready(status, owned_counts):
                _sample_runtime(config, deps, state, runtime_root, env, status=status)
                return status
        except SoakError:
            pass
        deps.sleep(0.25)
    raise SoakError("soak_workroom_readiness_timeout", blocked=True)


def _sample_runtime(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    status: Mapping[str, Any] | None = None,
    force_resource: bool = False,
) -> None:
    offset_ms = (
        max(0, round((deps.monotonic() - state.run_started_monotonic) * 1000))
        if state.run_started_monotonic is not None
        else 0
    )
    if (
        state.manager is not None
        and state.manager.poll() is None
        and (force_resource or offset_ms >= state.next_resource_sample_ms)
    ):
        raw = deps.process_sample(state.manager.pid)
        state.process_samples.append(
            ProcessSample(
                rss_bytes=raw.rss_bytes,
                fd_count=raw.fd_count,
                process_count=raw.process_count,
                offset_ms=offset_ms,
            )
        )
        state.next_resource_sample_ms = offset_ms + RESOURCE_SAMPLE_INTERVAL_MS
    try:
        current = status or _workroom_status(config, deps, runtime_root, env)
        active = _host_active_deliveries(current)
        if active is not None:
            state.host_delivery_evidence_seen = True
            state.max_active_deliveries = max(state.max_active_deliveries, active)
    except SoakError:
        return


def _preflight(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    result_path: Path,
) -> RepositorySnapshot:
    if config.profile_id == "live-soak" and not config.confirm_provider_cost:
        raise SoakError("soak_provider_cost_confirmation_required", blocked=True)
    if config.profile_id == "memory-recovery":
        executable = config.memoryos_executable
        if (
            executable is None
            or not executable.expanduser().resolve().is_file()
            or not os.access(executable.expanduser().resolve(), os.X_OK)
        ):
            raise SoakError("soak_memoryos_executable_required", blocked=True)
    if _is_relative_to(result_path, config.repo_root):
        raise SoakError("soak_result_path_inside_workspace", blocked=True)
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise SoakError("soak_runtime_root_not_empty", blocked=True)
    commands = ("git",) if config.profile_id == "ci-sim" else ("git", "uv", "npm", "node", "codex")
    for command in commands:
        if deps.which(command) is None:
            raise SoakError(f"soak_preflight_{command}_not_found", blocked=True)
    snapshot = deps.repository_snapshot(config.repo_root)
    if not snapshot.clean:
        raise SoakError("soak_preflight_worktree_dirty", blocked=True)
    if config.profile_id != "ci-sim":
        for host, port, name in (
            ("127.0.0.1", 3000, "frontend"),
            ("127.0.0.1", 8201, "chat_api"),
        ):
            if not deps.port_available(host, port):
                raise SoakError(f"soak_preflight_{name}_port_in_use", blocked=True)
        _checked(
            deps,
            ("codex", "login", "status"),
            cwd=config.repo_root,
            env=_clean_environment(),
            timeout_s=20.0,
            code="soak_preflight_codex_auth_unavailable",
            blocked=True,
        )
    return snapshot


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _start_workroom(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    if config.build_frontend:
        _checked(
            deps,
            ("npm", "run", "build"),
            cwd=config.repo_root / "frontend",
            env={**env, "NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL": CHAT_API_BASE_URL},
            timeout_s=900.0,
            code="soak_frontend_build_failed",
            blocked=True,
        )
    command: list[str] = [
        "uv",
        "run",
        "xmuse-workroom",
        "start",
        "--root",
        str(runtime_root),
        "--readiness-timeout-s",
        str(config.readiness_timeout_s),
    ]
    if config.profile_id == "memory-recovery":
        assert config.memoryos_executable is not None
        command.extend(("--memory", "--memoryos-executable", str(config.memoryos_executable)))
    runtime_root.mkdir(parents=True, exist_ok=True)
    state.manager = deps.spawn(command, cwd=config.repo_root, env=env)
    return _wait_ready(config, deps, state, runtime_root, env)


def _create_rooms(
    spec: LiveProfileSpec,
    deps: SoakDependencies,
    state: _LiveState,
) -> None:
    def create(index: int) -> str:
        response = deps.http_json(
            "POST",
            f"{FRONTEND_URL}/api/rooms",
            {
                "title": f"Soak Room {index + 1}",
                "client_request_id": f"soak_create_{uuid.uuid4().hex}",
                "initial_participants": [
                    {"role": "architect", "display_name": "Architect", "cli_kind": "codex"},
                    {"role": "review", "display_name": "Reviewer", "cli_kind": "codex"},
                ],
            },
            timeout_s=20.0,
        )
        conversation_id = response.payload.get("id") if response.payload else None
        if response.status != 201 or not _safe_id(conversation_id):
            raise SoakError("soak_room_create_failed")
        return str(conversation_id)

    with ThreadPoolExecutor(max_workers=spec.room_count) as pool:
        futures = [pool.submit(create, index) for index in range(spec.room_count)]
        for future in as_completed(futures):
            state.room_ids.append(future.result())
    state.room_ids.sort()
    if len(state.room_ids) != spec.room_count or len(set(state.room_ids)) != spec.room_count:
        raise SoakError("soak_room_create_count_invalid")


def _post_wave(
    spec: LiveProfileSpec,
    deps: SoakDependencies,
    state: _LiveState,
    *,
    wave: int,
) -> list[_Correlation]:
    if spec.memory_recovery:
        # A two-turn Room cannot prove archival recall: the Host already carries its
        # last eight activities in the causal envelope and correctly excludes them
        # from memory.  The first recovery phase therefore creates nine production
        # HTTP turns per Room; the post-restart phase creates the tenth.  Even if all
        # Agents noop, the first anchor is then outside the recent Room burst.
        turns_per_room = spec.human_turns_per_room - 1 if wave == 0 else 1
        targets = [room_id for room_id in state.room_ids for _ in range(turns_per_room)]
    else:
        targets = list(state.room_ids)
        if wave == 0:
            # The extra first-Room post proves two unresolved correlations can coexist.
            targets.append(state.room_ids[0])
        elif wave == 1:
            # Keep the fixed per-Room turn budget: the first Room already received its
            # second correlation in wave zero.
            targets = state.room_ids[1:]
    barrier = threading.Barrier(len(targets))
    meter_lock = threading.Lock()
    active_posts = 0

    def post(index: int, room_id: str) -> _Correlation:
        nonlocal active_posts
        with meter_lock:
            active_posts += 1
            state.max_active_posts = max(state.max_active_posts, active_posts)
        try:
            barrier.wait(timeout=10.0)
        except threading.BrokenBarrierError as exc:
            with meter_lock:
                active_posts -= 1
            raise SoakError("soak_post_concurrency_barrier_failed") from exc
        started = deps.monotonic()
        message = (
            (
                "Memory recovery phase 1 anchor XMUSE_MEMORY_RECOVERY_ANCHOR_V1: "
                "preserve the source-backed durable fact cobalt-orchid-17 for this "
                f"Room (sample {index + 1}); submit one concise outcome."
            )
            if spec.memory_recovery and wave == 0
            else (
                "Memory recovery phase 2: use source-backed archival evidence to recall "
                "XMUSE_MEMORY_RECOVERY_ANCHOR_V1 and cobalt-orchid-17 for this Room; "
                "submit one concise outcome."
            )
            if spec.memory_recovery
            else (
                f"Soak wave {wave + 1}, item {index + 1}: independently inspect the "
                "durable Room state and submit one concise outcome; do not edit files."
            )
        )
        try:
            response = deps.http_json(
                "POST",
                f"{FRONTEND_URL}/api/rooms/{room_id}/messages",
                {
                    "message": message,
                    "client_request_id": f"soak_post_{uuid.uuid4().hex}",
                },
                timeout_s=30.0,
            )
        finally:
            with meter_lock:
                active_posts -= 1
        activity_id = response.payload.get("activity_id") if response.payload else None
        if response.status != 201 or not _safe_id(activity_id):
            raise SoakError("soak_room_post_failed")
        return _Correlation(room_id, str(activity_id), started)

    correlations: list[_Correlation] = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [pool.submit(post, index, room_id) for index, room_id in enumerate(targets)]
        for future in as_completed(futures):
            correlations.append(future.result())
    state.correlations.extend(correlations)
    return correlations


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= 256


def _pause_runner(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    env: Mapping[str, str],
) -> int:
    status = _workroom_status(config, deps, runtime_root, env)
    runner = _service(status, "room_runner")
    binding = deps.runner_process_binding(runtime_root)
    if binding is None or runner.get("pid") != binding.pid or runner.get("ready") is not True:
        raise SoakError("soak_runner_pause_identity_unavailable")
    try:
        deps.signal_pid(binding.pid, signal.SIGSTOP)
    except OSError as exc:
        raise SoakError("soak_runner_pause_failed") from exc
    return binding.pid


def _resume_runner(deps: SoakDependencies, pid: int) -> None:
    try:
        deps.signal_pid(pid, signal.SIGCONT)
    except OSError as exc:
        raise SoakError("soak_runner_resume_failed") from exc


def _pending_correlation_count(database: Path, conversation_id: str) -> int:
    with _connect_readonly(database) as conn:
        return int(
            conn.execute(
                """select count(distinct a.correlation_id)
                   from room_observations o
                   join room_activities a on a.activity_id = o.activity_id
                   join participants p on p.participant_id = o.participant_id
                   where o.conversation_id = ? and o.delivery_mode = 'active'
                     and o.status = 'pending' and p.status = 'active'""",
                (conversation_id,),
            ).fetchone()[0]
        )


def _active_provider_binding(
    database: Path,
    bindings: Mapping[str, ProcessBinding],
    *,
    preferred_conversation_id: str | None = None,
    require_pending_followup: bool = False,
) -> tuple[str, str, ProcessBinding] | None:
    if not bindings:
        return None
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            """select t.attempt_id, t.god_session_id, t.conversation_id,
                      exists(
                          select 1 from room_observations followup
                          where followup.participant_id = t.participant_id
                            and followup.observation_id <> t.observation_id
                            and followup.status = 'pending'
                      ) has_pending_followup
               from room_observation_attempts t
               where t.state = 'delivering' and t.god_session_id is not null
               order by t.claimed_at, t.attempt_id"""
        ).fetchall()
    ordered = sorted(
        rows,
        key=lambda row: (
            0
            if preferred_conversation_id is not None
            and row["conversation_id"] == preferred_conversation_id
            else 1,
            0 if bool(row["has_pending_followup"]) else 1,
        ),
    )
    for row in ordered:
        if require_pending_followup and not bool(row["has_pending_followup"]):
            continue
        god_session_id = str(row["god_session_id"])
        binding = bindings.get(god_session_id)
        if binding is not None:
            return str(row["attempt_id"]), god_session_id, binding
    return None


def _provider_signal_target(
    binding: ProcessBinding,
    owned_pids: Sequence[int],
    *,
    read_identity: Callable[[int], str | None],
) -> ProcessBinding | None:
    descendants = sorted(
        {
            pid
            for pid in owned_pids
            if pid != binding.pid and _process_descends_from(pid, {binding.pid})
        }
    )
    if len(descendants) == 1:
        identity = read_identity(descendants[0])
        return ProcessBinding(descendants[0], identity) if identity is not None else None
    if not descendants and binding.pid in owned_pids:
        return binding
    return None


def _signal_provider_process_tree(
    registry_binding: ProcessBinding,
    native_target: ProcessBinding,
    *,
    read_identity: Callable[[int], str | None],
    signal_pid: Callable[[int, int], None],
) -> None:
    targets = tuple(
        dict.fromkeys(
            (
                native_target,
                registry_binding,
            )
        )
    )
    if any(read_identity(target.pid) != target.start_identity for target in targets):
        raise SoakError("soak_provider_fault_identity_lost")
    for target in targets:
        try:
            signal_pid(target.pid, signal.SIGKILL)
        except OSError as exc:
            if read_identity(target.pid) == target.start_identity:
                raise SoakError("soak_provider_fault_failed") from exc


def _provider_cleanup_confirmed(database: Path, attempt_id: str) -> bool:
    with _connect_readonly(database) as conn:
        row = conn.execute(
            """select provider_phase, provider_cleanup_reason
               from room_observation_attempts where attempt_id = ?""",
            (attempt_id,),
        ).fetchone()
    return bool(
        row is not None
        and row["provider_phase"] == "cleanup_succeeded"
        and isinstance(row["provider_cleanup_reason"], str)
        and row["provider_cleanup_reason"]
    )


def _connect_readonly(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _correlation_ids(database: Path, correlations: Sequence[_Correlation]) -> dict[str, str]:
    if not correlations:
        return {}
    placeholders = ",".join("?" for _ in correlations)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"select activity_id, correlation_id from room_activities "
            f"where activity_id in ({placeholders})",
            tuple(item.activity_id for item in correlations),
        ).fetchall()
    return {str(row["activity_id"]): str(row["correlation_id"]) for row in rows}


def _correlations_settled(database: Path, correlations: Sequence[_Correlation]) -> tuple[bool, int]:
    correlation_map = _correlation_ids(database, correlations)
    if len(correlation_map) != len(correlations):
        return False, 0
    keys = [(item.conversation_id, correlation_map[item.activity_id]) for item in correlations]
    with _connect_readonly(database) as conn:
        attempts = int(conn.execute("select count(*) from room_observation_attempts").fetchone()[0])
        for conversation_id, correlation_id in keys:
            unresolved = conn.execute(
                """select count(*) from room_observations o
                   join room_activities a on a.activity_id = o.activity_id
                   join participants p on p.participant_id = o.participant_id
                   where o.conversation_id = ? and a.correlation_id = ?
                     and o.delivery_mode = 'active' and p.status = 'active'
                     and o.status <> 'completed'""",
                (conversation_id, correlation_id),
            ).fetchone()[0]
            completed = conn.execute(
                """select count(*) from room_observations o
                   join room_activities a on a.activity_id = o.activity_id
                   where o.conversation_id = ? and a.correlation_id = ?
                     and o.delivery_mode = 'active' and o.status = 'completed'""",
                (conversation_id, correlation_id),
            ).fetchone()[0]
            if int(unresolved) or int(completed) < 1:
                return False, attempts
    return True, attempts


def _claimed_rooms(database: Path, correlations: Sequence[_Correlation]) -> set[str]:
    correlation_map = _correlation_ids(database, correlations)
    if not correlation_map:
        return set()
    claimed: set[str] = set()
    with _connect_readonly(database) as conn:
        for item in correlations:
            correlation_id = correlation_map.get(item.activity_id)
            if correlation_id is None:
                continue
            found = conn.execute(
                """select 1 from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   join room_activities a on a.activity_id = o.activity_id
                   where t.conversation_id = ? and a.correlation_id = ? limit 1""",
                (item.conversation_id, correlation_id),
            ).fetchone()
            if found is not None:
                claimed.add(item.conversation_id)
    return claimed


def _wait_until(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    deadline: float,
    predicate: Callable[[], bool],
    code: str,
) -> None:
    while deps.monotonic() < deadline:
        _sample_runtime(config, deps, state, runtime_root, env)
        if predicate():
            return
        deps.sleep(0.25)
    raise SoakError(code)


def _wait_wave_settled(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    correlations: Sequence[_Correlation],
) -> None:
    database = runtime_root / "chat.db"

    def settled() -> bool:
        claimed = _claimed_rooms(database, correlations)
        state.rooms_first_claimed.update(claimed)
        complete, attempts = _correlations_settled(database, correlations)
        if (
            len(state.rooms_first_claimed) == len(state.room_ids)
            and state.attempts_until_all_rooms_first_claimed == 0
        ):
            state.attempts_until_all_rooms_first_claimed = attempts
        return complete

    _wait_until(
        config,
        deps,
        state,
        runtime_root,
        env,
        deadline=deps.monotonic() + config.settle_timeout_s,
        predicate=settled,
        code="soak_wave_settle_timeout",
    )


def _wait_for_active_deliveries(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    minimum: int,
) -> dict[str, Any]:
    observed: dict[str, Any] = {}

    def ready() -> bool:
        nonlocal observed
        try:
            observed = _workroom_status(config, deps, runtime_root, env)
            _sample_runtime(config, deps, state, runtime_root, env, status=observed)
            active = _host_active_deliveries(observed)
            return active is not None and active >= minimum
        except SoakError:
            return False

    _wait_until(
        config,
        deps,
        state,
        runtime_root,
        env,
        deadline=deps.monotonic() + 120.0,
        predicate=ready,
        code="soak_active_delivery_threshold_timeout",
    )
    return observed


def _record_chaos(
    state: _LiveState,
    *,
    event: _PendingChaosEvent,
    recovery_wave_settled: bool,
) -> None:
    state.chaos_events.append(
        {
            "seq": len(state.chaos_events) + 1,
            "kind": event.kind,
            "reason_code": event.reason_code,
            "offset_ms": max(
                0,
                round((event.started_at - event.run_started_at) * 1000),
            ),
            "recovery_ms": max(0, event.recovery_ms),
            "runner_count": event.runner_count,
            "mcp_count": event.mcp_count,
            "active_delivery_count": event.active_delivery_count,
            "managed_reconcile": event.managed_reconcile,
            "recovery_wave_settled": recovery_wave_settled,
        }
    )


def _kill_one_provider(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
) -> _PendingChaosEvent:
    delivery_status = _wait_for_active_deliveries(
        config,
        deps,
        state,
        runtime_root,
        env,
        1,
    )
    active_at_fault = _active_deliveries(delivery_status)
    deadline = deps.monotonic() + min(120.0, config.settle_timeout_s)
    registry_binding: ProcessBinding | None = None
    signal_target: ProcessBinding | None = None
    target_attempt_id: str | None = None
    target_binding: str | None = None
    while deps.monotonic() < deadline:
        bindings = deps.provider_bindings(runtime_root)
        selected = _active_provider_binding(
            runtime_root / "chat.db",
            bindings,
            preferred_conversation_id=state.room_ids[0] if state.room_ids else None,
            require_pending_followup=bool(state.room_ids),
        )
        owned_codex = set(deps.runtime_provider_pids(runtime_root))
        if selected is not None and selected[2].pid in owned_codex:
            candidate_target = _provider_signal_target(
                selected[2],
                tuple(owned_codex),
                read_identity=deps.process_start_identity,
            )
            if candidate_target is not None:
                target_attempt_id, target_binding, registry_binding = selected
                signal_target = candidate_target
                break
        deps.sleep(0.1)
    if (
        registry_binding is None
        or signal_target is None
        or target_attempt_id is None
        or target_binding is None
    ):
        raise SoakError("soak_provider_fault_target_unavailable")
    started = deps.monotonic()
    _signal_provider_process_tree(
        registry_binding,
        signal_target,
        read_identity=deps.process_start_identity,
        signal_pid=deps.signal_pid,
    )
    recovered: dict[str, Any] | None = None
    recovered_counts: Mapping[str, int] | None = None
    deadline = started + MAX_FAULT_RECOVERY_MS / 1000
    while deps.monotonic() < deadline:
        try:
            status = _workroom_status(config, deps, runtime_root, env)
        except SoakError:
            status = {}
        owned_counts = deps.runtime_service_counts(runtime_root)
        if (
            deps.process_start_identity(signal_target.pid) != signal_target.start_identity
            and deps.process_start_identity(registry_binding.pid) != registry_binding.start_identity
            and _provider_cleanup_confirmed(
                runtime_root / "chat.db",
                target_attempt_id,
            )
            and _required_runtime_ready(status, owned_counts)
        ):
            recovered = status
            recovered_counts = owned_counts
            break
        _sample_runtime(config, deps, state, runtime_root, env, status=status or None)
        deps.sleep(0.1)
    if recovered is None or recovered_counts is None:
        raise SoakError("soak_provider_recovery_timeout")
    return _PendingChaosEvent(
        kind="codex_app_server_sigkill",
        reason_code="codex_app_server_cleanup_confirmed",
        started_at=started,
        run_started_at=run_started_at,
        recovery_ms=round((deps.monotonic() - started) * 1000),
        status=recovered,
        active_delivery_count=active_at_fault,
        managed_reconcile=False,
        runner_count=int(recovered_counts["room_runner"]),
        mcp_count=int(recovered_counts["room_mcp"]),
    )


def _kill_runner_and_wait_recovery(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
) -> _PendingChaosEvent:
    status = _wait_for_active_deliveries(config, deps, state, runtime_root, env, 2)
    runner = _service(status, "room_runner")
    binding = deps.runner_process_binding(runtime_root)
    boot = runner.get("boot_id")
    if binding is None or runner.get("pid") != binding.pid or not _safe_id(boot):
        raise SoakError("soak_runner_fault_identity_unavailable")
    if deps.process_start_identity(binding.pid) != binding.start_identity:
        raise SoakError("soak_runner_fault_identity_unavailable")
    started = deps.monotonic()
    try:
        deps.signal_pid(binding.pid, signal.SIGKILL)
    except OSError as exc:
        raise SoakError("soak_runner_fault_failed") from exc
    deadline = started + MAX_FAULT_RECOVERY_MS / 1000
    recovered: dict[str, Any] | None = None
    recovered_counts: Mapping[str, int] | None = None
    while deps.monotonic() < deadline:
        try:
            candidate = _workroom_status(config, deps, runtime_root, env)
            current = _service(candidate, "room_runner")
            owned_counts = deps.runtime_service_counts(runtime_root)
            if _required_runtime_ready(candidate, owned_counts) and current.get("boot_id") != boot:
                recovered = candidate
                recovered_counts = owned_counts
                break
        except SoakError:
            pass
        _sample_runtime(config, deps, state, runtime_root, env)
        deps.sleep(0.25)
    if recovered is None or recovered_counts is None:
        raise SoakError("soak_runner_recovery_timeout")
    recovery_ms = round((deps.monotonic() - started) * 1000)
    return _PendingChaosEvent(
        kind="runner_sigkill",
        reason_code="runner_reconciled",
        started_at=started,
        run_started_at=run_started_at,
        recovery_ms=recovery_ms,
        status=recovered,
        active_delivery_count=_active_deliveries(status),
        managed_reconcile=True,
        runner_count=int(recovered_counts["room_runner"]),
        mcp_count=int(recovered_counts["room_mcp"]),
    )


def _begin_memoryos_fault(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
) -> _MemoryFaultProof:
    status = _workroom_status(config, deps, runtime_root, env)
    memory = _service(status, "memoryos")
    binding = deps.memoryos_process_binding(runtime_root)
    if binding is None or memory.get("ready") is not True:
        raise SoakError("soak_memoryos_fault_target_unavailable")
    cutoff_by_room, wave0_activity_ids = _memory_fault_cutoff(
        runtime_root / "chat.db",
        state.room_ids,
    )
    if deps.process_start_identity(binding.pid) != binding.start_identity:
        raise SoakError("soak_memoryos_fault_identity_lost")
    started = deps.monotonic()
    try:
        deps.signal_pid(binding.pid, signal.SIGKILL)
    except OSError as exc:
        raise SoakError("soak_memoryos_fault_failed") from exc
    return _MemoryFaultProof(
        binding=binding,
        status_before=status,
        started_at=started,
        run_started_at=run_started_at,
        cutoff_by_room=cutoff_by_room,
        wave0_activity_ids=wave0_activity_ids,
    )


def _memory_fault_cutoff(
    database: Path,
    room_ids: Sequence[str],
) -> tuple[dict[str, int], set[str]]:
    placeholders = ",".join("?" for _ in room_ids)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"""select conversation_id, activity_id, seq from room_activities
                where conversation_id in ({placeholders}) order by conversation_id, seq""",
            tuple(room_ids),
        ).fetchall()
    cutoff = {room_id: 0 for room_id in room_ids}
    activity_ids: set[str] = set()
    for row in rows:
        conversation_id = str(row["conversation_id"])
        cutoff[conversation_id] = max(cutoff[conversation_id], int(row["seq"]))
        activity_ids.add(str(row["activity_id"]))
    if any(value <= 0 for value in cutoff.values()) or not activity_ids:
        raise SoakError("soak_memory_fault_cutoff_unavailable")
    return cutoff, activity_ids


def _record_memory_fault_backlog(
    database: Path,
    proof: _MemoryFaultProof,
    correlations: Sequence[_Correlation],
) -> None:
    activity_ids = {item.activity_id for item in correlations}
    if not activity_ids:
        raise SoakError("soak_memory_fault_backlog_missing")
    placeholders = ",".join("?" for _ in activity_ids)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"""select activity_id, state from room_memory_outbox
                where activity_id in ({placeholders})""",
            tuple(sorted(activity_ids)),
        ).fetchall()
    by_id = {str(row["activity_id"]): str(row["state"]) for row in rows}
    if set(by_id) != activity_ids or any(
        state not in {"pending", "claimed", "failed"} for state in by_id.values()
    ):
        raise SoakError("soak_memory_fault_backlog_missing")
    proof.fault_window_activity_ids = activity_ids
    proof.backlog_observed = True


def _assert_memory_fault_active(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    env: Mapping[str, str],
    proof: _MemoryFaultProof,
) -> None:
    status = _workroom_status(config, deps, runtime_root, env)
    memory = _service(status, "memoryos")
    binding = deps.memoryos_process_binding(runtime_root)
    if memory.get("ready") is True or (binding is not None and binding != proof.binding):
        raise SoakError("soak_memory_fault_window_missed")


def _wait_memoryos_recovery(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    proof: _MemoryFaultProof,
) -> _PendingChaosEvent:
    deadline = proof.started_at + MAX_FAULT_RECOVERY_MS / 1000
    recovered: dict[str, Any] | None = None
    recovered_counts: Mapping[str, int] | None = None
    while deps.monotonic() < deadline:
        candidate = _workroom_status(config, deps, runtime_root, env)
        service = _service(candidate, "memoryos")
        rebound = deps.memoryos_process_binding(runtime_root)
        owned_counts = deps.runtime_service_counts(runtime_root)
        if (
            service.get("ready") is True
            and rebound is not None
            and rebound != proof.binding
            and _required_runtime_ready(candidate, owned_counts)
        ):
            recovered = candidate
            recovered_counts = owned_counts
            break
        # Memory degradation must not lower the required Room runtime readiness.
        if any(_service(candidate, name).get("ready") is not True for name in REQUIRED_SERVICES):
            raise SoakError("soak_memoryos_degraded_room_runtime")
        _sample_runtime(config, deps, state, runtime_root, env, status=candidate)
        deps.sleep(0.5)
    if recovered is None or recovered_counts is None:
        raise SoakError("soak_memoryos_recovery_timeout")
    recovered_memory = _service(recovered, "memoryos")
    observed_restarts = recovered_memory.get("consecutive_restart_count")
    state.memory_restart_count = max(
        state.memory_restart_count,
        observed_restarts
        if isinstance(observed_restarts, int) and not isinstance(observed_restarts, bool)
        else 1,
    )
    return _PendingChaosEvent(
        kind="memoryos_sigkill",
        reason_code="memoryos_reconciled",
        started_at=proof.started_at,
        run_started_at=proof.run_started_at,
        recovery_ms=round((deps.monotonic() - proof.started_at) * 1000),
        status=recovered,
        active_delivery_count=_active_deliveries(proof.status_before),
        managed_reconcile=True,
        runner_count=int(recovered_counts["room_runner"]),
        mcp_count=int(recovered_counts["room_mcp"]),
    )


def _wait_for_wave_offset(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
    offset_s: float,
) -> None:
    target = run_started_at + offset_s
    while deps.monotonic() < target:
        _sample_runtime(config, deps, state, runtime_root, env)
        deps.sleep(min(1.0, max(0.01, target - deps.monotonic())))


def _default_browser_verify(
    request: BrowserVerificationRequest,
    deps: SoakDependencies,
) -> Mapping[str, Any]:
    request.artifact_dir.mkdir(parents=True, exist_ok=True)
    state_path = request.artifact_dir / "browser-input.json"
    evidence_path = request.artifact_dir / "browser-evidence.json"
    state_path.write_text(
        json.dumps(
            {"schema_version": BROWSER_INPUT_SCHEMA, "room_ids": list(request.room_ids)},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    browser_env = {
        **request.environment,
        "XMUSE_SOAK_BROWSER": "1",
        "XMUSE_SOAK_FRONTEND_URL": request.frontend_url,
        "XMUSE_SOAK_BROWSER_INPUT_PATH": str(state_path),
        "XMUSE_SOAK_BROWSER_EVIDENCE_PATH": str(evidence_path),
        "XMUSE_SOAK_BROWSER_OUTPUT_DIR": str(request.artifact_dir / "playwright"),
    }
    result = deps.run(
        ("npm", "run", "test:e2e:real", "--", "room-soak-real.spec.ts"),
        cwd=request.repo_root / "frontend",
        env=browser_env,
        timeout_s=request.timeout_s,
    )
    if result.returncode != 0:
        raise SoakError("soak_browser_verification_failed")
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SoakError("soak_browser_evidence_invalid") from exc
    if not isinstance(payload, Mapping):
        raise SoakError("soak_browser_evidence_invalid")
    return payload


def _verify_browser(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    artifact_dir: Path,
    env: Mapping[str, str],
) -> None:
    request = BrowserVerificationRequest(
        repo_root=config.repo_root,
        frontend_url=FRONTEND_URL,
        room_ids=tuple(state.room_ids),
        artifact_dir=artifact_dir,
        timeout_s=config.browser_timeout_s,
        environment=env,
    )
    payload = (
        deps.browser_verifier(request)
        if deps.browser_verifier is not None
        else _default_browser_verify(request, deps)
    )
    expected = {
        "schema_version",
        "refreshes",
        "console_errors",
        "page_errors",
    }
    if set(payload) != expected or payload.get("schema_version") != BROWSER_EVIDENCE_SCHEMA:
        raise SoakError("soak_browser_evidence_invalid")
    counts = {key: payload.get(key) for key in expected - {"schema_version"}}
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts.values()
    ):
        raise SoakError("soak_browser_evidence_invalid")
    if counts["refreshes"] != len(state.room_ids):
        raise SoakError("soak_browser_refresh_count_invalid")
    state.browser = {
        key: value
        for key, value in counts.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def _parse_stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latency_ms(start: object, finish: object) -> int | None:
    left = _parse_stamp(start)
    right = _parse_stamp(finish)
    if left is None or right is None or right < left:
        return None
    return round((right - left).total_seconds() * 1000)


def _attempt_concurrency_peak(database: Path, room_ids: Sequence[str]) -> int:
    placeholders = ",".join("?" for _ in room_ids)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"""select attempt_id, state, provider_phase,
                       transport_started_at, finished_at
                from room_observation_attempts
                where conversation_id in ({placeholders})""",
            tuple(room_ids),
        ).fetchall()
    events: list[tuple[datetime, int]] = []
    for row in rows:
        started = _parse_stamp(row["transport_started_at"])
        finished = _parse_stamp(row["finished_at"])
        if started is None:
            if row["provider_phase"] == "not_started" and row["state"] in {
                "failed",
                "expired",
                "cancelled",
            }:
                continue
            raise SoakError("soak_attempt_interval_incomplete")
        if finished is None or finished < started:
            raise SoakError("soak_attempt_interval_incomplete")
        events.append((started, 1))
        events.append((finished, -1))
    active = 0
    maximum = 0
    # At equal timestamps, count the starting interval before closing the prior one.
    for _stamp, delta in sorted(events, key=lambda item: (item[0], 0 if item[1] > 0 else 1)):
        active += delta
        maximum = max(maximum, active)
        if active < 0:
            raise SoakError("soak_attempt_interval_invalid")
    if active != 0 or not events:
        raise SoakError("soak_attempt_interval_incomplete")
    return maximum


def _duplicate_outcome_invariant_count(
    conn: sqlite3.Connection,
    room_ids: Sequence[str],
) -> int:
    placeholders = ",".join("?" for _ in room_ids)
    row = conn.execute(
        f"""select coalesce(sum(outcome_count - 1), 0) from (
                select b.conversation_id, b.participant_id, b.correlation_id, b.phase,
                       count(*) outcome_count
                from room_observation_attempts t
                join room_observation_batches b on b.batch_id = t.batch_id
                where t.conversation_id in ({placeholders}) and t.state = 'completed'
                group by b.conversation_id, b.participant_id, b.correlation_id, b.phase
                having count(*) > 1
            )""",
        tuple(room_ids),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _identity_invariant_count(
    conn: sqlite3.Connection,
    room_ids: Sequence[str],
) -> int:
    placeholders = ",".join("?" for _ in room_ids)
    params = tuple(room_ids)
    row = conn.execute(
        f"""select count(*) from (
                select t.attempt_id authority_ref
                from room_observation_attempts t
                left join room_observations o on o.observation_id = t.observation_id
                left join participants p on p.participant_id = t.participant_id
                left join room_observation_batches b on b.batch_id = t.batch_id
                left join room_observation_batch_members bm
                       on bm.batch_id = t.batch_id
                      and bm.observation_id = t.observation_id
                where t.conversation_id in ({placeholders})
                  and (o.observation_id is null or p.participant_id is null
                       or b.batch_id is null or bm.observation_id is null
                       or t.conversation_id <> o.conversation_id
                       or t.participant_id <> o.participant_id
                       or p.conversation_id <> t.conversation_id
                       or b.conversation_id <> t.conversation_id
                       or b.participant_id <> t.participant_id
                       or b.primary_observation_id <> t.observation_id)
                union all
                select b.batch_id authority_ref
                from room_observation_batches b
                left join room_observations primary_o
                       on primary_o.observation_id = b.primary_observation_id
                left join participants p on p.participant_id = b.participant_id
                where b.conversation_id in ({placeholders})
                  and (primary_o.observation_id is null or p.participant_id is null
                       or primary_o.conversation_id <> b.conversation_id
                       or primary_o.participant_id <> b.participant_id
                       or p.conversation_id <> b.conversation_id
                       or b.member_count <> (select count(*)
                                             from room_observation_batch_members members
                                             where members.batch_id = b.batch_id))
                union all
                select bm.observation_id authority_ref
                from room_observation_batch_members bm
                left join room_observation_batches b on b.batch_id = bm.batch_id
                left join room_observations o on o.observation_id = bm.observation_id
                left join room_activities a on a.activity_id = bm.activity_id
                where b.conversation_id in ({placeholders})
                  and (o.observation_id is null or a.activity_id is null
                       or o.conversation_id <> b.conversation_id
                       or o.participant_id <> b.participant_id
                       or o.activity_id <> bm.activity_id
                       or a.conversation_id <> b.conversation_id
                       or a.correlation_id <> b.correlation_id
                       or a.seq <> bm.activity_seq)
                union all
                select a.activity_id authority_ref
                from room_activities a
                left join participants p on p.participant_id = a.actor_participant_id
                where a.conversation_id in ({placeholders})
                  and a.actor_kind = 'participant'
                  and (p.participant_id is null
                       or p.conversation_id <> a.conversation_id)
            )""",
        (*params, *params, *params, *params),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _causality_invariant_count(
    conn: sqlite3.Connection,
    room_ids: Sequence[str],
) -> int:
    placeholders = ",".join("?" for _ in room_ids)
    params = tuple(room_ids)
    row = conn.execute(
        f"""select count(*) from (
                select child.activity_id authority_ref
                from room_activities child
                left join room_activities parent on parent.activity_id = child.causation_id
                where child.conversation_id in ({placeholders})
                  and child.actor_kind = 'participant'
                  and (parent.activity_id is null
                       or parent.conversation_id <> child.conversation_id
                       or parent.correlation_id <> child.correlation_id)
                union all
                select o.observation_id authority_ref
                from room_observations o
                left join room_activities source on source.activity_id = o.activity_id
                where o.conversation_id in ({placeholders})
                  and (source.activity_id is null
                       or source.conversation_id <> o.conversation_id)
                union all
                select o.observation_id authority_ref
                from room_observation_attempts t
                join room_observations o on o.observation_id = t.observation_id
                left join room_activities source on source.activity_id = o.activity_id
                left join room_activities produced
                       on produced.activity_id = o.produced_activity_id
                left join messages message on message.id = o.produced_message_id
                where t.conversation_id in ({placeholders}) and t.state = 'completed'
                  and (
                       (o.outcome_type in ('respond','handoff')
                        and (produced.activity_id is null or message.id is null))
                       or (o.outcome_type = 'propose' and produced.activity_id is null)
                       or (o.outcome_type in ('noop','defer')
                           and (o.produced_activity_id is not null
                                or o.produced_message_id is not null))
                       or (produced.activity_id is not null
                           and (source.activity_id is null
                                or produced.conversation_id <> o.conversation_id
                                or produced.correlation_id <> source.correlation_id
                                or produced.actor_participant_id <> o.participant_id))
                       or (message.id is not null
                           and (message.conversation_id <> o.conversation_id
                                or produced.materialized_message_id <> message.id))
                       or (o.produced_message_id is null
                           and produced.materialized_message_id is not null)
                  )
            )""",
        (*params, *params, *params),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _database_evidence(
    database: Path,
    room_ids: Sequence[str],
    *,
    state: _LiveState,
    provider_orphans: int,
) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in room_ids)
    params = tuple(room_ids)
    latency: dict[str, list[dict[str, int]]] = {
        "post_to_claim": [],
        "post_to_outcome": [],
        "post_to_settled": [],
    }
    with _connect_readonly(database) as conn:

        def scalar(query: str, values: Sequence[object] = params) -> int:
            return int(conn.execute(query, values).fetchone()[0])

        posts = scalar(
            f"select count(*) from room_activities where conversation_id in ({placeholders}) "
            "and actor_kind = 'human'"
        )
        correlations = scalar(
            f"select count(distinct correlation_id) from room_activities "
            f"where conversation_id in ({placeholders}) and actor_kind = 'human'"
        )
        attempts = scalar(
            "select count(*) from room_observation_attempts "
            f"where conversation_id in ({placeholders})"
        )
        outcomes = scalar(
            "select count(*) from room_observation_attempts "
            f"where conversation_id in ({placeholders}) and state = 'completed'"
        )
        root_attempts = scalar(
            f"select count(*) from room_observation_attempts t "
            "join room_observation_batches b on b.batch_id = t.batch_id "
            f"where t.conversation_id in ({placeholders}) and b.phase = 'root'"
        )
        peer_attempts = scalar(
            f"select count(*) from room_observation_attempts t "
            "join room_observation_batches b on b.batch_id = t.batch_id "
            f"where t.conversation_id in ({placeholders}) and b.phase = 'peer'"
        )
        respond = scalar(
            "select count(*) from room_observation_attempts t "
            "join room_observations o on o.observation_id = t.observation_id "
            f"where t.conversation_id in ({placeholders}) and t.state = 'completed' "
            "and o.outcome_type = 'respond'"
        )
        noop = scalar(
            "select count(*) from room_observation_attempts t "
            "join room_observations o on o.observation_id = t.observation_id "
            f"where t.conversation_id in ({placeholders}) and t.state = 'completed' "
            "and o.outcome_type = 'noop'"
        )
        other_outcomes = scalar(
            "select count(*) from room_observation_attempts t "
            "join room_observations o on o.observation_id = t.observation_id "
            f"where t.conversation_id in ({placeholders}) and t.state = 'completed' "
            "and o.outcome_type not in ('respond','noop')"
        )
        skill_decisions = scalar(
            "select count(*) from room_attempt_skill_decisions d "
            "join room_observation_attempts t on t.attempt_id = d.attempt_id "
            f"where t.conversation_id in ({placeholders})"
        )
        roots = conn.execute(
            f"""select a.conversation_id, a.correlation_id, a.created_at,
                       min(t.claimed_at) claimed_at,
                       min(o.completed_at) first_outcome_at,
                       max(o.completed_at) settled_at,
                       sum(case when o.status <> 'completed' and p.status = 'active'
                                then 1 else 0 end)
                           unresolved
                from room_activities a
                join room_observations o on o.conversation_id = a.conversation_id
                join room_activities source on source.activity_id = o.activity_id
                                     and source.correlation_id = a.correlation_id
                join participants p on p.participant_id = o.participant_id
                left join room_observation_attempts t on t.observation_id = o.observation_id
                where a.conversation_id in ({placeholders}) and a.actor_kind = 'human'
                group by a.conversation_id, a.correlation_id, a.created_at""",
            params,
        ).fetchall()
        root_by_key = {
            (str(row["conversation_id"]), str(row["correlation_id"])): row for row in roots
        }
        correlation_ids = _correlation_ids(database, state.correlations)
        chronology = sorted(
            (
                item.posted_monotonic,
                correlation_ids.get(item.activity_id, ""),
                item.conversation_id,
            )
            for item in state.correlations
        )
        settled = 0
        for _posted, correlation_id, conversation_id in chronology:
            row = root_by_key.get((conversation_id, correlation_id))
            if row is None:
                continue
            claim = _latency_ms(row["created_at"], row["claimed_at"])
            outcome = _latency_ms(row["created_at"], row["first_outcome_at"])
            settled_latency = _latency_ms(row["created_at"], row["settled_at"])
            if claim is not None:
                latency["post_to_claim"].append(
                    {
                        "ordinal": len(latency["post_to_claim"]) + 1,
                        "latency_ms": claim,
                    }
                )
            if outcome is not None:
                latency["post_to_outcome"].append(
                    {
                        "ordinal": len(latency["post_to_outcome"]) + 1,
                        "latency_ms": outcome,
                    }
                )
            if int(row["unresolved"] or 0) == 0 and settled_latency is not None:
                settled += 1
                latency["post_to_settled"].append(
                    {
                        "ordinal": len(latency["post_to_settled"]) + 1,
                        "latency_ms": settled_latency,
                    }
                )
        duplicate = _duplicate_outcome_invariant_count(conn, room_ids)
        cross_identity = _identity_invariant_count(conn, room_ids)
        cross_causality = _causality_invariant_count(conn, room_ids)
        live_leases = scalar(
            f"select count(*) from room_observations where conversation_id in ({placeholders}) "
            "and status = 'claimed'"
        )
        cleanup_pending = scalar(
            "select count(*) from room_observation_attempts "
            f"where conversation_id in ({placeholders}) "
            "and provider_phase in ('ensure_started','cleanup_pending')"
        )
        recovery_pending = scalar(
            "select count(*) from room_observation_attempts "
            f"where conversation_id in ({placeholders}) "
            "and recovery_state in ('fenced','cleanup_pending')"
        )
        exhausted = scalar(
            f"select count(*) from room_observations where conversation_id in ({placeholders}) "
            "and control_state = 'exhausted'"
        )
        incomplete_attempts = scalar(
            "select count(*) from room_observation_attempts "
            f"where conversation_id in ({placeholders}) "
            "and state not in ('completed','failed','expired','cancelled')"
        )
        integrity_rows = conn.execute("pragma integrity_check").fetchall()
        integrity = "ok" if [str(row[0]) for row in integrity_rows] == ["ok"] else "failed"
    return {
        "schema_version": LIVE_EVIDENCE_SCHEMA,
        "profile_id": "",  # populated by the caller after profile selection
        "configuration": {},
        "counts": {
            "human_posts": posts,
            "correlations": correlations,
            "attempts": attempts,
            "outcomes": outcomes,
            "root_attempts": root_attempts,
            "peer_attempts": peer_attempts,
            "respond": respond,
            "noop": noop,
            "other_outcomes": other_outcomes,
            "skill_decisions": skill_decisions,
            "settled_correlations": settled,
        },
        "concurrency": {
            "max_active_deliveries": state.max_active_deliveries,
            "rooms_first_claimed": len(state.rooms_first_claimed),
            "attempts_until_all_rooms_first_claimed": state.attempts_until_all_rooms_first_claimed,
            "max_active_posts": state.max_active_posts,
            "queued_correlations_before_host": state.queued_correlations_before_host,
        },
        "latency_samples_ms": latency,
        "violations": {
            "duplicate_outcome": duplicate,
            "cross_room_identity": cross_identity,
            "cross_room_causality": cross_causality,
            "unsettled_correlation": max(0, correlations - settled),
            "provider_orphans": provider_orphans,
        },
        "residual": {
            "live_leases": live_leases,
            "cleanup_pending": cleanup_pending,
            "recovery_pending": recovery_pending,
            "exhausted": exhausted,
            "incomplete_attempts": incomplete_attempts,
        },
        "storage": {
            "database_bytes": database.stat().st_size,
            "wal_bytes": (
                database.with_name(f"{database.name}-wal").stat().st_size
                if database.with_name(f"{database.name}-wal").exists()
                else 0
            ),
            "sqlite_integrity": integrity,
        },
    }


def _provider_orphan_count(
    runtime_root: Path,
    room_ids: Sequence[str],
    runtime_provider_pids: Callable[[Path], tuple[int, ...]],
) -> int:
    live = set(runtime_provider_pids(runtime_root))
    try:
        payload = json.loads((runtime_root / "god_sessions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return len(live)
    raw_sessions = payload.get("sessions") if isinstance(payload, Mapping) else []
    sessions = raw_sessions if isinstance(raw_sessions, list) else []
    registered = {
        int(item["pid"])
        for item in sessions
        if isinstance(item, Mapping)
        and item.get("conversation_id") in room_ids
        and isinstance(item.get("pid"), int)
        and not isinstance(item.get("pid"), bool)
    }
    return sum(
        pid not in registered and not _process_descends_from(pid, registered) for pid in live
    )


def _process_descends_from(pid: int, ancestors: set[int]) -> bool:
    seen: set[int] = set()
    current = pid
    while current > 1 and current not in seen:
        seen.add(current)
        try:
            tail = (
                Path(f"/proc/{current}/stat")
                .read_text(encoding="utf-8")
                .rsplit(
                    ") ",
                    1,
                )[1]
            )
            parent = int(tail.split()[1])
        except (OSError, IndexError, ValueError):
            return False
        if parent in ancestors:
            return True
        current = parent
    return False


def _memory_evidence(
    database: Path,
    room_ids: Sequence[str],
    *,
    enabled: bool,
    restart_count: int,
    proof: _MemoryFaultProof | None = None,
) -> dict[str, int | bool]:
    if not enabled:
        return {
            "enabled": False,
            "restart_count": 0,
            "outbox_delivered": 0,
            "outbox_pending": 0,
            "outbox_conflict": 0,
            "recall_receipts": 0,
            "recall_source_refs": 0,
        }
    if proof is None or not proof.backlog_observed or not proof.fault_window_activity_ids:
        raise SoakError("soak_memory_recovery_proof_incomplete")
    placeholders = ",".join("?" for _ in room_ids)
    params = tuple(room_ids)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"""select state, count(*) count from room_memory_outbox
                where conversation_id in ({placeholders}) group by state""",
            params,
        ).fetchall()
        states = {str(row["state"]): int(row["count"]) for row in rows}
        receipts = conn.execute(
            f"""select r.conversation_id, r.status, r.source_activity_ids_json,
                       source.seq source_seq
                from room_memory_attempt_receipts r
                join room_observation_attempts t on t.attempt_id = r.attempt_id
                join room_observations o on o.observation_id = t.observation_id
                join room_activities source on source.activity_id = o.activity_id
                where r.conversation_id in ({placeholders})""",
            params,
        ).fetchall()
        fault_ids = tuple(sorted(proof.fault_window_activity_ids))
        fault_placeholders = ",".join("?" for _ in fault_ids)
        delivered_fault_ids = {
            str(row["activity_id"])
            for row in conn.execute(
                f"""select activity_id from room_memory_outbox
                    where activity_id in ({fault_placeholders}) and state = 'delivered'""",
                fault_ids,
            ).fetchall()
        }
    if delivered_fault_ids != proof.fault_window_activity_ids:
        raise SoakError("soak_memory_replay_incomplete")
    verified_receipts = 0
    source_refs = 0
    for row in receipts:
        conversation_id = str(row["conversation_id"])
        if row["status"] != "ok" or int(row["source_seq"]) <= proof.cutoff_by_room.get(
            conversation_id, 0
        ):
            continue
        try:
            values = json.loads(str(row["source_activity_ids_json"]))
        except json.JSONDecodeError as exc:
            raise SoakError("soak_memory_source_proof_invalid") from exc
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise SoakError("soak_memory_source_proof_invalid")
        unique_refs = tuple(dict.fromkeys(values))
        ref_placeholders = ",".join("?" for _ in unique_refs)
        with _connect_readonly(database) as conn:
            source_rows = conn.execute(
                f"""select activity_id, conversation_id from room_activities
                    where activity_id in ({ref_placeholders})""",
                unique_refs,
            ).fetchall()
        source_rooms = {
            str(source["activity_id"]): str(source["conversation_id"]) for source in source_rows
        }
        if set(source_rooms) != set(unique_refs) or any(
            source_room != conversation_id for source_room in source_rooms.values()
        ):
            raise SoakError("soak_memory_source_proof_invalid")
        if not any(value in proof.wave0_activity_ids for value in unique_refs):
            continue
        verified_receipts += 1
        source_refs += len(unique_refs)
    if verified_receipts == 0 or source_refs == 0:
        raise SoakError("soak_memory_recall_proof_incomplete")
    return {
        "enabled": True,
        "restart_count": max(0, restart_count),
        "outbox_delivered": states.get("delivered", 0),
        "outbox_pending": sum(states.get(key, 0) for key in ("pending", "claimed", "failed")),
        "outbox_conflict": states.get("conflict", 0),
        "recall_receipts": verified_receipts,
        "recall_source_refs": source_refs,
    }


def _wait_for_memory_evidence(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> None:
    deadline = deps.monotonic() + min(120.0, config.settle_timeout_s)
    while deps.monotonic() < deadline:
        try:
            evidence = _memory_evidence(
                runtime_root / "chat.db",
                state.room_ids,
                enabled=True,
                restart_count=state.memory_restart_count,
                proof=state.memory_fault_proof,
            )
        except SoakError as exc:
            if exc.code not in {
                "soak_memory_replay_incomplete",
                "soak_memory_recall_proof_incomplete",
            }:
                raise
        else:
            if (
                int(evidence["outbox_delivered"]) > 0
                and int(evidence["outbox_pending"]) == 0
                and int(evidence["outbox_conflict"]) == 0
            ):
                state.verified_memory_evidence = evidence
                return
        _sample_runtime(config, deps, state, runtime_root, env)
        deps.sleep(0.5)
    raise SoakError("soak_memory_recovery_proof_timeout")


def _resource_evidence(
    samples: Sequence[ProcessSample],
    *,
    warmup_cutoff_ms: int | None,
) -> dict[str, int]:
    if warmup_cutoff_ms is None:
        raise SoakError("soak_resource_warmup_marker_missing")
    warm = [item for item in samples if item.offset_ms <= warmup_cutoff_ms]
    steady = [item for item in samples if item.offset_ms > warmup_cutoff_ms]
    if not warm or not steady:
        raise SoakError("soak_resource_sampling_window_incomplete")
    return {
        "rss_warmup_median_bytes": round(statistics.median(item.rss_bytes for item in warm)),
        "rss_steady_state_max_bytes": max(item.rss_bytes for item in steady),
        "fd_warmup": round(statistics.median(item.fd_count for item in warm)),
        "fd_steady_state_max": max(item.fd_count for item in steady),
        "process_count_max": max(item.process_count for item in samples),
    }


def _run_live(
    config: SoakConfig,
    deps: SoakDependencies,
    spec: LiveProfileSpec,
    runtime_root: Path,
    artifact_dir: Path,
    env: Mapping[str, str],
    before: RepositorySnapshot,
    state: _LiveState,
) -> Mapping[str, Any]:
    started = deps.monotonic()
    state.run_started_monotonic = started
    _start_workroom(config, deps, state, runtime_root, env)
    _create_rooms(spec, deps, state)
    offsets = [
        (spec.minimum_duration_s * index / (spec.wave_count - 1)) if spec.wave_count > 1 else 0.0
        for index in range(spec.wave_count)
    ]
    memory_event: _PendingChaosEvent | None = None
    for wave, offset in enumerate(offsets):
        _wait_for_wave_offset(
            config,
            deps,
            state,
            runtime_root,
            env,
            run_started_at=started,
            offset_s=offset,
        )
        if wave == 0:
            paused_runner = _pause_runner(config, deps, runtime_root, env)
            try:
                correlations = _post_wave(spec, deps, state, wave=wave)
                state.queued_correlations_before_host = _pending_correlation_count(
                    runtime_root / "chat.db",
                    state.room_ids[0],
                )
            finally:
                _resume_runner(deps, paused_runner)
        elif wave == 1 and spec.memory_recovery:
            proof = state.memory_fault_proof
            if proof is None:
                raise SoakError("soak_memory_recovery_proof_incomplete")
            paused_runner = _pause_runner(config, deps, runtime_root, env)
            try:
                _assert_memory_fault_active(config, deps, runtime_root, env, proof)
                correlations = _post_wave(spec, deps, state, wave=wave)
                _record_memory_fault_backlog(
                    runtime_root / "chat.db",
                    proof,
                    correlations,
                )
                memory_event = _wait_memoryos_recovery(
                    config,
                    deps,
                    state,
                    runtime_root,
                    env,
                    proof,
                )
            finally:
                _resume_runner(deps, paused_runner)
        else:
            correlations = _post_wave(spec, deps, state, wave=wave)
        wave_event: _PendingChaosEvent | None = None
        if wave == 0 and not spec.memory_recovery:
            wave_event = _kill_one_provider(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
        if wave == 1 and not spec.memory_recovery:
            wave_event = _kill_runner_and_wait_recovery(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
        _wait_wave_settled(config, deps, state, runtime_root, env, correlations)
        if wave_event is not None:
            _record_chaos(
                state,
                event=wave_event,
                recovery_wave_settled=True,
            )
        if wave == 1 and memory_event is not None:
            _record_chaos(
                state,
                event=memory_event,
                recovery_wave_settled=True,
            )
        if wave == 0:
            _sample_runtime(
                config,
                deps,
                state,
                runtime_root,
                env,
                force_resource=True,
            )
            if not state.process_samples:
                raise SoakError("soak_resource_warmup_marker_missing")
            state.warmup_cutoff_ms = state.process_samples[-1].offset_ms
            if spec.memory_recovery:
                state.memory_fault_proof = _begin_memoryos_fault(
                    config,
                    deps,
                    state,
                    runtime_root,
                    env,
                    run_started_at=started,
                )
    if spec.minimum_duration_s and deps.monotonic() - started < spec.minimum_duration_s:
        # The final wave is scheduled at the boundary; this branch only absorbs clock
        # granularity while continuing to sample the live system.
        _wait_for_wave_offset(
            config,
            deps,
            state,
            runtime_root,
            env,
            run_started_at=started,
            offset_s=spec.minimum_duration_s,
        )
    if spec.memory_recovery:
        _wait_for_memory_evidence(config, deps, state, runtime_root, env)
    _verify_browser(config, deps, state, artifact_dir, env)
    _sample_runtime(
        config,
        deps,
        state,
        runtime_root,
        env,
        force_resource=True,
    )
    if not state.host_delivery_evidence_seen:
        raise SoakError("soak_host_active_delivery_evidence_missing")
    db_active_peak = _attempt_concurrency_peak(
        runtime_root / "chat.db",
        state.room_ids,
    )
    state.max_active_deliveries = max(state.max_active_deliveries, db_active_peak)
    after = deps.repository_snapshot(config.repo_root)
    evidence = _database_evidence(
        runtime_root / "chat.db",
        state.room_ids,
        state=state,
        provider_orphans=_provider_orphan_count(
            runtime_root,
            state.room_ids,
            deps.runtime_provider_pids,
        ),
    )
    evidence["profile_id"] = spec.profile_id
    evidence["configuration"] = {
        "room_count": spec.room_count,
        "agents_per_room": spec.agents_per_room,
        "human_turns_per_room": spec.human_turns_per_room,
        "max_concurrent_provider_deliveries": MAX_ACTIVE_PROVIDER_DELIVERIES,
    }
    evidence["resources"] = _resource_evidence(
        state.process_samples,
        warmup_cutoff_ms=state.warmup_cutoff_ms,
    )
    evidence["chaos_events"] = state.chaos_events
    evidence["browser"] = state.browser
    evidence["worktree"] = {
        "before_digest": _snapshot_digest(before),
        "after_digest": _snapshot_digest(after),
    }
    evidence["provider_cost_confirmed"] = bool(config.confirm_provider_cost)
    evidence["monotonic_elapsed_ms"] = max(
        0,
        round((deps.monotonic() - started) * 1000),
    )
    evidence["memory"] = (
        state.verified_memory_evidence
        if spec.memory_recovery
        else _memory_evidence(
            runtime_root / "chat.db",
            state.room_ids,
            enabled=False,
            restart_count=0,
        )
    )
    if evidence["memory"] is None:
        raise SoakError("soak_memory_recovery_proof_incomplete")
    if (
        after.head != before.head
        or not after.clean
        or after.content_digest != before.content_digest
        or after.worktree_inventory_digest != before.worktree_inventory_digest
    ):
        raise SoakError("soak_worktree_changed")
    return evidence


def _snapshot_digest(snapshot: RepositorySnapshot) -> str:
    canonical = "\0".join(
        (
            snapshot.head,
            snapshot.content_digest,
            snapshot.worktree_inventory_digest,
        )
    )
    return f"sha256:{hashlib.sha256(canonical.encode('ascii')).hexdigest()}"


def _stop_process(process: ManagedProcess | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5.0)
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2.0)
        except (OSError, TimeoutError, subprocess.TimeoutExpired):
            pass


def _cleanup_live(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> bool:
    result = deps.run(
        (
            "uv",
            "run",
            "xmuse-workroom",
            "stop",
            "--root",
            str(runtime_root),
            "--timeout-s",
            "20",
        ),
        cwd=config.repo_root,
        env=env,
        timeout_s=35.0,
    )
    _stop_process(state.manager)
    if result.returncode != 0:
        return False
    deadline = deps.monotonic() + CLEANUP_PROVIDER_TIMEOUT_S
    inventory_clear = False
    while deps.monotonic() < deadline:
        counts = deps.runtime_service_counts(runtime_root)
        if (
            not deps.provider_pids(runtime_root)
            and not deps.runtime_provider_pids(runtime_root)
            and counts.get("codex", 0) == 0
            and counts.get("room_runner", 0) == 0
            and counts.get("room_mcp", 0) == 0
        ):
            inventory_clear = True
            break
        deps.sleep(0.1)
    if not inventory_clear:
        return False
    try:
        status = _workroom_status(config, deps, runtime_root, env)
    except SoakError:
        return False
    services = status.get("services")
    return not (
        isinstance(services, list)
        and any(isinstance(item, Mapping) and item.get("live") is True for item in services)
    )


def _cli_error(code: str, *, blocked: bool) -> dict[str, str]:
    return {
        "schema_version": CLI_ERROR_SCHEMA,
        "status": "blocked" if blocked else "failed",
        "reason_code": code,
        "proof_boundary": CLI_ERROR_PROOF_BOUNDARY,
    }


def _write_cli_error(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_result_strings(payload: object, forbidden: Sequence[str]) -> bool:
    if isinstance(payload, Mapping):
        return all(
            isinstance(key, str)
            and "token" not in key.lower()
            and "path" not in key.lower()
            and key.lower() != "pid"
            and _safe_result_strings(value, forbidden)
            for key, value in payload.items()
        )
    if isinstance(payload, list | tuple):
        return all(_safe_result_strings(item, forbidden) for item in payload)
    if isinstance(payload, str):
        return not any(item and item in payload for item in forbidden)
    return payload is None or isinstance(payload, bool | int | float)


def run_soak(
    config: SoakConfig,
    *,
    dependencies: SoakDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or SoakDependencies()
    repo_root = config.repo_root.expanduser().resolve()
    config = SoakConfig(**{**config.__dict__, "repo_root": repo_root})
    runtime_created = config.runtime_root is None
    runtime_root = (
        config.runtime_root.expanduser().resolve()
        if config.runtime_root is not None
        else Path(tempfile.mkdtemp(prefix="xmuse-room-soak-runtime-"))
    )
    artifact_dir = Path(tempfile.mkdtemp(prefix="xmuse-room-soak-artifacts-"))
    result_path = (
        config.result_path.expanduser().resolve()
        if config.result_path is not None
        else artifact_dir / "result.json"
    )
    env = _clean_environment()
    state = _LiveState()
    started_at = deps.now()
    profile: Any | None = None
    evidence: Mapping[str, Any] | None = None
    error: tuple[str, bool] | None = None
    cleanup_required = False
    cleanup_ok = True
    try:
        profile = deps.get_profile(config.profile_id)
        before = _preflight(config, deps, runtime_root, result_path)
        if config.profile_id == "ci-sim":
            runtime_root.mkdir(parents=True, exist_ok=True)
            evidence = deps.run_ci_sim(runtime_root=runtime_root)
        else:
            spec = LIVE_PROFILES.get(config.profile_id)
            if spec is None:
                raise SoakError("soak_profile_not_supported", blocked=True)
            cleanup_required = True
            # _run_live owns a private state.  The manager is recovered for cleanup
            # from the manifest by xmuse-workroom stop even if an exception escapes.
            evidence = _run_live(
                config,
                deps,
                spec,
                runtime_root,
                artifact_dir,
                env,
                before,
                state,
            )
    except KeyboardInterrupt:
        error = ("soak_interrupted", False)
    except SoakError as exc:
        error = (exc.code, exc.blocked)
    except Exception:
        error = ("soak_unexpected_failure", False)
    finally:
        if cleanup_required:
            cleanup_ok = _cleanup_live(config, deps, state, runtime_root, env)
            if not cleanup_ok:
                error = ("soak_cleanup_incomplete", False)
    can_write_result = not _is_relative_to(result_path, repo_root)
    if error is not None or profile is None or evidence is None:
        code, blocked = error or ("soak_incomplete_evidence", False)
        result = _cli_error(code, blocked=blocked)
        if can_write_result:
            _write_cli_error(result_path, result)
        if runtime_created and not config.keep_runtime_root and cleanup_ok:
            shutil.rmtree(runtime_root, ignore_errors=True)
        if result_path.parent != artifact_dir:
            shutil.rmtree(artifact_dir, ignore_errors=True)
        return result
    finished_at = deps.now()
    try:
        result = deps.build_result(
            profile=profile,
            evidence=evidence,
            started_at=started_at,
            finished_at=finished_at,
        )
        result = deps.validate_result(result)
        deps.evaluate_result(result)
    except Exception:
        result = _cli_error("soak_result_contract_failed", blocked=False)
        if can_write_result:
            _write_cli_error(result_path, result)
        if runtime_created and not config.keep_runtime_root and cleanup_ok:
            shutil.rmtree(runtime_root, ignore_errors=True)
        if result_path.parent != artifact_dir:
            shutil.rmtree(artifact_dir, ignore_errors=True)
        return result
    forbidden = (str(repo_root), str(runtime_root), str(artifact_dir))
    if not _safe_result_strings(result, forbidden):
        result = _cli_error("soak_result_safety_violation", blocked=False)
        if can_write_result:
            _write_cli_error(result_path, result)
        return result
    result_path.parent.mkdir(parents=True, exist_ok=True)
    deps.write_result(result_path, result)
    if runtime_created and not config.keep_runtime_root:
        shutil.rmtree(runtime_root, ignore_errors=True)
    if result_path.parent != artifact_dir:
        shutil.rmtree(artifact_dir, ignore_errors=True)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile",
        choices=("ci-sim", "live-short", "live-soak", "memory-recovery"),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--root", type=Path, help="fresh isolated XMUSE_ROOT")
    parser.add_argument("--result", type=Path, help="safe result JSON (must be outside repo)")
    parser.add_argument("--memoryos-executable", type=Path)
    parser.add_argument("--confirm-provider-cost", action="store_true")
    parser.add_argument("--keep-root", action="store_true")
    parser.add_argument("--no-build-frontend", action="store_true")
    parser.add_argument("--readiness-timeout-s", type=float, default=120.0)
    parser.add_argument("--settle-timeout-s", type=float, default=1200.0)
    parser.add_argument("--browser-timeout-s", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if min(args.readiness_timeout_s, args.settle_timeout_s, args.browser_timeout_s) <= 0:
        parser.error("timeouts must be positive")
    result = run_soak(
        SoakConfig(
            repo_root=args.repo_root,
            profile_id=args.profile,
            runtime_root=args.root,
            result_path=args.result,
            memoryos_executable=args.memoryos_executable,
            confirm_provider_cost=args.confirm_provider_cost,
            keep_runtime_root=args.keep_root,
            build_frontend=not args.no_build_frontend,
            readiness_timeout_s=args.readiness_timeout_s,
            settle_timeout_s=args.settle_timeout_s,
            browser_timeout_s=args.browser_timeout_s,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    if result.get("schema_version") != CLI_ERROR_SCHEMA:
        passed, _reasons = _default_evaluate_result(result)
        return 0 if passed else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
