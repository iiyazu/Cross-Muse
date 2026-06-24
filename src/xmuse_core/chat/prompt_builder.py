from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.participant_store import Participant
from xmuse_core.chat.writeback_contract import contract_text

PROMPT_CONTRACT_VERSION = "xmuse-peer-chat-prompt-v2"


@dataclass(frozen=True)
class PromptLayer:
    name: str
    content: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "metadata": dict(self.metadata),
            "sha256": _sha256(self.content),
        }


@dataclass(frozen=True)
class AssembledPrompt:
    version: str
    text: str
    layers: tuple[PromptLayer, ...]
    fingerprint: str

    def as_context_artifact(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "layer_order": [layer.name for layer in self.layers],
            "layers": [layer.as_dict() for layer in self.layers],
            "text": self.text,
        }

    def as_session_contract(self) -> dict[str, Any]:
        return {
            "prompt_contract_version": self.version,
            "prompt_layer_order": [layer.name for layer in self.layers],
            "prompt_layer_hashes": {
                layer.name: _sha256(layer.content) for layer in self.layers
            },
            "prompt_artifact_fingerprint": self.fingerprint,
        }


class XmusePromptBuilder:
    def build_peer_chat_prompt(
        self,
        *,
        participant: Participant,
        inbox_item: Any,
        group_context: dict[str, Any],
    ) -> AssembledPrompt:
        layers = (
            _governance_layer(),
            _member_identity_layer(participant),
            _roster_layer(group_context),
            _context_capsule_layer(group_context, inbox_item),
            _tool_writeback_layer(inbox_item),
        )
        text = "\n\n".join(
            f"## {layer.name}\n\n{layer.content.strip()}" for layer in layers
        ).strip() + "\n"
        return AssembledPrompt(
            version=PROMPT_CONTRACT_VERSION,
            text=text,
            layers=layers,
            fingerprint=_sha256(text),
        )


def _governance_layer() -> PromptLayer:
    return PromptLayer(
        name="xmuse_governance_l0",
        content=(
            "You are an xmuse GOD peer turn worker in a durable groupchat.\n"
            "Durable chat state is reply truth. Provider stdout, streamed text, "
            "terminal logs, worker summaries, and local tests are evidence only.\n"
            "A successful peer reply must be written through MCP/callback "
            "writeback and close the relevant inbox item.\n"
            "Do not claim production readiness, GitHub review truth, merge truth, "
            "live MemoryOS, full closure, or overnight readiness."
        ),
        metadata={"authority": "governance", "required": True},
    )


def _member_identity_layer(participant: Participant) -> PromptLayer:
    return PromptLayer(
        name="member_identity",
        content=(
            f"Role: {participant.role}\n"
            f"Display name: {participant.display_name}\n"
            f"Participant id: {participant.participant_id}\n"
            f"Provider: {participant.cli_kind}\n"
            f"Model: {participant.model}\n"
            "Speak as your assigned role. Respect the writeback contract and "
            "do not treat yourself as a private one-shot worker."
        ),
        metadata={
            "participant_id": participant.participant_id,
            "role": participant.role,
            "cli_kind": participant.cli_kind,
            "model": participant.model,
        },
    )


def _roster_layer(group_context: dict[str, Any]) -> PromptLayer:
    return PromptLayer(
        name="roster_and_capabilities",
        content=(
            "This is a group chat, not a private point-to-point chat. You can see "
            "the participant roster and recent transcript in xmuse_context.group_chat. "
            "Speak as your assigned role, be aware of the other GOD participants, "
            "and route messages to GODs with chat_mention when actual work should "
            "be handed off. Do not greet repeatedly or bounce hello messages unless "
            "the user explicitly asks for a greeting. Do not address @human unless "
            "the user explicitly asks you to mention the human.\n"
            f"Current participants: {_participant_roster_text(group_context)}\n"
            f"Turn guidance: {_turn_guidance_text(group_context)}"
        ),
        metadata={"participant_count": len(group_context.get("participants", []))},
    )


def _context_capsule_layer(group_context: dict[str, Any], inbox_item: Any) -> PromptLayer:
    capsule = group_context.get("context_capsule")
    capsule_version = "unknown"
    recent_messages = []
    if isinstance(capsule, dict):
        raw_version = capsule.get("version")
        if isinstance(raw_version, str) and raw_version:
            capsule_version = raw_version
        raw_messages = capsule.get("recent_messages")
        if isinstance(raw_messages, list):
            recent_messages = raw_messages[-8:]
    transcript = _recent_transcript_text(recent_messages)
    request_preview = _inbox_request_preview(getattr(inbox_item, "payload", {}))
    retry_feedback = _retry_feedback_text(group_context)
    content = (
        f"Local context capsule version: {capsule_version}\n"
        "Use this capsule as bounded durable context. It may be enriched by "
        "MemoryOS only after live MemoryOS proof exists.\n"
        f"Recent transcript:\n{transcript}\n"
        f"{retry_feedback}"
        f"{request_preview}"
    ).strip()
    return PromptLayer(
        name="local_context_capsule",
        content=content,
        metadata={"recent_message_count": len(recent_messages)},
    )


