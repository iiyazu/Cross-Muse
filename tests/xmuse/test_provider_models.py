from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.providers.models import (
    AdapterKind,
    PersistentCapability,
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
)
from xmuse_core.providers.registry import ProviderRegistry, build_default_provider_registry


def _worker_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.WORKER,
        adapter_kind=AdapterKind.CODEX_CLI,
        model_id="gpt-5.4-mini",
        supports_mcp=True,
        persistent_capability=PersistentCapability.SUPPORTED,
    )


def test_provider_profile_exposes_room_runtime_identity() -> None:
    profile = _worker_profile()

    assert profile.ref == "codex.worker"
    assert profile.supports_persistent_sessions is True
    assert profile.env_requirement_names == ()

    with pytest.raises(ValidationError, match="model_id"):
        ProviderProfile(
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            adapter_kind=AdapterKind.CODEX_CLI,
            model_id="",
            supports_mcp=True,
            persistent_capability=PersistentCapability.SUPPORTED,
        )


def test_default_registry_contains_only_codex_room_profiles() -> None:
    registry = build_default_provider_registry()

    assert [profile.ref for profile in registry.list_profiles()] == [
        "codex.default",
        "codex.worker",
        "codex.review",
        "codex.god",
        "codex.final_quality",
    ]
    assert registry.get("codex.default").model_id == "gpt-5.4"
    assert registry.get("codex.worker").model_id == "gpt-5.4-mini"
    assert registry.get("codex.final_quality").model_id == "gpt-5.5"
    with pytest.raises(KeyError, match="a2a.remote"):
        registry.get("a2a.remote")


def test_provider_runtime_enums_are_room_only() -> None:
    assert {kind.value for kind in AdapterKind} == {"codex_cli"}
    assert {provider.value for provider in ProviderId} == {"codex"}
    assert {profile.value for profile in ProviderProfileId} == {
        "default",
        "worker",
        "review",
        "god",
        "final_quality",
    }


def test_provider_registry_rejects_duplicate_refs_and_returns_frozen_profiles() -> None:
    worker = _worker_profile()
    with pytest.raises(ValueError, match="duplicate provider profile ref"):
        ProviderRegistry([worker, worker])
    with pytest.raises(ValidationError):
        worker.model_id = "changed"  # type: ignore[misc]
