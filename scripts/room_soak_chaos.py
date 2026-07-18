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
import re
import shutil
import signal
import socket
import sqlite3
import stat
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

FRONTEND_URL = "http://127.0.0.1:3000"
CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat"
LIVE_EVIDENCE_SCHEMA = "room_soak_live_evidence/v1"
GOAL_MEMORY_PROFILE_ID = "live-goal-memory-soak"
ENDURANCE_PROFILE_ID = "live-endurance"
ENDURANCE_SHORT_PROFILE_ID = "live-endurance-short"
ENDURANCE_PROFILE_IDS = frozenset({ENDURANCE_PROFILE_ID, ENDURANCE_SHORT_PROFILE_ID})
BROWSER_INPUT_SCHEMA = "room_soak_browser_input/v1"
BROWSER_EVIDENCE_SCHEMA = "room_soak_browser_evidence/v1"
GOAL_BROWSER_EVIDENCE_SCHEMA = "room_soak_browser_evidence/v2"
GOAL_BROWSER_CONSUMER = "g9_live_goal_memory_soak"
CLI_ERROR_SCHEMA = "room_soak_chaos_cli_error/v1"
CLI_ERROR_PROOF_BOUNDARY = "cli_failure_before_complete_soak_evidence"
FROZEN_MEMORYOS_BASE = "1b9d5dad7e3ba944fb668d8d87e364a06e0b20ef"
REQUIRED_SERVICES = ("frontend", "chat_api", "room_runner", "room_mcp")
MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
MAX_ACTIVE_PROVIDER_DELIVERIES = 4
MAX_FIRST_CLAIM_MS = 240_000.0
MAX_FAULT_RECOVERY_MS = 45_000
GOAL_PEER_OUTCOME_TIMEOUT_S = 240.0
CLEANUP_PROVIDER_TIMEOUT_S = 10.0
RESOURCE_SAMPLE_INTERVAL_MS = 1_000
FULL_LOCAL_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
SOAK_FASTEMBED_CACHE_SOURCE_ENV = "XMUSE_SOAK_FASTEMBED_CACHE_SOURCE"
MAX_FASTEMBED_CACHE_ENTRIES = 1_024
MAX_FASTEMBED_CACHE_BYTES = 256 * 1024 * 1024
REQUIRED_NATIVE_EVENT_KINDS = frozenset(
    {"turn_started", "item_completed", "token_usage_updated", "turn_completed"}
)


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
    ENDURANCE_PROFILE_ID: LiveProfileSpec(
        ENDURANCE_PROFILE_ID,
        8,
        2,
        5,
        5,
        192,
        minimum_duration_s=7200.0,
        memory_recovery=True,
    ),
    ENDURANCE_SHORT_PROFILE_ID: LiveProfileSpec(
        ENDURANCE_SHORT_PROFILE_ID,
        2,
        2,
        5,
        5,
        56,
        memory_recovery=True,
    ),
    GOAL_MEMORY_PROFILE_ID: LiveProfileSpec(
        GOAL_MEMORY_PROFILE_ID,
        4,
        2,
        4,
        4,
        128,
        minimum_duration_s=3600.0,
        memory_recovery=True,
    ),
}


