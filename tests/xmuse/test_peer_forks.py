from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_forks import PeerForkRecord, PeerForkStore
from xmuse_core.chat.store import ChatStore


def _conversation_with_sessions(
    tmp_path: Path,
) -> tuple[Path, Path, str, str, str, str, str]:
    db_path = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Peer forks")
    participants = ParticipantStore(db_path)
    source = participants.ensure_init_god(
        conversation_id=conversation.id,
        model="gpt-5.5",
    )
    forked = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    registry = GodSessionRegistry(registry_path)
    source_session = registry.create(
        role=source.role,
        agent_name=source.display_name,
        runtime="codex",
        session_address=f"@{conversation.id}:{source.participant_id}",
        session_inbox_id=f"inbox-{source.participant_id}",
        conversation_id=conversation.id,
        participant_id=source.participant_id,
        model=source.model,
    )
    forked_session = registry.create(
        role=forked.role,
        agent_name=forked.display_name,
        runtime="codex",
        session_address=f"@{conversation.id}:{forked.participant_id}",
        session_inbox_id=f"inbox-{forked.participant_id}",
        conversation_id=conversation.id,
        participant_id=forked.participant_id,
        model=forked.model,
        feature_scope_id="feature-alpha",
    )
    return (
        db_path,
        registry_path,
        conversation.id,
        source.participant_id,
        forked.participant_id,
        source_session.god_session_id,
        forked_session.god_session_id,
    )


def test_peer_fork_record_validates_distinct_peers_and_required_fields() -> None:
    with pytest.raises(ValidationError, match="source_peer_id and new_peer_id must differ"):
        PeerForkRecord(
            fork_id="fork-1",
            conversation_id="conv-1",
            source_peer_id="part-same",
            new_peer_id="part-same",
            prompt_delta="role delta",
            inherited_refs=["docs/spec.md"],
            model_policy={"runtime": "codex"},
            fork_reason="specialize review",
            created_at="2026-05-31T00:00:00Z",
        )

    with pytest.raises(ValidationError, match="prompt_delta must not be blank"):
        PeerForkRecord(
            fork_id="fork-2",
            conversation_id="conv-1",
            source_peer_id="part-a",
            new_peer_id="part-b",
            prompt_delta="   ",
            inherited_refs=["docs/spec.md"],
            model_policy={"runtime": "codex"},
            fork_reason="specialize review",
            created_at="2026-05-31T00:00:00Z",
        )


def test_record_peer_fork_round_trips_normalized_contract(tmp_path: Path) -> None:
    (
        db_path,
        registry_path,
        conversation_id,
        source_peer_id,
        new_peer_id,
        _source_session_id,
        _new_session_id,
    ) = _conversation_with_sessions(tmp_path)
    store = PeerForkStore(db_path, registry_path=registry_path)

    created = store.record(
        conversation_id=conversation_id,
        source_peer_id=source_peer_id,
        new_peer_id=new_peer_id,
        prompt_delta="Add review rigor and bounded-worker instructions.",
        inherited_refs=[" docs/spec.md ", "", "memory://conversation/bootstrap"],
        model_policy={
            "runtime": "codex",
            "enabled": True,
            "review_model": "gpt-5.5",
            "coordinator_model": "gpt-5.4",
            "worker_model": "gpt-5.4-mini",
            "delegation_mode": "bounded_worker",
        },
        feature_scope_id=" feature-alpha ",
        fork_reason=" Narrow the peer into a review specialist. ",
    )

    loaded = store.get(created.fork_id)

    assert loaded == created
    assert loaded.inherited_refs == [
        "docs/spec.md",
        f"memory://conversation/{conversation_id}/bootstrap",
    ]
    assert loaded.model_policy == {
        "model_policy_runtime": "codex",
        "model_policy_enabled": True,
        "review_model": "gpt-5.5",
        "coordinator_model": "gpt-5.4",
        "worker_model": "gpt-5.4-mini",
        "delegation_mode": "bounded_worker",
    }
    assert loaded.feature_scope_id == "feature-alpha"
    assert loaded.fork_reason == "Narrow the peer into a review specialist."


