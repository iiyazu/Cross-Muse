#!/usr/bin/env python3
"""REST API for the xmuse chat-plane MVP."""

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.api_models import (
    BlueprintFreezeRequest,
    BootstrapApplyCreate,
    BootstrapProposalCreate,
    CollaborationBlockerCreate,
    CollaborationBlockerResolve,
    CollaborationDispatchGateRequest,
    CollaborationRequestCreate,
    CollaborationResponseCreate,
    ConversationCreate,
    DeliberationAppendCreate,
    DispatchClaimRequest,
    DispatchDispatchedRequest,
    DispatchFailedRequest,
    GodRoomBlueprintFreezeRequest,
    GodRoomLaneDagRequest,
    GodRoomLanePatchForwardRequest,
    GodRoomLaneRecoveryRequest,
    GodRoomLaneReviewIntakeRequest,
    GodRoomLaneReviewVerdictRequest,
    GodRoomMemoryPlanRequest,
    GodRoomProviderInvocationCaptureRequest,
    GodRoomProviderInvocationRequest,
    GodRoomSpeakerAttemptRequest,
    GodRoomSpeakerResponseRequest,
    MessageCreate,
    OperatorActionCreate,
    ParticipantInit,
    PeerForkCreate,
    ProposalApproval,
    ProposalCreate,
    RoleTemplateCreate,
    RoleTemplateUpdate,
    ThreadMessageCreate,
)
from xmuse_core.chat.collaboration_contracts import (
    CollaborationRun,
    DispatchGateDecision,
)
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.deliberation_engine import DeliberationFreezeGuard
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.god_room_event_store import (
    GodRoomEventConflictError,
    GodRoomEventStore,
    GodRoomMembershipError,
)
from xmuse_core.chat.god_room_provider_invocation import (
    invoke_god_room_provider_speech,
)
from xmuse_core.chat.god_room_runtime import GodRoomEventV1, GodRoomParticipant
from xmuse_core.chat.god_room_speaker_response import (
    GodRoomProviderSpeechResponseV1,
    capture_god_room_speaker_response,
)
from xmuse_core.chat.god_room_speaker_runtime import build_god_room_speaker_attempt
from xmuse_core.chat.health_cards import build_run_health_chat_card
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import (
    INIT_GOD_ROLE,
    ParticipantStore,
    RoleTemplate,
    RoleTemplateStore,
    provider_profile_id_for_template_slug,
    resolve_codex_cli_kind,
)
from xmuse_core.chat.peer_proposals import classify_structured_proposal
from xmuse_core.chat.peer_service import PeerChatError, PeerChatService
from xmuse_core.chat.protocol_v2 import DeliberationMessageV1
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.god_room_memoryos_plan import (
    build_god_room_memoryos_plan,
)
from xmuse_core.integrations.memoryos_lite_interop import live_memoryos_lite_enabled
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.platform.http_auth import (
    authorize_chat_api_write,
    require_production_write_auth_token,
)
from xmuse_core.platform.operator_actions import (
    OperatorActionBlockedError,
    OperatorActionRequest,
    OperatorActionResult,
    OperatorActionService,
)
from xmuse_core.platform.read_contracts import build_execution_drilldown_refs
from xmuse_core.platform.release_evidence_attempts import (
    run_release_evidence_attempt_action,
)
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)
from xmuse_core.platform.run_health import summarize_run_health
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore
from xmuse_core.providers.god_identity_binding import GodIdentityBindingStore
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.structuring.blueprint_execution.approval_events import (
    produce_blueprint_approval_event,
)
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintLaneDagPlan,
    BlueprintLaneDagRequest,
    BlueprintLaneDagService,
    LaneRecoveryDecision,
    evaluate_lane_recovery,
)
from xmuse_core.structuring.feature_plan_store import (
    build_feature_plan_proposal,
    read_approved_mission_blueprint,
    save_approved_feature_plan_artifacts,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    GodRoomBlueprintFreezeArtifactV1,
    GodRoomBlueprintFreezeStatus,
    compile_blueprint_freeze_from_god_room_events,
)
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintDecisionLogEntry,
    MissionBlueprintStatus,
    MissionBlueprintV1,
    render_mission_blueprint_markdown,
)
from xmuse_core.structuring.models import (
    FeaturePlanFeature,
    FeaturePlanProposalApproval,
    ReviewDecision,
    ReviewVerdict,
)
from xmuse_core.structuring.planner import build_lane_graph
from xmuse_core.structuring.projection import project_ready_lanes

DEFAULT_PORT = 8201
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIR = default_xmuse_root(Path(__file__).resolve().parent)
_EXECUTION_CARD_TYPES = {
    "blueprint_execution_started",
    "feature_plan_ready",
    "lane_graph_ready",
    "run_progress",
    "run_takeover",
    "run_terminal",
}


def _auth_token_from_env() -> str | None:
    value = (
        os.environ.get("XMUSE_CHAT_API_AUTH_TOKEN")
        or os.environ.get("XMUSE_CHAT_API_KEY")
        or ""
    ).strip()
    return value or None


def _store(base_dir: Path) -> ChatStore:
    return ChatStore(base_dir / "chat.db")


def _peer_service(base_dir: Path) -> PeerChatService:
    return PeerChatService(base_dir / "chat.db")


def _plain_human_message_payload(
    base_dir: Path,
    *,
    conversation_id: str,
    author: str,
    content: str,
) -> dict[str, object]:
    try:
        message = _store(base_dir).add_message(
            conversation_id=conversation_id,
            author=author,
            role="human",
            content=content,
            mentions=[],
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    payload = message.model_dump(mode="json")
    payload["inbox_items"] = []
    return payload


def _request_id(value: str | None) -> str:
    return value or f"rest_{uuid.uuid4().hex}"


def _participant_store(base_dir: Path) -> ParticipantStore:
    _store(base_dir)
    return ParticipantStore(base_dir / "chat.db")


def _role_template_store(base_dir: Path) -> RoleTemplateStore:
    _store(base_dir)
    return RoleTemplateStore(base_dir / "chat.db")


def _collaboration_store(base_dir: Path) -> ChatCollaborationStore:
    return ChatCollaborationStore(base_dir / "chat.db")


def _dispatch_queue_store(base_dir: Path) -> ChatDispatchQueueStore:
    return ChatDispatchQueueStore(base_dir / "chat.db")


def _god_room_event_store(base_dir: Path) -> GodRoomEventStore:
    return GodRoomEventStore(base_dir / "god_room_events.sqlite3")


def _operator_action_service(base_dir: Path) -> OperatorActionService:
    return OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=base_dir / "work" / "operator_actions",
        registration_store=GodCliRegistrationStore(
            base_dir / "god_cli_registrations.json"
        ),
        selection_store=GodCliSelectionStore(base_dir / "god_cli_selections.json"),
        god_identity_binding_store=GodIdentityBindingStore(
            base_dir / "god_identity_bindings.json"
        ),
        lane_state_machine=LaneStateMachine(
            base_dir / "feature_lanes.json",
            history_path=base_dir / "state_history.json",
        ),
        blueprint_freeze_handler=lambda request: _operator_freeze_blueprint(
            base_dir,
            request,
        ),
        release_evidence_export_handler=lambda request: run_release_evidence_export_action(
            request,
            xmuse_root=base_dir,
            release_readiness_dir=base_dir / "work" / "release_readiness",
        ),
        release_evidence_candidate_handler=lambda request: (
            _operator_release_evidence_candidates(base_dir, request)
        ),
        release_evidence_attempt_handler=lambda request: run_release_evidence_attempt_action(
            request,
            xmuse_root=base_dir,
            release_readiness_dir=base_dir / "work" / "release_readiness",
        ),
    )


def _god_cli_registration_store(base_dir: Path) -> GodCliRegistrationStore:
    return GodCliRegistrationStore(base_dir / "god_cli_registrations.json")


def _god_cli_selection_store(base_dir: Path) -> GodCliSelectionStore:
    return GodCliSelectionStore(base_dir / "god_cli_selections.json")


def _god_identity_binding_store(base_dir: Path) -> GodIdentityBindingStore:
    return GodIdentityBindingStore(base_dir / "god_identity_bindings.json")


def _god_session_registry(base_dir: Path) -> GodSessionRegistry:
    return GodSessionRegistry(base_dir / "god_sessions.json")


def _selected_god_binding_resolver(base_dir: Path, room_id: str):
    store = _god_identity_binding_store(base_dir)

    def resolve(participant: GodRoomParticipant) -> dict[str, object]:
        return store.resolve(
            room_id=room_id,
            participant_id=participant.participant_id,
            god_id=participant.god_id,
        ).model_dump(mode="json")

    return resolve


def _operator_actor_id(request: Request) -> str:
    value = request.headers.get("X-XMuse-Operator-Id", "")
    return value.strip() or "anonymous-operator"


def _operator_payload_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _operator_release_evidence_candidates(
    base_dir: Path,
    request: OperatorActionRequest,
) -> dict[str, object]:
    return build_release_evidence_candidate_report(
        base_dir,
        conversation_id=_operator_payload_text(request.payload.get("conversation_id")),
        memoryos_payload=request.payload,
        trace_limit=_operator_payload_int(request.payload.get("trace_limit"), default=20),
    )


