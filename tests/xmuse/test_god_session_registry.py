from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xmuse_core.agents import god_session_registry as registry_module
from xmuse_core.agents.god_session_registry import GodSessionRegistry


def test_create_persists_stable_god_session_id(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)

    record = registry.create(
        role="planner",
        agent_name="alpha",
        runtime="codex",
        session_address="addr://planner-1",
        session_inbox_id="inbox-planner-1",
    )

    assert record.god_session_id.startswith("god-")
    assert record.assignment_feature_id is None
    stored = json.loads(path.read_text())
    assert stored == {
        "sessions": [
            {
                "god_session_id": record.god_session_id,
                "role": "planner",
                "agent_name": "alpha",
                "runtime": "codex",
                "session_address": "addr://planner-1",
                "session_inbox_id": "inbox-planner-1",
                "conversation_id": None,
                "participant_id": None,
                "status": "starting",
                "assignment_feature_id": None,
                "pid": None,
                "model": None,
                "prompt_fingerprint": None,
                "worktree": None,
                "feature_scope_id": None,
                "provider_session_id": None,
                "provider_session_kind": None,
                "provider_binding_status": None,
                "provider_binding_failure_reason": None,
            }
        ]
    }


def test_lookup_by_address_and_inbox(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)

    created = registry.create(
        role="reviewer",
        agent_name="beta",
        runtime="claude_code",
        session_address="addr://reviewer-1",
        session_inbox_id="inbox-reviewer-1",
    )

    by_address = registry.find_by_address("addr://reviewer-1")
    by_inbox = registry.find_by_inbox("inbox-reviewer-1")
    by_id = registry.get(created.god_session_id)

    assert by_address == created
    assert by_inbox == created
    assert by_id == created
    assert registry.list() == [created]


def test_assign_updates_feature_without_changing_god_session_id(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)

    created = registry.create(
        role="executor",
        agent_name="gamma",
        runtime="codex",
        session_address="addr://executor-1",
        session_inbox_id="inbox-executor-1",
    )

    updated = registry.assign(created.god_session_id, "feature-123")

    assert updated.god_session_id == created.god_session_id
    assert updated.assignment_feature_id == "feature-123"
    reloaded = GodSessionRegistry(path).get(created.god_session_id)
    assert reloaded.god_session_id == created.god_session_id
    assert reloaded.assignment_feature_id == "feature-123"


def test_update_provider_binding_persists_resume_metadata(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)

    created = registry.create(
        role="reviewer",
        agent_name="beta",
        runtime="codex",
        session_address="addr://reviewer-1",
        session_inbox_id="inbox-reviewer-1",
    )

    updated = registry.update_provider_binding(
        created.god_session_id,
        provider_session_id="thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )

    assert updated.provider_session_id == "thread-1"
    assert updated.provider_session_kind == "codex_app_server_thread"
    assert updated.provider_binding_status == "active"
    reloaded = GodSessionRegistry(path).get(created.god_session_id)
    assert reloaded.provider_session_id == "thread-1"


def test_promote_running_updates_starting_status_after_writeback(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)

    created = registry.create(
        role="reviewer",
        agent_name="beta",
        runtime="codex",
        session_address="addr://reviewer-1",
        session_inbox_id="inbox-reviewer-1",
        conversation_id="conv-1",
        participant_id="part-review-1",
        model="gpt-5.5",
    )

    updated = registry.promote_running(created.god_session_id)

    assert updated.status == "running"
    reloaded = GodSessionRegistry(path).get(created.god_session_id)
    assert reloaded.status == "running"
    assert reloaded.participant_id == "part-review-1"
    assert reloaded.model == "gpt-5.5"


def test_create_rejects_duplicate_session_address(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)
    registry.create(
        role="planner",
        agent_name="alpha",
        runtime="codex",
        session_address="addr://shared",
        session_inbox_id="inbox-alpha",
    )

    with pytest.raises(ValueError, match="session_address"):
        registry.create(
            role="reviewer",
            agent_name="beta",
            runtime="claude_code",
            session_address="addr://shared",
            session_inbox_id="inbox-beta",
        )


def test_create_rejects_duplicate_session_inbox_id(tmp_path):
    path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(path)
    registry.create(
        role="planner",
        agent_name="alpha",
        runtime="codex",
        session_address="addr://alpha",
        session_inbox_id="inbox-shared",
    )

    with pytest.raises(ValueError, match="session_inbox_id"):
        registry.create(
            role="reviewer",
            agent_name="beta",
            runtime="claude_code",
            session_address="addr://beta",
            session_inbox_id="inbox-shared",
        )


def test_assign_preserves_unrelated_fields(tmp_path):
    path = tmp_path / "god_sessions.json"
    initial = {
        "sessions": [
            {
                "god_session_id": "god-existing",
                "role": "planner",
                "agent_name": "alpha",
                "runtime": "codex",
                "session_address": "addr://alpha",
                "session_inbox_id": "inbox-alpha",
                "status": "running",
                "assignment_feature_id": None,
                "pid": 4242,
                "model": "gpt-5.5",
                "prompt_fingerprint": "sha256:abc",
                "worktree": "/repo",
                "feature_scope_id": "feature-123",
            }
        ]
    }
    path.write_text(json.dumps(initial))
    registry = GodSessionRegistry(path)

    updated = registry.assign("god-existing", "feature-123")

    assert updated.god_session_id == "god-existing"
    assert updated.role == "planner"
    assert updated.agent_name == "alpha"
    assert updated.runtime == "codex"
    assert updated.session_address == "addr://alpha"
    assert updated.session_inbox_id == "inbox-alpha"
    assert updated.status == "running"
    assert updated.pid == 4242
    assert updated.model == "gpt-5.5"
    assert updated.prompt_fingerprint == "sha256:abc"
    assert updated.worktree == "/repo"
    assert updated.feature_scope_id == "feature-123"
    assert updated.assignment_feature_id == "feature-123"


def test_create_and_assign_use_sidecar_file_lock(tmp_path, monkeypatch):
    path = tmp_path / "god_sessions.json"
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle, operation):
        lock_calls.append((Path(handle.name).name, operation))

    monkeypatch.setattr(
        registry_module,
        "fcntl",
        SimpleNamespace(LOCK_EX=1, LOCK_UN=2, flock=fake_flock),
        raising=False,
    )
    registry = GodSessionRegistry(path)

    created = registry.create(
        role="planner",
        agent_name="alpha",
        runtime="codex",
        session_address="addr://alpha",
        session_inbox_id="inbox-alpha",
    )
    registry.assign(created.god_session_id, "feature-123")

    assert path.with_name(f"{path.name}.lock").exists()
    assert lock_calls == [
        (f"{path.name}.lock", 1),
        (f"{path.name}.lock", 2),
        (f"{path.name}.lock", 1),
        (f"{path.name}.lock", 2),
    ]


