from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage, parse_stdout_line
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime, SessionConfig


class FakeSession:
    def __init__(self, alive: bool = True, pid: int | None = None) -> None:
        self._alive = alive
        self.pid = pid
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


class ProviderSessionAwareLauncher(FakeLauncher):
    def __init__(self) -> None:
        super().__init__()
        self.build_persistent_command_calls: list[tuple[str, Path, str | None]] = []

    def build_persistent_command(
        self,
        role: str,
        worktree: Path,
        *,
        provider_session_id: str | None = None,
    ) -> list[str]:
        self.build_persistent_command_calls.append((role, worktree, provider_session_id))
        command = ["fake-persistent-agent", role, str(worktree)]
        if provider_session_id is not None:
            command.extend(["--session-id", provider_session_id])
        return command


class ModelAwareLauncher(FakeLauncher):
    def __init__(self) -> None:
        super().__init__()
        self.build_persistent_command_calls: list[tuple[str, Path, str | None]] = []

    def build_persistent_command(
        self,
        role: str,
        worktree: Path,
        *,
        model: str | None = None,
    ) -> list[str]:
        self.build_persistent_command_calls.append((role, worktree, model))
        command = ["fake-persistent-agent", role, str(worktree)]
        if model is not None:
            command.extend(["--model", model])
        return command


class NativeSessionLauncher(FakeLauncher):
    def __init__(self) -> None:
        super().__init__()
        self.spawn_persistent_session_calls: list[dict[str, object]] = []

    async def spawn_persistent_session(
        self,
        *,
        role: str,
        worktree: Path,
        model: str | None = None,
        provider_session_id: str | None = None,
        db_path: Path | None = None,
    ) -> FakeSession:
        self.spawn_persistent_session_calls.append(
            {
                "role": role,
                "worktree": worktree,
                "model": model,
                "provider_session_id": provider_session_id,
                "db_path": db_path,
            }
        )
        return FakeSession(pid=4242)


@pytest.mark.asyncio
async def test_force_rebind_replaces_dead_conversation_session_without_new_identity(tmp_path):
    launcher = NativeSessionLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    agent = AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="room-codex",
        capabilities=["review"],
    )

    first = await layer.ensure_conversation_session(
        conversation_id="conv_rebind",
        participant_id="part_rebind",
        role="review",
        agent=agent,
        worktree=tmp_path,
        feature_scope_id="room_v1",
    )
    old_session = layer._live_sessions[first.god_session_id].session
    old_session._alive = False  # type: ignore[attr-defined]

    second = await layer.ensure_conversation_session(
        conversation_id="conv_rebind",
        participant_id="part_rebind",
        role="review",
        agent=agent,
        worktree=tmp_path,
        feature_scope_id="room_v1",
        force_rebind=True,
    )

    assert second.god_session_id == first.god_session_id
    assert old_session.aborted is True  # type: ignore[attr-defined]
    assert len(launcher.spawn_persistent_session_calls) == 2


@pytest.mark.asyncio
async def test_normal_and_force_rebind_share_one_identity_lock(tmp_path):
    launcher = SlowNativeSessionLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    agent = AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="room-codex",
        capabilities=["review"],
    )
    arguments = {
        "conversation_id": "conv_parallel_rebind",
        "participant_id": "part_parallel_rebind",
        "role": "review",
        "agent": agent,
        "worktree": tmp_path,
        "feature_scope_id": "room_v1",
    }

    normal, forced = await asyncio.gather(
        layer.ensure_conversation_session(**arguments),
        layer.ensure_conversation_session(**arguments, force_rebind=True),
    )

    live = layer._live_sessions[normal.god_session_id].session
    assert forced.god_session_id == normal.god_session_id
    assert live.aborted is False  # type: ignore[attr-defined]
    assert len(launcher.spawn_persistent_session_calls) == 1


