"""Archive-only HTTP adapter from durable Room memory state to MemoryOS Lite.

This application module intentionally imports no ``memoryos_lite`` package.  It uses
the four public HTTP contracts and treats every recall byte as untrusted until its
source references are resolved back to ``chat.db`` by the narrow recall store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_EVIDENCE_SCHEMA,
    ROOM_MEMORY_MAX_ITEMS,
    ROOM_MEMORY_MAX_RESPONSE_BYTES,
    ROOM_MEMORY_MAX_TOKENS,
    ROOM_MEMORY_RECALL_TIMEOUT_S,
    RoomMemoryEvidence,
    RoomMemoryEvidenceItem,
    RoomMemoryRecallInput,
    disabled_memory_evidence,
)

MEMORYOS_CONTEXT_SCHEMA = "memoryos_v3_context/v1"
MEMORYOS_DOCUMENT_PREFIX = "xmuse-room-activity-"
_MAX_REQUEST_BYTES = 64 * 1024
# MemoryOS v3 duplicates bounded retrieval diagnostics around archival items, so
# its transport envelope is materially larger than the evidence admitted into a
# Room prompt.  Keep that untrusted envelope bounded independently; validated
# ``memory_evidence`` remains capped at 8 KiB below.
_MEMORYOS_CONTEXT_HTTP_MAX_BYTES = 1024 * 1024
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class MemoryOSAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RoomMemoryDeliveryStoreProtocol(Protocol):
    def list_pending_bindings(self, *, limit: int = 20) -> list[dict[str, Any]]: ...

    def reserve_session_create(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def complete_session_create(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        session_id: str | None,
        uncertain: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def reserve_attachment(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def complete_attachment(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        attachment_id: str | None,
        uncertain: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def reopen_uncertain_binding(
        self,
        *,
        binding_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def claim_next_outbox(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any] | None: ...

    def complete_delivery(
        self,
        *,
        outbox_id: str,
        delivery_id: str,
        lease_token: str,
        status: Literal["delivered", "conflict", "failed"],
        request_digest: str,
        response_digest: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def requeue_retryable_failed_outbox(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...


class RoomMemoryRecallStoreProtocol(Protocol):
    def build_recall_request(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        correlation_id: str,
        causal_activity_ids: Sequence[str],
    ) -> dict[str, Any]: ...

    def resolve_recall_source(
        self,
        *,
        conversation_id: str,
        document_id: str,
        source_activity_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
    ) -> dict[str, Any]: ...

    def record_attempt_memory_receipt(
        self,
        *,
        attempt_id: str,
        status: str,
        schema_version: str | None,
        latency_ms: int,
        items: Sequence[Mapping[str, Any]],
        evidence_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def bind_attempt_memory_context(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class MemoryOSArchiveAdapter:
    base_url: str
    api_key: str = field(repr=False)
    default_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port is None
            or not (0 < parsed.port <= 65535)
        ):
            raise MemoryOSAdapterError("memoryos_url_invalid")
        if not isinstance(self.api_key, str) or not self.api_key:
            raise MemoryOSAdapterError("memoryos_api_key_missing")
        if self.default_timeout_s <= 0:
            raise MemoryOSAdapterError("memoryos_timeout_invalid")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def health(self, *, timeout_s: float = 0.5) -> Mapping[str, Any]:
        payload = self._request_json("GET", "/health", None, timeout_s=timeout_s)
        if payload.get("status") != "ok":
            raise MemoryOSAdapterError("memoryos_health_invalid")
        return payload

    def create_session(self, *, title: str) -> str:
        payload = self._request_json("POST", "/sessions", {"title": title})
        return _required_id(payload, "id", "memoryos_session_response_invalid")

    def ingest_document(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = self._request_json("POST", "/archives/ingest", request)
        expected = request.get("document_id")
        if payload.get("document_id") != expected:
            raise MemoryOSAdapterError("memoryos_ingest_response_invalid")
        passages = payload.get("passage_ids")
        if not isinstance(passages, list) or not all(
            isinstance(value, str) and value for value in passages
        ):
            raise MemoryOSAdapterError("memoryos_ingest_response_invalid")
        return payload

    def attach_archive(
        self,
        *,
        archive_id: str,
        session_id: str,
        source_refs: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        request = {
            "archive_id": archive_id,
            "scope_type": "session",
            "scope_id": session_id,
            "source_refs": [dict(value) for value in source_refs],
            "metadata": dict(metadata or {}),
        }
        payload = self._request_json("POST", "/archives/attachments", request)
        if payload.get("archive_id") != archive_id or payload.get("scope_id") != session_id:
            raise MemoryOSAdapterError("memoryos_attachment_response_invalid")
        _required_id(payload, "attachment_id", "memoryos_attachment_response_invalid")
        return payload

    def build_context(
        self,
        *,
        session_id: str,
        task: str,
        retrieval_query: str | None,
        budget: int = ROOM_MEMORY_MAX_TOKENS,
        timeout_s: float = ROOM_MEMORY_RECALL_TIMEOUT_S,
    ) -> Mapping[str, Any]:
        return self._request_json(
            "POST",
            f"/sessions/{urllib.parse.quote(session_id, safe='')}/build-context",
            {
                "task": task,
                "budget": budget,
                "retrieval_query": retrieval_query,
                "include_global_core": False,
            },
            timeout_s=timeout_s,
            max_response_bytes=_MEMORYOS_CONTEXT_HTTP_MAX_BYTES,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        *,
        timeout_s: float | None = None,
        max_response_bytes: int = ROOM_MEMORY_MAX_RESPONSE_BYTES,
    ) -> Mapping[str, Any]:
        encoded = None
        if body is not None:
            try:
                encoded = json.dumps(
                    dict(body),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise MemoryOSAdapterError("memoryos_request_invalid") from exc
            if len(encoded) > _MAX_REQUEST_BYTES:
                raise MemoryOSAdapterError("memoryos_request_too_large")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=timeout_s or self.default_timeout_s) as response:
                if int(response.status) != 200:
                    raise MemoryOSAdapterError("memoryos_http_error")
                raw = response.read(max_response_bytes + 1)
        except MemoryOSAdapterError:
            raise
        except urllib.error.HTTPError as exc:
            code = (
                "memoryos_document_conflict"
                if path == "/archives/ingest" and exc.code == 409
                else "memoryos_http_error"
            )
            raise MemoryOSAdapterError(code) from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise MemoryOSAdapterError("memoryos_unavailable") from exc
        if len(raw) > max_response_bytes:
            raise MemoryOSAdapterError("memoryos_response_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryOSAdapterError("memoryos_response_invalid") from exc
        if not isinstance(payload, Mapping):
            raise MemoryOSAdapterError("memoryos_response_invalid")
        return payload


class ArchiveOnlyRoomMemoryRuntime:
    """Bind strict MemoryOS recall/outbox transport to durable Room memory state."""

    def __init__(
        self,
        delivery_store: RoomMemoryDeliveryStoreProtocol,
        recall_store: RoomMemoryRecallStoreProtocol,
        adapter: MemoryOSArchiveAdapter,
        *,
        worker_id: str,
    ) -> None:
        self.delivery_store = delivery_store
        self.recall_store = recall_store
        self.adapter = adapter
        self.worker_id = worker_id

    async def recall(self, request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        started = time.perf_counter()
        try:
            durable = self.recall_store.build_recall_request(
                conversation_id=request.conversation_id,
                attempt_id=request.attempt_id,
                correlation_id=request.correlation_id,
                causal_activity_ids=request.causal_activity_ids,
            )
            session_id = _required_id(durable, "session_id", "room_memory_binding_unavailable")
            task = str(durable.get("task") or request.task)
            query = durable.get("retrieval_query")
            if query is not None and not isinstance(query, str):
                raise MemoryOSAdapterError("room_memory_request_invalid")
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    self.adapter.build_context,
                    session_id=session_id,
                    task=task,
                    retrieval_query=query,
                    budget=ROOM_MEMORY_MAX_TOKENS,
                    timeout_s=ROOM_MEMORY_RECALL_TIMEOUT_S,
                ),
                timeout=ROOM_MEMORY_RECALL_TIMEOUT_S,
            )
            return self._validated_evidence(
                payload,
                request=request,
                durable_request=durable,
                latency_ms=_latency_ms(started),
            )
        except TimeoutError:
            return _degraded("timeout", "room_memory_timeout", started)
        except MemoryOSAdapterError as exc:
            status = _status_for_error(exc.code)
            return _degraded(status, exc.code, started)
        except Exception as exc:
            code = str(getattr(exc, "code", "room_memory_unavailable"))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
                code = "room_memory_unavailable"
            return _degraded("unavailable", code, started)

    def record_recall_receipt(
        self,
        *,
        attempt_id: str,
        evidence: RoomMemoryEvidence,
    ) -> None:
        self.recall_store.record_attempt_memory_receipt(
            attempt_id=attempt_id,
            status=evidence.status,
            schema_version=evidence.schema_version,
            latency_ms=evidence.latency_ms,
            items=[
                {
                    "item_id": item.item_id,
                    "document_id": item.document_id,
                    "source_activity_ids": list(item.source_activity_ids),
                    "content_sha256": item.content_sha256,
                    "text": item.text,
                }
                for item in evidence.items
            ],
            evidence_sha256=evidence.evidence_sha256,
            now=datetime.now(UTC),
        )

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
    ) -> None:
        if (
            _DIGEST_RE.fullmatch(evidence_sha256) is None
            or _DIGEST_RE.fullmatch(context_payload_sha256) is None
        ):
            raise MemoryOSAdapterError("room_memory_context_digest_invalid")
        self.recall_store.bind_attempt_memory_context(
            attempt_id=attempt_id,
            evidence_sha256=evidence_sha256,
            context_payload_sha256=context_payload_sha256,
            now=datetime.now(UTC),
        )

    async def pump_once(self) -> bool:
        if await self._pump_binding_once():
            return True
        # Reopen durable transient failures only while the derived sidecar is
        # actually healthy.  chat.db enforces per-item exponential backoff.
        await asyncio.to_thread(self.adapter.health, timeout_s=0.5)
        if self.delivery_store.requeue_retryable_failed_outbox(limit=1):
            return True
        claim = self.delivery_store.claim_next_outbox(worker_id=self.worker_id)
        if claim is None:
            return False
        outbox = _mapping(claim, "outbox")
        delivery = _mapping(claim, "delivery")
        request = _mapping(claim, "document_request")
        outbox_id = _required_id(outbox, "outbox_id", "room_memory_outbox_invalid")
        delivery_id = _required_id(delivery, "delivery_id", "room_memory_outbox_invalid")
        lease_token = _required_id(delivery, "lease_token", "room_memory_outbox_invalid")
        attempt_number = delivery.get("attempt_number")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
            raise MemoryOSAdapterError("room_memory_outbox_invalid")
        request_digest = _canonical_digest(request)
        try:
            response = await asyncio.to_thread(self.adapter.ingest_document, request)
            self.delivery_store.complete_delivery(
                outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status="delivered",
                request_digest=request_digest,
                response_digest=_canonical_digest(response),
                reason_code=None,
            )
        except MemoryOSAdapterError as exc:
            if exc.code == "memoryos_document_conflict":
                self.delivery_store.complete_delivery(
                    outbox_id=outbox_id,
                    delivery_id=delivery_id,
                    lease_token=lease_token,
                    status="conflict",
                    request_digest=request_digest,
                    reason_code="room_memory_document_conflict",
                )
            else:
                self.delivery_store.complete_delivery(
                    outbox_id=outbox_id,
                    delivery_id=delivery_id,
                    lease_token=lease_token,
                    status="failed",
                    request_digest=request_digest,
                    reason_code=exc.code,
                )
                raise
        return True

    async def _pump_binding_once(self) -> bool:
        bindings = self.delivery_store.list_pending_bindings(limit=20)
        for raw in bindings:
            binding = dict(raw)
            binding_id = _required_id(binding, "binding_id", "room_memory_binding_invalid")
            conversation_id = _required_id(
                binding, "conversation_id", "room_memory_binding_invalid"
            )
            revision = binding.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise MemoryOSAdapterError("room_memory_binding_invalid")
            session_state = binding.get("session_state")
            if session_state == "uncertain":
                try:
                    self.delivery_store.reopen_uncertain_binding(
                        binding_id=binding_id,
                        expected_revision=revision,
                    )
                except Exception as exc:
                    if getattr(exc, "code", None) == "room_memory_binding_retry_not_ready":
                        continue
                    raise
                return True
            if session_state == "creating":
                request_id = _binding_request_id("session", binding_id, revision - 1)
                self.delivery_store.complete_session_create(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=revision,
                    session_id=None,
                    uncertain=True,
                )
                return True
            if session_state == "unbound" and binding.get("scope_type") == "room":
                request_id = _binding_request_id("session", binding_id, revision)
                reserved = self.delivery_store.reserve_session_create(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=revision,
                )
                reserved_revision = _revision(reserved)
                try:
                    session_id = await asyncio.to_thread(
                        self.adapter.create_session,
                        title=f"xmuse Room archive {conversation_id}",
                    )
                except Exception as exc:
                    self.delivery_store.complete_session_create(
                        binding_id=binding_id,
                        client_request_id=request_id,
                        expected_revision=reserved_revision,
                        session_id=None,
                        uncertain=True,
                    )
                    raise MemoryOSAdapterError("room_memory_session_uncertain") from exc
                self.delivery_store.complete_session_create(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=reserved_revision,
                    session_id=session_id,
                    uncertain=False,
                )
                return True
            if session_state != "bound":
                continue
            attachment_state = binding.get("attachment_state")
            if attachment_state == "uncertain":
                try:
                    self.delivery_store.reopen_uncertain_binding(
                        binding_id=binding_id,
                        expected_revision=revision,
                    )
                except Exception as exc:
                    if getattr(exc, "code", None) == "room_memory_binding_retry_not_ready":
                        continue
                    raise
                return True
            if attachment_state == "attaching":
                request_id = _binding_request_id("attachment", binding_id, revision - 1)
                self.delivery_store.complete_attachment(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=revision,
                    attachment_id=None,
                    uncertain=True,
                )
                return True
            if attachment_state != "pending":
                continue
            session_id = _required_id(binding, "session_id", "room_memory_binding_invalid")
            archive_id = _required_id(binding, "archive_id", "room_memory_binding_invalid")
            request_id = _binding_request_id("attachment", binding_id, revision)
            reserved = self.delivery_store.reserve_attachment(
                binding_id=binding_id,
                client_request_id=request_id,
                expected_revision=revision,
            )
            reserved_revision = _revision(reserved)
            try:
                response = await asyncio.to_thread(
                    self.adapter.attach_archive,
                    archive_id=archive_id,
                    session_id=session_id,
                    source_refs=(
                        {
                            "source_type": "document",
                            "source_id": f"xmuse-room-binding-{conversation_id}",
                            "session_id": session_id,
                            "metadata": {"scope_type": binding.get("scope_type")},
                        },
                    ),
                    metadata={"producer": "xmuse_room_archive_adapter/v1"},
                )
                attachment_id = _required_id(
                    response, "attachment_id", "memoryos_attachment_response_invalid"
                )
            except Exception as exc:
                self.delivery_store.complete_attachment(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=reserved_revision,
                    attachment_id=None,
                    uncertain=True,
                )
                raise MemoryOSAdapterError("room_memory_attachment_uncertain") from exc
            self.delivery_store.complete_attachment(
                binding_id=binding_id,
                client_request_id=request_id,
                expected_revision=reserved_revision,
                attachment_id=attachment_id,
                uncertain=False,
            )
            return True
        return False

    def _validated_evidence(
        self,
        payload: Mapping[str, Any],
        *,
        request: RoomMemoryRecallInput,
        durable_request: Mapping[str, Any],
        latency_ms: int,
    ) -> RoomMemoryEvidence:
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            raise MemoryOSAdapterError("room_memory_schema_rejected")
        context = metadata.get("v3_context")
        if not isinstance(context, Mapping):
            raise MemoryOSAdapterError("room_memory_schema_rejected")
        context_metadata = context.get("metadata")
        if not isinstance(context_metadata, Mapping) or context_metadata.get("memory_arch") != "v3":
            raise MemoryOSAdapterError("room_memory_schema_rejected")
        raw_items = context.get("items")
        if not isinstance(raw_items, list):
            raise MemoryOSAdapterError("room_memory_schema_rejected")
        excluded = {
            str(value)
            for value in durable_request.get("excluded_activity_ids", [])
            if isinstance(value, str)
        }
        excluded.update(request.causal_activity_ids)
        excluded_documents = {
            str(value)
            for value in durable_request.get("excluded_document_ids", [])
            if isinstance(value, str)
        }
        items: list[RoomMemoryEvidenceItem] = []
        total_tokens = 0
        for raw in raw_items:
            if not isinstance(raw, Mapping) or raw.get("layer") != "archival":
                continue
            item = self._validated_item(
                raw,
                conversation_id=request.conversation_id,
                correlation_id=request.correlation_id,
                excluded_activity_ids=excluded,
                excluded_document_ids=excluded_documents,
            )
            if item is None:
                continue
            if len(items) >= ROOM_MEMORY_MAX_ITEMS:
                break
            if total_tokens + item.estimated_tokens > ROOM_MEMORY_MAX_TOKENS:
                break
            candidate_items = [*items, item]
            if _memory_context_size(candidate_items) > ROOM_MEMORY_MAX_RESPONSE_BYTES:
                if not items:
                    raise MemoryOSAdapterError("room_memory_evidence_too_large")
                break
            items.append(item)
            total_tokens += item.estimated_tokens
        status: Literal["ok", "empty"] = "ok" if items else "empty"
        reason = "room_memory_recalled" if items else "room_memory_no_evidence"
        evidence_digest = _canonical_digest(
            {
                "schema_version": ROOM_MEMORY_EVIDENCE_SCHEMA,
                "status": status,
                "items": [
                    {
                        **item.context_payload(),
                        "document_id": item.document_id,
                        "content_sha256": item.content_sha256,
                    }
                    for item in items
                ],
            }
        )
        return RoomMemoryEvidence(
            status=status,
            reason_code=reason,
            schema_version=MEMORYOS_CONTEXT_SCHEMA,
            latency_ms=latency_ms,
            evidence_sha256=evidence_digest,
            items=tuple(items),
        )

    def _validated_item(
        self,
        raw: Mapping[str, Any],
        *,
        conversation_id: str,
        correlation_id: str,
        excluded_activity_ids: set[str],
        excluded_document_ids: set[str],
    ) -> RoomMemoryEvidenceItem | None:
        item_id = _required_id(raw, "item_id", "room_memory_schema_rejected")
        text = raw.get("text")
        tokens = raw.get("estimated_tokens")
        refs = raw.get("source_refs")
        metadata = raw.get("metadata")
        if (
            not isinstance(text, str)
            or not text.strip()
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens <= 0
            or not isinstance(refs, list)
            or not refs
            or not isinstance(metadata, Mapping)
        ):
            raise MemoryOSAdapterError("room_memory_schema_rejected")
        document_id = metadata.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            raise MemoryOSAdapterError("room_memory_source_rejected")
        if document_id in excluded_document_ids:
            return None
        source_ids: list[str] = []
        for ref in refs:
            if not isinstance(ref, Mapping) or ref.get("source_type") != "document":
                raise MemoryOSAdapterError("room_memory_source_rejected")
            activity_id = ref.get("source_id")
            if not isinstance(activity_id, str) or not activity_id:
                raise MemoryOSAdapterError("room_memory_source_rejected")
            if activity_id in excluded_activity_ids:
                return None
            source_ids.append(activity_id)
        content_sha256 = f"sha256:{hashlib.sha256(text.strip().encode('utf-8')).hexdigest()}"
        try:
            authority = self.recall_store.resolve_recall_source(
                conversation_id=conversation_id,
                document_id=document_id,
                source_activity_ids=tuple(sorted(set(source_ids))),
                content_sha256=content_sha256,
                item_text=text.strip(),
            )
        except Exception as exc:
            raise MemoryOSAdapterError("room_memory_source_rejected") from exc
        activities = authority.get("source_activities")
        if not isinstance(activities, list) or not activities:
            raise MemoryOSAdapterError("room_memory_source_rejected")
        for source in activities:
            if not isinstance(source, Mapping):
                raise MemoryOSAdapterError("room_memory_source_rejected")
            source_id = source.get("activity_id")
            if (
                source.get("conversation_id") == conversation_id
                and source.get("correlation_id") == correlation_id
            ):
                return None
            if isinstance(source_id, str) and source_id in excluded_activity_ids:
                return None
        return RoomMemoryEvidenceItem(
            item_id=item_id,
            document_id=document_id,
            text=text.strip(),
            estimated_tokens=tokens,
            source_activity_ids=tuple(sorted(set(source_ids))),
            content_sha256=content_sha256,
        )


class DisabledRoomMemoryRuntime:
    """Persist disabled receipts while leaving all sidecar I/O dormant."""

    def __init__(self, recall_store: RoomMemoryRecallStoreProtocol) -> None:
        self.recall_store = recall_store

    async def recall(self, _request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        return disabled_memory_evidence()

    def record_recall_receipt(self, *, attempt_id: str, evidence: RoomMemoryEvidence) -> None:
        self.recall_store.record_attempt_memory_receipt(
            attempt_id=attempt_id,
            status=evidence.status,
            schema_version=evidence.schema_version,
            latency_ms=evidence.latency_ms,
            items=[],
            evidence_sha256=evidence.evidence_sha256,
            now=datetime.now(UTC),
        )

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
    ) -> None:
        self.recall_store.bind_attempt_memory_context(
            attempt_id=attempt_id,
            evidence_sha256=evidence_sha256,
            context_payload_sha256=context_payload_sha256,
            now=datetime.now(UTC),
        )

    async def pump_once(self) -> bool:
        return False


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise MemoryOSAdapterError("room_memory_outbox_invalid")
    return value


def _required_id(payload: Mapping[str, Any], key: str, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise MemoryOSAdapterError(code)
    return value


def _revision(payload: Mapping[str, Any]) -> int:
    value = payload.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryOSAdapterError("room_memory_binding_invalid")
    return value


def _binding_request_id(kind: str, binding_id: str, revision: int) -> str:
    if revision < 0:
        raise MemoryOSAdapterError("room_memory_binding_invalid")
    digest = hashlib.sha256(f"{kind}:{binding_id}:{revision}".encode()).hexdigest()[:32]
    return f"memory-{kind}-{digest}"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MemoryOSAdapterError("room_memory_digest_invalid") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _memory_context_size(items: Sequence[RoomMemoryEvidenceItem]) -> int:
    evidence = RoomMemoryEvidence(
        status="ok",
        reason_code="room_memory_recalled",
        schema_version=MEMORYOS_CONTEXT_SCHEMA,
        latency_ms=0,
        evidence_sha256="sha256:" + "0" * 64,
        items=tuple(items),
    )
    return len(
        json.dumps(
            evidence.context_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _degraded(status: str, code: str, started: float) -> RoomMemoryEvidence:
    digest = _canonical_digest(
        {
            "schema_version": ROOM_MEMORY_EVIDENCE_SCHEMA,
            "status": status,
            "reason_code": code,
            "items": [],
        }
    )
    return RoomMemoryEvidence(
        status=status,  # type: ignore[arg-type]
        reason_code=code,
        schema_version=MEMORYOS_CONTEXT_SCHEMA,
        latency_ms=_latency_ms(started),
        evidence_sha256=digest,
    )


def _status_for_error(code: str) -> str:
    if code in {"memoryos_response_too_large", "room_memory_evidence_too_large"}:
        return "oversize"
    if code in {"room_memory_schema_rejected", "memoryos_response_invalid"}:
        return "schema_rejected"
    if code == "room_memory_source_rejected":
        return "source_rejected"
    return "unavailable"
