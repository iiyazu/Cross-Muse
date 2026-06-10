from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Protocol

from xmuse_core.agents.protocol import StdoutMessage, format_stdin_message, parse_stdout_line


class GodTransport(Protocol):
    async def start(self) -> None: ...

    async def send_typed(self, msg_type: str, **kwargs: object) -> None: ...

    async def receive(self) -> StdoutMessage | None: ...

    async def shutdown(self) -> None: ...

    def get_info(self) -> dict[str, object]: ...


class ProcessJsonTransport:
    """Line-oriented xmuse JSON protocol over a subprocess.

    This is the legacy transport used by ``codex_persistent``.  It stays as a
    fallback while Ray-backed GOD sessions move toward Codex app-server.
    """

    def __init__(self, *, command: list[str], worktree: Path) -> None:
        self._command = list(command)
        self._worktree = worktree
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._worktree,
            env=os.environ.copy(),
        )

    async def send_typed(self, msg_type: str, **kwargs: object) -> None:
        await self.start()
        if self._process is None or self._process.stdin is None:
            return
        self._process.stdin.write(format_stdin_message(msg_type, **kwargs).encode())
        await self._process.stdin.drain()

    async def receive(self) -> StdoutMessage | None:
        await self.start()
        if self._process is None or self._process.stdout is None:
            return None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                return None
            decoded = line.decode(errors="replace").strip()
            if not decoded:
                continue
            return parse_stdout_line(decoded)

    async def shutdown(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            try:
                self._process.kill()
            except ProcessLookupError:
                return
            await self._process.wait()

    def get_info(self) -> dict[str, object]:
        return {
            "alive": self._process is not None and self._process.returncode is None,
            "pid": self._process.pid if self._process else None,
            "transport": "process-json",
        }


__all__ = ["GodTransport", "ProcessJsonTransport"]