@pytest.mark.asyncio
async def test_late_force_rebind_reuses_new_healthy_incarnation(tmp_path):
    launcher = NativeSessionLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    agent = AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="room-codex",
        capabilities=["review"],
    )
    arguments = {
        "conversation_id": "conv_late_rebind",
        "participant_id": "part_late_rebind",
        "role": "review",
        "agent": agent,
        "worktree": tmp_path,
        "feature_scope_id": "room_v1",
    }

    first = await layer.ensure_conversation_session(**arguments)
    incarnation = layer.native_session_incarnation(first.god_session_id)
    second = await layer.ensure_conversation_session(**arguments, force_rebind=True)

    live = layer._live_sessions[first.god_session_id].session
    assert second.god_session_id == first.god_session_id
    assert layer.native_session_incarnation(second.god_session_id) == incarnation
    assert live.aborted is False  # type: ignore[attr-defined]
    assert len(launcher.spawn_persistent_session_calls) == 1


@pytest.mark.asyncio
async def test_late_abort_does_not_remove_new_healthy_incarnation(tmp_path):
    launcher = NativeSessionLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    agent = AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="room-codex",
        capabilities=["review"],
    )
    arguments = {
        "conversation_id": "conv_late_abort",
        "participant_id": "part_late_abort",
        "role": "review",
        "agent": agent,
        "worktree": tmp_path,
        "feature_scope_id": "room_v1",
    }
    first = await layer.ensure_conversation_session(**arguments)
    old_session = layer._live_sessions[first.god_session_id].session
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_abort() -> None:
        old_session.aborted = True  # type: ignore[attr-defined]
        old_session._alive = False  # type: ignore[attr-defined]
        entered.set()
        await release.wait()

    old_session.abort = slow_abort  # type: ignore[method-assign]
    abort_task = asyncio.create_task(layer.abort_session(first.god_session_id))
    await entered.wait()

    second = await layer.ensure_conversation_session(**arguments)
    replacement = layer._live_sessions[second.god_session_id].session
    replacement_incarnation = layer.native_session_incarnation(second.god_session_id)
    release.set()
    await abort_task

    assert second.god_session_id == first.god_session_id
    assert layer._live_sessions[second.god_session_id].session is replacement
    assert layer.native_session_incarnation(second.god_session_id) == replacement_incarnation
    assert replacement is not old_session
    assert replacement.is_alive()


class SlowNativeSessionLauncher(NativeSessionLauncher):
    async def spawn_persistent_session(
        self,
        *,
        role: str,
        worktree: Path,
        model: str | None = None,
        provider_session_id: str | None = None,
        db_path: Path | None = None,
    ) -> FakeSession:
        await asyncio.sleep(0.01)
        return await super().spawn_persistent_session(
            role=role,
            worktree=worktree,
            model=model,
            provider_session_id=provider_session_id,
            db_path=db_path,
        )


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
async def test_ensure_session_prefers_provider_native_session_factory(
    tmp_path,
    monkeypatch,
):
    launcher = NativeSessionLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fail_spawn(command, env=None):
        raise AssertionError("provider-native session factory should be used")

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fail_spawn,
    )

    record = await layer.ensure_session(
        role="architect",
        agent=_make_agent(),
        worktree=tmp_path,
    )

    assert record.pid == 4242
    assert launcher.spawn_persistent_session_calls == [
        {
            "role": "architect",
            "worktree": tmp_path,
            "model": None,
            "provider_session_id": None,
            "db_path": tmp_path / "chat.db",
        }
    ]
    assert launcher.build_persistent_command_calls == []
    assert launcher.build_env_calls == []


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
        runtime="future_cli",
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
async def test_ensure_conversation_session_records_running_pid(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    registry_path = tmp_path / "god_sessions.json"
    layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fake_spawn(command, env=None):
        return FakeSession(pid=4242)

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv_architect",
        participant_id="architect-god",
        role="architect",
        agent=_make_agent(),
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:architect",
    )

    assert record.status == "running"
    assert record.pid == 4242
    reloaded = GodSessionRegistry(registry_path).get(record.god_session_id)
    assert reloaded.status == "running"
    assert reloaded.pid == 4242


