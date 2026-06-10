from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_COLLABORATION_TARGETS = 3
DEFAULT_COLLABORATION_TIMEOUT_S = 480


class CollaborationStatus(StrEnum):
    RUNNING = "running"
    PARTIAL = "partial"
    DONE = "done"
    TIMEOUT = "timeout"
    FAILED = "failed"


TERMINAL_COLLABORATION_STATUSES = {
    CollaborationStatus.DONE,
    CollaborationStatus.TIMEOUT,
    CollaborationStatus.FAILED,
}


class DispatchGateDecision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED_UNKNOWN_RUN = "blocked_unknown_run"
    BLOCKED_MISSING_PROPOSAL = "blocked_missing_proposal"
    BLOCKED_MISSING_ARTIFACT = "blocked_missing_artifact"
    BLOCKED_EXECUTE_NOT_CONFIRMED = "blocked_execute_not_confirmed"
    BLOCKED_ACTIVE_VETO = "blocked_active_veto"
    BLOCKED_POLICY = "blocked_policy"


class CollaborationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    run_id: str
    target: str = Field(min_length=1)
    content: str
    status: Literal["received", "timeout", "failed"]
    created_at: str


class CollaborationBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocker_id: str
    run_id: str
    conversation_id: str
    issuer: str = Field(min_length=1)
    severity: Literal["info", "warning", "blocker", "veto"]
    reason: str = Field(min_length=1)
    affected_ref: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)
    active: bool
    blocks_dispatch: bool
    resolution_evidence: str | None = None
    resolved_by: str | None = None
    created_at: str
    resolved_at: str | None = None


class CollaborationDispatchGateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    conversation_id: str
    decision: DispatchGateDecision
    proposal_ref: str | None = None
    artifact_ref: str | None = None
    execute_confirmed: bool
    policy_allows_real_provider: bool
    created_at: str


class CollaborationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    conversation_id: str
    goal: str = Field(min_length=1)
    orchestration_mode: Literal["peer_consensus", "leader_assisted"]
    status: CollaborationStatus
    initiator: str = Field(min_length=1)
    targets: list[str]
    callback_target: str = Field(min_length=1)
    question: str = Field(min_length=1)
    context_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    timeout_s: int = DEFAULT_COLLABORATION_TIMEOUT_S
    max_depth: int = 1
    current_depth: int = 0
    created_at: str
    updated_at: str
    responses: list[CollaborationResponse] = Field(default_factory=list)
    blockers: list[CollaborationBlocker] = Field(default_factory=list)
