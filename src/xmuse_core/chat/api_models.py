from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from xmuse_core.providers.models import ProviderId, ProviderProfileId


class ParticipantInit(BaseModel):
    role: str = Field(min_length=1)
    provider_id: ProviderId | None = None
    profile_id: ProviderProfileId | None = None
    cli_kind: Literal["codex", "opencode"] | None = None
    model: str | None = None
    role_template_id: str | None = None
    display_name: str | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)

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
        return _strip_optional_string(value)


class ProviderOverride(BaseModel):
    provider_id: ProviderId
    profile_id: ProviderProfileId
    cli_kind: Literal["codex", "opencode"]
    model: str = Field(min_length=1)
    template_slug: str | None = None
    display_name: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)

    @field_validator("template_slug", "display_name", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional_string(value)


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1)
    initial_participants: list[ParticipantInit] | None = None
    preset_id: str | None = None
    init_mode: Literal["deterministic", "proposal_then_approve"] = "proposal_then_approve"
    provider_overrides: dict[str, ProviderOverride] = Field(default_factory=dict)

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        return _strip_required_string(value)

    @field_validator("preset_id", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional_string(value)


class BootstrapProposalCreate(BaseModel):
    source: Literal["deterministic", "init_god"] = "deterministic"


class BootstrapApplyCreate(BaseModel):
    proposal_id: str = Field(min_length=1)

    @field_validator("proposal_id", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)


class CollaborationRequestCreate(BaseModel):
    goal: str = Field(min_length=1)
    initiator: str = Field(min_length=1)
    targets: list[str] = Field(min_length=1, max_length=3)
    callback_target: str = Field(min_length=1)
    question: str = Field(min_length=1)
    context_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    timeout_s: int = 480
    orchestration_mode: Literal["peer_consensus", "leader_assisted"] = "peer_consensus"


class CollaborationResponseCreate(BaseModel):
    target: str = Field(min_length=1)
    content: str = ""
    status: Literal["received", "timeout", "failed"] = "received"


class CollaborationBlockerCreate(BaseModel):
    issuer: str = Field(min_length=1)
    severity: Literal["info", "warning", "blocker", "veto"]
    reason: str = Field(min_length=1)
    affected_ref: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)
    blocks_dispatch: bool = True


class CollaborationBlockerResolve(BaseModel):
    resolved_by: str = Field(min_length=1)
    resolution_evidence: str = Field(min_length=1)


class CollaborationDispatchGateRequest(BaseModel):
    proposal_ref: str | None = None
    artifact_ref: str | None = None
    execute_confirmed: bool = False
    policy_allows_real_provider: bool = True


class DispatchClaimRequest(BaseModel):
    claimed_by: str = Field(min_length=1)

    @field_validator("claimed_by", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)


class DispatchDispatchedRequest(BaseModel):
    provider_run_ref: str = Field(min_length=1)
    dispatch_evidence: str = Field(min_length=1)

    @field_validator("provider_run_ref", "dispatch_evidence", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)


class DispatchFailedRequest(BaseModel):
    failure_reason: str = Field(min_length=1)

    @field_validator("failure_reason", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)


class RoleTemplateCreate(BaseModel):
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    provider_id: ProviderId | None = None
    profile_id: ProviderProfileId | None = None
    cli_kind: Literal["codex"] | None = None
    default_model: str = Field(min_length=1)

    @field_validator(
        "slug",
        "display_name",
        "prompt",
        "default_model",
        "provider_id",
        "profile_id",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        if value is None:
            return value
        return _strip_required_string(value)


class RoleTemplateUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    provider_id: ProviderId | None = None
    profile_id: ProviderProfileId | None = None
    cli_kind: Literal["codex"] | None = None
    default_model: str | None = Field(default=None, min_length=1)

    @field_validator(
        "display_name",
        "prompt",
        "default_model",
        "provider_id",
        "profile_id",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional_string(value)


class MessageCreate(BaseModel):
    author: str = Field(min_length=1)
    role: str = Field(min_length=1)
    content: str = Field(min_length=1)
    client_request_id: str | None = None


class ProposalCreate(BaseModel):
    author: str = Field(min_length=1)
    proposal_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    references: list[str] = Field(default_factory=list)


class ProposalApproval(BaseModel):
    approved_by: list[str] = Field(min_length=1)
    approval_mode: str = Field(min_length=1)
    goal_summary: str = Field(min_length=1)
    content: dict[str, Any] | None = None


class ThreadMessageCreate(BaseModel):
    message: str = Field(min_length=1)
    client_request_id: str | None = None


class PeerForkCreate(BaseModel):
    source_peer_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    model: str | None = None
    role_template_id: str | None = None
    display_name: str | None = None
    prompt_delta: str = Field(min_length=1)
    inherited_refs: list[str] = Field(default_factory=list)
    model_policy: dict[str, Any]
    feature_scope_id: str | None = None
    fork_reason: str = Field(min_length=1)

    @field_validator(
        "source_peer_id",
        "role",
        "prompt_delta",
        "fork_reason",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        return _strip_required_string(value)

    @field_validator(
        "model",
        "role_template_id",
        "display_name",
        "feature_scope_id",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional_string(value)


def _strip_required_string(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _strip_optional_string(value: object) -> object:
    if value is None or not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped
