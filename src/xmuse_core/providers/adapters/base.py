from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from xmuse_core.providers.goal_contract import (
    WorkerGoalContract,
    WorkerGoalResult,
    WorkerResultStatus,
)
from xmuse_core.providers.health import ProviderHealthSnapshot
from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_text_list(
    values: list[str],
    field_name: str,
) -> list[str]:
    return [_require_text(str(value), field_name) for value in values]


class ProviderFailureKind(StrEnum):
    UNAVAILABLE = "unavailable"
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    TIMEOUT = "timeout"
    TRANSPORT_CRASH = "transport_crash"
    NON_ZERO_EXIT = "non_zero_exit"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONTRACT_VIOLATION = "contract_violation"
    STALE_REQUEST = "stale_request"


class ProviderInvocationWritebackContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    participant_id: str
    reply_to_inbox_item_id: str

    @field_validator("conversation_id", "participant_id", "reply_to_inbox_item_id")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, info.field_name)


class ProviderInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    provider_id: ProviderId
    profile_id: ProviderProfileId
    task_type: TaskCapability
    risk_tier: RiskTier
    prompt: str
    workspace: Path
    timeout_seconds: int = Field(gt=0)
    goal_contract: WorkerGoalContract | None = None
    writeback_context: ProviderInvocationWritebackContext | None = None
    runtime_context: dict[str, object] = Field(default_factory=dict)

    @field_validator("request_id", "prompt")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_goal_contract(self) -> ProviderInvocation:
        if self.goal_contract is None:
            return self

        if self.goal_contract.request_id != self.request_id:
            raise ValueError("goal_contract request_id must match invocation request_id")

        if (
            self.goal_contract.provider_id is not self.provider_id
            or self.goal_contract.provider_profile_id is not self.profile_id
        ):
            raise ValueError("goal_contract provider/profile must match invocation")

        return self

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"


class ProviderInvocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    provider_id: ProviderId
    profile_id: ProviderProfileId
    status: WorkerResultStatus
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    provider_session_id: str | None = None
    worker_result: WorkerGoalResult | None = None
    changed_files: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    diagnostic_payload: dict[str, object] = Field(default_factory=dict)
    failure_kind: ProviderFailureKind | None = None

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, value: str) -> str:
        return _require_text(value, "request_id")

    @field_validator("stdout_ref", "stderr_ref", "provider_session_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        cleaned = _require_optional_text(value, info.field_name)
        if info.field_name == "provider_session_id" and cleaned is not None:
            if cleaned.lower() in {"last", "--last", "latest", "--latest"}:
                raise ValueError(
                    "provider_session_id must be explicit; "
                    "last-session aliases are forbidden"
                )
        return cleaned

    @field_validator("changed_files", "tests_run", "evidence_refs")
    @classmethod
    def _validate_text_lists(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_worker_result(self) -> ProviderInvocationResult:
        if self.status is WorkerResultStatus.FAILED and self.failure_kind is None:
            raise ValueError("failure_kind must be provided for failed status")

        if self.status is not WorkerResultStatus.FAILED and self.failure_kind is not None:
            raise ValueError("failure_kind is only allowed for failed status")

        if self.worker_result is None:
            return self

        if self.worker_result.request_id != self.request_id:
            raise ValueError("worker_result request_id must match result request_id")

        if (
            self.worker_result.provider_id is not self.provider_id
            or self.worker_result.provider_profile_id is not self.profile_id
        ):
            raise ValueError("worker_result provider/profile must match result")

        if self.worker_result.status is not self.status:
            raise ValueError("worker_result status must match result status")

        return self

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"


@runtime_checkable
class ProviderAdapter(Protocol):
    profile: ProviderProfile

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult: ...

    def check_health(self) -> ProviderHealthSnapshot: ...
