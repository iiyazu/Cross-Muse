from __future__ import annotations

from typing import Any

from xmuse_core.agents.persistent_peer import PeerHandle, PeerRequestResult
from xmuse_core.chat.models import ChatCard


def build_peer_request_chat_card(
    handle: PeerHandle,
    *,
    request_id: str,
    message_type: str,
    created_at: str,
    lane_id: str | None = None,
    feature_id: str | None = None,
    graph_id: str | None = None,
    href: str | None = None,
    api_href: str | None = None,
    prompt: str | None = None,
    context: Any = None,
) -> ChatCard:
    _require_non_empty("request_id", request_id)
    clean_message_type = _clean_required("message_type", message_type)
    title = f"{_display_label(clean_message_type)} request"
    return ChatCard(
        id=f"card_peer_request_{request_id}",
        conversation_id=handle.conversation_id,
        card_type="peer_request",
        source_id=request_id,
        title=title,
        summary=(
            f"Sent {clean_message_type} request {request_id} to {handle.role} peer"
        ),
        status="sent",
        href=href
        or f"/dashboard/peer-chat/conversations/{handle.conversation_id}"
        f"#peer-request-{request_id}",
        api_href=api_href or f"/api/peer-requests/{request_id}",
        created_at=created_at,
        counts=_ref_counts(handle, lane_id=lane_id, feature_id=feature_id),
        metadata=_metadata(
            handle,
            request_id=request_id,
            message_type=clean_message_type,
            lane_id=lane_id,
            feature_id=feature_id,
            graph_id=graph_id,
        ),
    )


def build_peer_result_chat_card(
    handle: PeerHandle,
    result: PeerRequestResult,
    *,
    message_type: str,
    created_at: str,
    lane_id: str | None = None,
    feature_id: str | None = None,
    graph_id: str | None = None,
    href: str | None = None,
    api_href: str | None = None,
) -> ChatCard:
    _require_non_empty("request_id", result.request_id)
    clean_message_type = _clean_required("message_type", message_type)
    title = f"{_display_label(clean_message_type)} result"
    metadata = _metadata(
        handle,
        request_id=result.request_id,
        message_type=clean_message_type,
        lane_id=lane_id,
        feature_id=feature_id,
        graph_id=graph_id,
    )
    metadata["result_status"] = result.status
    if result.reason:
        metadata["reason"] = result.reason
    return ChatCard(
        id=f"card_peer_result_{result.request_id}",
        conversation_id=handle.conversation_id,
        card_type="peer_result",
        source_id=result.request_id,
        title=title,
        summary=(
            f"Peer {clean_message_type} request {result.request_id} "
            f"finished with {result.status}"
        ),
        status=_card_result_status(result),
        href=href
        or f"/dashboard/peer-chat/conversations/{handle.conversation_id}"
        f"#peer-result-{result.request_id}",
        api_href=api_href or f"/api/peer-requests/{result.request_id}/result",
        created_at=created_at,
        counts=_ref_counts(handle, lane_id=lane_id, feature_id=feature_id),
        metadata=metadata,
    )


def _metadata(
    handle: PeerHandle,
    *,
    request_id: str,
    message_type: str,
    lane_id: str | None,
    feature_id: str | None,
    graph_id: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "request_id": request_id,
        "message_type": message_type,
        "participant_id": handle.participant_id,
        "god_session_id": handle.god_session_id,
        "role": handle.role,
        "cli_kind": handle.cli_kind,
        "runtime": handle.runtime,
        "model": handle.model,
    }
    _set_optional(metadata, "feature_scope_id", handle.feature_scope_id)
    _set_optional(metadata, "lane_id", lane_id)
    _set_optional(metadata, "feature_id", feature_id)
    _set_optional(metadata, "graph_id", graph_id)
    return metadata


def _ref_counts(
    handle: PeerHandle,
    *,
    lane_id: str | None,
    feature_id: str | None,
) -> dict[str, int]:
    feature_refs = {
        value
        for value in (_clean_optional(feature_id), _clean_optional(handle.feature_scope_id))
        if value is not None
    }
    return {
        "lane_refs": 1 if _clean_optional(lane_id) is not None else 0,
        "feature_refs": len(feature_refs),
    }


def _card_result_status(result: PeerRequestResult) -> str:
    if result.status == "ok":
        return "completed"
    if result.status == "timeout":
        return "timeout"
    return "failed"


def _display_label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _set_optional(metadata: dict[str, Any], key: str, value: str | None) -> None:
    clean = _clean_optional(value)
    if clean is not None:
        metadata[key] = clean


def _clean_required(name: str, value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{name} must be non-empty")
    return clean


def _require_non_empty(name: str, value: str) -> None:
    _clean_required(name, value)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None