def _operator_payload_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _operator_capabilities(request: Request) -> tuple[str, ...]:
    raw = request.headers.get("X-XMuse-Operator-Capabilities", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _operator_role(request: Request) -> str:
    value = request.headers.get("X-XMuse-Operator-Role", "")
    return value.strip() or "operator"


def _operator_action_http_status(result: OperatorActionResult) -> int:
    if result.status == "denied":
        return status.HTTP_403_FORBIDDEN
    if result.status in {"blocked", "manual_gap"}:
        return status.HTTP_409_CONFLICT
    return status.HTTP_200_OK


def _collaboration_run_refs(references: list[str]) -> list[str]:
    run_ids: list[str] = []
    for reference in references:
        if not reference.startswith("collaboration:"):
            continue
        run_id = reference.removeprefix("collaboration:").strip()
        if run_id:
            run_ids.append(run_id)
    return run_ids


def _enforce_collaboration_dispatch_gate(
    base_dir: Path,
    *,
    conversation_id: str,
    proposal_id: str,
    proposal_type: str,
    references: list[str],
) -> None:
    store = _collaboration_store(base_dir)
    for run_id in _collaboration_run_refs(references):
        run = _collaboration_run_or_none(store, run_id)
        decision = store.evaluate_dispatch_gate(
            conversation_id=conversation_id,
            run_id=run_id,
            proposal_ref=f"proposal:{proposal_id}",
            artifact_ref=f"artifact:{proposal_type}",
            execute_confirmed=_collaboration_execute_confirmed(run),
            policy_allows_real_provider=True,
        )
        if decision is not DispatchGateDecision.ALLOWED:
            raise PeerChatError("dispatch_gate_blocked", decision.value)


def _collaboration_run_or_none(
    store: ChatCollaborationStore,
    run_id: str,
) -> CollaborationRun | None:
    try:
        return store.get_run(run_id)
    except KeyError:
        return None


def _collaboration_execute_confirmed(run: CollaborationRun | None) -> bool:
    if run is None:
        return False
    return any(
        response.target == "execute"
        and response.status == "received"
        and _execute_feasibility_verdict_confirmed(response.content)
        for response in run.responses
    )


def _execute_feasibility_verdict_confirmed(content: str) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("type") != "execute_feasibility_verdict":
        return False
    if payload.get("status") != "executable":
        return False
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        return False
    return any(isinstance(ref, str) and bool(ref.strip()) for ref in evidence_refs)


def _conversation_exists(store: ChatStore, conversation_id: str) -> bool:
    return any(conversation.id == conversation_id for conversation in store.list_conversations())


def _deliberation_message_from_request(
    conversation_id: str,
    request: DeliberationAppendCreate,
) -> DeliberationMessageV1:
    return DeliberationMessageV1(
        msg_id=request.msg_id,
        conversation_id=conversation_id,
        agent_id=request.agent_id,
        lamport_ts=request.lamport_ts,
        kind=request.kind,
        parent_id=request.parent_id,
        target_ref=request.target_ref,
        mentions=request.mentions,
        payload=request.payload,
        source_refs=request.source_refs,
        objection_level=request.objection_level,
        decision_scope=request.decision_scope,
    )


def _deliberation_content(message: DeliberationMessageV1) -> str:
    for key in ("summary", "question", "body", "commitment", "evidence", "vote"):
        value = message.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{message.kind.value}: {message.msg_id}"


def _stored_deliberation_messages(
    store: ChatStore,
    conversation_id: str,
) -> list[DeliberationMessageV1]:
    messages: list[DeliberationMessageV1] = []
    for message in store.list_messages(conversation_id):
        if message.envelope_type != "deliberation":
            continue
        envelope = message.envelope_json or {}
        payload = envelope.get("message")
        if not isinstance(payload, dict):
            continue
        try:
            messages.append(DeliberationMessageV1.model_validate(payload))
        except ValidationError:
            continue
    return messages


def _frozen_blueprint_from_request(
    request: BlueprintFreezeRequest,
    *,
    conversation_id: str,
    decision_evidence_refs: list[str],
    decision_open_questions: list[dict[str, Any]],
    commit_agent_ids: list[str],
) -> MissionBlueprintV1:
    source_refs = _dedupe_text([*request.blueprint.source_refs, *decision_evidence_refs])
    open_questions = _dedupe_text(
        [
            *request.blueprint.open_questions,
            *[
                str(question["question"])
                for question in decision_open_questions
                if isinstance(question.get("question"), str)
            ],
        ]
    )
    return MissionBlueprintV1(
        blueprint_id=request.blueprint.blueprint_id,
        conversation_id=conversation_id,
        revision=request.blueprint.revision,
        goal=request.blueprint.goal,
        scope=request.blueprint.scope,
        constraints=request.blueprint.constraints,
        non_goals=request.blueprint.non_goals,
        acceptance_contracts=request.blueprint.acceptance_contracts,
        repo_areas=request.blueprint.repo_areas,
        open_questions=open_questions,
        decision_log=[
            MissionBlueprintDecisionLogEntry(
                decision="deliberation freeze allowed",
                source_refs=decision_evidence_refs,
            )
        ],
        source_refs=source_refs,
        status=MissionBlueprintStatus.FROZEN,
        approved_by=commit_agent_ids,
    )


def _blueprint_resolution_content(
    blueprint: MissionBlueprintV1,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    markdown = render_mission_blueprint_markdown(blueprint)
    return {
        "type": "mission_blueprint",
        "title": blueprint.goal,
        "body": markdown,
        "acceptance_criteria": blueprint.acceptance_contracts,
        "references": blueprint.source_refs,
        "blueprint_v1": blueprint.model_dump(mode="json"),
        "markdown": markdown,
        "freeze_decision": decision_payload,
        "open_questions": blueprint.open_questions,
        "repo_areas": blueprint.repo_areas,
    }


def _persist_blueprint_resolution(
    base_dir: Path,
    *,
    conversation_id: str,
    blueprint: MissionBlueprintV1,
    decision_payload: dict[str, Any],
    author: str,
    approval_mode: str,
    envelope_type: str,
    target_ref: str,
    content_extra: dict[str, Any] | None = None,
    envelope_extra: dict[str, Any] | None = None,
) -> dict[str, object]:
    store = _store(base_dir)
    content = _blueprint_resolution_content(blueprint, decision_payload)
    if content_extra:
        content.update(content_extra)
    proposal = store.create_proposal(
        conversation_id=conversation_id,
        author=author,
        proposal_type="mission_blueprint",
        content=json.dumps(content, ensure_ascii=False, sort_keys=True),
        references=blueprint.source_refs,
    )
    resolution = store.approve_proposal(
        proposal.id,
        approved_by=blueprint.approved_by,
        approval_mode=approval_mode,
        goal_summary=blueprint.goal,
        content=content,
    )
    resolution_payload = resolution.model_dump(mode="json")
    _append_resolution_read_model(base_dir, resolution_payload)
    produce_blueprint_approval_event(base_dir, resolution)
    envelope_json: dict[str, Any] = {
        "type": envelope_type,
        "target_ref": target_ref,
        "proposal_id": proposal.id,
        "resolution_id": resolution.id,
        "blueprint": blueprint.model_dump(mode="json"),
        "decision": decision_payload,
    }
    if envelope_extra:
        envelope_json.update(envelope_extra)
    message = store.add_message(
        conversation_id=conversation_id,
        author=author,
        role="assistant",
        content=f"Frozen mission blueprint: {blueprint.goal}",
        envelope_type=envelope_type,
        envelope_json=envelope_json,
    )
    return {
        "decision": decision_payload,
        "blueprint": blueprint.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "resolution": resolution_payload,
        "message": message.model_dump(mode="json"),
    }


def _operator_freeze_blueprint(
    base_dir: Path,
    request: OperatorActionRequest,
) -> dict[str, object]:
    conversation_id = str(request.payload.get("conversation_id") or "").strip()
    if not conversation_id:
        raise OperatorActionBlockedError(
            "freeze_blueprint requires payload.conversation_id",
            proof_level="manual_gap",
        )
    try:
        freeze_request = BlueprintFreezeRequest.model_validate(
            {
                key: value
                for key, value in request.payload.items()
                if key != "conversation_id"
            }
        )
    except ValidationError as exc:
        raise OperatorActionBlockedError(
            "freeze_blueprint payload is invalid",
            payload={"errors": exc.errors()},
        ) from exc
    try:
        return _freeze_blueprint_for_request(
            base_dir,
            conversation_id=conversation_id,
            request=freeze_request,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        summary = "blueprint freeze blocked"
        if isinstance(detail, dict):
            message = detail.get("message")
            code = detail.get("code")
            if isinstance(message, str) and message.strip():
                summary = message.strip()
            elif isinstance(code, str) and code.strip():
                summary = code.strip()
            elif isinstance(detail.get("decision"), dict):
                reason = detail["decision"].get("reason")
                if isinstance(reason, str) and reason.strip():
                    summary = reason.strip()
        raise OperatorActionBlockedError(
            summary,
            payload={"detail": detail},
        ) from exc


def _freeze_blueprint_for_request(
    base_dir: Path,
    *,
    conversation_id: str,
    request: BlueprintFreezeRequest,
) -> dict[str, object]:
    store = _store(base_dir)
    if not _conversation_exists(store, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    deliberations = _stored_deliberation_messages(store, conversation_id)
    decision = DeliberationFreezeGuard(
        required_commits=request.required_commits,
        objection_window_lamports=request.objection_window_lamports,
    ).evaluate(deliberations, target_ref=request.target_ref)
    decision_payload = decision.model_dump(mode="json")
    if not decision.can_freeze:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "blueprint_freeze_blocked",
                "decision": decision_payload,
            },
        )
    try:
        blueprint = _frozen_blueprint_from_request(
            request,
            conversation_id=conversation_id,
            decision_evidence_refs=decision.evidence_refs,
            decision_open_questions=decision.open_questions,
            commit_agent_ids=decision.commit_agent_ids,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return _persist_blueprint_resolution(
        base_dir,
        conversation_id=conversation_id,
        author="xmuse-deliberation",
        approval_mode="deliberation_freeze",
        envelope_type="blueprint_freeze",
        target_ref=request.target_ref,
        blueprint=blueprint,
        decision_payload=decision_payload,
    )


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _role_template_has_participants(base_dir: Path, template_id: str) -> bool:
    store = _store(base_dir)
    participant_store = _participant_store(base_dir)
    for conversation in store.list_conversations():
        for participant in participant_store.list_by_conversation(conversation.id):
            if participant.role_template_id == template_id:
                return True
    return False


def _mark_review_trigger_read_for_approved_proposal(
    base_dir: Path,
    *,
    conversation_id: str,
    proposal_id: str,
) -> None:
    store = _store(base_dir)
    try:
        proposal = store.get_proposal(proposal_id)
    except KeyError:
        return
    if proposal.proposal_type != "lane_graph":
        return
    proposal_message_id = None
    for message in store.list_messages(conversation_id):
        if (
            message.envelope_type == "proposal"
            and message.envelope_json.get("proposal_id") == proposal_id
        ):
            proposal_message_id = message.id
            break
    if proposal_message_id is None:
        return
    inbox = ChatInboxStore(base_dir / "chat.db")
    for item in inbox.list_by_conversation(conversation_id, include_terminal=True):
        if (
            item.item_type == "review_trigger"
            and item.source_message_id == proposal_message_id
            and item.status in {"unread", "claimed"}
        ):
            inbox.mark_read(item.id, responded_message_id=proposal_message_id)


def _public_peer_participants(payload: dict[str, object]) -> list[dict[str, object]]:
    participants = payload.get("participants")
    if not isinstance(participants, list):
        return []
    return [
        participant
        for participant in participants
        if isinstance(participant, dict) and participant.get("role") != "init"
    ]


def _default_god_room_id(conversation_id: str) -> str:
    return f"god-room:{conversation_id}"


def _god_room_participants(base_dir: Path, conversation_id: str) -> list[GodRoomParticipant]:
    participants = _participant_store(base_dir).list_by_conversation(conversation_id)
    return [
        GodRoomParticipant(
            participant_id=participant.participant_id,
            god_id=participant.display_name,
            cli_id=participant.cli_kind,
            role=participant.role,
        )
        for participant in participants
        if participant.status == "active" and participant.role != INIT_GOD_ROLE
    ]


def _god_room_payload(
    store: GodRoomEventStore,
    room_id: str,
) -> dict[str, object]:
    snapshot = store.load_room(room_id)
    replay = store.replay_room(room_id)
    return {
        "source_authority": "god_room_event_store",
        "room_id": snapshot.room_id,
        "conversation_id": snapshot.conversation_id,
        "participants": [
            participant.model_dump(mode="json")
            for participant in snapshot.participants
        ],
        "events": [event.model_dump(mode="json") for event in snapshot.events],
        "replay": replay.model_dump(mode="json"),
    }


def _freeze_blueprint_from_god_room(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomBlueprintFreezeRequest,
) -> dict[str, object]:
    chat_store = _store(base_dir)
    if not _conversation_exists(chat_store, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    event_store = _god_room_event_store(base_dir)
    room_id = _default_god_room_id(conversation_id)
    try:
        room = event_store.load_room(room_id)
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "god_room_not_found", "message": str(exc)},
        ) from exc
    try:
        artifact = compile_blueprint_freeze_from_god_room_events(
            blueprint_id=request.blueprint_id,
            revision=request.revision,
            events=room.events,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_blueprint_freeze_invalid",
                "message": str(exc),
                "source_authority": "god_room_event_store",
                "room_id": room_id,
            },
        ) from exc
    artifact_payload = artifact.model_dump(mode="json")
    if (
        artifact.status is not GodRoomBlueprintFreezeStatus.FROZEN
        or artifact.blueprint is None
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_blueprint_freeze_blocked",
                "source_authority": "god_room_event_store",
                "room_id": room_id,
                "artifact": artifact_payload,
                "blocked_reason": artifact.blocked_reason,
            },
        )
    blueprint = artifact.blueprint
    target_ref = f"blueprint:{blueprint.blueprint_id}:{blueprint.revision}"
    decision_payload = {
        "status": "allowed",
        "reason": "god_room_freeze_requested",
        "source_authority": "god_room_event_store",
        "room_id": room_id,
        "decision_event_id": artifact.decision_event_id,
        "source_refs": artifact.source_refs,
    }
    result = _persist_blueprint_resolution(
        base_dir,
        conversation_id=conversation_id,
        blueprint=blueprint,
        decision_payload=decision_payload,
        author="xmuse-god-room",
        approval_mode="god_room_blueprint_freeze",
        envelope_type="god_room_blueprint_freeze",
        target_ref=target_ref,
        content_extra={
            "source_authority": "god_room_event_store",
            "god_room_blueprint_freeze": artifact_payload,
        },
        envelope_extra={
            "room_id": room_id,
            "god_room_blueprint_freeze": artifact_payload,
        },
    )
    result["source_authority"] = "god_room_event_store"
    result["artifact"] = artifact_payload
    result["room"] = _god_room_payload(event_store, room_id)
    return result


def _build_lane_dag_from_god_room_freeze(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomLaneDagRequest,
) -> dict[str, object]:
    store = _store(base_dir)
    if not _conversation_exists(store, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    try:
        resolution = store.get_resolution(request.resolution_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="resolution not found") from exc
    if resolution.conversation_id != conversation_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_resolution_mismatch",
                "message": "resolution does not belong to the conversation",
            },
        )
    freeze_artifact = _god_room_blueprint_freeze_artifact_for_lane_dag(resolution)
    blueprint = freeze_artifact.blueprint
    if blueprint is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_requires_frozen_blueprint",
                "message": "GOD room blueprint freeze artifact is missing a blueprint",
            },
        )
    try:
        plan = BlueprintLaneDagService().build_plan(
            BlueprintLaneDagRequest(
                graph_id=request.graph_id,
                resolution_id=resolution.id,
                graph_version=request.graph_version,
                blueprint=blueprint,
                blueprint_proof_level=freeze_artifact.proof_level,
                features=request.features,
                lanes=request.lanes,
                source_refs=[
                    f"resolution:{resolution.id}",
                    *freeze_artifact.source_refs,
                    *request.source_refs,
                ],
            )
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_invalid",
                "message": str(exc),
                "source_authority": "mission_blueprint_resolution",
                "resolution_id": resolution.id,
            },
        ) from exc
    artifacts = _write_lane_dag_artifacts(base_dir, plan)
    return {
        "source_authority": "mission_blueprint_resolution",
        "resolution_id": resolution.id,
        "blueprint_ref": plan.blueprint_ref,
        "lane_dag": plan.model_dump(mode="json"),
        "artifacts": artifacts,
    }


