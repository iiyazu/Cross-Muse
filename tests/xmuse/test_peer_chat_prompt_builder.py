from __future__ import annotations

from pathlib import Path

from xmuse_core.chat.context_assembler import ContextAssembler
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.prompt_builder import (
    PROMPT_CONTRACT_VERSION,
    XmusePromptBuilder,
)
from xmuse_core.chat.store import ChatStore


def test_peer_chat_prompt_builder_emits_ordered_auditable_layers(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Layered prompt")
    participants = ParticipantStore(tmp_path / "chat.db")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="OpenCode Review GOD",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    user_msg = chat.add_message(conv.id, "human", "human", "@architect plan this")
    item = ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=user_msg.id,
        item_type="mention",
        payload={"content": "@architect plan this"},
    )

    group_context = ContextAssembler(
        participants=participants,
        chat=chat,
    ).group_chat_context(conv.id)
    assembled = XmusePromptBuilder().build_peer_chat_prompt(
        participant=architect,
        inbox_item=item,
        group_context=group_context,
    )
    artifact = assembled.as_context_artifact()

    assert assembled.version == PROMPT_CONTRACT_VERSION
    assert artifact["layer_order"] == [
        "xmuse_governance_l0",
        "member_identity",
        "roster_and_capabilities",
        "local_context_capsule",
        "tool_and_writeback_contract",
    ]
    assert artifact["fingerprint"].startswith("sha256:")
    assert artifact["layers"][0]["sha256"].startswith("sha256:")
    assert "Durable chat state is reply truth" in assembled.text
    assert "Role: architect" in assembled.text
    assert "@review=OpenCode Review GOD" in assembled.text
    assert "Local context capsule version: xmuse-local-context-capsule-v1" in assembled.text
    assert "chat_emit_proposal" in assembled.text
    assert "If the inbox request explicitly asks for chat_emit_proposal" in assembled.text
    assert "that tool is the durable writeback for proposal turns" in assembled.text
    assert "do not return the JSON as final assistant text or streamed stdout" in (
        assembled.text
    )
    assert "do not also call chat_mention for the same target" in assembled.text
    assert "If mcp_tools_ready has appeared, MCP tools are available" in assembled.text


def test_context_assembler_turn_context_carries_prompt_artifact(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Turn context")
    participants = ParticipantStore(tmp_path / "chat.db")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    msg = chat.add_message(conv.id, "human", "human", "@architect")
    item = ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=msg.id,
        item_type="mention",
        payload={"content": "@architect"},
    )
    assembler = ContextAssembler(participants=participants, chat=chat)
    group_context = assembler.group_chat_context(conv.id)
    assembled = XmusePromptBuilder().build_peer_chat_prompt(
        participant=architect,
        inbox_item=item,
        group_context=group_context,
    )

    context = assembler.turn_context(
        conversation_id=conv.id,
        participant_id=architect.participant_id,
        god_session_id="god-live",
        inbox_item=item,
        group_chat=group_context,
        prompt_artifact=assembled.as_context_artifact(),
    )

    assert context["context_capsule"]["version"] == "xmuse-local-context-capsule-v1"
    assert context["xmuse_prompt"]["version"] == PROMPT_CONTRACT_VERSION
    assert context["xmuse_prompt"]["text"] == assembled.text


def test_prompt_builder_includes_retry_feedback(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Prompt retry")
    participants = ParticipantStore(tmp_path / "chat.db")
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    msg = chat.add_message(conv.id, "architect", "assistant", "@execute")
    item = ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conv.id,
        target_participant_id=execute.participant_id,
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@architect",
        source_message_id=msg.id,
        item_type="collaboration_request",
        payload={"content": "Use chat_record_collaboration_response."},
    )
    group_context = ContextAssembler(
        participants=participants,
        chat=chat,
    ).group_chat_context(conv.id)
    group_context["retry_feedback"] = (
        "Previous attempt failed with peer_no_inbox_side_effect; call "
        "chat_record_collaboration_response."
    )

    assembled = XmusePromptBuilder().build_peer_chat_prompt(
        participant=execute,
        inbox_item=item,
        group_context=group_context,
    )

    assert "Retry feedback:" in assembled.text
    assert "Previous attempt failed with peer_no_inbox_side_effect" in assembled.text
