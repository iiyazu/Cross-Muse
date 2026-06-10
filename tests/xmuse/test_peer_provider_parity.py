from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.ray_session_layer import RayGodSessionLayer
from xmuse_core.agents.registry import AgentDescriptor
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import _runtime_for_participant
from xmuse_core.providers.models import ProviderId, RiskTier, TaskCapability
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.feature_review_contracts import ProviderSessionBindingRecord


def test_participant_store_accepts_opencode_participants(tmp_path) -> None:
    store = ParticipantStore(tmp_path / "chat.db")
    _seed_conversation(tmp_path / "chat.db", "conv-opencode")

    participant = store.add(
        conversation_id="conv-opencode",
        role="architect",
        display_name="architect-open",
        cli_kind="opencode",
        model="gpt-oss",
    )

    assert participant.provider_id is ProviderId.OPENCODE
    assert participant.cli_kind == "opencode"
    assert store.get(participant.participant_id).provider_id is ProviderId.OPENCODE


def test_peer_scheduler_maps_opencode_participant_to_opencode_runtime(tmp_path) -> None:
    store = ParticipantStore(tmp_path / "chat.db")
    _seed_conversation(tmp_path / "chat.db", "conv-runtime")
    participant = store.add(
        conversation_id="conv-runtime",
        role="review",
        display_name="review-open",
        cli_kind="opencode",
        model="gpt-oss",
    )

    assert _runtime_for_participant(participant) == "opencode"


@pytest.mark.asyncio
async def test_god_session_layer_supports_opencode_persistent_peer_session(
    tmp_path,
    monkeypatch,
) -> None:
    sessions: list[DummyLocalSession] = []

    async def spawn(_command, env):
        session = DummyLocalSession(env=env)
        sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        spawn,
    )

    layer = GodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        launchers={"opencode": DummyLauncher("gpt-oss")},
    )
    record = await layer.ensure_conversation_session(
        conversation_id="conv-god",
        participant_id="part-open",
        role="architect",
        agent=AgentDescriptor(
            name="architect-open",
            runtime="opencode",
            capabilities=["architect"],
        ),
        worktree=tmp_path,
        model="gpt-oss",
    )

    assert record.runtime == "opencode"
    assert len(sessions) == 1
    assert layer.persistent_model_for_runtime("opencode") == "gpt-oss"


@pytest.mark.asyncio
async def test_ray_god_session_layer_supports_opencode_persistent_peer_session(tmp_path) -> None:
    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={"opencode": DummyLauncher("gpt-oss")},
        actor_factory=lambda **kwargs: DummyRayActor(**kwargs),
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv-ray",
        participant_id="part-open-ray",
        role="architect",
        agent=AgentDescriptor(
            name="architect-open-ray",
            runtime="opencode",
            capabilities=["architect"],
        ),
        worktree=tmp_path,
        model="gpt-oss",
    )

    assert record.runtime == "opencode"
    assert layer.persistent_model_for_runtime("opencode") == "gpt-oss"


def test_runner_provider_service_uses_opencode_runtime_and_rejects_resume_binding_for_it() -> None:
    service = RunnerProviderService(registry=DummyProviderRegistry())
    invocation = service.build_execution_invocation(
        lane_id="lane-open",
        prompt="Do peer work",
        workspace=Path("."),
        timeout_seconds=30,
        provider_profile_ref="opencode.default",
        risk_tier=RiskTier.MEDIUM,
    )

    assert invocation.provider_id is ProviderId.OPENCODE
    assert service.runtime_for_invocation(invocation) == "opencode"
    assert service.supports_explicit_session_resume(invocation) is False

    binding = ProviderSessionBindingRecord(
        binding_id="bind-open",
        god_session_id="god-open",
        provider=ProviderId.OPENCODE.value,
        provider_session_id="open-session-1",
        session_kind="exec",
        status="active",
        role="architect",
        model="gpt-oss",
        cwd=str(Path(".")),
        worktree=str(Path(".")),
        created_at="2026-06-04T00:00:00Z",
    )
    with pytest.raises(ValueError):
        service.build_command(invocation, provider_session_binding=binding)


def _seed_conversation(db_path: Path, conversation_id: str) -> None:
    from xmuse_core.chat.store import ChatStore

    store = ChatStore(db_path)
    with store._connect() as conn:
        conn.execute(
            "insert into conversations (id, title, created_at) values (?, ?, ?)",
            (conversation_id, conversation_id, "2026-06-04T00:00:00Z"),
        )

class DummyLauncher:
    supports_persistent_sessions = True

    def __init__(self, model: str) -> None:
        self.model = model

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return ["opencode", "--role", role, "--workspace", str(worktree)]

    def build_env(self, role: str) -> dict[str, str]:
        return {"XMUSE_ROLE": role}

    def persistent_model(self) -> str:
        return self.model


class DummyLocalSession:
    def __init__(self, *, env: dict[str, str]) -> None:
        self.env = env
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    async def abort(self) -> None:
        self._alive = False

    async def send_typed(self, *_args, **_kwargs) -> None:
        return None

    async def receive(self):
        return None


class DummyRayActor:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self._alive = False

    async def ensure_alive(self):
        self._alive = True
        return None

    async def get_info(self):
        return {"alive": self._alive}

    async def shutdown(self):
        self._alive = False
        return None


class DummyProviderProfile:
    provider_id = ProviderId.OPENCODE
    profile_id = "default"
    model_id = "gpt-oss"
    supports_persistent_sessions = False
    task_capabilities = {TaskCapability.LANE_COORDINATION}


class DummyProviderRegistry:
    def get(self, provider_profile_ref: str) -> DummyProviderProfile:
        if provider_profile_ref != "opencode.default":
            raise KeyError(provider_profile_ref)
        return DummyProviderProfile()
