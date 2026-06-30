from __future__ import annotations

from pathlib import Path

from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.context_assembler import ContextAssembler
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.groupchat_worklist import (
    GroupchatWorklistScheduler,
    GroupchatWorklistStore,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.mentions import MentionResolver
from xmuse_core.chat.natural_routing import (
    build_natural_route_event,
    natural_route_payload,
)
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


def test_group_chat_context_projects_provider_session_bindings(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Natural context")
    participants = ParticipantStore(db_path)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    session_address, session_inbox_id = build_conversation_session_identity(
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
    )
    registry = GodSessionRegistry(registry_path)
    session = registry.create(
        role=architect.role,
        agent_name=architect.display_name,
        runtime=architect.cli_kind,
        session_address=session_address,
        session_inbox_id=session_inbox_id,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        model=architect.model,
        prompt_fingerprint="sha256:test",
        worktree=str(tmp_path),
    )
    registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )

    context = ContextAssembler(
        participants=participants,
        chat=chat,
        session_registry_path=registry_path,
    ).group_chat_context(conversation.id)

    assert context["context_layers"] == [
        "xmuse_l0_governance",
        "member_identity",
        "provider_session_binding_summary",
        "roster",
        "recent_transcript",
        "structured_state_refs",
    ]
    assert context["source_refs"] == [
        f"chat.db:conversation:{conversation.id}",
        "god_sessions:god_sessions.json",
    ]
    assert context["session_bindings"][0]["participant_id"] == architect.participant_id
    assert context["session_bindings"][0]["session_address"] == session_address
    assert context["session_bindings"][0]["session_inbox_id"] == session_inbox_id
    assert context["session_bindings"][0]["provider_session_id"] == "codex-thread-1"
    assert context["session_bindings"][0]["provider_binding_status"] == "active"
    profile = context["participant_profiles"][0]
    assert profile["god_id"] == f"god:{conversation.id}:{architect.participant_id}"
    assert profile["mention_handle"] == "@architect"
    assert profile["provider_session_binding_ref"] == (f"god_session:{session.god_session_id}")
    assert profile["identity_authority_refs"] == [
        f"chat.db:participant:{architect.participant_id}",
        f"chat.db:conversation:{conversation.id}",
    ]


def test_group_chat_context_marks_missing_session_binding_without_failing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Missing binding")
    participants = ParticipantStore(db_path)
    review = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    context = ContextAssembler(
        participants=participants,
        chat=chat,
        session_registry_path=tmp_path / "god_sessions.json",
    ).group_chat_context(conversation.id)

    assert context["session_bindings"][0]["participant_id"] == review.participant_id
    assert context["session_bindings"][0]["session_status"] == "unbound"
    assert context["session_bindings"][0]["has_provider_session"] is False
    assert context["participant_profiles"][0]["provider_session_binding_ref"] is None
    assert context["participant_profiles"][0]["mention_handle"] == "@review"


def test_group_chat_profile_handles_ambiguous_role_aliases(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Ambiguous aliases")
    participants = ParticipantStore(db_path)
    first = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Primary Architect",
        cli_kind="codex",
        model="gpt-5.4",
    )
    second = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Backup Architect",
        cli_kind="codex",
        model="gpt-5.4",
    )

    context = ContextAssembler(
        participants=participants,
        chat=chat,
    ).group_chat_context(conversation.id)

    profiles = {profile["participant_id"]: profile for profile in context["participant_profiles"]}
    assert profiles[first.participant_id]["mention_handle"] == (
        f"@participant:{first.participant_id}"
    )
    assert profiles[second.participant_id]["mention_handle"] == (
        f"@participant:{second.participant_id}"
    )
    assert "@architect" not in profiles[first.participant_id]["aliases"]
    assert "@architect" not in profiles[second.participant_id]["aliases"]
    resolver = MentionResolver(participants)
    for participant in (first, second):
        handle = profiles[participant.participant_id]["mention_handle"]
        assert (
            resolver.resolve(
                conversation.id,
                handle,
            ).participant.participant_id
            == participant.participant_id
        )


