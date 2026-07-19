"""Narrow lifecycle contracts for the optional MemoryOS archive sidecar.

MemoryOS is a disposable, opt-in index.  This module deliberately exposes only a
fixed loopback command, a scrubbed child environment, and a safe status receipt;
Room and Workroom readiness remain authoritative elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

MEMORYOS_RUNTIME_SCHEMA = "xmuse_memoryos_runtime/v2"
MEMORYOS_RUNTIME_V1_SCHEMA = "xmuse_memoryos_runtime/v1"
MEMORYOS_STATUS_NAME = "memoryos-status.json"
MEMORYOS_DERIVED_RELATIVE = Path("runtime") / "memoryos-derived"
MEMORYOS_HOST = "127.0.0.1"
MEMORYOS_PORT = 8301
MEMORYOS_HEARTBEAT_TTL_S = 20.0

MEMORYOS_RESTART_BACKOFF_S = (1, 2, 4, 8, 16, 30)
MEMORYOS_PROFILES = ("archive-only", "full-local")

MemoryOSRuntimeState = Literal[
    "disabled",
    "starting",
    "recovering",
    "ready",
    "degraded",
    "rebuilding",
    "stopped",
]
_STATES = frozenset(
    {"disabled", "starting", "recovering", "ready", "degraded", "rebuilding", "stopped"}
)
_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_REBUILDABLE_CODES = frozenset(
    {
        "memoryos_crash_loop",
        "memoryos_derived_cache_incompatible",
        "memoryos_derived_cache_clear_failed",
        "memoryos_derived_cache_prepare_failed",
        "memoryos_derived_cache_unsafe",
        "memoryos_derived_schema_incompatible",
    }
)
_SAFE_WITHOUT_LIVE_PROCESS_CODES = frozenset(
    {
        "memoryos_crash_loop",
        "memoryos_derived_cache_incompatible",
        "memoryos_derived_cache_clear_failed",
        "memoryos_derived_cache_prepare_failed",
        "memoryos_derived_cache_unsafe",
        "memoryos_derived_schema_incompatible",
        "memoryos_port_in_use",
        "memoryos_process_exited",
        "memoryos_reconcile_failed",
        "memoryos_spawn_failed",
    }
)
_SAFE_AMBIENT_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
    }
)


class MemoryOSSupervisorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def memoryos_status_path(xmuse_root: Path) -> Path:
    return xmuse_root / MEMORYOS_STATUS_NAME


def memoryos_derived_dir(xmuse_root: Path) -> Path:
    return xmuse_root / MEMORYOS_DERIVED_RELATIVE


def resolve_memoryos_executable(value: Path | str) -> Path:
    configured = Path(value).expanduser()
    metadata = configured.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MemoryOSSupervisorError("memoryos_executable_invalid")
    path = configured.resolve(strict=True)
    if not os.access(path, os.X_OK):
        raise MemoryOSSupervisorError("memoryos_executable_not_executable")
    return path


def memoryos_command(
    executable: Path,
    *,
    host: str = MEMORYOS_HOST,
    port: int = MEMORYOS_PORT,
) -> tuple[str, ...]:
    if host != MEMORYOS_HOST or isinstance(port, bool) or not (1 <= int(port) <= 65_535):
        raise MemoryOSSupervisorError("memoryos_endpoint_invalid")
    return (str(executable), "api", "--host", host, "--port", str(port))


def memoryos_child_environment(
    ambient: Mapping[str, str],
    *,
    xmuse_root: Path,
    generation: str,
    api_key: str,
    profile: str = "archive-only",
) -> dict[str, str]:
    """Return a strict allow-list environment with all network providers disabled."""

    if not api_key or not generation:
        raise MemoryOSSupervisorError("memoryos_runtime_configuration_invalid")
    if profile not in MEMORYOS_PROFILES:
        raise MemoryOSSupervisorError("memoryos_profile_invalid")
    environment = {
        key: value
        for key, value in ambient.items()
        if key in _SAFE_AMBIENT_KEYS and isinstance(value, str)
    }
    environment.update(
        {
            "DATA_DIR": str(memoryos_derived_dir(xmuse_root)),
            # FastEmbed deletes temporary caches after unpacking; pin the
            # managed model cache to the Workroom runtime so offline startup
            # can prove the preloaded model without using a global temp path.
            "FASTEMBED_CACHE_PATH": str(xmuse_root / "runtime" / "fastembed-cache"),
            "MEMORYOS_AGENT_KERNEL": "external" if profile == "full-local" else "off",
            "MEMORYOS_API_KEY": api_key,
            # full-local uses MemoryOS' bounded process-local FastEmbed index.
            # archive-only deliberately remains lexical and dependency-light.
            "MEMORYOS_ARCHIVAL_VECTOR_ENABLED": "true" if profile == "full-local" else "false",
            "MEMORYOS_CORS_ORIGINS": "[]",
            "MEMORYOS_ITEM_EXTRACTION": "true" if profile == "full-local" else "false",
            "MEMORYOS_MEMORY_ARCH": "v3",
            "MEMORYOS_PAGING_MODE": "heuristic" if profile == "full-local" else "off",
            "MEMORYOS_RECALL_CACHE_ENABLED": "false",
            "MEMORYOS_RECALL_PIPELINE": "v2",
            "MEMORYOS_EMBEDDING_PROVIDER": "fastembed" if profile == "full-local" else "auto",
            "MEMORYOS_EMBEDDING_MODEL": (
                "BAAI/bge-small-en-v1.5" if profile == "full-local" else "text-embedding-3-small"
            ),
            "MEMORYOS_FASTEMBED_OFFLINE": "1" if profile == "full-local" else "0",
            "HF_HUB_OFFLINE": "1" if profile == "full-local" else "0",
            "TRANSFORMERS_OFFLINE": "1" if profile == "full-local" else "0",
            "MEMORYOS_RERANK_ENABLED": "false",
            "MEMORYOS_REWRITE_ENABLED": "false",
            "PYTHONUNBUFFERED": "1",
            "XMUSE_ROOT": str(xmuse_root),
            "XMUSE_WORKROOM_GENERATION": generation,
            "XMUSE_WORKROOM_SERVICE": "memoryos",
        }
    )
    return environment


def memoryos_restart_backoff_seconds(consecutive_restart_count: int) -> int:
    """Return the fixed bounded delay for one-based consecutive failures."""

    if (
        isinstance(consecutive_restart_count, bool)
        or not isinstance(consecutive_restart_count, int)
        or consecutive_restart_count < 1
    ):
        raise MemoryOSSupervisorError("memoryos_restart_count_invalid")
    return MEMORYOS_RESTART_BACKOFF_S[
        min(consecutive_restart_count, len(MEMORYOS_RESTART_BACKOFF_S)) - 1
    ]


def write_memoryos_status(
    xmuse_root: Path,
    *,
    enabled: bool,
    state: MemoryOSRuntimeState,
    code: str,
    generation: str | None,
    pid: int | None = None,
    start_identity: str | None = None,
    started_at: str | None = None,
    heartbeat_at: str | None = None,
    consecutive_restart_count: int = 0,
    next_retry_at: str | None = None,
    last_healthy_at: str | None = None,
    profile: str = "archive-only",
) -> dict[str, Any]:
    if state not in _STATES or _CODE_RE.fullmatch(code) is None:
        raise MemoryOSSupervisorError("memoryos_status_invalid")
    if profile not in MEMORYOS_PROFILES:
        raise MemoryOSSupervisorError("memoryos_profile_invalid")
    if enabled != (state != "disabled"):
        raise MemoryOSSupervisorError("memoryos_status_invalid")
    if pid is not None and (isinstance(pid, bool) or pid <= 0):
        raise MemoryOSSupervisorError("memoryos_status_invalid")
    if (
        isinstance(consecutive_restart_count, bool)
        or not isinstance(consecutive_restart_count, int)
        or consecutive_restart_count < 0
    ):
        raise MemoryOSSupervisorError("memoryos_status_invalid")
    if any(
        value is not None and not _valid_timestamp(value)
        for value in (started_at, heartbeat_at, next_retry_at, last_healthy_at)
    ):
        raise MemoryOSSupervisorError("memoryos_status_invalid")
    stamp = heartbeat_at or _utc_now()
    payload: dict[str, Any] = {
        "schema_version": MEMORYOS_RUNTIME_SCHEMA,
        "enabled": enabled,
        "state": state,
        "code": code,
        "heartbeat_at": stamp,
        "started_at": started_at,
        "consecutive_restart_count": consecutive_restart_count,
        "next_retry_at": next_retry_at,
        "last_healthy_at": last_healthy_at,
        "profile": profile,
    }
    if generation is not None:
        payload["generation"] = generation
    if pid is not None:
        payload["pid"] = pid
    if start_identity is not None:
        payload["start_identity"] = start_identity
    _atomic_write_private_json(memoryos_status_path(xmuse_root), payload)
    return payload


def read_memoryos_status(xmuse_root: Path) -> dict[str, Any] | None:
    path = memoryos_status_path(xmuse_root)
    try:
        raw = path.read_bytes()
        if len(raw) > 8 * 1024:
            return None
        payload = json.loads(raw)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        MEMORYOS_RUNTIME_V1_SCHEMA,
        MEMORYOS_RUNTIME_SCHEMA,
    }:
        return None
    state = payload.get("state")
    code = payload.get("code")
    if state not in _STATES or not isinstance(code, str) or _CODE_RE.fullmatch(code) is None:
        return None
    if payload.get("enabled") != (state != "disabled"):
        return None
    if payload.get("schema_version") == MEMORYOS_RUNTIME_SCHEMA and not {
        "consecutive_restart_count",
        "next_retry_at",
        "last_healthy_at",
    }.issubset(payload):
        return None
    if not _valid_private_status_fields(payload):
        return None
    if payload.get("schema_version") == MEMORYOS_RUNTIME_V1_SCHEMA:
        payload = {
            **payload,
            "schema_version": MEMORYOS_RUNTIME_SCHEMA,
            "consecutive_restart_count": 0,
            "next_retry_at": None,
            "last_healthy_at": None,
            "profile": "archive-only",
        }
    return payload


def assess_memoryos_status(
    xmuse_root: Path,
    *,
    expected_generation: str | None,
    live: bool,
    ready_probe: bool,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Assess optional sidecar evidence without changing Workroom readiness."""

    payload = read_memoryos_status(xmuse_root)
    if payload is None:
        return _safe_status(None, state="degraded", code="memoryos_receipt_invalid")
    if expected_generation is not None and payload.get("generation") != expected_generation:
        return _safe_status(payload, state="degraded", code="memoryos_generation_mismatch")
    state = str(payload["state"])
    if state == "disabled":
        return _safe_status(payload, state="disabled", code="memoryos_disabled")
    if not live and not (
        state in {"starting", "recovering", "rebuilding"}
        or payload.get("code") in _SAFE_WITHOUT_LIVE_PROCESS_CODES
    ):
        return _safe_status(payload, state="degraded", code="memoryos_process_stopped")
    if _heartbeat_stale(payload.get("heartbeat_at"), now=now):
        return _safe_status(payload, state="degraded", code="memoryos_heartbeat_stale")
    if payload.get("code") == "memoryos_full_local_capability_missing":
        return _safe_status(
            payload,
            state="degraded",
            code="memoryos_full_local_capability_missing",
        )
    if ready_probe:
        return _safe_status(payload, state="ready", code="ready")
    return _safe_status(payload, state="degraded", code="memoryos_health_unavailable")


