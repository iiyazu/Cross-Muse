from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlanningEventStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    ACKED = "acked"


class PlanningEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    planning_run_id: str | None = None
    conversation_id: str
    blueprint_ref: str
    dedupe_key: str
    idempotency_key: str
    status: PlanningEventStatus = PlanningEventStatus.QUEUED
    attempt: int = 0
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    available_at: str | None = None
    last_error_reason: str | None = None
    lease_ttl_seconds: int | None = None
    recovered_from_stale_lease: bool = False

    @field_validator(
        "event_id",
        "event_type",
        "planning_run_id",
        "conversation_id",
        "blueprint_ref",
        "dedupe_key",
        "idempotency_key",
        "lease_owner",
        "lease_expires_at",
        "created_at",
        "updated_at",
        "available_at",
        "last_error_reason",
    )
    @classmethod
    def _validate_event_text_fields(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)

    @field_validator("attempt", "lease_ttl_seconds")
    @classmethod
    def _validate_event_non_negative_ints(
        cls,
        value: int | None,
        info: Any,
    ) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_event_state(self) -> PlanningEvent:
        if self.event_type != "blueprint.approved" and self.planning_run_id is None:
            raise ValueError(
                "planning_run_id is required for events after blueprint.approved"
            )
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError(
                "lease_owner and lease_expires_at must both be set or both be null"
            )
        if self.status is PlanningEventStatus.CLAIMED and self.lease_owner is None:
            raise ValueError("claimed events require an active lease")
        if self.status is not PlanningEventStatus.CLAIMED and self.lease_owner is not None:
            raise ValueError("only claimed events may carry an active lease")
        return self


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value
