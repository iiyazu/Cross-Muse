from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunTerminalStatus(StrEnum):
    """Authoritative run-level terminal outcomes."""

    MERGED = "merged"
    TERMINATED = "terminated"
    BLOCKED_FOR_INPUT = "blocked_for_input"
    IN_PROGRESS = "in_progress"


class RunTerminalAggregation(BaseModel):
    """Result of a run-level terminal status computation."""

    graph_id: str
    status: RunTerminalStatus
    open_lane_lineages: list[str] = Field(default_factory=list)
    failed_lineages: list[str] = Field(default_factory=list)
    open_final_action_holds: list[str] = Field(default_factory=list)
    open_clarification_ids: list[str] = Field(default_factory=list)
    basis: str = ""


class ReviewDecision(StrEnum):
    MERGE = "merge"
    REWORK = "rework"
    PATCH_FORWARD = "patch-forward"
    TERMINATE = "terminate"


class ReviewVerdict(BaseModel):
    id: str
    lane_id: str
    decision: ReviewDecision
    status: str = "finalized"
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    patch_instructions: str | None = None
    terminate_reason: str | None = None
    task_id: str | None = None
    created_at: str | None = None


class ReviewTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERDICT_EMITTED = "verdict_emitted"
    FAILED_CLASSIFIED = "failed_classified"
    INTERRUPTED_RETRYABLE = "interrupted_retryable"
    CANCELLED = "cancelled"


class StructuredEvidenceBundle(BaseModel):
    """Cross-run handoff bundle for self-evolution planning."""

    bundle_id: str
    source_run_id: str
    source_resolution_id: str | None = None
    selection_policy_id: str
    selection_policy_version: str
    summary: str
    run_terminal_status: RunTerminalStatus
    verdict_refs: list[str] = Field(default_factory=list)
    gate_report_refs: list[str] = Field(default_factory=list)
    lineage_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    signal_refs: list[str] = Field(default_factory=list)
    primary_refs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class ReviewTask(BaseModel):
    """A unit of review work queued for Review GOD."""

    task_id: str
    lane_id: str
    graph_id: str | None = None
    resolution_id: str | None = None
    lane_prompt: str = ""
    gate_report_ref: str | None = None
    status: ReviewTaskStatus = ReviewTaskStatus.PENDING
    verdict_id: str | None = None
    review_attempt_id: str | None = None
    runner_id: str | None = None
    started_at: str | None = None
    provider_runtime: str | None = None
    provider_model: str | None = None
    spawn_log_refs: list[str] = Field(default_factory=list)
    terminal_reason: str | None = None
    created_at: str
    updated_at: str | None = None
