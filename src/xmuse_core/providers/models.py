from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _require_non_empty(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _require_unique_non_empty(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    cleaned = [_require_non_empty(value, field_name) for value in values]
    duplicates = sorted({value for value in cleaned if cleaned.count(value) > 1})
    if duplicates:
        raise ValueError(
            f"{field_name} must not contain duplicates: {', '.join(duplicates)}"
        )
    return tuple(cleaned)


class ProviderId(StrEnum):
    A2A = "a2a"
    CODEX = "codex"
    OPENCODE = "opencode"


class ProviderProfileId(StrEnum):
    DEFAULT = "default"
    WORKER = "worker"
    REVIEW = "review"
    GOD = "god"
    FINAL_QUALITY = "final_quality"
    DEEPSEEK_FLASH_WORKER = "deepseek_flash_worker"
    REMOTE = "remote"


class AdapterKind(StrEnum):
    A2A_REMOTE = "a2a_remote"
    CODEX_CLI = "codex_cli"
    OPENCODE_CLI = "opencode_cli"


class SupportLevel(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXPERIMENTAL = "experimental"
    LEGACY = "legacy"
    TEST_ONLY = "test_only"


class CostTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskCapability(StrEnum):
    BOUNDED_CODE_WRITING = "bounded_code_writing"
    BOUNDED_DELIBERATION = "bounded_deliberation"
    REVIEW = "review"
    LANE_COORDINATION = "lane_coordination"
    PLANNING = "planning"
    TAKEOVER = "takeover"
    MERGE_FINAL_REVIEW = "merge_final_review"


class PersistentCapability(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    profile_id: ProviderProfileId
    adapter_kind: AdapterKind
    model_id: str
    model_id_env_name: str | None = None
    api_base_env_name: str | None = None
    env_requirement_names: tuple[str, ...] = Field(default_factory=tuple)
    supports_mcp: bool
    persistent_capability: PersistentCapability
    support_level: SupportLevel = SupportLevel.PRIMARY
    cost_tier: CostTier
    risk_tier: RiskTier
    task_capabilities: tuple[TaskCapability, ...]

    @field_validator("model_id")
    @classmethod
    def _validate_model_id(cls, value: str) -> str:
        return _require_non_empty(value, "model_id")

    @field_validator("model_id_env_name", "api_base_env_name")
    @classmethod
    def _validate_optional_env_name(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "env_name")

    @field_validator("env_requirement_names")
    @classmethod
    def _validate_env_requirement_names(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return _require_unique_non_empty(value, "env_requirement_names")

    @field_validator("task_capabilities")
    @classmethod
    def _validate_task_capabilities(
        cls,
        value: tuple[TaskCapability, ...],
    ) -> tuple[TaskCapability, ...]:
        if not value:
            raise ValueError("task_capabilities must contain at least one capability")
        duplicates = sorted({item.value for item in value if value.count(item) > 1})
        if duplicates:
            raise ValueError(
                "task_capabilities must not contain duplicates: "
                + ", ".join(duplicates)
            )
        return value

    @property
    def ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"

    @property
    def supports_persistent_sessions(self) -> bool:
        return self.persistent_capability is PersistentCapability.SUPPORTED
