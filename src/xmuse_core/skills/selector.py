from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from xmuse_core.skills.models import SelectionReason, SkillDecision, SkillDescriptor

SELECTOR_VERSION = "xmuse.room_skill_selector/v1"
MAX_SELECTION_INPUT_CHARS = 65_536
MAX_SELECTION_INPUT_BYTES = 65_536
_EXPLICIT_MARKER = re.compile(r"\[skill:([a-z0-9]+(?:-[a-z0-9]+)*)\]")


class SkillSelectorError(ValueError):
    def __init__(self, message: str, *, code: str = "room_skill_explicit_marker_invalid"):
        super().__init__(message)
        self.code = code


def normalize_selection_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def select_skill(
    *,
    descriptors: Sequence[SkillDescriptor],
    catalog_sha256: str,
    participant_role: str,
    source_text: str,
) -> SkillDecision:
    if not isinstance(participant_role, str) or not isinstance(source_text, str):
        raise TypeError("participant_role and source_text must be strings")
    if len(source_text) > MAX_SELECTION_INPUT_CHARS:
        return _none(
            participant_role=participant_role,
            input_sha256=None,
            catalog_sha256=catalog_sha256,
            reason="input_too_large",
        )
    source_bytes = source_text.encode("utf-8")
    if len(source_bytes) > MAX_SELECTION_INPUT_BYTES:
        return _none(
            participant_role=participant_role,
            input_sha256=None,
            catalog_sha256=catalog_sha256,
            reason="input_too_large",
        )

    input_sha256 = _sha256(source_bytes)
    explicit_id, match_text = _parse_explicit_marker(source_text, descriptors)
    normalized_text = normalize_selection_text(match_text)
    normalized_role = normalize_selection_text(participant_role)
    candidates: list[tuple[int, int, str, SkillDescriptor, tuple[str, ...]]] = []

    for descriptor in descriptors:
        if explicit_id is not None and descriptor.skill_id != explicit_id:
            continue
        if normalized_role not in descriptor.roles:
            continue
        if any(term in normalized_text for term in descriptor.not_for):
            continue
        matched = tuple(sorted({term for term in descriptor.triggers if term in normalized_text}))
        if explicit_id is None and not matched:
            continue
        candidates.append(
            (
                -len(matched),
                -descriptor.priority,
                descriptor.skill_id,
                descriptor,
                matched,
            )
        )

    if not candidates:
        return _none(
            participant_role=participant_role,
            input_sha256=input_sha256,
            catalog_sha256=catalog_sha256,
            reason="no_match",
        )

    _, _, _, selected, matched_terms = min(candidates)
    return SkillDecision(
        selector_version=SELECTOR_VERSION,
        participant_role_snapshot=participant_role,
        selection_input_sha256=input_sha256,
        decision="selected",
        skill_id=selected.skill_id,
        skill_version=selected.version,
        skill_content_sha256=selected.content_sha256,
        skill_instructions_sha256=selected.instructions_sha256,
        catalog_sha256=catalog_sha256,
        selection_reason="explicit" if explicit_id is not None else "trigger",
        matched_terms=matched_terms,
    )


def _parse_explicit_marker(
    source_text: str,
    descriptors: Sequence[SkillDescriptor],
) -> tuple[str | None, str]:
    marker_occurrences = source_text.count("[skill:")
    lines = source_text.splitlines()
    first_nonempty_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    first_nonempty = lines[first_nonempty_index] if first_nonempty_index is not None else None
    match = _EXPLICIT_MARKER.fullmatch(first_nonempty or "")
    if marker_occurrences == 0:
        return None, source_text
    if marker_occurrences != 1 or match is None:
        raise SkillSelectorError("skill marker must be the exact first non-empty line")
    skill_id = match.group(1)
    if all(item.skill_id != skill_id for item in descriptors):
        raise SkillSelectorError(f"unknown skill marker: {skill_id}")
    assert first_nonempty_index is not None
    match_text = "\n".join(lines[:first_nonempty_index] + lines[first_nonempty_index + 1 :])
    return skill_id, match_text


def _none(
    *,
    participant_role: str,
    input_sha256: str | None,
    catalog_sha256: str,
    reason: SelectionReason,
) -> SkillDecision:
    return SkillDecision(
        selector_version=SELECTOR_VERSION,
        participant_role_snapshot=participant_role,
        selection_input_sha256=input_sha256,
        decision="none",
        skill_id=None,
        skill_version=None,
        skill_content_sha256=None,
        skill_instructions_sha256=None,
        catalog_sha256=catalog_sha256,
        selection_reason=reason,
        matched_terms=(),
    )


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
