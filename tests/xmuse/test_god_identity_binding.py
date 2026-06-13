from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.providers.god_identity_binding import (
    GodIdentityBindingStore,
    RoomSelectedGodBinding,
    build_operator_selected_god_binding,
)


def test_god_identity_binding_store_persists_and_resolves_room_binding(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "god_identity_bindings.json"
    store = GodIdentityBindingStore(store_path)
    account, profile, binding = build_operator_selected_god_binding(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="review-god",
        account_ref="codex.god",
        cli_command="codex",
        model="gpt-5.4",
        selected_by="operator-1",
        selected_at="2026-06-14T00:00:00Z",
        capabilities=("peer_god", "review"),
        role="review",
    )

    resolution = store.upsert_selection(
        provider_account=account,
        god_profile=profile,
        room_binding=binding,
    )

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    reloaded = GodIdentityBindingStore(store_path).resolve(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="review-god",
    )
    assert raw["schema_version"] == "xmuse.god_identity_binding_store.v1"
    assert resolution.status == "resolved"
    assert reloaded.status == "resolved"
    assert reloaded.account_ref == "codex.god"
    assert reloaded.binding_revision == "binding:god-room:conv-1:part-review:1"
    assert reloaded.source_refs == [
        "room_selected_god_binding:god-room:conv-1:part-review:binding:god-room:conv-1:part-review:1",
        "provider_account:codex.god",
        "god_profile:review-god",
    ]


def test_god_identity_binding_resolver_fails_closed_without_account(
    tmp_path: Path,
) -> None:
    store = GodIdentityBindingStore(tmp_path / "god_identity_bindings.json")
    binding = RoomSelectedGodBinding(
        room_id="god-room:conv-1",
        binding_revision="binding-rev-1",
        participant_id="part-review",
        god_id="review-god",
        account_ref="missing.account",
        cli_command="codex",
        model="gpt-5.4",
        proof_level="contract_proof",
        selected_by="operator-1",
        selected_at="2026-06-14T00:00:00Z",
    )

    store.upsert_room_binding(binding)
    resolution = store.resolve(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="review-god",
    )

    assert resolution.status == "manual_gap"
    assert resolution.proof_level == "manual_gap"
    assert resolution.blocked_reason == "provider account unavailable: missing.account"
    assert resolution.source_refs == [
        "room_selected_god_binding:god-room:conv-1:part-review:binding-rev-1"
    ]


def test_opencode_max_variant_must_not_be_encoded_in_model() -> None:
    with pytest.raises(ValueError, match="opencode max must be stored in variant"):
        RoomSelectedGodBinding(
            room_id="god-room:conv-1",
            binding_revision="binding-rev-1",
            participant_id="part-review",
            god_id="review-god",
            account_ref="opencode.deepseek",
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash:max",
            variant="max",
            proof_level="contract_proof",
            selected_by="operator-1",
            selected_at="2026-06-14T00:00:00Z",
        )


def test_opencode_model_and_max_variant_are_separate_fields(tmp_path: Path) -> None:
    store = GodIdentityBindingStore(tmp_path / "god_identity_bindings.json")
    account, profile, binding = build_operator_selected_god_binding(
        room_id="god-room:conv-1",
        participant_id="part-worker",
        god_id="bounded-worker",
        account_ref="opencode.deepseek_flash_worker",
        cli_command="opencode",
        model="opencode-go/deepseek-v4-flash",
        variant="max",
        selected_by="operator-1",
        selected_at="2026-06-14T00:00:00Z",
        capabilities=("bounded_code_writing",),
        role="bounded_worker",
    )

    resolution = store.upsert_selection(
        provider_account=account,
        god_profile=profile,
        room_binding=binding,
    )

    assert resolution.status == "resolved"
    assert resolution.cli_command == "opencode"
    assert resolution.model == "opencode-go/deepseek-v4-flash"
    assert resolution.variant == "max"