ENDURANCE_OUTCOME_REQUIREMENT = (
    " Submit exactly one concise durable Room outcome through the allowed Room outcome tool; "
    "do not end with provider text alone."
)
ENDURANCE_PROMPT_CATEGORIES: tuple[tuple[str, str], ...] = (
    (
        "boundary_inventory",
        "Read-only architecture review: identify one runtime boundary and report only "
        "evidence-backed observations; do not edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
    (
        "package_direction",
        "Read-only architecture review: inspect runtime boundaries and package import "
        "direction, cite durable evidence, and do not edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
    (
        "authority_ownership",
        "Read-only architecture review: inspect boundaries, package direction, and durable "
        "authority ownership; distinguish infrastructure from Agent decisions and do not "
        "edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
    (
        "causality_recovery",
        "Read-only architecture review: inspect boundaries, direction, authority, causality, "
        "idempotency, and recovery behavior using only re-provable Room sources; do not "
        "edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
    (
        "execution_safety",
        "Read-only architecture review: inspect boundaries, direction, authority, causality, "
        "recovery, and exact-patch execution safety; reject claims lacking durable evidence and "
        "do not edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
    (
        "adversarial_integration",
        "Read-only adversarial architecture review: jointly inspect boundaries, import direction, "
        "authority, causality, idempotency, recovery, memory source proof, and execution gates; "
        "surface contradictions and do not edit files." + ENDURANCE_OUTCOME_REQUIREMENT,
    ),
)


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
class RunnerRuntimeBinding:
    process: ProcessBinding
    boot_id: str


@dataclass(frozen=True)
class BrowserVerificationRequest:
    repo_root: Path
    frontend_url: str
    room_ids: tuple[str, ...]
    artifact_dir: Path
    timeout_s: float
    environment: Mapping[str, str]
    goal_memory: bool = False


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
    goal_guard_wall_s: float | None = None
    goal_guard_idle_s: float | None = None


_GOAL_TERMINAL_STATES = frozenset(
    {"paused", "blocked", "usageLimited", "budgetLimited", "complete"}
)


@dataclass
class _GoalContinuationObserver:
    participant_id: str
    baseline_event_seq: int
    started_at: float
    last_progress_at: float
    latest_event_seq: int
    turn_started_event_seqs: set[int] = field(default_factory=set)
    active_goal_update_event_seqs: set[int] = field(default_factory=set)
    terminal_status: str | None = None

    @classmethod
    def start(
        cls,
        participant_id: str,
        baseline_event_seq: int,
        now: float,
    ) -> _GoalContinuationObserver:
        return cls(
            participant_id=participant_id,
            baseline_event_seq=baseline_event_seq,
            started_at=now,
            last_progress_at=now,
            latest_event_seq=baseline_event_seq,
        )

    def observe(self, projection: Mapping[str, Any], now: float) -> None:
        native = projection.get("native_events")
        items = native.get("items") if isinstance(native, Mapping) else None
        progressed = False
        relevant: list[tuple[int, Mapping[str, Any]]] = []
        for item in _mapping_records(items):
            event_seq = item.get("event_seq")
            if (
                item.get("participant_id") != self.participant_id
                or not isinstance(event_seq, int)
                or isinstance(event_seq, bool)
                or event_seq <= self.baseline_event_seq
            ):
                continue
            relevant.append((event_seq, item))
        for event_seq, item in sorted(relevant, key=lambda pair: pair[0]):
            if event_seq > self.latest_event_seq:
                self.latest_event_seq = event_seq
                progressed = True
            if item.get("kind") == "turn_started":
                self.turn_started_event_seqs.add(event_seq)
            if item.get("kind") == "goal_updated":
                status = item.get("status")
                if status == "active":
                    self.active_goal_update_event_seqs.add(event_seq)
                    self.terminal_status = None
                elif status in _GOAL_TERMINAL_STATES:
                    self.terminal_status = str(status)
        if progressed:
            self.last_progress_at = now
        participant = _participant_view(projection, self.participant_id)
        if participant is None:
            return
        wrapper = participant.get("native_snapshot")
        snapshot = wrapper.get("value") if isinstance(wrapper, Mapping) else None
        if not isinstance(snapshot, Mapping):
            return
        goal = snapshot.get("goal")
        status = goal.get("status") if isinstance(goal, Mapping) else None
        if status in _GOAL_TERMINAL_STATES:
            self.terminal_status = str(status)

    @property
    def turn_started_count(self) -> int:
        return len(self.turn_started_event_seqs)

    @property
    def continuation_checkpoint_count(self) -> int:
        """Count persisted Goal accounting checkpoints after native work starts.

        Setting or resuming an active native Goal automatically starts an idle
        thread turn. A later ``goal_updated(active)`` notification corroborates
        that the turn has accounted Goal progress and remains pausable.
        """

        if not self.turn_started_event_seqs:
            return 0
        first_turn = min(self.turn_started_event_seqs)
        return sum(seq > first_turn for seq in self.active_goal_update_event_seqs)

    def stop_reason(
        self,
        now: float,
        *,
        wall_s: float | None,
        idle_s: float | None,
    ) -> str | None:
        if self.terminal_status is not None:
            return "soak_codex_goal_terminal_before_continuation"
        if self.continuation_checkpoint_count >= 1:
            return None
        if wall_s is not None and now - self.started_at >= wall_s:
            return "soak_goal_guard_wall_limit_reached"
        if idle_s is not None and now - self.last_progress_at >= idle_s:
            return "soak_goal_guard_idle_limit_reached"
        return None


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


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_digest_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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


def _registered_god_session_id(
    runtime_root: Path,
    *,
    conversation_id: str,
    participant_id: str,
    feature_scope_id: str = "room_delivery_v1",
) -> str | None:
    binding = _registered_god_session_private_binding(
        runtime_root,
        conversation_id=conversation_id,
        participant_id=participant_id,
        feature_scope_id=feature_scope_id,
    )
    return binding[0] if binding is not None else None


def _registered_god_session_private_binding(
    runtime_root: Path,
    *,
    conversation_id: str,
    participant_id: str,
    feature_scope_id: str = "room_delivery_v1",
) -> tuple[str, str] | None:
    try:
        payload = json.loads((runtime_root / "god_sessions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sessions = payload.get("sessions") if isinstance(payload, Mapping) else None
    if not isinstance(sessions, list):
        return None
    matches = [
        (str(item["god_session_id"]), str(item["provider_session_id"]))
        for item in sessions
        if isinstance(item, Mapping)
        and item.get("conversation_id") == conversation_id
        and item.get("participant_id") == participant_id
        and item.get("feature_scope_id") == feature_scope_id
        and _safe_id(item.get("god_session_id"))
        and _safe_id(item.get("provider_session_id"))
        and item.get("provider_binding_status") == "active"
    ]
    return matches[0] if len(matches) == 1 else None


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
    private = _runner_runtime_binding(runtime_root)
    if private is not None:
        return private.process
    from xmuse_core.chat.room_runtime import read_process_start_identity

    candidate = runtime_root / "workroom_room_runner.pid.json"
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
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


def _runner_runtime_binding(runtime_root: Path) -> RunnerRuntimeBinding | None:
    from xmuse_core.chat.room_runtime import read_process_start_identity

    try:
        payload = json.loads((runtime_root / "room-runner-status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    pid = payload.get("pid")
    expected = payload.get("start_identity")
    boot_id = payload.get("boot_id")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(expected, str)
        or not expected
        or not _safe_id(boot_id)
        or read_process_start_identity(pid) != expected
    ):
        return None
    return RunnerRuntimeBinding(ProcessBinding(pid, expected), str(boot_id))


def _default_get_profile(profile_id: str) -> Any:
    from xmuse_core.chat.room_soak_chaos import get_soak_profile

    return get_soak_profile(profile_id)


def _default_build_result(**kwargs: Any) -> dict[str, Any]:
    if "manifest" in kwargs:
        from xmuse_core.chat.room_goal_memory_soak import build_goal_memory_soak_result

        return build_goal_memory_soak_result(**kwargs)
    from xmuse_core.chat.room_soak_chaos import build_soak_result

    return build_soak_result(**kwargs)


def _default_validate_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") == "room_goal_memory_soak_result/v1":
        from xmuse_core.chat.room_goal_memory_soak import validate_goal_memory_soak_result

        return validate_goal_memory_soak_result(payload)
    from xmuse_core.chat.room_soak_chaos import validate_soak_result

    return validate_soak_result(payload)


def _default_evaluate_result(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    if payload.get("schema_version") == "room_goal_memory_soak_result/v1":
        from xmuse_core.chat.room_goal_memory_soak import evaluate_goal_memory_soak_result

        return evaluate_goal_memory_soak_result(payload)
    from xmuse_core.chat.room_soak_chaos import evaluate_soak_result

    return evaluate_soak_result(payload)


def _default_write_result(path: Path, payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") == "room_goal_memory_soak_result/v1":
        from xmuse_core.chat.room_goal_memory_soak import write_goal_memory_soak_result

        write_goal_memory_soak_result(path, payload)
        return
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
    runner_runtime_binding: Callable[[Path], RunnerRuntimeBinding | None] = _runner_runtime_binding
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


@dataclass(frozen=True)
class _ProviderFaultTarget:
    attempt_id: str
    god_session_id: str
    conversation_id: str
    participant_id: str
    binding: ProcessBinding


@dataclass(frozen=True)
class _ProviderRecoveryProof:
    conversation_id: str
    participant_id: str
    god_session_id: str
    provider_session_id_before: str
    session_guard_before: str


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
    provider_recovery_proof: _ProviderRecoveryProof | None = None
    goal_memory_evidence: dict[str, Any] = field(default_factory=dict)
    endurance_prompt_categories: Counter[str] = field(default_factory=Counter)
    endurance_retried_observations: set[str] = field(default_factory=set)
    browser: dict[str, int] = field(
        default_factory=lambda: {"refreshes": 0, "console_errors": 0, "page_errors": 0}
    )


def _mapping_records(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _codex_projection(deps: SoakDependencies, conversation_id: str) -> dict[str, Any]:
    response = deps.http_json(
        "GET",
        f"{CHAT_API_BASE_URL}/conversations/{conversation_id}/codex-agents?limit=100",
        None,
        timeout_s=20.0,
    )
    if (
        response.status != 200
        or not isinstance(response.payload, Mapping)
        or response.payload.get("schema_version") != "room_codex_projection/v1"
    ):
        raise SoakError("soak_codex_projection_unavailable")
    return dict(response.payload)


def _room_projection(deps: SoakDependencies, conversation_id: str) -> dict[str, Any]:
    response = deps.http_json(
        "GET",
        f"{CHAT_API_BASE_URL}/conversations/{conversation_id}/room-projection?limit=100",
        None,
        timeout_s=20.0,
    )
    if (
        response.status != 200
        or not isinstance(response.payload, Mapping)
        or response.payload.get("schema_version") != "room_chat_projection/v3"
    ):
        raise SoakError("soak_room_projection_unavailable")
    return dict(response.payload)


def _goal_turn_started_count(
    projection: Mapping[str, Any], participant_id: str, baseline_event_seq: int
) -> int:
    native = projection.get("native_events")
    items = native.get("items") if isinstance(native, Mapping) else None
    return sum(
        item.get("kind") == "turn_started"
        and item.get("participant_id") == participant_id
        and isinstance(item.get("event_seq"), int)
        and int(item["event_seq"]) > baseline_event_seq
        for item in _mapping_records(items)
    )


def _wait_goal_continuation(
    config: SoakConfig,
    deps: SoakDependencies,
    conversation_id: str,
    participant_id: str,
    baseline_event_seq: int,
) -> int:
    observer = _GoalContinuationObserver.start(
        participant_id,
        baseline_event_seq,
        deps.monotonic(),
    )
    while True:
        projection = _codex_projection(deps, conversation_id)
        now = deps.monotonic()
        observer.observe(projection, now)
        reason = observer.stop_reason(
            now,
            wall_s=config.goal_guard_wall_s,
            idle_s=config.goal_guard_idle_s,
        )
        if reason is None and observer.continuation_checkpoint_count >= 1:
            return 1
        if reason is not None:
            if reason.startswith("soak_goal_guard_"):
                pause_applied = False
                try:
                    action_projection = _invoke_native_action(
                        config,
                        deps,
                        conversation_id,
                        participant_id,
                        "goal_pause",
                        {},
                        timeout_s=60.0,
                    )
                    pause_applied = True
                    observer.observe(action_projection, deps.monotonic())
                except SoakError:
                    try:
                        projection = _codex_projection(deps, conversation_id)
                        observer.observe(projection, deps.monotonic())
                    except SoakError:
                        pass
                pause_deadline = deps.monotonic() + 30.0
                while True:
                    if observer.terminal_status == "paused" and pause_applied:
                        raise SoakError(reason)
                    if observer.terminal_status is not None:
                        raise SoakError("soak_codex_goal_terminal_before_continuation")
                    if observer.continuation_checkpoint_count >= 1:
                        return 1
                    if not pause_applied or deps.monotonic() >= pause_deadline:
                        raise SoakError("soak_goal_guard_pause_unconfirmed")
                    projection = _codex_projection(deps, conversation_id)
                    observer.observe(projection, deps.monotonic())
                    deps.sleep(0.25)
            raise SoakError(reason)
        deps.sleep(0.25)


def _goal_hold_projection_count(
    projection: Mapping[str, Any],
    *,
    root_activity_ids: Sequence[str],
    goal_participant_id: str,
) -> int:
    roots = set(root_activity_ids)
    proven = 0
    for turn in _mapping_records(projection.get("turns")):
        if turn.get("root_activity_id") not in roots or turn.get("status") != "active":
            continue
        members = _mapping_records(turn.get("participants"))
        goal = next(
            (item for item in members if item.get("participant_id") == goal_participant_id),
            None,
        )
        peers = [item for item in members if item.get("participant_id") != goal_participant_id]
        frontier = goal.get("frontier") if isinstance(goal, Mapping) else None
        if (
            isinstance(goal, Mapping)
            and goal.get("state") == "pending"
            and isinstance(frontier, Mapping)
            and frontier.get("phase") == "root"
            and frontier.get("attempt_count") == 0
            and any(isinstance(peer.get("latest_outcome"), Mapping) for peer in peers)
        ):
            proven += 1
    return proven


def _wait_goal_hold_projection(
    deps: SoakDependencies,
    conversation_id: str,
    *,
    root_activity_ids: Sequence[str],
    goal_participant_id: str,
    deadline: float,
) -> int:
    """Wait for the projection to catch up with a durable peer delivery.

    Runner fencing can briefly leave the peer attempt expired while the Goal
    participant remains pending.  The durable database check establishes that
    the hold is real; this bounded poll lets the derived Room projection expose
    the corresponding peer outcome after recovery instead of sampling the
    pre-reconcile snapshot once.
    """
    while deps.monotonic() < deadline:
        count = _goal_hold_projection_count(
            _room_projection(deps, conversation_id),
            root_activity_ids=root_activity_ids,
            goal_participant_id=goal_participant_id,
        )
        if count >= 1:
            return count
        deps.sleep(0.25)
    return 0


def _participant_view(
    projection: Mapping[str, Any], participant_id: str
) -> Mapping[str, Any] | None:
    for item in _mapping_records(projection.get("participants")):
        participant = item.get("participant")
        if isinstance(participant, Mapping) and participant.get("participant_id") == participant_id:
            return item
    return None


def _action_descriptor(
    participant: Mapping[str, Any], capability_id: str
) -> Mapping[str, Any] | None:
    capabilities = participant.get("capabilities")
    actions = capabilities.get("actions") if isinstance(capabilities, Mapping) else None
    for item in _mapping_records(actions):
        if item.get("capability_id") == capability_id:
            return item
    return None


def _invoke_native_action(
    config: SoakConfig,
    deps: SoakDependencies,
    conversation_id: str,
    participant_id: str,
    capability_id: str,
    request: Mapping[str, Any],
    *,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    deadline = deps.monotonic() + timeout_s
    client_action_id = f"soak_codex_{uuid.uuid4().hex}"
    action_id: object = None
    while deps.monotonic() < deadline:
        projection = _codex_projection(deps, conversation_id)
        participant = _participant_view(projection, participant_id)
        descriptor = _action_descriptor(participant, capability_id) if participant else None
        if descriptor is None or descriptor.get("available") is not True:
            deps.sleep(0.25)
            continue
        payload = {
            "client_action_id": client_action_id,
            "capability_id": capability_id,
            "request": dict(request),
            "expected_session_guard": descriptor.get("expected_session_guard"),
            "expected_goal_guard": descriptor.get("expected_goal_guard"),
            "expected_settings_guard": descriptor.get("expected_settings_guard"),
            "expected_turn_guard": descriptor.get("expected_turn_guard"),
            "confirmed_pending_observations": descriptor.get("confirmation_required") is True,
        }
        response = deps.http_json(
            "POST",
            f"{FRONTEND_URL}/api/room-participants/{participant_id}/codex-actions",
            payload,
            timeout_s=30.0,
        )
        if response.status == 409:
            # A prior action can be durably applied before its best-effort snapshot
            # reconcile reaches the projection. Refresh every guard while keeping
            # the logical request id stable; a guard rejection creates no action.
            deps.sleep(0.25)
            continue
        action_id = response.payload.get("action_id") if response.payload else None
        if response.status not in {200, 201, 202} or not _safe_id(action_id):
            raise SoakError(f"soak_codex_{capability_id}_request_failed")
        break
    if not _safe_id(action_id):
        raise SoakError(f"soak_codex_{capability_id}_unavailable")
    while deps.monotonic() < deadline:
        projection = _codex_projection(deps, conversation_id)
        participant = _participant_view(projection, participant_id)
        bridge = participant.get("room_bridge") if participant else None
        actions = bridge.get("actions") if isinstance(bridge, Mapping) else None
        for item in _mapping_records(actions):
            if item.get("action_id") != action_id:
                continue
            status_value = item.get("status")
            if status_value == "applied":
                return projection
            if status_value in {"failed", "rejected"}:
                raise SoakError(f"soak_codex_{capability_id}_not_applied")
        deps.sleep(0.25)
    raise SoakError(f"soak_codex_{capability_id}_timeout")


def _wait_native_state(
    deps: SoakDependencies,
    conversation_id: str,
    participant_id: str,
    predicate: Callable[[Mapping[str, Any]], bool],
    *,
    timeout_s: float,
    code: str,
) -> Mapping[str, Any]:
    deadline = deps.monotonic() + timeout_s
    while deps.monotonic() < deadline:
        projection = _codex_projection(deps, conversation_id)
        participant = _participant_view(projection, participant_id)
        if participant is not None and predicate(participant):
            return participant
        deps.sleep(0.25)
    raise SoakError(code)


def _native_snapshot(participant: Mapping[str, Any]) -> Mapping[str, Any]:
    wrapper = participant.get("native_snapshot")
    value = wrapper.get("value") if isinstance(wrapper, Mapping) else None
    if not isinstance(value, Mapping):
        raise SoakError("soak_codex_native_snapshot_unavailable")
    return value


def _goal_console_turn_request(text: str) -> dict[str, str]:
    return {"text": text, "mode": "default"}


def _goal_native_request() -> dict[str, str | int]:
    return {
        "objective": (
            "Audit the Room runtime and source-backed memory recovery evidence without editing "
            "files. Establish a bounded plan and at least one automatic Goal continuation "
            "checkpoint, but keep the Goal active so the external pause/resume and Room delivery "
            "hold can be verified before completion."
        ),
        # The acceptance Goal must survive all four fixed waves and the
        # recovery hold.  Codex's native accounting includes the full context
        # envelope; the previous 100k budget became budgetLimited during the
        # first recovery run before pause/resume could be proven.  Use the
        # contract's bounded maximum rather than weakening the external Guard.
        "token_budget": 1_000_000,
    }


def _pause_native_goal(
    config: SoakConfig,
    deps: SoakDependencies,
    conversation_id: str,
    participant_id: str,
) -> None:
    _invoke_native_action(
        config,
        deps,
        conversation_id,
        participant_id,
        "goal_pause",
        {},
        timeout_s=60.0,
    )
    paused = _wait_native_state(
        deps,
        conversation_id,
        participant_id,
        lambda item: (
            isinstance(_native_snapshot(item).get("goal"), Mapping)
            and _native_snapshot(item)["goal"].get("status") == "paused"
        ),
        timeout_s=30.0,
        code="soak_codex_goal_pause_unproven",
    )
    if _native_snapshot(paused).get("active_turn") is True:
        # Goal pause fences the next continuation but deliberately does not
        # cancel the turn that is already running.  Interrupt that exact guarded
        # turn so a bounded acceptance Goal cannot consume its entire budget
        # before the later resume/hold proof.
        _invoke_native_action(
            config,
            deps,
            conversation_id,
            participant_id,
            "turn_interrupt",
            {},
            timeout_s=60.0,
        )
    _wait_native_state(
        deps,
        conversation_id,
        participant_id,
        lambda item: (
            isinstance(_native_snapshot(item).get("goal"), Mapping)
            and _native_snapshot(item)["goal"].get("status") == "paused"
            and _native_snapshot(item).get("active_turn") is False
        ),
        timeout_s=max(30.0, config.goal_guard_idle_s or config.settle_timeout_s),
        code="soak_codex_goal_pause_idle_unproven",
    )


def _resume_native_goal(
    config: SoakConfig,
    deps: SoakDependencies,
    conversation_id: str,
    participant_id: str,
) -> None:
    _invoke_native_action(
        config,
        deps,
        conversation_id,
        participant_id,
        "goal_resume",
        {},
        timeout_s=60.0,
    )
    _wait_native_state(
        deps,
        conversation_id,
        participant_id,
        lambda item: (
            isinstance(_native_snapshot(item).get("goal"), Mapping)
            and _native_snapshot(item)["goal"].get("status") == "active"
        ),
        timeout_s=30.0,
        code="soak_codex_goal_resume_unproven",
    )


def _prove_provider_recovery_identity(
    runtime_root: Path,
    proof: _ProviderRecoveryProof,
    participants: Sequence[tuple[str, str, Mapping[str, Any]]],
) -> tuple[tuple[str, str, Mapping[str, Any]], dict[str, int]]:
    target = next(
        (
            item
            for item in participants
            if item[0] == proof.conversation_id and item[1] == proof.participant_id
        ),
        None,
    )
    if target is None:
        raise SoakError("soak_provider_recovery_participant_missing")
    registered = _registered_god_session_private_binding(
        runtime_root,
        conversation_id=proof.conversation_id,
        participant_id=proof.participant_id,
    )
    snapshot = _native_snapshot(target[2])
    guards = snapshot.get("guards")
    session_guard = guards.get("session") if isinstance(guards, Mapping) else None
    if registered is None or registered[0] != proof.god_session_id:
        raise SoakError("soak_provider_recovery_god_identity_changed")
    if registered[1] == proof.provider_session_id_before:
        raise SoakError("soak_provider_recovery_delivery_session_unchanged")
    if not isinstance(session_guard, str) or session_guard != proof.session_guard_before:
        raise SoakError("soak_provider_recovery_native_session_changed")
    return target, {
        "god_identity_unchanged": 1,
        "delivery_provider_rebound": 1,
        "native_session_guard_unchanged": 1,
    }


def _provider_recovery_action_counts(
    database: Path,
    proof: _ProviderRecoveryProof,
) -> dict[str, int]:
    capabilities = ("settings_update", "console_turn_start")
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            """select capability_id, status, count(*) count
               from room_codex_bridge_actions
               where conversation_id = ? and participant_id = ?
                 and capability_id in (?, ?)
               group by capability_id, status""",
            (
                proof.conversation_id,
                proof.participant_id,
                *capabilities,
            ),
        ).fetchall()
    by_capability = {
        capability: {
            str(row["status"]): int(row["count"])
            for row in rows
            if row["capability_id"] == capability
        }
        for capability in capabilities
    }
    if any(statuses != {"applied": 1} for statuses in by_capability.values()):
        raise SoakError("soak_provider_recovery_native_action_evidence_invalid")
    return {capability: statuses["applied"] for capability, statuses in by_capability.items()}


def _codex_api_model_support(runtime_root: Path | None = None) -> Mapping[str, bool]:
    """Read only the local Codex model availability flags for soak assignment.

    ``model/list`` is intentionally a UI capability surface and does not say
    whether a model can serve an API/MCP Room turn.  The local Codex catalog is
    the only server-side capability evidence available to this harness.  A
    missing or malformed cache is treated as unknown, not as a reason to
    reject every model; entries explicitly marked unsupported are fail-closed.
    """

    cache_paths: list[Path] = []
    if runtime_root is not None:
        cache_paths.append(runtime_root / "runtime" / "room-codex-home" / "models_cache.json")
    codex_home = os.environ.get("CODEX_HOME")
    cache_paths.append(
        Path(codex_home).expanduser() / "models_cache.json"
        if codex_home
        else Path.home() / ".codex" / "models_cache.json"
    )
    raw: object | None = None
    for cache_path in cache_paths:
        if not cache_path.is_file():
            continue
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        break
    if raw is None:
        return {}
    models = raw.get("models") if isinstance(raw, Mapping) else None
    if not isinstance(models, list):
        return {}
    result: dict[str, bool] = {}
    for item in models[:2_000]:
        if not isinstance(item, Mapping) or not isinstance(item.get("supported_in_api"), bool):
            continue
        supported = bool(item["supported_in_api"])
        for key in (item.get("slug"), item.get("id"), item.get("model")):
            if isinstance(key, str) and key and len(key) <= 256:
                result[key] = supported
    return result


def _goal_model_combinations(
    models: Sequence[Mapping[str, Any]],
    *,
    runtime_root: Path | None = None,
) -> list[tuple[str, str, str]]:
    """Build deterministic native settings coverage for API-capable models."""

    api_support = _codex_api_model_support(runtime_root)
    combinations: list[tuple[str, str, str]] = []
    for model in models:
        model_id = model.get("id")
        model_name = model.get("model")
        efforts = model.get("efforts")
        if (
            not isinstance(model_id, str)
            or not isinstance(model_name, str)
            or not isinstance(efforts, list)
        ):
            continue
        if api_support.get(model_id) is False or api_support.get(model_name) is False:
            continue
        combinations.extend(
            (model_id, model_name, effort)
            for effort in efforts
            if isinstance(effort, str) and effort
        )
    return sorted(set(combinations), key=lambda item: (item[2] != "max", item))


def _select_goal_participant(
    assignments: Sequence[tuple[str, str, str, str]],
    excluded_targets: Sequence[tuple[str, str]],
) -> tuple[str, str, str, str]:
    """Choose a bounded-cost participant for the native Goal proof.

    The soak still exercises every frozen model/effort assignment above, but the
    Goal control proof itself must be run on a participant that can reach a
    continuation checkpoint before provider budget exhaustion.  An active Codex
    Goal can continue consuming until it reaches a terminal/budget state, so the
    control proof requires an explicitly bounded low/medium effort assignment.
    The recovery, review, and steer participants are excluded because their
    session identities are reserved for the other native proofs.
    """

    effort_rank = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}
    model_rank = {
        "gpt-5.4": 0,
        "gpt-5.4-mini": 1,
        "gpt-5.6-sol": 2,
        "gpt-5.6-luna": 3,
        "gpt-5.6-terra": 4,
    }
    excluded = set(excluded_targets)
    candidates = [item for item in assignments if item[:2] not in excluded]
    bounded_candidates = [item for item in candidates if item[3] in {"low", "medium"}]
    if not bounded_candidates:
        raise SoakError("soak_codex_goal_participant_unavailable")
    return min(
        bounded_candidates,
        key=lambda item: (
            effort_rank.get(item[3], 99),
            model_rank.get(item[2], 99),
            item[0],
            item[1],
        ),
    )


def _prepare_goal_native_capabilities(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
) -> None:
    participants: list[tuple[str, str, Mapping[str, Any]]] = []
    capability_material: list[object] = []
    for conversation_id in state.room_ids:
        projection = _codex_projection(deps, conversation_id)
        for item in _mapping_records(projection.get("participants")):
            participant = item.get("participant")
            capabilities = item.get("capabilities")
            capability_value = (
                capabilities.get("value") if isinstance(capabilities, Mapping) else None
            )
            participant_id = (
                participant.get("participant_id") if isinstance(participant, Mapping) else None
            )
            if not _safe_id(participant_id) or not isinstance(capability_value, Mapping):
                raise SoakError("soak_codex_capability_incomplete")
            participants.append((conversation_id, str(participant_id), item))
            capability_material.append(capability_value)
    if len(participants) != 8:
        raise SoakError("soak_codex_participant_count_invalid")
    recovery_proof = state.provider_recovery_proof
    if recovery_proof is None:
        raise SoakError("soak_provider_recovery_proof_incomplete")
    recovery_target, recovery_identity = _prove_provider_recovery_identity(
        runtime_root,
        recovery_proof,
        participants,
    )
    first_capabilities = participants[0][2].get("capabilities")
    first_value = (
        first_capabilities.get("value") if isinstance(first_capabilities, Mapping) else None
    )
    models = _mapping_records(
        first_value.get("models") if isinstance(first_value, Mapping) else None
    )
    combinations = _goal_model_combinations(models, runtime_root=runtime_root)
    if len(combinations) < 2 or not any(effort == "max" for _, _, effort in combinations):
        raise SoakError("soak_codex_settings_coverage_unavailable", blocked=True)
    assignments: list[dict[str, str]] = []
    assigned_participants: list[tuple[str, str, str, str]] = []
    for index, (conversation_id, participant_id, _item) in enumerate(participants):
        model_id, model_name, effort = combinations[index % len(combinations)]
        _invoke_native_action(
            config,
            deps,
            conversation_id,
            participant_id,
            "settings_update",
            {"model": model_id, "effort": effort},
        )

        def settings_observed(
            item: Mapping[str, Any],
            *,
            expected_models: frozenset[str] = frozenset({model_id, model_name}),
            expected_effort: str = effort,
        ) -> bool:
            settings = _native_snapshot(item).get("settings")
            return (
                isinstance(settings, Mapping)
                and settings.get("model") in expected_models
                and settings.get("effort") == expected_effort
            )

        _wait_native_state(
            deps,
            conversation_id,
            participant_id,
            settings_observed,
            timeout_s=60.0,
            code="soak_codex_settings_not_observed",
        )
        assignments.append(
            {
                "participant": _digest_json(participant_id),
                "model": _digest_json(model_id),
                "effort": effort,
            }
        )
        assigned_participants.append((conversation_id, participant_id, model_id, effort))
    other_participants = [item for item in participants if item[:2] != recovery_target[:2]]
    if len(other_participants) < 2:
        raise SoakError("soak_codex_participant_count_invalid")
    review_room, review_participant, _ = other_participants[0]
    _invoke_native_action(
        config,
        deps,
        review_room,
        review_participant,
        "review_start",
        {"target": "uncommitted"},
        timeout_s=180.0,
    )
    recovery_room, recovery_participant, _ = recovery_target
    _invoke_native_action(
        config,
        deps,
        recovery_room,
        recovery_participant,
        "console_turn_start",
        _goal_console_turn_request(
            "Inspect the current repository boundary and produce a concise verification plan."
        ),
        timeout_s=180.0,
    )
    _wait_native_state(
        deps,
        recovery_room,
        recovery_participant,
        lambda item: _native_snapshot(item).get("active_turn") is False,
        timeout_s=300.0,
        code="soak_codex_recovered_console_turn_not_terminal",
    )
    recovery_actions = _provider_recovery_action_counts(
        runtime_root / "chat.db",
        recovery_proof,
    )
    steer_room, steer_participant, _ = other_participants[1]
    _invoke_native_action(
        config,
        deps,
        steer_room,
        steer_participant,
        "console_turn_start",
        _goal_console_turn_request(
            "Inspect the current repository boundary and produce a concise verification plan."
        ),
        timeout_s=180.0,
    )
    _invoke_native_action(
        config,
        deps,
        steer_room,
        steer_participant,
        "turn_steer",
        {"text": "Focus the verification on source-backed memory and runtime recovery guards."},
        timeout_s=180.0,
    )
    _wait_native_state(
        deps,
        steer_room,
        steer_participant,
        lambda item: _native_snapshot(item).get("active_turn") is False,
        timeout_s=300.0,
        code="soak_codex_steer_turn_not_terminal",
    )
    goal_room, goal_participant, _goal_model, _goal_effort = _select_goal_participant(
        assigned_participants,
        (
            recovery_target[:2],
            (review_room, review_participant),
            (steer_room, steer_participant),
        ),
    )
    goal_before = _codex_projection(deps, goal_room)
    before_native = goal_before.get("native_events")
    baseline_event_seq = (
        before_native.get("latest_event_seq") if isinstance(before_native, Mapping) else 0
    )
    if not isinstance(baseline_event_seq, int):
        baseline_event_seq = 0
    _invoke_native_action(
        config,
        deps,
        goal_room,
        goal_participant,
        "goal_set",
        _goal_native_request(),
        timeout_s=180.0,
    )
    goal_auto_continuations = _wait_goal_continuation(
        config,
        deps,
        goal_room,
        goal_participant,
        baseline_event_seq,
    )
    _pause_native_goal(
        config,
        deps,
        goal_room,
        goal_participant,
    )
    state.goal_memory_evidence.update(
        {
            "participants": [(room, participant) for room, participant, _ in participants],
            "goal_room": goal_room,
            "goal_participant": goal_participant,
            "settings_assignment_digest": _digest_json(
                {
                    "assignments": assignments,
                    "provider_recovery": recovery_identity | recovery_actions,
                }
            ),
            "distinct_settings_combinations": len(
                set(combinations[index % len(combinations)] for index in range(8))
            ),
            "max_effort_observed": sum(
                combinations[index % len(combinations)][2] == "max" for index in range(8)
            ),
            "capability_descriptor_digest": _digest_json(capability_material),
            "steer_actions": 1,
            "review_actions": 1,
            "goal_initial_continuation_checkpoint": goal_auto_continuations,
            "goal_model": _goal_model,
            "goal_effort": _goal_effort,
        }
    )


def _rebuild_native_event_evidence_after_cache_reset(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
) -> None:
    """Prove rebuilt native subscriptions with one real Console turn per Room."""

    raw_participants = state.goal_memory_evidence.get("participants")
    if not isinstance(raw_participants, list):
        raise SoakError("soak_codex_native_evidence_missing")
    goal_target = (
        state.goal_memory_evidence.get("goal_room"),
        state.goal_memory_evidence.get("goal_participant"),
    )
    candidates: dict[str, list[str]] = {room_id: [] for room_id in state.room_ids}
    for value in raw_participants:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and value[0] in candidates
            and _safe_id(value[1])
        ):
            candidates[str(value[0])].append(str(value[1]))
    targets: list[tuple[str, str]] = []
    for room_id in state.room_ids:
        available = candidates.get(room_id, [])
        participant_id = next(
            (item for item in available if (room_id, item) != goal_target),
            available[0] if available else None,
        )
        if participant_id is None:
            raise SoakError("soak_codex_participant_count_invalid")
        targets.append((room_id, participant_id))

    def exercise(target: tuple[str, str]) -> None:
        conversation_id, participant_id = target
        before = _codex_projection(deps, conversation_id)
        before_events = before.get("native_events")
        baseline_seq = (
            before_events.get("latest_event_seq") if isinstance(before_events, Mapping) else 0
        )
        if not isinstance(baseline_seq, int) or isinstance(baseline_seq, bool):
            baseline_seq = 0
        _invoke_native_action(
            config,
            deps,
            conversation_id,
            participant_id,
            "console_turn_start",
            _goal_console_turn_request(
                "Report one concise read-only runtime verification checkpoint."
            ),
            timeout_s=180.0,
        )
        deadline = deps.monotonic() + 300.0
        while deps.monotonic() < deadline:
            projection = _codex_projection(deps, conversation_id)
            native_events = projection.get("native_events")
            events = native_events.get("items") if isinstance(native_events, Mapping) else None
            kinds = {
                str(item["kind"])
                for item in _mapping_records(events)
                if item.get("participant_id") == participant_id
                and isinstance(item.get("event_seq"), int)
                and int(item["event_seq"]) > baseline_seq
                and isinstance(item.get("kind"), str)
            }
            if REQUIRED_NATIVE_EVENT_KINDS <= kinds:
                return
            deps.sleep(0.25)
        raise SoakError("soak_codex_post_cache_event_evidence_incomplete")

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = [executor.submit(exercise, target) for target in targets]
        for future in as_completed(futures):
            future.result()


def _goal_observation_state(
    database: Path,
    activity_ids: Sequence[str],
    participant_id: str,
) -> tuple[int, int]:
    if not activity_ids:
        return 0, 0
    placeholders = ",".join("?" for _ in activity_ids)
    with _connect_readonly(database) as conn:
        row = conn.execute(
            f"""select count(distinct o.observation_id) as observation_count,
                       count(distinct t.attempt_id) as attempt_count
                  from room_observations o
                  left join room_observation_attempts t
                    on t.observation_id = o.observation_id
                 where o.activity_id in ({placeholders}) and o.participant_id = ?""",
            (*activity_ids, participant_id),
        ).fetchone()
    return int(row["observation_count"] or 0), int(row["attempt_count"] or 0)


def _other_completed_goal_attempt_count(
    database: Path,
    activity_ids: Sequence[str],
    participant_id: str,
) -> int:
    if not activity_ids:
        return 0
    placeholders = ",".join("?" for _ in activity_ids)
    with _connect_readonly(database) as conn:
        row = conn.execute(
            f"""select count(distinct t.attempt_id)
                   from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                  where o.activity_id in ({placeholders})
                    and o.participant_id <> ? and t.state = 'completed'""",
            (*activity_ids, participant_id),
        ).fetchone()
    return int(row[0] or 0)


def _resume_goal_for_hold(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
) -> None:
    goal_room = state.goal_memory_evidence.get("goal_room")
    goal_participant = state.goal_memory_evidence.get("goal_participant")
    if not isinstance(goal_room, str) or not isinstance(goal_participant, str):
        raise SoakError("soak_codex_goal_evidence_missing")
    before = _codex_projection(deps, goal_room)
    native = before.get("native_events")
    baseline_event_seq = native.get("latest_event_seq") if isinstance(native, Mapping) else 0
    if not isinstance(baseline_event_seq, int):
        baseline_event_seq = 0
    _resume_native_goal(config, deps, goal_room, goal_participant)
    state.goal_memory_evidence["goal_auto_continuations"] = _wait_goal_continuation(
        config,
        deps,
        goal_room,
        goal_participant,
        baseline_event_seq,
    )


def _prove_goal_hold_and_release(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    correlations: Sequence[_Correlation],
) -> None:
    goal_room = state.goal_memory_evidence.get("goal_room")
    goal_participant = state.goal_memory_evidence.get("goal_participant")
    if not isinstance(goal_room, str) or not isinstance(goal_participant, str):
        raise SoakError("soak_codex_goal_evidence_missing")
    activity_ids = [item.activity_id for item in correlations if item.conversation_id == goal_room]
    if not activity_ids:
        raise SoakError("soak_codex_goal_hold_observation_missing")
    database = runtime_root / "chat.db"
    # A started peer attempt is not yet a visible peer response.  In a real
    # provider run (especially immediately after Runner recovery), completion
    # can legitimately outlive the old 30-second sampling window.  Keep proving
    # that the Goal participant has zero attempts while waiting for a durable
    # peer outcome, bounded by the product's existing 240-second first-claim
    # gate rather than weakening any result threshold.
    deadline = deps.monotonic() + min(GOAL_PEER_OUTCOME_TIMEOUT_S, config.settle_timeout_s)
    other_delivered = False
    while deps.monotonic() < deadline:
        observations, attempts = _goal_observation_state(
            database,
            activity_ids,
            goal_participant,
        )
        if attempts != 0:
            raise SoakError("soak_codex_goal_hold_claim_violation")
        other_delivered = (
            _other_completed_goal_attempt_count(database, activity_ids, goal_participant) > 0
        )
        if observations > 0 and other_delivered:
            break
        deps.sleep(0.25)
    else:
        raise SoakError("soak_codex_goal_hold_proof_timeout")
    projection_deadline = deps.monotonic() + 15.0
    peer_wait_projections = _wait_goal_hold_projection(
        deps,
        goal_room,
        root_activity_ids=activity_ids,
        goal_participant_id=goal_participant,
        deadline=projection_deadline,
    )
    if peer_wait_projections < 1:
        raise SoakError("soak_codex_goal_peer_wait_unproven")
    _pause_native_goal(config, deps, goal_room, goal_participant)
    terminal_state = "paused"
    released_at = deps.monotonic()
    while deps.monotonic() - released_at <= 30.0:
        _observations, attempts = _goal_observation_state(
            database,
            activity_ids,
            goal_participant,
        )
        if attempts > 0:
            state.goal_memory_evidence.update(
                {
                    "goal_hold_claim_violations": 0,
                    "goal_resume_count": 1,
                    "goal_resume_max_ms": round((deps.monotonic() - released_at) * 1000),
                    "other_agent_root_deliveries": int(other_delivered),
                    "peer_wait_projections": peer_wait_projections,
                    "goal_terminal_state": terminal_state,
                }
            )
            return
        deps.sleep(0.25)
    raise SoakError("soak_codex_goal_release_claim_timeout")


def _goal_manifest(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    before: RepositorySnapshot,
    *,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    executable = config.memoryos_executable
    if executable is None:
        raise SoakError("soak_memoryos_executable_required", blocked=True)
    clean_env = _clean_environment()
    top = _checked(
        deps,
        ("git", "-C", str(executable.parent), "rev-parse", "--show-toplevel"),
        cwd=config.repo_root,
        env=clean_env,
        timeout_s=20.0,
        code="soak_memoryos_repository_unavailable",
        blocked=True,
    ).stdout.strip()
    if not top:
        raise SoakError("soak_memoryos_repository_unavailable", blocked=True)
    memory_head = _checked(
        deps,
        ("git", "-C", top, "rev-parse", "HEAD"),
        cwd=config.repo_root,
        env=clean_env,
        timeout_s=20.0,
        code="soak_memoryos_repository_unavailable",
        blocked=True,
    ).stdout.strip()
    memory_status = _checked(
        deps,
        ("git", "-C", top, "status", "--porcelain=v1"),
        cwd=config.repo_root,
        env=clean_env,
        timeout_s=20.0,
        code="soak_memoryos_repository_unavailable",
        blocked=True,
    ).stdout
    ancestry = deps.run(
        (
            "git",
            "-C",
            top,
            "merge-base",
            "--is-ancestor",
            FROZEN_MEMORYOS_BASE,
            memory_head,
        ),
        cwd=config.repo_root,
        env=clean_env,
        timeout_s=20.0,
    )
    if ancestry.returncode != 0:
        raise SoakError("soak_memoryos_revision_mismatch", blocked=True)
    if memory_status.strip():
        raise SoakError("soak_memoryos_worktree_dirty", blocked=True)
    codex_version_output = _checked(
        deps,
        ("codex", "--version"),
        cwd=config.repo_root,
        env=clean_env,
        timeout_s=20.0,
        code="soak_preflight_codex_version_unavailable",
        blocked=True,
    ).stdout.strip()
    version_match = re.search(
        r"([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)",
        codex_version_output,
    )
    if version_match is None:
        raise SoakError("soak_preflight_codex_version_unavailable", blocked=True)
    capability_digest = state.goal_memory_evidence.get("capability_descriptor_digest")
    if not isinstance(capability_digest, str):
        raise SoakError("soak_codex_capability_incomplete")
    return {
        "schema_version": "room_goal_memory_soak_manifest/v1",
        "profile_id": GOAL_MEMORY_PROFILE_ID,
        "seed": 9,
        "xmuse_sha": before.head,
        "memoryos_sha": memory_head,
        "codex_version": version_match.group(1),
        "native_capability_descriptor_digest": capability_digest,
        # This digest identifies the actual G9 workload and native actions.  It does not
        # claim authorship for the already accepted G7/G8P product changes.
        "task_manifest_digest": _digest_json(
            {
                "profile": GOAL_MEMORY_PROFILE_ID,
                "rooms": 4,
                "agents": 2,
                "waves": 4,
                "faults": [
                    "codex_app_server_sigkill",
                    "runner_sigkill",
                    "memoryos_sigkill",
                    "codex_projection_cache_deleted",
                ],
                "native_actions": {
                    "review": "uncommitted",
                    "steer": "source-backed-memory-and-runtime-recovery-guards",
                    "goal": "bounded-runtime-and-memory-recovery-audit",
                },
            }
        ),
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _goal_numeric_usage(deps: SoakDependencies, room_ids: Sequence[str]) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    latest_by_participant: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for conversation_id in room_ids:
        projection = _codex_projection(deps, conversation_id)
        native_events = projection.get("native_events")
        events = native_events.get("items") if isinstance(native_events, Mapping) else None
        for event in _mapping_records(events):
            if event.get("kind") != "token_usage_updated":
                continue
            participant_id = event.get("participant_id")
            event_seq = event.get("event_seq")
            usage = event.get("usage")
            total = usage.get("total") if isinstance(usage, Mapping) else None
            if (
                not isinstance(participant_id, str)
                or not isinstance(event_seq, int)
                or not isinstance(total, Mapping)
            ):
                continue
            prior = latest_by_participant.get(participant_id)
            if prior is None or event_seq > prior[0]:
                latest_by_participant[participant_id] = (event_seq, total)
    for _seq, usage in latest_by_participant.values():
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
    return totals


def _goal_memory_contract_evidence(
    database: Path,
    room_ids: Sequence[str],
    *,
    state: _LiveState,
) -> dict[str, int]:
    proof = state.memory_fault_proof
    if proof is None:
        raise SoakError("soak_memory_recovery_proof_incomplete")
    base = _memory_evidence(
        database,
        room_ids,
        enabled=True,
        restart_count=state.memory_restart_count,
        proof=proof,
    )
    from xmuse.memoryos_evidence import _MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES
    from xmuse.memoryos_http_client import _MEMORYOS_CONTEXT_HTTP_MAX_BYTES
    from xmuse_core.chat.room_memory_runtime import ROOM_MEMORY_MAX_RESPONSE_BYTES

    # _memory_evidence above re-proves every successful source against chat.db and raises
    # on cross-Room or unbound evidence.  These are the production enforcement ceilings,
    # deliberately reported as upper bounds rather than fabricated observed byte counts.
    return {
        "compact_response_upper_bound_bytes": _MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES,
        "raw_response_upper_bound_bytes": _MEMORYOS_CONTEXT_HTTP_MAX_BYTES,
        "accepted_evidence_upper_bound_bytes": ROOM_MEMORY_MAX_RESPONSE_BYTES,
        "source_ref_count": int(base["recall_source_refs"]),
        "source_proof_failures": 0,
        "restart_count": int(base["restart_count"]),
        "outbox_pending": int(base["outbox_pending"]),
        "outbox_conflict": int(base["outbox_conflict"]),
        "room_readiness_degraded": 0,
        "settlement_blocked": 0,
    }


def _map_goal_counts(base: Mapping[str, Any], state: _LiveState) -> dict[str, int]:
    counts = base["counts"]
    violations = base["violations"]
    residual = base["residual"]
    return {
        "correlations": int(counts["correlations"]),
        "settled_correlations": int(counts["settled_correlations"]),
        "attempts": int(counts["attempts"]),
        "outcomes": int(counts["outcomes"]),
        "duplicate_outcomes": int(violations["duplicate_outcome"]),
        "cross_room_identity": int(violations["cross_room_identity"]),
        "cross_room_causality": int(violations["cross_room_causality"]),
        "cross_room_source": 0,
        "provider_orphans": int(violations["provider_orphans"]),
        "live_leases": int(residual["live_leases"]),
        "cleanup_pending": int(residual["cleanup_pending"]),
        "recovery_pending": int(residual["recovery_pending"]),
        "exhausted": int(residual["exhausted"]),
        "max_active_deliveries": state.max_active_deliveries,
    }


def _map_goal_faults(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expected = [
        ("codex_app_server_sigkill", "codex_app_server_cleanup_confirmed", False),
        ("runner_sigkill", "runner_reconciled", True),
        ("memoryos_sigkill", "memoryos_reconciled", True),
        ("codex_projection_cache_delete", "codex_projection_cache_rebuilt", True),
    ]
    if len(events) != len(expected):
        raise SoakError("soak_fault_sequence_incomplete")
    result: list[dict[str, Any]] = []
    for seq, (event, (kind, reason, managed)) in enumerate(zip(events, expected, strict=True), 1):
        if (
            event.get("kind") != kind
            or event.get("reason_code") != reason
            or event.get("managed_reconcile") is not managed
            or event.get("recovery_wave_settled") is not True
        ):
            raise SoakError("soak_fault_sequence_invalid")
        result.append(
            {
                "seq": seq,
                "kind": "codex_projection_cache_deleted" if seq == 4 else kind,
                "reason_code": reason,
                "recovery_ms": int(event["recovery_ms"]),
                "active_delivery_count": int(event.get("active_delivery_count") or 0),
                "runner_count": int(event["runner_count"]),
                "mcp_count": int(event["mcp_count"]),
            }
        )
    return result


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


def _prepare_full_local_memory_cache(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    env: Mapping[str, str],
) -> None:
    """Prove the offline FastEmbed model before starting the managed sidecar.

    The supervisor deliberately pins FastEmbed to a root-scoped cache and starts
    the sidecar with all model-network access disabled.  A fresh soak root is
    therefore empty during preflight, then receives only this bounded local
    capability proof before Workroom starts.  This keeps a missing model a
    deterministic preflight blocker rather than a misleading degraded run.
    """

    if config.profile_id not in {GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}:
        return
    executable = config.memoryos_executable
    if executable is None:
        raise SoakError("soak_memoryos_executable_required", blocked=True)
    python = executable.parent / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise SoakError("soak_memoryos_python_unavailable", blocked=True)
    cache = runtime_root / "runtime" / "fastembed-cache"
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise SoakError("soak_memoryos_fastembed_cache_unavailable", blocked=True) from exc
    source_value = env.get(SOAK_FASTEMBED_CACHE_SOURCE_ENV)
    if not isinstance(source_value, str) or not source_value.strip():
        raise SoakError("soak_memoryos_fastembed_cache_source_required", blocked=True)
    _copy_proven_fastembed_cache(Path(source_value), cache)
    proof = (
        "from pathlib import Path\n"
        "import sys\n"
        "from fastembed import TextEmbedding\n"
        "cache = Path(sys.argv[1])\n"
        f"model = TextEmbedding(model_name={FULL_LOCAL_FASTEMBED_MODEL!r}, cache_dir=str(cache))\n"
        "next(model.embed(['xmuse full-local capability proof']), None)\n"
    )
    result = deps.run(
        (str(python), "-c", proof, str(cache)),
        cwd=config.repo_root,
        env={
            **env,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MEMORYOS_FASTEMBED_OFFLINE": "1",
            "FASTEMBED_CACHE_PATH": str(cache),
        },
        timeout_s=900.0,
    )
    if result.returncode != 0:
        raise SoakError("soak_memoryos_fastembed_cache_unavailable", blocked=True)


def _copy_proven_fastembed_cache(source: Path, destination: Path) -> None:
    """Copy one bounded, locally proven model cache without following escapes."""

    try:
        source = source.expanduser().resolve(strict=True)
        destination = destination.resolve(strict=True)
        source_stat = source.stat()
        destination_stat = destination.stat()
    except OSError as exc:
        raise SoakError("soak_memoryos_fastembed_cache_source_invalid", blocked=True) from exc
    if (
        not stat.S_ISDIR(source_stat.st_mode)
        or not stat.S_ISDIR(destination_stat.st_mode)
        or source == destination
        or source_stat.st_uid != os.getuid()
        or destination_stat.st_uid != os.getuid()
    ):
        raise SoakError("soak_memoryos_fastembed_cache_source_invalid", blocked=True)
    entries = 0
    total_bytes = 0
    for candidate in source.rglob("*"):
        entries += 1
        if entries > MAX_FASTEMBED_CACHE_ENTRIES:
            raise SoakError("soak_memoryos_fastembed_cache_source_unbounded", blocked=True)
        try:
            item = candidate.lstat()
        except OSError as exc:
            raise SoakError("soak_memoryos_fastembed_cache_source_invalid", blocked=True) from exc
        if stat.S_ISLNK(item.st_mode):
            try:
                target = candidate.resolve(strict=True)
                target.relative_to(source)
            except (OSError, ValueError) as exc:
                raise SoakError(
                    "soak_memoryos_fastembed_cache_source_invalid", blocked=True
                ) from exc
            if not target.is_file():
                raise SoakError("soak_memoryos_fastembed_cache_source_invalid", blocked=True)
            continue
        if stat.S_ISDIR(item.st_mode):
            continue
        if not stat.S_ISREG(item.st_mode) or candidate.name.endswith(".incomplete"):
            raise SoakError("soak_memoryos_fastembed_cache_source_invalid", blocked=True)
        total_bytes += item.st_size
        if total_bytes > MAX_FASTEMBED_CACHE_BYTES:
            raise SoakError("soak_memoryos_fastembed_cache_source_unbounded", blocked=True)
    try:
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
    except OSError as exc:
        raise SoakError("soak_memoryos_fastembed_cache_unavailable", blocked=True) from exc


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


def _wait_for_runtime_idle(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    deadline = deps.monotonic() + min(120.0, config.settle_timeout_s)
    while deps.monotonic() < deadline:
        status = _workroom_status(config, deps, runtime_root, env)
        owned_counts = deps.runtime_service_counts(runtime_root)
        if not _required_runtime_ready(status, owned_counts):
            raise SoakError("soak_runtime_idle_readiness_lost")
        if _active_deliveries(status) == 0:
            return status
        _sample_runtime(config, deps, state, runtime_root, env, status=status)
        deps.sleep(0.25)
    raise SoakError("soak_runtime_idle_timeout")


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
    if (
        config.profile_id in {"live-soak", GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}
        and not config.confirm_provider_cost
    ):
        raise SoakError("soak_provider_cost_confirmation_required", blocked=True)
    if config.profile_id in {"memory-recovery", GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}:
        executable = config.memoryos_executable
        if (
            executable is None
            or not executable.expanduser().resolve().is_file()
            or not os.access(executable.expanduser().resolve(), os.X_OK)
        ):
            raise SoakError("soak_memoryos_executable_required", blocked=True)
        if config.profile_id in {GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}:
            assert executable is not None
            try:
                executable_stat = executable.expanduser().lstat()
            except OSError as exc:
                raise SoakError("soak_memoryos_executable_required", blocked=True) from exc
            if (
                stat.S_ISLNK(executable_stat.st_mode)
                or not stat.S_ISREG(executable_stat.st_mode)
                or executable_stat.st_nlink != 1
            ):
                raise SoakError("soak_memoryos_executable_unsafe", blocked=True)
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
        ports = [
            ("127.0.0.1", 3000, "frontend"),
            ("127.0.0.1", 8201, "chat_api"),
        ]
        if config.profile_id in {GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}:
            ports.extend(
                [
                    ("127.0.0.1", 8100, "room_mcp"),
                    ("127.0.0.1", 8301, "memoryos"),
                ]
            )
        for host, port, name in ports:
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
    if config.profile_id in {"memory-recovery", GOAL_MEMORY_PROFILE_ID, *ENDURANCE_PROFILE_IDS}:
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
    if spec.profile_id == "memory-recovery":
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
        client_request_id = f"soak_post_{uuid.uuid4().hex}"
        category: str | None = None
        if spec.profile_id in ENDURANCE_PROFILE_IDS:
            category, message = ENDURANCE_PROMPT_CATEGORIES[
                (wave * spec.room_count + index) % len(ENDURANCE_PROMPT_CATEGORIES)
            ]
        else:
            message = (
                (
                    "Memory recovery phase 1 anchor XMUSE_MEMORY_RECOVERY_ANCHOR_V1: "
                    "preserve the source-backed durable fact cobalt-orchid-17 for this "
                    f"Room (sample {index + 1}); submit one concise outcome."
                )
                if spec.profile_id == "memory-recovery" and wave == 0
                else (
                    "Memory recovery phase 2: use source-backed archival evidence to recall "
                    "XMUSE_MEMORY_RECOVERY_ANCHOR_V1 and cobalt-orchid-17 for this Room; "
                    "submit one concise outcome."
                )
                if spec.profile_id == "memory-recovery"
                else (
                    "Goal Memory soak wave 1: preserve the source-backed fact "
                    "G9_COBALT_ORCHID_17 for this Room, independently inspect the runtime "
                    "boundary, and submit one concise outcome without editing files."
                )
                if spec.profile_id == GOAL_MEMORY_PROFILE_ID and wave == 0
                else (
                    f"Goal Memory soak wave {wave + 1}: use only re-provable Room or archival "
                    "sources when relevant, verify runtime recovery state, and submit one "
                    "concise outcome without editing files."
                )
                if spec.profile_id == GOAL_MEMORY_PROFILE_ID
                else (
                    f"Soak wave {wave + 1}, item {index + 1}: independently inspect the "
                    "durable Room state and submit one concise outcome; do not edit files."
                )
            )
        try:
            response = _post_room_message_with_replay(
                deps,
                room_id=room_id,
                message=message,
                client_request_id=client_request_id,
            )
        finally:
            with meter_lock:
                active_posts -= 1
        activity_id = response.payload.get("activity_id") if response.payload else None
        if response.status != 201 or not _safe_id(activity_id):
            raise SoakError("soak_room_post_failed")
        if category is not None:
            with meter_lock:
                state.endurance_prompt_categories[category] += 1
        return _Correlation(room_id, str(activity_id), started)

    correlations: list[_Correlation] = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [pool.submit(post, index, room_id) for index, room_id in enumerate(targets)]
        for future in as_completed(futures):
            correlations.append(future.result())
    state.correlations.extend(correlations)
    return correlations


def _post_room_message_with_replay(
    deps: SoakDependencies,
    *,
    room_id: str,
    message: str,
    client_request_id: str,
) -> HttpJsonResponse:
    """Resolve one ambiguous proxy failure through the durable idempotency key.

    The Room write may commit before the fixed Next proxy returns its receipt.  A
    bounded replay with the *same* request ID recovers that receipt without
    creating another Human activity.  Definitive client/guard failures are not
    replayed, and a second ambiguous failure remains a hard soak failure.
    """
    payload = {"message": message, "client_request_id": client_request_id}
    ambiguous_statuses = {499, 502, 503, 504}
    for replay in range(2):
        try:
            response = deps.http_json(
                "POST",
                f"{FRONTEND_URL}/api/rooms/{room_id}/messages",
                payload,
                timeout_s=30.0,
            )
        except SoakError as exc:
            if replay == 0 and exc.code == "soak_http_unavailable":
                deps.sleep(0.25)
                continue
            raise
        activity_id = response.payload.get("activity_id") if response.payload else None
        if response.status == 201 and _safe_id(activity_id):
            return response
        if replay == 0 and response.status in ambiguous_statuses:
            deps.sleep(0.25)
            continue
        return response
    raise AssertionError("bounded Room message replay did not terminate")


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= 256


def _pause_runner(
    config: SoakConfig,
    deps: SoakDependencies,
    runtime_root: Path,
    env: Mapping[str, str],
) -> ProcessBinding:
    status = _workroom_status(config, deps, runtime_root, env)
    runner = _service(status, "room_runner")
    binding = deps.runner_process_binding(runtime_root)
    if (
        binding is None
        or runner.get("ready") is not True
        or deps.process_start_identity(binding.pid) != binding.start_identity
    ):
        raise SoakError("soak_runner_pause_identity_unavailable")
    try:
        deps.signal_pid(binding.pid, signal.SIGSTOP)
    except OSError as exc:
        raise SoakError("soak_runner_pause_failed") from exc
    return binding


def _resume_runner(deps: SoakDependencies, binding: ProcessBinding) -> None:
    if deps.process_start_identity(binding.pid) != binding.start_identity:
        raise SoakError("soak_runner_resume_identity_lost")
    try:
        deps.signal_pid(binding.pid, signal.SIGCONT)
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
) -> _ProviderFaultTarget | None:
    if not bindings:
        return None
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            """select t.attempt_id, t.god_session_id, t.conversation_id,
                      t.participant_id,
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
            return _ProviderFaultTarget(
                attempt_id=str(row["attempt_id"]),
                god_session_id=god_session_id,
                conversation_id=str(row["conversation_id"]),
                participant_id=str(row["participant_id"]),
                binding=binding,
            )
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


def _retry_exhausted_endurance_observations(
    deps: SoakDependencies,
    state: _LiveState,
    database: Path,
    correlations: Sequence[_Correlation],
) -> None:
    correlation_ids = set(_correlation_ids(database, correlations).values())
    if not correlation_ids:
        return
    placeholders = ",".join("?" for _ in correlation_ids)
    with _connect_readonly(database) as conn:
        rows = conn.execute(
            f"""select o.conversation_id, o.observation_id
                  from room_observations o
                  join room_activities a on a.activity_id = o.activity_id
                 where a.correlation_id in ({placeholders})
                   and o.control_state = 'exhausted'""",
            tuple(sorted(correlation_ids)),
        ).fetchall()
    by_room: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        observation_id = str(row["observation_id"])
        if observation_id not in state.endurance_retried_observations:
            by_room[str(row["conversation_id"])].add(observation_id)
    for conversation_id, expected_observations in by_room.items():
        projection = _room_projection(deps, conversation_id)
        for participant in _mapping_records(projection.get("participants")):
            frontier = participant.get("frontier")
            if not isinstance(frontier, Mapping):
                continue
            raw_observation_id = frontier.get("observation_id")
            actions = frontier.get("actions")
            retry = actions.get("retry") if isinstance(actions, Mapping) else None
            if (
                not isinstance(raw_observation_id, str)
                or raw_observation_id not in expected_observations
                or not isinstance(retry, Mapping)
                or retry.get("available") is not True
                or retry.get("href")
                != f"/api/chat/operator/room-observations/{raw_observation_id}/retry"
            ):
                continue
            observation_id = raw_observation_id
            payload = {
                "client_action_id": "soak_retry_"
                + hashlib.sha256(observation_id.encode()).hexdigest()[:24],
                "expected_state": retry.get("expected_state"),
                "expected_attempt_count": retry.get("expected_attempt_count"),
                "expected_control_seq": retry.get("expected_control_seq"),
            }
            response = deps.http_json(
                "POST",
                f"{FRONTEND_URL}/api/room-observations/{observation_id}/retry",
                payload,
                timeout_s=30.0,
            )
            if response.status in {200, 201, 202}:
                state.endurance_retried_observations.add(observation_id)
            elif response.status != 409:
                raise SoakError("soak_endurance_retry_failed")


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
        if config.profile_id in ENDURANCE_PROFILE_IDS:
            _retry_exhausted_endurance_observations(deps, state, database, correlations)
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
    recovery_proof: _ProviderRecoveryProof | None = None
    while deps.monotonic() < deadline:
        bindings = deps.provider_bindings(runtime_root)
        selected = _active_provider_binding(
            runtime_root / "chat.db",
            bindings,
            preferred_conversation_id=state.room_ids[0] if state.room_ids else None,
            require_pending_followup=bool(state.room_ids),
        )
        owned_codex = set(deps.runtime_provider_pids(runtime_root))
        if selected is not None and selected.binding.pid in owned_codex:
            candidate_target = _provider_signal_target(
                selected.binding,
                tuple(owned_codex),
                read_identity=deps.process_start_identity,
            )
            if candidate_target is not None:
                target_attempt_id = selected.attempt_id
                registry_binding = selected.binding
                signal_target = candidate_target
                if config.profile_id == GOAL_MEMORY_PROFILE_ID:
                    registered = _registered_god_session_private_binding(
                        runtime_root,
                        conversation_id=selected.conversation_id,
                        participant_id=selected.participant_id,
                    )
                    projection = _codex_projection(deps, selected.conversation_id)
                    participant = _participant_view(projection, selected.participant_id)
                    snapshot = _native_snapshot(participant) if participant is not None else None
                    guards = snapshot.get("guards") if isinstance(snapshot, Mapping) else None
                    session_guard = guards.get("session") if isinstance(guards, Mapping) else None
                    if (
                        registered is None
                        or registered[0] != selected.god_session_id
                        or not isinstance(session_guard, str)
                        or re.fullmatch(r"sha256:[0-9a-f]{64}", session_guard) is None
                    ):
                        raise SoakError("soak_provider_fault_identity_unavailable")
                    recovery_proof = _ProviderRecoveryProof(
                        conversation_id=selected.conversation_id,
                        participant_id=selected.participant_id,
                        god_session_id=selected.god_session_id,
                        provider_session_id_before=registered[1],
                        session_guard_before=session_guard,
                    )
                break
        deps.sleep(0.1)
    if registry_binding is None or signal_target is None or target_attempt_id is None:
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
    if config.profile_id == GOAL_MEMORY_PROFILE_ID:
        if recovery_proof is None:
            raise SoakError("soak_provider_recovery_proof_incomplete")
        state.provider_recovery_proof = recovery_proof
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
    private = deps.runner_runtime_binding(runtime_root)
    if private is None:
        raise SoakError("soak_runner_fault_identity_unavailable")
    binding = private.process
    boot = private.boot_id
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
            owned_counts = deps.runtime_service_counts(runtime_root)
            current_private = deps.runner_runtime_binding(runtime_root)
            if (
                _required_runtime_ready(candidate, owned_counts)
                and current_private is not None
                and current_private.process != binding
                and current_private.boot_id != boot
            ):
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


def _safe_projection_cache_leaf(runtime_root: Path, candidate: Path) -> None:
    expected = runtime_root / "runtime" / "room-codex-projection.sqlite3"
    if candidate != expected:
        raise SoakError("soak_projection_cache_path_invalid")
    try:
        root_stat = runtime_root.stat()
        parent_stat = candidate.parent.lstat()
        leaf_stat = candidate.lstat()
    except OSError as exc:
        raise SoakError("soak_projection_cache_unavailable") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or candidate.parent.resolve() != expected.parent
        or stat.S_ISLNK(leaf_stat.st_mode)
        or not stat.S_ISREG(leaf_stat.st_mode)
        or leaf_stat.st_nlink != 1
        or leaf_stat.st_uid != root_stat.st_uid
    ):
        raise SoakError("soak_projection_cache_unsafe")


def _unlink_projection_cache_leaf(runtime_root: Path) -> None:
    cache = runtime_root / "runtime" / "room-codex-projection.sqlite3"
    _safe_projection_cache_leaf(runtime_root, cache)
    candidates = (
        cache,
        cache.with_name(f"{cache.name}-wal"),
        cache.with_name(f"{cache.name}-shm"),
    )
    for candidate in candidates:
        if candidate != cache and not candidate.exists():
            continue
        if candidate == cache:
            _safe_projection_cache_leaf(runtime_root, candidate)
        else:
            _safe_cache_sidecar(runtime_root, candidate)
        candidate.unlink()


def _safe_cache_sidecar(runtime_root: Path, candidate: Path) -> None:
    cache = runtime_root / "runtime" / "room-codex-projection.sqlite3"
    if candidate not in {
        cache.with_name(f"{cache.name}-wal"),
        cache.with_name(f"{cache.name}-shm"),
    }:
        raise SoakError("soak_projection_cache_path_invalid")
    try:
        root_stat = runtime_root.stat()
        item = candidate.lstat()
    except OSError as exc:
        raise SoakError("soak_projection_cache_unavailable") from exc
    if (
        stat.S_ISLNK(item.st_mode)
        or not stat.S_ISREG(item.st_mode)
        or item.st_nlink != 1
        or item.st_uid != root_stat.st_uid
    ):
        raise SoakError("soak_projection_cache_unsafe")


def _reset_projection_cache_and_wait_recovery(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
) -> _PendingChaosEvent:
    from xmuse.chat_api_runtime import (
        _locked_workroom_runtime_start,
        _stop_workroom_room_runtime_locked,
        _workroom_room_runtime_config,
    )

    status = _wait_for_runtime_idle(config, deps, state, runtime_root, env)
    private = deps.runner_runtime_binding(runtime_root)
    if private is None or _active_deliveries(status) != 0:
        raise SoakError("soak_projection_cache_fault_identity_unavailable")
    binding = private.process
    boot = private.boot_id
    started = deps.monotonic()
    with _locked_workroom_runtime_start(runtime_root):
        current_status = _workroom_status(config, deps, runtime_root, env)
        current_private = deps.runner_runtime_binding(runtime_root)
        if current_private != private or _active_deliveries(current_status) != 0:
            raise SoakError("soak_projection_cache_fault_identity_lost")
        runtime_config = _workroom_room_runtime_config(
            runtime_root,
            config.repo_root,
        )
        stopped = _stop_workroom_room_runtime_locked(
            runtime_root,
            generation=runtime_config.generation,
        )
        if stopped.get("state") != "stopped":
            raise SoakError("soak_projection_cache_runner_stop_failed")
        _unlink_projection_cache_leaf(runtime_root)
    # The managed Chat API owns the Room Runner environment, including the optional
    # server-only MemoryOS binding.  Let its reconcile loop rebuild the stopped runtime;
    # starting a child from this unprivileged soak process would silently drop those
    # capabilities and would not exercise the production recovery path.
    deadline = started + MAX_FAULT_RECOVERY_MS / 1000
    recovered: dict[str, Any] | None = None
    recovered_counts: Mapping[str, int] | None = None
    while deps.monotonic() < deadline:
        try:
            candidate = _workroom_status(config, deps, runtime_root, env)
            owned_counts = deps.runtime_service_counts(runtime_root)
            current_private = deps.runner_runtime_binding(runtime_root)
            if (
                _required_runtime_ready(candidate, owned_counts)
                and current_private is not None
                and current_private.process != binding
                and current_private.boot_id != boot
            ):
                recovered = candidate
                recovered_counts = owned_counts
                break
        except SoakError:
            pass
        _sample_runtime(config, deps, state, runtime_root, env)
        deps.sleep(0.25)
    if recovered is None or recovered_counts is None:
        raise SoakError("soak_projection_cache_recovery_timeout")
    return _PendingChaosEvent(
        kind="codex_projection_cache_delete",
        reason_code="codex_projection_cache_rebuilt",
        started_at=started,
        run_started_at=run_started_at,
        recovery_ms=round((deps.monotonic() - started) * 1000),
        status=recovered,
        active_delivery_count=0,
        managed_reconcile=True,
        runner_count=int(recovered_counts["room_runner"]),
        mcp_count=int(recovered_counts["room_mcp"]),
    )


def _safe_agent_stream_cache_leaf(runtime_root: Path, candidate: Path) -> None:
    expected = runtime_root / "runtime" / "room-agent-streams.sqlite3"
    if candidate != expected:
        raise SoakError("soak_agent_stream_cache_path_invalid")
    try:
        root_stat = runtime_root.stat()
        parent_stat = candidate.parent.lstat()
        leaf_stat = candidate.lstat()
    except OSError as exc:
        raise SoakError("soak_agent_stream_cache_unavailable") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or candidate.parent.resolve() != expected.parent
        or stat.S_ISLNK(leaf_stat.st_mode)
        or not stat.S_ISREG(leaf_stat.st_mode)
        or leaf_stat.st_nlink != 1
        or leaf_stat.st_uid != root_stat.st_uid
    ):
        raise SoakError("soak_agent_stream_cache_unsafe")


def _safe_agent_stream_cache_sidecar(runtime_root: Path, candidate: Path) -> None:
    cache = runtime_root / "runtime" / "room-agent-streams.sqlite3"
    if candidate not in {
        cache.with_name(f"{cache.name}-wal"),
        cache.with_name(f"{cache.name}-shm"),
    }:
        raise SoakError("soak_agent_stream_cache_path_invalid")
    try:
        root_stat = runtime_root.stat()
        item = candidate.lstat()
    except OSError as exc:
        raise SoakError("soak_agent_stream_cache_unavailable") from exc
    if (
        stat.S_ISLNK(item.st_mode)
        or not stat.S_ISREG(item.st_mode)
        or item.st_nlink != 1
        or item.st_uid != root_stat.st_uid
    ):
        raise SoakError("soak_agent_stream_cache_unsafe")


def _agent_stream_cache_epoch(runtime_root: Path) -> str:
    cache = runtime_root / "runtime" / "room-agent-streams.sqlite3"
    _safe_agent_stream_cache_leaf(runtime_root, cache)
    try:
        with _connect_readonly(cache) as conn:
            row = conn.execute(
                "select schema_version, epoch from stream_meta where singleton = 1"
            ).fetchone()
    except sqlite3.Error as exc:
        raise SoakError("soak_agent_stream_cache_unavailable") from exc
    if row is None or row["schema_version"] != "room_agent_stream_cache/v1":
        raise SoakError("soak_agent_stream_cache_unavailable")
    epoch = row["epoch"]
    if not _safe_id(epoch):
        raise SoakError("soak_agent_stream_cache_epoch_invalid")
    return str(epoch)


def _unlink_agent_stream_cache(runtime_root: Path) -> None:
    cache = runtime_root / "runtime" / "room-agent-streams.sqlite3"
    _safe_agent_stream_cache_leaf(runtime_root, cache)
    for candidate in (
        cache,
        cache.with_name(f"{cache.name}-wal"),
        cache.with_name(f"{cache.name}-shm"),
    ):
        if candidate != cache and not candidate.exists():
            continue
        if candidate == cache:
            _safe_agent_stream_cache_leaf(runtime_root, candidate)
        else:
            _safe_agent_stream_cache_sidecar(runtime_root, candidate)
        candidate.unlink()


def _reset_agent_stream_cache_and_wait_recovery(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    runtime_root: Path,
    env: Mapping[str, str],
    *,
    run_started_at: float,
) -> _PendingChaosEvent:
    from xmuse.chat_api_runtime import (
        _locked_workroom_runtime_start,
        _stop_workroom_room_runtime_locked,
        _workroom_room_runtime_config,
    )

    status = _wait_for_runtime_idle(config, deps, state, runtime_root, env)
    private = deps.runner_runtime_binding(runtime_root)
    if private is None or _active_deliveries(status) != 0:
        raise SoakError("soak_agent_stream_cache_fault_identity_unavailable")
    binding = private.process
    boot = private.boot_id
    epoch_before = _agent_stream_cache_epoch(runtime_root)
    started = deps.monotonic()
    with _locked_workroom_runtime_start(runtime_root):
        current_status = _workroom_status(config, deps, runtime_root, env)
        current_private = deps.runner_runtime_binding(runtime_root)
        if current_private != private or _active_deliveries(current_status) != 0:
            raise SoakError("soak_agent_stream_cache_fault_identity_lost")
        runtime_config = _workroom_room_runtime_config(runtime_root, config.repo_root)
        stopped = _stop_workroom_room_runtime_locked(
            runtime_root,
            generation=runtime_config.generation,
        )
        if stopped.get("state") != "stopped":
            raise SoakError("soak_agent_stream_cache_runner_stop_failed")
        if deps.process_start_identity(binding.pid) == binding.start_identity:
            raise SoakError("soak_agent_stream_cache_runner_still_live")
        _unlink_agent_stream_cache(runtime_root)
    deadline = started + MAX_FAULT_RECOVERY_MS / 1000
    recovered: dict[str, Any] | None = None
    recovered_counts: Mapping[str, int] | None = None
    while deps.monotonic() < deadline:
        try:
            candidate = _workroom_status(config, deps, runtime_root, env)
            owned_counts = deps.runtime_service_counts(runtime_root)
            current_private = deps.runner_runtime_binding(runtime_root)
            if (
                _required_runtime_ready(candidate, owned_counts)
                and current_private is not None
                and current_private.process != binding
                and current_private.boot_id != boot
                and _agent_stream_cache_epoch(runtime_root) != epoch_before
            ):
                recovered = candidate
                recovered_counts = owned_counts
                break
        except SoakError:
            pass
        _sample_runtime(config, deps, state, runtime_root, env)
        deps.sleep(0.25)
    if recovered is None or recovered_counts is None:
        raise SoakError("soak_agent_stream_cache_recovery_timeout")
    return _PendingChaosEvent(
        kind="agent_stream_cache_delete",
        reason_code="agent_stream_cache_epoch_rotated",
        started_at=started,
        run_started_at=run_started_at,
        recovery_ms=round((deps.monotonic() - started) * 1000),
        status=recovered,
        active_delivery_count=0,
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
    if request.goal_memory:
        browser_env["XMUSE_SOAK_GOAL_MEMORY"] = "1"
        browser_env["XMUSE_SOAK_HEADED"] = "1"
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


def _verify_goal_browser(
    config: SoakConfig,
    deps: SoakDependencies,
    state: _LiveState,
    artifact_dir: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    request = BrowserVerificationRequest(
        repo_root=config.repo_root,
        frontend_url=FRONTEND_URL,
        room_ids=tuple(state.room_ids),
        artifact_dir=artifact_dir,
        timeout_s=config.browser_timeout_s,
        environment=env,
        goal_memory=True,
    )
    payload = (
        deps.browser_verifier(request)
        if deps.browser_verifier is not None
        else _default_browser_verify(request, deps)
    )
    expected = {"schema_version", "consumer", "headed", "viewports", "digest"}
    if (
        set(payload) != expected
        or payload.get("schema_version") != GOAL_BROWSER_EVIDENCE_SCHEMA
        or payload.get("consumer") != GOAL_BROWSER_CONSUMER
        or payload.get("headed") is not True
        or not isinstance(payload.get("viewports"), Mapping)
    ):
        raise SoakError("soak_browser_evidence_invalid")
    viewports = payload["viewports"]
    expected_viewports = {
        "640x900": (640, 900),
        "1280x720": (1280, 720),
        "1440x900": (1440, 900),
    }
    if set(viewports) != set(expected_viewports):
        raise SoakError("soak_browser_evidence_invalid")
    expected_item_keys = {
        "width",
        "height",
        "room_count",
        "refresh_count",
        "console_error_count",
        "page_error_count",
        "http_5xx_count",
        "native_snapshot_count",
        "native_capabilities_count",
        "native_event_count",
        "native_event_kind_count",
        "history_partial_count",
        "digest",
    }
    mapped: list[dict[str, int]] = []
    for key, dimensions in expected_viewports.items():
        item = viewports.get(key)
        if not isinstance(item, Mapping) or set(item) != expected_item_keys:
            raise SoakError("soak_browser_evidence_invalid")
        numeric = {name: item.get(name) for name in expected_item_keys - {"digest"}}
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in numeric.values()
        ):
            raise SoakError("soak_browser_evidence_invalid")
        digest = item.get("digest")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            or digest != _canonical_digest_json(numeric)
        ):
            raise SoakError("soak_browser_evidence_invalid")
        if (
            (numeric["width"], numeric["height"]) != dimensions
            or numeric["room_count"] != len(state.room_ids)
            or numeric["refresh_count"] != len(state.room_ids)
            or numeric["console_error_count"] != 0
            or numeric["page_error_count"] != 0
            or numeric["http_5xx_count"] != 0
            or numeric["native_snapshot_count"] != len(state.room_ids) * 2
            or numeric["native_capabilities_count"] != len(state.room_ids) * 2
            or cast(int, numeric["native_event_count"]) <= 0
            or cast(int, numeric["native_event_kind_count"]) < len(REQUIRED_NATIVE_EVENT_KINDS)
            or numeric["history_partial_count"] != len(state.room_ids) * 2
        ):
            raise SoakError("soak_browser_evidence_invalid")
        mapped.append(
            {
                "width": dimensions[0],
                "height": dimensions[1],
                "refreshes": numeric["refresh_count"],
                "console_errors": numeric["console_error_count"],
                "page_errors": numeric["page_error_count"],
                "current_state_available": min(
                    numeric["native_snapshot_count"],
                    numeric["native_capabilities_count"],
                ),
                "history_fabricated": 0,
            }
        )
    top_digest = _canonical_digest_json(
        {
            "consumer": GOAL_BROWSER_CONSUMER,
            "headed": True,
            "viewports": viewports,
        }
    )
    if payload.get("digest") != top_digest:
        raise SoakError("soak_browser_evidence_invalid")
    return {"headed": True, "viewports": mapped}


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
    if spec.profile_id == ENDURANCE_PROFILE_ID:
        # Fault waves are fixed at 0/24/48/72/96 minutes.  The system then
        # remains under observation until the 120-minute duration boundary.
        offsets = [index * 24.0 * 60.0 for index in range(spec.wave_count)]
    else:
        offsets = [
            (spec.minimum_duration_s * index / (spec.wave_count - 1))
            if spec.wave_count > 1
            else 0.0
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
        if spec.profile_id in ENDURANCE_PROFILE_IDS and wave == 2:
            state.memory_fault_proof = _begin_memoryos_fault(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
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
        elif (
            wave == 1 and spec.memory_recovery and spec.profile_id not in ENDURANCE_PROFILE_IDS
        ) or (wave == 2 and spec.profile_id in ENDURANCE_PROFILE_IDS):
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
        if wave == 0 and (not spec.memory_recovery or spec.profile_id in ENDURANCE_PROFILE_IDS):
            wave_event = _kill_one_provider(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
        if wave == 1 and (not spec.memory_recovery or spec.profile_id in ENDURANCE_PROFILE_IDS):
            wave_event = _kill_runner_and_wait_recovery(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
        _wait_wave_settled(config, deps, state, runtime_root, env, correlations)
        if wave == 3 and spec.profile_id in ENDURANCE_PROFILE_IDS:
            wave_event = _reset_agent_stream_cache_and_wait_recovery(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
        if wave_event is not None:
            _record_chaos(
                state,
                event=wave_event,
                recovery_wave_settled=True,
            )
        if wave in {1, 2} and memory_event is not None:
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
            if spec.memory_recovery and spec.profile_id not in ENDURANCE_PROFILE_IDS:
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
    if spec.profile_id in ENDURANCE_PROFILE_IDS:
        expected_categories = {category for category, _message in ENDURANCE_PROMPT_CATEGORIES}
        if (
            set(state.endurance_prompt_categories) != expected_categories
            or sum(state.endurance_prompt_categories.values())
            != spec.room_count * spec.human_turns_per_room
            or any(count <= 0 for count in state.endurance_prompt_categories.values())
        ):
            raise SoakError("soak_endurance_prompt_coverage_incomplete")
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


def _run_goal_memory_live(
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
    offsets = [0.0, 0.0, spec.minimum_duration_s / 2, spec.minimum_duration_s]
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
        if wave == 3:
            cache_event = _reset_projection_cache_and_wait_recovery(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
            _record_chaos(state, event=cache_event, recovery_wave_settled=True)
            _rebuild_native_event_evidence_after_cache_reset(config, deps, state)
        if wave == 2:
            state.memory_fault_proof = _begin_memoryos_fault(
                config,
                deps,
                state,
                runtime_root,
                env,
                run_started_at=started,
            )
            paused_runner = _pause_runner(config, deps, runtime_root, env)
            try:
                _assert_memory_fault_active(
                    config,
                    deps,
                    runtime_root,
                    env,
                    state.memory_fault_proof,
                )
                correlations = _post_wave(spec, deps, state, wave=wave)
                _record_memory_fault_backlog(
                    runtime_root / "chat.db",
                    state.memory_fault_proof,
                    correlations,
                )
                memory_event = _wait_memoryos_recovery(
                    config,
                    deps,
                    state,
                    runtime_root,
                    env,
                    state.memory_fault_proof,
                )
            finally:
                _resume_runner(deps, paused_runner)
            _wait_wave_settled(config, deps, state, runtime_root, env, correlations)
            _record_chaos(state, event=memory_event, recovery_wave_settled=True)
        else:
            if wave == 1:
                _resume_goal_for_hold(config, deps, state)
            correlations = _post_wave(spec, deps, state, wave=wave)
            if wave == 0:
                event = _kill_one_provider(
                    config,
                    deps,
                    state,
                    runtime_root,
                    env,
                    run_started_at=started,
                )
            elif wave == 1:
                event = _kill_runner_and_wait_recovery(
                    config,
                    deps,
                    state,
                    runtime_root,
                    env,
                    run_started_at=started,
                )
                _prove_goal_hold_and_release(
                    config,
                    deps,
                    state,
                    runtime_root,
                    correlations,
                )
            else:
                event = None
            _wait_wave_settled(config, deps, state, runtime_root, env, correlations)
            if event is not None:
                _record_chaos(state, event=event, recovery_wave_settled=True)
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
            _prepare_goal_native_capabilities(config, deps, state, runtime_root)
    if deps.monotonic() - started < spec.minimum_duration_s:
        _wait_for_wave_offset(
            config,
            deps,
            state,
            runtime_root,
            env,
            run_started_at=started,
            offset_s=spec.minimum_duration_s,
        )
    _wait_for_memory_evidence(config, deps, state, runtime_root, env)
    browser = _verify_goal_browser(config, deps, state, artifact_dir, env)
    _sample_runtime(config, deps, state, runtime_root, env, force_resource=True)
    if not state.host_delivery_evidence_seen:
        raise SoakError("soak_host_active_delivery_evidence_missing")
    state.max_active_deliveries = max(
        state.max_active_deliveries,
        _attempt_concurrency_peak(runtime_root / "chat.db", state.room_ids),
    )
    after = deps.repository_snapshot(config.repo_root)
    base = _database_evidence(
        runtime_root / "chat.db",
        state.room_ids,
        state=state,
        provider_orphans=_provider_orphan_count(
            runtime_root,
            state.room_ids,
            deps.runtime_provider_pids,
        ),
    )
    if (
        after.head != before.head
        or not after.clean
        or after.content_digest != before.content_digest
        or after.worktree_inventory_digest != before.worktree_inventory_digest
    ):
        raise SoakError("soak_worktree_changed")
    database = runtime_root / "chat.db"
    resource = _resource_evidence(
        state.process_samples,
        warmup_cutoff_ms=state.warmup_cutoff_ms,
    )
    native = state.goal_memory_evidence
    participants = native.get("participants")
    if not isinstance(participants, list):
        raise SoakError("soak_codex_native_evidence_missing")
    with _connect_readonly(database) as conn:
        action_rows = conn.execute(
            """select capability_id, status from room_codex_bridge_actions
                 where conversation_id in (?,?,?,?)""",
            tuple(state.room_ids),
        ).fetchall()
    applied = Counter(
        str(row["capability_id"]) for row in action_rows if row["status"] == "applied"
    )
    if (
        applied["settings_update"] != 8
        or applied["console_turn_start"] != 2 + len(state.room_ids)
        or applied["turn_steer"] < 1
        or applied["review_start"] < 1
    ):
        raise SoakError("soak_codex_native_action_evidence_incomplete")
    evidence_native = {
        "participant_count": len(participants),
        "settings_participants_covered": applied["settings_update"],
        "settings_assignment_digest": native["settings_assignment_digest"],
        "distinct_settings_combinations": native["distinct_settings_combinations"],
        "max_effort_observed": native["max_effort_observed"],
        "goal_auto_continuations": native["goal_auto_continuations"],
        "goal_terminal_state": native["goal_terminal_state"],
        "goal_hold_claim_violations": native["goal_hold_claim_violations"],
        "goal_resume_count": native["goal_resume_count"],
        "goal_resume_max_ms": native["goal_resume_max_ms"],
        "other_agent_root_deliveries": native["other_agent_root_deliveries"],
        "peer_wait_projections": native["peer_wait_projections"],
        "steer_actions": applied["turn_steer"],
        "review_actions": applied["review_start"],
    }
    snapshot = _snapshot_digest(before)
    after_snapshot = _snapshot_digest(after)
    return {
        "schema_version": "room_goal_memory_soak_evidence/v1",
        "monotonic_elapsed_ms": max(0, round((deps.monotonic() - started) * 1000)),
        "counts": _map_goal_counts(base, state),
        "latency_samples_ms": {
            key: [int(item["latency_ms"]) for item in base["latency_samples_ms"][key]]
            for key in ("post_to_claim", "post_to_outcome", "post_to_settled")
        },
        "native": evidence_native,
        "numeric_usage": _goal_numeric_usage(deps, state.room_ids),
        "memory": _goal_memory_contract_evidence(database, state.room_ids, state=state),
        "faults": _map_goal_faults(state.chaos_events),
        "browser": browser,
        "resources": {
            **resource,
            "database_bytes": int(base["storage"]["database_bytes"]),
            "wal_bytes": int(base["storage"]["wal_bytes"]),
            "sqlite_integrity": base["storage"]["sqlite_integrity"],
        },
        "worktree": {
            "sentinel_before_digest": snapshot,
            "sentinel_after_digest": after_snapshot,
            "repository_before_digest": snapshot,
            "repository_after_digest": after_snapshot,
            "git_status_before_digest": _digest_json(
                {"clean": before.clean, "inventory": before.worktree_inventory_digest}
            ),
            "git_status_after_digest": _digest_json(
                {"clean": after.clean, "inventory": after.worktree_inventory_digest}
            ),
        },
    }


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
        for key, value in payload.items():
            if not isinstance(key, str) or "path" in key.lower() or key.lower() == "pid":
                return False
            if "token" in key.lower():
                if key not in {
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "total_tokens",
                }:
                    return False
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    return False
                continue
            if not _safe_result_strings(value, forbidden):
                return False
        return True
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
        if any(
            value is not None and value <= 0
            for value in (config.goal_guard_wall_s, config.goal_guard_idle_s)
        ):
            raise SoakError("soak_goal_guard_invalid", blocked=True)
        profile = (
            LIVE_PROFILES[GOAL_MEMORY_PROFILE_ID]
            if config.profile_id == GOAL_MEMORY_PROFILE_ID
            else deps.get_profile(config.profile_id)
        )
        before = _preflight(config, deps, runtime_root, result_path)
        if config.profile_id == "ci-sim":
            runtime_root.mkdir(parents=True, exist_ok=True)
            evidence = deps.run_ci_sim(runtime_root=runtime_root)
        else:
            spec = LIVE_PROFILES.get(config.profile_id)
            if spec is None:
                raise SoakError("soak_profile_not_supported", blocked=True)
            cleanup_required = True
            _prepare_full_local_memory_cache(config, deps, runtime_root, env)
            # _run_live owns a private state.  The manager is recovered for cleanup
            # from the manifest by xmuse-workroom stop even if an exception escapes.
            run = (
                _run_goal_memory_live if config.profile_id == GOAL_MEMORY_PROFILE_ID else _run_live
            )
            evidence = run(config, deps, spec, runtime_root, artifact_dir, env, before, state)
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
        if config.profile_id == GOAL_MEMORY_PROFILE_ID:
            manifest = _goal_manifest(
                config,
                deps,
                state,
                before,
                started_at=started_at,
                finished_at=finished_at,
            )
            result = deps.build_result(manifest=manifest, evidence=evidence)
        else:
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
        choices=(
            "ci-sim",
            "live-short",
            "live-soak",
            ENDURANCE_PROFILE_ID,
            ENDURANCE_SHORT_PROFILE_ID,
            "memory-recovery",
            GOAL_MEMORY_PROFILE_ID,
        ),
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
    parser.add_argument(
        "--goal-guard-wall-s",
        type=float,
        help="optional outer soak wall guard for native Goal observation",
    )
    parser.add_argument(
        "--goal-guard-idle-s",
        type=float,
        help="optional outer soak idle guard reset by native progress events",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if min(args.readiness_timeout_s, args.settle_timeout_s, args.browser_timeout_s) <= 0:
        parser.error("timeouts must be positive")
    if any(
        value is not None and value <= 0
        for value in (args.goal_guard_wall_s, args.goal_guard_idle_s)
    ):
        parser.error("Goal guard limits must be positive")
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
            goal_guard_wall_s=args.goal_guard_wall_s,
            goal_guard_idle_s=args.goal_guard_idle_s,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    if result.get("schema_version") != CLI_ERROR_SCHEMA:
        passed, _reasons = _default_evaluate_result(result)
        return 0 if passed else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
