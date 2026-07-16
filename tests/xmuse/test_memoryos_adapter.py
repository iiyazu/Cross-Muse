from __future__ import annotations

import asyncio
import hashlib
import json
import time
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


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _v3_item(
    *,
    text: str = "prior durable fact",
    correlation_id: str = "correlation-old",
) -> dict[str, Any]:
    del correlation_id
    return {
        "item_id": "memory-item-1",
        "archive_id": "archive-room-1",
        "document_id": "xmuse-room-activity-activity-prior",
        "source_refs": [
            {
                "source_type": "document",
                "source_id": "activity-prior",
            }
        ],
        "text": text,
        "estimated_tokens": 4,
        "content_sha256": _sha(text),
        "score": 0.75,
        "rank": 1,
        "truncated": False,
    }


def _compact_payload(*items: Mapping[str, Any], omitted_count: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "memoryos_source_evidence/v1",
        "items": [dict(item) for item in items],
        "omitted_count": omitted_count,
        "estimated_tokens": sum(int(item["estimated_tokens"]) for item in items),
        "truncated": omitted_count > 0,
    }
    payload["diagnostics_digest"] = _canonical_digest(payload)
    return payload


def _v3_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_payload(item)


def _v2_message_item(*, text: str = "prior durable fact") -> dict[str, Any]:
    return {
        "item_id": "memory-v2-item-1",
        "layer": "recall",
        "text": text,
        "estimated_tokens": 4,
        "content_sha256": _sha(text),
        "source_refs": [
            {
                "source_type": "message",
                "source_id": "message-1",
                "session_id": "memory-session-1",
            }
        ],
        "derived": True,
        "source_complete": True,
        "score": 0.8,
        "rank": 1,
        "truncated": False,
    }


def _v2_archival_candidate_item() -> dict[str, Any]:
    text = "approved project rule"
    return {
        "item_id": "archival-passage-1",
        "layer": "archival",
        "document_id": "xmuse-room-memory-candidate-candidate-1",
        "text": text,
        "estimated_tokens": 3,
        "content_sha256": _sha(text),
        "source_refs": [
            {
                "source_type": "document",
                "source_id": "activity-source-1",
                "session_id": "source-room-session",
            }
        ],
        "derived": False,
        "source_complete": True,
        "score": 0.9,
        "rank": 1,
        "truncated": False,
    }


def _v2_payload(*items: Mapping[str, Any], omitted_count: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "memoryos_source_evidence/v2",
        "items": [dict(item) for item in items],
        "omitted_count": omitted_count,
        "estimated_tokens": sum(int(item["estimated_tokens"]) for item in items),
        "truncated": omitted_count > 0,
    }
    payload["diagnostics_digest"] = _canonical_digest(payload)
    return payload


