from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, cast

from xmuse.memoryos_delivery_pump import MemoryOSDeliveryClient, MemoryOSDeliveryPump
from xmuse.memoryos_runtime_adapter import (
    DisabledRoomMemoryRuntime,
)
from xmuse_core.chat.room_memory_runtime import (
    RoomMemoryContextReceiptPort,
    RoomMemoryDeliveryPumpPort,
    RoomMemoryEvidence,
    RoomMemoryRecallInput,
    RoomMemoryRecallPort,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "http": REPO_ROOT / "xmuse" / "memoryos_http_client.py",
    "evidence": REPO_ROOT / "xmuse" / "memoryos_evidence.py",
    "delivery": REPO_ROOT / "xmuse" / "memoryos_delivery_pump.py",
    "recall": REPO_ROOT / "xmuse" / "memoryos_recall_runtime.py",
    "runtime": REPO_ROOT / "xmuse" / "memoryos_runtime_adapter.py",
    "compat": REPO_ROOT / "xmuse" / "memoryos_adapter.py",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _port_imports(path: Path) -> set[str]:
    return {
        alias.name
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom) and node.module == "xmuse_core.chat.room_memory_ports"
        for alias in node.names
    }


def _modules(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
    return result


def test_components_import_only_their_frozen_persistence_ports() -> None:
    assert _port_imports(MODULES["http"]) == set()
    assert _port_imports(MODULES["evidence"]) == {"RoomMemoryRecallSourceRequestPort"}
    assert _port_imports(MODULES["delivery"]) == {
        "RoomMemoryBindingSessionAttachmentPort",
        "RoomMemoryDocumentOutboxPort",
        "RoomMemoryMessageOutboxPort",
    }
    assert _port_imports(MODULES["recall"]) == {
        "RoomMemoryAdvisoryGovernancePort",
        "RoomMemoryRecallReceiptContextPort",
        "RoomMemoryRecallSourceRequestPort",
    }
    assert _port_imports(MODULES["runtime"]) == {"RoomMemoryRecallReceiptContextPort"}


def test_application_adapter_never_imports_concrete_memory_stores() -> None:
    for name, path in MODULES.items():
        imports = _modules(path)
        assert not any(module.endswith("_store") for module in imports), name
    assert "xmuse_core.chat.room_memory_ports" not in _modules(MODULES["http"])


def test_split_components_do_not_probe_for_optional_store_capabilities() -> None:
    capability_names = {
        "claim_next_message_outbox",
        "complete_message_delivery",
        "list_advisories",
        "record_external_advisories",
        "resolve_recall_message_source",
    }
    for name in ("delivery", "recall", "evidence"):
        dynamic_capabilities = {
            node.args[1].value
            for node in ast.walk(_tree(MODULES[name]))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        }
        assert capability_names.isdisjoint(dynamic_capabilities)


class _Recall:
    recall_timeout_s = 0.5

    def __init__(self) -> None:
        self.receipts = 0
        self.binds = 0

    async def recall(self, _request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        return _evidence()

    def record_recall_receipt(self, *, attempt_id: str, evidence: RoomMemoryEvidence) -> None:
        assert attempt_id and evidence.status == "empty"
        self.receipts += 1

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        included_items=(),
    ) -> None:
        assert attempt_id and evidence_sha256 and context_payload_sha256
        assert included_items == ()
        self.binds += 1


class _Pump:
    def __init__(self) -> None:
        self.calls = 0

    async def pump_once(self) -> bool:
        self.calls += 1
        return True


def _evidence() -> RoomMemoryEvidence:
    return RoomMemoryEvidence(
        status="empty",
        reason_code="room_memory_no_evidence",
        schema_version="memoryos_source_evidence/v1",
        latency_ms=0,
        evidence_sha256="sha256:" + "0" * 64,
    )


def _request() -> RoomMemoryRecallInput:
    return RoomMemoryRecallInput(
        conversation_id="conversation-1",
        attempt_id="attempt-1",
        correlation_id="correlation-1",
        task="task",
        causal_activity_ids=(),
    )


def test_split_runtime_capabilities_operate_without_a_wide_facade() -> None:
    recall = _Recall()
    pump = _Pump()
    recall_port = cast(RoomMemoryRecallPort, recall)
    context_port = cast(RoomMemoryContextReceiptPort, recall)
    delivery_port = cast(RoomMemoryDeliveryPumpPort, pump)

    evidence = asyncio.run(recall_port.recall(_request()))
    recall_port.record_recall_receipt(attempt_id="attempt-1", evidence=evidence)
    context_port.bind_context_receipt(
        attempt_id="attempt-1",
        evidence_sha256=evidence.evidence_sha256,
        context_payload_sha256="sha256:" + "1" * 64,
    )

    assert asyncio.run(delivery_port.pump_once()) is True
    assert (recall.receipts, recall.binds, pump.calls) == (1, 1, 1)


class _ReceiptOnly:
    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []
        self.binds: list[dict[str, Any]] = []

    def record_attempt_memory_receipt(self, **kwargs: Any) -> dict[str, Any]:
        self.receipts.append(kwargs)
        return kwargs

    def bind_attempt_memory_context(self, **kwargs: Any) -> dict[str, Any]:
        self.binds.append(kwargs)
        return kwargs


def test_disabled_runtime_needs_only_receipt_context_authority() -> None:
    store = _ReceiptOnly()
    runtime = DisabledRoomMemoryRuntime(store)
    evidence = asyncio.run(runtime.recall(_request()))
    runtime.record_recall_receipt(attempt_id="attempt-1", evidence=evidence)
    runtime.bind_context_receipt(
        attempt_id="attempt-1",
        evidence_sha256=evidence.evidence_sha256,
        context_payload_sha256="sha256:" + "1" * 64,
    )

    assert evidence.status == "disabled"
    assert len(store.receipts) == len(store.binds) == 1


class _BindingEmpty:
    def list_pending_bindings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        assert limit == 20
        return []


class _MessageUnused:
    pass


class _DocumentEmpty:
    def __init__(self) -> None:
        self.requeue_calls = 0

    def requeue_retryable_failed_outbox(self, **_kwargs: Any) -> list[dict[str, Any]]:
        self.requeue_calls += 1
        return []

    def claim_next_outbox(self, **_kwargs: Any) -> None:
        return None


class _Client:
    profile = "archive-only"

    def __init__(self) -> None:
        self.health_calls = 0

    def health(self, **_kwargs: Any) -> dict[str, str]:
        self.health_calls += 1
        return {"status": "ok"}


def test_archive_delivery_does_not_require_the_message_port_at_runtime() -> None:
    document = _DocumentEmpty()
    client = _Client()
    pump = MemoryOSDeliveryPump(
        binding_store=cast(Any, _BindingEmpty()),
        message_store=cast(Any, _MessageUnused()),
        document_store=cast(Any, document),
        client=cast(MemoryOSDeliveryClient, client),
        worker_id="worker-1",
    )

    assert asyncio.run(pump.pump_once()) is False
    assert (document.requeue_calls, client.health_calls) == (1, 1)
