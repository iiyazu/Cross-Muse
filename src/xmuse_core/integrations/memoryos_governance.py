from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.integrations.memoryos_client import (
    MemoryOSIngestRequest,
    MemoryOSMemoryLayer,
)
from xmuse_core.integrations.memoryos_namespace import (
    MemoryOSNamespace,
    MemoryOSNamespaceKind,
)

RedactionHook = Callable[[str], str]
MemoryOSGovernanceStatus = Literal["ok", "blocked"]
MemoryOSGovernanceDecision = Literal[
    "ingest",
    "promote_to_shared",
    "provider_session_binding_only",
    "blocked",
]
MemoryOSGovernanceProofLevel = Literal["contract_proof", "manual_gap"]


class MemoryOSGovernanceScope(StrEnum):
    PERSONAL = "personal"
    TASK = "task"
    SHARED = "shared"
    GLOBAL = "global"


PROVIDER_SESSION_EVENT_KINDS = frozenset(
    {
        "provider_session_binding",
        "provider_session_continuity",
        "god_session_heartbeat",
    }
)


class MemoryOSGovernedWritePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    scope: MemoryOSGovernanceScope
    event_kind: str
    status: MemoryOSGovernanceStatus
    decision: MemoryOSGovernanceDecision
    proof_level: MemoryOSGovernanceProofLevel
    target_namespace_uri: str
    shared_namespace_uri: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    next_action: str | None = None
    namespace: MemoryOSNamespace
    shared_namespace: MemoryOSNamespace | None = None
    actor_id: str
    content: str
    memory_layer: MemoryOSMemoryLayer
    metadata: dict[str, object] = Field(default_factory=dict)

    def to_ingest_request(self) -> MemoryOSIngestRequest | None:
        if self.status != "ok":
            return None
        if self.decision not in {"ingest", "promote_to_shared"}:
            return None
        return MemoryOSIngestRequest(
            namespace=self.namespace,
            actor_id=self.actor_id,
            content=self.content,
            source_refs=list(self.source_refs),
            memory_layer=self.memory_layer,
            metadata=dict(self.metadata),
            promote_to_shared=self.decision == "promote_to_shared",
            shared_namespace=self.shared_namespace
            if self.decision == "promote_to_shared"
            else None,
        )


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


