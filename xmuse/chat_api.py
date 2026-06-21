#!/usr/bin/env python3
"""REST API for the xmuse chat-plane MVP."""

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
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
    MessageCreate,
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
    CollaborationStatus,
    DispatchGateDecision,
)
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.deliberation_engine import DeliberationFreezeGuard
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.health_cards import build_run_health_chat_card
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.models import Proposal, ProposalStatus
from xmuse_core.chat.participant_store import (
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
from xmuse_core.platform.read_contracts import build_execution_drilldown_refs
from xmuse_core.platform.run_health import summarize_run_health
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.structuring.blueprint_execution.approval_events import (
    produce_blueprint_approval_event,
)
from xmuse_core.structuring.feature_plan_store import (
    build_feature_plan_proposal,
    read_approved_mission_blueprint,
    save_approved_feature_plan_artifacts,
)
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintDecisionLogEntry,
    MissionBlueprintStatus,
    MissionBlueprintV1,
    render_mission_blueprint_markdown,
)
from xmuse_core.structuring.models import FeaturePlanFeature, FeaturePlanProposalApproval
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


def _acceptance_spine_store(base_dir: Path) -> AcceptanceSpineStore:
    return AcceptanceSpineStore(base_dir / "chat.db")


def _peer_chat_error_detail(exc: PeerChatError) -> dict[str, object]:
    detail: dict[str, object] = {"code": exc.code, "message": exc.message}
    detail.update(exc.details)
    return detail


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


def _enforce_collaboration_proposal_freshness(
    store: ChatStore,
    collaboration_store: ChatCollaborationStore,
    proposal: Proposal,
) -> None:
    for run_id in _collaboration_run_refs(proposal.references):
        run = _collaboration_run_or_none(collaboration_store, run_id)
        if run is None or run.conversation_id != proposal.conversation_id:
            raise PeerChatError("dispatch_gate_blocked", "blocked_unknown_run")
        if run.status is not CollaborationStatus.DONE:
            raise PeerChatError("dispatch_gate_blocked", "blocked_collaboration_not_done")
        if _proposal_created_before_collaboration_done(proposal, run):
            raise PeerChatError("dispatch_gate_blocked", "blocked_stale_collaboration_proposal")
        if _newer_open_collaboration_proposal_exists(store, proposal, run_id):
            raise PeerChatError(
                "dispatch_gate_blocked",
                "blocked_newer_collaboration_proposal_exists",
            )


def _proposal_created_before_collaboration_done(
    proposal: Proposal,
    run: CollaborationRun,
) -> bool:
    proposal_ts = _parse_utc_timestamp(proposal.created_at)
    run_done_ts = _parse_utc_timestamp(run.updated_at)
    return proposal_ts < run_done_ts


def _newer_open_collaboration_proposal_exists(
    store: ChatStore,
    proposal: Proposal,
    run_id: str,
) -> bool:
    proposal_ts = _parse_utc_timestamp(proposal.created_at)
    collaboration_ref = f"collaboration:{run_id}"
    for other in store.list_proposals(proposal.conversation_id):
        if other.id == proposal.id or other.status is not ProposalStatus.OPEN:
            continue
        if collaboration_ref not in other.references:
            continue
        if _parse_utc_timestamp(other.created_at) >= proposal_ts:
            return True
    return False


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _collaboration_execute_confirmed(run: CollaborationRun | None) -> bool:
    if run is None:
        return False
    return any(
        response.target in {"execute", "@execute"}
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
    verdict_type = payload.get("type") or payload.get("response_type")
    if verdict_type != "execute_feasibility_verdict":
        return False
    if payload.get("status") == "executable":
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return False
        evidence_refs = payload.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            return False
        return any(isinstance(ref, str) and bool(ref.strip()) for ref in evidence_refs)
    verdict_confirms = _execute_verdict_text_confirms_dispatchability(
        payload.get("verdict")
    )
    if (
        payload.get("dispatchable") is not True
        and payload.get("feasible") is not True
        and not verdict_confirms
    ):
        return False
    command = payload.get("command") or payload.get("later_execution_command")
    if not isinstance(command, str) or not command.strip():
        return False
    proof_boundary = payload.get("proof_boundary")
    if not isinstance(proof_boundary, str) or not proof_boundary.strip():
        return False
    summary = payload.get("summary")
    notes = payload.get("notes")
    if (
        not isinstance(summary, str)
        or not summary.strip()
    ) and not (
        isinstance(notes, str)
        and notes.strip()
        or isinstance(notes, list)
        and any(isinstance(note, str) and note.strip() for note in notes)
    ):
        return False
    return True


def _execute_verdict_text_confirms_dispatchability(value: object) -> bool:
    if not isinstance(value, str):
        return False
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", value.strip().lower())
        if token
    ]
    if not tokens:
        return False
    negative_tokens = {
        "blocked",
        "cannot",
        "denied",
        "deny",
        "failed",
        "failure",
        "non",
        "not",
        "reject",
        "rejected",
        "unsafe",
    }
    if any(token in negative_tokens for token in tokens):
        return False
    return any(token in {"dispatchable", "feasible", "executable"} for token in tokens)


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


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
    graph = _with_approved_proposal_execution_contract(base_dir, resolution, graph)
    LaneGraphStore(base_dir / "lane_graphs").save(graph)
    project_ready_lanes(
        graph,
        base_dir / "feature_lanes.json",
        operational_metadata={"worktree": str(execution_worktree)},
    )


