from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from xmuse_core.providers.models import ProviderId, ProviderProfileId

MAX_DIAGNOSTIC_SUMMARY_LENGTH = 512


class ProviderHealthFailureKind(StrEnum):
    UNAVAILABLE = "unavailable"
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    TIMEOUT = "timeout"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


class ProviderHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    profile_id: ProviderProfileId
    checked_at: datetime
    is_available: bool
    is_configured: bool
    auth_ok: bool
    model_available: bool
    failure_kind: ProviderHealthFailureKind | None = None
    diagnostic_summary: str | None = Field(
        default=None,
        max_length=MAX_DIAGNOSTIC_SUMMARY_LENGTH,
    )

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value

    @field_validator("diagnostic_summary")
    @classmethod
    def _validate_diagnostic_summary(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return _require_optional_text(value, info.field_name)

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"


def infer_provider_health_failure_kind(
    snapshot: ProviderHealthSnapshot | None,
) -> ProviderHealthFailureKind | None:
    if snapshot is None:
        return ProviderHealthFailureKind.UNAVAILABLE
    if snapshot.failure_kind is not None:
        return snapshot.failure_kind
    if not snapshot.is_configured:
        return ProviderHealthFailureKind.CONFIG_ERROR
    if not snapshot.auth_ok:
        return ProviderHealthFailureKind.AUTH_ERROR
    if not snapshot.model_available:
        return ProviderHealthFailureKind.MODEL_UNAVAILABLE
    if not snapshot.is_available:
        return ProviderHealthFailureKind.UNAVAILABLE
    return None