def test_group_chat_context_bounds_recent_transcript_without_mutating_authority(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Bounded context")
    long_content = "HEAD-" + ("x" * 80) + "-TAIL"
    message = chat.add_message(
        conversation.id,
        author="human",
        role="user",
        content=long_content,
    )

    context = ContextAssembler(
        participants=ParticipantStore(db_path),
        chat=chat,
        max_message_chars=50,
    ).group_chat_context(conversation.id)

    recent = context["recent_messages"][0]
    assert context["context_budget"] == {
        "recent_limit": 8,
        "max_message_chars": 50,
        "message_count": 1,
        "truncated_messages": 1,
    }
    assert recent["id"] == message.id
    assert recent["truncated"] is True
    assert recent["original_chars"] == len(long_content)
    assert len(recent["content"]) == 50
    assert recent["content"].startswith("HEAD")
    assert recent["content"].endswith("TAIL")
    assert "truncated" in recent["content"]
    assert chat.list_messages(conversation.id)[0].content == long_content


def test_group_chat_context_projects_compact_message_envelope_artifacts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("A2A artifact context")
    message = chat.add_message(
        conversation.id,
        author="remote-a2a-architect",
        role="assistant",
        content="Remote A2A result.",
        envelope_type="a2a_provider_result",
        envelope_json={
            "type": "a2a_provider_result",
            "provider_profile_ref": "a2a.remote",
            "provider_request_id": "inbox-a2a",
            "provider_status": "completed",
            "source_refs": ["a2a_task:inbox-a2a", "a2a_state:TASK_STATE_COMPLETED"],
            "authority": "chat.db/inbox",
            "a2a_is_authority": False,
            "diagnostic_payload": {
                "a2a_artifacts": [
                    {
                        "artifact_id": "artifact-lane-candidate",
                        "name": "lane candidate",
                        "parts": [{"text": "Use this as proposal evidence, not approval."}],
                    }
                ]
            },
        },
    )

    context = ContextAssembler(
        participants=ParticipantStore(db_path),
        chat=chat,
    ).group_chat_context(conversation.id)

    recent = context["recent_messages"][0]
    assert recent["id"] == message.id
    assert recent["envelope"] == {
        "type": "a2a_provider_result",
        "provider_profile_ref": "a2a.remote",
        "provider_request_id": "inbox-a2a",
        "provider_status": "completed",
        "authority": "chat.db/inbox",
        "a2a_is_authority": False,
        "source_refs": ["a2a_task:inbox-a2a", "a2a_state:TASK_STATE_COMPLETED"],
        "artifacts": [
            {
                "artifact_id": "artifact-lane-candidate",
                "name": "lane candidate",
                "text": "Use this as proposal evidence, not approval.",
            }
        ],
        "artifact_count": 1,
    }
    assert context["context_capsule"]["recent_messages"][0]["envelope"] == (recent["envelope"])


def test_group_chat_context_projects_writeback_authority_envelope_refs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Writeback authority context")
    dispatch = chat.add_message(
        conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-1",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-1",
            "proposal_id": "proposal-1",
            "resolution_id": "resolution-1",
            "collaboration_run_id": "collab-1",
            "artifact_ref": "artifact:lane_graph",
            "dispatch_evidence_ref": "mcp_writeback:inbox-1",
            "source_refs": [
                "chat_dispatch_queue:dispatch-1",
                "proposal:proposal-1",
                "review_trigger_verdict:review-1",
                "resolution:resolution-1",
            ],
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
        },
    )
    final_action = chat.add_message(
        conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-1 is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "authority": "chat.db/messages/final_action_result",
            "final_action_id": "final-1",
            "final_action_ref": "final_actions.json#hold=final-1",
            "lane_id": "lane-1",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence.json#evidence=ghgate-1",
            "github_gate_gap_ref": None,
            "acceptance_spine_ref": "chat.db#acceptance_spine=spine-1",
            "source_refs": [
                "final_actions.json#hold=final-1",
                "chat.db#acceptance_spine=spine-1",
                "github_gate_evidence.json#evidence=ghgate-1",
            ],
            "proof_boundary": "final_action_writeback_not_github_or_merge_truth",
            "github_gate": {
                "status": "accepted",
                "proof_level": "server_side_merge_proof",
                "repo": "iiyazu/Cross-Muse",
                "pull_request_number": 42,
                "head_sha": "head123",
                "workflow_run_id": 111,
                "check_suite_id": 222,
                "required_checks": ["quality-gates"],
                "check_runs": [
                    {"id": 111, "name": "quality-gates", "head_sha": "head123"}
                ],
                "merge": {
                    "merge_commit_sha": "merge123",
                    "merged_at": "2026-06-10T15:00:00Z",
                    "merge_event_id": "merge-event-1",
                },
                "main_ci": {
                    "workflow_run_id": 333,
                    "workflow_name": "xmuse CI",
                    "head_sha": "merge123",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://github.com/iiyazu/Cross-Muse/actions/runs/333",
                },
            },
        },
    )

    context = ContextAssembler(
        participants=ParticipantStore(db_path),
        chat=chat,
    ).group_chat_context(conversation.id)

    by_id = {message["id"]: message["envelope"] for message in context["recent_messages"]}
    assert by_id[dispatch.id] == {
        "type": "dispatch_result",
        "authority": "chat.db/messages/dispatch_result",
        "dispatch_queue_entry_id": "dispatch-1",
        "proposal_id": "proposal-1",
        "resolution_id": "resolution-1",
        "collaboration_run_id": "collab-1",
        "artifact_ref": "artifact:lane_graph",
        "dispatch_evidence_ref": "mcp_writeback:inbox-1",
        "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
        "source_refs": [
            "chat_dispatch_queue:dispatch-1",
            "proposal:proposal-1",
            "review_trigger_verdict:review-1",
            "resolution:resolution-1",
        ],
    }
    assert by_id[final_action.id]["final_action_ref"] == "final_actions.json#hold=final-1"
    assert by_id[final_action.id]["status"] == "accepted"
    assert by_id[final_action.id]["github_gate_evidence_ref"] == (
        "github_gate_evidence.json#evidence=ghgate-1"
    )
    assert by_id[final_action.id]["proof_boundary"] == (
        "final_action_writeback_not_github_or_merge_truth"
    )
    assert by_id[final_action.id]["github_gate"] == {
        "status": "accepted",
        "proof_level": "server_side_merge_proof",
        "repo": "iiyazu/Cross-Muse",
        "pull_request_number": 42,
        "head_sha": "head123",
        "workflow_run_id": 111,
        "check_suite_id": 222,
        "check_runs": [{"id": 111, "name": "quality-gates", "head_sha": "head123"}],
        "main_ci": {
            "workflow_run_id": 333,
            "workflow_name": "xmuse CI",
            "head_sha": "merge123",
            "status": "completed",
            "conclusion": "success",
        },
    }
    assert context["context_capsule"]["recent_messages"][-1]["envelope"] == (
        by_id[final_action.id]
    )


