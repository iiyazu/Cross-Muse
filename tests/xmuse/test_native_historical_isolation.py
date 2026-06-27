from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "platform_runner.py"


def _load_platform_runner():
    spec = importlib.util.spec_from_file_location("xmuse_platform_runner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_runner = _load_platform_runner()


class _FakeStateMachine:
    def get_lanes(self, status=None):
        return []


@pytest.mark.asyncio
async def test_runner_uses_native_peer_god_layer_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.delenv("XMUSE_PEER_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert type(captured["scheduler_kwargs"]["god_layer"]).__name__ == "GodSessionLayer"


@pytest.mark.asyncio
async def test_runner_can_force_native_peer_god_layer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "native")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    god_layer = captured["scheduler_kwargs"]["god_layer"]
    assert type(god_layer).__name__ == "GodSessionLayer"
    assert not hasattr(god_layer, "degraded_peer_runtime")
    assert not hasattr(god_layer, "degraded_peer_runtime_reason")


@pytest.mark.asyncio
async def test_runner_rejects_unknown_peer_backend_without_native_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("peer scheduler must not be built when backend is invalid")

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "mystery")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)

    with pytest.raises(RuntimeError, match="Unknown peer GOD backend"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            peer_chat_enabled=True,
        )


@pytest.mark.asyncio
async def test_runner_rejects_native_peer_fallback_when_ray_unavailable_without_degraded_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("peer scheduler must not be built when Ray is unavailable")

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        ray_session_layer_module,
        "RayGodSessionLayer",
        type(
            "BrokenRayLayer",
            (),
            {
                "__init__": lambda self, *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("ray unavailable")
                )
            },
        ),
    )

    with pytest.raises(RuntimeError, match="native fallback is disabled"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            peer_chat_enabled=True,
        )


@pytest.mark.asyncio
async def test_runner_marks_degraded_local_peer_fallback_when_ray_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", "1")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        ray_session_layer_module,
        "RayGodSessionLayer",
        type(
            "BrokenRayLayer",
            (),
            {
                "__init__": lambda self, *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("ray unavailable")
                )
            },
        ),
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    god_layer = captured["scheduler_kwargs"]["god_layer"]
    assert type(god_layer).__name__ == "GodSessionLayer"
    assert god_layer.degraded_peer_runtime == "native_exec_shim"
    assert god_layer.degraded_peer_runtime_reason == (
        "ray_unavailable_degraded_local_mode"
    )


@pytest.mark.asyncio
async def test_runner_marks_degraded_local_peer_fallback_when_ray_prewarm_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    async def failing_prewarm(self) -> None:
        raise RuntimeError("ray packaging failed during prewarm")

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", "1")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(ray_session_layer_module.RayGodSessionLayer, "prewarm", failing_prewarm)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    god_layer = captured["scheduler_kwargs"]["god_layer"]
    assert type(god_layer).__name__ == "GodSessionLayer"
    assert god_layer.degraded_peer_runtime == "native_exec_shim"
    assert god_layer.degraded_peer_runtime_reason == (
        "ray_unavailable_degraded_local_mode"
    )


@pytest.mark.asyncio
async def test_runner_rejects_native_peer_fallback_when_ray_prewarm_fails_without_degraded_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("peer scheduler must not be built after prewarm failure")

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    async def failing_prewarm(self) -> None:
        raise RuntimeError("ray packaging failed during prewarm")

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(ray_session_layer_module.RayGodSessionLayer, "prewarm", failing_prewarm)

    with pytest.raises(RuntimeError, match="native fallback is disabled"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            peer_chat_enabled=True,
        )
