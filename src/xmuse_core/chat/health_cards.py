from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xmuse_core.chat.models import ChatCard

RUN_HEALTH_CARD_COUNT_KEYS = (
    "live",
    "stale",
    "retrying",
    "blocked",
    "infra_failed",
    "terminal",
    "degraded_fallback",
    "required_peer_failures",
    "takeover_context_needed",
)


def build_run_health_chat_card(
    conversation_id: str,
    run_health: Mapping[str, Any],
    *,
    created_at: str,
    href: str = "/dashboard/health",
    api_href: str = "/api/run-health",
) -> ChatCard:
    counts = _chat_counts(run_health)
    return ChatCard(
        id=f"card_health_summary_{conversation_id}",
        conversation_id=conversation_id,
        card_type="health_summary",
        source_id="run_health",
        title="Run health",
        summary=_summary_text(counts),
        status=_status(counts),
        href=href,
        api_href=api_href,
        created_at=created_at,
        counts=counts,
        metadata=_chat_metadata(run_health),
    )


def _chat_counts(run_health: Mapping[str, Any]) -> dict[str, int]:
    raw_counts = run_health.get("counts")
    source = raw_counts if isinstance(raw_counts, Mapping) else {}
    counts = {key: _count_value(source.get(key)) for key in RUN_HEALTH_CARD_COUNT_KEYS}
    counts["required_peer_failures"] = _required_peer_failure_count(
        run_health.get("peer_delivery"),
        fallback=counts["required_peer_failures"],
    )
    return counts


def _required_peer_failure_count(raw_peer_delivery: Any, *, fallback: int) -> int:
    if not isinstance(raw_peer_delivery, Mapping):
        return fallback
    failures = raw_peer_delivery.get("required_peer_failures")
    if not isinstance(failures, list):
        return fallback
    return len([item for item in failures if isinstance(item, Mapping)])


def _chat_metadata(run_health: Mapping[str, Any]) -> dict[str, Any]:
    peer_delivery = run_health.get("peer_delivery")
    if not isinstance(peer_delivery, Mapping):
        return {}
    mode_counts = _peer_delivery_mode_counts(peer_delivery.get("counts_by_delivery_mode"))
    if not mode_counts:
        return {}
    return {"peer_delivery_modes": mode_counts}


def _peer_delivery_mode_counts(raw_counts: Any) -> dict[str, int]:
    if not isinstance(raw_counts, Mapping):
        return {}
    counts: dict[str, int] = {}
    for raw_key, raw_value in raw_counts.items():
        key = str(raw_key).strip()
        value = _count_value(raw_value)
        if key and value > 0:
            counts[key] = value
    return counts


def _count_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _summary_text(counts: Mapping[str, int]) -> str:
    return ", ".join(
        f"{counts[key]} {_summary_label(key)}" for key in RUN_HEALTH_CARD_COUNT_KEYS
    )


def _summary_label(key: str) -> str:
    return key.replace("_", " ")


def _status(counts: Mapping[str, int]) -> str:
    if any(counts[key] > 0 for key in ("stale", "retrying", "blocked", "infra_failed")):
        return "degraded"
    return "ok"
