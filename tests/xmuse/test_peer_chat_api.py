import json
import sqlite3

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


def _assert_participant_sessions(
    *,
    participants: list[dict[str, object]],
    participant_sessions: list[dict[str, object]],
    conversation_id: str,
    tmp_path,
) -> None:
    participants_by_role = {str(item["role"]): item for item in participants}
    sessions_by_role = {str(item["role"]): item for item in participant_sessions}

    assert sessions_by_role.keys() == participants_by_role.keys()

    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    for role, participant in participants_by_role.items():
        session = sessions_by_role[role]
        assert session["conversation_id"] == conversation_id
        assert session["participant_id"] == participant["participant_id"]
        record = registry.get(str(session["god_session_id"]))
        assert record.participant_id == participant["participant_id"]


def test_create_conversation_response_includes_participant_sessions(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post("/api/chat/conversations", json={"title": "Chat"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["bootstrap"]["participant_sessions"] == payload["participant_sessions"]
    _assert_participant_sessions(
        participants=payload["participants"],
        participant_sessions=payload["participant_sessions"],
        conversation_id=payload["id"],
        tmp_path=tmp_path,
    )


def test_bootstrap_apply_response_includes_participant_sessions(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "Bootstrap apply", "init_mode": "proposal_then_approve"},
    )

    assert created.status_code == 201
    conversation = created.json()
    assert conversation["participant_sessions"] == []
    proposal_id = conversation["bootstrap"]["proposal_id"]

    response = client.post(
        f"/api/chat/conversations/{conversation['id']}/bootstrap/apply",
        json={"proposal_id": proposal_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bootstrap"]["participant_sessions"] == payload["participant_sessions"]
    _assert_participant_sessions(
        participants=payload["participants"],
        participant_sessions=payload["participant_sessions"],
        conversation_id=payload["conversation_id"],
        tmp_path=tmp_path,
    )


def test_rest_message_mention_creates_inbox(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "@architect please discuss",
            "client_request_id": "rest-1",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == ["@architect"]
    assert len(payload["inbox_items"]) == 1

    inbox = ChatInboxStore(tmp_path / "chat.db")
    assert inbox.get(payload["inbox_items"][0]["id"]).status == "unread"


def test_rest_message_line_start_instructional_mention_uses_default_intake(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": (
                "请 Architect GOD 判断下一步。如果需要 review，请在新行开头精确 "
                "@review 并说明 what/why/tradeoffs/open_questions。"
            ),
            "client_request_id": "rest-line-start-example-mention",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == []
    assert len(payload["inbox_items"]) == 1
    assert payload["inbox_items"][0]["target_role"] == "architect"
    assert payload["inbox_items"][0]["item_type"] == "default_intake"


def test_chat_timeline_projects_peer_progress_from_durable_inbox_and_trace(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Peer progress"}).json()
    message = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "@architect please handle this",
            "client_request_id": "rest-peer-progress",
        },
    ).json()
    item_id = message["inbox_items"][0]["id"]
    inbox = ChatInboxStore(tmp_path / "chat.db")
    claimed = inbox.claim_next(owner="sched-test", item_id=item_id)

    running = client.get(f"/api/chat/conversations/{conv['id']}/messages").json()
    running_event = running["peer_progress_events"][0]
    assert running_event["source_authority"] == "chat_inbox_items"
    assert running_event["source_id"] == item_id
    assert running_event["status"] == "running"
    assert running_event["target_role"] == "architect"

    failed = inbox.mark_failed(item_id, reason="peer_no_inbox_writeback_message")
    PeerTurnLatencyTraceStore(tmp_path / "chat.db").record(
        conversation_id=conv["id"],
        inbox_item_id=item_id,
        participant_id=failed.target_participant_id,
        target_role=failed.target_role,
        message_created_at=failed.created_at,
        inbox_claimed_at=claimed.claimed_at,
        delivery_started_at=10.0,
        provider_turn_started_at=10.1,
        first_delta_at=10.2,
        writeback_at=11.5,
        total_latency_ms=1500,
        delivery_mode="failed",
        degraded_reason="peer_no_inbox_writeback_message",
        stage_timings={"chat_read_inbox": {"at": 10.2}},
    )

    timeline = client.get(f"/api/chat/conversations/{conv['id']}/messages")

    assert timeline.status_code == 200
    payload = timeline.json()
    progress_events = payload["peer_progress_events"]
    assert len(progress_events) == 1
    event = progress_events[0]
    assert event["source_authority"] == "peer_turn_latency_traces"
    assert event["source_id"] == f"peer_latency_{item_id}"
    assert event["inbox_item_id"] == item_id
    assert event["status"] == "failed"
    assert event["delivery_mode"] == "failed"
    assert event["degraded_reason"] == "peer_no_inbox_writeback_message"
    assert event["latency_ms"] == 1500
    assert event["stage_names"] == ["chat_read_inbox"]
    assert payload["peer_progress_counts"]["failed"] == 1
    assert payload["recent_peer_progress_events"] == progress_events[-5:]


def test_dynamic_participant_add_records_visible_roster_event(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Dynamic roster"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/participants",
        json={
            "role": "review",
            "display_name": "opencode-review-god",
            "cli_kind": "opencode",
            "model": "opencode-go/deepseek-v4-flash",
        },
    )

    assert response.status_code == 201
    participant = response.json()

    timeline = client.get(f"/api/chat/conversations/{conv['id']}/messages").json()

    assert timeline["messages"] == []
    assert timeline["roster_event_counts"] == {"total": 1, "participant_added": 1}
    assert timeline["recent_roster_events"] == timeline["roster_events"][-5:]
    event = timeline["roster_events"][0]
    assert event["source_authority"] == "participants"
    assert event["action"] == "participant_added"
    assert event["participant_id"] == participant["participant_id"]
    assert event["role"] == "review"
    assert event["display_name"] == "opencode-review-god"
    assert event["cli_kind"] == "opencode"
    assert event["model"] == "opencode-go/deepseek-v4-flash"

    session = participant["session"]
    assert session["participant_id"] == participant["participant_id"]
    assert session["role"] == "review"
    assert session["runtime"] == "opencode"
    assert session["provider_id"] == "opencode"
    assert session["profile_id"] == "review"
    assert session["model"] == "opencode-go/deepseek-v4-flash"

    restarted_client = TestClient(create_app(tmp_path))
    listed = restarted_client.get(f"/api/chat/conversations/{conv['id']}/participants").json()
    listed_participant = next(
        item
        for item in listed["participants"]
        if item["participant_id"] == participant["participant_id"]
    )
    assert listed_participant["session"]["god_session_id"] == session["god_session_id"]
    assert listed_participant["session"]["runtime"] == "opencode"

    with sqlite3.connect(tmp_path / "chat.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            select envelope_type, envelope_json
            from messages
            where id = ?
            """,
            (event["message_id"],),
        ).fetchone()
    assert row is not None
    assert row["envelope_type"] == "roster_event"
    envelope = json.loads(row["envelope_json"])
    assert envelope["source_authority"] == "participants"
    assert envelope["participant_id"] == participant["participant_id"]


def test_rest_message_routes_role_before_capitalized_sentence(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "@architect Coordinate a tiny routing fix.",
            "client_request_id": "rest-leading-capitalized-sentence",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == ["@architect"]
    assert [item["target_role"] for item in payload["inbox_items"]] == ["architect"]


def test_rest_message_all_broadcasts_to_active_peers(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Broadcast"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "@all please join this discussion",
            "client_request_id": "rest-all-broadcast",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == ["@all"]
    routed_roles = sorted(item["target_role"] for item in payload["inbox_items"])
    assert routed_roles == ["architect", "execute", "review"]
    assert {item["item_type"] for item in payload["inbox_items"]} == {"mention"}


def test_thread_message_endpoint_uses_peer_service(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Thread"}).json()

    response = client.post(
        f"/api/chat/threads/{conv['id']}/messages",
        json={"message": "@review check", "client_request_id": "thread-1"},
    )

    assert response.status_code == 201
    assert response.json()["message"]["mentions"] == ["@review"]


def test_rest_message_preserves_unknown_at_text_as_plain_message(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "please keep @external-handle as text",
            "client_request_id": "rest-unknown-mention",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"] == "please keep @external-handle as text"
    assert payload["mentions"] == []
    assert payload["inbox_items"] == []


def test_rest_message_inline_code_mention_stays_plain_without_peer_enqueue(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "Document `@architect` literally in the example.",
            "client_request_id": "rest-inline-code-mention",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == []
    assert payload["inbox_items"] == []
    assert ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conv["id"]) == []


def test_rest_message_escaped_mention_stays_plain_without_peer_enqueue(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Chat"}).json()

    response = client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": r"Keep \@architect as literal text in the docs.",
            "client_request_id": "rest-escaped-mention",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mentions"] == []
    assert payload["inbox_items"] == []
    assert ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conv["id"]) == []


def test_thread_message_preserves_unknown_at_text_as_plain_message(tmp_path):
    client = TestClient(create_app(tmp_path))
    conv = client.post("/api/chat/conversations", json={"title": "Thread"}).json()

    response = client.post(
        f"/api/chat/threads/{conv['id']}/messages",
        json={
            "message": "plain update for @external-handle",
            "client_request_id": "thread-unknown-mention",
        },
    )

    assert response.status_code == 201
    payload = response.json()["message"]
    assert payload["content"] == "plain update for @external-handle"
    assert payload["mentions"] == []


def test_god_post_message_mentions_are_display_only_without_followup_inbox(
    tmp_path,
) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="GOD mention display only")
    conv_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conv_id,
        participants["architect"]["participant_id"],
    )

    result = service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conv_id,
        participant_id=participants["architect"]["participant_id"],
        god_session_id=architect_session.god_session_id,
        client_request_id="architect-mentions-execute-display-only",
        content="@execute please turn this plan into an implementation slice.",
    )

    assert result["message"]["mentions"] == ["@execute"]
    assert result["inbox_items"] == []
    assert ChatInboxStore(tmp_path / "chat.db").list_for_participant(
        conversation_id=conv_id,
        participant_id=participants["execute"]["participant_id"],
    ) == []


def test_god_mention_explicitly_routes_to_target_peer_inbox(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="GOD explicit route")
    conv_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conv_id,
        participants["architect"]["participant_id"],
    )

    result = service.mention_from_god(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conv_id,
        participant_id=participants["architect"]["participant_id"],
        god_session_id=architect_session.god_session_id,
        client_request_id="architect-explicitly-routes-execute",
        target_address="@execute",
        content="Please turn this TUI blueprint into an implementation slice.",
    )

    assert result["message"]["mentions"] == ["@execute"]
    assert len(result["inbox_items"]) == 1
    item = ChatInboxStore(tmp_path / "chat.db").get(result["inbox_items"][0]["id"])
    assert item.target_participant_id == participants["execute"]["participant_id"]
    assert item.sender_participant_id == participants["architect"]["participant_id"]
    assert item.item_type == "mention"
