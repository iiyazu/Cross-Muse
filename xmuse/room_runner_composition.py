"""Construct the isolated Room runtime from already-proven capabilities."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_codex_native_runtime import RoomCodexNativeRuntime
from xmuse_core.chat.room_codex_projection_cache import RoomCodexProjectionCache
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_execution_store import RoomExecutionStore
from xmuse_core.chat.room_host import RoomHostPolicy, RoomParticipantHost
from xmuse_core.chat.room_memory_runtime import RoomMemoryRuntime
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog


@dataclass(frozen=True)
class RoomRuntimeComposition:
    host: RoomParticipantHost
    session_layer: GodSessionLayer
    native_runtime: RoomCodexNativeRuntime
    stream_projector: RoomAgentStreamProjector
    memory_runtime: RoomMemoryRuntime
    memory_enabled: bool


def compose_room_runtime(
    *,
    root: Path,
    worktree: Path,
    launchers: Mapping[Any, object],
    controls: RoomObservationControlStore,
    skill_decisions: RoomAttemptSkillDecisionStore,
    skill_catalog: SkillCatalog,
    execution_store: RoomExecutionStore,
    max_concurrent_rooms: int,
    delivery_timeout_s: float,
    cleanup_grace_s: float,
    runner_generation: str,
    runner_boot_id: str,
    memory_runtime: RoomMemoryRuntime,
    memory_enabled: bool = False,
) -> RoomRuntimeComposition:
    """Wire one Room-only runtime without starting process lifecycle tasks."""

    session_layer = GodSessionLayer(
        registry_path=root / "god_sessions.json",
        launchers=dict(launchers),
    )
    lease_ttl_s = max(
        240,
        int(math.ceil(delivery_timeout_s + cleanup_grace_s + 30.0)),
    )
    native_runtime = RoomCodexNativeRuntime(
        root / "chat.db",
        session_layer,
        worktree=worktree,
        runner_generation=runner_generation,
        projection_cache=RoomCodexProjectionCache(root),
    )
    stream_projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    host = RoomParticipantHost(
        root / "chat.db",
        CodexRoomObservationTransport(
            session_layer,
            worktree=worktree,
            control_store=controls,
            skill_decision_store=skill_decisions,
            execution_store=execution_store,
            memory_runtime=memory_runtime,
            stream_projector=stream_projector,
        ),
        policy=RoomHostPolicy(
            delivery_timeout_s=delivery_timeout_s,
            cleanup_grace_s=cleanup_grace_s,
            lease_ttl_s=lease_ttl_s,
            max_batch_size=max_concurrent_rooms,
        ),
        control_store=controls,
        skill_catalog=skill_catalog,
        skill_decision_store=skill_decisions,
        execution_store=execution_store,
        memory_runtime=memory_runtime,
        runner_generation=runner_generation,
        runner_boot_id=runner_boot_id,
        delivery_gate=native_runtime.accepts_delivery,
    )
    return RoomRuntimeComposition(
        host=host,
        session_layer=session_layer,
        native_runtime=native_runtime,
        stream_projector=stream_projector,
        memory_runtime=memory_runtime,
        memory_enabled=memory_enabled,
    )
