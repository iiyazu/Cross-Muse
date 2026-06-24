from __future__ import annotations

import re
from typing import Any

WRITEBACK_CONTRACT_KEY = "expected_writeback_contract"
WRITEBACK_CONTRACT_VERSION = "xmuse-writeback-contract-v1"

_NON_AUTHORITY_EVIDENCE = [
    "provider_stdout",
    "streamed_text",
    "terminal_log",
    "worker_summary",
    "local_test_output",
]


def with_expected_writeback_contract(
    payload: dict[str, Any],
    *,
    item_type: str,
    inbox_item_id: str,
    target_role: str | None,
) -> dict[str, Any]:
    normalized = dict(payload)
    existing = normalized.get(WRITEBACK_CONTRACT_KEY)
    if isinstance(existing, dict) and existing.get("version") == WRITEBACK_CONTRACT_VERSION:
        return normalized
    normalized[WRITEBACK_CONTRACT_KEY] = expected_writeback_contract(
        item_type=item_type,
        inbox_item_id=inbox_item_id,
        target_role=target_role,
        payload=normalized,
    )
    return normalized


def expected_writeback_contract(
    *,
    item_type: str,
    inbox_item_id: str,
    target_role: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    base = {
        "version": WRITEBACK_CONTRACT_VERSION,
        "inbox_item_id": inbox_item_id,
        "target_role": target_role,
        "item_type": item_type,
        "source_authority": "chat_inbox_items",
        "reply_to_inbox_item_id_required": True,
        "required_args": {"reply_to_inbox_item_id": inbox_item_id},
        "rejected_evidence": list(_NON_AUTHORITY_EVIDENCE),
    }
    if item_type == "collaboration_request":
        return {
            **base,
            "required_tool": "chat_record_collaboration_response",
            "allowed_terminal_tools": ["chat_record_collaboration_response"],
            "terminal_effect": "record_collaboration_response_and_mark_inbox_read",
            "responded_message_required": False,
            "required_args": {
                "run_id": payload.get("collaboration_run_id"),
            },
        }
    if item_type == "collaboration_callback":
        return {
            **base,
            "required_tool": "chat_emit_proposal",
            "allowed_terminal_tools": ["chat_emit_proposal"],
            "terminal_effect": "create_lane_graph_proposal_and_mark_callback_inbox_read",
            "responded_message_required": True,
            "required_marker": _collaboration_ref(payload),
        }
    if item_type == "review_trigger":
        return {
            **base,
            "required_tool": "chat_post_message",
            "allowed_terminal_tools": [
                "chat_post_message",
                "chat_raise_collaboration_blocker",
            ],
            "terminal_effect": "persist_review_feedback_or_blocker",
            "responded_message_required": True,
        }
    if _requests_chat_emit_proposal(payload):
        marker = _proposal_marker(payload)
        contract = {
            **base,
            "required_tool": "chat_emit_proposal",
            "allowed_terminal_tools": ["chat_emit_proposal"],
            "terminal_effect": "create_lane_graph_proposal_and_mark_inbox_read",
            "responded_message_required": True,
            "contract_reason": "explicit_chat_emit_proposal_request",
        }
        if marker is not None:
            contract["required_marker"] = marker
        return contract
    return {
        **base,
        "required_tool": "chat_post_message",
        "allowed_terminal_tools": [
            "chat_post_message",
            "chat_mention",
            "chat_create_collaboration_request",
            "chat_emit_proposal",
        ],
        "terminal_effect": "mark_inbox_read_with_durable_peer_writeback",
        "responded_message_required": True,
    }


def contract_from_payload_or_default(
    *,
    payload: dict[str, Any],
    item_type: str,
    inbox_item_id: str,
    target_role: str | None,
) -> dict[str, Any]:
    contract = payload.get(WRITEBACK_CONTRACT_KEY)
    if isinstance(contract, dict) and contract.get("version") == WRITEBACK_CONTRACT_VERSION:
        return dict(contract)
    return expected_writeback_contract(
        item_type=item_type,
        inbox_item_id=inbox_item_id,
        target_role=target_role,
        payload=payload,
    )


def allowed_terminal_tools(contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(contract, dict):
        return set()
    raw_tools = contract.get("allowed_terminal_tools")
    if isinstance(raw_tools, list):
        tools = {tool for tool in raw_tools if isinstance(tool, str) and tool}
        if tools:
            return tools
    required = contract.get("required_tool")
    return {required} if isinstance(required, str) and required else set()


def contract_requires_response_message(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return True
    value = contract.get("responded_message_required")
    return bool(value) if isinstance(value, bool) else True


def contract_text(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return "Expected writeback contract: none"
    required_tool = str(contract.get("required_tool") or "unknown")
    allowed_tools = ", ".join(sorted(allowed_terminal_tools(contract))) or required_tool
    terminal_effect = str(contract.get("terminal_effect") or "unknown")
    rejected = ", ".join(
        item
        for item in contract.get("rejected_evidence", [])
        if isinstance(item, str) and item
    )
    required_marker = contract.get("required_marker")
    marker_line = (
        f"\nRequired marker/reference: {required_marker}"
        if isinstance(required_marker, str) and required_marker
        else ""
    )
    return (
        "Expected writeback contract:\n"
        f"- required_tool: {required_tool}\n"
        f"- allowed_terminal_tools: {allowed_tools}\n"
        f"- terminal_effect: {terminal_effect}\n"
        "- reply_to_inbox_item_id_required: "
        f"{bool(contract.get('reply_to_inbox_item_id_required', True))}\n"
        f"- rejected_evidence: {rejected or 'none'}"
        f"{marker_line}"
    )


def _collaboration_ref(payload: dict[str, Any]) -> str | None:
    run_id = payload.get("collaboration_run_id")
    return f"collaboration:{run_id}" if isinstance(run_id, str) and run_id else None


def _requests_chat_emit_proposal(payload: dict[str, Any]) -> bool:
    content = payload.get("content")
    if not isinstance(content, str):
        return False
    lowered = " ".join(content.lower().split())
    if "chat_emit_proposal" not in lowered:
        return False
    if "do not use chat_post_message" in lowered and "proposal turn" in lowered:
        return True
    return bool(
        re.search(
            r"\b(use|call|invoke|run)\b.{0,40}\bchat_emit_proposal\b",
            lowered,
        )
    )


def _proposal_marker(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    match = re.search(r"\bcollaboration:[A-Za-z0-9_.:-]+", content)
    return match.group(0) if match is not None else None
