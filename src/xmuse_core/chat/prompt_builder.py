from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.participant_store import Participant

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
            "prompt_layer_hashes": {layer.name: _sha256(layer.content) for layer in self.layers},
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
            *_memoryos_sidecar_layers(group_context),
            _tool_writeback_layer(),
        )
        text = (
            "\n\n".join(f"## {layer.name}\n\n{layer.content.strip()}" for layer in layers).strip()
            + "\n"
        )
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
    participant_count = _participant_count(group_context)
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
            f"Provider/session bindings: {_session_binding_text(group_context)}\n"
            f"Turn guidance: {_turn_guidance_text(group_context)}"
        ),
        metadata={"participant_count": participant_count},
    )


def _context_capsule_layer(group_context: dict[str, Any], inbox_item: Any) -> PromptLayer:
    capsule = group_context.get("context_capsule")
    recent_messages = []
    if isinstance(capsule, dict):
        raw_messages = capsule.get("recent_messages")
        if isinstance(raw_messages, list):
            recent_messages = raw_messages[-8:]
    transcript = _recent_transcript_text(recent_messages)
    request_preview = _inbox_request_preview(getattr(inbox_item, "payload", {}))
    retry_feedback = _retry_feedback_text(group_context)
    content = (
        "Local context capsule version: xmuse-local-context-capsule-v1\n"
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


def _memoryos_sidecar_layers(group_context: dict[str, Any]) -> tuple[PromptLayer, ...]:
    memory_context = group_context.get("memoryos_context")
    if not isinstance(memory_context, dict):
        return ()
    status = str(memory_context.get("status") or "unknown").strip() or "unknown"
    namespace_uri = str(memory_context.get("namespace_uri") or "unknown").strip()
    proof_level = str(memory_context.get("proof_level") or "unknown").strip()
    authority = str(memory_context.get("authority") or "memoryos_sidecar").strip()
    lines = [
        f"MemoryOS sidecar status: {status}",
        f"Authority: {authority}",
        f"Proof level: {proof_level}",
        f"Namespace: {namespace_uri}",
        "MemoryOS is sidecar context, not proposal/review/dispatch truth.",
    ]
    degraded_reason = memory_context.get("degraded_reason")
    if isinstance(degraded_reason, str) and degraded_reason.strip():
        lines.append(f"Degraded reason: {degraded_reason.strip()}")
        lines.append("No MemoryOS recall is available; continue from chat.db authority.")
    text = memory_context.get("text")
    if isinstance(text, str) and text.strip():
        lines.extend(["", "Recall:", _bounded(text.strip(), max_chars=2400)])
    source_refs = _memoryos_source_refs(memory_context)
    if source_refs:
        lines.extend(["", "Source refs:"])
        lines.extend(f"- {ref}" for ref in source_refs)
    return (
        PromptLayer(
            name="memoryos_sidecar_context",
            content="\n".join(lines),
            metadata={
                "authority": authority,
                "status": status,
                "proof_level": proof_level,
                "namespace_uri": namespace_uri,
                "source_refs": source_refs,
            },
        ),
    )


def _memoryos_source_refs(memory_context: dict[str, Any]) -> list[str]:
    value = memory_context.get("source_refs")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(ref) for ref in value if isinstance(ref, str) and ref.strip()]


