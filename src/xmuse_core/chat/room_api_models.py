"""HTTP request contracts used by the default Room product."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.providers.models import ProviderId, ProviderProfileId


def strip_required_string(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def strip_optional_string(value: object) -> object:
    if value is None or not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


class ParticipantInit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=64)
    provider_id: ProviderId | None = None
    profile_id: ProviderProfileId | None = None
    cli_kind: Literal["codex"] | None = None
    model: str | None = Field(default=None, max_length=200)
    role_template_id: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("role", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return strip_required_string(value)

    @field_validator(
        "provider_id",
        "profile_id",
        "model",
        "role_template_id",
        "display_name",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return strip_optional_string(value)


class RoomConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    roster_template_id: str | None = Field(default=None, max_length=200)
    initial_participants: list[ParticipantInit] | None = Field(
        default=None,
        min_length=1,
        max_length=8,
    )

    @field_validator("title", mode="before")
    @classmethod
    def _strip_room_title(cls, value: object) -> object:
        return strip_required_string(value)

    @field_validator("client_request_id", "roster_template_id", mode="before")
    @classmethod
    def _strip_room_optional_text(cls, value: object) -> object:
        return strip_optional_string(value)


class ThreadMessageCreate(BaseModel):
    message: str = Field(min_length=1)
    client_request_id: str | None = None


class RoomObservationControlRequest(BaseModel):
    client_action_id: str = Field(min_length=1)
    expected_state: Literal[
        "active", "cancel_requested", "cancel_pending", "cancelled", "exhausted"
    ]
    expected_attempt_count: int = Field(ge=0)
    expected_control_seq: int = Field(ge=0)


class RoomRuntimeRecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    expected_incident_id: str = Field(min_length=1, max_length=200)

    @field_validator("client_action_id", "expected_incident_id", mode="before")
    @classmethod
    def _strip_runtime_recover_text(cls, value: object) -> object:
        return strip_required_string(value)


class RoomMemoryRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    expected_incident_id: str = Field(min_length=1, max_length=200)

    @field_validator("client_action_id", "expected_incident_id", mode="before")
    @classmethod
    def _strip_memory_rebuild_text(cls, value: object) -> object:
        return strip_required_string(value)


class RoomExecutionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    mode: Literal["manual", "consensus"]
    expected_revision: int = Field(ge=0)

    @field_validator("client_action_id", mode="before")
    @classmethod
    def _strip_execution_policy_text(cls, value: object) -> object:
        return strip_required_string(value)


class RoomExecutionCandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    decision: Literal["execute", "reject"]
    expected_candidate_digest: str = Field(min_length=1, max_length=200)
    expected_candidate_revision: int = Field(ge=0)
    expected_policy_revision: int = Field(ge=0)

    @field_validator("client_action_id", "expected_candidate_digest", mode="before")
    @classmethod
    def _strip_execution_decision_text(cls, value: object) -> object:
        return strip_required_string(value)


class RoomExecutionRunCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    expected_run_state: Literal[
        "requested",
        "preparing",
        "staging",
        "verifying",
        "ready_to_promote",
        "cancel_requested",
        "cancel_pending",
    ]
    expected_run_revision: int = Field(ge=0)

    @field_validator("client_action_id", mode="before")
    @classmethod
    def _strip_execution_cancel_text(cls, value: object) -> object:
        return strip_required_string(value)


class RoomMemoryCandidateResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]
    expected_digest: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)

    @field_validator("client_action_id", "expected_digest", mode="before")
    @classmethod
    def _strip_memory_resolve_text(cls, value: object) -> object:
        return strip_required_string(value)
