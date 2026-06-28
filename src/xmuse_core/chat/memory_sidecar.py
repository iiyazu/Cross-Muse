from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from xmuse_core.integrations.memoryos_client import MemoryOSClientProtocol, MemoryOSContext
from xmuse_core.integrations.memoryos_namespace import (
    MemoryOSNamespace,
    conversation_namespace,
)


@dataclass(frozen=True)
class GroupchatMemorySidecar:
    client: MemoryOSClientProtocol
    budget: int = 2048
    timeout_s: float = 1.0

    async def probe(self, *, conversation_id: str, query: str = "health") -> dict[str, Any]:
        namespace = conversation_namespace(conversation_id)
        base = {
            "authority": "memoryos_sidecar",
            "namespace_uri": namespace.uri,
        }
        try:
            context = await self._build_context(
                namespace,
                query=query,
                budget=min(self.budget, 256),
            )
        except TimeoutError:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": "memoryos_timeout",
            }
        except Exception as exc:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": f"memoryos_exception:{type(exc).__name__}",
            }
        if context.degraded_reason:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": context.degraded_reason,
            }
        return {
            **base,
            "status": "available",
            "proof_level": "contract",
            "degraded_reason": None,
        }

    async def recall_for_turn(
        self,
        *,
        conversation_id: str,
        actor_id: str,
        inbox_item: Any,
    ) -> dict[str, Any]:
        namespace = conversation_namespace(conversation_id)
        query = _query_for_item(inbox_item)
        base = {
            "authority": "memoryos_sidecar",
            "namespace_uri": namespace.uri,
            "actor_id": actor_id,
            "query": query,
            "budget": self.budget,
        }
        try:
            context = await self._build_context(
                namespace,
                query=query,
                budget=self.budget,
            )
        except TimeoutError:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": "memoryos_timeout",
                "source_refs": [],
            }
        except Exception as exc:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": f"memoryos_exception:{type(exc).__name__}",
                "source_refs": [],
            }
        if context.degraded_reason:
            return {
                **base,
                "status": "degraded",
                "proof_level": "degraded",
                "degraded_reason": context.degraded_reason,
                "source_refs": list(context.source_refs),
            }
        text = context.text.strip()
        if not text:
            return {
                **base,
                "status": "empty",
                "proof_level": "contract",
                "source_refs": list(context.source_refs),
            }
        return {
            **base,
            "status": "attached",
            "proof_level": "contract",
            "text": text,
            "source_refs": list(context.source_refs),
        }

    async def _build_context(
        self,
        namespace: MemoryOSNamespace,
        *,
        query: str,
        budget: int,
    ) -> MemoryOSContext:
        return await asyncio.wait_for(
            self.client.build_context(
                namespace,
                query=query,
                budget=budget,
            ),
            timeout=max(self.timeout_s, 0.001),
        )


def _query_for_item(inbox_item: Any) -> str:
    payload = getattr(inbox_item, "payload", {})
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    item_type = getattr(inbox_item, "item_type", "")
    if isinstance(item_type, str) and item_type.strip():
        return item_type.strip()
    return "xmuse groupchat turn"
