from __future__ import annotations

import logging
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xmuse_core.integrations.memoryos_namespace import MemoryOSNamespace

logger = logging.getLogger(__name__)


class MemoryOSMemoryLayer(StrEnum):
    PINNED_CORE = "pinned_core"
    TASK_STATE = "task_state"
    ARCHIVAL = "archival"


class MemoryOSPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    content: str
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    actor_id: str | None = None
    memory_layer: MemoryOSMemoryLayer = MemoryOSMemoryLayer.TASK_STATE


class MemoryOSIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: MemoryOSNamespace
    actor_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    memory_layer: MemoryOSMemoryLayer = MemoryOSMemoryLayer.TASK_STATE
    metadata: dict[str, object] = Field(default_factory=dict)
    promote_to_shared: bool = False
    shared_namespace: MemoryOSNamespace | None = None

    @model_validator(mode="after")
    def _validate_shared_promotion(self) -> MemoryOSIngestRequest:
        if self.promote_to_shared and self.shared_namespace is None:
            raise ValueError("shared_namespace is required when promote_to_shared is true")
        return self


class MemoryOSIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    memory_ref: str | None = None
    degraded_reason: str | None = None


class MemoryOSContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    text: str
    source_refs: list[str] = Field(default_factory=list)
    degraded_reason: str | None = None


class MemoryOSClientProtocol(Protocol):
    async def ingest(self, request: MemoryOSIngestRequest) -> MemoryOSIngestResult: ...

    async def build_context(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        budget: int = 4096,
    ) -> MemoryOSContext: ...

    async def search(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        limit: int = 10,
    ) -> list[MemoryOSPage]: ...


class FakeMemoryOSClient:
    def __init__(self) -> None:
        self._pages_by_namespace: dict[str, list[MemoryOSPage]] = {}
        self._tombstoned_source_refs_by_namespace: dict[str, set[str]] = {}

    async def ingest(self, request: MemoryOSIngestRequest) -> MemoryOSIngestResult:
        page = MemoryOSPage(
            namespace_uri=request.namespace.uri,
            content=request.content,
            source_refs=_dedupe(request.source_refs),
            metadata=dict(request.metadata),
            actor_id=request.actor_id,
            memory_layer=request.memory_layer,
        )
        self._pages_by_namespace.setdefault(request.namespace.uri, []).append(page)
        if request.promote_to_shared and request.shared_namespace is not None:
            self._pages_by_namespace.setdefault(request.shared_namespace.uri, []).append(
                page.model_copy(update={"namespace_uri": request.shared_namespace.uri})
            )
        return MemoryOSIngestResult(ok=True, memory_ref=_memory_ref_for_page(page))

    async def build_context(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        budget: int = 4096,
    ) -> MemoryOSContext:
        pages = await self.search(namespace, query=query, limit=budget)
        text = "\n\n".join(page.content for page in pages)
        source_refs: list[str] = []
        for page in pages:
            source_refs.extend(page.source_refs)
        return MemoryOSContext(
            namespace_uri=namespace.uri,
            text=text[:budget],
            source_refs=_dedupe(source_refs),
        )

    async def search(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        limit: int = 10,
    ) -> list[MemoryOSPage]:
        query_lower = query.lower()
        pages = self._pages_by_namespace.get(namespace.uri, [])
        tombstoned_source_refs = self._tombstoned_source_refs_by_namespace.get(
            namespace.uri,
            set(),
        )
        matched = [
            page
            for page in pages
            if not query_lower or query_lower in page.content.lower()
            if not tombstoned_source_refs.intersection(page.source_refs)
        ]
        return matched[:limit]

    def tombstone_source_refs(
        self,
        namespace: MemoryOSNamespace,
        *,
        source_refs: list[str],
    ) -> None:
        refs = {_clean_ref(ref) for ref in source_refs}
        self._tombstoned_source_refs_by_namespace.setdefault(namespace.uri, set()).update(refs)


class RestMemoryOSClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_client

    async def ingest(self, request: MemoryOSIngestRequest) -> MemoryOSIngestResult:
        try:
            response = await self._http().post(
                f"{self._base_url}/memory/ingest",
                json={
                    "namespace": request.namespace.model_dump(mode="json"),
                    "namespace_uri": request.namespace.uri,
                    "actor_id": request.actor_id,
                    "content": request.content,
                    "source_refs": request.source_refs,
                    "memory_layer": request.memory_layer.value,
                    "metadata": request.metadata,
                    "promote_to_shared": request.promote_to_shared,
                    "shared_namespace_uri": (
                        request.shared_namespace.uri if request.shared_namespace else None
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
            return MemoryOSIngestResult(
                ok=True,
                memory_ref=str(payload.get("memory_ref") or ""),
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos ingest degraded: %s", exc)
            return MemoryOSIngestResult(ok=False, degraded_reason="memoryos_unavailable")

    async def build_context(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        budget: int = 4096,
    ) -> MemoryOSContext:
        try:
            response = await self._http().post(
                f"{self._base_url}/memory/build-context",
                json={
                    "namespace": namespace.model_dump(mode="json"),
                    "namespace_uri": namespace.uri,
                    "query": query,
                    "budget": budget,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text=str(payload.get("context") or payload.get("text") or ""),
                source_refs=[
                    str(ref) for ref in payload.get("source_refs", []) if isinstance(ref, str)
                ],
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos build_context degraded: %s", exc)
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text="",
                degraded_reason="memoryos_unavailable",
            )

    async def search(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        limit: int = 10,
    ) -> list[MemoryOSPage]:
        try:
            response = await self._http().post(
                f"{self._base_url}/memory/search",
                json={
                    "namespace": namespace.model_dump(mode="json"),
                    "namespace_uri": namespace.uri,
                    "query": query,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            if not isinstance(items, list):
                return []
            return [MemoryOSPage.model_validate(item) for item in items if isinstance(item, dict)]
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("memoryos search degraded: %s", exc)
            return []

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        headers = {"X-API-Key": self._api_key} if self._api_key else None
        self._client = httpx.AsyncClient(headers=headers)
        return self._client


def _memory_ref_for_page(page: MemoryOSPage) -> str:
    if page.source_refs:
        return f"{page.namespace_uri}/refs/{page.source_refs[0]}"
    return f"{page.namespace_uri}/refs/inline"


def _clean_ref(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("source_ref must be non-empty")
    return value


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
