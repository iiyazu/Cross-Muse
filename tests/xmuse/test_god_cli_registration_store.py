from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import (
    GodCliCapability,
    GodCliRegistration,
)


def _registration(cli_id: str = "custom.peer") -> GodCliRegistration:
    return GodCliRegistration(
        cli_id=cli_id,
        display_name="Custom Peer",
        command_family="custom-cli",
        provider_profile_ref=cli_id,
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


def test_god_cli_registration_store_persists_manual_registration(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "god_cli_registrations.json"
    store = GodCliRegistrationStore(store_path)

    record = store.record_registration(
        registration=_registration(),
        registered_by="operator-1",
        audit_id="operator-action:audit-1",
        idempotency_key="idem-register-1",
    )

    reloaded = GodCliRegistrationStore(store_path).get("custom.peer")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert record.registration.cli_id == "custom.peer"
    assert record.registration.proof_refs == ("provider-run://custom.peer/live-smoke-1",)
    assert reloaded is not None
    assert reloaded.registration.cli_id == "custom.peer"
    assert reloaded.registered_by == "operator-1"
    assert reloaded.audit_id == "operator-action:audit-1"
    assert reloaded.source_authority == "operator_action_contract"
    assert reloaded.proof_level == "contract_proof"
    assert raw["schema_version"] == "xmuse.god_cli_registration_store.v1"


def test_god_cli_registration_store_replaces_one_cli_only(tmp_path: Path) -> None:
    store = GodCliRegistrationStore(tmp_path / "god_cli_registrations.json")

    store.record_registration(
        registration=_registration("custom.peer"),
        registered_by="operator-1",
        audit_id="operator-action:audit-1",
        idempotency_key="idem-register-1",
    )
    store.record_registration(
        registration=_registration("other.peer"),
        registered_by="operator-2",
        audit_id="operator-action:audit-2",
        idempotency_key="idem-register-2",
    )
    store.record_registration(
        registration=_registration("custom.peer"),
        registered_by="operator-3",
        audit_id="operator-action:audit-3",
        idempotency_key="idem-register-3",
    )

    custom = store.get("custom.peer")
    other = store.get("other.peer")
    assert custom is not None
    assert other is not None
    assert custom.registered_by == "operator-3"
    assert custom.audit_id == "operator-action:audit-3"
    assert other.registered_by == "operator-2"
    assert [item.cli_id for item in store.list_registrations()] == [
        "custom.peer",
        "other.peer",
    ]