def test_record_peer_fork_rejects_memory_refs_from_other_conversations(
    tmp_path: Path,
) -> None:
    (
        db_path,
        registry_path,
        conversation_id,
        source_peer_id,
        new_peer_id,
        _source_session_id,
        _new_session_id,
    ) = _conversation_with_sessions(tmp_path)
    store = PeerForkStore(db_path, registry_path=registry_path)

    with pytest.raises(ValueError, match="memory refs must stay within the conversation"):
        store.record(
            conversation_id=conversation_id,
            source_peer_id=source_peer_id,
            new_peer_id=new_peer_id,
            prompt_delta="Add review rigor and bounded-worker instructions.",
            inherited_refs=["memory://conversation/conv-foreign/bootstrap"],
            model_policy={"runtime": "codex"},
            feature_scope_id="feature-alpha",
            fork_reason="Specialize review.",
        )


def test_record_peer_fork_requires_persistent_sessions_for_both_peers(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Peer forks")
    participants = ParticipantStore(db_path)
    source = participants.ensure_init_god(
        conversation_id=conversation.id,
        model="gpt-5.5",
    )
    forked = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    store = PeerForkStore(db_path, registry_path=registry_path)

    with pytest.raises(ValueError, match="persistent peer sessions"):
        store.record(
            conversation_id=conversation.id,
            source_peer_id=source.participant_id,
            new_peer_id=forked.participant_id,
            prompt_delta="Add review rigor.",
            inherited_refs=["docs/spec.md"],
            model_policy={"runtime": "codex"},
            fork_reason="specialize review",
        )


def test_list_summaries_includes_participant_and_session_lineage(tmp_path: Path) -> None:
    (
        db_path,
        registry_path,
        conversation_id,
        source_peer_id,
        new_peer_id,
        source_session_id,
        new_session_id,
    ) = _conversation_with_sessions(tmp_path)
    store = PeerForkStore(db_path, registry_path=registry_path)
    record = store.record(
        conversation_id=conversation_id,
        source_peer_id=source_peer_id,
        new_peer_id=new_peer_id,
        prompt_delta="Add review rigor and evidence routing.",
        inherited_refs=["docs/spec.md", "memory://conversation/bootstrap"],
        model_policy={
            "model_policy_runtime": "codex",
            "review_model": "gpt-5.5",
        },
        feature_scope_id="feature-alpha",
        fork_reason="specialize review",
    )

    summaries = store.list_summaries_by_conversation(conversation_id)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.fork_id == record.fork_id
    assert summary.source_peer_id == source_peer_id
    assert summary.source_role == "init"
    assert summary.source_display_name == "init-god"
    assert summary.source_god_session_id == source_session_id
    assert summary.new_peer_id == new_peer_id
    assert summary.new_role == "review"
    assert summary.new_display_name == "Review GOD"
    assert summary.new_god_session_id == new_session_id
    assert summary.model_policy_runtime == "codex"
    assert summary.inherited_ref_count == 2
    assert summary.feature_scope_id == "feature-alpha"
    assert summary.fork_reason == "specialize review"

    participants = ParticipantStore(db_path)
    source = participants.get(source_peer_id)
    forked = participants.get(new_peer_id)
    assert source.provider_id.value == "codex"
    assert source.profile_id.value == "god"
    assert forked.provider_id.value == "codex"
    assert forked.profile_id.value == "review"


def test_record_bootstrap_once_is_duplicate_safe(tmp_path: Path) -> None:
    (
        db_path,
        registry_path,
        conversation_id,
        source_peer_id,
        new_peer_id,
        _source_session_id,
        _new_session_id,
    ) = _conversation_with_sessions(tmp_path)
    store = PeerForkStore(db_path, registry_path=registry_path)

    first = store.record_bootstrap_once(
        fork_id="bootstrap-fork:conv:proposal:init:review",
        conversation_id=conversation_id,
        source_peer_id=source_peer_id,
        new_peer_id=new_peer_id,
        prompt_delta="Add review rigor.",
        inherited_refs=["memory://conversation/bootstrap"],
        model_policy={"runtime": "codex"},
        feature_scope_id=None,
        fork_reason="bootstrap review",
    )
    second = store.record_bootstrap_once(
        fork_id="bootstrap-fork:conv:proposal:init:review",
        conversation_id=conversation_id,
        source_peer_id=source_peer_id,
        new_peer_id=new_peer_id,
        prompt_delta="Changed text must not create a duplicate.",
        inherited_refs=[],
        model_policy={"runtime": "codex"},
        feature_scope_id=None,
        fork_reason="duplicate replay",
    )

    records = store.list_by_conversation(conversation_id)
    assert first == second
    assert len(records) == 1
    assert records[0].prompt_delta == "Add review rigor."
