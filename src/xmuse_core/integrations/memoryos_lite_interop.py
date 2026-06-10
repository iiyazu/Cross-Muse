from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.integrations.memoryos_client import (
    MemoryOSContext,
    MemoryOSIngestRequest,
    MemoryOSIngestResult,
    MemoryOSMemoryLayer,
    MemoryOSPage,
)
from xmuse_core.integrations.memoryos_namespace import MemoryOSNamespace
from xmuse_core.runtime.paths import default_xmuse_root

logger = logging.getLogger(__name__)

LIVE_MEMORYOS_LITE_ENV = "XMUSE_LIVE_MEMORYOS_LITE"
MEMORYOS_LITE_BASE_URL_ENV = "XMUSE_MEMORYOS_LITE_URL"
DEFAULT_BINDING_STORE_NAME = "memoryos_lite_sessions.json"


class MemoryOSLiteSessionBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    session_id: str = Field(min_length=1)
    session_title: str = Field(min_length=1)
    status: Literal["active", "stale"] = "active"
    stale_reason: str | None = None


class MemoryOSLiteSessionBindingStore:
    def __init__(self, path: str | Path | None = None) -> None:
        root = default_xmuse_root("xmuse")
        self.path = Path(path) if path is not None else root / DEFAULT_BINDING_STORE_NAME

    def get(self, namespace_uri: str) -> MemoryOSLiteSessionBinding | None:
        for binding in self._load():
            if binding.namespace_uri == namespace_uri and binding.status == "active":
                return binding
        return None

    def list_stale(self, namespace_uri: str | None = None) -> list[MemoryOSLiteSessionBinding]:
        return [
            binding
            for binding in self._load()
            if binding.status == "stale"
            if namespace_uri is None or binding.namespace_uri == namespace_uri
        ]

    def upsert_active(
        self,
        *,
        namespace_uri: str,
        session_id: str,
        session_title: str,
    ) -> MemoryOSLiteSessionBinding:
        binding = MemoryOSLiteSessionBinding(
            namespace_uri=namespace_uri,
            session_id=session_id,
            session_title=session_title,
            status="active",
        )
        bindings = [
            existing
            for existing in self._load()
            if not (existing.namespace_uri == namespace_uri and existing.status == "active")
        ]
        bindings.append(binding)
        self._save(bindings)
        return binding

    def mark_stale(
        self,
        binding: MemoryOSLiteSessionBinding,
        *,
        reason: str,
    ) -> MemoryOSLiteSessionBinding:
        stale = binding.model_copy(
            update={
                "status": "stale",
                "stale_reason": reason,
            }
        )
        bindings = [
            existing
            for existing in self._load()
            if not (
                existing.namespace_uri == binding.namespace_uri
                and existing.session_id == binding.session_id
                and existing.status == "active"
            )
        ]
        bindings.append(stale)
        self._save(bindings)
        return stale

    def _load(self) -> list[MemoryOSLiteSessionBinding]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("memoryos lite binding store must be an object")
        bindings = payload.get("bindings", [])
        if not isinstance(bindings, list):
            raise ValueError("memoryos lite binding store bindings must be a list")
        return [
            MemoryOSLiteSessionBinding.model_validate(item)
            for item in bindings
            if isinstance(item, dict)
        ]

    def _save(self, bindings: list[MemoryOSLiteSessionBinding]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "xmuse.memoryos_lite_sessions.v1",
            "bindings": [binding.model_dump(mode="json") for binding in bindings],
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


class MemoryOSLiteEndpointPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    create_session: str = "/sessions"
    ingest: str = "/sessions/{session_id}/ingest"
    page: str = "/sessions/{session_id}/page"
    build_context: str = "/sessions/{session_id}/build-context"
    trace: str = "/sessions/{session_id}/trace"
    search: str = "/memory/search"
    health: str = "/health"


class MemoryOSLiteInteropPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    session_title: str
    session_metadata: dict[str, object]
    endpoint_plan: MemoryOSLiteEndpointPlan = Field(default_factory=MemoryOSLiteEndpointPlan)
    proof_level: Literal["contract", "live"] = "contract"


class MemoryOSLiteTraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    session_id: str
    trace_events: list[dict[str, object]] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    estimated_tokens: int | None = None
    proof_level: Literal["live_service_proof"] = "live_service_proof"


class MemoryOSLiteInteropAdapter:
    """REST-only bridge from xmuse task namespaces to MemoryOS Lite sessions."""

    def __init__(
        self,
        *,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
        binding_store: MemoryOSLiteSessionBindingStore | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client
        self._binding_store = binding_store or MemoryOSLiteSessionBindingStore()
        self._sessions_by_namespace_uri: dict[str, MemoryOSLiteSessionBinding] = {}

    async def ingest(self, request: MemoryOSIngestRequest) -> MemoryOSIngestResult:
        binding = await self._ensure_session(request.namespace)
        if binding is None:
            return MemoryOSIngestResult(
                ok=False,
                degraded_reason="memoryos_lite_unavailable",
            )
        result = await self._ingest_to_binding(binding, request)
        if _is_stale_session_result(result):
            stale_result = await self._replace_stale_binding(
                request.namespace,
                binding,
                reason=result.degraded_reason or "memoryos_lite_session_not_found",
            )
            if stale_result is None:
                return result
            binding = stale_result
            result = await self._ingest_to_binding(binding, request)
        if result.ok and request.promote_to_shared and request.shared_namespace is not None:
            shared_binding = await self._ensure_session(request.shared_namespace)
            if shared_binding is not None:
                await self._ingest_to_binding(shared_binding, request)
        return result

    async def build_context(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        budget: int = 4096,
    ) -> MemoryOSContext:
        binding = await self._ensure_session(namespace)
        if binding is None:
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text="",
                degraded_reason="memoryos_lite_unavailable",
            )
        try:
            payload = await self._post_build_context_with_stale_retry(
                namespace,
                binding,
                query=query,
                budget=budget,
            )
            text = _context_text(payload)
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text=text[:budget],
                source_refs=_dedupe(_context_source_refs(payload)),
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos-lite build_context degraded: %s", exc)
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text="",
                degraded_reason="memoryos_lite_unavailable",
            )

    async def search(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        limit: int = 10,
    ) -> list[MemoryOSPage]:
        binding = await self._ensure_session(namespace)
        if binding is None:
            return []
        try:
            payload = await self._post_search_with_stale_retry(
                namespace,
                binding,
                query=query,
                limit=limit,
            )
            if not isinstance(payload, list):
                return []
            return [
                _page_from_search_hit(namespace=namespace, hit=hit)
                for hit in payload[:limit]
                if isinstance(hit, dict)
            ]
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos-lite search degraded: %s", exc)
            return []

    async def fetch_trace(
        self,
        namespace: MemoryOSNamespace,
    ) -> MemoryOSLiteTraceEvidence | None:
        binding = await self._ensure_session(namespace)
        if binding is None:
            return None
        try:
            response = await self._http().get(
                f"{self._base_url}/sessions/{binding.session_id}/trace"
            )
            response.raise_for_status()
            payload = response.json()
            return _trace_evidence_from_payload(
                namespace=namespace,
                session_id=binding.session_id,
                payload=payload,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos-lite trace degraded: %s", exc)
            return None

    async def _ensure_session(
        self,
        namespace: MemoryOSNamespace,
    ) -> MemoryOSLiteSessionBinding | None:
        existing = self._sessions_by_namespace_uri.get(namespace.uri)
        if existing is not None:
            return existing
        persisted = self._binding_store.get(namespace.uri)
        if persisted is not None:
            self._sessions_by_namespace_uri[namespace.uri] = persisted
            return persisted
        try:
            response = await self._http().post(
                f"{self._base_url}/sessions",
                json=build_memoryos_lite_create_session_payload(namespace),
            )
            response.raise_for_status()
            payload = response.json()
            session_id = str(payload.get("id") or "")
            if not session_id:
                return None
            binding = self._binding_store.upsert_active(
                namespace_uri=namespace.uri,
                session_id=session_id,
                session_title=memoryos_lite_session_title(namespace),
            )
            self._sessions_by_namespace_uri[namespace.uri] = binding
            return binding
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos-lite session creation degraded: %s", exc)
            return None

    async def _ingest_to_binding(
        self,
        binding: MemoryOSLiteSessionBinding,
        request: MemoryOSIngestRequest,
    ) -> MemoryOSIngestResult:
        try:
            response = await self._http().post(
                f"{self._base_url}/sessions/{binding.session_id}/ingest",
                json=build_memoryos_lite_ingest_payload(request),
            )
            response.raise_for_status()
            payload = response.json()
            message = payload.get("message", {})
            message_id = message.get("id") if isinstance(message, dict) else None
            suffix = str(message_id or "inline")
            return MemoryOSIngestResult(
                ok=True,
                memory_ref=f"{binding.namespace_uri}/messages/{suffix}",
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return MemoryOSIngestResult(
                    ok=False,
                    degraded_reason="memoryos_lite_session_not_found",
                )
            logger.warning("memoryos-lite ingest degraded: %s", exc)
            return MemoryOSIngestResult(
                ok=False,
                degraded_reason="memoryos_lite_unavailable",
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos-lite ingest degraded: %s", exc)
            return MemoryOSIngestResult(
                ok=False,
                degraded_reason="memoryos_lite_unavailable",
            )

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient()
        return self._client

    async def _replace_stale_binding(
        self,
        namespace: MemoryOSNamespace,
        binding: MemoryOSLiteSessionBinding,
        *,
        reason: str,
    ) -> MemoryOSLiteSessionBinding | None:
        self._binding_store.mark_stale(binding, reason=reason)
        self._sessions_by_namespace_uri.pop(namespace.uri, None)
        return await self._ensure_session(namespace)

    async def _post_build_context_with_stale_retry(
        self,
        namespace: MemoryOSNamespace,
        binding: MemoryOSLiteSessionBinding,
        *,
        query: str,
        budget: int,
    ) -> object:
        try:
            response = await self._http().post(
                f"{self._base_url}/sessions/{binding.session_id}/build-context",
                json=build_memoryos_lite_build_context_payload(
                    query=query,
                    budget=budget,
                ),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            fresh = await self._replace_stale_binding(
                namespace,
                binding,
                reason="memoryos_lite_session_not_found",
            )
            if fresh is None:
                raise
            response = await self._http().post(
                f"{self._base_url}/sessions/{fresh.session_id}/build-context",
                json=build_memoryos_lite_build_context_payload(
                    query=query,
                    budget=budget,
                ),
            )
            response.raise_for_status()
            return response.json()

    async def _post_search_with_stale_retry(
        self,
        namespace: MemoryOSNamespace,
        binding: MemoryOSLiteSessionBinding,
        *,
        query: str,
        limit: int,
    ) -> object:
        try:
            response = await self._http().post(
                f"{self._base_url}/memory/search",
                json=build_memoryos_lite_search_payload(
                    session_id=binding.session_id,
                    query=query,
                    limit=limit,
                ),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            fresh = await self._replace_stale_binding(
                namespace,
                binding,
                reason="memoryos_lite_session_not_found",
            )
            if fresh is None:
                raise
            response = await self._http().post(
                f"{self._base_url}/memory/search",
                json=build_memoryos_lite_search_payload(
                    session_id=fresh.session_id,
                    query=query,
                    limit=limit,
                ),
            )
            response.raise_for_status()
            return response.json()


def build_memoryos_lite_interop_plan(
    namespace: MemoryOSNamespace,
    *,
    proof_level: Literal["contract", "live"] = "contract",
) -> MemoryOSLiteInteropPlan:
    return MemoryOSLiteInteropPlan(
        namespace_uri=namespace.uri,
        session_title=memoryos_lite_session_title(namespace),
        session_metadata=_namespace_metadata(namespace),
        proof_level=proof_level,
    )


def build_memoryos_lite_create_session_payload(
    namespace: MemoryOSNamespace,
) -> dict[str, str]:
    return {"title": memoryos_lite_session_title(namespace)}


def build_memoryos_lite_ingest_payload(
    request: MemoryOSIngestRequest,
) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": request.content,
        "metadata": {
            **_namespace_metadata(request.namespace),
            "xmuse_actor_id": request.actor_id,
            "xmuse_memory_layer": request.memory_layer.value,
            "xmuse_source_refs": list(request.source_refs),
            "xmuse_request_metadata": dict(request.metadata),
        },
    }


def build_memoryos_lite_build_context_payload(
    *,
    query: str,
    budget: int,
) -> dict[str, object]:
    return {
        "task": query,
        "budget": budget,
        "retrieval_query": query,
    }


def build_memoryos_lite_search_payload(
    *,
    session_id: str,
    query: str,
    limit: int,
) -> dict[str, object]:
    return {
        "query": query,
        "top_k": limit,
        "session_id": session_id,
    }


def memoryos_lite_session_title(namespace: MemoryOSNamespace) -> str:
    digest = hashlib.sha256(namespace.uri.encode("utf-8")).hexdigest()[:12]
    return f"xmuse:{namespace.kind.value}:{digest}"


def live_memoryos_lite_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    enabled = env.get(LIVE_MEMORYOS_LITE_ENV, "").strip().lower()
    base_url = env.get(MEMORYOS_LITE_BASE_URL_ENV, "").strip()
    return enabled in {"1", "true", "yes", "on"} and bool(base_url)


def _namespace_metadata(namespace: MemoryOSNamespace) -> dict[str, object]:
    return {
        "xmuse_namespace_uri": namespace.uri,
        "xmuse_namespace": namespace.model_dump(mode="json"),
    }


def _context_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for value in payload.get("pinned_core", []):
        if isinstance(value, str):
            parts.append(value)
    for item in payload.get("retrieved_evidence", []):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(str(item["text"]))
    for item in payload.get("recent_messages", []):
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            parts.append(str(item["content"]))
    for key in ("active_task_pages", "retrieved_pages"):
        for item in payload.get(key, []):
            if isinstance(item, dict):
                title = item.get("title")
                reason = item.get("reason")
                if isinstance(title, str):
                    parts.append(title)
                if isinstance(reason, str):
                    parts.append(reason)
    return "\n\n".join(part for part in parts if part)


def _context_source_refs(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    refs: list[str] = []
    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        refs.extend(_string_list(metadata.get("xmuse_source_refs")))
    for item in payload.get("retrieved_evidence", []):
        if isinstance(item, dict):
            metadata = item.get("metadata", {})
            if isinstance(metadata, dict):
                refs.extend(_string_list(metadata.get("xmuse_source_refs")))
            message_id = item.get("message_id")
            if isinstance(message_id, str):
                refs.append(f"memoryos-lite-message:{message_id}")
    for item in payload.get("recent_messages", []):
        if isinstance(item, dict):
            metadata = item.get("metadata", {})
            if isinstance(metadata, dict):
                refs.extend(_string_list(metadata.get("xmuse_source_refs")))
            message_id = item.get("id")
            if isinstance(message_id, str):
                refs.append(f"memoryos-lite-message:{message_id}")
    return refs


def _is_stale_session_result(result: MemoryOSIngestResult) -> bool:
    return result.degraded_reason == "memoryos_lite_session_not_found"


def _page_from_search_hit(
    *,
    namespace: MemoryOSNamespace,
    hit: dict[str, Any],
) -> MemoryOSPage:
    page = hit.get("page", {})
    page_payload = page if isinstance(page, dict) else {}
    return MemoryOSPage(
        namespace_uri=namespace.uri,
        content=_page_text(page_payload),
        source_refs=_dedupe(_string_list(page_payload.get("source_message_ids"))),
        metadata={
            "memoryos_lite_page_id": str(page_payload.get("id") or ""),
            "memoryos_lite_session_id": str(page_payload.get("session_id") or ""),
            "memoryos_lite_score": hit.get("score"),
            "memoryos_lite_reason": hit.get("reason"),
        },
        actor_id=None,
        memory_layer=MemoryOSMemoryLayer.TASK_STATE,
    )


def _page_text(page: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "summary"):
        value = page.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("facts", "decisions", "open_questions"):
        for value in _string_list(page.get(key)):
            parts.append(value)
    return "\n".join(part for part in parts if part)


def _trace_evidence_from_payload(
    *,
    namespace: MemoryOSNamespace,
    session_id: str,
    payload: object,
) -> MemoryOSLiteTraceEvidence:
    events: list[dict[str, object]]
    if isinstance(payload, list):
        events = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        raw_events = payload.get("trace") or payload.get("events") or []
        events = [item for item in raw_events if isinstance(item, dict)]
    else:
        events = []
    source_refs: list[str] = []
    estimated_tokens: int | None = None
    for event in events:
        metadata = event.get("metadata", {})
        if isinstance(metadata, dict):
            source_refs.extend(_string_list(metadata.get("xmuse_source_refs")))
        if estimated_tokens is None:
            tokens = event.get("estimated_tokens")
            if isinstance(tokens, int) and not isinstance(tokens, bool):
                estimated_tokens = tokens
    return MemoryOSLiteTraceEvidence(
        namespace_uri=namespace.uri,
        session_id=session_id,
        trace_events=events,
        source_refs=_dedupe(source_refs),
        estimated_tokens=estimated_tokens,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "LIVE_MEMORYOS_LITE_ENV",
    "MEMORYOS_LITE_BASE_URL_ENV",
    "MemoryOSLiteEndpointPlan",
    "MemoryOSLiteInteropAdapter",
    "MemoryOSLiteInteropPlan",
    "MemoryOSLiteSessionBinding",
    "MemoryOSLiteSessionBindingStore",
    "MemoryOSLiteTraceEvidence",
    "build_memoryos_lite_build_context_payload",
    "build_memoryos_lite_create_session_payload",
    "build_memoryos_lite_ingest_payload",
    "build_memoryos_lite_interop_plan",
    "build_memoryos_lite_search_payload",
    "live_memoryos_lite_enabled",
    "memoryos_lite_session_title",
]
