from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.chat.god_room_runtime import (
    GodRoomEventV1,
    GodRoomParticipant,
    sort_god_room_events,
)
from xmuse_core.integrations.memoryos_client import (
    MemoryOSIngestRequest,
    MemoryOSMemoryLayer,
)
from xmuse_core.integrations.memoryos_governance import (
    MemoryOSGovernanceScope,
    MemoryOSGovernedWritePlan,
    default_redaction_hook,
    plan_memoryos_governed_write,
)
from xmuse_core.integrations.memoryos_namespace import (
    MemoryOSNamespace,
    blueprint_namespace,
    god_private_namespace,
    task_namespace,
)
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintLaneDagPlan,
    LaneRecoveryDecision,
    LaneRuntimeContract,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    GodRoomBlueprintFreezeArtifactV1,
)

GOD_ROOM_MEMORYOS_PLAN_SCHEMA = "xmuse.god_room_memoryos_plan.v1"
GOD_ROOM_MEMORYOS_PLAN_AUTHORITY = "god_room_memoryos_plan_contract"


class GodRoomMemoryOSContextPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: MemoryOSNamespace
    namespace_uri: str
    query: str
    budget: int = Field(default=2048, ge=1)
    source_refs: list[str] = Field(default_factory=list)
    proof_level: Literal["contract_proof"] = "contract_proof"
    next_action: str = (
        "Use the REST-first MemoryOS client build_context path when live service "
        "configuration is available."
    )


class GodRoomMemoryOSLiveTracePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["manual_gap", "ready_for_live_capture"]
    proof_level: Literal["manual_gap", "contract_proof"]
    blocked_reason: str | None = None
    next_action: str | None = None


class GodRoomMemoryOSPlanArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xmuse.god_room_memoryos_plan.v1"] = (
        GOD_ROOM_MEMORYOS_PLAN_SCHEMA
    )
    source_authority: Literal["god_room_memoryos_plan_contract"] = (
        GOD_ROOM_MEMORYOS_PLAN_AUTHORITY
    )
    proof_level: Literal["contract_proof", "manual_gap"]
    repo_id: str
    workspace_id: str
    conversation_id: str
    room_id: str
    graph_id: str
    blueprint_id: str
    blueprint_ref: str
    plan_count: int
    ingest_request_count: int
    context_plan_count: int
    plans: list[MemoryOSGovernedWritePlan]
    ingest_requests: list[MemoryOSIngestRequest]
    context_plans: list[GodRoomMemoryOSContextPlan]
    live_trace: GodRoomMemoryOSLiveTracePlan
    source_refs: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    next_action: str | None = None