def _evaluate_god_room_lane_recovery(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomLaneRecoveryRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    plan = _load_lane_dag_plan(base_dir, request.graph_id)
    plan_conversation_id = str(plan.lane_graph.conversation_id)
    if plan_conversation_id != conversation_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_recovery_conversation_mismatch",
                "message": "laneDAG artifact does not belong to the conversation",
            },
        )
    contract = next(
        (
            lane_contract
            for lane_contract in plan.lane_contracts
            if lane_contract.lane_id == request.lane_id
        ),
        None,
    )
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_recovery_unknown_lane",
                "message": f"lane runtime contract not found: {request.lane_id}",
            },
        )
    decision = evaluate_lane_recovery(
        lane_id=request.lane_id,
        budget=contract.budget,
        failures=request.failures,
        runtime_seconds=request.runtime_seconds,
    )
    authority_refs = _dedupe_text(
        [
            plan.blueprint_ref,
            *plan.source_refs,
            *contract.source_refs,
            *decision.source_refs,
        ]
    )
    recovery_payload = {
        "schema_version": "xmuse.god_room_lane_recovery.v1",
        "source_authority": "lane_dag_artifact",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "blueprint_proof_level": plan.blueprint_proof_level,
        "source_refs": authority_refs,
        "decision": decision.model_dump(mode="json"),
        "lane_contract": contract.model_dump(mode="json"),
        "failure_count": len(request.failures),
    }
    recovery_path = _write_lane_recovery_artifact(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
        payload=recovery_payload,
    )
    return {
        "source_authority": "lane_dag_artifact",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "blueprint_proof_level": plan.blueprint_proof_level,
        "source_refs": authority_refs,
        "decision": decision.model_dump(mode="json"),
        "lane_dag": plan.model_dump(mode="json"),
        "artifacts": {"recovery": str(recovery_path.relative_to(base_dir))},
    }


def _build_god_room_lane_review_intake(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomLaneReviewIntakeRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    plan = _load_lane_dag_plan(base_dir, request.graph_id)
    if str(plan.lane_graph.conversation_id) != conversation_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_conversation_mismatch",
                "message": "laneDAG artifact does not belong to the conversation",
            },
        )
    contract = next(
        (
            lane_contract
            for lane_contract in plan.lane_contracts
            if lane_contract.lane_id == request.lane_id
        ),
        None,
    )
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_review_unknown_lane",
                "message": f"lane runtime contract not found: {request.lane_id}",
            },
        )
    recovery_decisions = _load_lane_recovery_decisions(
        base_dir,
        graph_id=request.graph_id,
        lane_ids=[request.lane_id],
    )
    recovery_decision = recovery_decisions[-1] if recovery_decisions else None
    candidate_refs = _dedupe_text(
        [*request.worker_candidate_refs, *request.execution_artifact_refs]
    )
    manual_gaps: list[str] = []
    if not candidate_refs:
        manual_gaps.append("worker_candidate_evidence_missing")
    if recovery_decision is None:
        manual_gaps.append("lane_recovery_decision_missing")
    source_authority = (
        "lane_dag_artifact+lane_recovery_artifact"
        if recovery_decision is not None
        else "lane_dag_artifact"
    )
    reviewer_input_refs = _dedupe_text(
        [
            f"lane_dag:{request.graph_id}",
            f"lane_contract:{request.lane_id}",
            plan.blueprint_ref,
            *plan.source_refs,
            *contract.source_refs,
            *candidate_refs,
            *(
                recovery_decision.source_refs
                if recovery_decision is not None
                else []
            ),
        ]
    )
    intake_payload: dict[str, object] = {
        "schema_version": "xmuse.god_room_lane_review_intake.v1",
        "source_authority": source_authority,
        "proof_level": "contract_proof",
        "review_truth_status": "pending_independent_review",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "blueprint_proof_level": plan.blueprint_proof_level,
        "reviewer_id": request.reviewer_id,
        "lane_contract": contract.model_dump(mode="json"),
        "worker_candidate_refs": list(request.worker_candidate_refs),
        "execution_artifact_refs": list(request.execution_artifact_refs),
        "candidate_truth_status": "candidate_only",
        "recovery_decision": (
            recovery_decision.model_dump(mode="json")
            if recovery_decision is not None
            else None
        ),
        "required_review_checks": _dedupe_text(
            [
                contract.review_profile,
                *contract.required_checks,
                "review_worker_candidate_against_lane_contract",
                "verify_no_worker_self_report_as_truth",
            ]
        ),
        "reviewer_input_refs": reviewer_input_refs,
        "manual_gaps": manual_gaps,
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "ready_to_merge",
            "pr_merged",
        ],
    }
    intake_path = _write_god_room_lane_review_intake_artifact(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
        payload=intake_payload,
    )
    return {
        "source_authority": source_authority,
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "review_intake": intake_payload,
        "artifacts": {
            "review_intake": str(intake_path.relative_to(base_dir)),
        },
    }


def _build_god_room_lane_review_verdict(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomLaneReviewVerdictRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    intake_path = _god_room_lane_review_intake_artifact_path(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
    )
    if not intake_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_review_intake_not_found",
                "message": "review verdict requires a GOD room lane review intake artifact",
            },
        )
    try:
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_intake_invalid",
                "message": str(exc),
            },
        ) from exc
    if not isinstance(intake, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_intake_invalid",
                "message": "review intake artifact must be an object",
            },
        )
    if (
        intake.get("conversation_id") != conversation_id
        or intake.get("graph_id") != request.graph_id
        or intake.get("lane_id") != request.lane_id
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_intake_mismatch",
                "message": "review intake artifact does not match request scope",
            },
        )
    reviewer_inputs = set(_string_list(intake.get("reviewer_input_refs")))
    cited_inputs = [ref for ref in request.evidence_refs if ref in reviewer_inputs]
    if not cited_inputs:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_missing_intake_evidence",
                "message": "review verdict evidence_refs must cite review intake inputs",
            },
        )
    if request.decision == "patch-forward" and not request.patch_instructions:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_missing_patch_instructions",
                "message": "patch-forward verdict requires patch_instructions",
            },
        )
    if request.decision == "terminate" and not request.terminate_reason:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_missing_terminate_reason",
                "message": "terminate verdict requires terminate_reason",
            },
        )
    verdict = ReviewVerdict(
        id=f"god_room_review_{uuid.uuid4().hex}",
        lane_id=request.lane_id,
        decision=ReviewDecision(request.decision),
        summary=request.summary,
        evidence_refs=[
            str(intake_path.relative_to(base_dir)),
            *request.evidence_refs,
        ],
        patch_instructions=request.patch_instructions,
        terminate_reason=request.terminate_reason,
    )
    verdict_payload: dict[str, object] = {
        "schema_version": "xmuse.god_room_lane_review_verdict.v1",
        "source_authority": "god_room_lane_review_intake_artifact",
        "proof_level": "contract_proof",
        "review_truth_status": "independent_review_artifact",
        "server_truth_status": "not_server_truth",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "reviewer_id": request.reviewer_id,
        "review_intake_artifact": str(intake_path.relative_to(base_dir)),
        "review_intake_source_authority": intake.get("source_authority"),
        "candidate_truth_status": intake.get("candidate_truth_status"),
        "review_verdict": verdict.model_dump(mode="json"),
        "required_follow_up": (
            "append_patch_forward_lane"
            if request.decision == "patch-forward"
            else "release_evidence_link"
        ),
        "manual_gaps": [
            "review_plane_store_not_updated",
            "lane_status_not_updated",
            "patch_forward_lane_dag_not_linked",
            "release_evidence_not_linked",
        ],
        "forbidden_claims": [
            "end_to_end_execution_review_closure",
            "ready_to_merge",
            "pr_merged",
            "github_review_truth",
        ],
    }
    verdict_path = _write_god_room_lane_review_verdict_artifact(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
        payload=verdict_payload,
    )
    return {
        "source_authority": "god_room_lane_review_intake_artifact",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "lane_id": request.lane_id,
        "review_verdict": verdict_payload,
        "artifacts": {
            "review_verdict": str(verdict_path.relative_to(base_dir)),
        },
    }


def _apply_god_room_lane_patch_forward(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomLanePatchForwardRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    plan = _load_lane_dag_plan(base_dir, request.graph_id)
    if str(plan.lane_graph.conversation_id) != conversation_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_patch_forward_conversation_mismatch",
                "message": "laneDAG artifact does not belong to the conversation",
            },
        )
    verdict_path = _god_room_lane_review_verdict_artifact_path(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
    )
    if not verdict_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_review_verdict_not_found",
                "message": "patch-forward requires a review verdict artifact",
            },
        )
    try:
        verdict_artifact = json.loads(verdict_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_invalid",
                "message": str(exc),
            },
        ) from exc
    if not isinstance(verdict_artifact, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_invalid",
                "message": "review verdict artifact must be an object",
            },
        )
    if (
        verdict_artifact.get("conversation_id") != conversation_id
        or verdict_artifact.get("graph_id") != request.graph_id
        or verdict_artifact.get("lane_id") != request.lane_id
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_mismatch",
                "message": "review verdict artifact does not match request scope",
            },
        )
    try:
        verdict = ReviewVerdict.model_validate(verdict_artifact.get("review_verdict"))
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_review_verdict_invalid",
                "message": str(exc),
            },
        ) from exc
    if verdict.decision is not ReviewDecision.PATCH_FORWARD:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_patch_forward_requires_patch_verdict",
                "message": "patch-forward laneDAG update requires patch-forward verdict",
            },
        )
    if not verdict.patch_instructions:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_patch_forward_missing_instructions",
                "message": "patch-forward verdict is missing patch instructions",
            },
        )
    patch_lane_id = request.patch_lane_id or (
        f"{request.lane_id}-patch-forward-{_artifact_path_id(verdict.id)[-8:]}"
    )
    evidence_refs = _dedupe_text(
        [
            str(verdict_path.relative_to(base_dir)),
            *verdict.evidence_refs,
        ]
    )
    try:
        patched_plan = BlueprintLaneDagService().append_patch_forward_lane(
            plan,
            failed_lane_id=request.lane_id,
            patch_lane_id=patch_lane_id,
            prompt=verdict.patch_instructions,
            acceptance_criteria=[
                f"Review verdict {verdict.id} patch-forward instructions are addressed.",
                "Patch-forward output receives independent review before release.",
            ],
            verdict_ref=f"god_room_review_verdict:{verdict.id}",
            evidence_refs=evidence_refs,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_patch_forward_invalid",
                "message": str(exc),
            },
        ) from exc
    artifacts = _write_lane_dag_artifacts(base_dir, patched_plan)
    patch_link = patched_plan.patch_forward_links[-1].model_dump(mode="json")
    patch_contract = next(
        contract
        for contract in patched_plan.lane_contracts
        if contract.lane_id == patch_lane_id
    )
    patch_forward_payload: dict[str, object] = {
        "schema_version": "xmuse.god_room_lane_patch_forward.v1",
        "source_authority": "god_room_lane_review_verdict_artifact+lane_dag_artifact",
        "proof_level": "contract_proof",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "failed_lane_id": request.lane_id,
        "patch_lane_id": patch_lane_id,
        "blueprint_proof_level": patched_plan.blueprint_proof_level,
        "review_verdict_artifact": str(verdict_path.relative_to(base_dir)),
        "patch_forward_link": patch_link,
        "patch_lane_contract": patch_contract.model_dump(mode="json"),
        "lane_dag_artifacts": artifacts,
        "manual_gaps": [
            "patch_lane_not_executed",
            "patch_lane_not_reviewed",
            "release_evidence_not_linked",
        ],
        "forbidden_claims": [
            "end_to_end_execution_review_closure",
            "ready_to_merge",
            "pr_merged",
            "github_review_truth",
        ],
    }
    patch_forward_path = _write_god_room_lane_patch_forward_artifact(
        base_dir,
        graph_id=request.graph_id,
        lane_id=request.lane_id,
        payload=patch_forward_payload,
    )
    return {
        "source_authority": "god_room_lane_review_verdict_artifact+lane_dag_artifact",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "failed_lane_id": request.lane_id,
        "patch_lane_id": patch_lane_id,
        "lane_dag": patched_plan.model_dump(mode="json"),
        "patch_forward": patch_forward_payload,
        "artifacts": {
            **artifacts,
            "patch_forward": str(patch_forward_path.relative_to(base_dir)),
        },
    }


def _build_god_room_memoryos_plan(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomMemoryPlanRequest,
) -> dict[str, object]:
    store = _store(base_dir)
    if not _conversation_exists(store, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    lane_dag = _load_lane_dag_plan(base_dir, request.graph_id)
    if str(lane_dag.lane_graph.conversation_id) != conversation_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_memoryos_plan_conversation_mismatch",
                "message": "laneDAG artifact does not belong to the conversation",
            },
        )
    try:
        resolution = store.get_resolution(lane_dag.lane_graph.resolution_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="resolution not found") from exc
    blueprint_freeze = _god_room_blueprint_freeze_artifact_from_resolution(resolution)
    event_store = _god_room_event_store(base_dir)
    room_id = _default_god_room_id(conversation_id)
    try:
        snapshot = event_store.load_room(room_id)
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "god_room_not_found", "message": str(exc)},
        ) from exc
    recovery_decisions = _load_lane_recovery_decisions(
        base_dir,
        graph_id=request.graph_id,
        lane_ids=[contract.lane_id for contract in lane_dag.lane_contracts],
    )
    try:
        artifact = build_god_room_memoryos_plan(
            repo_id=request.repo_id,
            workspace_id=request.workspace_id,
            participants=snapshot.participants,
            events=snapshot.events,
            blueprint_freeze=blueprint_freeze,
            lane_dag=lane_dag,
            recovery_decisions=recovery_decisions,
            context_budget=request.context_budget,
            live_memoryos_configured=live_memoryos_lite_enabled(os.environ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_memoryos_plan_invalid",
                "message": str(exc),
                "source_authority": "god_room_memoryos_plan_contract",
            },
        ) from exc
    artifact_path = _write_god_room_memoryos_plan_artifact(
        base_dir,
        graph_id=request.graph_id,
        payload=artifact.model_dump(mode="json"),
    )
    return {
        "source_authority": "god_room_memoryos_plan_contract",
        "conversation_id": conversation_id,
        "graph_id": request.graph_id,
        "memoryos_plan": artifact.model_dump(mode="json"),
        "artifacts": {"memoryos_plan": str(artifact_path.relative_to(base_dir))},
    }


