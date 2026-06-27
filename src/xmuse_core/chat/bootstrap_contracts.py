from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CliKind = Literal["codex", "opencode", "a2a"]
ProviderIdLiteral = Literal["codex", "opencode", "a2a"]
ProposalSource = Literal["init_god", "deterministic"]


class BootstrapInitMode(StrEnum):
    DETERMINISTIC = "deterministic"
    PROPOSAL_THEN_APPROVE = "proposal_then_approve"


class BootstrapStatus(StrEnum):
    DRAFTING = "drafting"
    PROPOSAL_READY = "proposal_ready"
    PROPOSAL_FAILED = "proposal_failed"
    VALIDATION_FAILED = "validation_failed"
    APPLIED = "applied"
    BOOTSTRAPPED = "bootstrapped"
    DEGRADED = "degraded"


class LogicalPeerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)
    address_slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    template_slug: str = Field(min_length=1)
    provider_id: ProviderIdLiteral
    profile_id: str = Field(min_length=1)
    cli_kind: CliKind
    model: str = Field(min_length=1)

    @field_validator(
        "role", "address_slug", "display_name", "template_slug", "profile_id", "model",
        mode="before",
    )
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError(
                    "explicit model is required" if value == "" else "must not be blank"
                )
            return stripped
        return value

    @model_validator(mode="after")
    def _provider_matches_cli(self) -> LogicalPeerSpec:
        if self.provider_id != self.cli_kind:
            raise ValueError("provider_id must match cli_kind for groupchat bootstrap")
        return self


class LogicalForkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_role: Literal["init"] = "init"
    target_address_slug: str = Field(min_length=1)
    prompt_delta: str = Field(min_length=1)
    inherited_refs: list[str] = Field(default_factory=list)
    fork_reason: str = Field(min_length=1)


class PresetRoleSpec(LogicalPeerSpec):
    pass


class GroupchatPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset_id: str
    display_name: str
    description: str
    roles: list[PresetRoleSpec]
    allowed_overrides: list[Literal["provider", "model", "template", "display_name"]]


class BootstrapDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str
    conversation_id: str
    preset_id: str
    init_participant_id: str
    init_session_id: str
    requested_overrides: dict[str, Any] = Field(default_factory=dict)
    default_team: list[LogicalPeerSpec]
    status: BootstrapStatus
    created_at: str
    updated_at: str


class TeamPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    draft_id: str
    conversation_id: str
    source: ProposalSource
    peers: list[LogicalPeerSpec]
    fork_plan: list[LogicalForkSpec] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    validation_status: Literal["pending", "accepted", "rejected"] = "pending"

    @model_validator(mode="after")
    def _unique_identity(self) -> TeamPlanProposal:
        addresses = [peer.address_slug for peer in self.peers]
        names = [peer.display_name for peer in self.peers]
        if len(addresses) != len(set(addresses)):
            raise ValueError("address_slug must be unique within team proposal")
        if len(names) != len(set(names)):
            raise ValueError("display_name must be unique within team proposal")
        return self


class AppliedBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apply_id: str
    draft_id: str
    proposal_id: str
    conversation_id: str
    participants: list[str]
    durable_god_sessions: list[str]
    fork_records: list[str]
    status: Literal["bootstrapped", "degraded"]
    created_at: str


_AUTHORITY_ID_KEYS = {
    "participant_id", "god_session_id", "fork_id",
    "provider_session_id", "provider_binding_id", "binding_id",
}


def validate_logical_proposal_payload(payload: dict[str, Any]) -> TeamPlanProposal:
    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        raise ValueError(f"proposal payload contains authority ids: {sorted(forbidden)}")
    return TeamPlanProposal.model_validate(payload)


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(key for key in value if key in _AUTHORITY_ID_KEYS)
        for child in value.values():
            found.update(_find_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_keys(child))
    return found


def bootstrap_apply_id(conversation_id: str, proposal_id: str) -> str:
    return f"bootstrap-apply:{conversation_id}:{proposal_id}"


def bootstrap_fork_idempotency_key(
    conversation_id: str, proposal_id: str, source_peer_id: str, target_address_slug: str,
) -> str:
    return f"bootstrap-fork:{conversation_id}:{proposal_id}:{source_peer_id}:{target_address_slug}"


def deterministic_draft_id(conversation_id: str) -> str:
    return f"bootstrap-draft:{conversation_id}"


def deterministic_proposal_id(conversation_id: str, preset_id: str) -> str:
    return f"bootstrap-proposal:{conversation_id}:{preset_id}"


def resolve_groupchat_preset(preset_id: str | None = None) -> GroupchatPreset:
    key = preset_id or "architect-review-execute"
    try:
        return _PRESETS[key]
    except KeyError as exc:
        raise ValueError(f"unknown groupchat preset: {key}") from exc


def preset_to_logical_team(preset: GroupchatPreset) -> list[LogicalPeerSpec]:
    return [LogicalPeerSpec.model_validate(role.model_dump()) for role in preset.roles]


_PRESETS: dict[str, GroupchatPreset] = {
    "architect-review-execute": GroupchatPreset(
        preset_id="architect-review-execute",
        display_name="Architect / Review / Execute",
        description="Default team for medium-to-large coding tasks.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(
                role="architect", address_slug="architect",
                display_name="architect-god", template_slug="architect",
                provider_id="codex", profile_id="god",
                cli_kind="codex", model="gpt-5.5",
            ),
            PresetRoleSpec(
                role="review", address_slug="review",
                display_name="review-god", template_slug="review",
                provider_id="codex", profile_id="review",
                cli_kind="codex", model="gpt-5.5",
            ),
            PresetRoleSpec(
                role="execute", address_slug="execute",
                display_name="execute-god", template_slug="execute",
                provider_id="codex", profile_id="worker",
                cli_kind="codex", model="gpt-5.5",
            ),
        ],
    ),
    "architect-review": GroupchatPreset(
        preset_id="architect-review",
        display_name="Architect / Review",
        description="Plan and review without executor.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(
                role="architect", address_slug="architect",
                display_name="architect-god", template_slug="architect",
                provider_id="codex", profile_id="god",
                cli_kind="codex", model="gpt-5.5",
            ),
            PresetRoleSpec(
                role="review", address_slug="review",
                display_name="review-god", template_slug="review",
                provider_id="codex", profile_id="review",
                cli_kind="codex", model="gpt-5.5",
            ),
        ],
    ),
    "solo-architect": GroupchatPreset(
        preset_id="solo-architect",
        display_name="Solo Architect",
        description="Lightweight requirements clarification.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(
                role="architect", address_slug="architect",
                display_name="architect-god", template_slug="architect",
                provider_id="codex", profile_id="god",
                cli_kind="codex", model="gpt-5.5",
            ),
        ],
    ),
    "debug-light": GroupchatPreset(
        preset_id="debug-light",
        display_name="Debug Light",
        description="Low-cost bootstrap/runtime smoke team.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(
                role="architect", address_slug="architect",
                display_name="architect-god", template_slug="architect",
                provider_id="codex", profile_id="god",
                cli_kind="codex", model="gpt-5.4-mini",
            ),
            PresetRoleSpec(
                role="review", address_slug="review",
                display_name="review-god", template_slug="review",
                provider_id="codex", profile_id="review",
                cli_kind="codex", model="gpt-5.4-mini",
            ),
        ],
    ),
}