def build_god_room_memoryos_plan(
    *,
    repo_id: str,
    workspace_id: str,
    participants: list[GodRoomParticipant],
    events: list[GodRoomEventV1],
    blueprint_freeze: GodRoomBlueprintFreezeArtifactV1,
    lane_dag: BlueprintLaneDagPlan,
    recovery_decisions: list[LaneRecoveryDecision] | None = None,
    context_budget: int = 2048,
    live_memoryos_configured: bool = False,
) -> GodRoomMemoryOSPlanArtifactV1:
    ordered_events = sort_god_room_events(events)
    conversation_id = _single_value(
        [event.conversation_id for event in ordered_events],
        "conversation_id",
    )
    room_id = _single_value([event.room_id for event in ordered_events], "room_id")
    if lane_dag.lane_graph.conversation_id != conversation_id:
        raise ValueError("laneDAG conversation_id must match GOD room events")
    if blueprint_freeze.blueprint is None:
        raise ValueError("GOD room MemoryOS plan requires a frozen blueprint")
    blueprint = blueprint_freeze.blueprint
    plans: list[MemoryOSGovernedWritePlan] = []
    plans.extend(
        _participant_trace_plans(
            repo_id=repo_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            participants=participants,
            events=ordered_events,
        )
    )
    plans.append(
        _blueprint_plan(
            repo_id=repo_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            blueprint_freeze=blueprint_freeze,
        )
    )
    lane_namespaces: dict[str, MemoryOSNamespace] = {}
    for contract in lane_dag.lane_contracts:
        namespace = _lane_namespace(
            repo_id=repo_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            room_id=room_id,
            blueprint_id=blueprint.blueprint_id,
            contract=contract,
        )
        lane_namespaces[contract.lane_id] = namespace
        plans.append(
            _lane_contract_plan(
                namespace=namespace,
                contract=contract,
                blueprint_ref=lane_dag.blueprint_ref,
            )
        )
    for recovery in recovery_decisions or []:
        namespace = lane_namespaces.get(recovery.lane_id)
        contract = _contract_by_lane(lane_dag, recovery.lane_id)
        if namespace is None or contract is None:
            continue
        plans.append(
            _lane_recovery_plan(
                namespace=namespace,
                contract=contract,
                recovery=recovery,
            )
        )
    context_plans = [
        GodRoomMemoryOSContextPlan(
            namespace=namespace,
            namespace_uri=namespace.uri,
            query=(
                f"Context for lane {contract.lane_id} under blueprint "
                f"{blueprint.blueprint_id}"
            ),
            budget=context_budget,
            source_refs=_dedupe(
                [f"lane:{contract.lane_id}", lane_dag.blueprint_ref, *contract.source_refs]
            ),
        )
        for contract in lane_dag.lane_contracts
        if (namespace := lane_namespaces.get(contract.lane_id)) is not None
    ]
    ingest_requests = [
        request
        for plan in plans
        if (request := plan.to_ingest_request()) is not None
    ]
    blocked_reasons = _dedupe(
        [plan.blocked_reason for plan in plans if plan.blocked_reason is not None]
    )
    live_trace = _live_trace_plan(live_memoryos_configured=live_memoryos_configured)
    if live_trace.status == "manual_gap" and live_trace.blocked_reason is not None:
        blocked_reasons.append(live_trace.blocked_reason)
    source_refs = _dedupe(
        [
            *[ref for plan in plans for ref in plan.source_refs],
            *[ref for context in context_plans for ref in context.source_refs],
        ]
    )
    target_refs = _dedupe(
        [
            *[plan.target_namespace_uri for plan in plans],
            *[
                plan.shared_namespace_uri
                for plan in plans
                if plan.shared_namespace_uri is not None
            ],
            *[context.namespace_uri for context in context_plans],
        ]
    )
    return GodRoomMemoryOSPlanArtifactV1(
        proof_level="contract_proof",
        repo_id=_require_text(repo_id, "repo_id"),
        workspace_id=_require_text(workspace_id, "workspace_id"),
        conversation_id=conversation_id,
        room_id=room_id,
        graph_id=lane_dag.lane_graph.id,
        blueprint_id=blueprint.blueprint_id,
        blueprint_ref=lane_dag.blueprint_ref,
        plan_count=len(plans),
        ingest_request_count=len(ingest_requests),
        context_plan_count=len(context_plans),
        plans=plans,
        ingest_requests=ingest_requests,
        context_plans=context_plans,
        live_trace=live_trace,
        source_refs=source_refs,
        target_refs=target_refs,
        blocked_reason="; ".join(blocked_reasons) if blocked_reasons else None,
        next_action=live_trace.next_action if live_trace.status == "manual_gap" else None,
    )


def _participant_trace_plans(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    participants: list[GodRoomParticipant],
    events: list[GodRoomEventV1],
) -> list[MemoryOSGovernedWritePlan]:
    plans: list[MemoryOSGovernedWritePlan] = []
    for participant in participants:
        participant_events = [event for event in events if event.god_id == participant.god_id]
        if not participant_events:
            continue
        namespace = god_private_namespace(
            repo_id=repo_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            god_id=participant.god_id,
        )
        plans.append(
            plan_memoryos_governed_write(
                scope=MemoryOSGovernanceScope.PERSONAL,
                event_kind="god_room_participant_trace",
                namespace=namespace,
                actor_id=participant.god_id,
                content=default_redaction_hook(
                    _participant_trace_content(participant, participant_events)
                ),
                source_refs=_dedupe(
                    [
                        ref
                        for event in participant_events
                        for ref in _event_source_refs(event)
                    ]
                ),
                metadata={
                    "xmuse_god_room_conversation_id": conversation_id,
                    "xmuse_god_room_participant_id": participant.participant_id,
                    "xmuse_god_room_event_count": len(participant_events),
                },
            )
        )
    return plans


def _blueprint_plan(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    blueprint_freeze: GodRoomBlueprintFreezeArtifactV1,
) -> MemoryOSGovernedWritePlan:
    blueprint = blueprint_freeze.blueprint
    if blueprint is None:
        raise ValueError("blueprint_freeze.blueprint is required")
    namespace = blueprint_namespace(
        repo_id=repo_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        blueprint_id=blueprint.blueprint_id,
    )
    blueprint_ref = f"blueprint:{blueprint.blueprint_id}:{blueprint.revision}"
    return plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="blueprint_frozen",
        namespace=namespace,
        actor_id=blueprint.approved_by[0] if blueprint.approved_by else "god-room",
        content=default_redaction_hook(
            "\n".join(
                [
                    f"Blueprint frozen: {blueprint_ref}",
                    f"Goal: {blueprint.goal}",
                    "Acceptance contracts:",
                    *[f"- {item}" for item in blueprint.acceptance_contracts],
                ]
            )
        ),
        source_refs=_dedupe([blueprint_ref, *blueprint_freeze.source_refs]),
        memory_layer=MemoryOSMemoryLayer.PINNED_CORE,
        metadata={
            "xmuse_god_room_blueprint_id": blueprint.blueprint_id,
            "xmuse_god_room_blueprint_revision": blueprint.revision,
            "xmuse_god_room_decision_event_id": blueprint_freeze.decision_event_id,
        },
    )


