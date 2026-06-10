from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport
from xmuse_core.agents.ray_session_layer import RayGodSessionLayer
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime


class DummyLauncher:
    supports_persistent_sessions = True

    def __init__(self, model: str) -> None:
        self.model = model

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return ["codex", role, str(worktree)]

    def persistent_model(self) -> str:
        return self.model


class DummyProcess:
    def __init__(self) -> None:
        self.stdin = _DummyPipe()
        self.stdout = _DummyPipe()
        self.stderr = _DummyPipe()
        self.returncode = None
        self.pid = 1001

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return 0


class _DummyPipe:
    def write(self, _data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        return b""


class DummyRayActor:
    def __init__(
        self,
        *,
        info_thread_id: str | None,
        fail_on_send: bool = False,
        **kwargs,
    ) -> None:
        self.kwargs = kwargs
        self._alive = False
        self._fail_on_send = fail_on_send
        self._shutdown = False
        self.sent: list[tuple[str, dict[str, object]]] = []
        self._info_thread_id = info_thread_id

    async def ensure_alive(self):
        self._alive = True
        return None

    async def get_info(self):
        return {
            "alive": self._alive,
            "transport": "codex-app-server",
            "thread_id": self._info_thread_id,
        }

    async def send_typed(self, msg_type: str, **payload) -> None:
        if self._fail_on_send:
            raise RuntimeError("resume thread is stale")
        self.sent.append((msg_type, payload))

    async def receive(self):
        return None

    async def shutdown(self):
        self._shutdown = True
        self._alive = False
        return None


@pytest.mark.asyncio
async def test_codex_app_server_transport_resumes_thread_before_turn_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class CaptureTransport(CodexAppServerTransport):
        async def _request(self, method: str, params: dict[str, object]):
            requests.append((method, params))
            if method == "initialize":
                return {"ok": True}
            if method == "thread/start":
                return {"thread": {"id": "thread-new"}}
            if method == "thread/resume":
                return {"thread": {"id": "thread-resume-1"}}
            raise AssertionError(method)

        async def _send_request(self, method: str, params: dict[str, object]) -> int:
            requests.append((method, params))
            return 1

    transport = CaptureTransport(
        god_id="god-restart",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        worktree=tmp_path,
        resume_thread_id="thread-resume-1",
    )

    await transport.send_typed(
        "peer_chat_nudge",
        prompt="reply",
        context="{}",
        request_id="inbox-1",
    )

    assert requests[0][0] == "initialize"
    assert [method for method, _ in requests].count("thread/start") == 0
    assert requests[1][0] == "thread/resume"
    assert requests[1][1]["threadId"] == "thread-resume-1"
    assert requests[-1][0] == "turn/start"
    assert requests[-1][1]["threadId"] == "thread-resume-1"


@pytest.mark.asyncio
async def test_ray_session_layer_persists_provider_binding_and_uses_it_after_restart(
    tmp_path: Path,
) -> None:
    actors: list[DummyRayActor] = []

    def actor_factory(**kwargs):
        actor = DummyRayActor(info_thread_id="thread-1", **kwargs)
        actors.append(actor)
        return actor

    launcher = DummyLauncher("gpt-5.4")
    registry_path = tmp_path / "god_sessions.json"
    first_layer = RayGodSessionLayer(
        registry_path=registry_path,
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: launcher},
        actor_factory=actor_factory,
    )
    agent = AgentDescriptor(
        name="architect",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )

    first = await first_layer.ensure_conversation_session(
        conversation_id="conv-cross-restart",
        participant_id="part-architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    await first_layer.send_message(
        first.god_session_id,
        "peer_chat_nudge",
        prompt="hello",
        context="{}",
        request_id="req-1",
    )

    restarted_layer = RayGodSessionLayer(
        registry_path=registry_path,
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: launcher},
        actor_factory=actor_factory,
    )
    second = await restarted_layer.ensure_conversation_session(
        conversation_id="conv-cross-restart",
        participant_id="part-architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )

    assert second.god_session_id == first.god_session_id
    reloaded = restarted_layer._registry.get(first.god_session_id)
    assert reloaded.provider_session_id == "thread-1"
    assert reloaded.provider_session_kind == "codex_app_server_thread"
    assert reloaded.provider_binding_status == "active"
    assert actors[1].kwargs["resume_thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_ray_session_layer_reuses_live_provider_thread_across_turns_for_same_god(
    tmp_path: Path,
) -> None:
    actors: list[DummyRayActor] = []

    def actor_factory(**kwargs):
        actor = DummyRayActor(info_thread_id="thread-architect-live", **kwargs)
        actors.append(actor)
        return actor

    launcher = DummyLauncher("gpt-5.4")
    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: launcher},
        actor_factory=actor_factory,
    )
    agent = AgentDescriptor(
        name="architect",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )

    first = await layer.ensure_conversation_session(
        conversation_id="conv-live-reuse",
        participant_id="part-architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    await layer.send_message(
        first.god_session_id,
        "peer_chat_nudge",
        prompt="first",
        context="{}",
        request_id="req-1",
    )
    second = await layer.ensure_conversation_session(
        conversation_id="conv-live-reuse",
        participant_id="part-architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    await layer.send_message(
        second.god_session_id,
        "peer_chat_nudge",
        prompt="second",
        context="{}",
        request_id="req-2",
    )

    assert second.god_session_id == first.god_session_id
    assert len(actors) == 1
    assert len(actors[0].sent) == 2
    reloaded = layer._registry.get(first.god_session_id)
    assert reloaded.provider_session_id == "thread-architect-live"
    assert reloaded.provider_binding_status == "active"


