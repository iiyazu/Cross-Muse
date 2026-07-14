import pytest

from xmuse_core.agents.codex_persistent_session import CodexAppServerSession
from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime


class FakeCodexSession:
    def __init__(self, thread_id="thread-1", alive=True, abort_error=None) -> None:
        self.provider_session_id, self._alive, self.aborted = thread_id, alive, False
        self.abort_error = abort_error

    def is_alive(self) -> bool:
        return self._alive

    async def abort(self) -> None:
        self.aborted, self._alive = True, False
        if self.abort_error:
            raise self.abort_error


class FakeCodexLauncher:
    supports_persistent_sessions = True

    def __init__(self, session: FakeCodexSession) -> None:
        self.session = session

    async def spawn_persistent_session(self, **kwargs) -> FakeCodexSession:
        return self.session


def _agent(runtime=AgentRuntime.CODEX) -> AgentDescriptor:
    return AgentDescriptor(runtime=runtime, name="codex", capabilities=[])


def _args() -> dict[str, object]:
    return {
        "conversation_id": "conv-1",
        "participant_id": "participant-1",
        "runtime": AgentRuntime.CODEX,
        "provider_session_kind": "codex_app_server_thread",
        "feature_scope_id": None,
    }


async def _spawn(layer, path, conversation="conv-1", runtime=AgentRuntime.CODEX):
    return await layer.ensure_conversation_session(
        conversation_id=conversation,
        participant_id="participant-1",
        role="review",
        agent=_agent(runtime),
        worktree=path,
    )


def _layer(path, session=None, runtime=AgentRuntime.CODEX) -> GodSessionLayer:
    launcher = FakeCodexLauncher(session or FakeCodexSession())
    return GodSessionLayer(path / "god.json", {runtime: launcher})


def _bind(registry, record, thread_id: str | None) -> None:
    registry.update_provider_binding(
        record.god_session_id,
        provider_session_id=thread_id,
        provider_session_kind="codex_app_server_thread" if thread_id else None,
        provider_binding_status="active" if thread_id else None,
        provider_binding_failure_reason=None,
    )


@pytest.mark.asyncio
async def test_codex_app_server_session_exposes_explicit_started_thread_id(monkeypatch):
    class Transport:
        async def start(self):
            pass

        def get_info(self):
            return {"thread_id": " started-thread "}

    monkeypatch.setattr(
        "xmuse_core.agents.codex_persistent_session.CodexAppServerTransport",
        Transport,
    )
    session = await CodexAppServerSession.spawn()
    assert session.provider_session_id == "started-thread"
    for value in "", "last", "latest", "--last", "--latest":
        session._transport.get_info = lambda value=value: {"thread_id": value}
        assert session.provider_session_id is None


@pytest.mark.asyncio
async def test_native_codex_spawn_persists_room_session_thread_binding(tmp_path):
    record = await _spawn(_layer(tmp_path), tmp_path)
    assert record.provider_session_id == "thread-1"
    assert record.provider_session_kind == "codex_app_server_thread"
    assert record.provider_binding_status == "active"
    other = await _spawn(_layer(tmp_path / "other", runtime="other"), tmp_path, runtime="other")
    assert (other.status, other.provider_session_id, other.provider_session_kind) == (
        "running",
        None,
        None,
    )
    assert other.provider_binding_status is None and other.provider_binding_failure_reason is None


@pytest.mark.asyncio
async def test_live_provider_binding_requires_exact_conversation_participant_and_thread(tmp_path):
    layer = _layer(tmp_path)
    record = await _spawn(layer, tmp_path)
    assert layer.require_live_provider_session_binding(**_args()) == record
    for key, value, prefix in (
        ("conversation_id", "other", "not_found"),
        ("participant_id", "other", "not_found"),
        ("feature_scope_id", "other", "not_found"),
        ("runtime", "other", "identity_mismatch"),
    ):
        with pytest.raises(RuntimeError, match=f"^provider_session_binding_{prefix}"):
            layer.require_live_provider_session_binding(**(_args() | {key: value}))
    duplicate = layer._registry.create(
        "review",
        "codex",
        "codex",
        "@two",
        "inbox-two",
        "conv-1",
        "participant-1",
    )
    assert duplicate.god_session_id
    with pytest.raises(RuntimeError, match="^provider_session_binding_ambiguous"):
        layer.require_live_provider_session_binding(**_args())


