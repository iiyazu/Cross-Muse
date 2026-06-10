from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_non_negative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


class ReviewGodTakeoverAction(StrEnum):
    REPAIR_AND_MERGE = "repair_and_merge"
    REQUEUE_WITH_CONTEXT = "requeue_with_context"
    ABANDON_LANE = "abandon_lane"
    SELF_CORRECTION_THEN_ABANDON = "self_correction_then_abandon"
    ESCALATE_TO_HUMAN_OR_OUTER_GOD = "escalate_to_human_or_outer_god"


class TakeoverAttemptContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    takeover_attempt_id: str
    retry_count: int = 0
    review_retry_count: int = 0

    @field_validator("takeover_attempt_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("retry_count", "review_retry_count")
    @classmethod
    def _validate_non_negative_int(cls, value: int, info: Any) -> int:
        return _require_non_negative_int(value, info.field_name)


class TakeoverLeaseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str
    lease_owner: str
    lease_expires_at: str | int | float

    @field_validator("lease_id", "lease_owner")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)


class TakeoverProjectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_revision: int
    projection_source: str | None = None

    @field_validator("projection_revision")
    @classmethod
    def _validate_non_negative_int(cls, value: int, info: Any) -> int:
        return _require_non_negative_int(value, info.field_name)

    @field_validator("projection_source")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)


class TakeoverLaneContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    lane_status: str
    graph_id: str | None = None
    conversation_id: str | None = None

    @field_validator("lane_id", "lane_status")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("graph_id", "conversation_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)


class TakeoverEvidenceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    takeover_context_ref: str
    lane_context_ref: str
    lane_context_hash: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    gate_report_refs: list[str] = Field(default_factory=list)
    review_history_refs: list[str] = Field(default_factory=list)
    worker_diff_refs: list[str] = Field(default_factory=list)

    @field_validator(
        "takeover_context_ref",
        "lane_context_ref",
        "lane_context_hash",
        "evidence_bundle_id",
        "evidence_bundle_hash",
    )
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("gate_report_refs", "review_history_refs", "worker_diff_refs")
    @classmethod
    def _validate_ref_lists(cls, value: list[str], info: Any) -> list[str]:
        return [_require_non_empty(item, info.field_name) for item in value]


class TakeoverGraphSetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_set_id: str
    graph_id: str | None = None

    @field_validator("graph_set_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("graph_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)


class TakeoverFeaturePlanContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_plan_id: str
    plan_feature_id: str

    @field_validator("feature_plan_id", "plan_feature_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)


class TakeoverMaxAttemptContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts_by_reason: dict[str, int]
    takeover_attempt_cap: int
    cooldown_seconds: int
    terminal_escalation_policy: str

    @field_validator("max_attempts_by_reason")
    @classmethod
    def _validate_max_attempts_by_reason(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("max_attempts_by_reason must not be empty")
        cleaned: dict[str, int] = {}
        for key, item in value.items():
            cleaned[_require_non_empty(key, "max_attempts_by_reason")] = (
                _require_non_negative_int(item, "max_attempts_by_reason")
            )
        return cleaned

    @field_validator("takeover_attempt_cap", "cooldown_seconds")
    @classmethod
    def _validate_non_negative_int(cls, value: int, info: Any) -> int:
        return _require_non_negative_int(value, info.field_name)

    @field_validator("terminal_escalation_policy")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)


class ReviewGodTakeoverContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "takeover-context-contract/v1"
    lane_id: str
    attempt: TakeoverAttemptContext
    lease: TakeoverLeaseContext
    projection: TakeoverProjectionContext
    lane: TakeoverLaneContext
    evidence: TakeoverEvidenceContext
    graph_set: TakeoverGraphSetContext
    feature_plan: TakeoverFeaturePlanContext
    max_attempt: TakeoverMaxAttemptContext

    @field_validator("schema_version", "lane_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_lane_identity(self) -> ReviewGodTakeoverContextContract:
        if self.lane.lane_id != self.lane_id:
            raise ValueError("lane.lane_id must match lane_id")
        return self


class ReviewGodTakeoverEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    takeover_context_ref: str
    change_ref: str
    verification_ref: str
    review_verdict_ref: str
    audit_event_ref: str
    chat_card_ref: str

    @field_validator(
        "takeover_context_ref",
        "change_ref",
        "verification_ref",
        "review_verdict_ref",
        "audit_event_ref",
        "chat_card_ref",
    )
    @classmethod
    def _validate_required_ref(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)


class ReviewGodTakeoverDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    action: ReviewGodTakeoverAction
    summary: str
    evidence: ReviewGodTakeoverEvidence
    abandon_reason: str | None = None
    impact: str | None = None
    replacement_required: bool | None = None
    feature_gap_implications: str | None = None
    review_self_correction: bool = False
    original_review_issue: str | None = None
    corrected_review_issue: str | None = None

    @field_validator("lane_id", "summary")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("abandon_reason", "impact", "feature_gap_implications")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action_alias(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() == "escalate":
            return ReviewGodTakeoverAction.ESCALATE_TO_HUMAN_OR_OUTER_GOD
        return value

    @model_validator(mode="after")
    def _validate_action_requirements(self) -> ReviewGodTakeoverDecision:
        if self.action in {
            ReviewGodTakeoverAction.ABANDON_LANE,
            ReviewGodTakeoverAction.SELF_CORRECTION_THEN_ABANDON,
        }:
            if self.abandon_reason is None:
                raise ValueError("abandon_reason is required for abandon actions")
            if self.impact is None:
                raise ValueError("impact is required for abandon actions")
            if self.replacement_required is None:
                raise ValueError("replacement_required is required for abandon actions")
            if self.feature_gap_implications is None:
                raise ValueError(
                    "feature_gap_implications is required for abandon actions"
                )
        if self.action is ReviewGodTakeoverAction.SELF_CORRECTION_THEN_ABANDON:
            if self.review_self_correction is not True:
                raise ValueError(
                    "review_self_correction must be true for self_correction_then_abandon"
                )
            if self.original_review_issue is None:
                raise ValueError(
                    "original_review_issue is required for self_correction_then_abandon"
                )
            if self.corrected_review_issue is None:
                raise ValueError(
                    "corrected_review_issue is required for self_correction_then_abandon"
                )
        return self
