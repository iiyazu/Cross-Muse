from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def test_god_cli_selection_store_persists_selected_cli(tmp_path: Path) -> None:
    store_path = tmp_path / "god_cli_selections.json"
    store = GodCliSelectionStore(store_path)

    record = store.record_selection(
        conversation_id="conv-1",
        cli_id="codex.god",
        selected_by="operator-1",
        audit_id="operator-action:audit-1",
        idempotency_key="idem-1",
    )

    reloaded = GodCliSelectionStore(store_path).get("conv-1")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert record.cli_id == "codex.god"
    assert reloaded is not None
    assert reloaded.cli_id == "codex.god"
    assert reloaded.selected_by == "operator-1"
    assert reloaded.audit_id == "operator-action:audit-1"
    assert reloaded.source_authority == "operator_action_contract"
    assert reloaded.proof_level == "contract_proof"
    assert raw["schema_version"] == "xmuse.god_cli_selection_store.v1"


def test_god_cli_selection_store_replaces_one_conversation_only(tmp_path: Path) -> None:
    store = GodCliSelectionStore(tmp_path / "god_cli_selections.json")

    store.record_selection(
        conversation_id="conv-1",
        cli_id="codex.god",
        selected_by="operator-1",
        audit_id="operator-action:audit-1",
        idempotency_key="idem-1",
    )
    store.record_selection(
        conversation_id="conv-2",
        cli_id="codex.god",
        selected_by="operator-2",
        audit_id="operator-action:audit-2",
        idempotency_key="idem-2",
    )
    store.record_selection(
        conversation_id="conv-1",
        cli_id="codex.god",
        selected_by="operator-3",
        audit_id="operator-action:audit-3",
        idempotency_key="idem-3",
    )

    conv_1 = store.get("conv-1")
    conv_2 = store.get("conv-2")
    assert conv_1 is not None
    assert conv_2 is not None
    assert conv_1.selected_by == "operator-3"
    assert conv_1.audit_id == "operator-action:audit-3"
    assert conv_2.selected_by == "operator-2"
