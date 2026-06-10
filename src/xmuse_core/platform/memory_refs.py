from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, model_validator


class MemoryScope(StrEnum):
    CONVERSATION = "conversation"
    FEATURE = "feature"
    PEER = "peer"
    GLOBAL = "global"


class MemoryCategory(StrEnum):
    CONVERSATION_SUMMARY = "conversation_summary"
    BLUEPRINT_DECISION = "blueprint_decision"
    FEATURE_HISTORY = "feature_history"
    REVIEW_REWORK_LESSON = "review_rework_lesson"
    PEER_LESSON = "peer_lesson"
    PLATFORM_LESSON = "platform_lesson"


class MemoryRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MemoryScope
    category: MemoryCategory
    session_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    conversation_id: str | None = None
    feature_id: str | None = None
    participant_id: str | None = None
    primary_evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryRef:
        _validate_scope_fields(
            scope=self.scope,
            conversation_id=self.conversation_id,
            feature_id=self.feature_id,
            participant_id=self.participant_id,
            label="memory refs",
        )
        self.primary_evidence_refs = _clean_refs(self.primary_evidence_refs)
        return self

    @computed_field(return_type=str)  # type: ignore[prop-decorator]
    @property
    def uri(self) -> str:
        if self.scope == MemoryScope.CONVERSATION:
            return f"memoryos://conversation/{self.conversation_id}/{self.session_id}"
        if self.scope == MemoryScope.FEATURE:
            return (
                f"memoryos://feature/{self.conversation_id}/{self.feature_id}/{self.session_id}"
            )
        if self.scope == MemoryScope.PEER:
            base = f"memoryos://peer/{self.conversation_id}/{self.participant_id}"
            if self.feature_id:
                base = f"{base}/{self.feature_id}"
            return f"{base}/{self.session_id}"
        return f"memoryos://global/{self.session_id}"


class MemoryLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MemoryScope
    category: MemoryCategory
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    conversation_id: str | None = None
    feature_id: str | None = None
    participant_id: str | None = None
    source_lane_id: str | None = None
    primary_evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryLesson:
        _validate_scope_fields(
            scope=self.scope,
            conversation_id=self.conversation_id,
            feature_id=self.feature_id,
            participant_id=self.participant_id,
            label="memory refs",
        )
        self.primary_evidence_refs = _clean_refs(self.primary_evidence_refs)
        return self


class MemoryOSStoreClient(Protocol):
    async def create_session(self, title: str) -> str | None: ...
    async def ingest(self, session_id: str, role: str, content: str) -> None: ...
    async def build_context(self, session_id: str, task: str, budget: int = 4096) -> str: ...