def test_group_chat_context_projects_terminal_groupchat_worklist_boundary(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Terminal worklist context")
    participants = ParticipantStore(db_path)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    root = chat.add_message(
        conversation.id,
        author="human",
        role="user",
        content="Run the next approved dispatch.",
    )
    store = GroupchatWorklistStore(db_path)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proposal_id": "proposal-a",
            "resolution_id": "resolution-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": [
                "chat_dispatch_queue:dispatch-a",
                "proposal:proposal-a",
                "resolution:resolution-a",
            ],
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db_path, scheduler_id="groupchat-a1")
    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)
    assert len(routed) == 1

    context = ContextAssembler(
        participants=participants,
        chat=chat,
        db_path=db_path,
    ).group_chat_context(conversation.id)

    worklist = context["structured_state"]["groupchat_worklist"]
    assert worklist["source_authority"] == [
        "chat.db:groupchat_chains",
        "chat.db:groupchat_worklist",
        "chat.db:messages",
    ]
    assert worklist["items"] == [
        {
            "item_id": routed[0].item_id,
            "chain_id": chain.chain_id,
            "status": "blocked",
            "target_role": architect.role,
            "target_participant_id": architect.participant_id,
            "route_kind": "handoff",
            "depth": 1,
            "terminal_reason": "dispatch_acknowledgement_not_execution_proof",
            "source_message_id": dispatch_ack.id,
            "source_refs": [
                f"chat:message:{dispatch_ack.id}",
                "chat_dispatch_queue:dispatch-a",
                "proposal:proposal-a",
                "resolution:resolution-a",
            ],
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "next_authority_boundary": "execution_evidence_or_final_action_writeback",
            "authority_boundary": {
                "producer": "chat.db:groupchat_worklist",
                "consumer": "group_chat_context",
                "condition": "read_only_structured_state",
                "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            },
        }
    ]


def test_group_chat_context_projects_structured_state_from_chat_authorities(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Structured state")
    participants = ParticipantStore(db_path)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    demand = chat.add_message(
        conversation.id,
        author="human",
        role="user",
        content="@architect create a bounded plan.",
        mentions=["@architect"],
    )
    AcceptanceSpineStore(db_path).create_for_intake(
        conversation_id=conversation.id,
        intake_message_id=demand.id,
    )
    inbox = ChatInboxStore(db_path)
    mention_route = build_natural_route_event(
        conversation_id=conversation.id,
        origin_message_id=demand.id,
        source_kind="human_line_start_mention",
        author_participant_id=None,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        source_refs=[f"message:{demand.id}"],
    )
    inbox.create_item(
        conversation_id=conversation.id,
        target_participant_id=architect.participant_id,
        target_role=architect.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="human",
        source_message_id=demand.id,
        item_type="mention",
        payload=natural_route_payload(
            mention_route,
            content=demand.content,
            mention="@architect",
        ),
    )
    blocker_route = build_natural_route_event(
        conversation_id=conversation.id,
        origin_message_id=demand.id,
        source_kind="review_gate",
        author_participant_id=None,
        target_participant_id=architect.participant_id,
        route_kind="review_blocker",
        source_refs=[f"message:{demand.id}", "review:required"],
        depth=2,
        blocker_reason="review_required",
    )
    inbox.create_item(
        conversation_id=conversation.id,
        target_participant_id=architect.participant_id,
        target_role=architect.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@review",
        source_message_id=demand.id,
        item_type="review_blocker",
        payload=natural_route_payload(
            blocker_route,
            content="Review is required before dispatch.",
            extra={"blocks_dispatch": True},
        ),
    )
    proposal = chat.create_proposal(
        conversation_id=conversation.id,
        author=architect.participant_id,
        proposal_type="lane_graph",
        content='{"type":"lane_graph","lanes":[]}',
        references=[f"message:{demand.id}"],
    )
    collaboration = ChatCollaborationStore(db_path).create_request(
        conversation_id=conversation.id,
        goal="Check execution feasibility",
        initiator="@architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Can this lane run as a read-only inspection?",
        context_refs=[f"message:{demand.id}"],
        idempotency_key=None,
        timeout_s=300,
    )
    ChatCollaborationStore(db_path).record_response(
        collaboration.run_id,
        target="@execute",
        content=(
            '{"type":"execute_feasibility_verdict","status":"executable",'
            '"execution_performed":false,"summary":"Dispatchable as read-only."}'
        ),
        response_status="received",
    )
    resolution = chat.approve_proposal(
        proposal_id=proposal.id,
        approved_by=["architect"],
        approval_mode="structured-state-proof",
        goal_summary="Approve structured state proof.",
        content={"type": "lane_graph", "lanes": []},
    )
    dispatch = ChatDispatchQueueStore(db_path).enqueue_agent_auto_dispatch(
        conversation_id=conversation.id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id=collaboration.run_id,
        artifact_ref=f"resolution:{resolution.id}",
        gate_refs=[f"collaboration:{collaboration.run_id}"],
    )

    context = ContextAssembler(
        participants=participants,
        chat=chat,
        db_path=db_path,
    ).group_chat_context(conversation.id)

    assert f"chat.db:structured_state:{conversation.id}" in context["source_refs"]
    state = context["structured_state"]
    assert state["source"] == "chat.db"
    assert state["counts"]["open_inbox"] == 2
    assert state["counts"]["blockers"] == 1
    assert state["counts"]["accepted_proposals"] == 1
    assert state["counts"]["approved_resolutions"] == 1
    assert state["counts"]["collaborations"] == 1
    assert state["counts"]["collaboration_responses"] == 1
    assert state["counts"]["dispatch_entries"] == 1
    assert state["counts"]["acceptance_spines"] == 1
    assert state["open_inbox"][0]["route_key"] == mention_route.route_key
    assert state["open_inbox"][0]["route_depth"] == 1
    assert state["open_inbox"][0]["source_kind"] == "human_line_start_mention"
    assert state["open_inbox"][0]["source_refs"] == [f"message:{demand.id}"]
    assert state["open_inbox"][0]["natural_route"] == {
        "route_id": mention_route.route_id,
        "route_key": mention_route.route_key,
        "source_kind": "human_line_start_mention",
        "route_kind": "mention",
        "origin_message_id": demand.id,
        "target_participant_id": architect.participant_id,
        "status": "pending",
        "depth": 1,
        "source_refs": [f"message:{demand.id}"],
    }
    assert state["blockers"][0]["blocks_dispatch"] is True
    assert state["blockers"][0]["route_key"] == blocker_route.route_key
    assert state["blockers"][0]["route_depth"] == 2
    assert state["blockers"][0]["source_kind"] == "review_gate"
    assert state["blockers"][0]["source_refs"] == [
        f"message:{demand.id}",
        "review:required",
    ]
    assert state["blockers"][0]["natural_route"]["status"] == "blocked"
    assert state["blockers"][0]["natural_route"]["blocker_reason"] == ("review_required")
    assert state["blockers"][0]["natural_route_status"] == "blocked"
    assert state["proposals"][0]["id"] == proposal.id
    assert state["resolutions"][0]["id"] == resolution.id
    assert state["collaborations"][0]["run_id"] == collaboration.run_id
    assert state["collaborations"][0]["responses"][0]["target"] == "@execute"
    assert state["dispatch_queue"][0]["entry_id"] == dispatch.entry_id
    assert state["dispatch_queue"][0]["gate_refs"] == [f"collaboration:{collaboration.run_id}"]
    assert state["acceptance_spines"][0]["proposal_id"] == proposal.id
    assert state["acceptance_spines"][0]["review_or_execute_verdict_ref"] == (
        f"resolution:{resolution.id}"
    )
