from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED_HANDOFF_FIELDS = (
    "what",
    "why",
    "tradeoffs",
    "open_questions",
    "next_action",
    "evidence_refs",
)

_FIELD_ALIASES = {
    "what": ("what",),
    "why": ("why",),
    "tradeoffs": ("tradeoffs", "tradeoff"),
    "open_questions": ("open questions", "open question", "open_questions"),
    "next_action": ("next action", "next_action"),
    "evidence_refs": ("evidence refs", "evidence ref", "evidence_refs", "evidence"),
}

_HANDOFF_TRIGGER_RE = re.compile(
    r"\b(review|verify|handoff|take over|continue|execute|implement|patch|"
    r"review_request|交给|请\s*review|请验证|请执行|帮我确认)\b",
    re.IGNORECASE,
)
_FIELD_LABEL_RE = re.compile(
    r"(?<![\w])(?P<label>"
    + "|".join(
        re.escape(alias)
        for aliases in _FIELD_ALIASES.values()
        for alias in sorted(aliases, key=len, reverse=True)
    )
    + r")\s*:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HandoffAssessment:
    requires_envelope: bool
    fields: dict[str, str] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    route_kind: str = "mention"

    @property
    def is_complete(self) -> bool:
        return self.requires_envelope and not self.missing_fields

    def model_dump(self) -> dict[str, object]:
        return {
            "requires_envelope": self.requires_envelope,
            "fields": dict(self.fields),
            "missing_fields": list(self.missing_fields),
            "route_kind": self.route_kind,
            "is_complete": self.is_complete,
        }


def build_handoff_envelope(
    assessment: HandoffAssessment,
    *,
    conversation_id: str,
    origin_message_id: str,
    source_kind: str,
    author_participant_id: str | None,
    target_participant_id: str,
    target_role: str,
    source_refs: list[str] | tuple[str, ...],
    task_id: str | None = None,
    source_message_id: str | None = None,
    source_inbox_item_id: str | None = None,
    input_parts: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    artifact_refs: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    fields = dict(assessment.fields)
    source_refs_list = list(source_refs)
    return {
        "type": "natural_handoff",
        "schema_version": "xmuse-natural-handoff-v1",
        "task_id": task_id,
        "conversation_id": conversation_id,
        "origin_message_id": origin_message_id,
        "source_message_id": source_message_id or origin_message_id,
        "source_inbox_item_id": source_inbox_item_id,
        "source_kind": source_kind,
        "author_participant_id": author_participant_id,
        "source_participant_id": author_participant_id,
        "target_participant_id": target_participant_id,
        "target_participant_ids": [target_participant_id],
        "target_role": target_role,
        "intent": assessment.route_kind,
        "route_kind": assessment.route_kind,
        "requires_envelope": assessment.requires_envelope,
        "is_complete": assessment.is_complete,
        "missing_fields": list(assessment.missing_fields),
        "input_parts": [dict(item) for item in input_parts],
        "artifact_refs": list(artifact_refs),
        "what": fields.get("what"),
        "why": fields.get("why"),
        "tradeoffs": fields.get("tradeoffs"),
        "open_questions": fields.get("open_questions"),
        "next_action": fields.get("next_action"),
        "evidence_refs": _canonical_evidence_refs(
            fields.get("evidence_refs"),
            source_refs=source_refs_list,
        ),
        "fields": fields,
        "source_refs": source_refs_list,
    }


def assess_natural_handoff(content: str, *, target_role: str) -> HandoffAssessment:
    if not _requires_handoff_envelope(content, target_role=target_role):
        return HandoffAssessment(requires_envelope=False)
    fields = _extract_handoff_fields(content)
    missing = tuple(field for field in REQUIRED_HANDOFF_FIELDS if not fields.get(field))
    return HandoffAssessment(
        requires_envelope=True,
        fields=fields,
        missing_fields=missing,
        route_kind="review_request" if target_role == "review" else "handoff",
    )


def _requires_handoff_envelope(content: str, *, target_role: str) -> bool:
    role = target_role.strip().lower()
    if role in {"review", "execute"}:
        return True
    return bool(_HANDOFF_TRIGGER_RE.search(content))


def _extract_handoff_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    matches = list(_FIELD_LABEL_RE.finditer(content))
    for index, match in enumerate(matches):
        normalized_label = _normalize_label(match.group("label"))
        for field_name, aliases in _FIELD_ALIASES.items():
            if normalized_label in aliases:
                end = (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(content)
                )
                clean_value = content[match.end() : end].strip()
                if clean_value:
                    fields[field_name] = clean_value
                break
    return fields


def _normalize_label(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"^[-*>\s]+", "", text)
    return re.sub(r"[\s_-]+", " ", text)


def _canonical_evidence_refs(
    raw_refs: str | None,
    *,
    source_refs: list[str],
) -> list[str]:
    refs = list(source_refs)
    if raw_refs:
        for item in re.split(r"[\n,]+", raw_refs):
            ref = item.strip().strip("-*")
            if ref and ref not in refs:
                refs.append(ref)
    return refs
