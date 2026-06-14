from __future__ import annotations

from xmuse_core.platform import provider_read_contracts
from xmuse_core.platform.read_contracts import (
    build_provider_inventory as legacy_build_provider_inventory,
)


def test_provider_read_contracts_module_owns_provider_inventory() -> None:
    inventory = provider_read_contracts.build_provider_inventory()

    assert inventory["kind"] == "provider_inventory"
    assert inventory["read_only"] is True
    assert inventory["counts"]["providers"] >= 1
    assert inventory["counts"]["profiles"] >= inventory["counts"]["providers"]
    assert inventory["provider_ids"]
    profile_inventory = {
        profile["ref"]: profile
        for provider in inventory["providers"]
        for profile in provider["profiles"]
    }
    assert profile_inventory["codex.default"]["support_level"] == "primary"
    assert profile_inventory["opencode.deepseek_flash_worker"]["support_level"] == "secondary"


def test_read_contracts_preserves_provider_inventory_compat_export() -> None:
    assert (
        legacy_build_provider_inventory
        is provider_read_contracts.build_provider_inventory
    )


def test_provider_read_contracts_exposes_god_cli_inventory() -> None:
    inventory = provider_read_contracts.build_god_cli_inventory()

    assert inventory["kind"] == "god_cli_inventory"
    assert inventory["read_only"] is True
    rows = {
        row["cli_id"]: row
        for row in inventory["registrations"]
    }
    assert "codex.god" in rows
    assert "peer_god" in rows["codex.god"]["capabilities"]
    assert "opencode.deepseek_flash_worker" in rows
    assert "peer_god" not in rows["opencode.deepseek_flash_worker"]["capabilities"]
