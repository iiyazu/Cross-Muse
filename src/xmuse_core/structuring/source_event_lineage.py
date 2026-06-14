from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceEventProofLevel = Literal["contract_proof", "opt_in_live_proof", "manual_gap"]


class BlueprintSourceEventLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: str
    participant_id: str
    god_id: str
    proof_level: SourceEventProofLevel
    source_authority: str
    provider_response_artifact_ref: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    target_participant_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)

    @field_validator(
        "event_id",
        "event_type",
        "participant_id",
        "god_id",
        "source_authority",
    )
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "provider_response_artifact_ref",
        "binding_revision",
        "account_ref",
        "cli_command",
        "model",
        "variant",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("target_participant_ids", "source_refs", "forbidden_claims")
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


def _require_non_empty(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must be non-empty")
    return stripped