def safe_memoryos_status(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "schema_version": MEMORYOS_RUNTIME_SCHEMA,
            "enabled": False,
            "state": "disabled",
            "code": "memoryos_disabled",
            "heartbeat_at": None,
            "started_at": None,
        }
    return _safe_status(
        payload,
        state=str(payload.get("state") or "degraded"),
        code=str(payload.get("code") or "memoryos_status_invalid"),
    )


def browser_memoryos_status(
    xmuse_root: Path, *, now: datetime | str | None = None
) -> dict[str, Any]:
    """Read a browser-safe receipt with freshness checks and no process identity."""

    if not memoryos_status_path(xmuse_root).exists():
        return safe_memoryos_status(None)
    payload = read_memoryos_status(xmuse_root)
    if payload is None:
        return _safe_status(None, state="degraded", code="memoryos_receipt_invalid")
    if payload.get("state") == "disabled":
        return _safe_status(payload, state="disabled", code="memoryos_disabled")
    if _heartbeat_stale(payload.get("heartbeat_at"), now=now):
        return _safe_status(payload, state="degraded", code="memoryos_heartbeat_stale")
    return safe_memoryos_status(payload)


def _safe_status(
    payload: Mapping[str, Any] | None,
    *,
    state: str,
    code: str,
) -> dict[str, Any]:
    safe = {
        "schema_version": MEMORYOS_RUNTIME_SCHEMA,
        "enabled": bool(payload.get("enabled")) if payload is not None else True,
        "state": state,
        "code": code,
        "heartbeat_at": payload.get("heartbeat_at") if payload is not None else None,
        "started_at": payload.get("started_at") if payload is not None else None,
    }
    if payload is not None:
        safe.update(
            {
                "consecutive_restart_count": int(payload.get("consecutive_restart_count", 0)),
                "next_retry_at": payload.get("next_retry_at"),
                "last_healthy_at": payload.get("last_healthy_at"),
                "profile": (
                    payload.get("profile")
                    if payload.get("profile") in MEMORYOS_PROFILES
                    else "archive-only"
                ),
            }
        )
    return safe


