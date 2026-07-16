from __future__ import annotations

import ast
from pathlib import Path

from xmuse_core.chat import room_memory_ports

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tree(relative: str) -> ast.Module:
    path = REPO_ROOT / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(relative: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def _protocol_methods(name: str) -> set[str]:
    protocol = getattr(room_memory_ports, name)
    return {
        key
        for key, value in protocol.__dict__.items()
        if callable(value) and not key.startswith("_")
    }


def test_memory_ports_are_six_frozen_non_overlapping_capabilities() -> None:
    expected = {
        "RoomMemoryBindingSessionAttachmentPort": {
            "list_pending_bindings",
            "reserve_session_create",
            "complete_session_create",
            "reserve_attachment",
            "complete_attachment",
            "reopen_uncertain_binding",
        },
        "RoomMemoryMessageOutboxPort": {
            "claim_next_message_outbox",
            "complete_message_delivery",
            "requeue_retryable_failed_message_outbox",
        },
        "RoomMemoryDocumentOutboxPort": {
            "claim_next_outbox",
            "complete_delivery",
            "requeue_retryable_failed_outbox",
        },
        "RoomMemoryRecallSourceRequestPort": {
            "build_recall_request",
            "resolve_recall_source",
            "resolve_recall_message_source",
        },
        "RoomMemoryRecallReceiptContextPort": {
            "record_attempt_memory_receipt",
            "bind_attempt_memory_context",
        },
        "RoomMemoryAdvisoryGovernancePort": {
            "record_external_advisories",
            "record_external_advisory_failure",
        },
    }
    observed: set[str] = set()
    for name, methods in expected.items():
        assert _protocol_methods(name) == methods
        assert observed.isdisjoint(methods)
        observed.update(methods)
    assert not hasattr(room_memory_ports, "RoomMemoryDeliveryStorePort")
    assert not hasattr(room_memory_ports, "RoomMemoryRecallStorePort")


def test_memoryos_components_do_not_import_concrete_stores() -> None:
    components = (
        "xmuse/memoryos_http_client.py",
        "xmuse/memoryos_evidence.py",
        "xmuse/memoryos_delivery_pump.py",
        "xmuse/memoryos_recall_runtime.py",
        "xmuse/memoryos_runtime_adapter.py",
    )
    for component in components:
        assert not {
            module
            for module in _imports(component)
            if module.startswith("xmuse_core.chat.room_memory_") and module.endswith("_store")
        }


def test_wide_store_facades_and_dynamic_capability_probes_are_gone() -> None:
    assert not (REPO_ROOT / "src/xmuse_core/chat/room_memory_delivery_store.py").exists()
    assert not (REPO_ROOT / "src/xmuse_core/chat/room_memory_recall_store.py").exists()
    projection = _tree("src/xmuse_core/chat/room_memory_projection.py")
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
        for node in ast.walk(projection)
    )
    adapter = _tree("xmuse/memoryos_adapter.py")
    assert not any(isinstance(node, ast.ClassDef) for node in adapter.body)


def test_neutral_connection_helpers_never_own_transaction_completion() -> None:
    for relative in (
        "src/xmuse_core/chat/room_memory_binding_conn.py",
        "src/xmuse_core/chat/room_memory_document_outbox_conn.py",
        "src/xmuse_core/chat/room_memory_source_conn.py",
    ):
        calls = {
            node.func.attr
            for node in ast.walk(_tree(relative))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint({"commit", "rollback", "close"})
