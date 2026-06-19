from pathlib import Path

import pytest

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatError, PeerChatService
from xmuse_core.chat.store import ChatStore


def _conversation(tmp_path: Path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Peer chat")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    return db, conv, architect, review


def test_human_post_resolves_mention_and_creates_inbox(tmp_path: Path) -> None:
    db, conv, architect, _review = _conversation(tmp_path)
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="please @architect discuss the plan",
        client_request_id="req-human-1",
    )

    assert result.message.role == "human"
    assert result.message.mentions == ["@architect"]
    assert len(result.inbox_items) == 1
    assert result.inbox_items[0].target_participant_id == architect.participant_id


def test_human_post_treats_leading_mentions_as_routing_header(
    tmp_path: Path,
) -> None:
    db, conv, architect, _review = _conversation(tmp_path)
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content=(
            "@architect please coordinate this. The requirement text must "
            "discuss @execute and @review as role examples, but only the "
            "architect should receive the initial turn."
        ),
        client_request_id="req-human-leading-router",
    )

    assert result.message.mentions == ["@architect"]
    assert [item.target_role for item in result.inbox_items] == ["architect"]
    assert result.inbox_items[0].target_participant_id == architect.participant_id


def test_human_post_allows_multiple_leading_route_mentions(tmp_path: Path) -> None:
    db, conv, architect, review = _conversation(tmp_path)
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="@architect @review compare the safe path.",
        client_request_id="req-human-leading-multi-router",
    )

    assert result.message.mentions == ["@architect", "@review"]
    assert [item.target_participant_id for item in result.inbox_items] == [
        architect.participant_id,
        review.participant_id,
    ]


def test_ambiguous_mention_fails_without_creating_inbox(tmp_path: Path) -> None:
    db, conv, _architect, _review = _conversation(tmp_path)
    participants = ParticipantStore(db)
    participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect Backup",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    with pytest.raises(PeerChatError, match="ambiguous_target"):
        service.post_human_message(
            conversation_id=conv.id,
            author="Human operator",
            content="@architect please handle this",
            client_request_id="req-human-ambiguous",
        )

    assert ChatStore(db).list_messages(conv.id) == []


def test_idempotent_human_post_returns_same_message(tmp_path: Path) -> None:
    db, conv, _architect, _review = _conversation(tmp_path)
    service = PeerChatService(db)

    first = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="@review please check",
        client_request_id="same-request",
    )
    second = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="@review please check",
        client_request_id="same-request",
    )

    assert second.message.id == first.message.id
    assert [item.id for item in second.inbox_items] == [item.id for item in first.inbox_items]


def test_non_ascii_display_name_can_be_mentioned_by_participant_id(tmp_path: Path) -> None:
    db, conv, architect, _review = _conversation(tmp_path)
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content=f"please @participant:{architect.participant_id} discuss the plan",
        client_request_id="req-human-participant-id",
    )

    assert result.inbox_items[0].target_participant_id == architect.participant_id


def test_display_name_with_spaces_can_be_mentioned(tmp_path: Path) -> None:
    db, conv, _architect, _review = _conversation(tmp_path)
    qa = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="qa",
        display_name="QA Lead",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="please @QA Lead review the proposal",
        client_request_id="req-human-display-name",
    )

    assert result.message.mentions == ["@qa-lead"]
    assert result.inbox_items[0].target_participant_id == qa.participant_id


