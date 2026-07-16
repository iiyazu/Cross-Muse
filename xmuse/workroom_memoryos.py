"""Generation-local MemoryOS lifecycle decisions for the Workroom coordinator.

This leaf module owns no process loop, timer, manifest, lock, status receipt, or
durable action.  Callers must prove the current generation and hold the root
lifecycle lock before applying any returned decision to external state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from xmuse.workroom_processes import ManagedProcess, ProcessIdentity
from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_HOST,
    MEMORYOS_PORT,
    memoryos_restart_backoff_seconds,
)

MEMORYOS_HEARTBEAT_INTERVAL_S = 5.0


@dataclass
class MemoryOSRuntimeControl:
    """Non-durable authority for one sidecar child in exactly one generation."""

    executable: Path
    api_key: str = field(repr=False)
    url: str
    profile: Literal["archive-only", "full-local"] = "archive-only"
    process: ManagedProcess | None = None
    record: dict[str, Any] | None = None
    started_at: str | None = None
    consecutive_restart_count: int = 0
    next_retry_monotonic: float | None = None
    next_retry_at: str | None = None
    last_healthy_at: str | None = None
    healthy_since_monotonic: float | None = None
    rebuilding: bool = False
    retry_state: str | None = None
    retry_code: str | None = None
    rebuild_blocked_code: str | None = None

    def set_rebuilding(self, active: bool) -> None:
        self.rebuilding = active
        self.healthy_since_monotonic = None
        if active:
            self.next_retry_monotonic = None
            self.next_retry_at = None
            self.retry_state = None
            self.retry_code = None


@dataclass(frozen=True)
class MemoryOSControlDecision:
    """A safe single-step result; it is not permission to mutate external state."""

    state: Literal["starting", "ready", "recovering", "rebuilding", "degraded"]
    code: str


def set_memoryos_rebuilding(control: MemoryOSRuntimeControl, active: bool) -> None:
    control.set_rebuilding(active)


def generation_is_current(
    *,
    expected_generation: str,
    current_manifest: Mapping[str, Any] | None,
) -> bool:
    """Prove the caller's generation without reading or locking the manifest here."""

    return bool(
        expected_generation
        and current_manifest is not None
        and current_manifest.get("generation") == expected_generation
        and current_manifest.get("state") not in {"stopping", "stopped", "failed"}
    )


def retry_wall_time(now: str, delay_s: int) -> str:
    try:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if current.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError:
        current = datetime.now(UTC)
    return (
        (current.astimezone(UTC) + timedelta(seconds=delay_s))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def schedule_memoryos_recovery(
    control: MemoryOSRuntimeControl,
    *,
    code: str,
    monotonic_now: float,
    wall_time_now: str,
) -> MemoryOSControlDecision:
    """Forget a confirmed-dead child and schedule the existing bounded retry."""

    control.process = None
    control.record = None
    control.healthy_since_monotonic = None
    control.consecutive_restart_count += 1
    effective_code = "memoryos_crash_loop" if control.consecutive_restart_count >= 6 else code
    delay_s = memoryos_restart_backoff_seconds(control.consecutive_restart_count)
    control.next_retry_monotonic = monotonic_now + delay_s
    control.next_retry_at = retry_wall_time(wall_time_now, delay_s)
    control.retry_state = "recovering"
    control.retry_code = effective_code
    return MemoryOSControlDecision(state="recovering", code=effective_code)


def defer_memoryos_for_unknown_port(
    control: MemoryOSRuntimeControl,
    *,
    monotonic_now: float,
    wall_time_now: str,
) -> MemoryOSControlDecision:
    """Defer without claiming, killing, or replacing an unknown port owner."""

    control.healthy_since_monotonic = None
    control.next_retry_monotonic = monotonic_now + MEMORYOS_HEARTBEAT_INTERVAL_S
    control.next_retry_at = retry_wall_time(wall_time_now, int(MEMORYOS_HEARTBEAT_INTERVAL_S))
    control.retry_state = "degraded"
    control.retry_code = "memoryos_port_in_use"
    return MemoryOSControlDecision(
        state="degraded",
        code="memoryos_port_in_use",
    )


def memoryos_record_for_identity(
    process: ManagedProcess,
    identity: ProcessIdentity,
    *,
    generation: str,
    xmuse_root: Path,
) -> dict[str, Any] | None:
    """Build a record only from the shared exact process identity proof."""

    environment = identity.environment
    if (
        environment.get("XMUSE_WORKROOM_GENERATION") != generation
        or environment.get("XMUSE_ROOT") != str(xmuse_root)
        or environment.get("XMUSE_WORKROOM_SERVICE") != "memoryos"
    ):
        return None
    return {
        "service": "memoryos",
        "pid": process.pid,
        "pgid": identity.pgid,
        "start_identity": identity.start_identity,
        "generation": generation,
        "host": MEMORYOS_HOST,
        "port": MEMORYOS_PORT,
        "log_path": str(xmuse_root / "logs" / "workroom-memoryos.log"),
    }


def control_gate(
    control: MemoryOSRuntimeControl,
    *,
    monotonic_now: float,
) -> MemoryOSControlDecision | None:
    """Return the existing reconcile gate before a caller considers spawn work."""

    if control.rebuild_blocked_code is not None:
        return MemoryOSControlDecision(
            state="degraded",
            code=control.rebuild_blocked_code,
        )
    if control.rebuilding:
        return MemoryOSControlDecision(
            state="rebuilding",
            code="memoryos_rebuilding",
        )
    deadline = control.next_retry_monotonic
    if deadline is not None and monotonic_now < deadline:
        state: Literal["recovering", "degraded"] = (
            "degraded" if control.retry_state == "degraded" else "recovering"
        )
        return MemoryOSControlDecision(
            state=state,
            code=control.retry_code or "memoryos_recovering",
        )
    return None


def prepare_memoryos_spawn(
    control: MemoryOSRuntimeControl,
    *,
    started_at: str,
) -> MemoryOSControlDecision:
    """Reset retry fields immediately before the coordinator performs one spawn."""

    control.next_retry_monotonic = None
    control.next_retry_at = None
    control.retry_state = None
    control.retry_code = None
    control.started_at = started_at
    if control.consecutive_restart_count == 0:
        return MemoryOSControlDecision(state="starting", code="memoryos_starting")
    return MemoryOSControlDecision(state="recovering", code="memoryos_recovering")


def mark_memoryos_healthy(
    control: MemoryOSRuntimeControl,
    *,
    monotonic_now: float,
    wall_time_now: str,
) -> MemoryOSControlDecision:
    """Apply the existing 60-second healthy-window retry reset."""

    control.last_healthy_at = wall_time_now
    if control.healthy_since_monotonic is None:
        control.healthy_since_monotonic = monotonic_now
    elif monotonic_now - control.healthy_since_monotonic >= 60.0:
        control.consecutive_restart_count = 0
    return MemoryOSControlDecision(state="ready", code="ready")


__all__ = [
    "MEMORYOS_HEARTBEAT_INTERVAL_S",
    "MemoryOSControlDecision",
    "MemoryOSRuntimeControl",
    "control_gate",
    "defer_memoryos_for_unknown_port",
    "generation_is_current",
    "mark_memoryos_healthy",
    "memoryos_record_for_identity",
    "prepare_memoryos_spawn",
    "retry_wall_time",
    "schedule_memoryos_recovery",
    "set_memoryos_rebuilding",
]
