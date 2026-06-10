from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.providers.models import ProviderProfile
from xmuse_core.providers.registry import build_default_provider_registry
from xmuse_core.providers.selection_record import (
    ProviderSelectionRecord,
    ProviderSelectionRecordStore,
)


def build_provider_inventory() -> dict[str, Any]:
    registry = build_default_provider_registry()
    profiles = registry.list_profiles()
    providers: list[dict[str, Any]] = []

    for provider_id in sorted({profile.provider_id.value for profile in profiles}):
        provider_profiles = [
            _provider_profile_inventory(profile)
            for profile in profiles
            if profile.provider_id.value == provider_id
        ]
        providers.append(
            {
                "provider_id": provider_id,
                "profile_count": len(provider_profiles),
                "profile_refs": [profile["ref"] for profile in provider_profiles],
                "profiles": provider_profiles,
            }
        )

    return {
        "kind": "provider_inventory",
        "read_only": True,
        "counts": {
            "providers": len(providers),
            "profiles": len(profiles),
        },
        "provider_ids": [provider["provider_id"] for provider in providers],
        "providers": providers,
    }


def build_provider_selection_records(
    *,
    xmuse_root: Path,
    lane_id: str | None = None,
    provider_profile_ref: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    bounded_limit = _bounded_record_limit(limit)
    store = ProviderSelectionRecordStore.from_xmuse_root(xmuse_root)
    records = store.list_records(
        lane_id=lane_id,
        provider_profile_ref=provider_profile_ref,
        task_type=task_type,
        limit=bounded_limit,
    )
    return {
        "kind": "provider_selection_records",
        "read_only": True,
        "source_authority": "provider_selection_records_read_model",
        "generated_at": _utc_now(),
        "filters": {
            "lane_id": _optional_text(lane_id),
            "provider_profile_ref": _optional_text(provider_profile_ref),
            "task_type": _optional_text(task_type),
            "limit": bounded_limit,
        },
        "counts": {
            "records": len(records),
            "lanes": len({record.lane_id for record in records}),
            "provider_profiles": len(
                {record.provider_profile_ref for record in records}
            ),
            "task_types": len({record.task_type.value for record in records}),
        },
        "records": [
            _provider_selection_record_inventory(record) for record in records
        ],
    }


def _provider_profile_inventory(profile: ProviderProfile) -> dict[str, Any]:
    return {
        "ref": profile.ref,
        "provider_id": profile.provider_id.value,
        "profile_id": profile.profile_id.value,
        "adapter_kind": profile.adapter_kind.value,
        "model_id": profile.model_id,
        "supports_mcp": profile.supports_mcp,
        "supports_persistent_sessions": profile.supports_persistent_sessions,
        "persistent_capability": profile.persistent_capability.value,
        "support_level": profile.support_level.value,
        "cost_tier": profile.cost_tier.value,
        "risk_tier": profile.risk_tier.value,
        "task_capabilities": [capability.value for capability in profile.task_capabilities],
        "model_id_env_name": profile.model_id_env_name,
        "api_base_env_name": profile.api_base_env_name,
        "env_requirement_names": list(profile.env_requirement_names),
    }


def _provider_selection_record_inventory(
    record: ProviderSelectionRecord,
) -> dict[str, Any]:
    generated_at = record.selected_at.isoformat().replace("+00:00", "Z")
    return {
        "lane_id": record.lane_id,
        "selected_at": generated_at,
        "generated_at": generated_at,
        "provider_id": record.provider_id.value,
        "profile_id": record.profile_id.value,
        "provider_profile_ref": record.provider_profile_ref,
        "selected_profile_ref": record.provider_profile_ref,
        "task_type": record.task_type.value,
        "task_capability": record.task_type.value,
        "lane_risk": record.lane_risk.value,
        "risk_tier": record.lane_risk.value,
        "selection_reason": record.selection_reason,
        "peer_type": record.peer_type,
        "fallback_cause": record.fallback_cause,
        "health_failure_kind": record.health_failure_kind or record.fallback_cause,
        "source_authority": record.source_authority,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _bounded_record_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1:
        raise ValueError("limit must be positive")
    return min(limit, 200)
