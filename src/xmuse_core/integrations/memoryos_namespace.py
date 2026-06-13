from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MemoryOSNamespaceKind(StrEnum):
    REPO = "repo"
    WORKSPACE = "workspace"
    CONVERSATION = "conversation"
    PARTICIPANT = "participant"
    GOD_PRIVATE = "god_private"
    SHARED = "shared"
    TASK = "task"
    BLUEPRINT = "blueprint"
    REVIEW = "review"
    OPERATOR = "operator"


class MemoryOSTraceAnchorKind(StrEnum):
    GOD_PRIVATE = "god_private"
    TASK = "task"
    SHARED = "shared"
    BLUEPRINT = "blueprint"
    REVIEW = "review"
    OPERATOR = "operator"


class MemoryOSNamespace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: MemoryOSNamespaceKind
    repo_id: str | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None
    participant_id: str | None = None
    god_id: str | None = None
    thread_id: str | None = None
    blueprint_id: str | None = None
    feature_id: str | None = None
    lane_id: str | None = None
    review_id: str | None = None
    operator_id: str | None = None

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> MemoryOSNamespace:
        if self.kind is MemoryOSNamespaceKind.REPO and not self.repo_id:
            raise ValueError("repo namespace requires repo_id")
        if self.kind is MemoryOSNamespaceKind.WORKSPACE and not self.workspace_id:
            raise ValueError("workspace namespace requires workspace_id")
        if self.kind is MemoryOSNamespaceKind.CONVERSATION and not self.conversation_id:
            raise ValueError("conversation namespace requires conversation_id")
        if self.kind is MemoryOSNamespaceKind.PARTICIPANT and (
            not self.conversation_id or not self.participant_id
        ):
            raise ValueError("participant namespace requires conversation_id and participant_id")
        if self.kind is MemoryOSNamespaceKind.GOD_PRIVATE:
            _require_dimensions(
                self,
                "god_private",
                ("repo_id", "workspace_id", "conversation_id", "god_id"),
            )
        if self.kind is MemoryOSNamespaceKind.SHARED and not self.repo_id:
            raise ValueError("shared namespace requires repo_id")
        if self.kind is MemoryOSNamespaceKind.TASK:
            _require_dimensions(
                self,
                "task",
                (
                    "repo_id",
                    "workspace_id",
                    "god_id",
                    "conversation_id",
                    "thread_id",
                    "blueprint_id",
                    "feature_id",
                    "lane_id",
                ),
            )
        if self.kind is MemoryOSNamespaceKind.BLUEPRINT:
            _require_dimensions(
                self,
                "blueprint",
                ("repo_id", "workspace_id", "conversation_id", "blueprint_id"),
            )
        if self.kind is MemoryOSNamespaceKind.REVIEW:
            _require_dimensions(
                self,
                "review",
                (
                    "repo_id",
                    "workspace_id",
                    "conversation_id",
                    "feature_id",
                    "lane_id",
                    "review_id",
                ),
            )
        if self.kind is MemoryOSNamespaceKind.OPERATOR:
            _require_dimensions(
                self,
                "operator",
                ("repo_id", "workspace_id", "operator_id"),
            )
        return self

    @property
    def uri(self) -> str:
        if self.kind is MemoryOSNamespaceKind.REPO:
            return f"memory://global/repo/{self.repo_id}"
        if self.kind is MemoryOSNamespaceKind.WORKSPACE:
            return f"memory://global/workspace/{self.workspace_id}"
        if self.kind is MemoryOSNamespaceKind.CONVERSATION:
            return f"memory://conversation/{self.conversation_id}"
        if self.kind is MemoryOSNamespaceKind.PARTICIPANT:
            return f"memory://conversation/{self.conversation_id}/god/{self.participant_id}"
        if self.kind is MemoryOSNamespaceKind.GOD_PRIVATE:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/conversation/{self.conversation_id}/god/{self.god_id}/private"
            )
        if self.kind is MemoryOSNamespaceKind.TASK:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/conversation/{self.conversation_id}/thread/{self.thread_id}"
                f"/god/{self.god_id}/blueprint/{self.blueprint_id}"
                f"/feature/{self.feature_id}/lane/{self.lane_id}"
            )
        if self.kind is MemoryOSNamespaceKind.BLUEPRINT:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/conversation/{self.conversation_id}/blueprint/{self.blueprint_id}"
            )
        if self.kind is MemoryOSNamespaceKind.REVIEW:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/conversation/{self.conversation_id}/feature/{self.feature_id}"
                f"/lane/{self.lane_id}/review/{self.review_id}"
            )
        if self.kind is MemoryOSNamespaceKind.OPERATOR:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/operator/{self.operator_id}"
            )
        return f"memory://global/shared/{self.repo_id}"


class MemoryOSSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: MemoryOSNamespace
    event_kind: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    commit_sha: str | None = None

    @property
    def uri(self) -> str:
        parts = [self.namespace.uri]
        if self.commit_sha:
            parts.extend(["commits", self.commit_sha])
        parts.extend(["events", self.event_kind, self.event_id])
        return "/".join(parts)


class MemoryOSTraceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: MemoryOSTraceAnchorKind
    namespace: MemoryOSNamespace
    trace_id: str = Field(min_length=1)
    source_refs: list[str]
    proof_level: Literal["contract_proof", "live_proof", "manual_gap"] = "contract_proof"
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, value: str) -> str:
        return _clean(value)

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return _clean_list(values, "source_refs", require_non_empty=True)

    @property
    def uri(self) -> str:
        return f"{self.namespace.uri}/traces/{self.trace_id}"


def repo_namespace(repo_id: str) -> MemoryOSNamespace:
    return MemoryOSNamespace(kind=MemoryOSNamespaceKind.REPO, repo_id=_clean(repo_id))


def workspace_namespace(workspace_id: str) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.WORKSPACE,
        workspace_id=_clean(workspace_id),
    )


def conversation_namespace(conversation_id: str) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.CONVERSATION,
        conversation_id=_clean(conversation_id),
    )


def participant_namespace(conversation_id: str, participant_id: str) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.PARTICIPANT,
        conversation_id=_clean(conversation_id),
        participant_id=_clean(participant_id),
    )


def god_private_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    god_id: str,
) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.GOD_PRIVATE,
        repo_id=_clean(repo_id),
        workspace_id=_clean(workspace_id),
        conversation_id=_clean(conversation_id),
        god_id=_clean(god_id),
    )


def shared_namespace(repo_id: str) -> MemoryOSNamespace:
    return MemoryOSNamespace(kind=MemoryOSNamespaceKind.SHARED, repo_id=_clean(repo_id))


def task_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    god_id: str,
    conversation_id: str,
    thread_id: str,
    blueprint_id: str,
    feature_id: str,
    lane_id: str,
) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.TASK,
        repo_id=_clean(repo_id),
        workspace_id=_clean(workspace_id),
        god_id=_clean(god_id),
        conversation_id=_clean(conversation_id),
        thread_id=_clean(thread_id),
        blueprint_id=_clean(blueprint_id),
        feature_id=_clean(feature_id),
        lane_id=_clean(lane_id),
    )


def blueprint_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    blueprint_id: str,
) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.BLUEPRINT,
        repo_id=_clean(repo_id),
        workspace_id=_clean(workspace_id),
        conversation_id=_clean(conversation_id),
        blueprint_id=_clean(blueprint_id),
    )


def review_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    conversation_id: str,
    feature_id: str,
    lane_id: str,
    review_id: str,
) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.REVIEW,
        repo_id=_clean(repo_id),
        workspace_id=_clean(workspace_id),
        conversation_id=_clean(conversation_id),
        feature_id=_clean(feature_id),
        lane_id=_clean(lane_id),
        review_id=_clean(review_id),
    )


def operator_namespace(
    *,
    repo_id: str,
    workspace_id: str,
    operator_id: str,
) -> MemoryOSNamespace:
    return MemoryOSNamespace(
        kind=MemoryOSNamespaceKind.OPERATOR,
        repo_id=_clean(repo_id),
        workspace_id=_clean(workspace_id),
        operator_id=_clean(operator_id),
    )


def memory_trace_anchor(
    *,
    kind: MemoryOSTraceAnchorKind,
    namespace: MemoryOSNamespace,
    trace_id: str,
    source_refs: list[str],
    proof_level: Literal["contract_proof", "live_proof", "manual_gap"] = "contract_proof",
    metadata: dict[str, str] | None = None,
) -> MemoryOSTraceAnchor:
    return MemoryOSTraceAnchor(
        kind=kind,
        namespace=namespace,
        trace_id=trace_id,
        source_refs=source_refs,
        proof_level=proof_level,
        metadata=dict(metadata or {}),
    )


def deterministic_memory_source_ref(
    namespace: MemoryOSNamespace,
    *,
    event_kind: str,
    event_id: str,
    commit_sha: str | None = None,
) -> str:
    return MemoryOSSourceRef(
        namespace=namespace,
        event_kind=_clean(event_kind),
        event_id=_clean(event_id),
        commit_sha=_clean(commit_sha) if commit_sha is not None else None,
    ).uri


def _clean(value: str) -> str:
    value = value.strip().strip("/")
    if not value:
        raise ValueError("value must be non-empty")
    if ".." in value.split("/"):
        raise ValueError("value must not contain path traversal")
    return value


def _clean_list(
    values: list[str],
    field_name: str,
    *,
    require_non_empty: bool = False,
) -> list[str]:
    cleaned = [_clean(value) for value in values]
    if require_non_empty and not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned


def _require_dimensions(
    namespace: MemoryOSNamespace,
    label: str,
    fields: tuple[str, ...],
) -> None:
    missing = [
        field_name
        for field_name in fields
        if not getattr(namespace, field_name)
    ]
    if missing:
        raise ValueError(f"{label} namespace missing dimensions: " + ", ".join(missing))