@pytest.mark.asyncio
async def test_ray_session_layer_keeps_provider_bindings_isolated_by_participant(
    tmp_path: Path,
) -> None:
    actors: list[DummyRayActor] = []

    def actor_factory(**kwargs):
        thread_id = f"thread-{kwargs['role']}"
        actor = DummyRayActor(info_thread_id=thread_id, **kwargs)
        actors.append(actor)
        return actor

    launcher = DummyLauncher("gpt-5.4")

    def build_layer() -> RayGodSessionLayer:
        return RayGodSessionLayer(
            registry_path=tmp_path / "god_sessions.json",
            db_path=tmp_path / "chat.db",
            launchers={AgentRuntime.CODEX: launcher},
            actor_factory=actor_factory,
        )

    first_layer = build_layer()
    architect_agent = AgentDescriptor(
        name="architect",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )
    review_agent = AgentDescriptor(
        name="review",
        runtime=AgentRuntime.CODEX,
        capabilities=["review"],
    )

    architect = await first_layer.ensure_conversation_session(
        conversation_id="conv-binding-isolation",
        participant_id="part-architect",
        role="architect",
        agent=architect_agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    review = await first_layer.ensure_conversation_session(
        conversation_id="conv-binding-isolation",
        participant_id="part-review",
        role="review",
        agent=review_agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )

    first_registry = first_layer._registry
    assert first_registry.get(architect.god_session_id).provider_session_id == (
        "thread-architect"
    )
    assert first_registry.get(review.god_session_id).provider_session_id == "thread-review"

    restarted_layer = build_layer()
    await restarted_layer.ensure_conversation_session(
        conversation_id="conv-binding-isolation",
        participant_id="part-architect",
        role="architect",
        agent=architect_agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    await restarted_layer.ensure_conversation_session(
        conversation_id="conv-binding-isolation",
        participant_id="part-review",
        role="review",
        agent=review_agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )

    assert actors[-2].kwargs["resume_thread_id"] == "thread-architect"
    assert actors[-1].kwargs["resume_thread_id"] == "thread-review"
    assert actors[-2].kwargs["resume_thread_id"] != actors[-1].kwargs["resume_thread_id"]


@pytest.mark.asyncio
async def test_ray_session_layer_marks_stale_binding_and_falls_back_to_fresh_actor(
    tmp_path: Path,
) -> None:
    actors: list[DummyRayActor] = []

    def actor_factory(**kwargs):
        fail_on_send = len(actors) == 0
        thread_id = "thread-old" if fail_on_send else "thread-new"
        if len(actors) == 1:
            stale = layer._registry.get(record.god_session_id)
            assert stale.provider_session_id is None
            assert stale.provider_binding_status == "stale"
            assert stale.provider_binding_failure_reason == "resume thread is stale"
        actor = DummyRayActor(
            info_thread_id=thread_id,
            fail_on_send=fail_on_send,
            **kwargs,
        )
        actors.append(actor)
        return actor

    launcher = DummyLauncher("gpt-5.4")
    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: launcher},
        actor_factory=actor_factory,
    )
    agent = AgentDescriptor(
        name="architect",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )
    record = layer._registry.create(
        role="architect",
        agent_name="architect",
        runtime="codex",
        session_address="@conv_restart:part_architect",
        session_inbox_id="inbox-conv_restart-part_architect",
        conversation_id="conv_restart",
        participant_id="part_architect",
        model="gpt-5.4",
        worktree=str(tmp_path),
    )
    layer._registry.update_provider_binding(
        record.god_session_id,
        provider_session_id="thread-old",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )

    await layer.ensure_conversation_session(
        conversation_id="conv_restart",
        participant_id="part_architect",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
    )
    await layer.send_message(
        record.god_session_id,
        "peer_chat_nudge",
        prompt="resume me",
        context="{}",
        request_id="req-1",
    )

    reloaded = layer._registry.get(record.god_session_id)
    assert actors[0].kwargs["resume_thread_id"] == "thread-old"
    assert "resume_thread_id" not in actors[1].kwargs
    assert actors[0]._shutdown is True
    assert reloaded.provider_session_id == "thread-new"
    assert reloaded.provider_binding_status == "active"
    assert reloaded.provider_binding_failure_reason is None