def memoryos_incident_guard(payload: Mapping[str, Any]) -> str:
    """Return an opaque guard over safe state plus private process topology evidence."""

    evidence = {
        key: payload.get(key)
        for key in (
            "schema_version",
            "enabled",
            "state",
            "code",
            "generation",
            "pid",
            "start_identity",
            "consecutive_restart_count",
            "next_retry_at",
            "last_healthy_at",
        )
    }
    encoded = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"memoryos_incident_{hashlib.sha256(encoded).hexdigest()[:32]}"


def memoryos_rebuildability(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Describe whether a safe, fixed-cache rebuild may be operator-authorized."""

    code = payload.get("code")
    available = payload.get("enabled") is True and code in _REBUILDABLE_CODES
    return {
        "available": available,
        "reason_code": (str(code) if available else "memoryos_rebuild_not_available"),
        "incident_id": memoryos_incident_guard(payload) if available else None,
    }


def clear_memoryos_derived_cache(xmuse_root: Path) -> bool:
    """Delete only the fixed derived cache without following any symlink."""

    root = xmuse_root.expanduser()
    runtime = root / "runtime"
    target_name = "memoryos-derived"
    try:
        for directory in (root, runtime):
            metadata = directory.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise MemoryOSSupervisorError("memoryos_derived_cache_unsafe")
    except FileNotFoundError:
        return False
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = -1
    target_fd = -1
    try:
        parent_fd = os.open(runtime, flags)
        try:
            target_metadata = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(target_metadata.st_mode) or not stat.S_ISDIR(target_metadata.st_mode):
            raise MemoryOSSupervisorError("memoryos_derived_cache_unsafe")
        try:
            target_fd = os.open(target_name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return False
        _clear_directory_fd(target_fd)
        os.close(target_fd)
        target_fd = -1
        os.rmdir(target_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return True
    except MemoryOSSupervisorError:
        raise
    except OSError as exc:
        raise MemoryOSSupervisorError("memoryos_derived_cache_clear_failed") from exc
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def prepare_memoryos_derived_cache(xmuse_root: Path) -> Path:
    """Create the fixed cache through no-follow directory descriptors."""

    root = xmuse_root.expanduser()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    root_fd = -1
    runtime_fd = -1
    target_fd = -1
    try:
        root_metadata = root.lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            raise MemoryOSSupervisorError("memoryos_derived_cache_unsafe")
        root_fd = os.open(root, flags)
        try:
            os.mkdir("runtime", mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        runtime_metadata = os.stat("runtime", dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISLNK(runtime_metadata.st_mode) or not stat.S_ISDIR(runtime_metadata.st_mode):
            raise MemoryOSSupervisorError("memoryos_derived_cache_unsafe")
        runtime_fd = os.open("runtime", flags, dir_fd=root_fd)
        try:
            os.mkdir("memoryos-derived", mode=0o700, dir_fd=runtime_fd)
        except FileExistsError:
            pass
        target_metadata = os.stat("memoryos-derived", dir_fd=runtime_fd, follow_symlinks=False)
        if stat.S_ISLNK(target_metadata.st_mode) or not stat.S_ISDIR(target_metadata.st_mode):
            raise MemoryOSSupervisorError("memoryos_derived_cache_unsafe")
        target_fd = os.open("memoryos-derived", flags, dir_fd=runtime_fd)
        os.fchmod(target_fd, 0o700)
        os.fsync(runtime_fd)
        return memoryos_derived_dir(root)
    except MemoryOSSupervisorError:
        raise
    except OSError as exc:
        raise MemoryOSSupervisorError("memoryos_derived_cache_prepare_failed") from exc
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if runtime_fd >= 0:
            os.close(runtime_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _clear_directory_fd(directory_fd: int) -> None:
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                try:
                    _clear_directory_fd(child_fd)
                finally:
                    os.close(child_fd)
                os.rmdir(entry.name, dir_fd=directory_fd)
            else:
                os.unlink(entry.name, dir_fd=directory_fd)


def _valid_private_status_fields(payload: Mapping[str, Any]) -> bool:
    restart_count = payload.get("consecutive_restart_count", 0)
    if isinstance(restart_count, bool) or not isinstance(restart_count, int) or restart_count < 0:
        return False
    pid = payload.get("pid")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        return False
    for name in ("generation", "start_identity"):
        value = payload.get(name)
        if value is not None and (
            not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512
        ):
            return False
    return all(
        value is None or _valid_timestamp(value)
        for value in (
            payload.get("heartbeat_at"),
            payload.get("started_at"),
            payload.get("next_retry_at"),
            payload.get("last_healthy_at"),
        )
    )


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 100:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _heartbeat_stale(value: object, *, now: datetime | str | None) -> bool:
    if not isinstance(value, str):
        return True
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        current = (
            datetime.fromisoformat(now.replace("Z", "+00:00"))
            if isinstance(now, str)
            else (now or datetime.now(UTC))
        )
        if stamp.tzinfo is None or current.tzinfo is None:
            return True
        age = (current.astimezone(UTC) - stamp.astimezone(UTC)).total_seconds()
    except (TypeError, ValueError):
        return True
    return age < -5 or age > MEMORYOS_HEARTBEAT_TTL_S


def _atomic_write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def command_has_api_key(command: Sequence[str], api_key: str) -> bool:
    """Test/helper invariant: the server-only key must never be an argv value."""

    return any(api_key and api_key in part for part in command)
