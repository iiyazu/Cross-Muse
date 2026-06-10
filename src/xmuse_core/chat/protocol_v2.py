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


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
