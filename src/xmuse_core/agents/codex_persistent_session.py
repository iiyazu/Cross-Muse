"""Minimal persistent Codex app-server session wrapper."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from xmuse_core.agents.codex_app_server_connection import AppServerEventStream
from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport
from xmuse_core.agents.codex_native_adapter import NativeInvokeResult
from xmuse_core.agents.protocol import StdoutMessage


class CodexAppServerSession:
    def __init__(self, transport: CodexAppServerTransport) -> None:
        self._transport = transport
        self._operation_lock = asyncio.Lock()
        self._room_turn_owns_lock = False
        self._native_turn_release_task: asyncio.Task[None] | None = None

    @classmethod
    async def spawn(cls, **transport_kwargs: Any) -> CodexAppServerSession:
        transport = CodexAppServerTransport(**transport_kwargs)
        await transport.start()
        return cls(transport)

    async def send(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            raise ValueError("Codex app-server session requires JSON messages") from exc
        if not isinstance(payload, dict):
            raise ValueError("Codex app-server session message must be an object")
        msg_type = str(payload.pop("type", "task"))
        await self.send_typed(msg_type, **payload)

    async def send_typed(self, msg_type: str, **kwargs: object) -> None:
        await self._operation_lock.acquire()
        self._room_turn_owns_lock = True
        try:
            await self._transport.assert_room_delivery_allowed()
            await self._transport.send_typed(msg_type, **kwargs)
        except BaseException:
            self._release_room_turn_lock()
            raise

    async def receive(self) -> StdoutMessage | None:
        try:
            return await self._transport.receive()
        finally:
            self._release_room_turn_lock()

    async def abort(self) -> None:
        await self._transport.shutdown()
        if self._native_turn_release_task is not None:
            self._native_turn_release_task.cancel()
            await asyncio.gather(self._native_turn_release_task, return_exceptions=True)
            self._native_turn_release_task = None
        self._release_room_turn_lock()

    async def native_snapshot(self) -> dict[str, object]:
        return await self._transport.native_snapshot()

    async def discover_native_capabilities(self) -> dict[str, object]:
        return await self._transport.discover_native_capabilities()

    async def invoke_native(
        self,
        capability_id: str,
        safe_request: dict[str, object],
        *,
        resolved_review_target: dict[str, object] | None = None,
    ) -> NativeInvokeResult:
        concurrent_capabilities = {
            "goal_get",
            "goal_pause",
            "models_list",
            "turn_steer",
            "turn_interrupt",
        }
        if capability_id in concurrent_capabilities:
            return await self._transport.invoke_native(
                capability_id,
                safe_request,
                resolved_review_target=resolved_review_target,
            )
        await self._operation_lock.acquire()
        try:
            result = await self._transport.invoke_native(
                capability_id,
                safe_request,
                resolved_review_target=resolved_review_target,
            )
        except BaseException:
            self._operation_lock.release()
            raise
        if result.private_active_turn_id is None:
            self._operation_lock.release()
        else:
            self._native_turn_release_task = asyncio.create_task(
                self._release_after_native_turn(),
                name="codex-native-turn-lock",
            )
        return result

    def subscribe_native_events(self) -> AppServerEventStream:
        return self._transport.subscribe_native_events()

    async def _release_after_native_turn(self) -> None:
        try:
            await self._transport.wait_native_idle()
        finally:
            if self._operation_lock.locked():
                self._operation_lock.release()
            self._native_turn_release_task = None

    def _release_room_turn_lock(self) -> None:
        if self._room_turn_owns_lock and self._operation_lock.locked():
            self._room_turn_owns_lock = False
            self._operation_lock.release()

    def is_alive(self) -> bool:
        return self._transport.get_info().get("alive") is True

    @property
    def provider_session_id(self) -> str | None:
        value = self._transport.get_info().get("thread_id")
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value or value.lower() in {"last", "--last", "latest", "--latest"}:
            return None
        return value

    @property
    def pid(self) -> int | None:
        value = self._transport.get_info().get("pid")
        return value if isinstance(value, int) and not isinstance(value, bool) else None