def _build_god_room_speaker_attempt_from_runtime(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomSpeakerAttemptRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    event_store = _god_room_event_store(base_dir)
    room_id = _default_god_room_id(conversation_id)
    try:
        snapshot = event_store.load_room(room_id)
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "god_room_not_found", "message": str(exc)},
        ) from exc
    god_cli_registry = build_default_god_cli_registry(
        extra_registrations=_god_cli_registration_store(base_dir).list_registrations()
    )
    runtime_continuity = build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=_god_cli_selection_store(base_dir).list_records(),
        sessions=_god_session_registry(base_dir).list(),
        god_cli_registry=god_cli_registry,
    )
    attempt = build_god_room_speaker_attempt(
        conversation_id=conversation_id,
        room_id=room_id,
        participants=snapshot.participants,
        events=snapshot.events,
        runtime_continuity=runtime_continuity,
        after_event_id=request.after_event_id,
        selected_binding_resolver=_selected_god_binding_resolver(base_dir, room_id),
    )
    attempt_payload = attempt.model_dump(mode="json")
    artifact_path = _write_god_room_speaker_attempt_artifact(
        base_dir,
        conversation_id=conversation_id,
        after_event_id=request.after_event_id,
        payload=attempt_payload,
    )
    return {
        "source_authority": attempt.source_authority,
        "conversation_id": conversation_id,
        "room_id": room_id,
        "speaker_attempt": attempt_payload,
        "runtime_continuity": runtime_continuity,
        "artifacts": {"speaker_attempt": str(artifact_path.relative_to(base_dir))},
    }


def _invoke_god_room_provider_speech_from_runtime(
    base_dir: Path,
    *,
    execution_worktree: Path,
    conversation_id: str,
    request: GodRoomProviderInvocationRequest,
) -> dict[str, object]:
    invocation = _build_god_room_provider_invocation_artifact(
        base_dir,
        execution_worktree=execution_worktree,
        conversation_id=conversation_id,
        request=request,
    )
    return {
        "source_authority": (
            "god_room_event_store+room_selected_god_binding+provider_invocation"
        ),
        "conversation_id": conversation_id,
        "room_id": invocation["room_id"],
        "speaker_attempt": invocation["speaker_attempt"],
        "provider_response": invocation["provider_response"],
        "runtime_continuity": invocation["runtime_continuity"],
        "artifacts": {
            "provider_response": invocation["provider_response_artifact_ref"],
        },
    }


def _invoke_and_capture_god_room_provider_speech_from_runtime(
    base_dir: Path,
    *,
    execution_worktree: Path,
    conversation_id: str,
    request: GodRoomProviderInvocationCaptureRequest,
) -> dict[str, object]:
    invocation = _build_god_room_provider_invocation_artifact(
        base_dir,
        execution_worktree=execution_worktree,
        conversation_id=conversation_id,
        request=request,
    )
    event_store = invocation["event_store"]
    snapshot = invocation["snapshot"]
    room_id = invocation["room_id"]
    provider_response = invocation["provider_response_model"]
    provider_response_artifact_ref = invocation["provider_response_artifact_ref"]
    runtime_continuity = _refresh_runtime_continuity_after_provider_invocation(
        base_dir,
        conversation_id=conversation_id,
        provider_response=provider_response,
        fallback=invocation["runtime_continuity"],
    )

    def append_event(event: GodRoomEventV1) -> Literal["created", "duplicate"]:
        return event_store.append_event(event).status

    try:
        capture = capture_god_room_speaker_response(
            conversation_id=conversation_id,
            room_id=room_id,
            participants=snapshot.participants,
            events=snapshot.events,
            runtime_continuity=runtime_continuity,
            provider_response=provider_response,
            provider_response_artifact_ref=provider_response_artifact_ref,
            after_event_id=request.after_event_id,
            event_id=request.event_id,
            selected_binding_resolver=_selected_god_binding_resolver(base_dir, room_id),
            timestamp_utc=request.timestamp_utc or _utc_now(),
            append_event=append_event,
        )
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "god_room_membership_error", "message": str(exc)},
        ) from exc
    except GodRoomEventConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "god_room_event_conflict", "message": str(exc)},
        ) from exc

    capture_payload = capture.model_dump(mode="json")
    capture_path = _write_god_room_speaker_response_artifact(
        base_dir,
        conversation_id=conversation_id,
        after_event_id=request.after_event_id,
        event_id=request.event_id,
        payload=capture_payload,
    )
    return {
        "source_authority": (
            "god_room_event_store+room_selected_god_binding+provider_invocation"
            "+provider_response_capture"
        ),
        "conversation_id": conversation_id,
        "room_id": room_id,
        "speaker_attempt": invocation["speaker_attempt"],
        "provider_response": invocation["provider_response"],
        "speaker_response": capture_payload,
        "runtime_continuity": runtime_continuity,
        "artifacts": {
            "provider_response": provider_response_artifact_ref,
            "speaker_response": str(capture_path.relative_to(base_dir)),
        },
        "room": _god_room_payload(event_store, room_id),
    }


def _build_god_room_provider_invocation_artifact(
    base_dir: Path,
    *,
    execution_worktree: Path,
    conversation_id: str,
    request: GodRoomProviderInvocationRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    event_store = _god_room_event_store(base_dir)
    room_id = _default_god_room_id(conversation_id)
    try:
        snapshot = event_store.load_room(room_id)
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "god_room_not_found", "message": str(exc)},
        ) from exc
    god_cli_registry = build_default_god_cli_registry(
        extra_registrations=_god_cli_registration_store(base_dir).list_registrations()
    )
    runtime_continuity = build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=_god_cli_selection_store(base_dir).list_records(),
        sessions=_god_session_registry(base_dir).list(),
        god_cli_registry=god_cli_registry,
    )
    attempt = build_god_room_speaker_attempt(
        conversation_id=conversation_id,
        room_id=room_id,
        participants=snapshot.participants,
        events=snapshot.events,
        runtime_continuity=runtime_continuity,
        after_event_id=request.after_event_id,
        selected_binding_resolver=_selected_god_binding_resolver(base_dir, room_id),
    )
    prompt = request.prompt or _build_god_room_provider_speech_prompt(
        conversation_id=conversation_id,
        room_id=room_id,
        events=snapshot.events,
        attempt=attempt,
    )
    prompt_ref = (
        f"god-room-provider-prompt:"
        f"{conversation_id}:{attempt.selected_event_id or 'latest'}"
    )
    provider_response = invoke_god_room_provider_speech(
        attempt=attempt,
        prompt=prompt,
        workspace=execution_worktree,
        timeout_seconds=request.timeout_seconds,
        prompt_refs=[prompt_ref],
        allow_live_provider_proof=request.allow_live_provider_proof,
    )
    response_payload = provider_response.model_dump(mode="json")
    artifact_path = _write_god_room_provider_response_artifact(
        base_dir,
        conversation_id=conversation_id,
        after_event_id=request.after_event_id,
        response_id=provider_response.response_id,
        payload=response_payload,
    )
    return {
        "room_id": room_id,
        "event_store": event_store,
        "snapshot": snapshot,
        "speaker_attempt": attempt.model_dump(mode="json"),
        "speaker_attempt_model": attempt,
        "provider_response": response_payload,
        "provider_response_model": provider_response,
        "provider_response_artifact_ref": str(artifact_path.relative_to(base_dir)),
        "runtime_continuity": runtime_continuity,
    }


def _refresh_runtime_continuity_after_provider_invocation(
    base_dir: Path,
    *,
    conversation_id: str,
    provider_response: GodRoomProviderSpeechResponseV1,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if (
        provider_response.status != "completed"
        or provider_response.proof_level != "real_provider_proof"
        or not provider_response.target_participant_id
        or not provider_response.provider_session_id
    ):
        return fallback
    registry = _god_session_registry(base_dir)
    try:
        session = registry.find_by_conversation_participant(
            conversation_id,
            provider_response.target_participant_id,
        )
    except KeyError:
        return fallback
    registry.update_provider_binding(
        session.god_session_id,
        provider_session_id=provider_response.provider_session_id,
        provider_session_kind=(
            provider_response.provider_session_kind
            or session.provider_session_kind
            or "provider_invocation"
        ),
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    god_cli_registry = build_default_god_cli_registry(
        extra_registrations=_god_cli_registration_store(base_dir).list_registrations()
    )
    return build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=_god_cli_selection_store(base_dir).list_records(),
        sessions=registry.list(),
        god_cli_registry=god_cli_registry,
    )


def _capture_god_room_speaker_response_from_runtime(
    base_dir: Path,
    *,
    conversation_id: str,
    request: GodRoomSpeakerResponseRequest,
) -> dict[str, object]:
    if not _conversation_exists(_store(base_dir), conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    event_store = _god_room_event_store(base_dir)
    room_id = _default_god_room_id(conversation_id)
    try:
        snapshot = event_store.load_room(room_id)
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "god_room_not_found", "message": str(exc)},
        ) from exc
    god_cli_registry = build_default_god_cli_registry(
        extra_registrations=_god_cli_registration_store(base_dir).list_registrations()
    )
    runtime_continuity = build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=_god_cli_selection_store(base_dir).list_records(),
        sessions=_god_session_registry(base_dir).list(),
        god_cli_registry=god_cli_registry,
    )
    provider_response, provider_response_artifact_ref = (
        _load_god_room_provider_response_artifact(base_dir, request)
    )

    def append_event(event: GodRoomEventV1) -> Literal["created", "duplicate"]:
        return event_store.append_event(event).status

    try:
        capture = capture_god_room_speaker_response(
            conversation_id=conversation_id,
            room_id=room_id,
            participants=snapshot.participants,
            events=snapshot.events,
            runtime_continuity=runtime_continuity,
            provider_response=provider_response,
            provider_response_artifact_ref=provider_response_artifact_ref,
            after_event_id=request.after_event_id,
            event_id=request.event_id,
            selected_binding_resolver=_selected_god_binding_resolver(base_dir, room_id),
            timestamp_utc=request.timestamp_utc or _utc_now(),
            append_event=append_event,
        )
    except GodRoomMembershipError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "god_room_membership_error", "message": str(exc)},
        ) from exc
    except GodRoomEventConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "god_room_event_conflict", "message": str(exc)},
        ) from exc

    capture_payload = capture.model_dump(mode="json")
    artifact_path = _write_god_room_speaker_response_artifact(
        base_dir,
        conversation_id=conversation_id,
        after_event_id=request.after_event_id,
        event_id=request.event_id,
        payload=capture_payload,
    )
    return {
        "source_authority": capture.source_authority,
        "conversation_id": conversation_id,
        "room_id": room_id,
        "speaker_response": capture_payload,
        "runtime_continuity": runtime_continuity,
        "artifacts": {"speaker_response": str(artifact_path.relative_to(base_dir))},
        "room": _god_room_payload(event_store, room_id),
    }


def _build_god_room_provider_speech_prompt(
    *,
    conversation_id: str,
    room_id: str,
    events: list[GodRoomEventV1],
    attempt,
) -> str:
    recent_events = sorted(events, key=lambda item: (item.timestamp_utc, item.event_id))[-8:]
    transcript = "\n".join(
        f"- {event.god_id}/{event.event_type.value}: {event.content}"
        for event in recent_events
    )
    target = attempt.target_god_id or attempt.target_participant_id or "selected GOD"
    return (
        "You are the selected GOD speaker in an xmuse GOD room.\n"
        f"conversation_id: {conversation_id}\n"
        f"room_id: {room_id}\n"
        f"target: {target}\n"
        "Return a JSON object with at least a non-empty string field named "
        "`content`. Optional fields: response_id, provider_session_id, "
        "provider_session_kind, source_refs, output_refs.\n"
        "Recent durable room transcript:\n"
        f"{transcript or '- no prior events'}\n"
    )


def _load_god_room_provider_response_artifact(
    base_dir: Path,
    request: GodRoomSpeakerResponseRequest,
) -> tuple[GodRoomProviderSpeechResponseV1 | None, str | None]:
    artifact_ref = request.provider_response_artifact
    if artifact_ref is None:
        return request.provider_response, None
    artifact_path = _resolve_runtime_artifact_path(base_dir, artifact_ref)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "provider_response_artifact_missing",
                "message": f"provider response artifact does not exist: {artifact_ref}",
            },
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "provider_response_artifact_invalid_json",
                "message": f"provider response artifact is not valid JSON: {exc}",
            },
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "provider_response_artifact_unreadable",
                "message": str(exc),
            },
        ) from exc
    try:
        provider_response = GodRoomProviderSpeechResponseV1.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "provider_response_artifact_invalid",
                "message": str(exc),
            },
        ) from exc
    if (
        request.provider_response is not None
        and request.provider_response.model_dump(mode="json")
        != provider_response.model_dump(mode="json")
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "provider_response_artifact_mismatch",
                "message": "provider_response must match provider_response_artifact",
            },
        )
    return provider_response, str(artifact_path.relative_to(base_dir.resolve()))