def _lane_contract_plan(
    *,
    namespace: MemoryOSNamespace,
    contract: LaneRuntimeContract,
    blueprint_ref: str,
) -> MemoryOSGovernedWritePlan:
    return plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="lane_runtime_contract",
        namespace=namespace,
        actor_id=contract.owner,
        content=default_redaction_hook(
            "\n".join(
                [
                    f"Lane runtime contract: {contract.lane_id}",
                    f"Feature: {contract.feature_id}",
                    f"Owner: {contract.owner}",
                    "Required checks:",
                    *[f"- {item}" for item in contract.required_checks],
                    "Outputs:",
                    *[f"- {item}" for item in contract.outputs],
                ]
            )
        ),
        source_refs=_dedupe(
            [
                f"lane:{contract.lane_id}",
                blueprint_ref,
                *contract.source_refs,
                *contract.memory_refs,
            ]
        ),
        metadata={
            "xmuse_god_room_lane_id": contract.lane_id,
            "xmuse_god_room_feature_id": contract.feature_id,
            "xmuse_god_room_review_profile": contract.review_profile,
        },
    )


def _lane_recovery_plan(
    *,
    namespace: MemoryOSNamespace,
    contract: LaneRuntimeContract,
    recovery: LaneRecoveryDecision,
) -> MemoryOSGovernedWritePlan:
    return plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="lane_recovery_decision",
        namespace=namespace,
        actor_id=contract.owner,
        content=default_redaction_hook(
            "\n".join(
                [
                    f"Lane recovery decision: {recovery.lane_id}",
                    f"Decision: {recovery.decision.value}",
                    f"Retry allowed: {recovery.retry_allowed}",
                    f"Next action: {recovery.next_action}",
                ]
            )
        ),
        source_refs=_dedupe([f"lane:{recovery.lane_id}", *recovery.source_refs]),
        metadata={
            "xmuse_god_room_lane_id": recovery.lane_id,
            "xmuse_god_room_recovery_decision": recovery.decision.value,
            "xmuse_god_room_retry_allowed": recovery.retry_allowed,
        },
    )


def _lane_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    room_id: str,
    blueprint_id: str,
    contract: LaneRuntimeContract,
) -> MemoryOSNamespace:
    return task_namespace(
        repo_id=repo_id,
        workspace_id=workspace_id,
        god_id=contract.owner,
        conversation_id=conversation_id,
        thread_id=room_id,
        blueprint_id=blueprint_id,
        feature_id=contract.feature_id,
        lane_id=contract.lane_id,
    )


def _contract_by_lane(
    lane_dag: BlueprintLaneDagPlan,
    lane_id: str,
) -> LaneRuntimeContract | None:
    for contract in lane_dag.lane_contracts:
        if contract.lane_id == lane_id:
            return contract
    return None


def _participant_trace_content(
    participant: GodRoomParticipant,
    events: list[GodRoomEventV1],
) -> str:
    lines = [
        "GOD room participant trace",
        f"God: {participant.god_id}",
        f"Participant: {participant.participant_id}",
        "Events:",
    ]
    lines.extend(
        f"- {event.event_id} [{event.event_type.value}]: {event.content}"
        for event in events
    )
    return "\n".join(lines)


def _event_source_refs(event: GodRoomEventV1) -> list[str]:
    return [f"god-room-event:{event.event_id}", *event.source_refs]


def _live_trace_plan(
    *,
    live_memoryos_configured: bool,
) -> GodRoomMemoryOSLiveTracePlan:
    if live_memoryos_configured:
        return GodRoomMemoryOSLiveTracePlan(
            status="ready_for_live_capture",
            proof_level="contract_proof",
            next_action=(
                "Run xmuse-memoryos-live-trace-capture against the generated "
                "governed write/context plan to obtain live_service_proof."
            ),
        )
    return GodRoomMemoryOSLiveTracePlan(
        status="manual_gap",
        proof_level="manual_gap",
        blocked_reason="memoryos_lite_live_environment_missing",
        next_action=(
            "Configure XMUSE_LIVE_MEMORYOS_LITE and XMUSE_MEMORYOS_LITE_URL, then "
            "run xmuse-memoryos-live-trace-capture for live trace proof."
        ),
    )


def _single_value(values: list[str], label: str) -> str:
    cleaned = _dedupe([_require_text(value, label) for value in values])
    if len(cleaned) != 1:
        raise ValueError(f"GOD room MemoryOS plan requires one {label}")
    return cleaned[0]


def _require_text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must be non-empty")
    return value


def _dedupe(values: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "GOD_ROOM_MEMORYOS_PLAN_AUTHORITY",
    "GOD_ROOM_MEMORYOS_PLAN_SCHEMA",
    "GodRoomMemoryOSContextPlan",
    "GodRoomMemoryOSLiveTracePlan",
    "GodRoomMemoryOSPlanArtifactV1",
    "build_god_room_memoryos_plan",
]
