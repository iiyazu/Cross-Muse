from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xmuse_core.integrations.memoryos_client import (
    MemoryOSClientProtocol,
    MemoryOSIngestRequest,
    MemoryOSIngestResult,
)
from xmuse_core.integrations.memoryos_namespace import (
    MemoryOSNamespace,
    deterministic_memory_source_ref,
)

MemoryOSWritebackKind = Literal[
    "proposal_accepted",
    "blueprint_frozen",
    "feature_reworked",
    "review_verdict_finalized",
    "pr_merged",
]


class MemoryOSWritebackEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryOSWritebackKind
    namespace: MemoryOSNamespace
    event_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    commit_sha: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    promote_to_shared: bool = False
    shared_namespace: MemoryOSNamespace | None = None

    @model_validator(mode="after")
    def _validate_shared_promotion(self) -> MemoryOSWritebackEvent:
        if self.promote_to_shared and self.shared_namespace is None:
            raise ValueError("shared_namespace is required when promote_to_shared is true")
        return self

    @property
    def deterministic_source_ref(self) -> str:
        return deterministic_memory_source_ref(
            self.namespace,
            event_kind=self.kind,
            event_id=self.event_id,
            commit_sha=self.commit_sha,
        )

    def to_ingest_request(self) -> MemoryOSIngestRequest:
        source_refs = _dedupe([self.deterministic_source_ref, *self.source_refs])
        return MemoryOSIngestRequest(
            namespace=self.namespace,
            content=_render_event_content(self.kind, self.summary, source_refs),
            source_refs=source_refs,
            metadata={"memory_writeback_kind": self.kind, **self.metadata},
            promote_to_shared=self.promote_to_shared,
            shared_namespace=self.shared_namespace,
        )


async def write_memory_event(
    client: MemoryOSClientProtocol,
    event: MemoryOSWritebackEvent,
) -> MemoryOSIngestResult:
    return await client.ingest(event.to_ingest_request())


async def build_god_prompt_memory_block(
    client: MemoryOSClientProtocol,
    namespace: MemoryOSNamespace,
    *,
    task: str,
    query: str,
    budget: int = 4096,
) -> str:
    context = await client.build_context(namespace, query=query or task, budget=budget)
    if context.degraded_reason or not context.text.strip():
        return ""
    lines = ["## MemoryOS Context", "", context.text.strip()]
    if context.source_refs:
        lines.extend(["", "Source refs:"])
        lines.extend(f"- {ref}" for ref in context.source_refs)
    return "\n".join(lines)


def _render_event_content(kind: str, summary: str, source_refs: list[str]) -> str:
    lines = [f"Event: {kind}", f"Summary: {summary}"]
    if source_refs:
        lines.append("Source refs:")
        lines.extend(f"- {ref}" for ref in source_refs)
    return "\n".join(lines)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