def _tool_writeback_layer(inbox_item: Any) -> PromptLayer:
    item_contract = contract_text(
        getattr(inbox_item, "expected_writeback_contract", None)
    )
    return PromptLayer(
        name="tool_and_writeback_contract",
        content=(
            f"{item_contract}\n\n"
            "You have unread xmuse chat inbox items in conversation "
            "xmuse_context.conversation_id. If xmuse MCP tools are available, "
            "call chat_post_message directly with "
            "reply_to_inbox_item_id=xmuse_context.inbox_item.id, using "
            "xmuse_context.inbox_item.payload.content as the request. "
            "If the inbox request explicitly asks for chat_emit_proposal, call "
            "chat_emit_proposal directly instead of chat_post_message; that "
            "tool is the durable writeback for proposal turns. "
            "chat_read_inbox is only for recovery or batch inspection; do not "
            "call it before simple replies.\n"
            "When the inbox request asks you to answer, report, review, critique, "
            "name a risk, or otherwise reply back to the sender, use "
            "chat_post_message with reply_to_inbox_item_id; do not use "
            "chat_mention back to the sender for simple answers.\n"
            "Natural-language @mentions inside chat_post_message are display-only "
            "and do not enqueue peer work. If you need another GOD to take over, "
            "inspect, or continue the task, call chat_mention with "
            "reply_to_inbox_item_id=xmuse_context.inbox_item.id, target_address "
            "set to the target GOD's exact @role, and content containing the "
            "concrete handoff request; this closes your current inbox item and "
            "enqueues the target GOD in one durable writeback.\n"
            "For work that should enter real execution, do not rely on chat text "
            "alone: create or reference a collaboration run, have execute record "
            "a JSON execute_feasibility_verdict through "
            "chat_record_collaboration_response using the approval-gate shape "
            "{\"type\":\"execute_feasibility_verdict\",\"status\":\"executable\","
            "\"summary\":\"<why dispatch is safe>\",\"evidence_refs\":[\"<ref>\"]}; "
            "looser fields such as verdict=feasible do not satisfy dispatch. "
            "If your current inbox item is a collaboration_request or asks you "
            "to use chat_record_collaboration_response, call that tool; do not "
            "return the JSON as final assistant text or streamed stdout. "
            "If you call chat_create_collaboration_request, do not also call "
            "chat_mention for the same target: the collaboration tool already "
            "creates the target inbox and callback. "
            "Then emit a lane_graph proposal with chat_emit_proposal, "
            "reply_to_inbox_item_id=xmuse_context.inbox_item.id, and a "
            "collaboration:<run_id> reference. Human approval is still required "
            "before dispatch.\n"
            "Only if MCP tools are unavailable, reply directly as your final "
            "assistant message based on xmuse_context.inbox_item.payload.content; "
            "xmuse may persist that final answer as a degraded GOD chat reply. "
            "If mcp_tools_ready has appeared, MCP tools are available; do not say "
            "you cannot perform durable writeback."
        ),
        metadata={"writeback_truth": "mcp_or_callback"},
    )


def _participant_roster_text(group_context: dict[str, Any]) -> str:
    participants = group_context.get("participants")
    if not isinstance(participants, list) or not participants:
        return "none"
    return ", ".join(
        f"@{participant.get('role')}={participant.get('display_name')}"
        for participant in participants
        if isinstance(participant, dict)
    )


def _turn_guidance_text(group_context: dict[str, Any]) -> str:
    guidance = group_context.get("turn_guidance")
    if not isinstance(guidance, list) or not guidance:
        return "none"
    return " ".join(str(item).strip() for item in guidance if str(item).strip())


def _recent_transcript_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")
        author = str(message.get("author") or "unknown")
        content = _bounded(str(message.get("content") or ""), max_chars=800)
        if content:
            lines.append(f"- {role}/{author}: {content}")
    return "\n".join(lines) if lines else "none"


def _inbox_request_preview(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return "Current inbox request: none"
    return "Current inbox request:\n" + _bounded(content.strip(), max_chars=8000)


def _retry_feedback_text(group_context: dict[str, Any]) -> str:
    feedback = group_context.get("retry_feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        return ""
    return "Retry feedback:\n" + _bounded(feedback.strip(), max_chars=1600) + "\n"


def _bounded(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
