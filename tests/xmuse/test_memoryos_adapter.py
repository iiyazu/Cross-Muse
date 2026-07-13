from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

import pytest

from xmuse.memoryos_adapter import (
    ArchiveOnlyRoomMemoryRuntime,
    MemoryOSAdapterError,
)
from xmuse_core.chat.room_memory_runtime import RoomMemoryRecallInput


def _sha(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _v3_item(
    *,
    text: str = "prior durable fact",
    correlation_id: str = "correlation-old",
) -> dict[str, Any]:
    del correlation_id
    return {
        "layer": "archival",
        "item_id": "memory-item-1",
        "text": text,
        "estimated_tokens": 4,
        "source_refs": [
            {
                "source_type": "document",
                "source_id": "activity-prior",
                "metadata": {"conversation_id": "untrusted-value"},
            }
        ],
        "metadata": {"document_id": "xmuse-room-activity-activity-prior"},
    }


def _v3_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metadata": {
            "v3_context": {
                "metadata": {"memory_arch": "v3"},
                "items": [dict(item)],
            }
        }
    }


class _StoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FakeStore:
    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []
        self.binds: list[dict[str, Any]] = []
        self.completions: list[dict[str, Any]] = []
        self.requeue_calls: list[int] = []
        self.claim: dict[str, Any] | None = None
        self.reopened: list[str] = []
        self.bindings: list[dict[str, Any]] = []
        self.source_correlation = "correlation-old"
        self.reject_source = False
        self.requeue_result: list[dict[str, Any]] = []
        self.expected_text = "prior durable fact"

    def build_recall_request(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "session_id": "memory-session-1",
            "task": "recall prior evidence",
            "retrieval_query": "current task",
            "excluded_activity_ids": [],
            "excluded_document_ids": [],
        }

    def resolve_recall_source(self, **kwargs: Any) -> dict[str, Any]:
        if self.reject_source or kwargs["item_text"] != self.expected_text:
            raise _StoreError("room_memory_recall_source_rejected")
        assert kwargs["content_sha256"] == _sha(self.expected_text)
        assert kwargs["document_id"] == "xmuse-room-activity-activity-prior"
        return {
            "source_type": "room_activity",
            "authority_content": f"prefix {self.expected_text} suffix",
            "source_activities": [
                {
                    "activity_id": "activity-prior",
                    "conversation_id": "conversation-1",
                    "correlation_id": self.source_correlation,
                }
            ],
        }

    def record_attempt_memory_receipt(self, **kwargs: Any) -> dict[str, Any]:
        self.receipts.append(kwargs)
        return kwargs

    def bind_attempt_memory_context(self, **kwargs: Any) -> dict[str, Any]:
        self.binds.append(kwargs)
        return kwargs

    def list_pending_bindings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        assert limit == 20
        return self.bindings

    def reopen_uncertain_binding(self, **kwargs: Any) -> dict[str, Any]:
        self.reopened.append(str(kwargs["binding_id"]))
        return kwargs

    def reserve_session_create(self, **kwargs: Any) -> dict[str, Any]:
        return {**kwargs, "revision": int(kwargs["expected_revision"]) + 1}

    def complete_session_create(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs

    def reserve_attachment(self, **kwargs: Any) -> dict[str, Any]:
        return {**kwargs, "revision": int(kwargs["expected_revision"]) + 1}

    def complete_attachment(self, **kwargs: Any) -> dict[str, Any]:
        self.completions.append(kwargs)
        return kwargs

    def requeue_retryable_failed_outbox(
        self, *, limit: int = 20, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        self.requeue_calls.append(limit)
        result = self.requeue_result
        self.requeue_result = []
        return result

    def claim_next_outbox(self, **_kwargs: Any) -> dict[str, Any] | None:
        result = self.claim
        self.claim = None
        return result

    def complete_delivery(self, **kwargs: Any) -> dict[str, Any]:
        self.completions.append(kwargs)
        return kwargs

    def requeue_outbox(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"immediate requeue forbidden: {kwargs}")


class FakeAdapter:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.health_calls = 0
        self.attach_calls: list[dict[str, Any]] = []
        self.ingest_error: MemoryOSAdapterError | None = None

    def build_context(self, **_kwargs: Any) -> Mapping[str, Any]:
        return self.payload

    def health(self, **_kwargs: Any) -> dict[str, str]:
        self.health_calls += 1
        return {"status": "ok"}

    def attach_archive(self, **kwargs: Any) -> dict[str, Any]:
        self.attach_calls.append(kwargs)
        return {
            "attachment_id": "attachment-1",
            "archive_id": kwargs["archive_id"],
            "scope_id": kwargs["session_id"],
        }

    def ingest_document(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if self.ingest_error is not None:
            raise self.ingest_error
        return {"document_id": request["document_id"], "passage_ids": ["passage-1"]}


def _runtime(store: FakeStore, adapter: FakeAdapter) -> ArchiveOnlyRoomMemoryRuntime:
    return ArchiveOnlyRoomMemoryRuntime(  # type: ignore[arg-type]
        store,
        store,
        adapter,  # type: ignore[arg-type]
        worker_id="memory-worker-1",
    )


def _request() -> RoomMemoryRecallInput:
    return RoomMemoryRecallInput(
        conversation_id="conversation-1",
        attempt_id="attempt-1",
        correlation_id="correlation-current",
        task="current task",
        causal_activity_ids=(),
    )


def test_v3_archival_recall_is_source_resolved_and_receipt_is_two_stage() -> None:
    store = FakeStore()
    runtime = _runtime(store, FakeAdapter(_v3_payload(_v3_item())))

    evidence = asyncio.run(runtime.recall(_request()))

    assert evidence.status == "ok"
    assert evidence.items[0].source_activity_ids == ("activity-prior",)
    assert evidence.items[0].document_id == "xmuse-room-activity-activity-prior"
    runtime.record_recall_receipt(attempt_id="attempt-1", evidence=evidence)
    assert store.receipts[0]["items"] == [
        {
            "item_id": "memory-item-1",
            "document_id": "xmuse-room-activity-activity-prior",
            "source_activity_ids": ["activity-prior"],
            "content_sha256": _sha("prior durable fact"),
            "text": "prior durable fact",
        }
    ]
    assert store.binds == []
    runtime.bind_context_receipt(
        attempt_id="attempt-1",
        evidence_sha256=evidence.evidence_sha256,
        context_payload_sha256="sha256:" + "a" * 64,
    )
    assert store.binds[0]["evidence_sha256"] == evidence.evidence_sha256


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"text": "top-level fake"}, "schema_rejected"),
        (
            {"metadata": {"v3_context": {"metadata": {}, "items": []}}},
            "schema_rejected",
        ),
    ],
)
def test_recall_rejects_non_v3_or_top_level_simplified_text(
    payload: Mapping[str, Any], expected: str
) -> None:
    evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))
    assert evidence.status == expected
    assert evidence.items == ()


