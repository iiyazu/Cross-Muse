from __future__ import annotations

from xmuse_core.platform import read_tool_inventory
from xmuse_core.platform.read_contracts import (
    READ_CONTRACT_TOOL_SCHEMAS as LEGACY_READ_CONTRACT_TOOL_SCHEMAS,
)
from xmuse_core.platform.read_contracts import (
    build_tool_inventory as legacy_build_tool_inventory,
)


def test_read_tool_inventory_module_owns_contract_tool_schemas() -> None:
    tool_names = {
        schema["name"]
        for schema in read_tool_inventory.READ_CONTRACT_TOOL_SCHEMAS
    }

    assert "read_lane_contract" in tool_names
    assert "read_provider_inventory" in tool_names
    assert "read_run_health" in tool_names


def test_read_tool_inventory_module_classifies_write_contracts() -> None:
    inventory = read_tool_inventory.build_tool_inventory(
        control_schemas=[{"name": "abort_lane", "description": "Abort lane"}],
        platform_schemas=[],
        chat_schemas=[{"name": "chat_post_message"}],
        contract_schemas=read_tool_inventory.READ_CONTRACT_TOOL_SCHEMAS,
    )

    assert inventory["kind"] == "tool_inventory"
    assert inventory["read_only"] is True
    assert inventory["counts"]["write"] == 2
    assert (
        inventory["families"]["control"]["tools"][0]["mutation_contract"]
        == "audit_guard_required"
    )
    assert (
        inventory["families"]["chat"]["tools"][0]["mutation_contract"]
        == "chat_identity_idempotency"
    )


def test_read_contracts_preserves_tool_inventory_compat_exports() -> None:
    assert (
        LEGACY_READ_CONTRACT_TOOL_SCHEMAS
        is read_tool_inventory.READ_CONTRACT_TOOL_SCHEMAS
    )
    assert legacy_build_tool_inventory is read_tool_inventory.build_tool_inventory