def _resign(payload: dict[str, Any]) -> dict[str, Any]:
    signed = {
        key: payload[key]
        for key in {
            "schema",
            "items",
            "omitted_count",
            "estimated_tokens",
            "truncated",
        }
    }
    payload["diagnostics_digest"] = _canonical_digest(signed)
    return payload


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
            "archive_ids": ["archive-room-1"],
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

    def resolve_recall_message_source(self, **kwargs: Any) -> dict[str, Any]:
        if self.reject_source or (
            not kwargs.get("derived", False) and kwargs["item_text"] != self.expected_text
        ):
            raise _StoreError("room_memory_recall_source_rejected")
        assert kwargs["session_id"] == "memory-session-1"
        assert kwargs["source_message_ids"] == ("message-1",)
        assert kwargs["content_sha256"] == _sha(kwargs["item_text"])
        assert kwargs["derived"] is True
        return {
            "source_type": "room_message",
            "document_id": "xmuse-room-activity-activity-prior",
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
        self.profile = "archive-only"
        self.message_calls: list[dict[str, Any]] = []

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

    def ingest_message(self, **kwargs: Any) -> dict[str, Any]:
        self.message_calls.append(kwargs)
        return {
            "message": {"id": "message-1", "external_id": kwargs["external_id"]},
            "replayed": False,
        }


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


def test_recall_timeout_is_bounded_and_returns_degraded_empty_evidence() -> None:
    class SlowAdapter(FakeAdapter):
        def build_context(self, **_kwargs: Any) -> Mapping[str, Any]:
            time.sleep(1.0)
            return self.payload

    store = FakeStore()
    evidence = asyncio.run(_runtime(store, SlowAdapter(_v3_payload(_v3_item()))).recall(_request()))

    assert evidence.status == "timeout"
    assert evidence.reason_code == "room_memory_timeout"
    assert evidence.items == ()
    assert evidence.latency_ms < 950


def test_full_local_v2_message_source_is_reproved_to_room_activity() -> None:
    store = FakeStore()
    adapter = FakeAdapter(_v2_payload(_v2_message_item()))
    adapter.profile = "full-local"

    evidence = asyncio.run(_runtime(store, adapter).recall(_request()))

    assert evidence.status == "ok"
    assert evidence.schema_version == "memoryos_source_evidence/v2"
    assert evidence.items[0].document_id == "xmuse-room-activity-activity-prior"
    assert evidence.items[0].source_activity_ids == ("activity-prior",)


def test_full_local_v2_derived_message_text_uses_complete_source_refs_not_excerpt() -> None:
    store = FakeStore()
    item = _v2_message_item()
    item["text"] = "derived episode summary that is not a source excerpt"
    item["content_sha256"] = _sha(item["text"])
    adapter = FakeAdapter(_v2_payload(item))
    adapter.profile = "full-local"

    evidence = asyncio.run(_runtime(store, adapter).recall(_request()))

    assert evidence.status == "ok"
    assert evidence.items[0].derived is True
    assert evidence.items[0].source_activity_ids == ("activity-prior",)


def test_full_local_v2_archival_candidate_uses_explicit_document_identity() -> None:
    store = FakeStore()
    store.expected_text = "approved project rule"

    def resolve_candidate(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["document_id"] == "xmuse-room-memory-candidate-candidate-1"
        assert kwargs["source_activity_ids"] == ("activity-source-1",)
        assert kwargs["content_sha256"] == _sha("approved project rule")
        return {
            "source_type": "room_memory_candidate",
            "document_id": "xmuse-room-memory-candidate-candidate-1",
            "source_activities": [
                {
                    "activity_id": "activity-source-1",
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-old",
                }
            ],
        }

    store.resolve_recall_source = resolve_candidate  # type: ignore[method-assign]
    adapter = FakeAdapter(_v2_payload(_v2_archival_candidate_item()))
    adapter.profile = "full-local"

    evidence = asyncio.run(_runtime(store, adapter).recall(_request()))

    assert evidence.status == "ok"
    assert evidence.items[0].source_activity_ids == ("activity-source-1",)
    assert evidence.items[0].document_id == "xmuse-room-memory-candidate-candidate-1"


def test_full_local_v2_archival_requires_explicit_document_identity() -> None:
    item = _v2_archival_candidate_item()
    del item["document_id"]
    adapter = FakeAdapter(_v2_payload(item))
    adapter.profile = "full-local"

    evidence = asyncio.run(_runtime(FakeStore(), adapter).recall(_request()))

    assert evidence.status == "source_rejected"
    assert evidence.reason_code == "room_memory_source_rejected"


def test_full_local_v2_message_source_rejects_missing_session_scope() -> None:
    item = _v2_message_item()
    item["source_refs"] = [{"source_type": "message", "source_id": "message-1"}]
    adapter = FakeAdapter(_v2_payload(item))
    adapter.profile = "full-local"

    evidence = asyncio.run(_runtime(FakeStore(), adapter).recall(_request()))

    assert evidence.status == "unavailable"
    assert evidence.reason_code == "memoryos_source_evidence_capability_drift"


def test_full_local_v2_rejects_unknown_envelope_fields() -> None:
    payload = _v2_payload(_v2_message_item())
    payload["unexpected"] = "must fail closed"
    evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))

    assert evidence.status == "unavailable"
    assert evidence.reason_code == "memoryos_source_evidence_capability_drift"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"text": "top-level fake"}, "unavailable"),
        ({"metadata": {"v3_context": {"metadata": {}, "items": []}}}, "unavailable"),
    ],
)
def test_recall_rejects_non_v3_or_top_level_simplified_text(
    payload: Mapping[str, Any], expected: str
) -> None:
    evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))
    assert evidence.status == expected
    assert evidence.reason_code == "memoryos_source_evidence_capability_drift"
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


