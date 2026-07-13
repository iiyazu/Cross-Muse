from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SelectionReason = Literal["explicit", "trigger", "no_match", "input_too_large"]


@dataclass(frozen=True)
class SkillDecision:
    selector_version: str
    participant_role_snapshot: str
    selection_input_sha256: str | None
    decision: Literal["selected", "none"]
    skill_id: str | None
    skill_version: str | None
    skill_content_sha256: str | None
    skill_instructions_sha256: str | None
    catalog_sha256: str
    selection_reason: SelectionReason
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class SkillDecisionRecord:
    attempt_id: str
    selection: SkillDecision
    context_payload_sha256: str | None
    context_submitted_at: str | None


@dataclass(frozen=True)
class RoomSkillActivation:
    skill_id: str
    version: str
    content_sha256: str
    instructions_sha256: str
    catalog_sha256: str
    selection_reason: str
    matched_terms: tuple[str, ...]
    instructions: str


@dataclass(frozen=True)
class SkillDescriptor:
    skill_id: str
    version: str
    description: str
    content_sha256: str
    instructions_sha256: str
    roles: tuple[str, ...]
    triggers: tuple[str, ...]
    not_for: tuple[str, ...]
    priority: int
    _path: Path = field(repr=False, compare=False)