def _with_approved_proposal_execution_contract(
    base_dir: Path,
    resolution: object,
    graph: Any,
) -> Any:
    content = getattr(resolution, "content", None)
    if not isinstance(content, dict) or content.get("type") != "lane_graph":
        return graph
    source_refs = _approved_proposal_execution_source_refs(base_dir, resolution)
    lanes = [
        lane.model_copy(
            update={
                "prompt": _approved_proposal_execution_prompt(
                    lane.prompt,
                    base_dir=base_dir,
                    resolution=resolution,
                    source_refs=source_refs,
                )
            }
        )
        for lane in graph.lanes
    ]
    return graph.model_copy(
        update={
            "source_refs": _dedupe_text([*graph.source_refs, *source_refs]),
            "lanes": lanes,
        }
    )


def _approved_proposal_execution_source_refs(base_dir: Path, resolution: object) -> list[str]:
    refs = [
        f"resolution:{getattr(resolution, 'id', '')}",
        f"conversation:{getattr(resolution, 'conversation_id', '')}",
        f"runtime_root:{base_dir}",
        f"chat_db:{base_dir / 'chat.db'}",
    ]
    content = getattr(resolution, "content", None)
    if isinstance(content, dict):
        refs.extend(
            str(ref).strip()
            for ref in content.get("references", [])
            if isinstance(ref, str) and ref.strip()
        )
    proposal_ids = [
        str(proposal_id).strip()
        for proposal_id in getattr(resolution, "derived_from_proposal_ids", [])
        if str(proposal_id).strip()
    ]
    store = _store(base_dir)
    for proposal_id in proposal_ids:
        refs.append(f"proposal:{proposal_id}")
        try:
            proposal = store.get_proposal(proposal_id)
        except KeyError:
            continue
        refs.extend(proposal.references)
        try:
            payload = json.loads(proposal.content)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            refs.extend(
                str(ref).strip()
                for ref in payload.get("references", [])
                if isinstance(ref, str) and ref.strip()
            )
    for summary_path in sorted(base_dir.glob("loop*_summary.json")):
        refs.append(f"runtime_artifact:{summary_path}")
    return _dedupe_text([ref for ref in refs if ref])


def _approved_proposal_execution_prompt(
    original_prompt: str,
    *,
    base_dir: Path,
    resolution: object,
    source_refs: list[str],
) -> str:
    original = original_prompt.strip()
    if original.startswith("Approved proposal execution contract"):
        return original
    proposal_ids = ", ".join(
        str(proposal_id)
        for proposal_id in getattr(resolution, "derived_from_proposal_ids", [])
    )
    lines = [
        "Approved proposal execution contract",
        "",
        f"- resolution_id: {getattr(resolution, 'id', '')}",
        f"- conversation_id: {getattr(resolution, 'conversation_id', '')}",
        f"- proposal_ids: {proposal_ids or 'none'}",
        f"- xmuse_runtime_root: {base_dir}",
        "- Treat the original proposal prompt as source context. After approval, "
        "no-dispatch wording describes the proposal-production loop, not this "
        "execution/review continuation.",
        "- Prefer durable xmuse runtime refs and artifacts over checked-out docs "
        "when they conflict.",
        "- durable_source_refs:",
        *[f"  - {ref}" for ref in source_refs],
        "",
        "Original proposal lane prompt:",
        "",
        original,
    ]
    return "\n".join(lines).strip()


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
    app = FastAPI(title="xmuse Chat API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_write_auth(request: Request, call_next):
        if (
            auth_token
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("X-XMUSE-API-Key") != auth_token
        ):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "authentication required"},
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
                detail=_peer_chat_error_detail(exc),
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

    @app.get("/api/chat/conversations/{conversation_id}/acceptance-spines")
    def list_acceptance_spines(conversation_id: str) -> dict[str, object]:
        if not _conversation_exists(_store(root), conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation_id": conversation_id,
            "source_authority": "chat_store",
            "items": [
                spine.model_dump(mode="json")
                for spine in _acceptance_spine_store(root).list_by_conversation(
                    conversation_id
                )
            ],
        }

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
        store = _store(root)
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
        content = _blueprint_resolution_content(blueprint, decision_payload)
        proposal = store.create_proposal(
            conversation_id=conversation_id,
            author="xmuse-deliberation",
            proposal_type="mission_blueprint",
            content=json.dumps(content, ensure_ascii=False, sort_keys=True),
            references=blueprint.source_refs,
        )
        resolution = store.approve_proposal(
            proposal.id,
            approved_by=blueprint.approved_by,
            approval_mode="deliberation_freeze",
            goal_summary=blueprint.goal,
            content=content,
        )
        resolution_payload = resolution.model_dump(mode="json")
        _append_resolution_read_model(root, resolution_payload)
        produce_blueprint_approval_event(root, resolution)
        message = store.add_message(
            conversation_id=conversation_id,
            author="xmuse-deliberation",
            role="assistant",
            content=f"Frozen mission blueprint: {blueprint.goal}",
            envelope_type="blueprint_freeze",
            envelope_json={
                "type": "blueprint_freeze",
                "target_ref": request.target_ref,
                "proposal_id": proposal.id,
                "resolution_id": resolution.id,
                "blueprint": blueprint.model_dump(mode="json"),
                "decision": decision_payload,
            },
        )
        return {
            "decision": decision_payload,
            "blueprint": blueprint.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
            "resolution": resolution_payload,
            "message": message.model_dump(mode="json"),
        }

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
            _enforce_collaboration_proposal_freshness(
                store,
                _collaboration_store(root),
                proposal,
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
    uvicorn.run(create_app(), host="127.0.0.1", port=DEFAULT_PORT)


if __name__ == "__main__":
    main()
