from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from xmuse_core.integrations.memoryos_client import MemoryOSIngestRequest
from xmuse_core.integrations.memoryos_lite_interop import (
    MemoryOSLiteInteropAdapter,
    MemoryOSLiteSessionBindingStore,
)
from xmuse_core.integrations.memoryos_namespace import MemoryOSNamespace


async def capture_memoryos_lite_live_trace_artifact(
    *,
    base_url: str,
    namespace: MemoryOSNamespace,
    actor_id: str,
    content: str,
    query: str,
    output_path: str | Path,
    source_refs: Sequence[str] = (),
    metadata: Mapping[str, object] | None = None,
    budget: int = 4096,
    http_client: httpx.AsyncClient | None = None,
    binding_store_path: str | Path | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a live MemoryOS Lite REST trace capture and write the raw artifact.

    This deliberately writes the pre-gate `xmuse.memoryos_lite_trace.v1`
    artifact. `capture_memoryos_live_release_gate` remains responsible for
    validating whether the artifact can satisfy release readiness.
    """

    refs = _dedupe([str(ref) for ref in source_refs if str(ref).strip()])
    store = MemoryOSLiteSessionBindingStore(binding_store_path)
    client = http_client or httpx.AsyncClient(timeout=timeout)
    should_close_client = http_client is None
    try:
        adapter = MemoryOSLiteInteropAdapter(
            base_url=base_url,
            http_client=client,
            binding_store=store,
        )
        ingest = await adapter.ingest(
            MemoryOSIngestRequest(
                namespace=namespace,
                actor_id=actor_id,
                content=content,
                source_refs=refs,
                metadata={
                    **dict(metadata or {}),
                    "xmuse_capture_kind": "memoryos_lite_live_trace",
                },
            )
        )
        context = await adapter.build_context(namespace, query=query, budget=budget)
        trace = await adapter.fetch_trace(namespace)
    finally:
        if should_close_client:
            await client.aclose()

    blockers: list[dict[str, object]] = []
    if not ingest.ok:
        blockers.append(
            _blocker(
                ingest.degraded_reason or "memoryos_lite_ingest_failed",
                source_refs=refs,
            )
        )
    if context.degraded_reason is not None:
        blockers.append(
            _blocker(
                context.degraded_reason,
                source_refs=refs,
            )
        )
    if trace is None:
        blockers.append(_blocker("memoryos_lite_trace_unavailable", source_refs=refs))

    binding = store.get(namespace.uri)
    session_id = trace.session_id if trace is not None else binding.session_id if binding else ""
    trace_events = trace.trace_events if trace is not None else []
    estimated_tokens = trace.estimated_tokens if trace is not None else None
    artifact_refs = list(refs)
    if ingest.memory_ref is not None:
        artifact_refs.append(ingest.memory_ref)
    artifact_refs.extend(context.source_refs)
    if trace is not None:
        artifact_refs.extend(trace.source_refs)
    source_refs_out = _dedupe(artifact_refs)
    target_refs = _memoryos_target_refs(
        namespace_uri=namespace.uri,
        session_id=session_id,
    )
    trace_id = _trace_id(
        namespace_uri=namespace.uri,
        session_id=session_id,
        trace_events=trace_events,
        source_refs=source_refs_out,
    )

    proof_level = "live_service_proof" if trace is not None else "manual_gap"
    artifact: dict[str, Any] = {
        "schema_version": "xmuse.memoryos_lite_trace.v1",
        "trace_id": trace_id,
        "proof_level": proof_level,
        "fact_state": "blocked" if blockers else "observed",
        "namespace_uri": namespace.uri,
        "session_id": session_id,
        "trace_events": trace_events,
        "source_refs": source_refs_out,
        "target_refs": target_refs,
        "estimated_tokens": estimated_tokens,
        "blockers": blockers,
        "captured_at": _utc_now(),
    }
    _write_json(Path(output_path), artifact)
    return artifact


def capture_memoryos_lite_live_trace_manual_gap_artifact(
    *,
    namespace: MemoryOSNamespace,
    output_path: str | Path,
    reason: str = "memoryos_lite_live_environment_missing",
    source_refs: Sequence[str] = (),
) -> dict[str, Any]:
    refs = _dedupe([str(ref) for ref in source_refs if str(ref).strip()])
    artifact: dict[str, Any] = {
        "schema_version": "xmuse.memoryos_lite_trace.v1",
        "trace_id": None,
        "proof_level": "manual_gap",
        "fact_state": "blocked",
        "namespace_uri": namespace.uri,
        "session_id": "",
        "trace_events": [],
        "source_refs": refs,
        "target_refs": _memoryos_target_refs(namespace_uri=namespace.uri, session_id=""),
        "estimated_tokens": None,
        "blockers": [_blocker(reason, source_refs=refs)],
        "captured_at": _utc_now(),
    }
    _write_json(Path(output_path), artifact)
    return artifact


def _blocker(reason: str, *, source_refs: Sequence[str]) -> dict[str, object]:
    return {
        "reason": reason,
        "source_refs": _dedupe([str(ref) for ref in source_refs if str(ref).strip()]),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _memoryos_target_refs(*, namespace_uri: str, session_id: str) -> list[str]:
    refs = [f"memoryos:namespace:{namespace_uri}"]
    if session_id.strip():
        refs.append(f"memoryos:session:{session_id}")
    return refs


def _trace_id(
    *,
    namespace_uri: str,
    session_id: str,
    trace_events: Sequence[Mapping[str, object]],
    source_refs: Sequence[str],
) -> str | None:
    if not session_id.strip() or not trace_events:
        return None
    material = {
        "namespace_uri": namespace_uri,
        "session_id": session_id,
        "trace_events": list(trace_events),
        "source_refs": list(source_refs),
    }
    digest = sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"xmuse-memoryos-trace:{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "capture_memoryos_lite_live_trace_artifact",
    "capture_memoryos_lite_live_trace_manual_gap_artifact",
]
