from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.agents.codex_native_adapter import NativeInvokeResult
from xmuse_core.agents.codex_native_contract import NativeInvocation
from xmuse_core.agents.god_session_layer import GodSessionLayer, LiveGodSession
from xmuse_core.agents.god_session_registry import GodSessionRecord


class Session:
    async def native_snapshot(self) -> dict[str, object]:
        return {"schema_version": "room_codex_native_snapshot/v1"}

    async def discover_native_capabilities(self) -> dict[str, object]:
        return {"schema_version": "room_codex_native_capabilities/v1"}

    async def invoke_native(
        self,
        capability_id: str,
        safe_request: dict[str, object],
        *,
        resolved_review_target: dict[str, object] | None = None,
    ) -> NativeInvokeResult:
        del safe_request, resolved_review_target
        return NativeInvokeResult(
            NativeInvocation(capability_id, "native/test", {}),
            {"acknowledged": True},
        )

    async def send(self, _message: str) -> None: ...

    async def send_typed(self, _msg_type: str, **_kwargs: object) -> None: ...

    async def receive(self):
        return None

    async def abort(self) -> None: ...

    def is_alive(self) -> bool:
        return True


def _layer(tmp_path: Path, runtime: str = "codex") -> GodSessionLayer:
    layer = GodSessionLayer(tmp_path / "god_sessions.json", {})
    record = GodSessionRecord(
        god_session_id="god-1",
        role="reviewer",
        agent_name="Reviewer",
        runtime=runtime,
        session_address="@room",
        session_inbox_id="inbox-room",
        status="running",
    )
    layer._live_sessions[record.god_session_id] = LiveGodSession(  # noqa: SLF001
        record=record,
        session=Session(),  # type: ignore[arg-type]
        worktree=tmp_path,
    )
    return layer


@pytest.mark.asyncio
async def test_layer_exposes_only_typed_native_adapter_operations(tmp_path: Path) -> None:
    layer = _layer(tmp_path)
    assert (await layer.native_snapshot("god-1"))["schema_version"].endswith("/v1")
    assert (await layer.discover_native_capabilities("god-1"))["schema_version"].endswith("/v1")
    result = await layer.invoke_native("god-1", "goal_get", {})
    assert result.invocation.method == "native/test"
    assert not hasattr(layer, "raw_native_rpc")


@pytest.mark.asyncio
async def test_layer_rejects_non_codex_live_session(tmp_path: Path) -> None:
    layer = _layer(tmp_path, runtime="mock")
    with pytest.raises(RuntimeError, match="runtime mismatch"):
        await layer.native_snapshot("god-1")
