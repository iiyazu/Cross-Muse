from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class DeliberationMessageKind(StrEnum):
    NOTE = "note"
    CHALLENGE = "challenge"
    PROPOSAL = "proposal"
    VOTE = "vote"
    COMMIT = "commit"
    EVIDENCE = "evidence"


class GodSpeechAct(StrEnum):
    PROPOSE = "propose"
    ASK = "ask"
    CHALLENGE = "challenge"
    OBJECT = "object"
    VOTE = "vote"
    DECIDE = "decide"
    HANDOFF = "handoff"
    EVIDENCE = "evidence"
    RETRACT = "retract"


class ObjectionLevel(StrEnum):
    NONE = "none"
    NON_BLOCKING = "non_blocking"
    BLOCKING = "blocking"


class DeliberationMessageV1(BaseModel):
    """Versioned message contract for logical decentralized GOD deliberation."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["deliberation_message.v1"] = "deliberation_message.v1"
    msg_id: str
    conversation_id: str
    agent_id: str
    lamport_ts: int
    kind: DeliberationMessageKind
    parent_id: str | None = None
    target_ref: str | None = None
    mentions: list[str] = Field(default_factory=list)
    payload: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list)
    objection_level: ObjectionLevel = ObjectionLevel.NONE
    decision_scope: str

    @field_validator("msg_id", "conversation_id", "agent_id", "decision_scope")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("parent_id", "target_ref")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("lamport_ts")
    @classmethod
    def _validate_lamport_ts(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("lamport_ts must be >= 0")
        return value

    @field_validator("mentions", "source_refs")
    @classmethod
    def _validate_text_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return [_require_non_empty(item, info.field_name or "field") for item in value]

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_kind_payload(self) -> DeliberationMessageV1:
        if self.kind is DeliberationMessageKind.VOTE:
            vote = self.payload.get("vote")
            if vote not in {"approve", "reject", "abstain"}:
                raise ValueError("vote payload must contain vote=approve|reject|abstain")
        if self.kind is DeliberationMessageKind.COMMIT and not self.target_ref:
            raise ValueError("commit messages require target_ref")
        if (
            self.kind is DeliberationMessageKind.CHALLENGE
            and self.objection_level is ObjectionLevel.NONE
        ):
            raise ValueError("challenge messages require an objection_level")
        return self

    def stable_json(self) -> str:
        data = self.model_dump(mode="json")
        ordered = {
            "agent_id": data["agent_id"],
            "conversation_id": data["conversation_id"],
            "decision_scope": data["decision_scope"],
            "kind": data["kind"],
            "lamport_ts": data["lamport_ts"],
            "mentions": data["mentions"],
            "msg_id": data["msg_id"],
            "objection_level": data["objection_level"],
            "parent_id": data["parent_id"],
            "payload": data["payload"],
            "source_refs": data["source_refs"],
            "target_ref": data["target_ref"],
            "version": data["version"],
        }
        return _stable_json(ordered)

    def idempotency_key(self) -> str:
        payload = self.model_dump(mode="json", exclude={"msg_id"})
        digest = hashlib.sha256(_stable_json(payload).encode()).hexdigest()
        return f"deliberation:{digest}"


def sort_deliberation_messages(
    messages: list[DeliberationMessageV1],
) -> list[DeliberationMessageV1]:
    return sorted(messages, key=lambda message: (message.lamport_ts, message.msg_id))


class GodSpeechActMessageV1(BaseModel):
    """Structured GOD groupchat behavior envelope."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["god_speech_act_message.v1"] = "god_speech_act_message.v1"
    message_id: str
    conversation_id: str
    thread_id: str
    sender_god: str
    targets: list[str] = Field(min_length=1)
    speech_act: GodSpeechAct
    references: list[str] = Field(default_factory=list)
    causal_parent_id: str | None = None
    lane_scope: str | None = None
    confidence: float = Field(ge=0, le=1)
    memory_refs: list[str] = Field(default_factory=list)
    requires_reply_by: int | None = None
    payload: dict[str, Any]

    @field_validator("message_id", "conversation_id", "thread_id", "sender_god")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("causal_parent_id", "lane_scope")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("targets", "references", "memory_refs")
    @classmethod
    def _validate_text_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return [_require_non_empty(item, info.field_name or "field") for item in value]

    @field_validator("requires_reply_by")
    @classmethod
    def _validate_reply_deadline(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or value < 0:
            raise ValueError("requires_reply_by must be >= 0")
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_speech_act_shape(self) -> GodSpeechActMessageV1:
        if self.speech_act in {GodSpeechAct.CHALLENGE, GodSpeechAct.OBJECT} and not (
            self.causal_parent_id or self.references
        ):
            raise ValueError("challenge/object messages require a parent or reference")
        if self.speech_act is GodSpeechAct.VOTE:
            vote = self.payload.get("vote")
            if vote not in {"approve", "reject", "abstain"}:
                raise ValueError("vote payload must contain vote=approve|reject|abstain")
        return self

    def stable_json(self) -> str:
        data = self.model_dump(mode="json")
        ordered = {
            "causal_parent_id": data["causal_parent_id"],
            "confidence": data["confidence"],
            "conversation_id": data["conversation_id"],
            "lane_scope": data["lane_scope"],
            "memory_refs": data["memory_refs"],
            "message_id": data["message_id"],
            "payload": data["payload"],
            "references": data["references"],
            "requires_reply_by": data["requires_reply_by"],
            "sender_god": data["sender_god"],
            "speech_act": data["speech_act"],
            "targets": data["targets"],
            "thread_id": data["thread_id"],
            "version": data["version"],
        }
        return _stable_json(ordered)

    def idempotency_key(self) -> str:
        payload = self.model_dump(mode="json", exclude={"message_id"})
        digest = hashlib.sha256(_stable_json(payload).encode()).hexdigest()
        return f"god-speech-act:{digest}"


class ActiveChallengeTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    conversation_id: str
    thread_id: str
    assigned_to: str
    target_message_id: str
    reason: str
    source_refs: list[str] = Field(default_factory=list)


class SpeechActReplyBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blocker_id: str
    conversation_id: str
    thread_id: str
    source_message_id: str
    missing_targets: list[str]
    reason: str
    blocks_dispatch: bool = True


def sort_god_speech_act_messages(
    messages: list[GodSpeechActMessageV1],
) -> list[GodSpeechActMessageV1]:
    by_id = {message.message_id: message for message in messages}
    ordered: list[GodSpeechActMessageV1] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(message_id: str) -> None:
        if message_id in visited:
            return
        if message_id in visiting:
            raise ValueError("causal_parent_id cycle detected")
        visiting.add(message_id)
        message = by_id[message_id]
        if message.causal_parent_id in by_id:
            visit(message.causal_parent_id)
        visiting.remove(message_id)
        visited.add(message_id)
        ordered.append(message)

    for message_id in sorted(by_id):
        visit(message_id)
    return ordered


def dedupe_god_speech_act_messages(
    messages: list[GodSpeechActMessageV1],
) -> tuple[list[GodSpeechActMessageV1], list[str]]:
    seen_keys: set[str] = set()
    unique_messages: list[GodSpeechActMessageV1] = []
    duplicate_message_ids: list[str] = []
    for message in sort_god_speech_act_messages(messages):
        key = message.idempotency_key()
        if key in seen_keys:
            duplicate_message_ids.append(message.message_id)
            continue
        seen_keys.add(key)
        unique_messages.append(message)
    return unique_messages, duplicate_message_ids


def derive_active_challenge_tasks(
    messages: list[GodSpeechActMessageV1],
    *,
    review_god: str = "god-review",
) -> list[ActiveChallengeTask]:
    unique_messages, _ = dedupe_god_speech_act_messages(messages)
    challenged_parent_ids = {
        message.causal_parent_id
        for message in unique_messages
        if message.speech_act in {GodSpeechAct.CHALLENGE, GodSpeechAct.OBJECT}
        and message.causal_parent_id
    }
    tasks: list[ActiveChallengeTask] = []
    for message in unique_messages:
        if message.speech_act is not GodSpeechAct.PROPOSE:
            continue
        assumptions = message.payload.get("unverified_assumptions") or message.payload.get(
            "assumptions"
        )
        if not assumptions or message.message_id in challenged_parent_ids:
            continue
        tasks.append(
            ActiveChallengeTask(
                task_id=f"challenge:{message.message_id}:{review_god}",
                conversation_id=message.conversation_id,
                thread_id=message.thread_id,
                assigned_to=review_god,
                target_message_id=message.message_id,
                reason="proposal contains unverified assumptions",
                source_refs=[f"message:{message.message_id}", *message.references],
            )
        )
    return tasks


def derive_unanswered_reply_blockers(
    messages: list[GodSpeechActMessageV1],
    *,
    current_lamport: int,
) -> list[SpeechActReplyBlocker]:
    if current_lamport < 0:
        raise ValueError("current_lamport must be >= 0")
    unique_messages, _ = dedupe_god_speech_act_messages(messages)
    replies_by_parent: dict[str, set[str]] = {}
    for message in unique_messages:
        if message.causal_parent_id is None:
            continue
        replies_by_parent.setdefault(message.causal_parent_id, set()).add(message.sender_god)

    blockers: list[SpeechActReplyBlocker] = []
    for message in unique_messages:
        if message.requires_reply_by is None or message.requires_reply_by > current_lamport:
            continue
        replied = replies_by_parent.get(message.message_id, set())
        missing_targets = [target for target in message.targets if target not in replied]
        if not missing_targets:
            continue
        blockers.append(
            SpeechActReplyBlocker(
                blocker_id=f"reply-blocker:{message.message_id}",
                conversation_id=message.conversation_id,
                thread_id=message.thread_id,
                source_message_id=message.message_id,
                missing_targets=missing_targets,
                reason="required reply deadline elapsed",
            )
        )
    return blockers


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
