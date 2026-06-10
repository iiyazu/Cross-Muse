from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProposalStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ResolutionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class StructuredEscalationTarget(StrEnum):
    MESSAGE = "message"
    MISSION_BLUEPRINT = "mission_blueprint"
    PROPOSAL = "proposal"
    FEATURE_PLAN = "feature_plan"
    LANE_GRAPH = "lane_graph"
    VERDICT = "verdict"


class Conversation(BaseModel):
    id: str
    title: str
    created_at: str


class ChatMessage(BaseModel):
    id: str
    conversation_id: str
    author: str
    role: str
    content: str
    created_at: str
    envelope_type: str | None = None
    envelope_json: dict[str, Any] | None = None
    mentions: list[str] = Field(default_factory=list)
    reply_to_message_id: str | None = None


class ChatCard(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _normalize_contract_card(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        intent_id = data.get("intent_id")
        if isinstance(intent_id, str) and intent_id:
            data.setdefault("id", f"card_{intent_id}")
            data.setdefault("source_id", intent_id)
        drilldown_href = _first_drilldown_href(data.get("drilldown_refs"))
        if drilldown_href:
            data.setdefault("href", drilldown_href)
            data.setdefault("api_href", drilldown_href)
        return data

    id: str
    conversation_id: str
    card_type: Literal[
        "proposal",
        "mission_blueprint",
        "lane_graph",
        "feature_plan",
        "feature_graph_set",
        "blueprint_execution_started",
        "feature_plan_ready",
        "lane_graph_ready",
        "lane_blocked",
        "run_progress",
        "takeover_requested",
        "run_takeover",
        "run_terminal",
        "health_summary",
        "worklist_summary",
        "review_verdict",
        "takeover",
        "peer_request",
        "peer_result",
    ]
    source_id: str
    title: str
    summary: str
    status: str
    href: str
    api_href: str
    created_at: str
    counts: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTimelineItem(BaseModel):
    kind: Literal["message", "card"]
    created_at: str
    message: ChatMessage | None = None
    card: ChatCard | None = None


class ChatInboxItem(BaseModel):
    id: str
    conversation_id: str
    target_participant_id: str | None = None
    target_role: str | None = None
    target_address: str
    sender_participant_id: str | None = None
    sender_address: str
    source_message_id: str
    item_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["unread", "claimed", "read", "failed"]
    claim_owner: str | None = None
    claimed_at: str | None = None
    claim_expires_at: str | None = None
    nudge_count: int = 0
    last_nudged_at: str | None = None
    responded_message_id: str | None = None
    failure_reason: str | None = None
    created_at: str
    updated_at: str


class Proposal(BaseModel):
    id: str
    conversation_id: str
    author: str
    proposal_type: str
    content: str
    references: list[str] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.OPEN
    created_at: str
    accepted_resolution_id: str | None = None


class StructuredResolution(BaseModel):
    id: str
    conversation_id: str
    version: int
    status: ResolutionStatus
    derived_from_proposal_ids: list[str] = Field(default_factory=list)
    approved_by: list[str] = Field(default_factory=list)
    approval_mode: str
    goal_summary: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    superseded_by_resolution_id: str | None = None


class StructuredEscalationDecision(BaseModel):
    target: StructuredEscalationTarget
    normalized_proposal_type: str
    normalized_content: str
    rationale: str


def _first_drilldown_href(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict):
            continue
        api_href = item.get("api_href")
        if isinstance(api_href, str) and api_href:
            return api_href
    return None
