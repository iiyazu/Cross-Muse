from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.persistent_peer import PersistentCliPeerService
from xmuse_core.agents.protocol import parse_stdout_line
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime, SessionConfig
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


class FakeSession:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive
        self.sent_messages: list[tuple[str, dict[str, object]]] = []
        self.received_messages: list[object] = []
        self.aborted = False

    def is_alive(self) -> bool:
        return self._alive

    async def send_typed(self, msg_type: str, **kwargs) -> None:
        self.sent_messages.append((msg_type, kwargs))

    async def receive(self):
        if self.received_messages:
            return self.received_messages.pop(0)
        return None

    async def abort(self) -> None:
        self.aborted = True
        self._alive = False


class RecordingPeerSessionLayer:
    def __init__(self) -> None:
        self.ensure_calls: list[dict[str, object]] = []
        self._record: GodSessionRecord | None = None

    async def ensure_conversation_session(self, **kwargs) -> GodSessionRecord:
        self.ensure_calls.append(kwargs)
        if self._record is None:
            self._record = GodSessionRecord(
                god_session_id="god-peer-1",
                role=kwargs["role"],
                agent_name=kwargs["agent"].name,
                runtime=kwargs["agent"].runtime.value,
                session_address="@peer",
                session_inbox_id="inbox-peer",
                conversation_id=kwargs["conversation_id"],
                participant_id=kwargs["participant_id"],
                model=kwargs.get("model"),
                prompt_fingerprint=kwargs.get("prompt_fingerprint"),
                worktree=str(kwargs["worktree"]),
                feature_scope_id=kwargs.get("feature_scope_id"),
            )
        return self._record

    async def send_message(self, **kwargs) -> None:
        return None

    async def receive_message(self, god_session_id: str):
        return None


class FakeLauncher:
    def __init__(self, command: list[str] | None = None) -> None:
        self.command = command or ["fake-agent"]
        self.build_command_calls: list[tuple[str, Path]] = []
        self.build_persistent_command_calls: list[tuple[str, Path]] = []
        self.build_env_calls: list[str] = []
        self.supports_persistent_sessions = True

    def build_command(self, feature_id: str, worktree: Path) -> list[str]:
        self.build_command_calls.append((feature_id, worktree))
        return self.command

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        self.build_persistent_command_calls.append((role, worktree))
        return self.command

    def build_env(self, feature_id: str) -> dict[str, str] | None:
        self.build_env_calls.append(feature_id)
        return None

    def persistent_model(self) -> str:
        return "gpt-5.5"


class FakePersistentCommandLauncher(FakeLauncher):
    def __init__(self) -> None:
        super().__init__()
        self.build_persistent_command_calls: list[tuple[str, Path]] = []

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        self.build_persistent_command_calls.append((role, worktree))
        return ["fake-persistent-agent", role, str(worktree)]


class MisconfiguredPersistentLauncher:
    supports_persistent_sessions = True

    def build_command(self, feature_id: str, worktree: Path) -> list[str]:
        return ["one-shot-agent", feature_id, str(worktree)]

    def build_env(self, feature_id: str) -> dict[str, str] | None:
        return None


def _make_agent() -> AgentDescriptor:
    return AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="executor",
        capabilities=["code"],
        session_config=SessionConfig(),
    )


def _make_review_participant(tmp_path: Path) -> tuple[Path, str, str]:
    db_path = tmp_path / "chat.db"
    conversation = ChatStore(db_path).create_conversation("Peer session")
    participant = ParticipantStore(db_path).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    return db_path, conversation.id, participant.participant_id


class UnsupportedPersistentLauncher(FakeLauncher):
    supports_persistent_sessions = False

    def __init__(self) -> None:
        super().__init__()
        self.supports_persistent_sessions = False


@pytest.mark.asyncio
async def test_ensure_session_reuses_live_session_for_role(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        assert command == ["fake-agent"]
        assert env is None
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    first = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)
    second = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)

    assert first.god_session_id == second.god_session_id
    assert len(spawned_sessions) == 1
    assert launcher.build_persistent_command_calls == [("execute", tmp_path)]
    assert launcher.build_command_calls == []
    assert launcher.build_env_calls == ["execute"]


@pytest.mark.asyncio
async def test_ensure_session_prefers_persistent_command_builder(tmp_path, monkeypatch):
    launcher = FakePersistentCommandLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_commands: list[list[str]] = []

    async def fake_spawn(command, env=None):
        spawned_commands.append(command)
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    await layer.ensure_session(role="review", agent=_make_agent(), worktree=tmp_path)

    assert spawned_commands == [["fake-persistent-agent", "review", str(tmp_path)]]
    assert launcher.build_persistent_command_calls == [("review", tmp_path)]
    assert launcher.build_command_calls == []
    assert launcher.build_env_calls == ["review"]