def _tool_writeback_layer() -> PromptLayer:
    return PromptLayer(
        name="tool_and_writeback_contract",
        content=(
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
            "set to the target GOD's exact "
            "xmuse_context.group_chat.participant_profiles[].mention_handle, "
            "and content containing the "
            "concrete handoff request; this closes your current inbox item and "
            "enqueues the target GOD in one durable writeback.\n"
            "For work that should enter real execution, do not rely on chat text "
            "alone: create or reference a collaboration run, have execute record "
            "a JSON execute_feasibility_verdict through "
            "chat_record_collaboration_response using the approval-gate shape "
            '{"type":"execute_feasibility_verdict","status":"executable",'
            '"execution_performed":false,"summary":"<why dispatch is safe>",'
            '"evidence_refs":["<ref>"]}; '
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
            "before dispatch. Every dispatchable lane_graph lane must include "
            'explicit gate_profiles, for example ["xmuse-core"] for xmuse '
            "core code paths; if you cannot choose a gate profile, write a "
            "durable blocker or open question instead of proposing dispatchable "
            "work.\n"
            "Only if MCP tools are unavailable, reply directly as your final "
            "assistant message based on xmuse_context.inbox_item.payload.content; "
            "xmuse may persist that final answer as a degraded GOD chat reply. "
            "If mcp_tools_ready has appeared, MCP tools are available; do not say "
            "you cannot perform durable writeback."
        ),
        metadata={"writeback_truth": "mcp_or_callback"},
    )


def _participant_roster_text(group_context: dict[str, Any]) -> str:
    profiles = group_context.get("participant_profiles")
    if isinstance(profiles, list) and profiles:
        rows = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            handle = str(profile.get("mention_handle") or "").strip()
            role = str(profile.get("role") or "").strip()
            name = str(profile.get("display_name") or "").strip()
            capabilities = profile.get("capabilities")
            caps = (
                ",".join(str(capability) for capability in capabilities)
                if isinstance(capabilities, list)
                else ""
            )
            session_ref = profile.get("provider_session_binding_ref")
            binding = f" session={session_ref}" if isinstance(session_ref, str) else ""
            if handle:
                suffix = f" capabilities={caps}" if caps else ""
                rows.append(f"{handle}={name or role}{suffix}{binding}")
        if rows:
            return ", ".join(rows)
    participants = group_context.get("participants")
    if not isinstance(participants, list) or not participants:
        return "none"
    return ", ".join(
        f"@{participant.get('role')}={participant.get('display_name')}"
        for participant in participants
        if isinstance(participant, dict)
    )


def _session_binding_text(group_context: dict[str, Any]) -> str:
    bindings = group_context.get("session_bindings")
    if not isinstance(bindings, list) or not bindings:
        return "none"
    rows = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        participant_id = str(binding.get("participant_id") or "unknown")
        status = str(binding.get("session_status") or "unknown")
        provider_status = str(binding.get("provider_binding_status") or "unbound")
        provider_session_id = binding.get("provider_session_id")
        session = (
            f" provider_session={provider_session_id}"
            if isinstance(provider_session_id, str) and provider_session_id.strip()
            else ""
        )
        rows.append(
            f"{participant_id}: session_status={status} "
            f"provider_binding_status={provider_status}{session}"
        )
    return "; ".join(rows) if rows else "none"


def _participant_count(group_context: dict[str, Any]) -> int:
    profiles = group_context.get("participant_profiles")
    if isinstance(profiles, list) and profiles:
        return len([profile for profile in profiles if isinstance(profile, dict)])
    participants = group_context.get("participants")
    if isinstance(participants, list):
        return len([participant for participant in participants if isinstance(participant, dict)])
    return 0


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
    callback_action = _collaboration_callback_action(payload)
    if not isinstance(content, str) or not content.strip():
        return "Current inbox request: none" + callback_action
    return "Current inbox request:\n" + _bounded(content.strip(), max_chars=8000) + callback_action


def _collaboration_callback_action(payload: dict[str, object]) -> str:
    if payload.get("trigger_mode") != "collaboration_done_callback":
        return ""
    run_id = payload.get("collaboration_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return ""
    run_ref = f"collaboration:{run_id.strip()}"
    return (
        "\n\nCollaboration callback action:\n"
        "- call chat_emit_proposal before ending this turn.\n"
        f'- include references=["{run_ref}"].\n'
        "- use reply_to_inbox_item_id=xmuse_context.inbox_item.id.\n"
        "- plain final text or no tool call is a failed callback."
    )


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