def _resolve_runtime_artifact_path(base_dir: Path, artifact_ref: str) -> Path:
    root = base_dir.resolve()
    path = Path(artifact_ref)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "runtime_artifact_outside_root",
                "message": "artifact path must stay under xmuse root",
            },
        ) from exc
    return resolved


def _load_lane_dag_plan(base_dir: Path, graph_id: str) -> BlueprintLaneDagPlan:
    try:
        path = _lane_dag_artifact_path(base_dir, graph_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_dag_not_found",
                "message": f"laneDAG artifact not found: {graph_id}",
            },
        ) from exc
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "god_room_lane_dag_not_found",
                "message": f"laneDAG artifact not found: {graph_id}",
            },
        )
    try:
        return BlueprintLaneDagPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_invalid_artifact",
                "message": str(exc),
            },
        ) from exc


def _god_room_blueprint_freeze_artifact_from_resolution(
    resolution: object,
) -> GodRoomBlueprintFreezeArtifactV1:
    approval_mode = str(getattr(resolution, "approval_mode", "") or "")
    content = getattr(resolution, "content", None)
    if approval_mode != "god_room_blueprint_freeze" or not isinstance(content, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_memoryos_plan_requires_god_room_freeze",
                "message": "MemoryOS planning requires a GOD room blueprint freeze resolution",
            },
        )
    freeze_artifact = content.get("god_room_blueprint_freeze")
    if not isinstance(freeze_artifact, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_memoryos_plan_missing_freeze",
                "message": "GOD room freeze artifact is missing",
            },
        )
    try:
        return GodRoomBlueprintFreezeArtifactV1.model_validate(freeze_artifact)
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_memoryos_plan_invalid_freeze",
                "message": str(exc),
            },
        ) from exc


def _load_lane_recovery_decisions(
    base_dir: Path,
    *,
    graph_id: str,
    lane_ids: list[str],
) -> list[LaneRecoveryDecision]:
    decisions: list[LaneRecoveryDecision] = []
    for lane_id in lane_ids:
        path = _lane_recovery_artifact_path(base_dir, graph_id=graph_id, lane_id=lane_id)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("decision"), dict):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "god_room_lane_recovery_invalid_artifact",
                    "message": f"lane recovery artifact is invalid: {path.name}",
                },
            )
        try:
            decisions.append(LaneRecoveryDecision.model_validate(payload["decision"]))
        except ValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "god_room_lane_recovery_invalid_artifact",
                    "message": str(exc),
                },
            ) from exc
    return decisions


def _god_room_blueprint_freeze_artifact_for_lane_dag(
    resolution: object,
) -> GodRoomBlueprintFreezeArtifactV1:
    approval_mode = str(getattr(resolution, "approval_mode", "") or "")
    content = getattr(resolution, "content", None)
    if approval_mode != "god_room_blueprint_freeze" or not isinstance(content, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_requires_god_room_freeze",
                "message": "laneDAG planning requires a GOD room blueprint freeze resolution",
            },
        )
    freeze_artifact = content.get("god_room_blueprint_freeze")
    if (
        not isinstance(freeze_artifact, dict)
        or freeze_artifact.get("status") != "frozen"
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_requires_frozen_blueprint",
                "message": "GOD room blueprint freeze artifact is missing or not frozen",
            },
        )
    try:
        artifact = GodRoomBlueprintFreezeArtifactV1.model_validate(freeze_artifact)
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_invalid_freeze",
                "message": str(exc),
            },
        ) from exc
    if artifact.blueprint is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "god_room_lane_dag_missing_blueprint",
                "message": "GOD room freeze artifact does not carry blueprint",
            },
        )
    return artifact


