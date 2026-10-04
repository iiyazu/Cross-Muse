"""Construct the isolated Room runtime from already-proven capabilities."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.chat.room_acp_transport import (
    AcpRoomObservationTransport,
    AcpTransportConfig,
)
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_agy_transport import (
    AgyRoomObservationTransport,
    AgyTransportConfig,
)
from xmuse_core.chat.room_codex_native_runtime import RoomCodexNativeRuntime
from xmuse_core.chat.room_codex_projection_cache import RoomCodexProjectionCache
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_execution_ports import ExecutionReviewPort
from xmuse_core.chat.room_host import (
    LongTurnPolicy,
    RoomHostPolicy,
    RoomObservationTransport,
    RoomParticipantHost,
)
from xmuse_core.chat.room_memory_runtime import (
    RoomMemoryContextReceiptPort,
    RoomMemoryDeliveryPumpPort,
    RoomMemoryRecallPort,
)
from xmuse_core.chat.room_owner_transport import (
    OwnerTransportFactory,
    OwnerWorkspaceWriteSettings,
    RoomOwnerTransportRouter,
    build_owner_acp_transport_factory,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

# Live provider turns can legitimately exceed the configured Room default
# (Claude turns of ~280s were observed); each enabled slow provider gets this
# floor, and the lease TTL below covers the longest floor so a delivery can
# never outlive its claim.
PROVIDER_MIN_DELIVERY_TIMEOUT_S: Mapping[str, float] = {
    "claude": 600.0,
    "antigravity": 420.0,
    "opencode": 420.0,
}


@dataclass(frozen=True)
class RoomRuntimeComposition:
    host: RoomParticipantHost
    session_layer: GodSessionLayer
    native_runtime: RoomCodexNativeRuntime
    stream_projector: RoomAgentStreamProjector
    memory_delivery_pump: RoomMemoryDeliveryPumpPort | None
    acp_transports: tuple[AcpRoomObservationTransport, ...] = ()
    agy_transports: tuple[AgyRoomObservationTransport, ...] = ()


def compose_room_runtime(
    *,
    root: Path,
    worktree: Path,
    launchers: Mapping[Any, object],
    controls: RoomObservationControlStore,
    skill_decisions: RoomAttemptSkillDecisionStore,
    skill_catalog: SkillCatalog,
    execution_store: ExecutionReviewPort,
    max_concurrent_rooms: int,
    delivery_timeout_s: float,
    cleanup_grace_s: float,
    runner_generation: str,
    runner_boot_id: str,
    memory_recall: RoomMemoryRecallPort,
    memory_context_receipts: RoomMemoryContextReceiptPort,
    memory_delivery_pump: RoomMemoryDeliveryPumpPort | None,
    claude_acp_config: AcpTransportConfig | None = None,
    agy_config: AgyTransportConfig | None = None,
    opencode_acp_config: AcpTransportConfig | None = None,
    owner_settings: OwnerWorkspaceWriteSettings | None = None,
    owner_transport_factory: OwnerTransportFactory | None = None,
) -> RoomRuntimeComposition:
    """Wire one Room-only runtime without starting process lifecycle tasks.

    ``claude_acp_config``, ``agy_config`` and ``opencode_acp_config`` enable the
    ``claude``, ``antigravity`` and ``opencode`` routes by building each transport
    over the composition's shared disposable Agent preview projector.  The
    always-present ``codex`` route is the Codex app-server transport.  ``agy_config``
    selects the standalone CLI transport for ``antigravity``.
    """

    session_layer = GodSessionLayer(
        registry_path=root / "god_sessions.json",
        launchers=dict(launchers),
    )
    provider_min_delivery_timeout_s = {
        cli_kind: PROVIDER_MIN_DELIVERY_TIMEOUT_S[cli_kind]
        for cli_kind, enabled in (
            ("claude", claude_acp_config is not None),
            ("antigravity", agy_config is not None),
            ("opencode", opencode_acp_config is not None),
        )
        if enabled
    }
    max_delivery_timeout_s = max([delivery_timeout_s, *provider_min_delivery_timeout_s.values()])
    lease_ttl_s = max(
        240,
        int(math.ceil(max_delivery_timeout_s + cleanup_grace_s + 30.0)),
    )
    native_runtime = RoomCodexNativeRuntime(
        root / "chat.db",
        session_layer,
        worktree=worktree,
        runner_generation=runner_generation,
        projection_cache=RoomCodexProjectionCache(root),
    )
    stream_projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    routes: dict[str, RoomObservationTransport] = {}
    acp_transports: list[AcpRoomObservationTransport] = []
    agy_transports: list[AgyRoomObservationTransport] = []
    for acp_config in (claude_acp_config, opencode_acp_config):
        if acp_config is None:
            continue
        acp_transport = AcpRoomObservationTransport(
            config=acp_config,
            registry_path=root / "god_sessions.json",
            control_store=controls,
            skill_decision_store=skill_decisions,
            execution_store=execution_store,
            memory_runtime=memory_context_receipts,
            stream_projector=stream_projector,
        )
        acp_transports.append(acp_transport)
        routes[acp_config.profile.runtime] = acp_transport
    if agy_config is not None:
        agy_transport = AgyRoomObservationTransport(
            config=agy_config,
            registry_path=root / "god_sessions.json",
            control_store=controls,
            skill_decision_store=skill_decisions,
            execution_store=execution_store,
            memory_runtime=memory_context_receipts,
            stream_projector=stream_projector,
        )
        agy_transports.append(agy_transport)
        routes["antigravity"] = agy_transport
    routes["codex"] = CodexRoomObservationTransport(
        session_layer,
        worktree=worktree,
        control_store=controls,
        skill_decision_store=skill_decisions,
        execution_store=execution_store,
        memory_runtime=memory_context_receipts,
        stream_projector=stream_projector,
    )
    owner_factory = owner_transport_factory
    if owner_factory is None and owner_settings is not None:
        owner_factory = build_owner_acp_transport_factory(
            owner_settings,
            registry_path=root / "god_sessions.json",
            control_store=controls,
            skill_decision_store=skill_decisions,
            execution_store=execution_store,
            memory_runtime=memory_context_receipts,
            stream_projector=stream_projector,
        )
    transport = RoomOwnerTransportRouter(
        routes,
        settings=owner_settings,
        transport_factory=owner_factory,
    )
    host = RoomParticipantHost(
        root / "chat.db",
        transport,
        policy=RoomHostPolicy(
            delivery_timeout_s=delivery_timeout_s,
            cleanup_grace_s=cleanup_grace_s,
            lease_ttl_s=lease_ttl_s,
            max_batch_size=max_concurrent_rooms,
            provider_min_delivery_timeout_s=provider_min_delivery_timeout_s,
        ),
        control_store=controls,
        skill_catalog=skill_catalog,
        skill_decision_store=skill_decisions,
        execution_store=execution_store,
        memory_runtime=memory_recall,
        runner_generation=runner_generation,
        runner_boot_id=runner_boot_id,
        delivery_gate=native_runtime.accepts_delivery,
        long_turn_policy=LongTurnPolicy(),
        long_turn_selector=lambda p: p.workspace_access == "workspace_write",
    )
    return RoomRuntimeComposition(
        host=host,
        session_layer=session_layer,
        native_runtime=native_runtime,
        stream_projector=stream_projector,
        memory_delivery_pump=memory_delivery_pump,
        acp_transports=tuple(acp_transports),
        agy_transports=tuple(agy_transports),
    )
