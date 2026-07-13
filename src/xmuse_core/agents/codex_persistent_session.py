"""Minimal persistent Codex app-server session wrapper."""

from __future__ import annotations

import json
from typing import Any

from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport
from xmuse_core.agents.protocol import StdoutMessage


class CodexAppServerSession:
    def __init__(self, transport: CodexAppServerTransport) -> None:
        self._transport = transport

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
        await self._transport.send_typed(msg_type, **kwargs)

    async def receive(self) -> StdoutMessage | None:
        return await self._transport.receive()

    async def abort(self) -> None:
        await self._transport.shutdown()

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
