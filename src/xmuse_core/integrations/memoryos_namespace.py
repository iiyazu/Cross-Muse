from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemoryOSNamespaceKind(StrEnum):
    REPO = "repo"
    WORKSPACE = "workspace"
    CONVERSATION = "conversation"
    PARTICIPANT = "participant"
    SHARED = "shared"
    TASK = "task"


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
        if self.kind is MemoryOSNamespaceKind.SHARED and not self.repo_id:
            raise ValueError("shared namespace requires repo_id")
        if self.kind is MemoryOSNamespaceKind.TASK:
            missing = [
                field_name
                for field_name, value in {
                    "repo_id": self.repo_id,
                    "workspace_id": self.workspace_id,
                    "god_id": self.god_id,
                    "conversation_id": self.conversation_id,
                    "thread_id": self.thread_id,
                    "blueprint_id": self.blueprint_id,
                    "feature_id": self.feature_id,
                    "lane_id": self.lane_id,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError("task namespace missing dimensions: " + ", ".join(missing))
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
        if self.kind is MemoryOSNamespaceKind.TASK:
            return (
                f"memory://repo/{self.repo_id}/workspace/{self.workspace_id}"
                f"/conversation/{self.conversation_id}/thread/{self.thread_id}"
                f"/god/{self.god_id}/blueprint/{self.blueprint_id}"
                f"/feature/{self.feature_id}/lane/{self.lane_id}"
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