def _write_lane_dag_artifacts(
    base_dir: Path,
    plan: BlueprintLaneDagPlan,
) -> dict[str, str]:
    lane_graph = plan.lane_graph
    lane_dag_path = _lane_dag_artifact_path(base_dir, lane_graph.id)
    graph_path = LaneGraphStore(base_dir / "lane_graphs").save(lane_graph)
    lane_dag_path.parent.mkdir(parents=True, exist_ok=True)
    lane_dag_path.write_text(
        json.dumps(
            plan.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "lane_graph": str(graph_path.relative_to(base_dir)),
        "lane_dag": str(lane_dag_path.relative_to(base_dir)),
    }


def _write_lane_recovery_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    payload: dict[str, object],
) -> Path:
    path = _lane_recovery_artifact_path(base_dir, graph_id=graph_id, lane_id=lane_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_lane_review_intake_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    payload: dict[str, object],
) -> Path:
    path = _god_room_lane_review_intake_artifact_path(
        base_dir,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _god_room_lane_review_intake_artifact_path(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
) -> Path:
    return (
        base_dir
        / "reports"
        / "god_room_review_intake"
        / (
            f"{_artifact_path_id(graph_id)}."
            f"{_artifact_path_id(lane_id)}.review-intake.json"
        )
    )


def _write_god_room_lane_review_verdict_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    payload: dict[str, object],
) -> Path:
    path = _god_room_lane_review_verdict_artifact_path(
        base_dir,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _god_room_lane_review_verdict_artifact_path(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
) -> Path:
    return (
        base_dir
        / "reports"
        / "god_room_review_verdicts"
        / (
            f"{_artifact_path_id(graph_id)}."
            f"{_artifact_path_id(lane_id)}.review-verdict.json"
        )
    )


def _write_god_room_lane_patch_forward_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    payload: dict[str, object],
) -> Path:
    path = (
        base_dir
        / "reports"
        / "god_room_patch_forward"
        / (
            f"{_artifact_path_id(graph_id)}."
            f"{_artifact_path_id(lane_id)}.patch-forward.json"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_memoryos_plan_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    payload: dict[str, object],
) -> Path:
    path = (
        base_dir
        / "reports"
        / "god_room_memoryos"
        / f"{_artifact_path_id(graph_id)}.memoryos-plan.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_speaker_attempt_artifact(
    base_dir: Path,
    *,
    conversation_id: str,
    after_event_id: str | None,
    payload: dict[str, object],
) -> Path:
    event_id = after_event_id or "latest"
    path = (
        base_dir
        / "reports"
        / "god_room_speaker_attempts"
        / (
            f"{_artifact_safe_id(conversation_id)}."
            f"{_artifact_safe_id(event_id)}.speaker-attempt.json"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_speaker_response_artifact(
    base_dir: Path,
    *,
    conversation_id: str,
    after_event_id: str | None,
    event_id: str | None,
    payload: dict[str, object],
) -> Path:
    replay_event_id = after_event_id or "latest"
    response_event_id = event_id or "generated"
    path = (
        base_dir
        / "reports"
        / "god_room_speaker_responses"
        / (
            f"{_artifact_safe_id(conversation_id)}."
            f"{_artifact_safe_id(replay_event_id)}."
            f"{_artifact_safe_id(response_event_id)}.speaker-response.json"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_provider_response_artifact(
    base_dir: Path,
    *,
    conversation_id: str,
    after_event_id: str | None,
    response_id: str,
    payload: dict[str, object],
) -> Path:
    replay_event_id = after_event_id or "latest"
    path = (
        base_dir
        / "reports"
        / "provider-responses"
        / (
            f"{_artifact_safe_id(conversation_id)}."
            f"{_artifact_safe_id(replay_event_id)}."
            f"{_artifact_safe_id(response_id)}.json"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _lane_dag_artifact_path(base_dir: Path, graph_id: str) -> Path:
    return base_dir / "lane_graphs" / f"{_artifact_path_id(graph_id)}.lane-dag.json"


def _lane_recovery_artifact_path(base_dir: Path, *, graph_id: str, lane_id: str) -> Path:
    return (
        base_dir
        / "lane_graphs"
        / f"{_artifact_path_id(graph_id)}.{_artifact_path_id(lane_id)}.recovery.json"
    )


def _artifact_path_id(value: str) -> str:
    safe_id = _artifact_safe_id(value)
    if not value.strip() or safe_id != value or value in {".", ".."}:
        raise ValueError(f"unsafe artifact id: {value}")
    return safe_id


def _artifact_safe_id(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_participant_inits(role_templates: RoleTemplateStore) -> list[ParticipantInit]:
    defaults: list[ParticipantInit] = []
    for role in ("architect", "review", "execute"):
        template = role_templates.get_by_slug(role)
        if template is None:
            raise HTTPException(status_code=500, detail=f"missing predefined role template: {role}")
        defaults.append(
            ParticipantInit(
                role=role,
                cli_kind=template.cli_kind,
                model=template.default_model,
                role_template_id=template.id,
                display_name=f"{role}-god",
            )
        )
    return defaults


def _template_for_participant(
    role_templates: RoleTemplateStore,
    participant: ParticipantInit,
) -> RoleTemplate:
    if participant.role_template_id is not None:
        try:
            return role_templates.get(participant.role_template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="role template not found") from exc

    template = role_templates.get_by_slug(participant.role)
    if template is None or not template.predefined:
        raise HTTPException(
            status_code=400,
            detail="role_template_id is required for custom participants",
        )
    return template


def _add_participants(
    *,
    base_dir: Path,
    conversation_id: str,
    participants: list[ParticipantInit],
) -> list[dict[str, object]]:
    participant_store = _participant_store(base_dir)
    role_templates = _role_template_store(base_dir)
    created = []
    for participant in participants:
        template = _template_for_participant(role_templates, participant)
        try:
            cli_kind = resolve_codex_cli_kind(
                cli_kind=participant.cli_kind,
                provider_id=participant.provider_id,
                profile_id=participant.profile_id,
                expected_profile_id=template.profile_id,
                subject="xmuse chat participants",
            )
            created_participant = participant_store.add(
                conversation_id=conversation_id,
                role=participant.role.strip(),
                display_name=(participant.display_name or f"{participant.role}-god").strip(),
                cli_kind=cli_kind,
                model=(participant.model or template.default_model).strip(),
                role_template_id=template.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        payload = created_participant.model_dump(mode="json")
        payload["session"] = None
        created.append(payload)
    return created


def _append_resolution_read_model(base_dir: Path, resolution_payload: dict[str, object]) -> None:
    read_models_dir = base_dir / "read_models"
    path = read_models_dir / "resolutions.json"
    data: dict[str, list[dict[str, object]]]
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {"resolutions": []}
    else:
        data = {"resolutions": []}

    resolutions = data.get("resolutions", [])
    if not isinstance(resolutions, list):
        resolutions = []

    entry = {
        "resolution_id": resolution_payload["id"],
        "conversation_id": resolution_payload["conversation_id"],
        "version": resolution_payload["version"],
        "status": resolution_payload["status"],
        "goal_summary": resolution_payload["goal_summary"],
        "approved_by": resolution_payload["approved_by"],
        "approval_mode": resolution_payload["approval_mode"],
    }
    data["resolutions"] = [
        item for item in resolutions
        if isinstance(item, dict) and item.get("resolution_id") != entry["resolution_id"]
    ]
    data["resolutions"].append(entry)
    read_models_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _extract_mission_blueprint_ref(payload: dict[str, Any], references: list[str]) -> str:
    value = payload.get("source_blueprint_ref")
    if isinstance(value, str) and value.strip():
        return value.strip()
    for reference in references:
        if _is_mission_blueprint_ref(reference):
            return reference
    raise PeerChatError(
        "invalid_feature_plan_proposal",
        "feature plan proposals require an approved source blueprint ref",
    )


def _is_mission_blueprint_ref(value: str) -> bool:
    return value.startswith("resolution:") and value.endswith(":mission_blueprint")


def _resolution_id_from_blueprint_ref(blueprint_ref: str) -> str:
    if not _is_mission_blueprint_ref(blueprint_ref):
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            f"invalid mission blueprint ref: {blueprint_ref}",
        )
    resolution_id = blueprint_ref.removeprefix("resolution:").removesuffix(":mission_blueprint")
    if not resolution_id:
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            f"invalid mission blueprint ref: {blueprint_ref}",
        )
    return resolution_id


def _build_feature_plan_proposal_record(
    base_dir: Path,
    *,
    proposal: Any,
    content: dict[str, Any] | None,
) -> Any:
    payload = content
    if payload is None:
        try:
            payload = json.loads(proposal.content)
        except json.JSONDecodeError as exc:
            raise PeerChatError(
                "invalid_feature_plan_proposal",
                "feature plan proposal content must be valid JSON",
            ) from exc
    if not isinstance(payload, dict):
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            "feature plan proposal content must be an object",
        )
    if "lanes" in payload:
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            "feature plan proposals reject ad hoc flat lane writes",
        )

    blueprint_ref = _extract_mission_blueprint_ref(payload, proposal.references)
    try:
        resolution_id = _resolution_id_from_blueprint_ref(blueprint_ref)
        source_resolution = _store(base_dir).get_resolution(resolution_id)
        blueprint = read_approved_mission_blueprint(source_resolution)
        features = [
            FeaturePlanFeature.model_validate(item)
            for item in payload.get("features", [])
        ]
    except KeyError as exc:
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            f"unknown approved mission blueprint: {blueprint_ref}",
        ) from exc
    except ValidationError as exc:
        raise PeerChatError("invalid_feature_plan_proposal", str(exc)) from exc

    if not features:
        raise PeerChatError(
            "invalid_feature_plan_proposal",
            "feature plan proposals require at least one feature",
        )

    try:
        return build_feature_plan_proposal(
            proposal_id=proposal.id,
            conversation_id=proposal.conversation_id,
            source_blueprint=blueprint,
            features=features,
        )
    except ValidationError as exc:
        raise PeerChatError("invalid_feature_plan_proposal", str(exc)) from exc


def _feature_plan_resolution_content(proposal_record: Any) -> dict[str, Any]:
    return {
        "type": "feature_plan",
        "proposal_id": proposal_record.id,
        "source_blueprint_ref": proposal_record.source_blueprint.blueprint_ref,
        "feature_ids": [feature.feature_id for feature in proposal_record.features],
        "graph_ids": [feature.graph_id for feature in proposal_record.features],
    }


def _authoritative_blueprint_ref(store: ChatStore, conversation_id: str, source_ref: str) -> str:
    resolutions = [
        resolution
        for resolution in store.list_resolutions(conversation_id)
        if resolution.content.get("type") == "mission_blueprint"
    ]
    by_ref = {
        str(resolution.content.get("blueprint_ref") or ""): resolution
        for resolution in resolutions
        if isinstance(resolution.content.get("blueprint_ref"), str)
        and str(resolution.content.get("blueprint_ref")).strip()
    }
    current = by_ref.get(source_ref)
    if current is None:
        raise PeerChatError(
            "stale_feature_plan_blueprint",
            f"unknown mission blueprint source: {source_ref}",
        )
    newest_ref = source_ref
    while True:
        next_resolution = next(
            (
                resolution
                for resolution in resolutions
                if resolution.status.value == "approved"
                and resolution.content.get("revision_of") == newest_ref
            ),
            None,
        )
        if next_resolution is None:
            break
        newest_ref = str(next_resolution.content.get("blueprint_ref") or newest_ref)
    return newest_ref


def _require_current_feature_plan_blueprint(
    store: ChatStore,
    *,
    conversation_id: str,
    proposal_payload: dict[str, Any],
    references: list[str],
) -> str:
    source_ref = _extract_mission_blueprint_ref(proposal_payload, references)
    current_ref = _authoritative_blueprint_ref(store, conversation_id, source_ref)
    if current_ref != source_ref:
        raise PeerChatError(
            "stale_feature_plan_blueprint",
            (
                "feature plan must reference latest approved blueprint "
                f"{current_ref}, not stale {source_ref}"
            ),
        )
    return source_ref


def _project_resolution_into_execution_queue(
    base_dir: Path,
    resolution: object,
    *,
    execution_worktree: Path,
) -> None:
    content = getattr(resolution, "content", None)
    if isinstance(content, dict) and content.get("type") in {"mission_blueprint", "feature_plan"}:
        return
    graph = build_lane_graph(resolution)
    LaneGraphStore(base_dir / "lane_graphs").save(graph)
    project_ready_lanes(
        graph,
        base_dir / "feature_lanes.json",
        operational_metadata={"worktree": str(execution_worktree)},
    )


def _enqueue_structured_dispatch_intent(
    base_dir: Path,
    *,
    proposal_id: str,
    proposal_type: str,
    references: list[str],
    resolution: object,
) -> None:
    content = getattr(resolution, "content", None)
    if isinstance(content, dict) and content.get("type") in {"mission_blueprint", "feature_plan"}:
        return
    conversation_id = str(resolution.conversation_id)
    resolution_id = str(resolution.id)
    collaboration_run_ids = _collaboration_run_refs(references)
    if not collaboration_run_ids:
        return
    _dispatch_queue_store(base_dir).enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal_id,
        resolution_id=resolution_id,
        collaboration_run_id=collaboration_run_ids[0] if collaboration_run_ids else None,
        artifact_ref=f"artifact:{proposal_type}",
    )


def _chat_timeline_payload(base_dir: Path, conversation_id: str) -> dict[str, Any]:
    payload = _peer_service(base_dir).list_conversation_timeline(conversation_id)
    payload = _with_execution_card_drilldown_refs(base_dir, payload)
    return _with_compact_health_cards(base_dir, conversation_id, payload)


def _with_execution_card_drilldown_refs(
    base_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    cards = payload.get("cards")
    if isinstance(cards, list):
        payload["cards"] = [_enrich_execution_card(base_dir, card) for card in cards]
    recent_cards = payload.get("recent_cards")
    if isinstance(recent_cards, list):
        payload["recent_cards"] = [
            _enrich_execution_card(base_dir, card) for card in recent_cards
        ]
    items = payload.get("items")
    if isinstance(items, list):
        payload["items"] = [_enrich_timeline_execution_card(base_dir, item) for item in items]
    return payload


def _enrich_timeline_execution_card(base_dir: Path, item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    card = item.get("card")
    if not isinstance(card, dict):
        return item
    return {**item, "card": _enrich_execution_card(base_dir, card)}


def _enrich_execution_card(base_dir: Path, card: Any) -> Any:
    if not isinstance(card, dict):
        return card
    if str(card.get("card_type") or "") not in _EXECUTION_CARD_TYPES:
        return card
    metadata = card.get("metadata")
    if not isinstance(metadata, dict):
        return card
    planning_run_id = metadata.get("planning_run_id")
    payload = metadata.get("payload")
    conversation_id = card.get("conversation_id")
    if not isinstance(planning_run_id, str) or not isinstance(conversation_id, str):
        return card
    refs = build_execution_drilldown_refs(
        conversation_id=conversation_id,
        planning_run_id=planning_run_id,
        payload=payload if isinstance(payload, dict) else {},
        xmuse_root=base_dir,
        existing_refs=(
            metadata["drilldown_refs"]
            if isinstance(metadata.get("drilldown_refs"), list)
            else None
        ),
    )
    return {
        **card,
        "metadata": {
            **metadata,
            "drilldown_refs": refs,
        },
    }


def _with_compact_health_cards(
    base_dir: Path,
    conversation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    health_card = _compact_health_card_for_payload(base_dir, conversation_id, payload)
    if health_card is None:
        return payload

    payload["cards"] = [_replace_health_card(card, health_card) for card in payload["cards"]]
    if isinstance(payload.get("recent_cards"), list):
        payload["recent_cards"] = [
            _replace_health_card(card, health_card) for card in payload["recent_cards"]
        ]
        payload["card_counts"] = _card_counts(payload["cards"])
    payload["items"] = [
        _replace_timeline_health_card(item, health_card) for item in payload["items"]
    ]
    return payload


def _compact_health_card_for_payload(
    base_dir: Path,
    conversation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return None

    existing = next(
        (
            card
            for card in cards
            if isinstance(card, dict) and card.get("card_type") == "health_summary"
        ),
        None,
    )
    if existing is None:
        return None

    lanes = _conversation_scoped_lanes(base_dir, conversation_id)
    run_health = summarize_run_health(lanes, xmuse_root=base_dir)
    card = build_run_health_chat_card(
        conversation_id,
        run_health,
        created_at=str(existing.get("created_at") or _latest_health_timestamp(base_dir)),
        href=f"/dashboard/peer-chat/conversations/{conversation_id}#run-health",
        api_href=f"/api/dashboard/peer-chat/conversations/{conversation_id}/run-health",
    )
    return card.model_dump(mode="json")


def _conversation_scoped_lanes(base_dir: Path, conversation_id: str) -> list[dict[str, Any]]:
    lane_data = _read_json_file(base_dir / "feature_lanes.json", {"lanes": []})
    lanes = []
    if isinstance(lane_data, dict) and isinstance(lane_data.get("lanes"), list):
        lanes = [lane for lane in lane_data["lanes"] if isinstance(lane, dict)]
    return _peer_service(base_dir)._conversation_scoped_lanes(conversation_id, lanes)


def _replace_health_card(card: Any, health_card: dict[str, Any]) -> Any:
    if isinstance(card, dict) and card.get("card_type") == "health_summary":
        return health_card
    return card


def _replace_timeline_health_card(item: Any, health_card: dict[str, Any]) -> Any:
    if not isinstance(item, dict):
        return item
    card = item.get("card")
    if isinstance(card, dict) and card.get("card_type") == "health_summary":
        return {**item, "card": health_card}
    return item


def _card_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        card_type = str(card.get("card_type") or "unknown")
        counts[card_type] = counts.get(card_type, 0) + 1
    counts["total"] = len(cards)
    return counts


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _latest_health_timestamp(base_dir: Path) -> str:
    candidates = [
        base_dir / "feature_lanes.json",
        base_dir / "active_sessions.json",
        base_dir / "error_knowledge.json",
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return "1970-01-01T00:00:00Z"
    path = max(existing, key=lambda item: item.stat().st_mtime)
    from datetime import UTC, datetime

    return (
        datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_app(
    base_dir: Path | str = DEFAULT_BASE_DIR,
    *,
    execution_worktree: Path | str | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    root = Path(base_dir)
    execution_root = Path(execution_worktree) if execution_worktree is not None else REPO_ROOT
    resolved_auth_token = require_production_write_auth_token(
        service_name="xmuse Chat API",
        auth_token=auth_token or _auth_token_from_env(),
        env_names=("XMUSE_CHAT_API_AUTH_TOKEN", "XMUSE_CHAT_API_KEY"),
    )
    app = FastAPI(title="xmuse Chat API", version="0.1.0")
    app.state.auth_token = resolved_auth_token
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_write_auth(request: Request, call_next):
        mutating = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if (
            resolved_auth_token
            and mutating
            and request.headers.get("X-XMUSE-API-Key") != resolved_auth_token
        ):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "authentication required"},
            )
        if resolved_auth_token and mutating:
            decision = authorize_chat_api_write(
                method=request.method,
                path=request.url.path,
                role=_operator_role(request),
                capabilities=_operator_capabilities(request),
            )
            if not decision.allowed:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "detail": {
                            "code": decision.code,
                            "message": decision.message,
                            "required_capability": decision.required_capability,
                        }
                    },
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        _role_template_store(root)
        chat_db = root / "chat.db"
        return {
            "status": "ok",
            "service": "xmuse-chat-api",
            "chat_db": {
                "path": str(chat_db),
                "exists": chat_db.exists(),
            },
            "role_templates": "ready",
        }

    @app.post("/api/chat/conversations", status_code=status.HTTP_201_CREATED)
    def create_conversation(request: ConversationCreate) -> dict[str, object]:
        participants = (
            None
            if request.initial_participants is None
            else [
                participant.model_dump(mode="json")
                for participant in request.initial_participants
            ]
        )
        init_mode = request.init_mode
        if "init_mode" not in request.model_fields_set:
            init_mode = "deterministic"
        try:
            result = _peer_service(root).create_conversation(
                title=request.title.strip(),
                participants=participants,
                preset_id=request.preset_id,
                init_mode=init_mode,
                provider_overrides={
                    key: value.model_dump(mode="json")
                    for key, value in request.provider_overrides.items()
                },
            )
        except PeerChatError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        payload = result["conversation"]
        payload["bootstrap"] = result["bootstrap"]
        listed = _peer_service(root).list_participants(
            conversation_id=str(payload["id"]),
            registry_path=root / "god_sessions.json",
        )
        payload["participants"] = _public_peer_participants(listed)
        return payload

    @app.post(
        "/api/chat/conversations/{conversation_id}/bootstrap/proposals",
        status_code=status.HTTP_201_CREATED,
    )
    def create_bootstrap_proposal(
        conversation_id: str,
        request: BootstrapProposalCreate,
    ) -> dict[str, object]:
        try:
            return _peer_service(root).create_bootstrap_proposal(
                conversation_id=conversation_id,
                source=request.source,
            )
        except PeerChatError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get("/api/chat/conversations/{conversation_id}/bootstrap/status")
    def get_bootstrap_status(conversation_id: str) -> dict[str, object]:
        try:
            return _peer_service(root).get_bootstrap_status(conversation_id)
        except PeerChatError as exc:
            raise HTTPException(
                status_code=404 if exc.code == "unknown_conversation" else 400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post("/api/chat/conversations/{conversation_id}/bootstrap/apply")
    def apply_bootstrap_proposal(
        conversation_id: str,
        request: BootstrapApplyCreate,
    ) -> dict[str, object]:
        try:
            return _peer_service(root).apply_bootstrap_proposal(
                conversation_id=conversation_id,
                proposal_id=request.proposal_id,
                registry_path=root / "god_sessions.json",
            )
        except PeerChatError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get("/api/chat/conversations")
    def list_conversations() -> dict[str, object]:
        return _peer_service(root).list_conversations(
            api_href_template="/api/chat/conversations/{conversation_id}/messages"
        )

    @app.post("/api/chat/operator/actions")
    def run_operator_action(
        request: OperatorActionCreate,
        http_request: Request,
    ) -> dict[str, object]:
        payload = dict(request.payload)
        action = request.action.strip().lower().replace("-", "_")
        conversation_id = payload.get("conversation_id")
        if (
            action == "select_god_cli"
            and isinstance(conversation_id, str)
            and conversation_id.strip()
            and not _conversation_exists(_store(root), conversation_id.strip())
        ):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "unknown_conversation",
                    "message": "conversation not found",
                },
            )
        result = _operator_action_service(root).handle(
            OperatorActionRequest(
                action=action,
                actor_id=_operator_actor_id(http_request),
                capabilities=_operator_capabilities(http_request),
                idempotency_key=_request_id(request.idempotency_key),
                payload=payload,
                source="chat_api",
            )
        )
        if result.status != "ok":
            raise HTTPException(
                status_code=_operator_action_http_status(result),
                detail=result.model_dump(),
            )
        return result.model_dump()

    @app.get("/api/chat/operator/god-cli-selections/{conversation_id}")
    def get_god_cli_selection(conversation_id: str) -> dict[str, object]:
        selection = _god_cli_selection_store(root).get(conversation_id)
        if selection is None:
            raise HTTPException(status_code=404, detail="god cli selection not found")
        return {"selection": selection.model_dump()}

    @app.get("/api/chat/operator/god-cli-registrations")
    def list_god_cli_registrations() -> dict[str, object]:
        records = _god_cli_registration_store(root).list_records()
        return {"registrations": [record.model_dump() for record in records]}

    @app.get("/api/chat/conversations/{conversation_id}/participants")
    def list_participants(conversation_id: str) -> dict[str, object]:
        try:
            payload = _peer_service(root).list_participants(
                conversation_id=conversation_id,
                registry_path=root / "god_sessions.json",
            )
            payload["participants"] = _public_peer_participants(payload)
            return payload
        except PeerChatError as exc:
            raise HTTPException(
                status_code=404 if exc.code == "unknown_conversation" else 400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room",
        status_code=status.HTTP_201_CREATED,
    )
    def ensure_god_room(conversation_id: str) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        participants = _god_room_participants(root, conversation_id)
        if not participants:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "god_room_requires_participants",
                    "message": "god room requires active non-init participants",
                },
            )
        store = _god_room_event_store(root)
        room_id = _default_god_room_id(conversation_id)
        try:
            store.ensure_room(
                room_id=room_id,
                conversation_id=conversation_id,
                participants=participants,
            )
        except GodRoomMembershipError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "god_room_membership_error", "message": str(exc)},
            ) from exc
        return {"room": _god_room_payload(store, room_id)}

    @app.get("/api/chat/conversations/{conversation_id}/god-room")
    def get_god_room(conversation_id: str) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        store = _god_room_event_store(root)
        room_id = _default_god_room_id(conversation_id)
        try:
            return {"room": _god_room_payload(store, room_id)}
        except GodRoomMembershipError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "god_room_not_found", "message": str(exc)},
            ) from exc

    @app.post("/api/chat/conversations/{conversation_id}/god-room/events")
    def append_god_room_event(
        conversation_id: str,
        request: GodRoomEventV1,
    ) -> JSONResponse:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        expected_room_id = _default_god_room_id(conversation_id)
        if request.conversation_id != conversation_id or request.room_id != expected_room_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "god_room_event_scope_mismatch",
                    "message": (
                        "event conversation_id and room_id must match the "
                        "conversation GOD room"
                    ),
                },
            )
        store = _god_room_event_store(root)
        try:
            result = store.append_event(request)
        except GodRoomMembershipError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "god_room_membership_error", "message": str(exc)},
            ) from exc
        except GodRoomEventConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "god_room_event_conflict", "message": str(exc)},
            ) from exc
        return JSONResponse(
            status_code=(
                status.HTTP_201_CREATED
                if result.status == "created"
                else status.HTTP_200_OK
            ),
            content={
                "append_status": result.status,
                "event": result.event.model_dump(mode="json"),
                "room": _god_room_payload(store, expected_room_id),
            },
        )

    @app.get("/api/chat/conversations/{conversation_id}/god-room/snapshot")
    def get_god_room_snapshot(conversation_id: str) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        store = _god_room_event_store(root)
        try:
            return {
                "snapshot": store.build_room_snapshot_artifact(
                    _default_god_room_id(conversation_id)
                )
            }
        except GodRoomMembershipError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "god_room_not_found", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/speaker-attempt",
        status_code=status.HTTP_201_CREATED,
    )
    def build_god_room_speaker_attempt(
        conversation_id: str,
        request: GodRoomSpeakerAttemptRequest,
    ) -> dict[str, object]:
        return _build_god_room_speaker_attempt_from_runtime(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/provider-invocation",
        status_code=status.HTTP_201_CREATED,
    )
    def invoke_god_room_provider_speech(
        conversation_id: str,
        request: GodRoomProviderInvocationRequest,
    ) -> dict[str, object]:
        return _invoke_god_room_provider_speech_from_runtime(
            root,
            execution_worktree=execution_root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/provider-invocation-capture",
        status_code=status.HTTP_201_CREATED,
    )
    def invoke_and_capture_god_room_provider_speech(
        conversation_id: str,
        request: GodRoomProviderInvocationCaptureRequest,
    ) -> dict[str, object]:
        return _invoke_and_capture_god_room_provider_speech_from_runtime(
            root,
            execution_worktree=execution_root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/speaker-response",
        status_code=status.HTTP_201_CREATED,
    )
    def capture_god_room_speaker_response(
        conversation_id: str,
        request: GodRoomSpeakerResponseRequest,
    ) -> dict[str, object]:
        return _capture_god_room_speaker_response_from_runtime(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/freeze-blueprint",
        status_code=status.HTTP_201_CREATED,
    )
    def freeze_god_room_blueprint(
        conversation_id: str,
        request: GodRoomBlueprintFreezeRequest,
    ) -> dict[str, object]:
        return _freeze_blueprint_from_god_room(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/lane-dag",
        status_code=status.HTTP_201_CREATED,
    )
    def build_god_room_lane_dag(
        conversation_id: str,
        request: GodRoomLaneDagRequest,
    ) -> dict[str, object]:
        return _build_lane_dag_from_god_room_freeze(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/lane-dag/recovery",
        status_code=status.HTTP_201_CREATED,
    )
    def evaluate_god_room_lane_recovery(
        conversation_id: str,
        request: GodRoomLaneRecoveryRequest,
    ) -> dict[str, object]:
        return _evaluate_god_room_lane_recovery(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/lane-dag/review-intake",
        status_code=status.HTTP_201_CREATED,
    )
    def build_god_room_lane_review_intake(
        conversation_id: str,
        request: GodRoomLaneReviewIntakeRequest,
    ) -> dict[str, object]:
        return _build_god_room_lane_review_intake(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/lane-dag/review-verdict",
        status_code=status.HTTP_201_CREATED,
    )
    def build_god_room_lane_review_verdict(
        conversation_id: str,
        request: GodRoomLaneReviewVerdictRequest,
    ) -> dict[str, object]:
        return _build_god_room_lane_review_verdict(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/lane-dag/patch-forward",
        status_code=status.HTTP_201_CREATED,
    )
    def apply_god_room_lane_patch_forward(
        conversation_id: str,
        request: GodRoomLanePatchForwardRequest,
    ) -> dict[str, object]:
        return _apply_god_room_lane_patch_forward(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/god-room/memoryos-plan",
        status_code=status.HTTP_201_CREATED,
    )
    def build_god_room_memoryos_plan(
        conversation_id: str,
        request: GodRoomMemoryPlanRequest,
    ) -> dict[str, object]:
        return _build_god_room_memoryos_plan(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.get("/api/chat/conversations/{conversation_id}/inspector")
    def inspect_conversation(conversation_id: str) -> dict[str, object]:
        try:
            return _peer_service(root).inspect_conversation(conversation_id)
        except PeerChatError as exc:
            raise HTTPException(
                status_code=404 if exc.code == "conversation_not_found" else 400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post(
        "/api/chat/conversations/{conversation_id}/collaboration/requests",
        status_code=status.HTTP_201_CREATED,
    )
    def create_collaboration_request(
        conversation_id: str,
        request: CollaborationRequestCreate,
    ) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        try:
            run = _collaboration_store(root).create_request(
                conversation_id=conversation_id,
                goal=request.goal,
                initiator=request.initiator,
                targets=request.targets,
                callback_target=request.callback_target,
                question=request.question,
                context_refs=request.context_refs,
                idempotency_key=request.idempotency_key,
                timeout_s=request.timeout_s,
                orchestration_mode=request.orchestration_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"run": run.model_dump(mode="json")}

    @app.post(
        "/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/responses",
    )
    def record_collaboration_response(
        conversation_id: str,
        run_id: str,
        request: CollaborationResponseCreate,
    ) -> dict[str, object]:
        store = _collaboration_store(root)
        try:
            run = store.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collaboration run not found") from exc
        if run.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="collaboration run not found")
        if request.target not in run.targets:
            raise HTTPException(status_code=400, detail="target is not part of run")
        updated = store.record_response(
            run_id,
            target=request.target,
            content=request.content,
            response_status=request.status,
        )
        return {"run": updated.model_dump(mode="json")}

    @app.post(
        "/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/blockers",
        status_code=status.HTTP_201_CREATED,
    )
    def raise_collaboration_blocker(
        conversation_id: str,
        run_id: str,
        request: CollaborationBlockerCreate,
    ) -> dict[str, object]:
        store = _collaboration_store(root)
        try:
            run = store.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collaboration run not found") from exc
        if run.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="collaboration run not found")
        try:
            blocker = store.raise_blocker(
                run_id,
                issuer=request.issuer,
                severity=request.severity,
                reason=request.reason,
                affected_ref=request.affected_ref,
                suggested_fix=request.suggested_fix,
                blocks_dispatch=request.blocks_dispatch,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"blocker": blocker.model_dump(mode="json")}

    @app.post(
        "/api/chat/conversations/{conversation_id}/collaboration/blockers/{blocker_id}/resolve",
    )
    def resolve_collaboration_blocker(
        conversation_id: str,
        blocker_id: str,
        request: CollaborationBlockerResolve,
    ) -> dict[str, object]:
        store = _collaboration_store(root)
        try:
            blocker = store.get_blocker(blocker_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collaboration blocker not found") from exc
        if blocker.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="collaboration blocker not found")
        try:
            resolved = store.resolve_blocker(
                blocker_id,
                resolved_by=request.resolved_by,
                resolution_evidence=request.resolution_evidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"blocker": resolved.model_dump(mode="json")}

    @app.post(
        "/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/dispatch-gate",
    )
    def evaluate_collaboration_dispatch_gate(
        conversation_id: str,
        run_id: str,
        request: CollaborationDispatchGateRequest,
    ) -> dict[str, object]:
        decision = _collaboration_store(root).evaluate_dispatch_gate(
            conversation_id=conversation_id,
            run_id=run_id,
            proposal_ref=request.proposal_ref,
            artifact_ref=request.artifact_ref,
            execute_confirmed=request.execute_confirmed,
            policy_allows_real_provider=request.policy_allows_real_provider,
        )
        return {"decision": decision.value}

    @app.post("/api/chat/conversations/{conversation_id}/dispatch/claim")
    def claim_dispatch_entry(
        conversation_id: str,
        request: DispatchClaimRequest,
    ) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        entry = _dispatch_queue_store(root).claim_next_auto_dispatch(
            conversation_id=conversation_id,
            claimed_by=request.claimed_by,
        )
        return {"entry": None if entry is None else entry.model_dump(mode="json")}

    @app.post("/api/chat/dispatch/{entry_id}/dispatched")
    def mark_dispatch_entry_dispatched(
        entry_id: str,
        request: DispatchDispatchedRequest,
    ) -> dict[str, object]:
        try:
            entry = _dispatch_queue_store(root).mark_dispatched(
                entry_id,
                provider_run_ref=request.provider_run_ref,
                dispatch_evidence=request.dispatch_evidence,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="dispatch entry not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"entry": entry.model_dump(mode="json")}

    @app.post("/api/chat/dispatch/{entry_id}/failed")
    def mark_dispatch_entry_failed(
        entry_id: str,
        request: DispatchFailedRequest,
    ) -> dict[str, object]:
        try:
            entry = _dispatch_queue_store(root).mark_failed(
                entry_id,
                failure_reason=request.failure_reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="dispatch entry not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"entry": entry.model_dump(mode="json")}

    @app.post(
        "/api/chat/conversations/{conversation_id}/participants",
        status_code=status.HTTP_201_CREATED,
    )
    def add_participant(conversation_id: str, request: ParticipantInit) -> dict[str, object]:
        created = _add_participants(
            base_dir=root,
            conversation_id=conversation_id,
            participants=[request],
        )
        return created[0]

    @app.delete(
        "/api/chat/conversations/{conversation_id}/participants/{participant_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_participant(conversation_id: str, participant_id: str) -> None:
        store = _store(root)
        if not _conversation_exists(store, conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        participant_store = _participant_store(root)
        try:
            participant = participant_store.get(participant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="participant not found") from exc
        if participant.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="participant not found")
        participant_store.delete(participant_id)

    @app.get("/api/chat/conversations/{conversation_id}/forks")
    def list_forks(conversation_id: str) -> dict[str, object]:
        try:
            return _peer_service(root).list_fork_lineage(
                conversation_id=conversation_id,
                registry_path=root / "god_sessions.json",
            )
        except PeerChatError as exc:
            raise HTTPException(
                status_code=404 if exc.code == "unknown_conversation" else 400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post(
        "/api/chat/conversations/{conversation_id}/forks",
        status_code=status.HTTP_201_CREATED,
    )
    def create_fork(conversation_id: str, request: PeerForkCreate) -> dict[str, object]:
        try:
            return _peer_service(root).fork_participant(
                registry_path=root / "god_sessions.json",
                conversation_id=conversation_id,
                source_peer_id=request.source_peer_id,
                role=request.role,
                display_name=request.display_name,
                model=request.model,
                role_template_id=request.role_template_id,
                prompt_delta=request.prompt_delta,
                inherited_refs=request.inherited_refs,
                model_policy=request.model_policy,
                feature_scope_id=request.feature_scope_id,
                fork_reason=request.fork_reason,
            )
        except PeerChatError as exc:
            status_code = 404 if exc.code == "unknown_conversation" else 400
            raise HTTPException(
                status_code=status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/chat/role-templates")
    def list_role_templates() -> dict[str, object]:
        templates = _role_template_store(root).list_all()
        return {"role_templates": [template.model_dump(mode="json") for template in templates]}

    @app.post("/api/chat/role-templates", status_code=status.HTTP_201_CREATED)
    def create_role_template(request: RoleTemplateCreate) -> dict[str, object]:
        try:
            cli_kind = resolve_codex_cli_kind(
                cli_kind=request.cli_kind,
                provider_id=request.provider_id,
                profile_id=request.profile_id,
                expected_profile_id=provider_profile_id_for_template_slug(request.slug),
                subject="xmuse chat role templates",
            )
            template = _role_template_store(root).create(
                slug=request.slug.strip(),
                display_name=request.display_name.strip(),
                prompt=request.prompt.strip(),
                cli_kind=cli_kind,
                default_model=request.default_model.strip(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="role template slug already exists",
            ) from exc
        return template.model_dump(mode="json")

    @app.put("/api/chat/role-templates/{template_id}")
    def update_role_template(template_id: str, request: RoleTemplateUpdate) -> dict[str, object]:
        role_templates = _role_template_store(root)
        try:
            existing = role_templates.get(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="role template not found") from exc
        if existing.predefined:
            raise HTTPException(status_code=409, detail="predefined role templates are read-only")
        try:
            cli_kind = resolve_codex_cli_kind(
                cli_kind=request.cli_kind,
                provider_id=request.provider_id,
                profile_id=request.profile_id,
                expected_profile_id=existing.profile_id,
                subject="xmuse chat role templates",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        template = role_templates.update(
            template_id,
            display_name=request.display_name.strip() if request.display_name is not None else None,
            prompt=request.prompt.strip() if request.prompt is not None else None,
            cli_kind=cli_kind,
            default_model=(
                request.default_model.strip() if request.default_model is not None else None
            ),
        )
        return template.model_dump(mode="json")

    @app.delete(
        "/api/chat/role-templates/{template_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_role_template(template_id: str) -> None:
        role_templates = _role_template_store(root)
        try:
            existing = role_templates.get(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="role template not found") from exc
        if existing.predefined:
            raise HTTPException(
                status_code=409,
                detail="predefined role templates are read-only",
            )
        if _role_template_has_participants(root, template_id):
            raise HTTPException(
                status_code=409,
                detail="role template is still referenced by participants",
            )
        role_templates.delete(template_id)

    @app.get("/api/chat/conversations/{conversation_id}/messages")
    def list_messages(conversation_id: str) -> dict[str, object]:
        return _chat_timeline_payload(root, conversation_id)

    @app.post(
        "/api/chat/conversations/{conversation_id}/messages",
        status_code=status.HTTP_201_CREATED,
    )
    def add_message(conversation_id: str, request: MessageCreate) -> dict[str, object]:
        if request.role.strip() != "human":
            try:
                message = _store(root).add_message(
                    conversation_id=conversation_id,
                    author=request.author.strip(),
                    role=request.role.strip(),
                    content=request.content.strip(),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=404, detail="conversation not found") from exc
            return message.model_dump(mode="json")
        try:
            result = _peer_service(root).post_human_message(
                conversation_id=conversation_id,
                author=request.author.strip(),
                content=request.content.strip(),
                client_request_id=_request_id(request.client_request_id),
            )
        except PeerChatError as exc:
            if exc.code == "unknown_target":
                return _plain_human_message_payload(
                    root,
                    conversation_id=conversation_id,
                    author=request.author.strip(),
                    content=request.content.strip(),
                )
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        payload = result.message.model_dump(mode="json")
        payload["inbox_items"] = [
            item.model_dump(mode="json") for item in result.inbox_items
        ]
        return payload

    @app.post(
        "/api/chat/conversations/{conversation_id}/deliberations",
        status_code=status.HTTP_201_CREATED,
    )
    def append_deliberation(
        conversation_id: str,
        request: DeliberationAppendCreate,
    ) -> dict[str, object]:
        store = _store(root)
        if not _conversation_exists(store, conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        try:
            deliberation = _deliberation_message_from_request(conversation_id, request)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        idempotency_key = deliberation.idempotency_key()
        message = store.add_message(
            conversation_id=conversation_id,
            author=deliberation.agent_id,
            role="assistant",
            content=_deliberation_content(deliberation),
            envelope_type="deliberation",
            envelope_json={
                "type": "deliberation",
                "message": deliberation.model_dump(mode="json"),
                "idempotency_key": idempotency_key,
            },
            mentions=deliberation.mentions,
            reply_to_message_id=deliberation.parent_id,
        )
        payload = message.model_dump(mode="json")
        payload["deliberation"] = deliberation.model_dump(mode="json")
        payload["idempotency_key"] = idempotency_key
        return payload

    @app.post(
        "/api/chat/conversations/{conversation_id}/freeze-blueprint",
        status_code=status.HTTP_201_CREATED,
    )
    def freeze_blueprint(
        conversation_id: str,
        request: BlueprintFreezeRequest,
    ) -> dict[str, object]:
        return _freeze_blueprint_for_request(
            root,
            conversation_id=conversation_id,
            request=request,
        )

    @app.post(
        "/api/chat/conversations/{conversation_id}/proposals",
        status_code=status.HTTP_201_CREATED,
    )
    def create_proposal(conversation_id: str, request: ProposalCreate) -> dict[str, object]:
        try:
            escalation = classify_structured_proposal(
                proposal_type=request.proposal_type.strip(),
                content=request.content.strip(),
                references=request.references,
            )
            normalized_payload: dict[str, Any] | None = None
            if escalation.normalized_proposal_type == "feature_plan":
                normalized_payload = json.loads(escalation.normalized_content)
                _require_current_feature_plan_blueprint(
                    _store(root),
                    conversation_id=conversation_id,
                    proposal_payload=normalized_payload,
                    references=request.references,
                )
            proposal = _store(root).create_proposal(
                conversation_id=conversation_id,
                author=request.author.strip(),
                proposal_type=escalation.normalized_proposal_type,
                content=escalation.normalized_content,
                references=request.references,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except PeerChatError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return proposal.model_dump(mode="json")

    @app.post("/api/chat/proposals/{proposal_id}/approve")
    def approve_proposal(proposal_id: str, request: ProposalApproval) -> dict[str, object]:
        try:
            store = _store(root)
            proposal = store.get_proposal(proposal_id)
            escalation = classify_structured_proposal(
                proposal_type=proposal.proposal_type,
                content=proposal.content,
                references=proposal.references,
            )
            content = request.content
            feature_plan_proposal = None
            if escalation.normalized_proposal_type == "feature_plan":
                proposal_payload = json.loads(escalation.normalized_content)
                _require_current_feature_plan_blueprint(
                    store,
                    conversation_id=proposal.conversation_id,
                    proposal_payload=proposal_payload,
                    references=proposal.references,
                )
                feature_plan_proposal = _build_feature_plan_proposal_record(
                    root,
                    proposal=proposal,
                    content=content,
                )
                content = _feature_plan_resolution_content(feature_plan_proposal)
            if content is None:
                try:
                    proposal_payload = json.loads(escalation.normalized_content)
                except json.JSONDecodeError:
                    proposal_payload = {}
                content = proposal_payload.get("resolution_content") or {}
            _enforce_collaboration_dispatch_gate(
                root,
                conversation_id=proposal.conversation_id,
                proposal_id=proposal_id,
                proposal_type=escalation.normalized_proposal_type,
                references=proposal.references,
            )
            resolution = store.approve_proposal(
                proposal_id=proposal_id,
                approved_by=request.approved_by,
                approval_mode=request.approval_mode.strip(),
                goal_summary=request.goal_summary.strip(),
                content=content,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="proposal not found") from exc
        except PeerChatError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        if feature_plan_proposal is not None:
            save_approved_feature_plan_artifacts(
                feature_plan_proposal,
                approval=FeaturePlanProposalApproval(
                    approved_by=request.approved_by,
                    approval_mode=request.approval_mode.strip(),
                    approved_at=resolution.created_at,
                ),
                resolution_id=resolution.id,
                version=resolution.version,
                feature_plans_root=root / "feature_plans",
                graph_sets_root=root / "lane_graphs",
                lanes_path=root / "feature_lanes.json",
            )
        payload = resolution.model_dump(mode="json")
        _mark_review_trigger_read_for_approved_proposal(
            root,
            conversation_id=resolution.conversation_id,
            proposal_id=proposal_id,
        )
        _append_resolution_read_model(root, payload)
        produce_blueprint_approval_event(root, resolution)
        _enqueue_structured_dispatch_intent(
            root,
            proposal_id=proposal_id,
            proposal_type=escalation.normalized_proposal_type,
            references=proposal.references,
            resolution=resolution,
        )
        _project_resolution_into_execution_queue(
            root,
            resolution,
            execution_worktree=execution_root,
        )
        return payload

    @app.get("/api/chat/proposals/{proposal_id}")
    def get_proposal(proposal_id: str) -> dict[str, object]:
        try:
            proposal = _store(root).get_proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="proposal not found") from exc
        return proposal.model_dump(mode="json")

    @app.get("/api/chat/resolutions/{resolution_id}")
    def get_resolution(resolution_id: str) -> dict[str, object]:
        try:
            resolution = _store(root).get_resolution(resolution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="resolution not found") from exc
        return resolution.model_dump(mode="json")

    @app.get("/api/chat/threads")
    def list_threads() -> dict[str, object]:
        store = _store(root)
        service = _peer_service(root)
        threads = []
        workspace_rows = service.list_conversations(
            api_href_template="/api/chat/conversations/{conversation_id}/messages"
        )["conversations"]
        for workspace in workspace_rows:
            conversation_id = str(workspace["id"])
            timeline = _chat_timeline_payload(root, conversation_id)
            messages = [
                chat_api_message
                for chat_api_message in store.list_messages(conversation_id)
                if chat_api_message.envelope_type in {None, "message", "mention"}
            ]
            last_message = messages[-1] if messages else None
            thread = dict(workspace)
            thread.update(
                {
                    "featureId": workspace["title"],
                    "agent": "Human + Gods",
                    "status": "pending" if not messages else "reviewed",
                    "updatedAt": workspace["last_activity_at"],
                    "summary": (last_message.content if last_message else workspace["title"]),
                    "messages": [
                        {
                            "id": message.id,
                            "role": self_role,
                            "author": message.author,
                            "kind": kind,
                            "content": message.content,
                        }
                        for message in messages
                        for self_role, kind in [
                            (
                                "user"
                                if message.role == "human"
                                else ("tool" if message.role == "tool" else "assistant"),
                                "tool_call"
                                if message.role == "tool"
                                else ("checkpoint" if message.role == "human" else "answer"),
                            )
                        ]
                    ],
                    "cards": timeline["cards"],
                    "card_counts": _card_counts(timeline["cards"]),
                    "recent_cards": timeline["cards"][-5:],
                    "items": timeline["items"],
                }
            )
            threads.append(thread)
        return {"threads": threads}

    @app.post("/api/chat/threads/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
    def add_thread_message(conversation_id: str, request: ThreadMessageCreate) -> dict[str, object]:
        try:
            result = _peer_service(root).post_human_message(
                conversation_id=conversation_id,
                author="Human operator",
                content=request.message.strip(),
                client_request_id=_request_id(request.client_request_id),
            )
        except PeerChatError as exc:
            if exc.code == "unknown_target":
                message = _plain_human_message_payload(
                    root,
                    conversation_id=conversation_id,
                    author="Human operator",
                    content=request.message.strip(),
                )
                return {
                    "thread_id": conversation_id,
                    "message": {
                        "id": message["id"],
                        "role": "user",
                        "author": message["author"],
                        "kind": "checkpoint",
                        "content": message["content"],
                        "mentions": message["mentions"],
                        "envelope_type": message["envelope_type"],
                        "envelope_json": message["envelope_json"],
                    },
                }
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        return {
            "thread_id": conversation_id,
            "message": {
                "id": result.message.id,
                "role": "user",
                "author": result.message.author,
                "kind": "checkpoint",
                "content": result.message.content,
                "mentions": result.message.mentions,
                "envelope_type": result.message.envelope_type,
                "envelope_json": result.message.envelope_json,
            },
        }

    return app


def main() -> None:
    uvicorn.run(
        create_app(auth_token=_auth_token_from_env()),
        host="127.0.0.1",
        port=DEFAULT_PORT,
    )


if __name__ == "__main__":
    main()