def test_compact_wire_accepts_extensions_and_full_eight_item_budget() -> None:
    items = []
    for rank in range(1, 9):
        item = _v3_item()
        item.update(
            {
                "item_id": f"memory-item-{rank}",
                "estimated_tokens": 100,
                "rank": rank,
                "future_item_field": {"ignored": True},
            }
        )
        if rank == 1:
            item["item_id"] = "é" * 256
            item["source_refs"][0]["future_source_field"] = "ignored"
        items.append(item)
    payload = _compact_payload(*items)
    payload["future_top_level_field"] = "ignored"

    evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))

    assert evidence.status == "ok"
    assert len(evidence.items) == 8
    assert sum(item.estimated_tokens for item in evidence.items) == 800


def test_compact_rank_and_truncation_are_not_positional_or_derived() -> None:
    first = _v3_item()
    first.update({"rank": 8, "truncated": True})
    second = _v3_item()
    second.update({"item_id": "memory-item-2", "rank": 3})
    payload = _compact_payload(first, second)
    payload.update({"truncated": True, "omitted_count": 0})
    _resign(payload)

    evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))

    assert evidence.status == "ok"
    assert len(evidence.items) == 2


def test_compact_wire_drift_fails_closed_before_source_reproof() -> None:
    mutations: list[dict[str, Any]] = []

    wrong_rank = _v3_payload(_v3_item())
    wrong_rank["items"][0]["rank"] = True
    mutations.append(_resign(wrong_rank))

    bad_hash = _v3_payload(_v3_item())
    bad_hash["items"][0]["content_sha256"] = "sha256:" + "0" * 64
    mutations.append(_resign(bad_hash))

    missing_score = _v3_payload(_v3_item())
    missing_score["items"][0]["score"] = None
    mutations.append(_resign(missing_score))

    oversized_text = _v3_payload(_v3_item())
    oversized_text["items"][0]["text"] = "界" * 2_731
    oversized_text["items"][0]["content_sha256"] = _sha("界" * 2_731)
    mutations.append(_resign(oversized_text))

    oversized_utf8_id = _v3_payload(_v3_item())
    oversized_utf8_id["items"][0]["item_id"] = "界" * 171
    mutations.append(_resign(oversized_utf8_id))

    duplicate_refs = _v3_payload(_v3_item())
    duplicate_refs["items"][0]["source_refs"] *= 2
    mutations.append(_resign(duplicate_refs))

    cross_archive = _v3_payload(_v3_item())
    cross_archive["items"][0]["archive_id"] = "archive-other-room"
    mutations.append(_resign(cross_archive))

    duplicate_rank = _compact_payload(_v3_item(), {**_v3_item(), "item_id": "item-2"})
    mutations.append(duplicate_rank)

    out_of_range_rank = _v3_payload(_v3_item())
    out_of_range_rank["items"][0]["rank"] = 9
    mutations.append(_resign(out_of_range_rank))

    wrong_sum = _v3_payload(_v3_item())
    wrong_sum["estimated_tokens"] = 5
    mutations.append(_resign(wrong_sum))

    too_many = []
    for rank in range(1, 10):
        item = _v3_item()
        item.update({"item_id": f"item-{rank}", "rank": rank})
        too_many.append(item)
    mutations.append(_compact_payload(*too_many))

    too_much_text = []
    for rank in range(1, 6):
        text = str(rank) * 7_000
        item = _v3_item(text=text)
        item.update(
            {
                "item_id": f"large-item-{rank}",
                "estimated_tokens": 1,
                "rank": rank,
            }
        )
        too_much_text.append(item)
    mutations.append(_compact_payload(*too_much_text))

    bad_digest = _v3_payload(_v3_item())
    bad_digest["diagnostics_digest"] = "sha256:" + "0" * 64
    mutations.append(bad_digest)

    semantic_oversize = _v3_payload(_v3_item())
    semantic_oversize["future_top_level_field"] = "x" * (64 * 1024)
    mutations.append(semantic_oversize)

    for payload in mutations:
        evidence = asyncio.run(_runtime(FakeStore(), FakeAdapter(payload)).recall(_request()))
        assert evidence.status == "unavailable"
        assert evidence.reason_code == "memoryos_source_evidence_capability_drift"
        assert evidence.items == ()


