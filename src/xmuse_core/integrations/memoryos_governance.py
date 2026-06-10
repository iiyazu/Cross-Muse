from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.integrations.memoryos_client import MemoryOSMemoryLayer
from xmuse_core.integrations.memoryos_namespace import MemoryOSNamespace

RedactionHook = Callable[[str], str]


class MemoryOSPagingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace_uri: str
    actor_id: str
    memory_layer: MemoryOSMemoryLayer
    redacted_transcript: str
    source_refs: list[str] = Field(default_factory=list)


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
]


def default_redaction_hook(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def prepare_llm_paging_payload(
    *,
    namespace: MemoryOSNamespace,
    actor_id: str,
    transcript: str,
    source_refs: list[str],
    memory_layer: MemoryOSMemoryLayer = MemoryOSMemoryLayer.TASK_STATE,
    redaction_hook: RedactionHook = default_redaction_hook,
) -> MemoryOSPagingPayload:
    actor_id = _require_non_empty(actor_id, "actor_id")
    transcript = _require_non_empty(transcript, "transcript")
    return MemoryOSPagingPayload(
        namespace_uri=namespace.uri,
        actor_id=actor_id,
        memory_layer=memory_layer,
        redacted_transcript=redaction_hook(transcript),
        source_refs=[_require_non_empty(ref, "source_refs") for ref in source_refs],
    )


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value