def test_registry_records_conversation_and_participant(tmp_path):
    registry = GodSessionRegistry(tmp_path / "sessions.json")
    record = registry.create(
        role="architect",
        agent_name="codex",
        runtime="codex",
        session_address="@conv_a:part_architect",
        session_inbox_id="inbox-conv_a-part_architect",
        conversation_id="conv_a",
        participant_id="part_architect",
    )

    loaded = registry.get(record.god_session_id)
    assert loaded.conversation_id == "conv_a"
    assert loaded.participant_id == "part_architect"


def test_find_by_conversation_role_returns_init_god_session(tmp_path):
    registry = GodSessionRegistry(tmp_path / "sessions.json")
    record = registry.create(
        role="init",
        agent_name="init-god",
        runtime="codex",
        session_address="@conv_a:init-god",
        session_inbox_id="inbox-conv_a-init-god",
        conversation_id="conv_a",
        participant_id="part_init",
    )

    loaded = registry.find_by_conversation_role("conv_a", "init")

    assert loaded == record


def test_create_rejects_duplicate_init_god_session_for_same_conversation(tmp_path):
    registry = GodSessionRegistry(tmp_path / "sessions.json")
    registry.create(
        role="init",
        agent_name="init-god",
        runtime="codex",
        session_address="@conv_a:init-god",
        session_inbox_id="inbox-conv_a-init-god",
        conversation_id="conv_a",
        participant_id="part_init_a",
    )

    with pytest.raises(ValueError, match="duplicate init god session"):
        registry.create(
            role="init",
            agent_name="init-god",
            runtime="codex",
            session_address="@conv_a:init-god-2",
            session_inbox_id="inbox-conv_a-init-god-2",
            conversation_id="conv_a",
            participant_id="part_init_b",
        )


def test_create_persists_peer_compatibility_metadata(tmp_path):
    registry = GodSessionRegistry(tmp_path / "sessions.json")

    record = registry.create(
        role="review",
        agent_name="codex-review",
        runtime="codex",
        session_address="@conv_a:part_review",
        session_inbox_id="inbox-conv_a-part_review",
        conversation_id="conv_a",
        participant_id="part_review",
        model="gpt-5.5",
        prompt_fingerprint="sha256:abc",
        worktree="/repo",
        feature_scope_id="feature-a",
    )

    loaded = registry.get(record.god_session_id)
    assert loaded.model == "gpt-5.5"
    assert loaded.prompt_fingerprint == "sha256:abc"
    assert loaded.worktree == "/repo"
    assert loaded.feature_scope_id == "feature-a"


def test_find_by_conversation_participant_can_select_feature_scope(tmp_path):
    registry = GodSessionRegistry(tmp_path / "sessions.json")
    unscoped = registry.create(
        role="review",
        agent_name="opencode-review",
        runtime="opencode",
        session_address="@conv_a:part_review",
        session_inbox_id="inbox-conv_a-part_review",
        conversation_id="conv_a",
        participant_id="part_review",
        model="opencode-go/deepseek-v4-flash",
    )
    scoped = registry.create(
        role="review",
        agent_name="opencode-review",
        runtime="opencode",
        session_address="@conv_a:part_review:feature-feature-a",
        session_inbox_id="inbox-conv_a-part_review:feature-feature-a",
        conversation_id="conv_a",
        participant_id="part_review",
        model="opencode-go/deepseek-v4-flash",
        prompt_fingerprint="sha256:review",
        worktree="/repo/review",
        feature_scope_id="feature-a",
    )

    assert registry.find_by_conversation_participant(
        "conv_a",
        "part_review",
    ) == unscoped
    assert registry.find_by_conversation_participant(
        "conv_a",
        "part_review",
        feature_scope_id=None,
    ) == unscoped
    assert registry.find_by_conversation_participant(
        "conv_a",
        "part_review",
        feature_scope_id="feature-a",
    ) == scoped


def test_registry_loads_legacy_records_without_peer_metadata(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "god_session_id": "god-legacy",
                        "role": "review",
                        "agent_name": "codex-review",
                        "runtime": "codex",
                        "session_address": "@review",
                        "session_inbox_id": "inbox-review",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    record = GodSessionRegistry(path).get("god-legacy")

    assert record.model is None
    assert record.prompt_fingerprint is None
    assert record.worktree is None
    assert record.feature_scope_id is None