def test_missing_compact_capability_is_stable_attention_not_room_failure() -> None:
    class _UnsupportedAdapter(FakeAdapter):
        def build_context(self, **_kwargs: Any) -> Mapping[str, Any]:
            raise MemoryOSAdapterError("memoryos_source_evidence_unsupported")

    evidence = asyncio.run(
        _runtime(FakeStore(), _UnsupportedAdapter(_compact_payload())).recall(_request())
    )

    assert evidence.status == "unavailable"
    assert evidence.reason_code == "memoryos_source_evidence_unsupported"
    assert evidence.items == ()


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


def test_full_local_pump_delivers_message_ledger_before_archive_ledger() -> None:
    store = FakeStore()
    store.claim_message: dict[str, Any] | None = {
        "outbox": {"message_outbox_id": "message-outbox-1"},
        "delivery": {
            "delivery_id": "message-delivery-1",
            "lease_token": "message-lease-1",
            "attempt_number": 1,
            "request_digest": _sha("request"),
        },
        "message_request": {
            "session_id": "session-1",
            "external_id": "xmuse-room-message-activity-1",
            "role": "assistant",
            "content": "durable reply",
            "metadata": {"activity_id": "activity-1"},
        },
    }

    def claim_message(**_kwargs: Any) -> dict[str, Any] | None:
        value = store.claim_message
        store.claim_message = None
        return value

    def complete_message(**kwargs: Any) -> dict[str, Any]:
        store.completions.append(kwargs)
        return kwargs

    store.claim_next_message_outbox = claim_message  # type: ignore[attr-defined]
    store.complete_message_delivery = complete_message  # type: ignore[attr-defined]
    store.requeue_retryable_failed_message_outbox = lambda **_kwargs: []  # type: ignore[attr-defined]
    adapter = FakeAdapter(_compact_payload())
    adapter.profile = "full-local"

    assert asyncio.run(_runtime(store, adapter).pump_once()) is True
    assert adapter.message_calls[0]["external_id"] == "xmuse-room-message-activity-1"
    assert store.completions[-1]["status"] == "delivered"


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

    health = json.dumps(
        {
            "status": "ok",
            "capabilities": {
                "build_context_profiles": ["full", "source_evidence/v1"],
            },
        }
    ).encode("utf-8")
    bad_json = _HttpOpener([_HttpResponse(health), _HttpResponse(b"not-json")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: bad_json)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")
    assert exc_info.value.code == "memoryos_source_evidence_capability_drift"
    request = bad_json.requests[1]
    assert "server-key" not in request.full_url
    assert request.get_header("X-api-key") == "server-key"
    assert json.loads(request.data or b"{}")["response_profile"] == "source_evidence/v1"

    real_shape = _compact_payload()
    real_shape_opener = _HttpOpener([_HttpResponse(json.dumps(real_shape).encode("utf-8"))])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: real_shape_opener)
    assert (
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")["items"]
        == []
    )

    oversized = _HttpOpener([_HttpResponse(b"{" + b"x" * (128 * 1024) + b"}")])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: oversized)
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query="query")
    assert exc_info.value.code == "memoryos_source_evidence_capability_drift"

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


