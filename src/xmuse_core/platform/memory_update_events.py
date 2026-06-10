from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from xmuse_core.platform.memory_refs import (
    MemoryCategory,
    MemoryLesson,
    MemoryRef,
    MemoryScope,
    serialize_memory_refs,
)
from xmuse_core.platform.review_rework import classify_review_rework_lane

MemoryEventKind = Literal["planning", "review", "takeover"]


def build_memory_lesson_for_event(
    event: MemoryEventKind,
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None = None,
) -> MemoryLesson | None:
    if event == "planning":
        return build_planning_memory_lesson(lane)
    if event == "review":
        return build_review_memory_lesson(lane, xmuse_root=xmuse_root)
    return build_takeover_memory_lesson(lane, xmuse_root=xmuse_root)


def build_planning_memory_lesson(lane: dict[str, Any]) -> MemoryLesson | None:
    prompt = _text(lane.get("prompt"))
    if prompt is None:
        return None
    primary_refs = _dedupe(
        [
            "lane.prompt",
            *(_compact_text_items(lane.get("blueprint_refs"))[:4]),
            *(_primary_source_plan_ref(lane)),
            *(_criterion_refs(lane)),
        ]
    )
    if len(primary_refs) <= 1:
        return None
    scope = _lesson_scope_fields(lane)
    if scope is None:
        return None
    return MemoryLesson(
        scope=scope["scope"],
        category=MemoryCategory.FEATURE_HISTORY,
        title=_event_title("Planning", lane),
        summary=_planning_summary(lane, prompt=prompt),
        conversation_id=scope["conversation_id"],
        feature_id=scope["feature_id"],
        participant_id=scope["participant_id"],
        source_lane_id=_lane_id(lane),
        primary_evidence_refs=primary_refs,
        metadata={"memory_update_event": "planning"},
    )


def build_review_memory_lesson(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None = None,
) -> MemoryLesson | None:
    review_summary = _text(lane.get("review_summary"))
    review_verdict_id = _text(lane.get("review_verdict_id"))
    review_task_id = _text(lane.get("review_task_id"))
    if review_summary is None and review_verdict_id is None and review_task_id is None:
        return None
    primary_refs = _review_primary_evidence_refs(lane, xmuse_root=xmuse_root)
    if not primary_refs:
        return None
    scope = _lesson_scope_fields(lane, participant_fields=("review_peer_id",))
    if scope is None:
        return None
    summary = review_summary or _review_summary_fallback(lane)
    if summary is None:
        return None
    return MemoryLesson(
        scope=scope["scope"],
        category=MemoryCategory.REVIEW_REWORK_LESSON,
        title=_event_title("Review", lane),
        summary=summary,
        conversation_id=scope["conversation_id"],
        feature_id=scope["feature_id"],
        participant_id=scope["participant_id"],
        source_lane_id=_lane_id(lane),
        primary_evidence_refs=primary_refs,
        metadata={"memory_update_event": "review"},
    )


def build_takeover_memory_lesson(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None = None,
) -> MemoryLesson | None:
    if not _is_takeover_candidate(lane):
        return None
    primary_refs = _takeover_primary_evidence_refs(lane, xmuse_root=xmuse_root)
    if not primary_refs:
        return None
    scope = _lesson_scope_fields(
        lane,
        participant_fields=("execute_peer_id", "review_peer_id"),
    )
    if scope is None:
        return None
    summary = _takeover_summary(lane)
    if summary is None:
        return None
    return MemoryLesson(
        scope=scope["scope"],
        category=MemoryCategory.PEER_LESSON,
        title=_event_title("Takeover", lane),
        summary=summary,
        conversation_id=scope["conversation_id"],
        feature_id=scope["feature_id"],
        participant_id=scope["participant_id"],
        source_lane_id=_lane_id(lane),
        primary_evidence_refs=primary_refs,
        metadata={"memory_update_event": "takeover"},
    )


def find_matching_memory_ref(
    existing_refs: Any,
    lesson: MemoryLesson,
) -> MemoryRef | None:
    for payload in serialize_memory_refs(existing_refs):
        try:
            ref = MemoryRef.model_validate({k: v for k, v in payload.items() if k != "uri"})
        except Exception:
            continue
        if (
            ref.scope == lesson.scope
            and ref.category == lesson.category
            and ref.conversation_id == lesson.conversation_id
            and ref.feature_id == lesson.feature_id
            and ref.participant_id == lesson.participant_id
        ):
            return ref
    return None


def upsert_memory_ref(existing_refs: Any, ref: MemoryRef) -> list[dict[str, Any]]:
    serialized = serialize_memory_refs(existing_refs)
    updated = ref.model_dump(mode="json")
    for index, existing in enumerate(serialized):
        if _same_memory_slot(existing, updated):
            serialized[index] = updated
            return serialized
    serialized.append(updated)
    return serialized


def _review_primary_evidence_refs(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None,
) -> list[str]:
    refs: list[str] = []
    if _text(lane.get("review_summary")):
        refs.append("lane.review_summary")
    if _text(lane.get("review_verdict_id")):
        refs.append("lane.review_verdict_id")
    elif _text(lane.get("review_task_id")):
        refs.append("lane.review_task_id")
    alignment = classify_review_rework_lane(lane, xmuse_root=xmuse_root)
    refs.extend(str(ref) for ref in alignment.get("primary_evidence_refs", []))
    return _non_memory_refs(refs, lane)


