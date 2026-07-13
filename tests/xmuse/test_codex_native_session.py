from __future__ import annotations

import asyncio

import pytest

from xmuse_core.agents.codex_native_adapter import NativeInvokeResult
from xmuse_core.agents.codex_native_contract import NativeInvocation
from xmuse_core.agents.codex_persistent_session import CodexAppServerSession
from xmuse_core.agents.protocol import StdoutMessage


class Transport:
    def __init__(self) -> None:
        self.idle = asyncio.Event()
        self.idle.set()
        self.room_started = asyncio.Event()
        self.aborted = False
        self.native_turn = False
        self.room_delivery_error: RuntimeError | None = None
        self.invocations: list[str] = []

    async def send_typed(self, _msg_type: str, **_kwargs: object) -> None:
        self.room_started.set()

    async def assert_room_delivery_allowed(self) -> None:
        if self.room_delivery_error is not None:
            raise self.room_delivery_error

    async def receive(self) -> StdoutMessage:
        return StdoutMessage(type="result", status="success", message="done")

    async def shutdown(self) -> None:
        self.aborted = True

    async def native_snapshot(self) -> dict[str, object]:
        return {"source": "codex_app_server"}

    async def discover_native_capabilities(self) -> dict[str, object]:
        return {"capabilities": []}

    async def invoke_native(
        self,
        capability_id: str,
        _safe_request: dict[str, object],
        *,
        resolved_review_target: dict[str, object] | None = None,
    ) -> NativeInvokeResult:
        del resolved_review_target
        self.invocations.append(capability_id)
        turn_id = "private-turn" if self.native_turn else None
        if turn_id is not None:
            self.idle.clear()
        return NativeInvokeResult(
            invocation=NativeInvocation(capability_id, "native/method", {}),
            safe_ack={"acknowledged": True},
            private_active_turn_id=turn_id,
        )

    async def wait_native_idle(self) -> None:
        await self.idle.wait()

    def get_info(self) -> dict[str, object]:
        return {"alive": True, "thread_id": "private", "pid": 1}


@pytest.mark.asyncio
async def test_snapshot_bypasses_active_room_turn_without_starting_another_turn() -> None:
    transport = Transport()
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]
    await session.send_typed("room_observation")
    native = asyncio.create_task(session.native_snapshot())
    await asyncio.sleep(0)
    assert native.done() is True

    result = await session.receive()
    assert result is not None
    assert result.message == "done"
    assert await native == {"source": "codex_app_server"}


@pytest.mark.asyncio
async def test_steer_and_interrupt_bypass_active_console_turn_lock() -> None:
    transport = Transport()
    transport.native_turn = True
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]
    await session.invoke_native("console_turn_start", {"text": "work"})

    steer = await asyncio.wait_for(
        session.invoke_native("turn_steer", {"text": "focus"}), timeout=0.1
    )
    interrupt = await asyncio.wait_for(session.invoke_native("turn_interrupt", {}), timeout=0.1)

    assert steer.invocation.capability_id == "turn_steer"
    assert interrupt.invocation.capability_id == "turn_interrupt"
    await session.abort()


@pytest.mark.asyncio
async def test_console_native_turn_holds_room_delivery_until_native_completion() -> None:
    transport = Transport()
    transport.native_turn = True
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]
    result = await session.invoke_native("console_turn_start", {"text": "work"})
    assert result.private_active_turn_id == "private-turn"
    room = asyncio.create_task(session.send_typed("room_observation"))
    await asyncio.sleep(0)
    assert room.done() is False

    transport.idle.set()
    await room
    assert transport.room_started.is_set()
    await session.receive()


@pytest.mark.asyncio
async def test_abort_releases_native_turn_lock_without_waiting_for_runtime() -> None:
    transport = Transport()
    transport.native_turn = True
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]
    await session.invoke_native("console_turn_start", {"text": "work"})

    await session.abort()

    assert transport.aborted is True


@pytest.mark.asyncio
async def test_rejected_room_delivery_releases_participant_operation_gate() -> None:
    transport = Transport()
    transport.room_delivery_error = RuntimeError("codex_native_room_delivery_conflict")
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="codex_native_room_delivery_conflict"):
        await session.send_typed("room_observation")

    result = await asyncio.wait_for(
        session.invoke_native("settings_update", {"model": "gpt-test"}),
        timeout=0.1,
    )
    assert result.invocation.capability_id == "settings_update"


@pytest.mark.asyncio
async def test_unrelated_mutation_waits_but_interrupt_remains_actionable() -> None:
    transport = Transport()
    transport.native_turn = True
    session = CodexAppServerSession(transport)  # type: ignore[arg-type]
    await session.invoke_native("console_turn_start", {"text": "work"})

    settings = asyncio.create_task(session.invoke_native("settings_update", {"model": "gpt-test"}))
    await asyncio.sleep(0)
    assert settings.done() is False

    interrupt = await asyncio.wait_for(
        session.invoke_native("turn_interrupt", {}),
        timeout=0.1,
    )
    assert interrupt.invocation.capability_id == "turn_interrupt"
    assert transport.invocations == ["console_turn_start", "turn_interrupt"]

    transport.idle.set()
    await settings
    assert transport.invocations[-1] == "settings_update"