def test_http_adapter_requires_advertised_compact_profile_without_full_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_adapter import MemoryOSArchiveAdapter

    health_without_profile = json.dumps(
        {
            "status": "ok",
            "capabilities": {"build_context_profiles": ["full"]},
        }
    ).encode("utf-8")
    unsupported = _HttpOpener([_HttpResponse(health_without_profile)])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: unsupported)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")

    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query=None)

    assert exc_info.value.code == "memoryos_source_evidence_unsupported"
    assert len(unsupported.requests) == 1
    assert unsupported.requests[0].full_url.endswith("/health")

    health_with_profile = json.dumps(
        {
            "status": "ok",
            "capabilities": {
                "build_context_profiles": ["full", "source_evidence/v1"],
            },
        }
    ).encode("utf-8")
    for status_code in (413, 422):
        validation_error = urllib.error.HTTPError(
            "http://127.0.0.1:8301/sessions/session-1/build-context",
            status_code,
            "compact contract rejected",
            hdrs=None,
            fp=None,
        )
        drifted = _HttpOpener([_HttpResponse(health_with_profile), validation_error])
        monkeypatch.setattr(
            urllib.request,
            "build_opener",
            lambda *_args, _drifted=drifted: _drifted,
        )
        adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")

        with pytest.raises(MemoryOSAdapterError) as exc_info:
            adapter.build_context(session_id="session-1", task="task", retrieval_query=None)

        assert exc_info.value.code == "memoryos_source_evidence_capability_drift"
        assert len(drifted.requests) == 2
        body = json.loads(drifted.requests[1].data or b"{}")
        assert body["response_profile"] == "source_evidence/v1"


def test_full_local_requires_v2_source_evidence_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_adapter import MemoryOSArchiveAdapter

    health = json.dumps(
        {"status": "ok", "capabilities": {"build_context_profiles": ["source_evidence/v1"]}}
    ).encode("utf-8")
    opener = _HttpOpener([_HttpResponse(health)])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: opener)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key", profile="full-local")
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.build_context(session_id="session-1", task="task", retrieval_query=None)
    assert exc_info.value.code == "memoryos_source_evidence_unsupported"
    assert len(opener.requests) == 1


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


def test_message_ingest_uses_public_nested_message_response_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_adapter import MemoryOSArchiveAdapter

    response = json.dumps(
        {
            "message": {
                "id": "message-1",
                "external_id": "xmuse-room-message-activity-1",
                "role": "assistant",
                "content": "durable reply",
            },
            "replayed": False,
        }
    ).encode("utf-8")
    conflict = urllib.error.HTTPError(
        "http://127.0.0.1:8301/sessions/session-1/ingest",
        409,
        "conflict",
        hdrs=None,
        fp=None,
    )
    opener = _HttpOpener([_HttpResponse(response), conflict])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: opener)
    adapter = MemoryOSArchiveAdapter("http://127.0.0.1:8301", "server-key")
    request = {
        "session_id": "session-1",
        "external_id": "xmuse-room-message-activity-1",
        "role": "assistant",
        "content": "durable reply",
        "metadata": {"activity_id": "activity-1"},
    }

    assert adapter.ingest_message(**request)["message"]["id"] == "message-1"
    with pytest.raises(MemoryOSAdapterError) as exc_info:
        adapter.ingest_message(**{**request, "content": "changed"})
    assert exc_info.value.code == "memoryos_message_conflict"
    assert opener.requests[0].full_url.endswith("/sessions/session-1/ingest")
    assert "server-key" not in opener.requests[0].full_url


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
    item_two["rank"] = 2
    payload = _compact_payload(item_one, item_two)
    bounded = asyncio.run(_runtime(store, FakeAdapter(payload)).recall(_request()))
    assert bounded.status == "ok"
    assert len(bounded.items) == 1
    encoded = json.dumps(
        bounded.context_payload(), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded) <= 8 * 1024