@pytest.mark.asyncio
async def test_ensure_session_rejects_launcher_without_persistent_protocol(
    tmp_path,
    monkeypatch,
):
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: UnsupportedPersistentLauncher()},
    )

    async def fake_spawn(command, env=None):
        raise AssertionError("unsupported persistent launchers must not be spawned")

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    with pytest.raises(RuntimeError, match="does not support xmuse persistent sessions"):
        await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)


@pytest.mark.asyncio
async def test_ensure_session_rejects_launcher_with_fake_persistent_capability(
    tmp_path,
    monkeypatch,
):
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: MisconfiguredPersistentLauncher()},
    )

    async def fake_spawn(command, env=None):
        raise AssertionError("fake persistent launcher must not be spawned")

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    with pytest.raises(RuntimeError, match="does not support xmuse persistent sessions"):
        await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)


@pytest.mark.asyncio
async def test_ensure_session_rejects_role_reuse_when_shape_differs(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)

    other_agent = AgentDescriptor(
        runtime=AgentRuntime.CLAUDE_CODE,
        name="reviewer",
        capabilities=["code"],
        session_config=SessionConfig(),
    )
    with pytest.raises(
        RuntimeError,
        match="role='execute'.*existing live session.*requested agent/worktree",
    ):
        await layer.ensure_session(
            role="execute",
            agent=other_agent,
            worktree=tmp_path / "other-worktree",
        )


@pytest.mark.asyncio
async def test_ensure_session_respawns_dead_role_once_then_reuses_new_live_session(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    first = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)
    spawned_sessions[0]._alive = False

    second = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)
    third = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)

    assert first.god_session_id == second.god_session_id == third.god_session_id
    assert len(spawned_sessions) == 2
    assert launcher.build_persistent_command_calls == [
        ("execute", tmp_path),
        ("execute", tmp_path),
    ]
    assert launcher.build_command_calls == []
    assert launcher.build_env_calls == ["execute", "execute"]


@pytest.mark.asyncio
async def test_send_message_routes_by_god_session_id_not_feature_id(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    session = FakeSession()

    async def fake_spawn(command, env=None):
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)

    await layer.send_message(
        god_session_id=record.god_session_id,
        message_type="task",
        prompt="ship it",
        context="ctx",
    )

    assert session.sent_messages == [
        (
            "task",
            {
                "god_session_id": record.god_session_id,
                "prompt": "ship it",
                "context": "ctx",
            },
        )
    ]


@pytest.mark.asyncio
async def test_send_message_includes_structured_request_id(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    session = FakeSession()

    async def fake_spawn(command, env=None):
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_session(role="review", agent=_make_agent(), worktree=tmp_path)

    await layer.send_message(
        god_session_id=record.god_session_id,
        message_type="review",
        prompt="review it",
        context="ctx",
        request_id="req-1",
    )

    assert session.sent_messages == [
        (
            "review",
            {
                "god_session_id": record.god_session_id,
                "request_id": "req-1",
                "prompt": "review it",
                "context": "ctx",
            },
        )
    ]


@pytest.mark.asyncio
async def test_receive_message_routes_by_god_session_id(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    session = FakeSession()
    session.received_messages.append({"type": "result", "status": "success"})

    async def fake_spawn(command, env=None):
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_session(role="execute", agent=_make_agent(), worktree=tmp_path)

    message = await layer.receive_message(record.god_session_id)

    assert message == {"type": "result", "status": "success"}


@pytest.mark.asyncio
async def test_send_message_rejects_registered_but_unattached_session(tmp_path):
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={},
    )
    record = layer._registry.create(
        role="execute",
        agent_name="executor",
        runtime="codex",
        session_address="@execute",
        session_inbox_id="inbox-execute",
    )

    with pytest.raises(RuntimeError, match="registered.*no live transport attached"):
        await layer.send_message(
            god_session_id=record.god_session_id,
            message_type="task",
            prompt="ship it",
            context="ctx",
        )


@pytest.mark.asyncio
async def test_send_message_rejects_unknown_god_session_id(tmp_path):
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={},
    )

    with pytest.raises(LookupError, match="Unknown god_session_id: god-missing"):
        await layer.send_message(
            god_session_id="god-missing",
            message_type="task",
            prompt="ship it",
            context="ctx",
        )


