from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from xmuse_core.platform.provider_read_contracts import (
    build_provider_inventory,
    build_provider_selection_records,
)
from xmuse_core.platform.read_contracts import (
    build_blueprint_contract,
    build_graph_set_contract,
    build_graph_set_summary,
    build_lane_contract,
    build_review_contract,
    build_takeover_context,
)


def test_lane_contract_has_discriminator() -> None:
    lane: dict[str, Any] = {"feature_id": "test", "id": "test"}
    contract = build_lane_contract(lane=lane, xmuse_root=Path("/tmp"))
    assert contract["kind"] == "lane_contract"
    assert contract["read_only"] is True
    assert contract["lane_id"] == "test"
    assert isinstance(contract.get("refs"), dict)
    assert "gate_report" in contract["refs"]
    assert "diff" in contract["refs"]
    assert "review" in contract["refs"]
    assert "health" in contract["refs"]


def test_lane_contract_minimal_input_returns_stable_structure() -> None:
    lane: dict[str, Any] = {}
    contract = build_lane_contract(lane=lane, xmuse_root=Path("/tmp"))
    assert contract["kind"] == "lane_contract"
    assert contract["read_only"] is True
    assert contract["lane_id"] == ""
    assert isinstance(contract.get("refs"), dict)
    assert contract["refs"]["health"]["tool"] == "read_health_contract"


def test_blueprint_contract_missing_store_raises_key_error() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        raised = False
        try:
            build_blueprint_contract(
                xmuse_root=xmuse_root,
                resolution_id="nonexistent",
            )
        except KeyError:
            raised = True
        assert raised, "expected KeyError for missing chat.db"


def test_graph_set_contract_missing_id_raises_key_error() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        lanes_path = xmuse_root / "feature_lanes.json"
        lanes_path.write_text('{"lanes": []}')
        raised = False
        try:
            build_graph_set_contract(
                graph_set_id="nonexistent",
                lanes_path=lanes_path,
                xmuse_root=xmuse_root,
            )
        except KeyError:
            raised = True
        assert raised, "expected KeyError for nonexistent graph_set_id"


def test_graph_set_summary_missing_id_raises_key_error() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        lanes_path = xmuse_root / "feature_lanes.json"
        lanes_path.write_text('{"lanes": []}')
        raised = False
        try:
            build_graph_set_summary(
                graph_set_id="nonexistent",
                lanes_path=lanes_path,
                xmuse_root=xmuse_root,
            )
        except KeyError:
            raised = True
        assert raised, "expected KeyError for nonexistent graph_set_id"


def test_review_contract_has_discriminator() -> None:
    contract = build_review_contract(lane_id="test", xmuse_root=Path("/tmp"))
    assert contract["kind"] == "review_contract"
    assert contract["read_only"] is True
    assert contract["lane_id"] == "test"
    assert isinstance(contract.get("counts"), dict)
    assert "tasks" in contract["counts"]
    assert "verdicts" in contract["counts"]


def test_takeover_context_has_discriminator() -> None:
    lane: dict[str, Any] = {"feature_id": "test", "id": "test"}
    context = build_takeover_context(
        lane=lane,
        all_lanes=[lane],
        xmuse_root=Path("/tmp"),
    )
    assert context["kind"] == "takeover_context"
    assert context["read_only"] is True
    assert context["lane_id"] == "test"
    assert isinstance(context.get("supported_actions"), list)


def test_conversation_inspector_contract_has_discriminator() -> None:
    from xmuse_core.chat.participant_store import ParticipantStore
    from xmuse_core.chat.store import ChatStore
    from xmuse_core.platform.read_contracts import build_conversation_inspector_contract

    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        chat = ChatStore(xmuse_root / "chat.db")
        conv = chat.create_conversation("Test")
        ParticipantStore(xmuse_root / "chat.db").add(
            conversation_id=conv.id, role="architect",
            display_name="Arch", cli_kind="codex", model="gpt-5.5",
        )
        contract = build_conversation_inspector_contract(
            conversation_id=conv.id, xmuse_root=xmuse_root,
        )
    assert contract["kind"] == "conversation_inspector"
    assert contract["read_only"] is True
    assert contract["conversation"]["id"] == conv.id
    assert contract["conversation"]["title"] == "Test"
    assert "participants" in contract
    assert contract["participants"]["total"] == 1
    assert "recent_activity" in contract
    assert "current_blueprint" in contract
    assert "current_feature_plan" in contract
    assert "current_graph_set" in contract
    assert "refs" in contract


