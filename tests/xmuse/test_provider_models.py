from __future__ import annotations

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
    TaskCapability,
)
from xmuse_core.providers.registry import ProviderRegistry, build_default_provider_registry


def test_provider_profile_exposes_ref_and_validates_capabilities() -> None:
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

    assert profile.ref == "codex.worker"
    assert profile.supports_persistent_sessions is True
    assert profile.env_requirement_names == ()

    with pytest.raises(ValidationError):
        ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
            task_capabilities=[
                TaskCapability.BOUNDED_CODE_WRITING,
                TaskCapability.BOUNDED_CODE_WRITING,
            ],
        )


def test_provider_profile_requires_task_capabilities_when_omitted() -> None:
    with pytest.raises(ValidationError, match="task_capabilities"):
        ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="gpt-5.4-mini",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
            cost_tier=CostTier.LOW,
            risk_tier=RiskTier.LOW,
        )


def test_provider_registry_lists_required_codex_and_opencode_profiles() -> None:
    registry = build_default_provider_registry()

    assert [profile.ref for profile in registry.list_profiles()] == [
        "codex.default",
        "codex.worker",
        "codex.review",
        "codex.god",
        "codex.final_quality",
        "opencode.deepseek_flash_worker",
    ]

    codex_default = registry.get("codex.default")
    assert codex_default.model_id == "gpt-5.4"
    assert codex_default.supports_mcp is True
    assert codex_default.supports_persistent_sessions is True

    codex_god = registry.get("codex.god")
    assert codex_god.model_id == "gpt-5.4"
    assert TaskCapability.LANE_COORDINATION in codex_god.task_capabilities

    codex_final_quality = registry.get("codex.final_quality")
    assert codex_final_quality.model_id == "gpt-5.5"
    assert codex_final_quality.task_capabilities == (
        TaskCapability.MERGE_FINAL_REVIEW,
    )


def test_opencode_deepseek_flash_worker_has_configurable_model_and_env_requirements() -> None:
    registry = build_default_provider_registry(
        opencode_deepseek_model_id="deepseek-custom-test"
    )

    profile = registry.get("opencode.deepseek_flash_worker")

    assert profile.provider_id is ProviderId.OPENCODE
    assert profile.adapter_kind is AdapterKind.OPENCODE_CLI
    assert profile.model_id == "deepseek-custom-test"
    assert profile.model_id_env_name == "DEEPSEEK_MODEL"
    assert profile.api_base_env_name == "DEEPSEEK_BASE_URL"
    assert profile.env_requirement_names == ("DEEPSEEK_API_KEY",)
    assert profile.supports_mcp is False
    assert profile.supports_persistent_sessions is False
    assert profile.persistent_capability is PersistentCapability.UNSUPPORTED
    assert profile.task_capabilities == (
        TaskCapability.BOUNDED_CODE_WRITING,
        TaskCapability.BOUNDED_DELIBERATION,
    )
    assert TaskCapability.REVIEW not in profile.task_capabilities
    assert TaskCapability.TAKEOVER not in profile.task_capabilities


def test_provider_registry_rejects_duplicate_profile_refs() -> None:
    worker = ProviderProfile(
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

    with pytest.raises(ValueError, match="duplicate provider profile ref"):
        ProviderRegistry([worker, worker])


def test_registry_profiles_are_deeply_read_only() -> None:
    registry = build_default_provider_registry()
    profile = registry.get("codex.worker")

    with pytest.raises(AttributeError):
        profile.task_capabilities.append(TaskCapability.REVIEW)

    with pytest.raises(AttributeError):
        registry.get("opencode.deepseek_flash_worker").env_requirement_names.append(
            "EXTRA_ENV"
        )