@pytest.mark.asyncio
async def test_ensure_conversation_session_deduplicates_concurrent_spawn(tmp_path):
    launcher = SlowNativeSessionLauncher()
    registry_path = tmp_path / "god_sessions.json"
    layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )

    first, second = await asyncio.gather(
        layer.ensure_conversation_session(
            conversation_id="conv_parallel",
            participant_id="architect-god",
            role="architect",
            agent=_make_agent(),
            worktree=tmp_path,
            model="gpt-5.5",
            prompt_fingerprint="sha256:architect",
        ),
        layer.ensure_conversation_session(
            conversation_id="conv_parallel",
            participant_id="architect-god",
            role="architect",
            agent=_make_agent(),
            worktree=tmp_path,
            model="gpt-5.5",
            prompt_fingerprint="sha256:architect",
        ),
    )

    assert first.god_session_id == second.god_session_id
    assert launcher.spawn_persistent_session_calls == [
        {
            "role": "architect",
            "worktree": tmp_path,
            "model": "gpt-5.5",
            "provider_session_id": None,
            "db_path": tmp_path / "chat.db",
        }
    ]
    assert len(GodSessionRegistry(registry_path).list()) == 1


@pytest.mark.asyncio
async def test_ensure_conversation_session_passes_peer_model_to_persistent_command(
    tmp_path,
    monkeypatch,
):
    launcher = ModelAwareLauncher()
    spawned_commands: list[list[str]] = []
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )

    async def fake_spawn(command, env=None):
        spawned_commands.append(command)
        return FakeSession(pid=4242)

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    await layer.ensure_conversation_session(
        conversation_id="conv_builder",
        participant_id="builder-god",
        role="execute",
        agent=_make_agent(),
        worktree=tmp_path,
        model="gpt-5.4-mini",
        prompt_fingerprint="sha256:builder",
    )

    assert launcher.build_persistent_command_calls == [("execute", tmp_path, "gpt-5.4-mini")]
    assert spawned_commands == [
        ["fake-persistent-agent", "execute", str(tmp_path), "--model", "gpt-5.4-mini"]
    ]


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
async def test_receive_message_persists_codex_provider_session_id(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={AgentRuntime.CODEX: launcher},
    )
    session = FakeSession()
    session.received_messages.append(
        StdoutMessage(
            type="result",
            runtime="codex",
            status="success",
            artifacts={"provider_session_id": " provider_thread_123 "},
        )
    )

    async def fake_spawn(command, env=None):
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv_codex",
        participant_id="part_review",
        role="review",
        agent=AgentDescriptor(
            runtime=AgentRuntime.CODEX,
            name="review-codex-god",
            capabilities=["review"],
        ),
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
    )

    message = await layer.receive_message(record.god_session_id)

    assert isinstance(message, StdoutMessage)
    reloaded = layer._registry.get(record.god_session_id)
    assert reloaded.provider_session_id == "provider_thread_123"
    assert reloaded.provider_session_kind == "codex_app_server_thread"
    assert reloaded.provider_binding_status == "active"
    assert reloaded.provider_binding_failure_reason is None


@pytest.mark.asyncio
async def test_receive_message_ignores_future_provider_session_artifact(
    tmp_path,
    monkeypatch,
):
    launcher = FakeLauncher()
    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={"future_cli": launcher},
    )
    session = FakeSession()
    session.received_messages.append(
        StdoutMessage(
            type="result",
            runtime="future_cli",
            status="success",
            artifacts={"provider_session_id": "future_thread_123"},
        )
    )

    async def fake_spawn(command, env=None):
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv_future",
        participant_id="part_review",
        role="review",
        agent=AgentDescriptor(
            runtime="future_cli",
            name="review-future-cli-god",
            capabilities=["review"],
        ),
        worktree=tmp_path,
        model="future-cli-model",
        prompt_fingerprint="sha256:review",
    )

    message = await layer.receive_message(record.god_session_id)

    assert isinstance(message, StdoutMessage)
    reloaded = layer._registry.get(record.god_session_id)
    assert reloaded.provider_session_id is None
    assert reloaded.provider_session_kind is None
    assert reloaded.provider_binding_status is None
    assert reloaded.provider_binding_failure_reason is None


