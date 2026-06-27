from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_NATURAL_ROUTE_MAX_DEPTH = 3


@dataclass(frozen=True)
class NaturalRouteEvent:
    route_id: str
    conversation_id: str
    origin_message_id: str
    source_kind: str
    author_participant_id: str | None
    target_participant_id: str
    route_kind: str
    depth: int
    route_key: str
    source_refs: tuple[str, ...]
    status: str = "pending"
    blocker_reason: str | None = None

    def model_dump(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        return payload


def natural_route_key(
    *,
    conversation_id: str,
    origin_message_id: str,
    author_participant_id: str | None,
    target_participant_id: str,
    route_kind: str,
) -> str:
    raw = json.dumps(
        {
            "conversation_id": conversation_id,
            "origin_message_id": origin_message_id,
            "author_participant_id": author_participant_id,
            "target_participant_id": target_participant_id,
            "route_kind": route_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "natural-route:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_natural_route_event(
    *,
    conversation_id: str,
    origin_message_id: str,
    source_kind: str,
    author_participant_id: str | None,
    target_participant_id: str,
    route_kind: str,
    source_refs: list[str] | tuple[str, ...],
    depth: int = 1,
    blocker_reason: str | None = None,
) -> NaturalRouteEvent:
    route_key = natural_route_key(
        conversation_id=conversation_id,
        origin_message_id=origin_message_id,
        author_participant_id=author_participant_id,
        target_participant_id=target_participant_id,
        route_kind=route_kind,
    )
    return NaturalRouteEvent(
        route_id=route_key,
        conversation_id=conversation_id,
        origin_message_id=origin_message_id,
        source_kind=source_kind,
        author_participant_id=author_participant_id,
        target_participant_id=target_participant_id,
        route_kind=route_kind,
        depth=depth,
        route_key=route_key,
        source_refs=tuple(source_refs),
        status="blocked" if blocker_reason else "pending",
        blocker_reason=blocker_reason,
    )


def next_natural_route_depth(source_payload: dict[str, Any] | None) -> int:
    parent_depth = _natural_route_depth(source_payload)
    if parent_depth is None:
        return 1
    return parent_depth + 1


def natural_route_depth_exceeded(
    depth: int,
    *,
    max_depth: int = DEFAULT_NATURAL_ROUTE_MAX_DEPTH,
) -> bool:
    return depth > max_depth


def natural_route_payload(
    event: NaturalRouteEvent,
    *,
    content: str,
    mention: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "content": content,
        "source_kind": event.source_kind,
        "route_kind": event.route_kind,
        "route_depth": event.depth,
        "route_id": event.route_id,
        "route_key": event.route_key,
        "source_refs": list(event.source_refs),
        "natural_route": event.model_dump(),
    }
    if mention is not None:
        payload["mention"] = mention
    if event.blocker_reason:
        payload["blocker_reason"] = event.blocker_reason
    if extra:
        payload.update(extra)
    return payload


def _natural_route_depth(source_payload: dict[str, Any] | None) -> int | None:
    if not isinstance(source_payload, dict):
        return None
    natural_route = source_payload.get("natural_route")
    if isinstance(natural_route, dict):
        depth = natural_route.get("depth")
        if isinstance(depth, int):
            return depth
    depth = source_payload.get("route_depth")
    if isinstance(depth, int):
        return depth
    return None
