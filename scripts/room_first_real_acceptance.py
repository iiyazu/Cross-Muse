#!/usr/bin/env python3
"""Run the production Room-first Workroom acceptance without compatibility paths.

The orchestrator owns the fresh runtime root, production build, managed Workroom
lifecycle, fault injection, Playwright phases, bounded evidence, and cleanup.  Raw
command output is intentionally never copied into the result artifact because it may
contain provider text or local process details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = "room_first_real_acceptance/v2"
EXPECTED_BASELINE_HEAD = "07f44b6837e9f6273217c8c9225636424f0f437b"
FRONTEND_URL = "http://127.0.0.1:3000"
CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat"
REQUIRED_SERVICES = ("frontend", "chat_api", "room_runner", "room_mcp")
PLAYWRIGHT_PHASES = ("conversation", "recover-runner", "recover-mcp", "verify")
_MAX_JSON_BYTES = 1024 * 1024
_SECRET_SCAN_CHUNK_BYTES = 1024 * 1024


class AcceptanceError(RuntimeError):
    """Stable acceptance failure without unsafe command output."""

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
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


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


def _read_process_environment(pid: int) -> Mapping[str, str]:
    try:
        raw = (Path("/proc") / str(pid) / "environ").read_bytes()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        result[key.decode(errors="replace")] = value.decode(errors="replace")
    return result


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def _git_snapshot(repo_root: Path) -> str:
    """Hash all non-ignored changes without exposing their content."""

    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    ).stdout
    digest = hashlib.sha256(diff)
    for raw_name in sorted(item for item in untracked.split(b"\0") if item):
        relative = raw_name.decode("utf-8", errors="surrogateescape")
        path = repo_root / relative
        digest.update(raw_name)
        if path.is_symlink():
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            with path.open("rb") as handle:
                while chunk := handle.read(_SECRET_SCAN_CHUNK_BYTES):
                    digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class AcceptanceDependencies:
    run: Callable[..., CommandResult] = _run_command
    spawn: Callable[..., ManagedProcess] = _spawn_command
    which: Callable[[str], str | None] = shutil.which
    signal_pid: Callable[[int, int], None] = os.kill
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], str] = _utc_now
    read_process_environment: Callable[[int], Mapping[str, str]] = _read_process_environment
    port_available: Callable[[str, int], bool] = _port_available
    git_snapshot: Callable[[Path], str] = _git_snapshot


@dataclass(frozen=True)
class AcceptanceConfig:
    repo_root: Path
    expected_head: str = EXPECTED_BASELINE_HEAD
    runtime_root: Path | None = None
    artifact_dir: Path | None = None
    preflight_only: bool = False
    build_frontend: bool = True
    run_fault_recovery: bool = True
    keep_runtime_root: bool = False
    readiness_timeout_s: float = 120.0
    # The conversation phase deliberately runs three settled four-Agent turns.
    # Keep the outer process timeout above the three independent browser polls.
    phase_timeout_s: float = 2400.0


@dataclass
class _RunState:
    started_at: str
    started_monotonic: float
    gates: list[dict[str, Any]] = field(default_factory=list)
    manager: ManagedProcess | None = None
    token: str | None = None
    baseline_snapshot: str | None = None
    conversation_id: str | None = None
    participant_ids: list[str] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    root_correlation_id: str | None = None
    root_activity_id: str | None = None
    room_status: str | None = None
    durable_outcome_count: int = 0
    skill_evidence_count: int = 0
    console_error_count: int = 0
    page_error_count: int = 0
    initial_runner_boot: str | None = None
    recovered_runner_boot: str | None = None
    initial_mcp_pid: int | None = None
    recovered_mcp_pid: int | None = None


def _gate(
    state: _RunState,
    name: str,
    status: str,
    *,
    started: float,
    deps: AcceptanceDependencies,
    code: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "name": name,
        "status": status,
        "duration_s": round(max(0.0, deps.monotonic() - started), 3),
    }
    if code is not None:
        payload["code"] = code
    state.gates.append(payload)


def _run_checked(
    deps: AcceptanceDependencies,
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
        raise AcceptanceError(code, blocked=blocked)
    return result


def _json_object(raw: str, *, code: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > _MAX_JSON_BYTES:
        raise AcceptanceError(code)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(code) from exc
    if not isinstance(payload, dict):
        raise AcceptanceError(code)
    return payload


def _read_json_file(path: Path, *, code: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AcceptanceError(code) from exc
    return _json_object(raw, code=code)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _workroom_status(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
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
        raise AcceptanceError("workroom_status_unavailable")
    return _json_object(result.stdout, code="workroom_status_invalid")


def _service(status: Mapping[str, Any], name: str) -> dict[str, Any]:
    services = status.get("services")
    if not isinstance(services, list):
        raise AcceptanceError("workroom_status_services_invalid")
    for item in services:
        if isinstance(item, dict) and item.get("service") == name:
            return item
    raise AcceptanceError(f"workroom_service_{name}_missing")


def _wait_for_ready(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    deadline = deps.monotonic() + config.readiness_timeout_s
    last: dict[str, Any] | None = None
    while deps.monotonic() < deadline:
        if state.manager is not None and state.manager.poll() is not None:
            raise AcceptanceError("workroom_manager_exited")
        try:
            last = _workroom_status(config, deps, runtime_root, env)
        except AcceptanceError:
            deps.sleep(0.25)
            continue
        try:
            services_ready = all(
                _service(last, name).get("ready") is True for name in REQUIRED_SERVICES
            )
        except AcceptanceError:
            deps.sleep(0.25)
            continue
        if last.get("state") == "ready" and services_ready:
            return last
        deps.sleep(0.5)
    del last
    raise AcceptanceError("workroom_readiness_timeout", blocked=True)


def _preflight(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> None:
    started = deps.monotonic()
    for command in ("git", "uv", "npm", "node", "codex"):
        if deps.which(command) is None:
            raise AcceptanceError(f"preflight_{command}_not_found", blocked=True)
    head = _run_checked(
        deps,
        ("git", "rev-parse", "HEAD"),
        cwd=config.repo_root,
        env=env,
        timeout_s=10.0,
        code="preflight_head_unavailable",
        blocked=True,
    ).stdout.strip()
    if head != config.expected_head:
        raise AcceptanceError("preflight_head_mismatch", blocked=True)
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise AcceptanceError("preflight_runtime_root_not_empty", blocked=True)
    for host, port, name in (
        ("127.0.0.1", 8201, "chat_api"),
        ("127.0.0.1", 3000, "frontend"),
    ):
        if not deps.port_available(host, port):
            raise AcceptanceError(f"preflight_{name}_port_in_use", blocked=True)
    _run_checked(
        deps,
        ("codex", "login", "status"),
        cwd=config.repo_root,
        env=env,
        timeout_s=20.0,
        code="preflight_codex_auth_unavailable",
        blocked=True,
    )
    _run_checked(
        deps,
        ("npm", "run", "test:e2e:real", "--", "--list"),
        cwd=config.repo_root / "frontend",
        env={**env, "XMUSE_REAL_ACCEPTANCE": "0"},
        timeout_s=60.0,
        code="preflight_playwright_unavailable",
        blocked=True,
    )
    state.baseline_snapshot = deps.git_snapshot(config.repo_root)
    _gate(state, "preflight", "passed", started=started, deps=deps)


def _build_frontend(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    env: Mapping[str, str],
) -> None:
    started = deps.monotonic()
    if config.build_frontend:
        _run_checked(
            deps,
            ("npm", "run", "build"),
            cwd=config.repo_root / "frontend",
            env={
                **env,
                "NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL": CHAT_API_BASE_URL,
            },
            timeout_s=600.0,
            code="production_frontend_build_failed",
            blocked=True,
        )
    standalone = config.repo_root / "frontend" / ".next" / "standalone" / "server.js"
    static = config.repo_root / "frontend" / ".next" / "static"
    if not standalone.is_file() or not static.is_dir():
        raise AcceptanceError("production_frontend_build_missing", blocked=True)
    _gate(state, "production_build", "passed", started=started, deps=deps)


def _start_workroom(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    started = deps.monotonic()
    runtime_root.mkdir(parents=True, exist_ok=True)
    state.manager = deps.spawn(
        (
            "uv",
            "run",
            "xmuse-workroom",
            "start",
            "--root",
            str(runtime_root),
            "--readiness-timeout-s",
            str(config.readiness_timeout_s),
        ),
        cwd=config.repo_root,
        env=env,
    )
    status = _wait_for_ready(config, deps, state, runtime_root, env)
    chat_api = _service(status, "chat_api")
    pid = chat_api.get("pid")
    if not isinstance(pid, int):
        raise AcceptanceError("workroom_chat_api_identity_missing")
    token = deps.read_process_environment(pid).get("XMUSE_OPERATOR_TOKEN", "").strip()
    if not token:
        raise AcceptanceError("workroom_operator_token_missing")
    state.token = token
    runner = _service(status, "room_runner")
    state.initial_runner_boot = _optional_text(runner.get("boot_id"))
    mcp = _service(status, "room_mcp")
    state.initial_mcp_pid = _positive_int(mcp.get("pid"))
    _gate(state, "workroom_start", "passed", started=started, deps=deps)
    return status


def _playwright_environment(
    env: Mapping[str, str],
    *,
    operator_token: str,
    phase: str,
    state_path: Path,
    evidence_path: Path,
    screenshot_path: Path,
    output_dir: Path,
) -> dict[str, str]:
    return {
        **env,
        "XMUSE_REAL_ACCEPTANCE": "1",
        "XMUSE_REAL_PHASE": phase,
        "XMUSE_REAL_OPERATOR_TOKEN_SHA256": hashlib.sha256(
            operator_token.encode("utf-8")
        ).hexdigest(),
        "XMUSE_REAL_OPERATOR_TOKEN_LENGTH": str(len(operator_token)),
        "XMUSE_REAL_FRONTEND_URL": FRONTEND_URL,
        "XMUSE_REAL_CHAT_API_BASE_URL": CHAT_API_BASE_URL,
        "XMUSE_REAL_STATE_PATH": str(state_path),
        "XMUSE_REAL_EVIDENCE_PATH": str(evidence_path),
        "XMUSE_REAL_SCREENSHOT_PATH": str(screenshot_path),
        "XMUSE_REAL_OUTPUT_DIR": str(output_dir),
    }


def _run_playwright_phase(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    env: Mapping[str, str],
    *,
    phase: str,
    state_path: Path,
    evidence_path: Path,
    screenshot_path: Path,
    output_dir: Path,
) -> None:
    if phase not in PLAYWRIGHT_PHASES:
        raise AcceptanceError("playwright_phase_invalid")
    if not state.token:
        raise AcceptanceError("workroom_operator_token_missing")
    started = deps.monotonic()
    _run_checked(
        deps,
        ("npm", "run", "test:e2e:real"),
        cwd=config.repo_root / "frontend",
        env=_playwright_environment(
            env,
            operator_token=state.token,
            phase=phase,
            state_path=state_path,
            evidence_path=evidence_path,
            screenshot_path=screenshot_path,
            output_dir=output_dir,
        ),
        timeout_s=config.phase_timeout_s,
        code=f"playwright_{phase.replace('-', '_')}_failed",
    )
    _gate(state, f"playwright_{phase}", "passed", started=started, deps=deps)


def _load_browser_state(path: Path, state: _RunState) -> None:
    payload = _read_json_file(path, code="playwright_state_invalid")
    if payload.get("schema_version") != "room_first_real_browser_state/v2":
        raise AcceptanceError("playwright_state_schema_invalid")
    conversation_id = _required_text(payload.get("conversation_id"))
    participants = payload.get("participant_ids")
    if not isinstance(participants, list) or len(participants) != 4:
        raise AcceptanceError("playwright_participants_invalid")
    participant_ids = [_required_text(item) for item in participants]
    if len(set(participant_ids)) != 4:
        raise AcceptanceError("playwright_participants_invalid")
    turns = payload.get("turns")
    if not isinstance(turns, list) or len(turns) != 3:
        raise AcceptanceError("playwright_turns_invalid")
    safe_turns: list[dict[str, Any]] = []
    expected_kinds = ("normal", "mention", "handoff")
    for index, item in enumerate(turns):
        if not isinstance(item, dict) or item.get("kind") != expected_kinds[index]:
            raise AcceptanceError("playwright_turns_invalid")
        try:
            safe_turns.append(
                {
                    "kind": expected_kinds[index],
                    "correlation_id": _required_text(item.get("correlation_id")),
                    "root_activity_id": _required_text(item.get("root_activity_id")),
                    "observation_count": _bounded_nonnegative_int(item.get("observation_count")),
                    "attempt_count": _bounded_nonnegative_int(item.get("attempt_count")),
                    "skill_decision_count": _bounded_nonnegative_int(
                        item.get("skill_decision_count")
                    ),
                    "logical_batch_count": _bounded_nonnegative_int(
                        item.get("logical_batch_count")
                    ),
                    "infrastructure_retry_count": _bounded_nonnegative_int(
                        item.get("infrastructure_retry_count")
                    ),
                    "expected_mention_handle": _optional_text(item.get("expected_mention_handle")),
                }
            )
        except (TypeError, ValueError) as exc:
            raise AcceptanceError("playwright_turns_invalid") from exc
    state.conversation_id = conversation_id
    state.participant_ids = participant_ids
    state.turns = safe_turns
    state.root_correlation_id = safe_turns[-1]["correlation_id"]
    state.root_activity_id = safe_turns[-1]["root_activity_id"]


def _inject_fault(
    deps: AcceptanceDependencies,
    status: Mapping[str, Any],
    *,
    service_name: str,
) -> int:
    service = _service(status, service_name)
    pid = _positive_int(service.get("pid"))
    if pid is None or service.get("live") is not True:
        raise AcceptanceError(f"{service_name}_fault_target_unavailable")
    try:
        # SIGSTOP keeps the exact process identity observable until guarded recovery
        # fences and terminates it. This avoids racing the managed dead-process reconcile.
        deps.signal_pid(pid, signal.SIGSTOP)
    except OSError as exc:
        raise AcceptanceError(f"{service_name}_fault_injection_failed") from exc
    return pid


def _validate_recovered_service(
    status: Mapping[str, Any],
    *,
    service_name: str,
    prior_pid: int | None = None,
    prior_boot: str | None = None,
) -> tuple[int | None, str | None]:
    service = _service(status, service_name)
    if service.get("ready") is not True:
        raise AcceptanceError(f"{service_name}_not_recovered")
    pid = _positive_int(service.get("pid"))
    boot = _optional_text(service.get("boot_id"))
    if prior_pid is not None and pid == prior_pid:
        raise AcceptanceError(f"{service_name}_identity_not_replaced")
    if prior_boot is not None and boot == prior_boot:
        raise AcceptanceError(f"{service_name}_boot_not_replaced")
    return pid, boot


def _validate_browser_evidence(path: Path, *, expect_faults: bool) -> dict[str, Any]:
    payload = _read_json_file(path, code="playwright_evidence_invalid")
    if payload.get("schema_version") != "room_first_real_browser_evidence/v2":
        raise AcceptanceError("playwright_evidence_schema_invalid")
    phases = payload.get("phases")
    if not isinstance(phases, dict):
        raise AcceptanceError("playwright_evidence_phases_invalid")
    required = {"conversation", "verify"}
    if expect_faults:
        required.update({"recover-runner", "recover-mcp"})
    if any(not isinstance(phases.get(name), dict) for name in required):
        raise AcceptanceError("playwright_evidence_incomplete")
    if any(phases[name].get("status") != "passed" for name in required):
        raise AcceptanceError("playwright_evidence_failed")
    if int(payload.get("console_error_count") or 0) != 0:
        raise AcceptanceError("playwright_console_errors")
    if int(payload.get("page_error_count") or 0) != 0:
        raise AcceptanceError("playwright_page_errors")
    verify = phases["verify"]
    if (
        verify.get("room_status") != "settled"
        or int(verify.get("participant_count") or 0) != 4
        or int(verify.get("turn_count") or 0) != 3
        or int(verify.get("near_duplicate_pair_count") or 0) != 0
        or int(verify.get("batch_evidence_count") or 0) < 12
    ):
        raise AcceptanceError("playwright_evidence_structural_invalid")
    return payload


def _file_contains(path: Path, needle: bytes) -> bool:
    try:
        with path.open("rb") as handle:
            overlap = b""
            while chunk := handle.read(_SECRET_SCAN_CHUNK_BYTES):
                block = overlap + chunk
                if needle in block:
                    return True
                overlap = block[-max(0, len(needle) - 1) :]
    except (OSError, PermissionError):
        return False
    return False


def _tree_contains_secret(path: Path, secret: str) -> bool:
    if not secret or not path.exists():
        return False
    needle = secret.encode("utf-8")
    candidates = [path] if path.is_file() else (item for item in path.rglob("*") if item.is_file())
    return any(_file_contains(candidate, needle) for candidate in candidates)


def _scan_operator_token(
    config: AcceptanceConfig,
    state: _RunState,
    runtime_root: Path,
    artifact_dir: Path,
) -> None:
    if not state.token:
        raise AcceptanceError("operator_token_scan_unavailable")
    for path in (
        config.repo_root / "frontend" / ".next",
        runtime_root / "logs",
        artifact_dir,
    ):
        if _tree_contains_secret(path, state.token):
            raise AcceptanceError("operator_token_leaked")


def _stop_manager(manager: ManagedProcess | None) -> None:
    if manager is None or manager.poll() is not None:
        return
    try:
        manager.terminate()
        manager.wait(timeout=5.0)
    except (OSError, subprocess.TimeoutExpired, TimeoutError):
        try:
            manager.kill()
            manager.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired, TimeoutError):
            pass


def _cleanup(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> tuple[bool, str | None]:
    started = deps.monotonic()
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
        timeout_s=30.0,
    )
    _stop_manager(state.manager)
    code: str | None = None
    ok = result.returncode == 0
    try:
        status = _workroom_status(config, deps, runtime_root, env)
        services = status.get("services")
        if isinstance(services, list) and any(
            isinstance(item, dict) and item.get("live") is True for item in services
        ):
            ok = False
    except AcceptanceError:
        if runtime_root.exists():
            ok = False
    if not ok:
        code = "workroom_cleanup_incomplete"
    _gate(
        state,
        "cleanup",
        "passed" if ok else "failed",
        started=started,
        deps=deps,
        code=code,
    )
    return ok, code


def _safe_result(
    config: AcceptanceConfig,
    deps: AcceptanceDependencies,
    state: _RunState,
    *,
    status: str,
    reason_code: str | None,
    result_path: Path,
    screenshot_path: Path,
    evidence_path: Path,
    worktree_unchanged: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "started_at": state.started_at,
        "finished_at": deps.now(),
        "duration_s": round(max(0.0, deps.monotonic() - state.started_monotonic), 3),
        "baseline_head": config.expected_head,
        "worktree_unchanged": worktree_unchanged,
        "gates": list(state.gates),
        "room": {
            "conversation_id": state.conversation_id,
            "participant_ids": list(state.participant_ids),
            "participant_count": len(state.participant_ids),
            "root_correlation_id": state.root_correlation_id,
            "root_activity_id": state.root_activity_id,
            "status": state.room_status,
            "turn_count": len(state.turns),
            "turns": list(state.turns),
        },
        "counts": {
            "durable_outcomes": state.durable_outcome_count,
            "skill_evidence": state.skill_evidence_count,
            "console_errors": state.console_error_count,
            "page_errors": state.page_error_count,
        },
        "artifacts": {
            "result": str(result_path),
            "browser_evidence": str(evidence_path),
            "screenshot": str(screenshot_path),
        },
        "proof_boundary": "acceptance_evidence_not_room_or_provider_authority",
    }
    if reason_code is not None:
        result["reason_code"] = reason_code
    return result


def run_acceptance(
    config: AcceptanceConfig,
    *,
    dependencies: AcceptanceDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or AcceptanceDependencies()
    repo_root = config.repo_root.expanduser().resolve()
    config = AcceptanceConfig(**{**config.__dict__, "repo_root": repo_root})
    artifact_dir = (
        config.artifact_dir.expanduser().resolve()
        if config.artifact_dir is not None
        else Path(tempfile.mkdtemp(prefix="xmuse-room-first-real-artifacts-"))
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    runtime_root_created = config.runtime_root is None
    runtime_root = (
        config.runtime_root.expanduser().resolve()
        if config.runtime_root is not None
        else Path(tempfile.mkdtemp(prefix="xmuse-room-first-real-runtime-"))
    )
    state_path = artifact_dir / "browser-state.json"
    evidence_path = artifact_dir / "browser-evidence.json"
    screenshot_path = artifact_dir / "room-first-final.png"
    output_dir = artifact_dir / "playwright-output"
    result_path = artifact_dir / "result.json"
    state = _RunState(started_at=deps.now(), started_monotonic=deps.monotonic())
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "XMUSE_OPERATOR_TOKEN",
            "XMUSE_ROOT",
            "XMUSE_WORKROOM_GENERATION",
            "XMUSE_WORKROOM_MANAGED",
            "XMUSE_WORKROOM_SERVICE",
        }
    }
    final_status = "failed"
    reason_code: str | None = None
    cleanup_required = False
    cleanup_ok = True
    try:
        _preflight(config, deps, state, runtime_root, env)
        if config.preflight_only:
            final_status = "ok"
        else:
            _build_frontend(config, deps, state, env)
            # Once startup is attempted, cleanup is mandatory even when readiness
            # fails part-way through composition.
            cleanup_required = True
            _start_workroom(config, deps, state, runtime_root, env)
            _run_playwright_phase(
                config,
                deps,
                state,
                env,
                phase="conversation",
                state_path=state_path,
                evidence_path=evidence_path,
                screenshot_path=screenshot_path,
                output_dir=output_dir,
            )
            _load_browser_state(state_path, state)
            if config.run_fault_recovery:
                status = _workroom_status(config, deps, runtime_root, env)
                runner_pid = _inject_fault(deps, status, service_name="room_runner")
                started = deps.monotonic()
                _run_playwright_phase(
                    config,
                    deps,
                    state,
                    env,
                    phase="recover-runner",
                    state_path=state_path,
                    evidence_path=evidence_path,
                    screenshot_path=screenshot_path,
                    output_dir=output_dir,
                )
                status = _wait_for_ready(config, deps, state, runtime_root, env)
                _runner_pid, state.recovered_runner_boot = _validate_recovered_service(
                    status,
                    service_name="room_runner",
                    prior_pid=runner_pid,
                    prior_boot=state.initial_runner_boot,
                )
                _gate(
                    state,
                    "runner_recovery",
                    "passed",
                    started=started,
                    deps=deps,
                )

                status = _workroom_status(config, deps, runtime_root, env)
                mcp_pid = _inject_fault(deps, status, service_name="room_mcp")
                started = deps.monotonic()
                _run_playwright_phase(
                    config,
                    deps,
                    state,
                    env,
                    phase="recover-mcp",
                    state_path=state_path,
                    evidence_path=evidence_path,
                    screenshot_path=screenshot_path,
                    output_dir=output_dir,
                )
                status = _wait_for_ready(config, deps, state, runtime_root, env)
                state.recovered_mcp_pid, _mcp_boot = _validate_recovered_service(
                    status,
                    service_name="room_mcp",
                    prior_pid=mcp_pid,
                )
                _gate(
                    state,
                    "mcp_recovery",
                    "passed",
                    started=started,
                    deps=deps,
                )
            _run_playwright_phase(
                config,
                deps,
                state,
                env,
                phase="verify",
                state_path=state_path,
                evidence_path=evidence_path,
                screenshot_path=screenshot_path,
                output_dir=output_dir,
            )
            browser_evidence = _validate_browser_evidence(
                evidence_path,
                expect_faults=config.run_fault_recovery,
            )
            verify = browser_evidence["phases"]["verify"]
            state.room_status = _optional_text(verify.get("room_status"))
            state.durable_outcome_count = int(verify.get("durable_outcome_count") or 0)
            state.skill_evidence_count = int(verify.get("skill_evidence_count") or 0)
            state.console_error_count = int(browser_evidence.get("console_error_count") or 0)
            state.page_error_count = int(browser_evidence.get("page_error_count") or 0)
            _scan_operator_token(config, state, runtime_root, artifact_dir)
            final_status = "ok"
    except KeyboardInterrupt:
        reason_code = "acceptance_interrupted"
        final_status = "failed"
    except AcceptanceError as exc:
        reason_code = exc.code
        final_status = "blocked" if exc.blocked else "failed"
    finally:
        if cleanup_required:
            cleanup_ok, cleanup_code = _cleanup(
                config,
                deps,
                state,
                runtime_root,
                env,
            )
            if not cleanup_ok:
                final_status = "failed"
                reason_code = cleanup_code
        worktree_unchanged = (
            state.baseline_snapshot is not None
            and deps.git_snapshot(config.repo_root) == state.baseline_snapshot
        )
        if not worktree_unchanged and final_status == "ok":
            final_status = "failed"
            reason_code = "worktree_changed_during_acceptance"
        result = _safe_result(
            config,
            deps,
            state,
            status=final_status,
            reason_code=reason_code,
            result_path=result_path,
            screenshot_path=screenshot_path,
            evidence_path=evidence_path,
            worktree_unchanged=worktree_unchanged,
        )
        _atomic_json(result_path, result)
        if (
            runtime_root_created
            and not config.keep_runtime_root
            and (cleanup_ok or not cleanup_required)
        ):
            shutil.rmtree(runtime_root, ignore_errors=True)
    return result


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise AcceptanceError("acceptance_safe_id_invalid")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _bounded_nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 1_000_000:
        raise ValueError("acceptance_safe_count_invalid")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="fresh temporary XMUSE_ROOT")
    parser.add_argument("--artifacts", type=Path, help="safe artifact directory under /tmp")
    parser.add_argument("--expected-head", default=EXPECTED_BASELINE_HEAD)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--keep-root", action="store_true")
    parser.add_argument("--readiness-timeout-s", type=float, default=120.0)
    parser.add_argument("--phase-timeout-s", type=float, default=2400.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.readiness_timeout_s <= 0 or args.phase_timeout_s <= 0:
        build_parser().error("timeouts must be positive")
    result = run_acceptance(
        AcceptanceConfig(
            repo_root=Path(__file__).resolve().parents[1],
            expected_head=args.expected_head,
            runtime_root=args.root,
            artifact_dir=args.artifacts,
            preflight_only=args.preflight_only,
            keep_runtime_root=args.keep_root,
            readiness_timeout_s=args.readiness_timeout_s,
            phase_timeout_s=args.phase_timeout_s,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
