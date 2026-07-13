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
        raise ValueError(f"{field_name} must not contain duplicates: {', '.join(duplicates)}")
    return tuple(cleaned)


class ProviderId(StrEnum):
    CODEX = "codex"


class ProviderProfileId(StrEnum):
    DEFAULT = "default"
    WORKER = "worker"
    REVIEW = "review"
    GOD = "god"
    FINAL_QUALITY = "final_quality"


class AdapterKind(StrEnum):
    CODEX_CLI = "codex_cli"


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

    @property
    def ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"

    @property
    def supports_persistent_sessions(self) -> bool:
        return self.persistent_capability is PersistentCapability.SUPPORTED