def _takeover_primary_evidence_refs(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None,
) -> list[str]:
    refs: list[str] = []
    alignment = classify_review_rework_lane(lane, xmuse_root=xmuse_root)
    refs.extend(str(ref) for ref in alignment.get("primary_evidence_refs", []))
    for key in ("failure_reason", "review_summary", "merge_failure_reason"):
        if _text(lane.get(key)):
            refs.append(f"lane.{key}")
    return _non_memory_refs(refs, lane)


def _non_memory_refs(refs: list[str], lane: dict[str, Any]) -> list[str]:
    memory_uris = {
        str(ref.get("uri"))
        for ref in serialize_memory_refs(lane.get("memory_refs"))
        if isinstance(ref.get("uri"), str)
    }
    filtered = []
    for ref in refs:
        if not ref:
            continue
        if ref.startswith("memoryos://") or ref in memory_uris:
            continue
        filtered.append(ref)
    return _dedupe(filtered)


def _lesson_scope_fields(
    lane: dict[str, Any],
    *,
    participant_fields: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    conversation_id = _text(lane.get("conversation_id"))
    feature_id = _feature_scope_id(lane)
    participant_id = _first_text_value(lane, participant_fields)
    if participant_id and conversation_id:
        return {
            "scope": MemoryScope.PEER,
            "conversation_id": conversation_id,
            "feature_id": feature_id,
            "participant_id": participant_id,
        }
    if conversation_id and feature_id:
        return {
            "scope": MemoryScope.FEATURE,
            "conversation_id": conversation_id,
            "feature_id": feature_id,
            "participant_id": None,
        }
    if conversation_id:
        return {
            "scope": MemoryScope.CONVERSATION,
            "conversation_id": conversation_id,
            "feature_id": None,
            "participant_id": None,
        }
    return None


def _planning_summary(lane: dict[str, Any], *, prompt: str) -> str:
    parts = [prompt]
    criteria = _compact_text_items(lane.get("acceptance_criteria"))
    if criteria:
        parts.append("Acceptance criteria: " + "; ".join(criteria[:3]))
    refs = _compact_text_items(lane.get("blueprint_refs"))
    if refs:
        parts.append("Blueprint refs: " + ", ".join(refs[:3]))
    return " ".join(parts)


def _review_summary_fallback(lane: dict[str, Any]) -> str | None:
    decision = _text(lane.get("review_decision")) or _text(lane.get("status"))
    if decision is None:
        return None
    return f"Review decision: {decision}"


def _takeover_summary(lane: dict[str, Any]) -> str | None:
    parts: list[str] = []
    failure_reason = _text(lane.get("failure_reason"))
    if failure_reason:
        parts.append(f"Failure reason: {failure_reason}.")
    review_summary = _text(lane.get("review_summary"))
    if review_summary:
        parts.append(review_summary)
    retry_count = _int_or_zero(lane.get("retry_count"))
    review_retry_count = _int_or_zero(lane.get("review_retry_count"))
    if retry_count or review_retry_count:
        parts.append(
            f"Retry counters: execute={retry_count}, review={review_retry_count}."
        )
    if not parts:
        return None
    return " ".join(parts)


def _event_title(prefix: str, lane: dict[str, Any]) -> str:
    feature_title = (
        _text(lane.get("feature_title"))
        or _feature_scope_id(lane)
        or _lane_id(lane)
    )
    return f"{prefix} Memory: {feature_title}"


def _feature_scope_id(lane: dict[str, Any]) -> str | None:
    return _first_text_value(
        lane,
        (
            "feature_plan_feature_id",
            "plan_feature_id",
            "feature_scope_id",
            "feature_id",
        ),
    )


def _primary_source_plan_ref(lane: dict[str, Any]) -> list[str]:
    source_plan = _text(lane.get("source_plan"))
    return [source_plan] if source_plan else []


def _criterion_refs(lane: dict[str, Any]) -> list[str]:
    if _compact_text_items(lane.get("acceptance_criteria")):
        return ["lane.acceptance_criteria"]
    return []


def _compact_text_items(value: Any, *, max_items: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:max_items]:
        text = _text(item)
        if text:
            items.append(text)
    return items


def _is_takeover_candidate(lane: dict[str, Any]) -> bool:
    status = _text(lane.get("status"))
    return (
        _int_or_zero(lane.get("retry_count")) > 0
        or _int_or_zero(lane.get("review_retry_count")) > 0
        or bool(_text(lane.get("failure_reason")))
        or bool(_text(lane.get("merge_failure_reason")))
        or status in {"reworking", "exec_failed", "gate_failed", "failed"}
    )


def _same_memory_slot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("scope") == right.get("scope")
        and left.get("category") == right.get("category")
        and left.get("conversation_id") == right.get("conversation_id")
        and left.get("feature_id") == right.get("feature_id")
        and left.get("participant_id") == right.get("participant_id")
    )


def _first_text_value(data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _text(data.get(field))
        if value:
            return value
    return None


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("lane_id") or lane.get("id") or "unknown")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
