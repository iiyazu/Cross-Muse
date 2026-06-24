from __future__ import annotations

from pathlib import Path

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.context_assembler import ContextAssembler
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
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
    assert "Local context capsule version: xmuse-groupchat-context-v2" in assembled.text
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

    assert context["context_capsule"]["version"] == "xmuse-groupchat-context-v2"
    assert context["xmuse_prompt"]["version"] == PROMPT_CONTRACT_VERSION
    assert context["xmuse_prompt"]["text"] == assembled.text


def test_context_assembler_projects_groupchat_context_v2_authority(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Context v2")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    human = chat.add_message(
        conv.id,
        "human",
        "human",
        "Please produce the smallest audited change.",
        envelope_json={"type": "message", "intake_kind": "goal_intake"},
    )
    spine = AcceptanceSpineStore(db).create_for_intake(
        conversation_id=conv.id,
        intake_message_id=human.id,
    )
    inbox = ChatInboxStore(db)
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=human.id,
        item_type="default_intake",
        payload={
            "content": "Please produce the smallest audited change.",
            "intake_kind": "goal_intake",
        },
    )
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"small audited change","lanes":[]}',
        references=[f"intake_message:{human.id}"],
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id="res-context-v2",
        collaboration_run_id=None,
        artifact_ref=f"proposal:{proposal.id}",
    )
    collaboration = ChatCollaborationStore(db)
    run = collaboration.create_request(
        conversation_id=conv.id,
        goal="Collect review and execute feasibility.",
        initiator="architect",
        targets=["execute", "review"],
        callback_target="architect",
        question="Can this proposal execute safely?",
        context_refs=[f"proposal:{proposal.id}"],
        idempotency_key="context-v2-collaboration",
        timeout_s=480,
    )
    collaboration.record_response(
        run.run_id,
        target="execute",
        content='{"type":"execute_feasibility_verdict","status":"executable"}',
        response_status="received",
    )
    blocker = collaboration.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Review needs a narrower diff before dispatch.",
        affected_ref=f"proposal:{proposal.id}",
        suggested_fix="Reduce the proposal scope.",
        blocks_dispatch=True,
    )

    context = ContextAssembler(
        participants=participants,
        chat=chat,
        inbox=inbox,
        acceptance_spines=AcceptanceSpineStore(db),
        dispatch_queue=ChatDispatchQueueStore(db),
        collaboration_store=collaboration,
    ).group_chat_context(conv.id)

    capsule = context["context_capsule"]
    assert capsule["version"] == "xmuse-groupchat-context-v2"
    assert capsule["source_authority"] == "chat_store"
    assert f"chat.db#messages:{human.id}" in capsule["source_refs"]
    assert capsule["human_intake"]["latest"] == {
        "message_id": human.id,
        "intake_kind": "goal_intake",
        "source_refs": [f"chat.db#messages:{human.id}"],
    }
    assert capsule["inbox_summary"]["counts_by_type"]["default_intake"] == 1
    assert capsule["inbox_summary"]["pending"][0]["id"] == item.id
    assert capsule["proposal_summary"]["count"] == 1
    assert capsule["proposal_summary"]["latest"]["proposal_id"] == proposal.id
    assert capsule["acceptance_spines"][0]["spine_id"] == spine.spine_id
    assert capsule["acceptance_spines"][0]["proposal_id"] == proposal.id
    assert capsule["acceptance_spines"][0]["dispatch_item_id"] == dispatch.entry_id
    assert capsule["dispatch_queue"]["counts_by_status"]["queued"] == 1
    assert capsule["dispatch_queue"]["entries"][0]["entry_id"] == dispatch.entry_id
    assert capsule["collaboration_summary"]["counts_by_status"]["partial"] == 1
    assert capsule["collaboration_summary"]["runs"][0]["run_id"] == run.run_id
    assert capsule["collaboration_summary"]["runs"][0]["completed_targets"] == ["execute"]
    assert capsule["collaboration_summary"]["runs"][0]["pending_targets"] == ["review"]
    assert capsule["collaboration_summary"]["pending_handoffs"][0]["run_id"] == run.run_id
    assert capsule["collaboration_summary"]["open_blockers"][0]["blocker_id"] == (
        blocker.blocker_id
    )
    assert capsule["collaboration_summary"]["open_blockers"][0]["blocks_dispatch"] is True
    assert f"chat.db#collaboration_runs:{run.run_id}" in capsule["source_refs"]
    assert f"chat.db#collaboration_blockers:{blocker.blocker_id}" in capsule["source_refs"]
    assert capsule["review_summary"]["source_authority"] == "acceptance_spines"


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