@pytest.mark.asyncio
async def test_ensure_conversation_session_resumes_active_codex_provider_session(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "god_sessions.json"
    first_launcher = FakeLauncher()
    first_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: first_launcher},
    )
    session = FakeSession()
    session.received_messages.append(
        StdoutMessage(
            type="result",
            runtime="codex",
            status="success",
            artifacts={"provider_session_id": "provider_thread_resume"},
        )
    )
    spawned_commands: list[list[str]] = []

    async def first_spawn(command, env=None):
        spawned_commands.append(command)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        first_spawn,
    )
    agent = AgentDescriptor(
        runtime=AgentRuntime.CODEX,
        name="review-codex-god",
        capabilities=["review"],
    )

    first = await first_layer.ensure_conversation_session(
        conversation_id="conv_codex_restart",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
    )
    await first_layer.receive_message(first.god_session_id)

    restart_launcher = ProviderSessionAwareLauncher()
    restarted_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: restart_launcher},
    )

    async def restart_spawn(command, env=None):
        spawned_commands.append(command)
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        restart_spawn,
    )

    second = await restarted_layer.ensure_conversation_session(
        conversation_id="conv_codex_restart",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.5",
        prompt_fingerprint="sha256:review",
    )

    assert second.god_session_id == first.god_session_id
    assert restart_launcher.build_persistent_command_calls == [
        ("review", tmp_path, "provider_thread_resume")
    ]
    assert spawned_commands[-1][-2:] == ["--session-id", "provider_thread_resume"]


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
async def test_feature_scoped_conversation_session_does_not_reuse_peer_chat_session(
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
    peer_chat_worktree = tmp_path / "peer-chat"
    lane_review_worktree = tmp_path / "lane-review"

    peer_chat = await layer.ensure_conversation_session(
        conversation_id="conv_review",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=peer_chat_worktree,
        model="gpt-5.5",
        prompt_fingerprint="sha256:peer-chat",
        feature_scope_id=None,
    )
    lane_review = await layer.ensure_conversation_session(
        conversation_id="conv_review",
        participant_id="part_review",
        role="review",
        agent=agent,
        worktree=lane_review_worktree,
        model="gpt-5.5",
        prompt_fingerprint="sha256:lane-review",
        feature_scope_id="feature-a",
    )

    assert lane_review.god_session_id != peer_chat.god_session_id
    assert lane_review.session_address != peer_chat.session_address
    assert lane_review.session_inbox_id != peer_chat.session_inbox_id
    assert lane_review.feature_scope_id == "feature-a"
    assert peer_chat.feature_scope_id is None
    assert len(spawned_sessions) == 2
    assert spawned_sessions[0].aborted is False
    assert launcher.build_persistent_command_calls == [
        ("review", peer_chat_worktree),
        ("review", lane_review_worktree),
    ]


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
        runtime="future_cli",
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
    artifact_only = parse_stdout_line('{"type":"result","artifacts":{"request_id":"req-1"}}')

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
async def test_ensure_conversation_session_migrates_bootstrap_record_with_model_only(
    tmp_path,
    monkeypatch,
):
    registry_path = tmp_path / "sessions.json"
    layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={"future_cli": FakeLauncher()},
    )
    bootstrap = layer._registry.create(
        role="review",
        agent_name="review-future-cli-god",
        runtime="future_cli",
        session_address="@conv_boot:part_review",
        session_inbox_id="inbox-conv_boot-part_review",
        conversation_id="conv_boot",
        participant_id="part_review",
        model="future-cli-model",
    )

    async def fake_spawn(command, env=None):
        return FakeSession()

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv_boot",
        participant_id="part_review",
        role="review",
        agent=AgentDescriptor(
            runtime="future_cli",
            name="review-future-cli-god",
            capabilities=["review"],
        ),
        worktree=tmp_path,
        model="future-cli-model",
        prompt_fingerprint="sha256:review-future-cli",
        feature_scope_id=None,
    )

    assert record.god_session_id == bootstrap.god_session_id
    reloaded = layer._registry.get(record.god_session_id)
    assert reloaded.model == "future-cli-model"
    assert reloaded.prompt_fingerprint == "sha256:review-future-cli"
    assert reloaded.worktree == str(tmp_path)
    assert reloaded.feature_scope_id is None
