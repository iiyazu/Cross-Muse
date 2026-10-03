"""Per-participant workspace-write routing for owner agents.

A roster may declare a Claude or OpenCode participant as ``workspace_write``.
Such a participant works in its own local clone under an OS sandbox where only
that clone and its own provider state are writable, with full native tools.
Every other participant keeps the shared read-only route selected by
``RoutingRoomObservationTransport``.

The router below subclasses the existing router so ``cli_kind`` selection,
introspection, and fail-closed behavior stay unchanged for read-only
deliveries; writer deliveries go to a dedicated ``AcpRoomObservationTransport``
per ``(conversation_id, participant_id)`` created lazily under a lock.
"""

from __future__ import annotations

import asyncio
import functools
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.participant_store import (
    WORKSPACE_WRITE_CLI_KINDS,
    Participant,
)
from xmuse_core.chat.room_acp_transport import (
    CLAUDE_ACP_WORKSPACE_WRITE_PROFILE,
    OPENCODE_ACP_WORKSPACE_WRITE_PROFILE,
    AcpRoomObservationTransport,
    AcpTransportConfig,
)
from xmuse_core.chat.room_agent_stream import RoomAgentStreamProjector
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_execution_ports import ExecutionReviewReceiptWriter
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomObservationTransport,
    RoomTransportResult,
)
from xmuse_core.chat.room_memory_runtime import RoomMemoryContextReceiptPort
from xmuse_core.chat.room_observation_transport_base import sanitized_agent_environment
from xmuse_core.chat.room_owner_clones import (
    OwnerClone,
    OwnerCloneError,
    OwnerCloneManager,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport
from xmuse_core.chat.room_workspace_sandbox import build_workspace_write_sandbox_command

WORKSPACE_WRITE_UNAVAILABLE = "room_workspace_write_unavailable"
OWNER_PREPARE_FAILED = "room_owner_clone_prepare_failed"

OWNER_PREPARE_COMMAND_ENV = "XMUSE_OWNER_PREPARE_COMMAND"
OWNER_PREPARE_TIMEOUT_ENV = "XMUSE_OWNER_PREPARE_TIMEOUT_S"
OWNER_MASKED_PATHS_ENV = "XMUSE_OWNER_MASKED_PATHS"
OWNER_PREPARE_TIMEOUT_DEFAULT_S = 900.0

OwnerTransportFactory = Callable[[Participant, OwnerClone], RoomObservationTransport | None]


def owner_id_for_participant(conversation_id: str, participant_id: str) -> str:
    """Derive the host-owned clone id for one participant (always OWNER_ID_RE)."""

    digest = sha256(f"{conversation_id}\0{participant_id}".encode()).hexdigest()[:20]
    return f"p-{digest}"


def is_workspace_write_participant(participant: Participant) -> bool:
    """True only for writers the runner can confine (claude/opencode)."""

    return (
        participant.workspace_access == "workspace_write"
        and participant.cli_kind in WORKSPACE_WRITE_CLI_KINDS
    )


@dataclass(frozen=True)
class OwnerWorkspaceWriteSettings:
    """Host-owned inputs for per-writer dedicated transports."""

    clones_root: Path
    source_repo: Path
    xmuse_root: Path
    home: Path
    room_mcp_url: str
    bwrap: Path
    claude_agent_argv: tuple[str, ...] | None = None
    opencode_argv: tuple[str, ...] | None = None
    opencode_default_model: str | None = None
    extra_masked_paths: tuple[Path, ...] = ()
    prepare_command: tuple[str, ...] | None = None
    prepare_timeout_s: float = OWNER_PREPARE_TIMEOUT_DEFAULT_S


def resolve_owner_prepare_command(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...] | None:
    """Split the optional prepare argv (no shell); None when unset."""

    source = os.environ if environ is None else environ
    raw = str(source.get(OWNER_PREPARE_COMMAND_ENV, "") or "").strip()
    if not raw:
        return None
    try:
        argv = tuple(shlex.split(raw))
    except ValueError as exc:
        raise ValueError("room_owner_prepare_command_invalid") from exc
    if not argv:
        raise ValueError("room_owner_prepare_command_invalid")
    return argv


def resolve_owner_prepare_timeout_s(environ: Mapping[str, str] | None = None) -> float:
    """Read the prepare timeout in seconds (default 900)."""

    source = os.environ if environ is None else environ
    raw = str(source.get(OWNER_PREPARE_TIMEOUT_ENV, "") or "").strip()
    if not raw:
        return OWNER_PREPARE_TIMEOUT_DEFAULT_S
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("room_owner_prepare_timeout_invalid") from exc
    if not (value > 0) or value != value or value in (float("inf"), float("-inf")):
        raise ValueError("room_owner_prepare_timeout_invalid")
    return value


def resolve_owner_masked_paths(
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Read extra sandbox masks (os.pathsep-separated); empty when unset."""

    source = os.environ if environ is None else environ
    raw = str(source.get(OWNER_MASKED_PATHS_ENV, "") or "")
    if not raw.strip():
        return ()
    return tuple(Path(part) for part in raw.split(os.pathsep) if part.strip())


def run_owner_prepare_command(
    command: tuple[str, ...],
    clone_path: Path,
    *,
    timeout_s: float,
) -> None:
    """Run the prepare argv once inside a fresh clone; fail with a stable code."""

    try:
        result = subprocess.run(
            list(command),
            cwd=str(clone_path),
            # Dependency installs never need server-only secrets.
            env=sanitized_agent_environment(os.environ),
            timeout=float(timeout_s),
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OwnerCloneError("owner_clone_prepare_failed", f"timeout: {exc}") from exc
    except OSError as exc:
        raise OwnerCloneError("owner_clone_prepare_failed", f"{type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise OwnerCloneError("owner_clone_prepare_failed", detail)


def build_owner_prepare(
    settings: OwnerWorkspaceWriteSettings,
) -> Callable[[Path], None] | None:
    """Return the once-per-clone prepare hook, or None when unconfigured."""

    if settings.prepare_command is None:
        return None

    def _prepare(clone_path: Path) -> None:
        run_owner_prepare_command(
            settings.prepare_command or (),
            clone_path,
            timeout_s=settings.prepare_timeout_s,
        )

    return _prepare


def build_owner_acp_config(
    settings: OwnerWorkspaceWriteSettings,
    *,
    participant: Participant,
    clone: OwnerClone,
) -> AcpTransportConfig | None:
    """Build the sandboxed writer config, or None when the provider is off."""

    if participant.cli_kind == "claude":
        agent_argv = settings.claude_agent_argv
        profile = CLAUDE_ACP_WORKSPACE_WRITE_PROFILE
        default_model: str | None = None
    elif participant.cli_kind == "opencode":
        agent_argv = settings.opencode_argv
        profile = OPENCODE_ACP_WORKSPACE_WRITE_PROFILE
        default_model = settings.opencode_default_model
        if not default_model or not default_model.strip():
            return None
    else:
        return None
    if agent_argv is None or not agent_argv:
        return None
    command = build_workspace_write_sandbox_command(
        bwrap=Path(settings.bwrap),
        provider=participant.cli_kind,
        home=Path(settings.home),
        workspace=clone.path,
        agent_argv=agent_argv,
        # The xmuse root encloses the clones root, so the existing enclosing
        # mask order keeps other owners' clones hidden from this one.
        masked_paths=(settings.xmuse_root, *settings.extra_masked_paths),
    )
    return AcpTransportConfig(
        workspace=clone.path,
        command=command,
        room_mcp_url=settings.room_mcp_url,
        profile=profile,
        default_model=default_model,
    )


def build_owner_acp_transport_factory(
    settings: OwnerWorkspaceWriteSettings,
    *,
    registry_path: Path | str,
    control_store: RoomObservationControlStore | None = None,
    skill_decision_store: RoomAttemptSkillDecisionStore | None = None,
    execution_store: ExecutionReviewReceiptWriter | None = None,
    memory_runtime: RoomMemoryContextReceiptPort | None = None,
    stream_projector: RoomAgentStreamProjector | None = None,
) -> OwnerTransportFactory:
    """Build dedicated writer transports over the shared disposable preview cache."""

    def _factory(participant: Participant, clone: OwnerClone) -> AcpRoomObservationTransport | None:
        config = build_owner_acp_config(settings, participant=participant, clone=clone)
        if config is None:
            return None
        return AcpRoomObservationTransport(
            config=config,
            registry_path=registry_path,
            control_store=control_store,
            skill_decision_store=skill_decision_store,
            execution_store=execution_store,
            memory_runtime=memory_runtime,
            stream_projector=stream_projector,
        )

    return _factory


class RoomOwnerTransportRouter(RoutingRoomObservationTransport):
    """Route writer deliveries to dedicated owner-clone transports.

    Read-only deliveries use the wrapped ``cli_kind`` routes unchanged.
    Writers whose provider transport is disabled (or when no owner settings
    were wired) fail closed with ``room_workspace_write_unavailable`` instead
    of borrowing another provider's session semantics.
    """

    def __init__(
        self,
        routes: Mapping[str, RoomObservationTransport],
        *,
        settings: OwnerWorkspaceWriteSettings | None = None,
        clone_manager: OwnerCloneManager | None = None,
        transport_factory: OwnerTransportFactory | None = None,
    ) -> None:
        super().__init__(routes)
        self._owner_settings = settings
        if clone_manager is not None:
            self._clone_manager: OwnerCloneManager | None = clone_manager
        elif settings is not None:
            self._clone_manager = OwnerCloneManager(settings.clones_root)
        else:
            self._clone_manager = None
        self._transport_factory = transport_factory
        self._owner_prepare = build_owner_prepare(settings) if settings is not None else None
        self._owner_transports: dict[tuple[str, str], RoomObservationTransport] = {}
        self._owner_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        if not is_workspace_write_participant(delivery.participant):
            return await super().deliver(delivery, timeout_s=timeout_s)
        try:
            transport = await self._dedicated_transport(delivery.participant)
        except OwnerCloneError as exc:
            if exc.code == "owner_clone_prepare_failed":
                return RoomTransportResult("failed", OWNER_PREPARE_FAILED, str(exc))
            return RoomTransportResult("failed", exc.code, str(exc))
        except Exception as exc:
            return RoomTransportResult("failed", WORKSPACE_WRITE_UNAVAILABLE, str(exc))
        if transport is None:
            return RoomTransportResult("failed", WORKSPACE_WRITE_UNAVAILABLE)
        return await transport.deliver(delivery, timeout_s=timeout_s)

    async def reconcile_cancel(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        attempt: dict[str, Any],
        timeout_s: float,
    ) -> RoomCancelReconcileResult:
        if not is_workspace_write_participant(participant):
            return await super().reconcile_cancel(
                conversation_id=conversation_id,
                participant=participant,
                attempt=attempt,
                timeout_s=timeout_s,
            )
        # After a runner restart the cache is empty while the attempt still needs
        # reconciling, so rebuild the dedicated transport (the clone is reused).
        try:
            transport = await self._dedicated_transport(participant)
        except Exception:
            transport = None
        if transport is None:
            return RoomCancelReconcileResult("pending", WORKSPACE_WRITE_UNAVAILABLE)
        hook = getattr(transport, "reconcile_cancel", None)
        if not callable(hook):
            return RoomCancelReconcileResult("pending", "room_cancel_reconcile_unavailable")
        return await hook(
            conversation_id=conversation_id,
            participant=participant,
            attempt=attempt,
            timeout_s=timeout_s,
        )

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        if not is_workspace_write_participant(delivery.participant):
            return await super().reset_after_missing_outcome(delivery, timeout_s=timeout_s)
        transport = self._owner_transports.get(
            (delivery.conversation_id, delivery.participant.participant_id)
        )
        if transport is None:
            # No dedicated session exists yet, so there is nothing to rotate;
            # keep the host's reopen decision like the wrapped router does for
            # routes without the hook.
            return True
        hook = getattr(transport, "reset_after_missing_outcome", None)
        if not callable(hook):
            return True
        return bool(await hook(delivery, timeout_s=timeout_s))

    async def _dedicated_transport(
        self, participant: Participant
    ) -> RoomObservationTransport | None:
        key = (participant.conversation_id, participant.participant_id)
        existing = self._owner_transports.get(key)
        if existing is not None:
            return existing
        if (
            self._owner_settings is None
            or self._clone_manager is None
            or self._transport_factory is None
        ):
            return None
        lock = self._owner_locks.setdefault(key, asyncio.Lock())
        async with lock:
            existing = self._owner_transports.get(key)
            if existing is not None:
                return existing
            owner_id = owner_id_for_participant(
                participant.conversation_id, participant.participant_id
            )
            settings = self._owner_settings
            manager = self._clone_manager
            prepare = self._owner_prepare
            clone = await asyncio.to_thread(
                functools.partial(
                    manager.ensure,
                    settings.source_repo,
                    owner_id,
                    base_ref="HEAD",
                    prepare=prepare,
                )
            )
            transport = self._transport_factory(participant, clone)
            if transport is None:
                return None
            self._owner_transports[key] = transport
            return transport


__all__ = [
    "OWNER_MASKED_PATHS_ENV",
    "OWNER_PREPARE_COMMAND_ENV",
    "OWNER_PREPARE_FAILED",
    "OWNER_PREPARE_TIMEOUT_DEFAULT_S",
    "OWNER_PREPARE_TIMEOUT_ENV",
    "WORKSPACE_WRITE_UNAVAILABLE",
    "OwnerTransportFactory",
    "OwnerWorkspaceWriteSettings",
    "RoomOwnerTransportRouter",
    "build_owner_acp_config",
    "build_owner_acp_transport_factory",
    "build_owner_prepare",
    "is_workspace_write_participant",
    "owner_id_for_participant",
    "resolve_owner_masked_paths",
    "resolve_owner_prepare_command",
    "resolve_owner_prepare_timeout_s",
    "run_owner_prepare_command",
]