@pytest.mark.asyncio
async def test_god_session_layer_does_not_reuse_across_conversations(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    first = await layer.ensure_conversation_session(
        conversation_id="conv_a",
        participant_id="part_architect_a",
        role="architect",
        agent=agent,
        worktree=tmp_path,
    )
    second = await layer.ensure_conversation_session(
        conversation_id="conv_b",
        participant_id="part_architect_b",
        role="architect",
        agent=agent,
        worktree=tmp_path,
    )

    assert first.god_session_id != second.god_session_id
    assert first.session_address != second.session_address
    assert len(spawned_sessions) == 2


@pytest.mark.asyncio
async def test_ensure_init_session_reuses_same_conversation_identity(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    first = await layer.ensure_init_session(
        conversation_id="conv_init",
        participant_id="part_init",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:init",
    )
    second = await layer.ensure_init_session(
        conversation_id="conv_init",
        participant_id="part_init",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:init",
    )

    assert first.god_session_id == second.god_session_id
    assert first.role == "init"
    assert len(spawned_sessions) == 1


@pytest.mark.asyncio
async def test_ensure_init_session_rejects_different_participant_for_same_conversation(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    await layer.ensure_init_session(
        conversation_id="conv_init",
        participant_id="part_init_a",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:init",
    )

    with pytest.raises(RuntimeError, match="existing init GOD identity"):
        await layer.ensure_init_session(
            conversation_id="conv_init",
            participant_id="part_init_b",
            agent=agent,
            worktree=tmp_path,
            model="gpt-5.5",
            prompt_fingerprint="sha256:init",
        )


@pytest.mark.asyncio
async def test_ensure_conversation_session_reuses_registry_record_after_restart(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "sessions.json"
    launcher = FakeLauncher()
    first_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    first = await first_layer.ensure_conversation_session(
        conversation_id="conv_restart",
        participant_id="part_architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
    )
    restarted_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )

    second = await restarted_layer.ensure_conversation_session(
        conversation_id="conv_restart",
        participant_id="part_architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
    )

    assert second.god_session_id == first.god_session_id
    assert second.session_address == first.session_address
    assert len(spawned_sessions) == 2


@pytest.mark.asyncio
async def test_ensure_conversation_session_respawns_dead_peer_with_same_handle(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    first = await layer.ensure_conversation_session(
        conversation_id="conv_review",
        participant_id="review-god",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
        feature_scope_id="feature-a",
    )
    spawned_sessions[0]._alive = False

    second = await layer.ensure_conversation_session(
        conversation_id="conv_review",
        participant_id="review-god",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
        feature_scope_id="feature-a",
    )

    assert second.god_session_id == first.god_session_id
    assert second.session_address == first.session_address
    assert len(spawned_sessions) == 2
    assert launcher.build_persistent_command_calls == [
        ("review", tmp_path),
        ("review", tmp_path),
    ]


@pytest.mark.asyncio
async def test_ensure_conversation_session_rejects_live_worktree_change(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    spawned_sessions: list[FakeSession] = []

    async def fake_spawn(command, env=None):
        session = FakeSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()
    first_worktree = tmp_path / "lane-1"
    second_worktree = tmp_path / "lane-2"

    first = await layer.ensure_conversation_session(
        conversation_id="conv_review",
        participant_id="review-god",
        role="review",
        agent=agent,
        worktree=first_worktree,
    )
    with pytest.raises(RuntimeError, match="existing live session"):
        await layer.ensure_conversation_session(
            conversation_id="conv_review",
            participant_id="review-god",
            role="review",
            agent=agent,
            worktree=second_worktree,
        )

    assert first.god_session_id
    assert len(spawned_sessions) == 1
    assert spawned_sessions[0].aborted is False
    assert launcher.build_persistent_command_calls == [("review", first_worktree)]
    assert launcher.build_command_calls == []


@pytest.mark.asyncio
async def test_ensure_conversation_session_rejects_registry_mismatch_before_spawn(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "sessions.json"
    first_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )

    async def fake_initial_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_initial_spawn,
    )
    await first_layer.ensure_conversation_session(
        conversation_id="conv_restart",
        participant_id="part_architect",
        role="architect",
        agent=_make_agent(),
        worktree=tmp_path,
    )

    restarted_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )
    spawned_after_restart = False

    async def fail_if_spawned(command, env=None):
        nonlocal spawned_after_restart
        spawned_after_restart = True
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fail_if_spawned,
    )
    mismatched_agent = AgentDescriptor(
        runtime=AgentRuntime.CLAUDE_CODE,
        name="reviewer",
        capabilities=["code"],
        session_config=SessionConfig(),
    )

    with pytest.raises(RuntimeError, match="existing registered session"):
        await restarted_layer.ensure_conversation_session(
            conversation_id="conv_restart",
            participant_id="part_architect",
            role="reviewer",
            agent=mismatched_agent,
            worktree=tmp_path,
        )

    assert spawned_after_restart is False


@pytest.mark.asyncio
async def test_ensure_conversation_session_rejects_peer_metadata_mismatch(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()

    await layer.ensure_conversation_session(
        conversation_id="conv_peer",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:one",
        feature_scope_id="feature-a",
    )

    with pytest.raises(RuntimeError, match="existing live session"):
        await layer.ensure_conversation_session(
            conversation_id="conv_peer",
            participant_id="part_review",
            role="review",
            agent=agent,
            worktree=tmp_path,
            model="gpt-5.4",
            prompt_fingerprint="sha256:one",
            feature_scope_id="feature-a",
        )


@pytest.mark.asyncio
async def test_ensure_conversation_session_rejects_none_expected_model_for_concrete_record(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "sessions.json"
    first_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    agent = _make_agent()
    await first_layer.ensure_conversation_session(
        conversation_id="conv_peer",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:one",
        feature_scope_id="feature-a",
    )
    restarted_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )

    with pytest.raises(RuntimeError, match="existing registered session"):
        await restarted_layer.ensure_conversation_session(
            conversation_id="conv_peer",
            participant_id="part_review",
            role="review",
            agent=agent,
            worktree=tmp_path,
            model=None,
            prompt_fingerprint="sha256:one",
            feature_scope_id="feature-a",
        )


def test_stdout_protocol_parses_top_level_request_id_only():
    parsed = parse_stdout_line('{"type":"result","request_id":"req-1","artifacts":{}}')
    artifact_only = parse_stdout_line(
        '{"type":"result","artifacts":{"request_id":"req-1"}}'
    )

    assert parsed is not None
    assert parsed.request_id == "req-1"
    assert artifact_only is not None
    assert artifact_only.request_id is None


def test_god_session_layer_exposes_launcher_persistent_model(tmp_path):
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )

    assert layer.persistent_model_for_runtime(AgentRuntime.CODEX) == "gpt-5.5"


@pytest.mark.asyncio
async def test_ensure_conversation_session_migrates_legacy_record_metadata(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "sessions.json"
    layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: FakeLauncher()},
    )
    legacy = layer._registry.create(
        role="review",
        agent_name="executor",
        runtime="codex",
        session_address="@conv_legacy:part_review",
        session_inbox_id="inbox-conv_legacy-part_review",
        conversation_id="conv_legacy",
        participant_id="part_review",
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv_legacy",
        participant_id="part_review",
        role="review",
        agent=_make_agent(),
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
        feature_scope_id="feature-a",
    )

    assert record.god_session_id == legacy.god_session_id
    reloaded = layer._registry.get(record.god_session_id)
    assert reloaded.model == "gpt-5.5"
    assert reloaded.prompt_fingerprint == "sha256:review"
    assert reloaded.worktree == str(tmp_path)
    assert reloaded.feature_scope_id == "feature-a"


@pytest.mark.asyncio
async def test_persistent_peer_uses_role_capability_and_stable_session_prompt(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _make_review_participant(tmp_path)
    worktree = tmp_path / "lane-review"
    layer = RecordingPeerSessionLayer()
    service = PersistentCliPeerService(db_path=db_path, session_layer=layer)

    first = await service.ensure_peer(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review lane one with req-1",
        session_prompt="stable review role prompt",
        worktree=worktree,
        feature_scope_id="feature-a",
    )
    second = await service.ensure_peer(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review lane two with req-2",
        session_prompt="stable review role prompt",
        worktree=worktree,
        feature_scope_id="feature-a",
    )

    assert first.god_session_id == second.god_session_id == "god-peer-1"
    assert first.worktree == second.worktree == str(worktree)
    assert len(layer.ensure_calls) == 2
    first_call = layer.ensure_calls[0]
    second_call = layer.ensure_calls[1]
    assert first_call["agent"].name == "Review GOD"
    assert first_call["agent"].capabilities == ["review"]
    assert second_call["agent"].capabilities == ["review"]
    assert first.prompt_fingerprint == second.prompt_fingerprint
    assert first_call["prompt_fingerprint"] == second_call["prompt_fingerprint"]
