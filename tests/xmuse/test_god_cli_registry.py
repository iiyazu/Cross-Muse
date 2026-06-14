from __future__ import annotations

import pytest

from xmuse_core.providers.god_cli_registry import (
    GodCliCapability,
    GodCliRegistration,
    GodCliRegistry,
    build_default_god_cli_registry,
)


def test_default_registry_exposes_codex_as_peer_god_and_opencode_as_bounded() -> None:
    registry = build_default_god_cli_registry()

    codex = registry.get("codex.god")
    opencode = registry.get("opencode.deepseek_flash_worker")

    assert GodCliCapability.PEER_GOD in codex.capabilities
    assert codex.state_write_allowed is True
    assert set(codex.allowed_speech_acts) >= {
        "propose",
        "ask",
        "challenge",
        "object",
        "vote",
        "decide",
        "handoff",
        "evidence",
    }
    assert GodCliCapability.BOUNDED_DELIBERATION in opencode.capabilities
    assert GodCliCapability.PEER_GOD not in opencode.capabilities
    assert opencode.allowed_speech_acts == ("propose", "ask", "challenge")
    assert opencode.state_write_allowed is False


def test_registry_rejects_peer_god_selection_without_peer_capability() -> None:
    registry = build_default_god_cli_registry()

    selection = registry.select_for_god("opencode.deepseek_flash_worker")

    assert selection.allowed is False
    assert selection.cli_id == "opencode.deepseek_flash_worker"
    assert selection.required_capability == GodCliCapability.PEER_GOD
    assert "does not advertise peer_god" in selection.reason


def test_registry_allows_manual_peer_god_only_with_production_writeback_proof() -> None:
    registry = GodCliRegistry(
        [
            GodCliRegistration(
                cli_id="custom.peer",
                display_name="Custom Peer",
                command_family="custom-cli",
                provider_profile_ref="custom.peer",
                capabilities=(GodCliCapability.PEER_GOD,),
                allowed_speech_acts=(
                    "propose",
                    "ask",
                    "challenge",
                    "object",
                    "vote",
                    "decide",
                    "handoff",
                    "evidence",
                ),
                supports_persistent_sessions=True,
                supports_mcp_writeback=True,
                state_write_allowed=True,
                proof_level="real_provider_proof",
                proof_refs=("provider-run://custom.peer/live-smoke-1",),
            )
        ]
    )

    selection = registry.select_for_god("custom.peer")

    assert selection.allowed is True
    assert selection.registration is not None
    assert selection.registration.cli_id == "custom.peer"


def test_manual_peer_god_requires_real_provider_proof_and_writeback() -> None:
    with pytest.raises(ValueError, match="peer_god requires real_provider_proof"):
        GodCliRegistration(
            cli_id="unsafe.peer",
            display_name="Unsafe Peer",
            command_family="unsafe",
            provider_profile_ref="unsafe.peer",
            capabilities=(GodCliCapability.PEER_GOD,),
            allowed_speech_acts=("propose", "decide"),
            supports_persistent_sessions=True,
            supports_mcp_writeback=True,
            state_write_allowed=True,
            proof_level="contract_proof",
        )

    with pytest.raises(ValueError, match="peer_god requires persistent sessions"):
        GodCliRegistration(
            cli_id="no-session.peer",
            display_name="No Session Peer",
            command_family="unsafe",
            provider_profile_ref="unsafe.peer",
            capabilities=(GodCliCapability.PEER_GOD,),
            allowed_speech_acts=("propose", "decide"),
            supports_persistent_sessions=False,
            supports_mcp_writeback=True,
            state_write_allowed=True,
            proof_level="real_provider_proof",
            proof_refs=("provider-run://no-session.peer/live-smoke-1",),
        )

    with pytest.raises(ValueError, match="peer_god requires proof_refs"):
        GodCliRegistration(
            cli_id="no-proof-ref.peer",
            display_name="No Proof Ref Peer",
            command_family="unsafe",
            provider_profile_ref="unsafe.peer",
            capabilities=(GodCliCapability.PEER_GOD,),
            allowed_speech_acts=("propose", "decide"),
            supports_persistent_sessions=True,
            supports_mcp_writeback=True,
            state_write_allowed=True,
            proof_level="real_provider_proof",
        )
