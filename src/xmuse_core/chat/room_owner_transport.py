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
import logging
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
from xmuse_core.chat.room_agy_sandbox import (
    build_agy_sandbox_command,
    write_agy_mcp_config,
)
from xmuse_core.chat.room_agy_transport import (
    AgyRoomObservationTransport,
    AgyTransportConfig,
)
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
    OWNER_BOARD_DIR_NAME,
    OwnerClone,
    OwnerCloneError,
    OwnerCloneManager,
)
from xmuse_core.chat.room_owner_ids import owner_id_for_participant
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport
from xmuse_core.chat.room_workspace_sandbox import (
    ROOM_WORKSPACE_WRITE_CONFINEMENT,
    build_workspace_write_sandbox_command,
)

WORKSPACE_WRITE_UNAVAILABLE = "room_workspace_write_unavailable"
OWNER_PREPARE_FAILED = "room_owner_clone_prepare_failed"
OWNER_AGY_TURN_IDLE_TIMEOUT_S = 900.0

OWNER_PREPARE_COMMAND_ENV = "XMUSE_OWNER_PREPARE_COMMAND"
OWNER_PREPARE_TIMEOUT_ENV = "XMUSE_OWNER_PREPARE_TIMEOUT_S"
OWNER_MASKED_PATHS_ENV = "XMUSE_OWNER_MASKED_PATHS"
OWNER_PREPARE_TIMEOUT_DEFAULT_S = 900.0

OwnerTransportFactory = Callable[[Participant, OwnerClone], RoomObservationTransport | None]

logger = logging.getLogger(__name__)


def is_workspace_write_participant(participant: Participant) -> bool:
    """True only for writers the runner can confine (claude/opencode/antigravity)."""

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
    agy_executable: Path | None = None
    agy_default_model: str | None = None
    agy_bridge_script: Path | None = None
    agy_python3: Path | None = None
    extra_masked_paths: tuple[Path, ...] = ()
    prepare_command: tuple[str, ...] | None = None
    prepare_timeout_s: float = OWNER_PREPARE_TIMEOUT_DEFAULT_S
    # Host-owned root of per-owner board views; each owner's directory is
    # mounted read-only at ``<clone>/.xmuse``.  None disables the mount.
    board_root: Path | None = None


def owner_board_dir(settings: OwnerWorkspaceWriteSettings, owner_id: str) -> Path | None:
    """Return (creating) the host-owned board view directory for one owner."""

    if settings.board_root is None:
        return None
    path = Path(settings.board_root) / owner_id
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    readonly_binds: tuple[tuple[Path, Path], ...] = ()
    board_dir = owner_board_dir(settings, clone.owner_id)
    if board_dir is not None:
        mount_point = clone.path.resolve() / OWNER_BOARD_DIR_NAME
        # Clones created before the board existed lack the mount point.
        mount_point.mkdir(exist_ok=True)
        readonly_binds = ((board_dir, mount_point),)
    command = build_workspace_write_sandbox_command(
        bwrap=Path(settings.bwrap),
        provider=participant.cli_kind,
        home=Path(settings.home),
        workspace=clone.path,
        agent_argv=agent_argv,
        # The xmuse root encloses the clones root, so the existing enclosing
        # mask order keeps other owners' clones hidden from this one.
        masked_paths=(settings.xmuse_root, *settings.extra_masked_paths),
        readonly_binds=readonly_binds,
    )
    return AcpTransportConfig(
        workspace=clone.path,
        command=command,
        room_mcp_url=settings.room_mcp_url,
        profile=profile,
        default_model=default_model,
    )