@pytest.mark.asyncio
async def test_live_provider_binding_rejects_missing_inactive_dead_or_mismatched_thread(tmp_path):
    layer = _layer(tmp_path)
    record = await _spawn(layer, tmp_path)
    registry, live = layer._registry, layer._live_sessions[record.god_session_id]
    _bind(registry, record, None)
    with pytest.raises(RuntimeError, match="provider_session_binding_inactive"):
        layer.require_live_provider_session_binding(**_args())
    _bind(registry, record, "thread-1")
    live.session._alive = False
    with pytest.raises(RuntimeError, match="provider_session_binding_not_live"):
        layer.require_live_provider_session_binding(**_args())
    live.session._alive, live.session.provider_session_id = True, "thread-2"
    with pytest.raises(RuntimeError, match="provider_session_binding_stale"):
        layer.require_live_provider_session_binding(**_args())
    live.session.provider_session_id = "thread-1"
    for field in "god_session_id conversation_id participant_id runtime feature_scope_id".split():
        value = getattr(live.record, field)
        setattr(live.record, field, "wrong")
        with pytest.raises(RuntimeError, match="^provider_session_binding_identity_mismatch"):
            layer.require_live_provider_session_binding(**_args())
        setattr(live.record, field, value)
    attachment = layer._live_sessions.pop(record.god_session_id)
    with pytest.raises(RuntimeError, match="^provider_session_binding_not_live"):
        layer.require_live_provider_session_binding(**_args())
    layer._live_sessions[record.god_session_id] = attachment


@pytest.mark.asyncio
async def test_live_provider_binding_rejects_cross_room_thread_reuse(tmp_path):
    layer = _layer(tmp_path)
    record = await _spawn(layer, tmp_path)
    registry = GodSessionRegistry(tmp_path / "god.json")
    other = registry.create(
        "review",
        "codex",
        "codex",
        "@other",
        "inbox-other",
        "conv-2",
        "participant-2",
    )
    registry.promote_running(other.god_session_id)
    _bind(registry, other, "thread-1")
    with pytest.raises(RuntimeError, match="provider_session_binding_cross_room"):
        layer.require_live_provider_session_binding(**_args())
    message = StdoutMessage(
        type="result",
        runtime="codex",
        artifacts={"provider_session_id": "thread-1"},
    )
    with pytest.raises(RuntimeError, match="^provider_session_binding_cross_room"):
        layer._persist_provider_binding_from_message(
            layer._live_sessions[record.god_session_id],
            message,
        )
    _bind(registry, other, None)
    assert layer.require_live_provider_session_binding(**_args()) == record
    _bind(registry, record, None)
    layer._live_sessions[record.god_session_id].record = registry.get(record.god_session_id)
    layer._persist_provider_binding_from_message(
        layer._live_sessions[record.god_session_id],
        message,
    )
    layer._live_sessions[record.god_session_id].session.provider_session_id = None
    with pytest.raises(RuntimeError, match="^provider_session_binding_stale"):
        layer.require_live_provider_session_binding(**_args())


@pytest.mark.asyncio
async def test_binding_persistence_failure_aborts_new_native_session(tmp_path, monkeypatch):
    session = FakeCodexSession(abort_error=RuntimeError("abort failed"))
    layer = _layer(tmp_path, session)

    def fail(*args, **kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(layer._registry, "update_provider_binding", fail)
    with pytest.raises(OSError, match="write failed"):
        await _spawn(layer, tmp_path)
    assert session.aborted and not layer._live_sessions
    record = layer._registry.list()
    assert (
        len(record) == 1
        and record[0].status == "starting"
        and record[0].provider_session_id is None
    )
    session, layer = FakeCodexSession(), _layer(tmp_path / "promotion")
    layer._launchers[AgentRuntime.CODEX].session = session
    monkeypatch.setattr(
        layer._registry,
        "promote_running",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("promote failed")),
    )
    with pytest.raises(OSError, match="promote failed"):
        await _spawn(layer, tmp_path)
    record = layer._registry.list()
    assert session.aborted and not layer._live_sessions and len(record) == 1
    assert record[0].status == "starting" and record[0].provider_session_id == "thread-1"


@pytest.mark.asyncio
async def test_god_session_layer_shutdown_aborts_owned_live_sessions(tmp_path):
    session = FakeCodexSession()
    layer = _layer(tmp_path, session)
    await _spawn(layer, tmp_path)

    await layer.shutdown()
    await layer.shutdown()

    assert session.aborted
    assert layer._live_sessions == {}
    assert layer._active_conversation_session_starts == set()
