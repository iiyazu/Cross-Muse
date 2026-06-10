from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)

MAX_SELECTION_REASON_LENGTH = 512
MAX_FALLBACK_CAUSE_LENGTH = 256
MAX_PEER_TYPE_LENGTH = 64
MAX_SOURCE_AUTHORITY_LENGTH = 128
DEFAULT_SELECTION_RECORD_SOURCE_AUTHORITY = "provider_selection_record_store"


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _require_optional_text(
    value: str | None,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


class ProviderSelectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    selected_at: datetime
    provider_id: ProviderId
    profile_id: ProviderProfileId
    task_type: TaskCapability
    lane_risk: RiskTier
    selection_reason: str = Field(max_length=MAX_SELECTION_REASON_LENGTH)
    peer_type: str | None = Field(default=None, max_length=MAX_PEER_TYPE_LENGTH)
    fallback_cause: str | None = Field(
        default=None,
        max_length=MAX_FALLBACK_CAUSE_LENGTH,
    )
    health_failure_kind: str | None = Field(
        default=None,
        max_length=MAX_FALLBACK_CAUSE_LENGTH,
    )
    source_authority: str = Field(
        default=DEFAULT_SELECTION_RECORD_SOURCE_AUTHORITY,
        max_length=MAX_SOURCE_AUTHORITY_LENGTH,
    )

    @field_validator("lane_id", "selection_reason")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, info.field_name)

    @field_validator("peer_type", "fallback_cause", "health_failure_kind")
    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("source_authority")
    @classmethod
    def _validate_source_authority(cls, value: str) -> str:
        return _require_text(value, "source_authority")

    @field_validator("selected_at")
    @classmethod
    def _validate_selected_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selected_at must be timezone-aware")
        return value

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"


class ProviderSelectionRecordStore:
    FILE_NAME = "provider_selection_records.jsonl"

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @classmethod
    def from_xmuse_root(
        cls,
        xmuse_root: Path | str,
    ) -> ProviderSelectionRecordStore:
        return cls(Path(xmuse_root) / "read_models" / cls.FILE_NAME)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: ProviderSelectionRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def list_records(
        self,
        *,
        lane_id: str | None = None,
        provider_profile_ref: str | None = None,
        task_type: TaskCapability | str | None = None,
        limit: int | None = None,
    ) -> list[ProviderSelectionRecord]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be a positive integer")

        normalized_lane_id = lane_id.strip() if isinstance(lane_id, str) else None
        normalized_profile_ref = (
            provider_profile_ref.strip()
            if isinstance(provider_profile_ref, str)
            else None
        )
        normalized_task_type = (
            task_type.value if isinstance(task_type, TaskCapability) else None
        )
        if normalized_task_type is None and isinstance(task_type, str):
            normalized_task_type = task_type.strip()

        records: list[ProviderSelectionRecord] = []
        if not self._path.exists():
            return records

        for line in self._path.read_text(encoding="utf-8").splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                record = ProviderSelectionRecord.model_validate_json(payload)
            except ValueError:
                continue
            if normalized_lane_id and record.lane_id != normalized_lane_id:
                continue
            if (
                normalized_profile_ref
                and record.provider_profile_ref != normalized_profile_ref
            ):
                continue
            if normalized_task_type and record.task_type.value != normalized_task_type:
                continue
            records.append(record)

        if limit is not None:
            records = records[-limit:]
        records.reverse()
        return records
