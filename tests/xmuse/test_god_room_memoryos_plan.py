from __future__ import annotations

from importlib import import_module

import pytest

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintFeatureSpec,
    BlueprintLaneDagRequest,
    BlueprintLaneDagService,
    BlueprintLaneSpec,
    LaneFailureEvidence,
    evaluate_lane_recovery,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    compile_blueprint_freeze_from_god_room_events,
)


def test_god_room_memoryos_plan_builds_governed_writes_and_context_requests() -> None:
    try:
        module = import_module("xmuse_core.integrations.god_room_memoryos_plan")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing GOD room MemoryOS plan builder: {exc}")
    participants = [
        GodRoomParticipant(
            participant_id="p-architect",
            god_id="god-architect",
            role="architect",
            cli_id="codex",
        ),
        GodRoomParticipant(
            participant_id="p-execute",
            god_id="execute-god",
            role="execute",
            cli_id="opencode",
        ),
    ]
    events = [
        _event(
            event_id="evt-propose",
            participant=participants[0],
            event_type=GodRoomEventKind.SPEAK,
            content="Build MemoryOS plans from GOD room artifacts.",
            payload={
                "goal": "Build MemoryOS plans from GOD room artifacts.",
                "scope": ["MemoryOS governance"],
                "acceptance_contracts": ["Plans preserve source refs."],
            },
        ),
        _event(
            event_id="evt-freeze",
            participant=participants[1],
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            content="Freeze MemoryOS planning blueprint.",
            causal_parent_id="evt-propose",
            payload={
                "freeze_target_ref": "blueprint:bp-memory:1",
                "goal": "Build MemoryOS plans from GOD room artifacts.",
                "scope": ["MemoryOS governance"],
                "acceptance_contracts": ["Plans preserve source refs."],
            },
        ),
    ]
    freeze = compile_blueprint_freeze_from_god_room_events(
        blueprint_id="bp-memory",
        revision=1,
        events=events,
    )
    lane_dag = BlueprintLaneDagService().build_plan(
        BlueprintLaneDagRequest(
            graph_id="graph-memory",
            resolution_id="resolution-1",
            blueprint=freeze.blueprint,
            features=[
                BlueprintFeatureSpec(
                    feature_id="feature-memory",
                    title="Memory planning",
                    goal="Build governed MemoryOS plans.",
                    acceptance_criteria=["Plans are replayable."],
                    blueprint_refs=["blueprint:bp-memory:1"],
                )
            ],
            lanes=[
                BlueprintLaneSpec(
                    lane_id="lane-memory-plan",
                    feature_id="feature-memory",
                    title="Plan MemoryOS writes",
                    prompt="Build governed MemoryOS write plans.",
                    acceptance_criteria=["Plans use REST-first governance."],
                    blueprint_refs=["blueprint:bp-memory:1"],
                    owner="execute-god",
                    inputs=["blueprint:bp-memory:1"],
                    outputs=["artifact://memoryos/god-room-plan.json"],
                    required_checks=["focused-pytest"],
                    allowed_files=["src/xmuse_core/integrations/god_room_memoryos_plan.py"],
                    rollback_constraints=["do not write MemoryOS state"],
                    review_profile="memory-governance-review",
                )
            ],
            source_refs=["god-room-freeze:evt-freeze"],
        )
    )
    recovery = evaluate_lane_recovery(
        lane_id="lane-memory-plan",
        budget=lane_dag.lane_contracts[0].budget,
        failures=[
            LaneFailureEvidence(
                lane_id="lane-memory-plan",
                attempt=1,
                failure_class="memory_governance_gap",
                reason="No governed plan artifact existed.",
                source_refs=["pytest:memory-governance-gap"],
            )
        ],
    )

    artifact = module.build_god_room_memoryos_plan(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        participants=participants,
        events=events,
        blueprint_freeze=freeze,
        lane_dag=lane_dag,
        recovery_decisions=[recovery],
        live_memoryos_configured=False,
    )

    assert artifact.schema_version == "xmuse.god_room_memoryos_plan.v1"
    assert artifact.source_authority == "god_room_memoryos_plan_contract"
    assert artifact.proof_level == "contract_proof"
    assert artifact.conversation_id == "conv-memory"
    assert artifact.room_id == "room-memory"
    assert artifact.graph_id == "graph-memory"
    assert artifact.plan_count == 5
    assert artifact.ingest_request_count == 5
    assert artifact.live_trace.status == "manual_gap"
    assert artifact.live_trace.proof_level == "manual_gap"
    assert artifact.live_trace.blocked_reason == "memoryos_lite_live_environment_missing"
    assert "god-room-event:evt-freeze" in artifact.source_refs
    assert "lane:lane-memory-plan" in artifact.source_refs

    participant_plans = [
        plan for plan in artifact.plans if plan.event_kind == "god_room_participant_trace"
    ]
    architect_plan = next(
        plan for plan in participant_plans if plan.actor_id == "god-architect"
    )
    plan_by_kind = {
        plan.event_kind: plan
        for plan in artifact.plans
        if plan.event_kind != "god_room_participant_trace"
    }
    assert architect_plan.target_namespace_uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse/"
        "conversation/conv-memory/god/god-architect/private"
    )
    assert plan_by_kind["blueprint_frozen"].memory_layer.value == "pinned_core"
    assert plan_by_kind["blueprint_frozen"].decision == "ingest"
    assert "blueprint:bp-memory:1" in plan_by_kind["blueprint_frozen"].source_refs
    assert plan_by_kind["lane_runtime_contract"].target_namespace_uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse/"
        "conversation/conv-memory/thread/room-memory/god/execute-god/"
        "blueprint/bp-memory/feature/feature-memory/lane/lane-memory-plan"
    )
    assert plan_by_kind["lane_recovery_decision"].source_refs == [
        "lane:lane-memory-plan",
        "pytest:memory-governance-gap",
    ]
    assert artifact.context_plans[0].namespace_uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse/"
        "conversation/conv-memory/thread/room-memory/god/execute-god/"
        "blueprint/bp-memory/feature/feature-memory/lane/lane-memory-plan"
    )
    assert artifact.context_plans[0].query == (
        "Context for lane lane-memory-plan under blueprint bp-memory"
    )


def _event(
    *,
    event_id: str,
    participant: GodRoomParticipant,
    event_type: GodRoomEventKind,
    content: str,
    payload: dict[str, object],
    causal_parent_id: str | None = None,
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id="room-memory",
        conversation_id="conv-memory",
        participant_id=participant.participant_id,
        god_id=participant.god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc=f"2026-06-13T11:0{len(event_id)}:00Z",
        content=content,
        causal_parent_id=causal_parent_id,
        source_refs=[f"message:{event_id}"],
        cli_id=participant.cli_id,
        provider_profile="codex",
        payload=payload,
    )
