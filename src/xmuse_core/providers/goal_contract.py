from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.providers.models import ProviderId, ProviderProfileId

DEFAULT_WORKER_OUTPUT_SCHEMA_VERSION = "worker_goal_result.v1"
DEFAULT_WORKER_SKILL_CONTRACT_REF = "xmuse.cli_worker_goal.v1"
DEFAULT_WORKER_FORBIDDEN_ACTIONS = (
    "Do not write durable stores.",
    "Do not update lane status or feature_lanes.json directly.",
    "Do not create autonomous GOD chains.",
)


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _require_text_list(
    values: list[str],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    cleaned = [_require_text(str(value), field_name) for value in values]
    if not allow_empty and not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned


def _matches_expected_touched_area(candidate: str, expected_area: str) -> bool:
    normalized_candidate = candidate.strip().strip("/")
    normalized_expected = expected_area.strip().strip("/")
    if not normalized_candidate or not normalized_expected:
        return False
    if normalized_candidate == normalized_expected:
        return True
    if any(char in normalized_expected for char in "*?[]"):
        return PurePosixPath(normalized_candidate).match(normalized_expected)
    return normalized_candidate.startswith(normalized_expected + "/")


class WorkerResultStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class WorkerEvidenceKind(StrEnum):
    CHANGED_FILE = "changed_file"
    VERIFICATION = "verification"
    LOG = "log"
    STDOUT = "stdout"
    STDERR = "stderr"
    ARTIFACT = "artifact"
    REVIEW = "review"
    BLOCKER = "blocker"
    OTHER = "other"


class WorkerVerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


class WorkerBlockerKind(StrEnum):
    MISSING_DEPENDENCY = "missing_dependency"
    MISSING_CONTEXT = "missing_context"
    PROVIDER_CONFIG = "provider_config"
    PROVIDER_AUTH = "provider_auth"
    VERIFICATION_FAILED = "verification_failed"
    CONTRACT_VIOLATION = "contract_violation"
    OUT_OF_SCOPE = "out_of_scope"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    HUMAN_INPUT_REQUIRED = "human_input_required"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class WorkerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WorkerEvidenceKind
    ref: str
    summary: str | None = None

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, value: str) -> str:
        return _require_text(value, "ref")

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_text(value, "summary")


class WorkerVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    status: WorkerVerificationStatus
    exit_code: int | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    summary: str | None = None

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: str) -> str:
        return _require_text(value, "command")

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs", allow_empty=True)

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_text(value, "summary")


class WorkerBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WorkerBlockerKind
    message: str
    retryable: bool = False
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return _require_text(value, "message")

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs", allow_empty=True)


class WorkerGoalContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    lane_id: str
    provider_id: ProviderId
    provider_profile_id: ProviderProfileId
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)
    required_verification_commands: list[str] = Field(default_factory=list)
    prior_failure_context: list[str] = Field(default_factory=list)
    requires_changed_files: bool = True
    output_schema_version: str = DEFAULT_WORKER_OUTPUT_SCHEMA_VERSION
    skill_contract_refs: list[str] = Field(
        default_factory=lambda: [DEFAULT_WORKER_SKILL_CONTRACT_REF]
    )
    forbidden_actions: list[str] = Field(
        default_factory=lambda: list(DEFAULT_WORKER_FORBIDDEN_ACTIONS)
    )

    @field_validator("request_id", "lane_id", "goal", "output_schema_version")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("acceptance_criteria", "blueprint_refs", "skill_contract_refs")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @field_validator(
        "dependencies",
        "expected_touched_areas",
        "required_verification_commands",
        "prior_failure_context",
        "forbidden_actions",
    )
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.provider_profile_id.value}"


class WorkerGoalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    provider_id: ProviderId
    provider_profile_id: ProviderProfileId
    status: WorkerResultStatus
    changed_files: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    evidence_refs: list[str]
    evidence: list[WorkerEvidence] = Field(default_factory=list)
    verification: list[WorkerVerification] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    blocker_details: list[WorkerBlocker] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    touched_areas: list[str]
    summary: str

    @field_validator("request_id", "summary")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("changed_files", "tests_run", "blockers")
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)

    @field_validator("evidence_refs", "touched_areas")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_status_requirements(self) -> WorkerGoalResult:
        if (
            self.status is WorkerResultStatus.BLOCKED
            and not self.blockers
            and not self.blocker_details
        ):
            raise ValueError(
                "blockers or blocker_details must contain at least one item "
                "for blocked results"
            )
        return self

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.provider_profile_id.value}"


def validate_worker_goal_result(
    payload: WorkerGoalResult | dict[str, Any],
    *,
    contract: WorkerGoalContract,
) -> WorkerGoalResult:
    result = (
        payload
        if isinstance(payload, WorkerGoalResult)
        else WorkerGoalResult.model_validate(payload)
    )

    if result.request_id != contract.request_id:
        raise ValueError("stale request id")

    if (
        result.provider_id is not contract.provider_id
        or result.provider_profile_id is not contract.provider_profile_id
    ):
        raise ValueError("provider/profile must match the worker goal contract")

    if contract.requires_changed_files and result.status is WorkerResultStatus.COMPLETED:
        if not result.changed_files:
            raise ValueError("changed_files must contain at least one item for edit lanes")

    if (
        not result.tests_run
        and not result.verification
        and not result.blockers
        and not result.blocker_details
    ):
        raise ValueError(
            "tests_run or verification must contain at least one item when blockers are empty"
        )

    if result.status is WorkerResultStatus.COMPLETED:
        _validate_required_verification_commands(result, contract=contract)

    if contract.expected_touched_areas:
        unexpected_touched_areas = [
            item
            for item in result.touched_areas
            if not any(
                _matches_expected_touched_area(item, expected_area)
                for expected_area in contract.expected_touched_areas
            )
        ]
        if unexpected_touched_areas:
            raise ValueError("touched areas fall outside expected_touched_areas")

        unexpected_changed_files = [
            item
            for item in result.changed_files
            if not any(
                _matches_expected_touched_area(item, expected_area)
                for expected_area in contract.expected_touched_areas
            )
        ]
        if unexpected_changed_files:
            raise ValueError("changed files fall outside expected_touched_areas")

    return result


def _validate_required_verification_commands(
    result: WorkerGoalResult,
    *,
    contract: WorkerGoalContract,
) -> None:
    if not contract.required_verification_commands:
        return
    observed_commands = set(result.tests_run)
    observed_commands.update(item.command for item in result.verification)
    missing = [
        command
        for command in contract.required_verification_commands
        if command not in observed_commands
    ]
    if missing:
        raise ValueError(
            "required_verification_commands missing from worker result: "
            + ", ".join(missing)
        )
