from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from xmuse_core.providers.models import (
    AdapterKind,
    CostTier,
    PersistentCapability,
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    SupportLevel,
    TaskCapability,
)
from xmuse_core.providers.policy import ProviderPolicyService
from xmuse_core.providers.registry import ProviderRegistry, build_default_provider_registry


class TestSupportLevelEnum:
    def test_is_str_enum(self) -> None:
        assert issubclass(SupportLevel, str)
        assert SupportLevel.PRIMARY == "primary"
        assert SupportLevel.SECONDARY == "secondary"
        assert SupportLevel.EXPERIMENTAL == "experimental"
        assert SupportLevel.LEGACY == "legacy"
        assert SupportLevel.TEST_ONLY == "test_only"

    def test_values_are_unique(self) -> None:
        values = [m.value for m in SupportLevel]
        assert len(values) == len(set(values))

    def test_from_string(self) -> None:
        assert SupportLevel("primary") is SupportLevel.PRIMARY
        assert SupportLevel("secondary") is SupportLevel.SECONDARY
        assert SupportLevel("experimental") is SupportLevel.EXPERIMENTAL
        assert SupportLevel("legacy") is SupportLevel.LEGACY
        assert SupportLevel("test_only") is SupportLevel.TEST_ONLY

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError, match="not_a_valid_level"):
            SupportLevel("not_a_valid_level")


class TestSupportLevelOnDefaultProfiles:
    def test_all_codex_profiles_are_primary(self) -> None:
        registry = build_default_provider_registry()
        for profile in registry.list_profiles():
            if profile.provider_id is ProviderId.CODEX:
                assert profile.support_level is SupportLevel.PRIMARY, (
                    f"{profile.ref} expected PRIMARY, got {profile.support_level}"
                )

    def test_opencode_deepseek_flash_worker_is_secondary(self) -> None:
        registry = build_default_provider_registry()
        profile = registry.get("opencode.deepseek_flash_worker")
        assert profile.support_level is SupportLevel.SECONDARY

    def test_profile_support_level_default_is_primary(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        assert profile.support_level is SupportLevel.PRIMARY

    def test_can_set_explicit_support_level(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            support_level=SupportLevel.TEST_ONLY,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        assert profile.support_level is SupportLevel.TEST_ONLY


class TestSupportLevelSerialization:
    def test_serializes_to_string_in_json(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            support_level=SupportLevel.EXPERIMENTAL,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        data = profile.model_dump(mode="json")
        assert data["support_level"] == "experimental"
        assert isinstance(data["support_level"], str)

    def test_default_serializes_to_primary(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        data = profile.model_dump(mode="json")
        assert data["support_level"] == "primary"

    def test_round_trips_through_json(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            support_level=SupportLevel.LEGACY,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        raw = profile.model_dump_json()
        decoded = json.loads(raw)
        assert decoded["support_level"] == "legacy"
        restored = ProviderProfile.model_validate_json(raw)
        assert restored.support_level is SupportLevel.LEGACY

    def test_frozen_profile_cannot_change_support_level(self) -> None:
        profile = ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        with pytest.raises(ValidationError):
            profile.support_level = SupportLevel.EXPERIMENTAL  # type: ignore[misc]


class TestTestOnlyProfileIsNotSelectedByDefaultPolicy:
    """Verify that a TEST_ONLY profile is not selected by the default policy logic.

    The default policy uses hardcoded profile refs that point to PRIMARY/SECONDARY
    profiles. A TEST_ONLY profile in the registry should never be selected unless
    explicitly configured.
    """

    def test_default_registry_has_no_test_only_profiles(self) -> None:
        registry = build_default_provider_registry()
        for profile in registry.list_profiles():
            assert profile.support_level is not SupportLevel.TEST_ONLY, (
                f"{profile.ref} should not be TEST_ONLY"
            )

    def test_policy_ignores_test_only_profile_when_not_configured(self) -> None:
        """A TEST_ONLY profile registered under a non-standard ref is not selected."""
        test_only_profile = ProviderProfile(
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEFAULT,
            adapter_kind=AdapterKind.OPENCODE_CLI,
            model_id="test-model",
            supports_mcp=False,
            persistent_capability=PersistentCapability.UNSUPPORTED,
            support_level=SupportLevel.TEST_ONLY,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        default_profiles = build_default_provider_registry().list_profiles()
        registry = ProviderRegistry([*default_profiles, test_only_profile])
        service = ProviderPolicyService(registry=registry)

        # The policy should select the known profiles, not the TEST_ONLY one
        god = service.select_god(task_type=TaskCapability.PLANNING)
        assert god.provider_profile_ref == "codex.god"
        assert god.provider_profile_ref != "opencode.default"

        review = service.select_review()
        assert review.provider_profile_ref == "codex.review"
        assert review.provider_profile_ref != "opencode.default"

        coordinator = service.select_coordinator(
            lane={"risk": "medium", "task_type": "lane_coordination"}
        )
        assert coordinator.provider_profile_ref == "codex.god"
        assert coordinator.provider_profile_ref != "opencode.default"

    def test_policy_falls_back_when_low_cost_ref_points_to_test_only(self) -> None:
        """Even if a TEST_ONLY profile is configured as low_cost_worker, policy
        falls back to the codex worker when the TEST_ONLY profile is not healthy
        (no health data provided)."""
        test_only_profile = ProviderProfile(
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            adapter_kind=AdapterKind.OPENCODE_CLI,
            model_id="test-model",
            supports_mcp=False,
            persistent_capability=PersistentCapability.UNSUPPORTED,
            support_level=SupportLevel.TEST_ONLY,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
        )
        # Replace the deepseek profile with a TEST_ONLY one at the same ref
        codex_profiles = [
            p
            for p in build_default_provider_registry().list_profiles()
            if p.provider_id is ProviderId.CODEX
        ]
        registry = ProviderRegistry([*codex_profiles, test_only_profile])
        service = ProviderPolicyService(registry=registry)

        decision = service.select_worker(
            lane={
                "risk": "low",
                "task_type": "bounded_code_writing",
                "bounded_context": True,
                "well_specified": True,
            },
            health_by_profile=None,
        )

        # Falls back to codex.worker because TEST_ONLY profile is not healthy
        # (no health snapshot provided)
        assert decision.provider_profile_ref == "codex.worker"
        assert decision.fallback_cause is not None
