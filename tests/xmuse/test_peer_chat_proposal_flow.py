from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.structuring.graph_store import LaneGraphStore


def test_emit_proposal_stores_lane_payload_for_approval(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Proposal")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(tmp_path / "chat.db")

    result = service.emit_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="proposal-1",
        summary="Add peer chat",
        lanes=[
            {
                "feature_id": "lane-peer-chat",
                "prompt": "Implement peer chat",
                "depends_on": [],
                "capabilities": ["code"],
                "feature_group": "peer-chat",
            }
        ],
        references=["msg_1"],
        resolution_content=None,
    )
    replay = service.emit_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="proposal-1",
        summary="Add peer chat",
        lanes=[
            {
                "feature_id": "lane-peer-chat",
                "prompt": "Implement peer chat",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=["msg_1"],
        resolution_content=None,
    )

    proposal_id = result["proposal"]["id"]
    assert replay["proposal"]["id"] == proposal_id
    assert result["message"]["envelope_json"]["proposal_id"] == proposal_id
    client = TestClient(create_app(tmp_path))
    approved = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Add peer chat",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["content"]["lanes"][0]["feature_id"] == "lane-peer-chat"


def test_blueprint_proposal_revision_approval_and_downstream_lane_ref(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Blueprint flow")
    other_conv = chat.create_conversation("Other mission")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(tmp_path / "chat.db")

    draft = service.emit_blueprint_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="blueprint-1",
        title="Chat-first mission",
        body="Make group chat the planning front door.",
        acceptance_criteria=["A mission blueprint card is visible in chat."],
    )
    revision = service.emit_blueprint_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="blueprint-2",
        title="Chat-first mission",
        body="Make group chat the planning front door before lane planning.",
        acceptance_criteria=[
            "A mission blueprint card is visible in chat.",
            "Approval creates a stable blueprint reference.",
        ],
        revises_blueprint_ref=draft["message"]["envelope_json"]["blueprint_ref"],
    )

    assert draft["message"]["envelope_type"] == "proposal"
    assert draft["message"]["envelope_json"]["type"] == "mission_blueprint"
    assert revision["message"]["envelope_json"]["revision_of"] == draft["message"][
        "envelope_json"
    ]["blueprint_ref"]
    assert all(message.conversation_id == conv.id for message in chat.list_messages(conv.id))
    assert chat.list_messages(other_conv.id) == []

    client = TestClient(create_app(tmp_path))
    approved = client.post(
        f"/api/chat/proposals/{revision['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve chat-first mission blueprint",
        },
    )

    assert approved.status_code == 200
    approved_payload = approved.json()
    blueprint_ref = approved_payload["content"]["blueprint_ref"]
    assert blueprint_ref == f"resolution:{approved_payload['id']}:mission_blueprint"
    assert approved_payload["content"]["revision_of"] == draft["message"]["envelope_json"][
        "blueprint_ref"
    ]

    lane_proposal = service.emit_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="lane-plan-1",
        summary="Plan blueprint-aware review",
        lanes=[
            {
                "feature_id": "lane-blueprint-review",
                "prompt": "Implement blueprint-aware review.",
                "depends_on": [],
                "capabilities": ["code"],
                "blueprint_refs": [blueprint_ref],
                "acceptance_criteria": ["Review prompt cites the approved blueprint."],
            }
        ],
        references=[blueprint_ref],
        resolution_content=None,
    )
    lane_approved = client.post(
        f"/api/chat/proposals/{lane_proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Plan blueprint-aware review",
        },
    )

    assert lane_approved.status_code == 200
    graph = LaneGraphStore(tmp_path / "lane_graphs").get(
        f"{lane_approved.json()['id']}-graph-v{lane_approved.json()['version']}"
    )
    assert graph.lanes[0].blueprint_refs == [blueprint_ref]


def test_blueprint_approval_ignores_explicit_lane_content_override(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Blueprint override")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    proposal = PeerChatService(
        tmp_path / "chat.db"
    ).emit_blueprint_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        client_request_id="blueprint-override",
        title="Chat-first mission",
        body="Make group chat the planning front door.",
        acceptance_criteria=["Approval creates a stable blueprint reference."],
    )

    client = TestClient(create_app(tmp_path))
    approved = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve chat-first mission blueprint",
            "content": {
                "lanes": [
                    {
                        "feature_id": "lane-should-not-project",
                        "prompt": "This is not the approved blueprint.",
                    }
                ]
            },
        },
    )

    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["content"]["type"] == "mission_blueprint"
    assert approved_payload["content"]["blueprint_ref"] == (
        f"resolution:{approved_payload['id']}:mission_blueprint"
    )
    assert approved_payload["content"]["title"] == "Chat-first mission"
    assert not (tmp_path / "feature_lanes.json").exists()
    assert not (tmp_path / "lane_graphs").exists()
