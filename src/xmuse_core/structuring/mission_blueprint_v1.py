from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class MissionBlueprintStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class MissionBlueprintDecisionLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: str
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        return _require_non_empty(value, "decision")

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, value: list[str]) -> list[str]:
        return _validate_text_list(value, "source_refs")


class MissionBlueprintV1(BaseModel):
    """Immutable mission blueprint artifact produced by deliberation freeze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["mission_blueprint.v1"] = "mission_blueprint.v1"
    blueprint_id: str
    conversation_id: str
    revision: int
    goal: str
    scope: list[str]
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    acceptance_contracts: list[str]
    repo_areas: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    decision_log: list[MissionBlueprintDecisionLogEntry] = Field(default_factory=list)
    source_refs: list[str]
    status: MissionBlueprintStatus
    approved_by: list[str] = Field(default_factory=list)

    @field_validator("blueprint_id", "conversation_id", "goal")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("revision")
    @classmethod
    def _validate_revision(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("revision must be >= 1")
        return value

    @field_validator("scope", "acceptance_contracts", "source_refs")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        field_name = info.field_name or "field"
        cleaned = _validate_text_list(value, field_name)
        if not cleaned:
            raise ValueError(f"{field_name} must contain at least one item")
        return cleaned

    @field_validator("constraints", "non_goals", "repo_areas", "open_questions", "approved_by")
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _validate_text_list(value, info.field_name or "field")

    def stable_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def render_mission_blueprint_markdown(blueprint: MissionBlueprintV1) -> str:
    lines = [
        f"# Mission Blueprint {blueprint.blueprint_id} r{blueprint.revision}",
        "",
        f"Status: `{blueprint.status.value}`",
        f"Conversation: `{blueprint.conversation_id}`",
        "",
        "## Goal",
        "",
        blueprint.goal,
        "",
    ]
    _append_bullets(lines, "Scope", blueprint.scope)
    _append_bullets(lines, "Constraints", blueprint.constraints)
    _append_bullets(lines, "Non-Goals", blueprint.non_goals)
    _append_bullets(lines, "Acceptance Contracts", blueprint.acceptance_contracts)
    _append_bullets(lines, "Repo Areas", [f"`{area}`" for area in blueprint.repo_areas])
    _append_bullets(lines, "Open Questions", blueprint.open_questions)
    _append_decision_log(lines, blueprint.decision_log)
    _append_bullets(lines, "Source Refs", [f"`{ref}`" for ref in blueprint.source_refs])
    _append_bullets(lines, "Approved By", [f"`{agent}`" for agent in blueprint.approved_by])
    return "\n".join(lines).rstrip()


def _append_bullets(lines: list[str], title: str, values: list[str]) -> None:
    lines.extend([f"## {title}", ""])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- None")
    lines.append("")


def _append_decision_log(
    lines: list[str],
    entries: list[MissionBlueprintDecisionLogEntry],
) -> None:
    lines.extend(["## Decision Log", ""])
    if entries:
        for entry in entries:
            refs = ", ".join(f"`{ref}`" for ref in entry.source_refs)
            suffix = f" (refs: {refs})" if refs else ""
            lines.append(f"- {entry.decision}{suffix}")
    else:
        lines.append("- None")
    lines.append("")


def _validate_text_list(values: list[str], field_name: str) -> list[str]:
    return [_require_non_empty(value, field_name) for value in values]


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value