class MemoryOSStoreAdapter:
    def __init__(self, client: MemoryOSStoreClient) -> None:
        self._client = client
        self._session_ids_by_scope: dict[str, str] = {}

    async def remember(
        self,
        lesson: MemoryLesson,
        *,
        existing_ref: MemoryRef | None = None,
    ) -> MemoryRef:
        ref = existing_ref or await self._ensure_ref(lesson)
        metadata = dict(ref.metadata)
        metadata.update(dict(lesson.metadata))
        if lesson.source_lane_id:
            metadata.setdefault("source_lane_id", lesson.source_lane_id)
        ref = ref.model_copy(
            update={
                "scope": lesson.scope,
                "category": lesson.category,
                "title": lesson.title,
                "conversation_id": lesson.conversation_id,
                "feature_id": lesson.feature_id,
                "participant_id": lesson.participant_id,
                "primary_evidence_refs": list(lesson.primary_evidence_refs),
                "metadata": metadata,
            }
        )
        await self._client.ingest(ref.session_id, "assistant", _render_lesson(lesson))
        return ref

    async def build_context(
        self,
        refs: list[MemoryRef | dict[str, Any]],
        *,
        task: str,
        budget: int = 4096,
    ) -> str:
        parsed_refs = _coerce_memory_refs(refs)
        serialized_refs = _dedupe_memory_refs(
            [ref.model_dump(mode="json") for ref in parsed_refs],
            key="session_id",
        )
        if not serialized_refs:
            return ""
        per_ref_budget = max(1, budget // len(serialized_refs))
        sections: list[str] = []
        for payload in serialized_refs:
            ref = MemoryRef.model_validate({k: v for k, v in payload.items() if k != "uri"})
            context = (
                await self._client.build_context(ref.session_id, task, per_ref_budget)
            ).strip()
            if context:
                sections.append(f"## {ref.title}\n\n{context}")
        return "\n\n".join(sections)

    async def _ensure_ref(self, lesson: MemoryLesson) -> MemoryRef:
        scope_key = _scope_key(
            scope=lesson.scope,
            conversation_id=lesson.conversation_id,
            feature_id=lesson.feature_id,
            participant_id=lesson.participant_id,
        )
        session_id = self._session_ids_by_scope.get(scope_key)
        if session_id is None:
            session_id = await self._client.create_session(_session_title(lesson))
            if not session_id:
                raise RuntimeError(f"memoryos create_session returned empty for {scope_key}")
            self._session_ids_by_scope[scope_key] = session_id
        return MemoryRef(
            scope=lesson.scope,
            category=lesson.category,
            session_id=session_id,
            title=lesson.title,
            conversation_id=lesson.conversation_id,
            feature_id=lesson.feature_id,
            participant_id=lesson.participant_id,
            primary_evidence_refs=list(lesson.primary_evidence_refs),
            metadata=_lesson_metadata(lesson),
        )


def serialize_memory_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in _coerce_memory_refs(value):
        refs.append(ref.model_dump(mode="json"))
    return refs


def _coerce_memory_refs(value: Any) -> list[MemoryRef]:
    if value is None:
        return []
    if isinstance(value, MemoryRef):
        return [value]
    if isinstance(value, dict):
        try:
            payload = dict(value)
            payload.pop("uri", None)
            return [MemoryRef.model_validate(payload)]
        except ValidationError:
            return []
    if not isinstance(value, list):
        return []
    refs: list[MemoryRef] = []
    for item in value:
        refs.extend(_coerce_memory_refs(item))
    return refs


def _scope_key(
    *,
    scope: MemoryScope,
    conversation_id: str | None,
    feature_id: str | None,
    participant_id: str | None,
) -> str:
    parts = [scope.value, conversation_id or "-", feature_id or "-", participant_id or "-"]
    return ":".join(parts)


def _session_title(lesson: MemoryLesson) -> str:
    if lesson.scope == MemoryScope.CONVERSATION:
        return f"xmuse-memory:conversation:{lesson.conversation_id}"
    if lesson.scope == MemoryScope.FEATURE:
        return f"xmuse-memory:feature:{lesson.conversation_id}:{lesson.feature_id}"
    if lesson.scope == MemoryScope.PEER:
        base = f"xmuse-memory:peer:{lesson.conversation_id}:{lesson.participant_id}"
        if lesson.feature_id:
            base = f"{base}:{lesson.feature_id}"
        return base
    return "xmuse-memory:global:platform"


def _render_lesson(lesson: MemoryLesson) -> str:
    lines = [
        lesson.title,
        f"Category: {lesson.category.value}",
        f"Summary: {lesson.summary}",
    ]
    if lesson.primary_evidence_refs:
        lines.append("Primary evidence refs:")
        lines.extend(f"- {ref}" for ref in lesson.primary_evidence_refs)
    return "\n".join(lines)


def _lesson_metadata(lesson: MemoryLesson) -> dict[str, Any]:
    metadata = dict(lesson.metadata)
    if lesson.source_lane_id:
        metadata.setdefault("source_lane_id", lesson.source_lane_id)
    return metadata


def _validate_scope_fields(
    *,
    scope: MemoryScope,
    conversation_id: str | None,
    feature_id: str | None,
    participant_id: str | None,
    label: str,
) -> None:
    if scope == MemoryScope.CONVERSATION:
        if not _has_text(conversation_id):
            raise ValueError(f"conversation {label} require conversation_id")
        if _has_text(feature_id) or _has_text(participant_id):
            raise ValueError(
                f"conversation {label} cannot include feature_id or participant_id"
            )
        return
    if scope == MemoryScope.FEATURE:
        if not _has_text(conversation_id) or not _has_text(feature_id):
            raise ValueError(f"feature {label} require conversation_id and feature_id")
        if _has_text(participant_id):
            raise ValueError(f"feature {label} cannot include participant_id")
        return
    if scope == MemoryScope.PEER:
        if not _has_text(conversation_id) or not _has_text(participant_id):
            raise ValueError(f"peer {label} require conversation_id and participant_id")
        return
    if any(_has_text(value) for value in (conversation_id, feature_id, participant_id)):
        raise ValueError(
            f"global {label} cannot include conversation_id, feature_id, or participant_id"
        )


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _clean_refs(value: list[str]) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe_memory_refs(refs: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        value = ref.get(key)
        if not isinstance(value, str) or value in seen:
            continue
        seen.add(value)
        deduped.append(ref)
    return deduped
