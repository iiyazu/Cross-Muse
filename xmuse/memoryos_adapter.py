"""Archive-only HTTP adapter from durable Room memory state to MemoryOS Lite.

This application module intentionally imports no ``memoryos_lite`` package.  It uses
the four public HTTP contracts and treats every recall byte as untrusted until its
source references are resolved back to ``chat.db`` by the narrow recall store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_EVIDENCE_SCHEMA,
    ROOM_MEMORY_FULL_LOCAL_RECALL_TIMEOUT_S,
    ROOM_MEMORY_MAX_ITEMS,
    ROOM_MEMORY_MAX_RESPONSE_BYTES,
    ROOM_MEMORY_MAX_TOKENS,
    ROOM_MEMORY_RECALL_TIMEOUT_S,
    RoomMemoryEvidence,
    RoomMemoryEvidenceItem,
    RoomMemoryRecallInput,
    disabled_memory_evidence,
)

MEMORYOS_CONTEXT_SCHEMA = "memoryos_source_evidence/v1"
MEMORYOS_SOURCE_EVIDENCE_PROFILE = "source_evidence/v1"
MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA = "memoryos_source_evidence/v2"
MEMORYOS_SOURCE_EVIDENCE_V2_PROFILE = "source_evidence/v2"
MEMORYOS_DOCUMENT_PREFIX = "xmuse-room-activity-"
_MAX_REQUEST_BYTES = 64 * 1024
# MemoryOS v3 duplicates bounded retrieval diagnostics around archival items, so
# its transport envelope is materially larger than the evidence admitted into a
# Room prompt.  Keep that untrusted envelope bounded independently; validated
# ``memory_evidence`` remains capped at 8 KiB below.
_MEMORYOS_CONTEXT_HTTP_MAX_BYTES = 128 * 1024
_MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES = 64 * 1024
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_EVIDENCE_KEYS = {
    "schema",
    "items",
    "omitted_count",
    "estimated_tokens",
    "truncated",
    "diagnostics_digest",
}
_SOURCE_EVIDENCE_ITEM_KEYS = {
    "item_id",
    "archive_id",
    "document_id",
    "source_refs",
    "text",
    "estimated_tokens",
    "content_sha256",
    "score",
    "rank",
    "truncated",
}
_SOURCE_EVIDENCE_V2_ITEM_KEYS = {
    "item_id",
    "layer",
    "document_id",
    "text",
    "estimated_tokens",
    "source_refs",
    "content_sha256",
    "derived",
    "source_complete",
    "score",
    "rank",
    "truncated",
}


class MemoryOSAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _SourceEvidenceItemWire:
    item_id: str
    archive_id: str | None
    document_id: str | None
    text: str
    estimated_tokens: int
    source_ids: tuple[str, ...]
    content_sha256: str
    rank: int
    source_type: Literal["document", "message"] = "document"
    source_session_id: str | None = None
    layer: Literal["recall", "page", "core", "archival"] = "archival"
    derived: bool = False


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

    def claim_next_message_outbox(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any] | None: ...

    def complete_message_delivery(
        self,
        *,
        message_outbox_id: str,
        delivery_id: str,
        lease_token: str,
        status: Literal["delivered", "conflict", "failed"],
        request_digest: str,
        response_digest: str | None = None,
        memoryos_message_id: str | None = None,
        memoryos_session_id: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def requeue_retryable_failed_message_outbox(
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

    def resolve_recall_message_source(
        self,
        *,
        conversation_id: str,
        session_id: str,
        source_message_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
        derived: bool = False,
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

    def record_external_advisories(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        advisories: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    def record_external_advisory_failure(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class MemoryOSArchiveAdapter:
    base_url: str
    api_key: str = field(repr=False)
    default_timeout_s: float = 2.0
    profile: Literal["archive-only", "full-local"] = "archive-only"
    _build_context_profiles: frozenset[str] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _context_cache: dict[tuple[str, str, str | None], tuple[float, Mapping[str, Any]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _context_cache_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def recall_timeout_s(self) -> float:
        return (
            ROOM_MEMORY_FULL_LOCAL_RECALL_TIMEOUT_S
            if self.profile == "full-local"
            else ROOM_MEMORY_RECALL_TIMEOUT_S
        )

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
        if self.profile not in {"archive-only", "full-local"}:
            raise MemoryOSAdapterError("memoryos_profile_invalid")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def health(self, *, timeout_s: float = 0.5) -> Mapping[str, Any]:
        payload = self._request_json("GET", "/health", None, timeout_s=timeout_s)
        if payload.get("status") != "ok":
            raise MemoryOSAdapterError("memoryos_health_invalid")
        capabilities = payload.get("capabilities")
        profiles = (
            capabilities.get("build_context_profiles")
            if isinstance(capabilities, Mapping)
            else None
        )
        if (
            not isinstance(profiles, list)
            or len(profiles) > 16
            or any(
                not isinstance(value, str) or not value or len(value) > 128 for value in profiles
            )
            or len(set(profiles)) != len(profiles)
        ):
            normalized_profiles: frozenset[str] = frozenset()
        else:
            normalized_profiles = frozenset(profiles)
        object.__setattr__(self, "_build_context_profiles", normalized_profiles)
        return payload

    def create_session(self, *, title: str) -> str:
        payload = self._request_json("POST", "/sessions", {"title": title})
        return _required_id(payload, "id", "memoryos_session_response_invalid")

    def ingest_message(
        self,
        *,
        session_id: str,
        external_id: str,
        role: Literal["user", "assistant"],
        content: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Ingest one durable Room speech item using stable external identity.

        This endpoint is capability-gated by the MemoryOS server.  A legacy
        archive-only sidecar therefore fails with a stable attention code and
        never gets a synthetic archive document masquerading as a message.
        """

        if role not in {"user", "assistant"}:
            raise MemoryOSAdapterError("memoryos_message_role_invalid")
        if not isinstance(external_id, str) or not external_id or len(external_id) > 512:
            raise MemoryOSAdapterError("memoryos_message_external_id_invalid")
        if not isinstance(content, str) or not content or len(content.encode("utf-8")) > 64 * 1024:
            raise MemoryOSAdapterError("memoryos_message_content_invalid")
        request = {
            "external_id": external_id,
            "role": role,
            "content": content,
            "metadata": dict(metadata or {}),
        }
        try:
            payload = self._request_json(
                "POST",
                f"/sessions/{urllib.parse.quote(session_id, safe='')}/ingest",
                request,
                timeout_s=self.default_timeout_s,
            )
        except MemoryOSAdapterError as exc:
            if exc.code == "memoryos_http_error":
                raise MemoryOSAdapterError("memoryos_message_ingest_unsupported") from exc
            raise
        message = payload.get("message")
        message_payload = message if isinstance(message, Mapping) else payload
        echoed = message_payload.get("external_id")
        if echoed is not None and echoed != external_id:
            raise MemoryOSAdapterError("memoryos_message_response_invalid")
        if not isinstance(message_payload.get("id"), str) or echoed is None:
            raise MemoryOSAdapterError("memoryos_message_response_invalid")
        return payload

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
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        timeout_s = self.recall_timeout_s if timeout_s is None else timeout_s
        if self._build_context_profiles is None:
            self.health(timeout_s=min(timeout_s, 0.25))
        profiles = self._build_context_profiles or ()
        selected_profile = (
            MEMORYOS_SOURCE_EVIDENCE_V2_PROFILE
            if self.profile == "full-local"
            else MEMORYOS_SOURCE_EVIDENCE_PROFILE
        )
        if selected_profile not in profiles:
            raise MemoryOSAdapterError("memoryos_source_evidence_unsupported")
        request_key = (session_id, task, retrieval_query)
        if self.profile == "full-local":
            now = time.monotonic()
            with self._context_cache_lock:
                cached = self._context_cache.get(request_key)
                if cached is not None and now - cached[0] <= 15.0:
                    return cached[1]
                self._context_cache.pop(request_key, None)
        try:
            with self._context_cache_lock if self.profile == "full-local" else nullcontext():
                payload = self._request_json(
                    "POST",
                    f"/sessions/{urllib.parse.quote(session_id, safe='')}/build-context",
                    {
                        "task": task,
                        "budget": budget,
                        "retrieval_query": retrieval_query,
                        "include_global_core": False,
                        "response_profile": selected_profile,
                    },
                    timeout_s=timeout_s,
                    max_response_bytes=_MEMORYOS_CONTEXT_HTTP_MAX_BYTES,
                )
                if self.profile == "full-local":
                    self._context_cache[request_key] = (time.monotonic(), payload)
                    if len(self._context_cache) > 16:
                        oldest = min(
                            self._context_cache,
                            key=lambda key: self._context_cache[key][0],
                        )
                        self._context_cache.pop(oldest, None)
                return payload
        except MemoryOSAdapterError as exc:
            if exc.code in {"memoryos_response_invalid", "memoryos_response_too_large"}:
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift") from exc
            raise

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
                else "memoryos_message_conflict"
                if path.endswith("/ingest") and exc.code == 409
                else "memoryos_source_evidence_capability_drift"
                if path.endswith("/build-context") and exc.code in {413, 422}
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

    def list_advisories(self, *, session_id: str) -> list[Mapping[str, Any]]:
        payload = self._request_json(
            "GET",
            f"/sessions/{urllib.parse.quote(session_id, safe='')}/advisories",
            None,
            max_response_bytes=64 * 1024,
        )
        if payload.get("schema") != "memoryos_external_advisories/v1":
            raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > 32:
            raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
        result: list[Mapping[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, Mapping):
                raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
            if set(item) != {
                "advisory_id",
                "session_id",
                "fingerprint",
                "proposal_type",
                "content",
                "source_refs",
                "created_at",
            }:
                raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
            if (
                not isinstance(item.get("advisory_id"), str)
                or not isinstance(item.get("session_id"), str)
                or item.get("session_id") != session_id
                or not isinstance(item.get("fingerprint"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["fingerprint"])
                or item.get("proposal_type") not in {"archive_write", "core_promotion_request"}
                or not isinstance(item.get("content"), str)
                or not item["content"].strip()
                or len(item["content"].encode("utf-8")) > 4096
                or not isinstance(item.get("source_refs"), list)
                or len(item["source_refs"]) == 0
                or len(item["source_refs"]) > 8
                or not isinstance(item.get("created_at"), str)
            ):
                raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
            result.append(item)
        return result


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

    @property
    def recall_timeout_s(self) -> float:
        return float(getattr(self.adapter, "recall_timeout_s", ROOM_MEMORY_RECALL_TIMEOUT_S))

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
                    timeout_s=self.recall_timeout_s,
                ),
                timeout=self.recall_timeout_s,
            )
            if self.adapter.profile == "full-local":
                try:
                    list_advisories = getattr(self.adapter, "list_advisories", None)
                    advisories = (
                        await asyncio.to_thread(
                            list_advisories,
                            session_id=session_id,
                        )
                        if callable(list_advisories)
                        else []
                    )
                    recorder = getattr(self.recall_store, "record_external_advisories", None)
                    if callable(recorder) and advisories:
                        recorder(
                            conversation_id=request.conversation_id,
                            attempt_id=request.attempt_id,
                            advisories=advisories,
                            now=datetime.now(UTC),
                        )
                except Exception as exc:
                    # Advisory governance is additive; a sidecar advisory
                    # contract failure must not turn a valid Room recall into
                    # an Agent delivery failure.  It must nevertheless leave
                    # a durable, bounded diagnostic instead of disappearing.
                    reason_code = str(getattr(exc, "code", "memoryos_advisory_replay_failed"))
                    if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason_code):
                        reason_code = "memoryos_advisory_replay_failed"
                    failure_recorder = getattr(
                        self.recall_store, "record_external_advisory_failure", None
                    )
                    if callable(failure_recorder):
                        try:
                            failure_recorder(
                                conversation_id=request.conversation_id,
                                attempt_id=request.attempt_id,
                                reason_code=reason_code,
                                now=datetime.now(UTC),
                            )
                        except Exception:
                            # A receipt failure is itself non-authoritative;
                            # never turn it into a Room delivery failure.
                            pass
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
        # Message ingest is an optional capability.  A legacy FakeStore or
        # archive-only runtime simply has no message ledger and continues with
        # the established archival pump.
        if await self._pump_message_once():
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

    async def _pump_message_once(self) -> bool:
        if getattr(self.adapter, "profile", "archive-only") != "full-local":
            return False
        claim_method = getattr(self.delivery_store, "claim_next_message_outbox", None)
        if not callable(claim_method):
            return False
        requeue_method = getattr(
            self.delivery_store, "requeue_retryable_failed_message_outbox", None
        )
        if callable(requeue_method):
            reopened = requeue_method(limit=1)
            if reopened:
                return True
        claim = claim_method(worker_id=self.worker_id)
        if claim is None:
            return False
        outbox = _mapping(claim, "outbox")
        delivery = _mapping(claim, "delivery")
        request = _mapping(claim, "message_request")
        outbox_id = _required_id(outbox, "message_outbox_id", "room_memory_outbox_invalid")
        delivery_id = _required_id(delivery, "delivery_id", "room_memory_outbox_invalid")
        lease_token = _required_id(delivery, "lease_token", "room_memory_outbox_invalid")
        attempt_number = delivery.get("attempt_number")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
            raise MemoryOSAdapterError("room_memory_outbox_invalid")
        request_digest = _canonical_digest(request)
        session_id = request.get("session_id")
        external_id = request.get("external_id")
        role = request.get("role")
        content = request.get("content")
        metadata = request.get("metadata")
        if (
            not isinstance(session_id, str)
            or not isinstance(external_id, str)
            or role not in {"user", "assistant"}
            or not isinstance(content, str)
            or not isinstance(metadata, Mapping)
        ):
            raise MemoryOSAdapterError("room_memory_outbox_invalid")
        try:
            response = await asyncio.to_thread(
                self.adapter.ingest_message,
                session_id=session_id,
                external_id=external_id,
                role=role,
                content=content,
                metadata=metadata,
            )
            message_payload = response.get("message")
            message_payload = message_payload if isinstance(message_payload, Mapping) else response
            memoryos_message_id = message_payload.get("id")
            if not isinstance(memoryos_message_id, str) or not memoryos_message_id:
                raise MemoryOSAdapterError("memoryos_message_response_invalid")
            self.delivery_store.complete_message_delivery(
                message_outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status="delivered",
                request_digest=request_digest,
                response_digest=_canonical_digest(response),
                memoryos_message_id=memoryos_message_id,
                memoryos_session_id=session_id,
                reason_code=None,
            )
        except MemoryOSAdapterError as exc:
            status: Literal["conflict", "failed"] = (
                "conflict" if exc.code == "memoryos_message_conflict" else "failed"
            )
            self.delivery_store.complete_message_delivery(
                message_outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status=status,
                request_digest=request_digest,
                reason_code=("room_memory_message_conflict" if status == "conflict" else exc.code),
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
        try:
            semantic_bytes = json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift") from exc
        if len(semantic_bytes) > _MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        response_schema = payload.get("schema")
        if response_schema not in {MEMORYOS_CONTEXT_SCHEMA, MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA}:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        if response_schema == MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA:
            if set(payload) != _SOURCE_EVIDENCE_KEYS:
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        elif not _SOURCE_EVIDENCE_KEYS <= set(payload):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        raw_items = payload.get("items")
        omitted_count = payload.get("omitted_count")
        estimated_tokens = payload.get("estimated_tokens")
        truncated = payload.get("truncated")
        diagnostics_digest = payload.get("diagnostics_digest")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > ROOM_MEMORY_MAX_ITEMS
            or isinstance(omitted_count, bool)
            or not isinstance(omitted_count, int)
            or omitted_count < 0
            or isinstance(estimated_tokens, bool)
            or not isinstance(estimated_tokens, int)
            or not 0 <= estimated_tokens <= ROOM_MEMORY_MAX_TOKENS
            or not isinstance(truncated, bool)
            or not isinstance(diagnostics_digest, str)
            or _DIGEST_RE.fullmatch(diagnostics_digest) is None
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        digest_payload = {
            key: payload[key] for key in _SOURCE_EVIDENCE_KEYS - {"diagnostics_digest"}
        }
        if _canonical_digest(digest_payload) != diagnostics_digest:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
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
        raw_archive_ids = durable_request.get("archive_ids")
        if not isinstance(raw_archive_ids, list) or not raw_archive_ids:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        try:
            archive_ids = {
                _required_source_evidence_id({"archive_id": value}, "archive_id")
                for value in raw_archive_ids
            }
        except MemoryOSAdapterError as exc:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift") from exc
        if len(archive_ids) != len(raw_archive_ids):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        wire_items: list[_SourceEvidenceItemWire] = []
        expected_session_id = durable_request.get("session_id")
        if not isinstance(expected_session_id, str) or not expected_session_id:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
            wire_items.append(
                _source_evidence_item_wire(
                    raw,
                    v2=response_schema == MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA,
                    expected_session_id=expected_session_id,
                )
            )
        if (
            any(
                item.archive_id is not None and item.archive_id not in archive_ids
                for item in wire_items
            )
            or len({item.rank for item in wire_items}) != len(wire_items)
            or sum(item.estimated_tokens for item in wire_items) != estimated_tokens
            or sum(len(item.text.encode("utf-8")) for item in wire_items) > 32 * 1024
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")

        items: list[RoomMemoryEvidenceItem] = []
        rejected_item = False
        for wire_item in wire_items:
            try:
                item = self._reprove_item(
                    wire_item,
                    conversation_id=request.conversation_id,
                    correlation_id=request.correlation_id,
                    excluded_activity_ids=excluded,
                    excluded_document_ids=excluded_documents,
                )
            except MemoryOSAdapterError as exc:
                if exc.code != "room_memory_source_rejected":
                    raise
                # Derived recall/page items are untrusted and may reference a
                # different Room.  Drop just that item; a separately proved
                # archival item in the same bounded envelope remains usable.
                rejected_item = True
                continue
            if item is None:
                continue
            candidate_items = [*items, item]
            if _memory_context_size(candidate_items) > ROOM_MEMORY_MAX_RESPONSE_BYTES:
                if not items:
                    raise MemoryOSAdapterError("room_memory_evidence_too_large")
                break
            items.append(item)
        if not items and rejected_item:
            raise MemoryOSAdapterError("room_memory_source_rejected")
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
            schema_version=str(response_schema),
            latency_ms=latency_ms,
            evidence_sha256=evidence_digest,
            items=tuple(items),
        )

    def _reprove_item(
        self,
        wire: _SourceEvidenceItemWire,
        *,
        conversation_id: str,
        correlation_id: str,
        excluded_activity_ids: set[str],
        excluded_document_ids: set[str],
    ) -> RoomMemoryEvidenceItem | None:
        if wire.document_id in excluded_document_ids:
            return None
        try:
            if wire.source_type == "message":
                resolver = getattr(self.recall_store, "resolve_recall_message_source", None)
                if not callable(resolver) or wire.source_session_id is None:
                    raise MemoryOSAdapterError("room_memory_source_rejected")
                authority = resolver(
                    conversation_id=conversation_id,
                    session_id=wire.source_session_id,
                    source_message_ids=wire.source_ids,
                    content_sha256=wire.content_sha256,
                    item_text=wire.text,
                    derived=wire.derived,
                )
            else:
                if wire.document_id is None:
                    raise MemoryOSAdapterError("room_memory_source_rejected")
                for activity_id in wire.source_ids:
                    if activity_id in excluded_activity_ids:
                        return None
                authority = self.recall_store.resolve_recall_source(
                    conversation_id=conversation_id,
                    document_id=wire.document_id,
                    source_activity_ids=tuple(sorted(wire.source_ids)),
                    content_sha256=wire.content_sha256,
                    item_text=wire.text,
                )
        except Exception as exc:
            if isinstance(exc, MemoryOSAdapterError):
                raise
            raise MemoryOSAdapterError("room_memory_source_rejected") from exc
        activities = authority.get("source_activities")
        if not isinstance(activities, list) or not activities:
            raise MemoryOSAdapterError("room_memory_source_rejected")
        resolved_activity_ids: list[str] = []
        for source in activities:
            if not isinstance(source, Mapping):
                raise MemoryOSAdapterError("room_memory_source_rejected")
            source_id = source.get("activity_id")
            if not isinstance(source_id, str) or not source_id:
                raise MemoryOSAdapterError("room_memory_source_rejected")
            resolved_activity_ids.append(source_id)
            if (
                source.get("conversation_id") == conversation_id
                and source.get("correlation_id") == correlation_id
            ):
                return None
            if isinstance(source_id, str) and source_id in excluded_activity_ids:
                return None
        document_id = authority.get("document_id") or wire.document_id
        if (
            not isinstance(document_id, str)
            or not document_id
            or len(document_id.encode("utf-8")) > 512
        ):
            raise MemoryOSAdapterError("room_memory_source_rejected")
        return RoomMemoryEvidenceItem(
            item_id=wire.item_id,
            document_id=document_id,
            text=wire.text,
            estimated_tokens=wire.estimated_tokens,
            source_activity_ids=tuple(sorted(resolved_activity_ids)),
            content_sha256=wire.content_sha256,
            layer=wire.layer,
            derived=wire.derived,
        )


class DisabledRoomMemoryRuntime:
    """Persist disabled receipts while leaving all sidecar I/O dormant."""

    def __init__(self, recall_store: RoomMemoryRecallStoreProtocol) -> None:
        self.recall_store = recall_store

    @property
    def recall_timeout_s(self) -> float:
        return ROOM_MEMORY_RECALL_TIMEOUT_S

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


def _required_source_evidence_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return value


def _optional_source_evidence_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        return None
    return value


def _source_evidence_item_wire(
    raw: Mapping[str, Any],
    *,
    v2: bool = False,
    expected_session_id: str | None = None,
) -> _SourceEvidenceItemWire:
    if v2:
        return _source_evidence_v2_item_wire(raw, expected_session_id=expected_session_id)
    if not _SOURCE_EVIDENCE_ITEM_KEYS <= set(raw):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    item_id = _required_source_evidence_id(raw, "item_id")
    archive_id = _required_source_evidence_id(raw, "archive_id")
    document_id = _required_source_evidence_id(raw, "document_id")
    text = raw.get("text")
    tokens = raw.get("estimated_tokens")
    refs = raw.get("source_refs")
    content_sha256 = raw.get("content_sha256")
    score = raw.get("score")
    rank = raw.get("rank")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text.encode("utf-8")) > 8 * 1024
        or isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 0 < tokens <= ROOM_MEMORY_MAX_TOKENS
        or not isinstance(refs, list)
        or not refs
        or len(refs) > 8
        or not isinstance(content_sha256, str)
        or _DIGEST_RE.fullmatch(content_sha256) is None
        or isinstance(rank, bool)
        or not isinstance(rank, int)
        or not 1 <= rank <= ROOM_MEMORY_MAX_ITEMS
        or not isinstance(raw.get("truncated"), bool)
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    expected_content_sha256 = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    if content_sha256 != expected_content_sha256:
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    source_ids: list[str] = []
    for ref in refs:
        if (
            not isinstance(ref, Mapping)
            or not {"source_type", "source_id"} <= set(ref)
            or ref.get("source_type") != "document"
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        source_ids.append(_required_source_evidence_id(ref, "source_id"))
    if len(set(source_ids)) != len(source_ids):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    layer = raw.get("layer", "archival")
    derived = raw.get("derived", layer in {"recall", "page"})
    if layer not in {"recall", "page", "core", "archival"} or not isinstance(derived, bool):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return _SourceEvidenceItemWire(
        item_id=item_id,
        archive_id=archive_id,
        document_id=document_id,
        text=text,
        estimated_tokens=tokens,
        source_ids=tuple(source_ids),
        content_sha256=content_sha256,
        rank=rank,
        source_type="document",
        layer=layer,
        derived=derived,
    )


def _source_evidence_v2_item_wire(
    raw: Mapping[str, Any], *, expected_session_id: str | None
) -> _SourceEvidenceItemWire:
    """Validate the actual MemoryOS v2 item shape and normalize Room refs."""

    if (
        set(raw) - _SOURCE_EVIDENCE_V2_ITEM_KEYS
        or not (_SOURCE_EVIDENCE_V2_ITEM_KEYS - {"document_id"}) <= set(raw)
        or not isinstance(expected_session_id, str)
        or not expected_session_id
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    item_id = _required_source_evidence_id(raw, "item_id")
    text = raw.get("text")
    tokens = raw.get("estimated_tokens")
    refs = raw.get("source_refs")
    content_sha256 = raw.get("content_sha256")
    score = raw.get("score")
    rank = raw.get("rank")
    layer = raw.get("layer")
    document_id_raw = raw.get("document_id")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text.encode("utf-8")) > 8 * 1024
        or isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 0 < tokens <= ROOM_MEMORY_MAX_TOKENS
        or not isinstance(refs, list)
        or not refs
        or len(refs) > 8
        or not isinstance(content_sha256, str)
        or _DIGEST_RE.fullmatch(content_sha256) is None
        or isinstance(rank, bool)
        or not isinstance(rank, int)
        or not 1 <= rank <= ROOM_MEMORY_MAX_ITEMS
        or layer not in {"recall", "page", "core", "archival"}
        or (document_id_raw is not None and _optional_source_evidence_id(document_id_raw) is None)
        or raw.get("source_complete") is not True
        or not isinstance(raw.get("derived"), bool)
        or not isinstance(raw.get("truncated"), bool)
        or (score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))))
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if score is not None and not math.isfinite(float(score)):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    expected_content_sha256 = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    if content_sha256 != expected_content_sha256:
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")

    source_type: Literal["document", "message"] | None = None
    source_session_id: str | None = None
    source_ids: list[str] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        if set(ref) - {"source_type", "source_id", "session_id"}:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        ref_type = ref.get("source_type")
        if ref_type not in {"document", "message"}:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        if source_type is not None and source_type != ref_type:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        source_type = ref_type
        source_id = _required_source_evidence_id(ref, "source_id")
        session = ref.get("session_id")
        if session is not None:
            if not isinstance(session, str) or not session or len(session.encode("utf-8")) > 512:
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
            if ref_type == "message":
                if session != expected_session_id:
                    raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
                if source_session_id is not None and source_session_id != session:
                    raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
                source_session_id = session
        elif ref_type == "message":
            # Message identities are only meaningful inside their sidecar
            # session; a missing scope must not be guessed.
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        source_ids.append(source_id)
    if source_type is None or len(set(source_ids)) != len(source_ids):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if source_type == "message" and layer == "archival":
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    document_id: str | None = None
    if source_type == "document":
        source_id = source_ids[0]
        document_id = (
            _optional_source_evidence_id(document_id_raw)
            if document_id_raw is not None
            else (
                source_id
                if source_id.startswith((MEMORYOS_DOCUMENT_PREFIX, "xmuse-room-memory-candidate-"))
                else f"{MEMORYOS_DOCUMENT_PREFIX}{source_id}"
            )
        )
        if layer == "archival" and document_id is None:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return _SourceEvidenceItemWire(
        item_id=item_id,
        archive_id=None,
        document_id=document_id,
        text=text,
        estimated_tokens=tokens,
        source_ids=tuple(source_ids),
        content_sha256=content_sha256,
        rank=rank,
        source_type=source_type,
        source_session_id=source_session_id,
        layer=layer,
        derived=bool(raw["derived"]),
    )


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
            allow_nan=False,
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