def build_owner_agy_config(
    settings: OwnerWorkspaceWriteSettings,
    *,
    participant: Participant,
    clone: OwnerClone,
) -> AgyTransportConfig | None:
    """Build the sandboxed agy writer config, or None when agy is off."""

    if participant.cli_kind != "antigravity":
        return None
    agy_executable = settings.agy_executable
    bridge_script = settings.agy_bridge_script
    python3 = settings.agy_python3
    model = (participant.model or "").strip() or (settings.agy_default_model or "").strip()
    if agy_executable is None or bridge_script is None or python3 is None or not model:
        return None
    readonly_binds: tuple[tuple[Path, Path], ...] = ()
    board_dir = owner_board_dir(settings, clone.owner_id)
    if board_dir is not None:
        mount_point = clone.path.resolve() / OWNER_BOARD_DIR_NAME
        # Clones created before the board existed lack the mount point.
        mount_point.mkdir(exist_ok=True)
        readonly_binds = ((board_dir, mount_point),)
    mcp_config_path = write_agy_mcp_config(
        Path(settings.xmuse_root) / "runtime" / "agy" / clone.owner_id / "mcp_config.json",
        python3=Path(python3),
        room_mcp_url=settings.room_mcp_url,
    )

    def _command_builder(resume_conversation_id: str | None) -> tuple[str, ...]:
        agy_args: list[str] = [
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--model",
            model,
            "--dangerously-skip-permissions",
        ]
        if resume_conversation_id:
            agy_args.extend(["--conversation", resume_conversation_id])
        # ``-p=`` must be the last agy argument.
        agy_args.append("-p=")
        return build_agy_sandbox_command(
            bwrap=Path(settings.bwrap),
            agy=Path(agy_executable),
            home=Path(settings.home),
            workspace=clone.path,
            workspace_writable=True,
            mcp_config=mcp_config_path,
            bridge_script=Path(bridge_script),
            python3=Path(python3),
            agy_args=agy_args,
            # The xmuse root encloses the clones root, so the existing
            # enclosing mask order keeps other owners' clones hidden.
            masked_paths=(settings.xmuse_root, *settings.extra_masked_paths),
            readonly_binds=readonly_binds,
        )

    return AgyTransportConfig(
        workspace=clone.path,
        command_builder=_command_builder,
        default_model=model,
        confinement=ROOM_WORKSPACE_WRITE_CONFINEMENT,
        owner=True,
        # Owners run builds and test suites that may print nothing for minutes;
        # the host's long-turn stall detection is the real liveness bound.
        turn_idle_timeout_s=OWNER_AGY_TURN_IDLE_TIMEOUT_S,
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

    def _factory(participant: Participant, clone: OwnerClone) -> RoomObservationTransport | None:
        if participant.cli_kind == "antigravity":
            agy_config = build_owner_agy_config(settings, participant=participant, clone=clone)
            if agy_config is None:
                return None
            return AgyRoomObservationTransport(
                config=agy_config,
                registry_path=registry_path,
                control_store=control_store,
                skill_decision_store=skill_decision_store,
                execution_store=execution_store,
                memory_runtime=memory_runtime,
                stream_projector=stream_projector,
            )
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
        settings = self._owner_settings
        if settings is not None and settings.board_root is not None:
            try:
                from xmuse_core.chat.room_board_view import materialize_owner_board_view

                db_path = Path(settings.xmuse_root) / "chat.db"
                board_dir = owner_board_dir(
                    settings,
                    owner_id_for_participant(
                        delivery.conversation_id,
                        delivery.participant.participant_id,
                    ),
                )
                if board_dir is not None:
                    await asyncio.to_thread(
                        materialize_owner_board_view,
                        db_path,
                        delivery.conversation_id,
                        delivery.participant.participant_id,
                        board_dir,
                    )
            except Exception as exc:
                logger.warning("room owner board materialize failed: %s", exc)
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

    async def restart_owner(self, conversation_id: str, participant_id: str) -> bool:
        """Close one owner's dedicated transport; its clone and Room state stay.

        The next delivery to that owner builds a new transport, so the provider
        starts a fresh session without the previous conversation: the same state
        a replaced or restarted owner is in (the module-memory handover case).
        Returns whether a transport was closed. Call it only between deliveries.
        """

        key = (conversation_id, participant_id)
        lock = self._owner_locks.setdefault(key, asyncio.Lock())
        async with lock:
            transport = self._owner_transports.pop(key, None)
        if transport is None:
            return False
        aclose = getattr(transport, "aclose", None)
        if callable(aclose):
            await aclose()
        return True

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
    "build_owner_agy_config",
    "build_owner_prepare",
    "is_workspace_write_participant",
    "owner_board_dir",
    "owner_id_for_participant",
    "resolve_owner_masked_paths",
    "resolve_owner_prepare_command",
    "resolve_owner_prepare_timeout_s",
    "run_owner_prepare_command",
]