def plan_memoryos_governed_write(
    *,
    scope: MemoryOSGovernanceScope,
    event_kind: str,
    namespace: MemoryOSNamespace,
    actor_id: str,
    content: str,
    source_refs: list[str],
    memory_layer: MemoryOSMemoryLayer | None = None,
    promote_to_shared: bool = False,
    shared_namespace: MemoryOSNamespace | None = None,
    reviewed: bool = False,
    metadata: dict[str, object] | None = None,
) -> MemoryOSGovernedWritePlan:
    clean_actor = _require_non_empty(actor_id, "actor_id")
    clean_event = _require_non_empty(event_kind, "event_kind")
    clean_content = _require_non_empty(content, "content")
    clean_refs = [_require_non_empty(ref, "source_refs") for ref in source_refs]
    selected_layer = memory_layer or _default_memory_layer(scope)
    base_metadata = {
        **(dict(metadata) if metadata is not None else {}),
        "xmuse_memory_governance_scope": scope.value,
        "xmuse_memory_governance_decision": "ingest",
        "xmuse_memory_event_kind": clean_event,
        "xmuse_memory_reviewed": reviewed,
    }
    if not clean_refs:
        return _blocked_plan(
            scope=scope,
            event_kind=clean_event,
            namespace=namespace,
            shared_namespace=shared_namespace,
            actor_id=clean_actor,
            content=clean_content,
            source_refs=[],
            memory_layer=selected_layer,
            metadata=base_metadata,
            blocked_reason="memory writes require source_refs",
            next_action="Attach durable chat, blueprint, review, MemoryOS, or GitHub source refs.",
        )
    if clean_event in PROVIDER_SESSION_EVENT_KINDS:
        return MemoryOSGovernedWritePlan(
            scope=scope,
            event_kind=clean_event,
            status="ok",
            decision="provider_session_binding_only",
            proof_level="contract_proof",
            target_namespace_uri=namespace.uri,
            shared_namespace_uri=shared_namespace.uri if shared_namespace else None,
            source_refs=clean_refs,
            next_action=(
                "Keep provider continuity in GodSessionRecord/ProviderSessionBindingStore; "
                "do not mirror live session state into MemoryOS."
            ),
            namespace=namespace,
            shared_namespace=shared_namespace,
            actor_id=clean_actor,
            content=clean_content,
            memory_layer=selected_layer,
            metadata={
                **base_metadata,
                "xmuse_memory_governance_decision": "provider_session_binding_only",
            },
        )
    if promote_to_shared and shared_namespace is None:
        return _blocked_plan(
            scope=scope,
            event_kind=clean_event,
            namespace=namespace,
            shared_namespace=shared_namespace,
            actor_id=clean_actor,
            content=clean_content,
            source_refs=clean_refs,
            memory_layer=selected_layer,
            metadata=base_metadata,
            blocked_reason="shared promotion requires shared_namespace",
            next_action="Provide an explicit memory://global/shared/<repo> namespace.",
        )
    if promote_to_shared and shared_namespace.kind is not MemoryOSNamespaceKind.SHARED:
        return _blocked_plan(
            scope=scope,
            event_kind=clean_event,
            namespace=namespace,
            shared_namespace=shared_namespace,
            actor_id=clean_actor,
            content=clean_content,
            source_refs=clean_refs,
            memory_layer=selected_layer,
            metadata=base_metadata,
            blocked_reason="shared promotion requires a shared namespace",
            next_action="Use shared_namespace(repo_id) for reviewed cross-GOD memory.",
        )
    shared_or_global_scope = scope in {
        MemoryOSGovernanceScope.SHARED,
        MemoryOSGovernanceScope.GLOBAL,
    }
    if (promote_to_shared or shared_or_global_scope) and not reviewed:
        return _blocked_plan(
            scope=scope,
            event_kind=clean_event,
            namespace=namespace,
            shared_namespace=shared_namespace,
            actor_id=clean_actor,
            content=clean_content,
            source_refs=clean_refs,
            memory_layer=selected_layer,
            metadata=base_metadata,
            blocked_reason="shared promotion requires explicit review",
            next_action="Attach review evidence before promoting memory beyond task scope.",
        )
    decision: MemoryOSGovernanceDecision = (
        "promote_to_shared" if promote_to_shared else "ingest"
    )
    return MemoryOSGovernedWritePlan(
        scope=scope,
        event_kind=clean_event,
        status="ok",
        decision=decision,
        proof_level="contract_proof",
        target_namespace_uri=namespace.uri,
        shared_namespace_uri=shared_namespace.uri if shared_namespace else None,
        source_refs=clean_refs,
        namespace=namespace,
        shared_namespace=shared_namespace,
        actor_id=clean_actor,
        content=clean_content,
        memory_layer=selected_layer,
        metadata={
            **base_metadata,
            "xmuse_memory_governance_decision": decision,
        },
    )


def _blocked_plan(
    *,
    scope: MemoryOSGovernanceScope,
    event_kind: str,
    namespace: MemoryOSNamespace,
    shared_namespace: MemoryOSNamespace | None,
    actor_id: str,
    content: str,
    source_refs: list[str],
    memory_layer: MemoryOSMemoryLayer,
    metadata: dict[str, object],
    blocked_reason: str,
    next_action: str,
) -> MemoryOSGovernedWritePlan:
    return MemoryOSGovernedWritePlan(
        scope=scope,
        event_kind=event_kind,
        status="blocked",
        decision="blocked",
        proof_level="manual_gap",
        target_namespace_uri=namespace.uri,
        shared_namespace_uri=shared_namespace.uri if shared_namespace else None,
        source_refs=source_refs,
        blocked_reason=blocked_reason,
        next_action=next_action,
        namespace=namespace,
        shared_namespace=shared_namespace,
        actor_id=actor_id,
        content=content,
        memory_layer=memory_layer,
        metadata={
            **metadata,
            "xmuse_memory_governance_decision": "blocked",
        },
    )


def _default_memory_layer(scope: MemoryOSGovernanceScope) -> MemoryOSMemoryLayer:
    if scope is MemoryOSGovernanceScope.GLOBAL:
        return MemoryOSMemoryLayer.PINNED_CORE
    return MemoryOSMemoryLayer.TASK_STATE


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


__all__ = [
    "MemoryOSGovernanceScope",
    "MemoryOSGovernedWritePlan",
    "MemoryOSPagingPayload",
    "default_redaction_hook",
    "plan_memoryos_governed_write",
    "prepare_llm_paging_payload",
]