def test_recall_rejects_forged_text_and_filters_current_correlation() -> None:
    forged = asyncio.run(
        _runtime(
            FakeStore(),
            FakeAdapter(_v3_payload(_v3_item(text="forged memory text"))),
        ).recall(_request())
    )
    assert forged.status == "source_rejected"

    store = FakeStore()
    store.source_correlation = "correlation-current"
    filtered = asyncio.run(_runtime(store, FakeAdapter(_v3_payload(_v3_item()))).recall(_request()))
    assert filtered.status == "empty"
    assert filtered.items == ()


def test_attachment_uses_real_document_source_ref_contract() -> None:
    store = FakeStore()
    store.bindings = [
        {
            "binding_id": "binding-1",
            "conversation_id": "conversation-1",
            "scope_type": "project",
            "archive_id": "archive-project",
            "session_id": "session-1",
            "session_state": "bound",
            "attachment_state": "pending",
            "revision": 4,
        }
    ]
    adapter = FakeAdapter(_v3_payload(_v3_item()))

    assert asyncio.run(_runtime(store, adapter).pump_once()) is True

    source_ref = adapter.attach_calls[0]["source_refs"][0]
    assert source_ref == {
        "source_type": "document",
        "source_id": "xmuse-room-binding-conversation-1",
        "session_id": "session-1",
        "metadata": {"scope_type": "project"},
    }
    assert store.completions[-1]["attachment_id"] == "attachment-1"


