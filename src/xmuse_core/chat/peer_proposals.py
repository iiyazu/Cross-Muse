from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.envelopes import mission_blueprint_envelope
from xmuse_core.chat.models import StructuredEscalationDecision, StructuredEscalationTarget
from xmuse_core.chat.peer_types import PeerChatError
from xmuse_core.chat.store import ChatStore


@dataclass(frozen=True)
class PeerProposalEmitter:
    chat: ChatStore

    def emit_blueprint_proposal(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        client_request_id: str,
        title: str,
        body: str,
        acceptance_criteria: list[str],
        revises_blueprint_ref: str | None,
        references: list[str],
    ) -> dict[str, Any]:
        proposal_ref = f"proposal_request:{conversation_id}:{client_request_id}:mission_blueprint"
        envelope = mission_blueprint_envelope(
            title=title,
            body=body,
            acceptance_criteria=acceptance_criteria,
            blueprint_ref=proposal_ref,
            revision_of=revises_blueprint_ref,
            references=references,
        )
        resolution_content = {
            "type": "mission_blueprint",
            "title": envelope["title"],
            "body": envelope["body"],
            "acceptance_criteria": envelope["acceptance_criteria"],
            "proposal_blueprint_ref": proposal_ref,
        }
        if revises_blueprint_ref is not None:
            resolution_content["revision_of"] = revises_blueprint_ref
        content_payload = {
            "summary": envelope["title"],
            "title": envelope["title"],
            "body": envelope["body"],
            "acceptance_criteria": envelope["acceptance_criteria"],
            **(
                {"source_blueprint_ref": revises_blueprint_ref}
                if revises_blueprint_ref is not None
                else {}
            ),
            "resolution_content": resolution_content,
        }
        return self.chat.create_proposal_message_and_log(
            conversation_id=conversation_id,
            tool_name="chat_emit_blueprint_proposal",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
            author=participant_id,
            proposal_type="mission_blueprint",
            content=json.dumps(content_payload),
            references=references,
            message_content=f"[mission blueprint] {envelope['title']}",
            envelope_json=envelope,
        )

    def emit_lane_graph_proposal(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        client_request_id: str,
        summary: str,
        lanes: list[dict[str, Any]],
        references: list[str],
        resolution_content: dict[str, Any] | None,
    ) -> dict[str, Any]:
        for lane in lanes:
            missing = {"feature_id", "prompt", "depends_on", "capabilities"} - set(lane)
            if missing:
                raise PeerChatError("invalid_lane_payload", ",".join(sorted(missing)))
        content_payload = {
            "summary": summary,
            "lanes": lanes,
            "resolution_content": _normalize_lane_graph_resolution_content(
                summary=summary,
                lanes=lanes,
                resolution_content=resolution_content,
            ),
        }
        return self.chat.create_proposal_message_and_log(
            conversation_id=conversation_id,
            tool_name="chat_emit_proposal",
            caller_identity=caller_identity,
            client_request_id=client_request_id,
            author=participant_id,
            proposal_type="lane_graph",
            content=json.dumps(content_payload),
            references=references,
            message_content=f"[proposal] {summary} ({len(lanes)} lanes)",
            envelope_json={
                "schema_version": 1,
                "type": "proposal",
                "summary": summary,
                "lanes": lanes,
                "references": references,
            },
        )


def classify_structured_proposal(
    *,
    proposal_type: str,
    content: str,
    references: list[str],
) -> StructuredEscalationDecision:
    normalized_type = proposal_type.strip()
    payload = _json_object_or_none(content)
    resolution_content = _resolution_content(payload)

    if _looks_like_mission_blueprint(normalized_type, payload, resolution_content):
        if payload is None:
            raise PeerChatError(
                "invalid_structured_escalation",
                "mission blueprint content must be a JSON object",
            )
        try:
            normalized_payload = _normalize_mission_blueprint_payload(payload)
        except PeerChatError:
            if normalized_type != StructuredEscalationTarget.MISSION_BLUEPRINT.value:
                raise
            normalized_payload = dict(payload)
        return StructuredEscalationDecision(
            target=StructuredEscalationTarget.MISSION_BLUEPRINT,
            normalized_proposal_type=StructuredEscalationTarget.MISSION_BLUEPRINT.value,
            normalized_content=json.dumps(normalized_payload),
            rationale="content contains mission-blueprint markers",
        )

    if _looks_like_feature_plan(payload, resolution_content, references):
        if _looks_like_lane_graph(payload, resolution_content):
            raise PeerChatError(
                "invalid_structured_escalation",
                "feature plan payload must not mix features and flat lanes",
            )
        if payload is None:
            raise PeerChatError(
                "invalid_structured_escalation",
                "feature plan content must be a JSON object",
            )
        normalized_payload = dict(payload)
        return StructuredEscalationDecision(
            target=StructuredEscalationTarget.FEATURE_PLAN,
            normalized_proposal_type=StructuredEscalationTarget.FEATURE_PLAN.value,
            normalized_content=json.dumps(normalized_payload),
            rationale="content contains approved-blueprint feature-plan markers",
        )

    if _looks_like_lane_graph(payload, resolution_content) or normalized_type == "lane_graph":
        if payload is None:
            raise PeerChatError(
                "invalid_structured_escalation",
                "lane graph content must be a JSON object",
            )
        normalized_payload = _normalize_lane_graph_payload(payload)
        return StructuredEscalationDecision(
            target=StructuredEscalationTarget.LANE_GRAPH,
            normalized_proposal_type=StructuredEscalationTarget.LANE_GRAPH.value,
            normalized_content=json.dumps(normalized_payload),
            rationale="content contains flat lane-graph markers",
        )

    if _looks_like_verdict(normalized_type, payload, resolution_content):
        if payload is None:
            raise PeerChatError(
                "invalid_structured_escalation",
                "verdict content must be a JSON object",
            )
        normalized_payload = _normalize_verdict_payload(payload)
        return StructuredEscalationDecision(
            target=StructuredEscalationTarget.VERDICT,
            normalized_proposal_type=StructuredEscalationTarget.VERDICT.value,
            normalized_content=json.dumps(normalized_payload),
            rationale="content contains verdict markers",
        )

    return StructuredEscalationDecision(
        target=StructuredEscalationTarget.PROPOSAL,
        normalized_proposal_type=StructuredEscalationTarget.PROPOSAL.value,
        normalized_content=content,
        rationale="content does not require structured escalation beyond generic proposal",
    )


