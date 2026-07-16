"""Strict loopback HTTP client for the optional MemoryOS sidecar."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal

from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_FULL_LOCAL_RECALL_TIMEOUT_S,
    ROOM_MEMORY_MAX_RESPONSE_BYTES,
    ROOM_MEMORY_MAX_TOKENS,
    ROOM_MEMORY_RECALL_TIMEOUT_S,
)

MEMORYOS_SOURCE_EVIDENCE_PROFILE = "source_evidence/v1"
MEMORYOS_SOURCE_EVIDENCE_V2_PROFILE = "source_evidence/v2"
_MAX_REQUEST_BYTES = 64 * 1024
_MEMORYOS_CONTEXT_HTTP_MAX_BYTES = 128 * 1024


class MemoryOSAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class MemoryOSHTTPClient:
    """Call only the fixed, public MemoryOS endpoints used by xmuse."""

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
        return required_id(payload, "id", "memoryos_session_response_invalid")

    def ingest_message(
        self,
        *,
        session_id: str,
        external_id: str,
        role: Literal["user", "assistant"],
        content: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
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
        required_id(payload, "attachment_id", "memoryos_attachment_response_invalid")
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
            if not isinstance(item, Mapping) or set(item) != {
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
                or not 0 < len(item["source_refs"]) <= 8
                or not isinstance(item.get("created_at"), str)
            ):
                raise MemoryOSAdapterError("memoryos_advisory_contract_invalid")
            result.append(item)
        return result

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


def required_id(payload: Mapping[str, Any], key: str, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise MemoryOSAdapterError(code)
    return value


# Compatibility name used by existing callers while composition migrates.
MemoryOSArchiveAdapter = MemoryOSHTTPClient

__all__ = [
    "MEMORYOS_SOURCE_EVIDENCE_PROFILE",
    "MEMORYOS_SOURCE_EVIDENCE_V2_PROFILE",
    "MemoryOSAdapterError",
    "MemoryOSArchiveAdapter",
    "MemoryOSHTTPClient",
    "required_id",
]
