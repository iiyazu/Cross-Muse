from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SourceType = Literal[
    "message",
    "card",
    "proposal",
    "blueprint",
    "verdict",
    "artifact",
]


class ChatMemoryScope(StrEnum):
    CONVERSATION_SHARED = "conversation_shared"
    BLUEPRINT_DECISION = "blueprint_decision"
    PARTICIPANT = "participant"
    UNRESOLVED_THREAD = "unresolved_thread"
    CROSS_RESTART_RECALL = "cross_restart_recall"


class ChatMemoryCategory(StrEnum):
    CONVERSATION_SUMMARY = "conversation_summary"
    BLUEPRINT_VERSION = "blueprint_version"
    DECISION_RATIONALE = "decision_rationale"
    FEATURE_PLAN_REF = "feature_plan_ref"
    PARTICIPANT_PREFERENCE = "participant_preference"
    PARTICIPANT_HISTORY = "participant_history"
    THREAD_QUESTION = "thread_question"
    THREAD_DECISION_PENDING = "thread_decision_pending"
    RECOVERY_CHECKPOINT = "recovery_checkpoint"
    SESSION_BOUNDARY = "session_boundary"


_SCOPE_CATEGORY_MAP: dict[ChatMemoryScope, set[ChatMemoryCategory]] = {
    ChatMemoryScope.CONVERSATION_SHARED: {
        ChatMemoryCategory.CONVERSATION_SUMMARY,
        ChatMemoryCategory.SESSION_BOUNDARY,
    },
    ChatMemoryScope.BLUEPRINT_DECISION: {
        ChatMemoryCategory.BLUEPRINT_VERSION,
        ChatMemoryCategory.DECISION_RATIONALE,
        ChatMemoryCategory.FEATURE_PLAN_REF,
    },
    ChatMemoryScope.PARTICIPANT: {
        ChatMemoryCategory.PARTICIPANT_PREFERENCE,
        ChatMemoryCategory.PARTICIPANT_HISTORY,
    },
    ChatMemoryScope.UNRESOLVED_THREAD: {
        ChatMemoryCategory.THREAD_QUESTION,
        ChatMemoryCategory.THREAD_DECISION_PENDING,
    },
    ChatMemoryScope.CROSS_RESTART_RECALL: {
        ChatMemoryCategory.RECOVERY_CHECKPOINT,
        ChatMemoryCategory.SESSION_BOUNDARY,
    },
}


class SourceEvidence(BaseModel):
    source_type: SourceType
    source_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    timestamp: datetime
    thread_id: str | None = None
    evidence_uri: str | None = None

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, v: str) -> str:
        valid = {"message", "card", "proposal", "blueprint", "verdict", "artifact"}
        if v not in valid:
            raise ValueError(f"invalid source_type: {v!r}; must be one of {valid}")
        return v


class ChatMemoryTaxonomy(BaseModel):
    scope: ChatMemoryScope
    categories: list[ChatMemoryCategory] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _validate_categories(cls, v: list[ChatMemoryCategory], info) -> list[ChatMemoryCategory]:
        if not v:
            raise ValueError("at least one category is required")
        scope: ChatMemoryScope | None = None
        raw_scope = info.data.get("scope")
        if isinstance(raw_scope, ChatMemoryScope):
            scope = raw_scope
        if scope is not None:
            valid = _SCOPE_CATEGORY_MAP.get(scope, set())
            for cat in v:
                if cat not in valid:
                    raise ValueError(
                        f"category {cat!r} is not valid for scope {scope!r}"
                    )
        return v


def scope_to_categories() -> dict[ChatMemoryScope, list[ChatMemoryCategory]]:
    return {s: list(cats) for s, cats in _SCOPE_CATEGORY_MAP.items()}


ChatMemoryTaxonomy.scope_to_categories = staticmethod(scope_to_categories)


def build_conversation_shared_taxonomy() -> ChatMemoryTaxonomy:
    return ChatMemoryTaxonomy(
        scope=ChatMemoryScope.CONVERSATION_SHARED,
        categories=[
            ChatMemoryCategory.CONVERSATION_SUMMARY,
            ChatMemoryCategory.SESSION_BOUNDARY,
        ],
    )


def build_blueprint_decision_taxonomy() -> ChatMemoryTaxonomy:
    return ChatMemoryTaxonomy(
        scope=ChatMemoryScope.BLUEPRINT_DECISION,
        categories=[
            ChatMemoryCategory.BLUEPRINT_VERSION,
            ChatMemoryCategory.DECISION_RATIONALE,
            ChatMemoryCategory.FEATURE_PLAN_REF,
        ],
    )


def build_participant_taxonomy() -> ChatMemoryTaxonomy:
    return ChatMemoryTaxonomy(
        scope=ChatMemoryScope.PARTICIPANT,
        categories=[
            ChatMemoryCategory.PARTICIPANT_PREFERENCE,
            ChatMemoryCategory.PARTICIPANT_HISTORY,
        ],
    )


def build_unresolved_thread_taxonomy() -> ChatMemoryTaxonomy:
    return ChatMemoryTaxonomy(
        scope=ChatMemoryScope.UNRESOLVED_THREAD,
        categories=[
            ChatMemoryCategory.THREAD_QUESTION,
            ChatMemoryCategory.THREAD_DECISION_PENDING,
        ],
    )


def build_cross_restart_recall_taxonomy() -> ChatMemoryTaxonomy:
    return ChatMemoryTaxonomy(
        scope=ChatMemoryScope.CROSS_RESTART_RECALL,
        categories=[
            ChatMemoryCategory.RECOVERY_CHECKPOINT,
            ChatMemoryCategory.SESSION_BOUNDARY,
        ],
    )