def _json_object_or_none(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _resolution_content(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    resolution_content = payload.get("resolution_content")
    if isinstance(resolution_content, dict):
        return resolution_content
    return None


def _looks_like_feature_plan(
    payload: dict[str, Any] | None,
    resolution_content: dict[str, Any] | None,
    references: list[str],
) -> bool:
    if resolution_content and resolution_content.get("type") == "feature_plan":
        return True
    if payload is None:
        return False
    if "features" in payload or "source_blueprint_ref" in payload:
        return True
    if resolution_content and (
        "features" in resolution_content or "source_blueprint_ref" in resolution_content
    ):
        return True
    return any(
        isinstance(reference, str)
        and reference.startswith("resolution:")
        and reference.endswith(":mission_blueprint")
        for reference in references
    )


def _looks_like_mission_blueprint(
    proposal_type: str,
    payload: dict[str, Any] | None,
    resolution_content: dict[str, Any] | None,
) -> bool:
    if proposal_type == "mission_blueprint":
        return True
    if resolution_content and resolution_content.get("type") == "mission_blueprint":
        return True
    if payload is None:
        return False
    return all(field in payload for field in ("title", "body", "acceptance_criteria"))


def _looks_like_lane_graph(
    payload: dict[str, Any] | None,
    resolution_content: dict[str, Any] | None,
) -> bool:
    if resolution_content and resolution_content.get("type") == "lane_graph":
        return True
    if payload is None:
        return False
    return isinstance(payload.get("lanes"), list)


def _looks_like_verdict(
    proposal_type: str,
    payload: dict[str, Any] | None,
    resolution_content: dict[str, Any] | None,
) -> bool:
    if proposal_type == "verdict":
        return True
    if resolution_content and resolution_content.get("type") == "verdict":
        return True
    if payload is None:
        return False
    return "decision" in payload and "rationale" in payload


def _normalize_mission_blueprint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    title = str(normalized.get("title") or "").strip()
    body = str(normalized.get("body") or "").strip()
    criteria = [
        str(item).strip()
        for item in normalized.get("acceptance_criteria", [])
        if str(item).strip()
    ]
    if not title or not body or not criteria:
        raise PeerChatError(
            "invalid_structured_escalation",
            "mission blueprint payload requires title, body, and acceptance_criteria",
        )
    source_blueprint_ref = str(normalized.get("source_blueprint_ref") or "").strip()
    revision_of = str(normalized.get("revision_of") or "").strip()
    if source_blueprint_ref and not revision_of:
        revision_of = source_blueprint_ref
    normalized.setdefault("summary", title)
    normalized["resolution_content"] = {
        "type": "mission_blueprint",
        "title": title,
        "body": body,
        "acceptance_criteria": criteria,
        **(
            {"revision_of": revision_of}
            if revision_of
            else {}
        ),
    }
    return normalized


def _normalize_lane_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    lanes = normalized.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise PeerChatError(
            "invalid_structured_escalation",
            "lane graph payload requires a non-empty lanes list",
        )
    summary = str(normalized.get("summary") or "").strip()
    if not summary:
        raise PeerChatError(
            "invalid_structured_escalation",
            "lane graph payload requires summary",
        )
    normalized["resolution_content"] = _normalize_lane_graph_resolution_content(
        summary=summary,
        lanes=lanes,
        resolution_content=_resolution_content(normalized),
    )
    return normalized


def _normalize_lane_graph_resolution_content(
    *,
    summary: str,
    lanes: list[dict[str, Any]],
    resolution_content: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(resolution_content or {})
    normalized["type"] = "lane_graph"
    normalized.setdefault("goal", summary)
    normalized["lanes"] = lanes
    return normalized


def _normalize_verdict_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    decision = str(normalized.get("decision") or "").strip()
    rationale = str(normalized.get("rationale") or "").strip()
    if not decision or not rationale:
        raise PeerChatError(
            "invalid_structured_escalation",
            "verdict payload requires decision and rationale",
        )
    normalized["resolution_content"] = {
        "type": "verdict",
        "decision": decision,
        "rationale": rationale,
    }
    return normalized