def test_conversation_inspector_contract_stable_with_missing_conversation() -> None:
    from xmuse_core.chat.store import ChatStore
    from xmuse_core.platform.read_contracts import build_conversation_inspector_contract

    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        ChatStore(xmuse_root / "chat.db")
        raised = False
        try:
            build_conversation_inspector_contract(
                conversation_id="nonexistent", xmuse_root=xmuse_root,
            )
        except KeyError:
            raised = True
    assert raised, "expected KeyError for nonexistent conversation"


def test_feature_plan_contract_missing_plan_raises_key_error() -> None:
    from xmuse_core.platform.read_contracts import build_feature_plan_contract

    with TemporaryDirectory() as tmp:
        raised = False
        try:
            build_feature_plan_contract(
                feature_plan_id="nonexistent",
                lanes_path=Path(tmp) / "feature_lanes.json",
                xmuse_root=Path(tmp),
            )
        except KeyError:
            raised = True
    assert raised, "expected KeyError for nonexistent feature plan"


def test_conversation_inspector_contract_includes_contract_refs() -> None:
    from xmuse_core.chat.participant_store import ParticipantStore
    from xmuse_core.chat.store import ChatStore
    from xmuse_core.platform.read_contracts import build_conversation_inspector_contract

    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        chat = ChatStore(xmuse_root / "chat.db")
        conv = chat.create_conversation("Refs")
        ParticipantStore(xmuse_root / "chat.db").add(
            conversation_id=conv.id, role="architect",
            display_name="Arch", cli_kind="codex", model="gpt-5.5",
        )
        contract = build_conversation_inspector_contract(
            conversation_id=conv.id, xmuse_root=xmuse_root,
        )
    assert "refs" in contract
    assert "self" in contract["refs"]
    assert "conversation_detail" in contract["refs"]


def test_provider_inventory_has_consistent_kind() -> None:
    inventory = build_provider_inventory()
    assert inventory["kind"] == "provider_inventory"
    assert inventory["read_only"] is True
    assert inventory["counts"]["providers"] >= 1
    assert inventory["counts"]["profiles"] >= inventory["counts"]["providers"]
    assert isinstance(inventory["provider_ids"], list)
    assert isinstance(inventory["providers"], list)


def test_provider_selection_records_has_consistent_kind() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        records = build_provider_selection_records(xmuse_root=xmuse_root)
        assert records["kind"] == "provider_selection_records"
        assert records["read_only"] is True
        assert records["source_authority"] == "provider_selection_records_read_model"
        assert records["generated_at"].endswith("Z")
        assert isinstance(records["filters"], dict)
        assert isinstance(records["counts"], dict)
        assert isinstance(records["records"], list)
        assert records["records"] == []


def test_provider_selection_records_empty_input_returns_stable_structure() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        records = build_provider_selection_records(
            xmuse_root=xmuse_root,
            lane_id="nonexistent",
            limit=5,
        )
        assert records["filters"]["lane_id"] == "nonexistent"
        assert records["filters"]["limit"] == 5
        assert records["counts"]["records"] == 0
        assert records["records"] == []


def test_provider_selection_records_rejects_invalid_limit() -> None:
    with TemporaryDirectory() as tmp:
        xmuse_root = Path(tmp)
        raised = False
        try:
            build_provider_selection_records(xmuse_root=xmuse_root, limit=0)
        except ValueError:
            raised = True
        assert raised, "expected ValueError for limit=0"
        raised = False
        try:
            build_provider_selection_records(xmuse_root=xmuse_root, limit=-1)
        except ValueError:
            raised = True
        assert raised, "expected ValueError for limit=-1"


def test_review_contract_empty_store_returns_empty_counts() -> None:
    contract = build_review_contract(
        lane_id="nonexistent",
        xmuse_root=Path("/tmp"),
    )
    assert contract["counts"]["tasks"] == 0
    assert contract["counts"]["verdicts"] == 0
    assert contract["latest_task"] is None
    assert contract["latest_verdict"] is None