def test_transient_ingest_failure_stays_failed_until_health_gated_durable_reopen() -> None:
    store = FakeStore()
    store.claim = {
        "outbox": {"outbox_id": "outbox-1"},
        "delivery": {
            "delivery_id": "delivery-1",
            "lease_token": "lease-1",
            "attempt_number": 1,
        },
        "document_request": {
            "document_id": "xmuse-room-activity-activity-prior",
            "title": "prior",
            "content": "prior durable fact",
        },
    }
    adapter = FakeAdapter(_v3_payload(_v3_item()))
    adapter.ingest_error = MemoryOSAdapterError("memoryos_unavailable")
    runtime = _runtime(store, adapter)

    with pytest.raises(MemoryOSAdapterError):
        asyncio.run(runtime.pump_once())
    assert store.completions[-1]["status"] == "failed"
    assert store.requeue_calls == [1]

    adapter.ingest_error = None
    store.requeue_result = [{"outbox_id": "outbox-1", "state": "pending"}]
    assert asyncio.run(runtime.pump_once()) is True
    assert store.requeue_calls == [1, 1]
    assert adapter.health_calls == 2


class _HttpResponse:
    status = 200

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.raw if size < 0 else self.raw[:size]


class _HttpOpener:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, **_kwargs):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def test_http_adapter_bounds_json_disables_redirects_and_keeps_key_out_of_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_adapter import MemoryOSArchiveAdapter

    bad_json = _HttpOpener([_HttpResponse(b"not-json")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: bad_json)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")
    assert exc_info.value.code == "memoryos_response_invalid"
    request = bad_json.requests[0]
    assert "server-key" not in request.full_url
    assert request.get_header("X-api-key") == "server-key"

    real_shape = {
        "metadata": {
            "v3_context": {
                # MemoryOS v3 can emit diagnostics larger than the final context;
                # xmuse still admits only the bounded items below.
                "metadata": {"memory_arch": "v3", "diagnostics": "x" * 600_000},
                "items": [],
            }
        }
    }
    real_shape_opener = _HttpOpener([_HttpResponse(json.dumps(real_shape).encode("utf-8"))])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: real_shape_opener)
    assert (
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")[
            "metadata"
        ]["v3_context"]["items"]
        == []
    )

    oversized = _HttpOpener([_HttpResponse(b"{" + b"x" * (1024 * 1024) + b"}")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: oversized)
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")
    assert exc_info.value.code == "memoryos_response_too_large"

    redirect = urllib.error.HTTPError(
        "http://127.0.0.1:8301/sessions",
        302,
        "redirect",
        hdrs=None,
        fp=None,
    )
    redirected = _HttpOpener([redirect])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: redirected)
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.create_session(title="room")
    assert exc_info.value.code == "memoryos_http_error"

    timed_out = _HttpOpener([TimeoutError("late")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: timed_out)
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.health()
    assert exc_info.value.code == "memoryos_unavailable"


def test_archive_ingest_accepts_replay_and_reports_content_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_adapter import MemoryOSArchiveAdapter

    response = b'{"document_id":"doc-1","passage_ids":["passage-1"]}'
    conflict = urllib.error.HTTPError(
        "http://127.0.0.1:8301/archives/ingest",
        409,
        "conflict",
        hdrs=None,
        fp=None,
    )
    opener = _HttpOpener([_HttpResponse(response), _HttpResponse(response), conflict])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: opener)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")
    request = {
        "document_id": "doc-1",
        "title": "title",
        "content": "same content",
    }

    assert adapter.ingest_document(request)["document_id"] == "doc-1"
    assert adapter.ingest_document(request)["document_id"] == "doc-1"
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.ingest_document({**request, "content": "different content"})
    assert exc_info.value.code == "memoryos_document_conflict"


def test_final_memory_evidence_stays_within_eight_kib_and_oversize_fails_closed() -> None:
    too_large = "m" * 8_100
    store = FakeStore()
    store.expected_text = too_large
    item = _v3_item(text=too_large)
    item["estimated_tokens"] = 200

    evidence = asyncio.run(_runtime(store, FakeAdapter(_v3_payload(item))).recall(_request()))

    assert evidence.status == "oversize"
    assert evidence.items == ()

    first = "a" * 4_000
    store = FakeStore()
    store.expected_text = first
    item_one = _v3_item(text=first)
    item_one["estimated_tokens"] = 200
    item_two = {**item_one, "item_id": "memory-item-2"}
    payload = {
        "metadata": {
            "v3_context": {
                "metadata": {"memory_arch": "v3"},
                "items": [item_one, item_two],
            }
        }
    }
    bounded = asyncio.run(_runtime(store, FakeAdapter(payload)).recall(_request()))
    assert bounded.status == "ok"
    assert len(bounded.items) == 1
    encoded = json.dumps(
        bounded.context_payload(), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded) <= 8 * 1024
