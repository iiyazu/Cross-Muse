from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import ray

from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport
from xmuse_core.agents.god_transport import GodTransport, ProcessJsonTransport
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.models import ChatInboxItem


class _RayGodActorCore:
    def __init__(
        self,
        *,
        god_id: str,
        role: str,
        display_name: str,
        model: str,
        command: list[str],
        db_path: str,
        worktree: str,
        transport_mode: str = "process",
        mcp_port: int = 8100,
        codex_command: str = "codex",
        reasoning_effort: str = "low",
        enable_mcp: bool = False,
        resume_thread_id: str | None = None,
        transport_factory: Callable[..., GodTransport] | None = None,
    ) -> None:
        self._god_id = god_id
        self._role = role
        self._display_name = display_name
        self._model = model
        self._command = command
        self._worktree = Path(worktree)
        self._db_path = Path(db_path)
        self._transport_mode = transport_mode
        self._mcp_port = mcp_port
        self._codex_command = codex_command
        self._reasoning_effort = reasoning_effort
        self._enable_mcp = enable_mcp
        self._resume_thread_id = resume_thread_id
        self._transport_factory = transport_factory
        self._transport: GodTransport | None = None
        self._started_at: str | None = None
        self._crash_count = 0

    def get_info(self) -> dict:
        transport_info = self._transport.get_info() if self._transport is not None else {}
        info = {
            "god_id": self._god_id,
            "role": self._role,
            "display_name": self._display_name,
            "model": self._model,
            "alive": bool(transport_info.get("alive")),
            "pid": transport_info.get("pid"),
            "transport": transport_info.get("transport", self._transport_mode),
            "started_at": self._started_at,
            "crash_count": self._crash_count,
        }
        for key in ("thread_id", "resume_thread_id"):
            if key in transport_info:
                info[key] = transport_info[key]
        return info

    async def ensure_alive(self) -> bool:
        if self._transport is not None and self._transport.get_info().get("alive"):
            return True
        self._transport = self._build_transport()
        await self._transport.start()
        self._started_at = datetime.now(UTC).isoformat()
        self._crash_count += 1
        return True

    async def send_typed(self, msg_type: str, **kwargs) -> None:
        await self.ensure_alive()
        if self._transport is not None:
            await self._transport.send_typed(msg_type, **kwargs)

    async def receive(self):
        await self.ensure_alive()
        if self._transport is None:
            return None
        return await self._transport.receive()

    async def chat_post_message(self, conversation_id: str, content: str) -> str:
        from xmuse_core.chat.store import ChatStore
        store = ChatStore(self._db_path)
        msg = store.add_message(
            conversation_id=conversation_id,
            author=self._god_id,
            role=self._role,
            content=content,
            mentions=[],
        )
        return msg.id

    async def chat_mention(self, conversation_id: str, content: str, target: str) -> str:
        inbox = ChatInboxStore(self._db_path)
        from xmuse_core.chat.store import ChatStore
        store = ChatStore(self._db_path)
        msg = store.add_message(
            conversation_id=conversation_id,
            author=self._god_id,
            role=self._role,
            content=content,
            mentions=[target],
        )
        inbox.create_item(
            conversation_id=conversation_id,
            target_participant_id=target,
            target_role=None,
            target_address=f"@{target}",
            sender_participant_id=self._god_id,
            sender_address=f"@{self._role}",
            source_message_id=msg.id,
            item_type="mention",
            payload={"content": content},
        )
        return msg.id

    async def check_inbox(self, conversation_id: str) -> list[ChatInboxItem]:
        inbox = ChatInboxStore(self._db_path)
        items = inbox.list_for_participant(
            conversation_id=conversation_id,
            participant_id=self._god_id,
            include_claimed=False,
        )
        return items

    async def mark_inbox_read(self, item_id: str) -> None:
        inbox = ChatInboxStore(self._db_path)
        inbox.mark_read(item_id)

    async def shutdown(self) -> None:
        if self._transport is not None:
            await self._transport.shutdown()

    def _build_transport(self) -> GodTransport:
        if self._transport_factory is not None:
            return self._transport_factory(
                god_id=self._god_id,
                role=self._role,
                display_name=self._display_name,
                model=self._model,
                command=self._command,
                db_path=str(self._db_path),
                worktree=str(self._worktree),
                transport_mode=self._transport_mode,
                mcp_port=self._mcp_port,
                codex_command=self._codex_command,
                reasoning_effort=self._reasoning_effort,
                enable_mcp=self._enable_mcp,
                resume_thread_id=self._resume_thread_id,
            )
        mode = self._transport_mode.strip().lower().replace("_", "-")
        if mode in {"app-server", "appserver", "codex-app-server"}:
            return CodexAppServerTransport(
                god_id=self._god_id,
                role=self._role,
                display_name=self._display_name,
                model=self._model,
                worktree=self._worktree,
                db_path=self._db_path,
                mcp_port=self._mcp_port,
                codex_command=self._codex_command,
                reasoning_effort=self._reasoning_effort,
                enable_mcp=self._enable_mcp,
                resume_thread_id=self._resume_thread_id,
            )
        return ProcessJsonTransport(command=self._command, worktree=self._worktree)


RayGodActor = ray.remote(_RayGodActorCore)


__all__ = ["RayGodActor", "_RayGodActorCore"]