def test_create_conversation_rejects_non_codex_participants(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    with pytest.raises(PeerChatError, match="codex_only_participants"):
        service.create_conversation(
            title="Invalid",
            participants=[
                {
                    "role": "architect",
                    "display_name": "Architect GOD",
                    "cli_kind": "claude",
                }
            ],
        )

    assert ChatStore(db).list_conversations() == []


def test_create_conversation_accepts_provider_profile_participants(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    payload = service.create_conversation(
        title="Provider compatible",
        participants=[
            {
                "role": "review",
                "display_name": "Review GOD",
                "provider_id": "codex",
                "profile_id": "review",
                "model": "gpt-5.5",
            }
        ],
    )

    assert payload["conversation"]["title"] == "Provider compatible"
    assert payload["participants"] == [
        {
            "participant_id": payload["participants"][0]["participant_id"],
            "conversation_id": payload["conversation"]["id"],
            "role": "review",
            "display_name": "Review GOD",
            "provider_id": "codex",
            "profile_id": "review",
            "cli_kind": "codex",
            "model": "gpt-5.4",
            "role_template_id": payload["participants"][0]["role_template_id"],
            "status": "active",
            "last_seen_at": None,
            "created_at": payload["participants"][0]["created_at"],
        }
    ]
    listed = service.list_participants(
        conversation_id=payload["conversation"]["id"],
        registry_path=tmp_path / "god_sessions.json",
    )
    review = next(
        participant for participant in listed["participants"]
        if participant["role"] == "review"
    )
    assert review["session"]["provider_id"] == "codex"
    assert review["session"]["profile_id"] == "review"
    assert review["session"]["runtime"] == "codex"


def test_create_conversation_accepts_explicit_opencode_review_participant(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    payload = service.create_conversation(
        title="OpenCode review",
        participants=[
            {
                "role": "review",
                "display_name": "Review OpenCode",
                "provider_id": "opencode",
                "profile_id": "review",
                "cli_kind": "opencode",
                "model": "gpt-oss",
            }
        ],
    )

    assert payload["participants"] == [
        {
            "participant_id": payload["participants"][0]["participant_id"],
            "conversation_id": payload["conversation"]["id"],
            "role": "review",
            "display_name": "Review OpenCode",
            "provider_id": "opencode",
            "profile_id": "review",
            "cli_kind": "opencode",
            "model": "gpt-oss",
            "role_template_id": payload["participants"][0]["role_template_id"],
            "status": "active",
            "last_seen_at": None,
            "created_at": payload["participants"][0]["created_at"],
        }
    ]
    listed = service.list_participants(
        conversation_id=payload["conversation"]["id"],
        registry_path=tmp_path / "god_sessions.json",
    )
    review = next(
        participant for participant in listed["participants"]
        if participant["role"] == "review"
    )
    assert review["session"]["provider_id"] == "opencode"
    assert review["session"]["profile_id"] == "review"
    assert review["session"]["runtime"] == "opencode"
    listed = service.list_participants(
        conversation_id=payload["conversation"]["id"],
        registry_path=tmp_path / "god_sessions.json",
    )
    review = next(
        participant for participant in listed["participants"]
        if participant["role"] == "review"
    )
    assert review["session"]["runtime"] == "opencode"
    assert review["session"]["model"] == "gpt-oss"


def test_create_conversation_infers_review_profile_for_opencode_participant(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    payload = service.create_conversation(
        title="OpenCode review",
        participants=[
            {
                "role": "review",
                "display_name": "Review GOD",
                "provider_id": "opencode",
                "cli_kind": "opencode",
                "model": "deepseek-v4-flash",
            }
        ],
    )

    assert payload["participants"] == [
        {
            "participant_id": payload["participants"][0]["participant_id"],
            "conversation_id": payload["conversation"]["id"],
            "role": "review",
            "display_name": "Review GOD",
            "provider_id": "opencode",
            "profile_id": "review",
            "cli_kind": "opencode",
            "model": "deepseek-v4-flash",
            "role_template_id": payload["participants"][0]["role_template_id"],
            "status": "active",
            "last_seen_at": None,
            "created_at": payload["participants"][0]["created_at"],
        }
    ]


def test_create_conversation_rejects_explicit_profile_mismatch_for_role(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    with pytest.raises(PeerChatError) as exc_info:
        service.create_conversation(
            title="Invalid review",
            participants=[
                {
                    "role": "review",
                    "display_name": "Review GOD",
                    "provider_id": "opencode",
                    "profile_id": "default",
                    "cli_kind": "opencode",
                    "model": "deepseek-v4-flash",
                }
            ],
        )

    assert exc_info.value.code == "participant_profile_role_mismatch"
    assert exc_info.value.details == {
        "role": "review",
        "expected_profile_id": "review",
        "provided_profile_id": "default",
        "role_profile_map": {"review": "review"},
    }
    assert ChatStore(db).list_conversations() == []


def test_create_conversation_defaults_to_non_final_quality_participant_models(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)

    payload = service.create_conversation(title="Default participants")

    participants = {
        participant["role"]: participant["model"]
        for participant in payload["participants"]
    }

    assert participants == {
        "architect": "gpt-5.4",
        "review": "gpt-5.4",
        "execute": "gpt-5.4-mini",
    }


def test_fork_participant_creates_participant_session_and_compact_lineage(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db)
    conversation = chat.create_conversation("Forks")
    participants = ParticipantStore(db)
    source = participants.ensure_init_god(
        conversation_id=conversation.id,
        model="gpt-5.5",
    )
    source_session = GodSessionRegistry(registry_path).create(
        role=source.role,
        agent_name=source.display_name,
        runtime="codex",
        session_address=f"@{conversation.id}:{source.participant_id}",
        session_inbox_id=f"inbox-{source.participant_id}",
        conversation_id=conversation.id,
        participant_id=source.participant_id,
        model=source.model,
    )
    service = PeerChatService(db)

    created = service.fork_participant(
        registry_path=registry_path,
        conversation_id=conversation.id,
        source_peer_id=source.participant_id,
        role="review",
        display_name="Review Child",
        model="gpt-5.5",
        prompt_delta="Add review rigor and bounded execution constraints.",
        inherited_refs=[" docs/spec.md ", "memory://conversation/bootstrap", ""],
        model_policy={"runtime": "codex", "review_model": "gpt-5.5"},
        fork_reason=" specialize review ",
        feature_scope_id=" feature-alpha ",
    )

    assert created["participant"]["conversation_id"] == conversation.id
    assert created["participant"]["role"] == "review"
    assert created["participant"]["display_name"] == "Review Child"
    assert created["participant"]["provider_id"] == "codex"
    assert created["participant"]["profile_id"] == "review"
    assert created["participant"]["model"] == "gpt-5.4"
    assert created["session"]["participant_id"] == created["participant"]["participant_id"]
    assert created["session"]["conversation_id"] == conversation.id
    assert created["session"]["provider_id"] == "codex"
    assert created["session"]["profile_id"] == "review"
    assert created["session"]["model"] == "gpt-5.4"
    assert created["session"]["feature_scope_id"] == "feature-alpha"
    assert created["lineage"]["source_peer_id"] == source.participant_id
    assert created["lineage"]["source_god_session_id"] == source_session.god_session_id
    assert created["lineage"]["new_peer_id"] == created["participant"]["participant_id"]
    assert created["lineage"]["new_god_session_id"] == created["session"]["god_session_id"]
    assert created["lineage"]["inherited_ref_count"] == 2
    assert created["lineage"]["fork_reason"] == "specialize review"

    listing = service.list_participants(
        conversation_id=conversation.id,
        registry_path=registry_path,
    )

    assert listing["conversation_id"] == conversation.id
    assert listing["lineage"] == [created["lineage"]]
    forked = next(
        participant
        for participant in listing["participants"]
        if participant["participant_id"] == created["participant"]["participant_id"]
    )
    assert forked["session"]["god_session_id"] == created["session"]["god_session_id"]
    assert forked["session"]["provider_id"] == "codex"
    assert forked["session"]["profile_id"] == "review"
    assert forked["session"]["feature_scope_id"] == "feature-alpha"


def test_fork_participant_rejects_invalid_contract_without_side_effects(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db)
    conversation = chat.create_conversation("Forks")
    participants = ParticipantStore(db)
    source = participants.ensure_init_god(
        conversation_id=conversation.id,
        model="gpt-5.5",
    )
    GodSessionRegistry(registry_path).create(
        role=source.role,
        agent_name=source.display_name,
        runtime="codex",
        session_address=f"@{conversation.id}:{source.participant_id}",
        session_inbox_id=f"inbox-{source.participant_id}",
        conversation_id=conversation.id,
        participant_id=source.participant_id,
        model=source.model,
    )
    service = PeerChatService(db)

    before_participants = participants.list_by_conversation(conversation.id)
    before_sessions = GodSessionRegistry(registry_path).list()

    with pytest.raises(
        ValueError,
        match="model_policy must declare model_policy_runtime",
    ):
        service.fork_participant(
            registry_path=registry_path,
            conversation_id=conversation.id,
            source_peer_id=source.participant_id,
            role="review",
            display_name="Broken Review Child",
            model="gpt-5.5",
            prompt_delta="Add review rigor and bounded execution constraints.",
            inherited_refs=["docs/spec.md"],
            model_policy={},
            fork_reason="specialize review",
        )

    after_participants = participants.list_by_conversation(conversation.id)
    after_sessions = GodSessionRegistry(registry_path).list()

    assert [item.participant_id for item in after_participants] == [
        item.participant_id for item in before_participants
    ]
    assert [item.god_session_id for item in after_sessions] == [
        item.god_session_id for item in before_sessions
    ]
    assert (
        service.list_fork_lineage(
            conversation_id=conversation.id,
            registry_path=registry_path,
        )["lineage"]
        == []
    )
