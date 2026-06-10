from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from xmuse_core.platform.provider_read_contracts import (
    build_provider_inventory,
    build_provider_selection_records,
)
from xmuse_core.providers.models import (
    CostTier,
    PersistentCapability,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.registry import build_default_provider_registry


def test_provider_inventory_profile_fields_match_source_model() -> None:
    inventory = build_provider_inventory()
    registry = build_default_provider_registry()

    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            profile = registry.get(profile_entry["ref"])
            assert profile is not None

            assert profile_entry["provider_id"] == profile.provider_id.value
            assert profile_entry["profile_id"] == profile.profile_id.value
            assert profile_entry["adapter_kind"] == profile.adapter_kind.value
            assert profile_entry["model_id"] == profile.model_id
            assert profile_entry["supports_mcp"] == profile.supports_mcp
            assert (
                profile_entry["supports_persistent_sessions"]
                == profile.supports_persistent_sessions
            )
            assert profile_entry["persistent_capability"] == profile.persistent_capability.value
            assert profile_entry["cost_tier"] == profile.cost_tier.value
            assert profile_entry["risk_tier"] == profile.risk_tier.value
            assert profile_entry["task_capabilities"] == [
                c.value for c in profile.task_capabilities
            ]
            assert profile_entry["model_id_env_name"] == profile.model_id_env_name
            assert profile_entry["api_base_env_name"] == profile.api_base_env_name


def test_provider_inventory_task_capabilities_enum_values_consistent() -> None:
    inventory = build_provider_inventory()
    expected_values = {c.value for c in TaskCapability}

    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            for cap in profile_entry["task_capabilities"]:
                assert cap in expected_values, (
                    f"Unknown task capability {cap!r} in profile {profile_entry['ref']}"
                )


def test_provider_inventory_risk_tier_enum_values_consistent() -> None:
    inventory = build_provider_inventory()
    expected_values = {r.value for r in RiskTier}

    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            assert profile_entry["risk_tier"] in expected_values


def test_provider_inventory_cost_tier_enum_values_consistent() -> None:
    inventory = build_provider_inventory()
    expected_values = {c.value for c in CostTier}

    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            assert profile_entry["cost_tier"] in expected_values, (
                f"Unknown cost_tier {profile_entry['cost_tier']!r}"
            )


def test_provider_inventory_persistent_capability_enum_values_consistent() -> None:
    inventory = build_provider_inventory()
    expected_values = {p.value for p in PersistentCapability}

    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            assert profile_entry["persistent_capability"] in expected_values


def test_provider_selection_records_task_type_matches_task_capability_enum() -> None:
    expected_values = {c.value for c in TaskCapability}
    with TemporaryDirectory() as tmp:
        records = build_provider_selection_records(xmuse_root=Path(tmp))
        for record in records["records"]:
            assert record["task_type"] in expected_values, (
                f"Unknown task_type {record['task_type']!r}"
            )


def test_provider_selection_records_lane_risk_matches_risk_tier_enum() -> None:
    expected_values = {r.value for r in RiskTier}
    with TemporaryDirectory() as tmp:
        records = build_provider_selection_records(xmuse_root=Path(tmp))
        for record in records["records"]:
            assert record["lane_risk"] in expected_values


def test_registry_profile_count_matches_inventory_count() -> None:
    registry = build_default_provider_registry()
    inventory = build_provider_inventory()

    registry_profiles = {}
    for profile in registry.list_profiles():
        key = f"{profile.provider_id.value}.{profile.profile_id.value}"
        registry_profiles[key] = profile

    inventory_profiles = {}
    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            inventory_profiles[profile_entry["ref"]] = profile_entry

    assert set(registry_profiles) == set(inventory_profiles), (
        f"Registry has {set(registry_profiles) - set(inventory_profiles)} "
        f"not in inventory; inventory has "
        f"{set(inventory_profiles) - set(registry_profiles)} not in registry"
    )


def test_every_provider_has_supports_mcp_and_persistent_sessions_fields() -> None:
    inventory = build_provider_inventory()
    for provider_entry in inventory["providers"]:
        for profile_entry in provider_entry["profiles"]:
            assert "supports_mcp" in profile_entry
            assert "supports_persistent_sessions" in profile_entry
            assert "persistent_capability" in profile_entry


def test_model_policy_default_constants_match_registry_defaults() -> None:
    from xmuse_core.platform.model_policy import (
        DEFAULT_CODEX_MODEL,
        DEFAULT_TIERED_COORDINATOR_MODEL,
        DEFAULT_TIERED_REVIEW_MODEL,
        DEFAULT_TIERED_WORKER_MODEL,
    )
    from xmuse_core.providers.registry import (
        DEFAULT_CODEX_GOD_MODEL_ID,
        DEFAULT_CODEX_REVIEW_MODEL_ID,
        DEFAULT_CODEX_WORKER_MODEL_ID,
    )

    assert DEFAULT_CODEX_MODEL == DEFAULT_CODEX_REVIEW_MODEL_ID
    assert DEFAULT_TIERED_REVIEW_MODEL == DEFAULT_CODEX_REVIEW_MODEL_ID
    assert DEFAULT_TIERED_COORDINATOR_MODEL == DEFAULT_CODEX_GOD_MODEL_ID
    assert DEFAULT_TIERED_WORKER_MODEL == DEFAULT_CODEX_WORKER_MODEL_ID


def test_every_registry_profile_has_valid_task_capabilities() -> None:
    registry = build_default_provider_registry()
    for profile in registry.list_profiles():
        assert len(profile.task_capabilities) >= 1
        for cap in profile.task_capabilities:
            assert isinstance(cap, TaskCapability)
