from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

JSON_OBJECT_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_EVENT_QUEUE_SIZE = 512
STDERR_TAIL_BYTES = 16 * 1024


class AppServerConnectionError(RuntimeError):
    """A stable, content-free app-server connection failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Readable(Protocol):
    async def readline(self) -> bytes: ...


class _Writable(Protocol):
    def write(self, data: bytes) -> object: ...

    async def drain(self) -> object: ...

    def close(self) -> object: ...


class AppServerProcess(Protocol):
    stdin: _Writable | None
    stdout: _Readable | None
    stderr: _Readable | None
    pid: int
    returncode: int | None

    def terminate(self) -> object: ...

    def kill(self) -> object: ...

    async def wait(self) -> int: ...


@dataclass(frozen=True, slots=True)
class AppServerRequest:
    request_id: int
    response: asyncio.Future[object]


@dataclass(frozen=True, slots=True)
class _PendingRequest:
    response: asyncio.Future[object]
    method: str
    requested_thread_id: str | None


class AppServerEventStream:
    """A bounded, connection-owned notification subscription."""

    def __init__(
        self,
        connection: CodexAppServerConnection,
        queue: asyncio.Queue[dict[str, object] | AppServerConnectionError],
        turn_id: str | None,
    ) -> None:
        self._connection = connection
        self._queue = queue
        self._turn_id = turn_id
        self._closed = False

    async def receive(self) -> dict[str, object]:
        item = await self._queue.get()
        if isinstance(item, AppServerConnectionError):
            raise item
        return item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connection._remove_stream(self._queue, self._turn_id)


class CodexAppServerConnection:
    """Sole reader and serialized writer for one app-server generation."""

    def __init__(
        self,
        process: asyncio.subprocess.Process | AppServerProcess,
        *,
        generation: int,
        event_queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
        owns_process_group: bool = True,
    ) -> None:
        if generation < 1:
            raise ValueError("generation must be positive")
        if event_queue_size < 1:
            raise ValueError("event_queue_size must be positive")
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise AppServerConnectionError("codex_app_server_stream_unavailable")
        self._process = process
        self._generation = generation
        self._event_queue_size = event_queue_size
        self._owns_process_group = owns_process_group
        self._write_lock = asyncio.Lock()
        self._next_request_id = 1
        self._pending: dict[int, _PendingRequest] = {}
        self._streams: set[asyncio.Queue[dict[str, object] | AppServerConnectionError]] = set()
        self._turn_streams: dict[
            str, set[asyncio.Queue[dict[str, object] | AppServerConnectionError]]
        ] = {}
        self._stderr_hash = hashlib.sha256()
        self._stderr_tail: deque[int] = deque(maxlen=STDERR_TAIL_BYTES)
        self._stderr_bytes = 0
        self._terminal: AppServerConnectionError | None = None
        self._closed = False
        self._stdout_task = asyncio.create_task(self._read_stdout(), name="codex-app-server-stdout")
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(), name="codex-app-server-stderr"
        )

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def terminal_code(self) -> str | None:
        return self._terminal.code if self._terminal is not None else None

    async def request(self, method: str, params: Mapping[str, object]) -> object:
        pending = await self.start_request(method, params)
        return await pending.response

    async def start_request(self, method: str, params: Mapping[str, object]) -> AppServerRequest:
        if not isinstance(method, str) or not method or not isinstance(params, Mapping):
            raise ValueError("invalid app-server request")
        self._raise_if_terminal()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()
        async with self._write_lock:
            self._raise_if_terminal()
            request_id = self._next_request_id
            self._next_request_id += 1
            requested_thread_id = None
            if method == "thread/resume":
                raw_thread_id = params.get("threadId")
                if isinstance(raw_thread_id, str) and raw_thread_id:
                    requested_thread_id = raw_thread_id
            self._pending[request_id] = _PendingRequest(
                response=future,
                method=method,
                requested_thread_id=requested_thread_id,
            )
            try:
                await self._write_json({"id": request_id, "method": method, "params": dict(params)})
            except BaseException:
                self._pending.pop(request_id, None)
                if not future.done():
                    future.set_exception(AppServerConnectionError("codex_app_server_write_failed"))
                await self._fail("codex_app_server_write_failed")
                raise
        return AppServerRequest(request_id=request_id, response=future)

    def subscribe(self, *, turn_id: str | None = None) -> AppServerEventStream:
        self._raise_if_terminal()
        if turn_id is not None and (not isinstance(turn_id, str) or not turn_id.strip()):
            raise ValueError("turn_id must be non-empty")
        queue: asyncio.Queue[dict[str, object] | AppServerConnectionError] = asyncio.Queue(
            maxsize=self._event_queue_size
        )
        if turn_id is None:
            self._streams.add(queue)
        else:
            self._turn_streams.setdefault(turn_id, set()).add(queue)
        return AppServerEventStream(self, queue, turn_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._fail("codex_app_server_closed")
        current = asyncio.current_task()
        for task in (self._stdout_task, self._stderr_task):
            if task is not current and not task.done():
                task.cancel()
        stdin = self._process.stdin
        if stdin is not None:
            try:
                stdin.close()
            except (OSError, RuntimeError):
                pass
        await self._stop_process()
        await asyncio.gather(self._stdout_task, self._stderr_task, return_exceptions=True)

    def stderr_evidence(self) -> tuple[str, int, bytes]:
        """Return private diagnostic evidence; callers must not project its tail."""

        return (
            f"sha256:{self._stderr_hash.hexdigest()}",
            self._stderr_bytes,
            bytes(self._stderr_tail),
        )

    async def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    await self._fail("codex_app_server_exited")
                    return
                if len(line) > JSON_OBJECT_LIMIT_BYTES:
                    await self._fail("codex_app_server_message_too_large")
                    return
                try:
                    raw = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._fail("codex_app_server_malformed_json")
                    return
                if not isinstance(raw, dict):
                    await self._fail("codex_app_server_future_schema")
                    return
                message = cast(dict[str, object], raw)
                if "id" in message and "method" not in message:
                    if not await self._dispatch_response(message):
                        return
                elif "id" in message and isinstance(message.get("method"), str):
                    if not await self._deny_server_request(message):
                        return
                elif isinstance(message.get("method"), str):
                    if not await self._dispatch_notification(message):
                        return
                else:
                    await self._fail("codex_app_server_future_schema")
                    return
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError):
            await self._fail("codex_app_server_read_failed")
        finally:
            if self._terminal is not None and not self._closed:
                await self._stop_process()

    async def _dispatch_response(self, message: dict[str, object]) -> bool:
        request_id = message.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            await self._fail("codex_app_server_unknown_response")
            return False
        pending = self._pending.pop(request_id, None)
        if pending is None:
            await self._fail("codex_app_server_unknown_response")
            return False
        future = pending.response
        if future.cancelled():
            return True
        error = message.get("error")
        if error is not None:
            code = "codex_app_server_request_failed"
            if _is_missing_resumed_thread_error(error, pending):
                code = "codex_app_server_thread_not_found"
            future.set_exception(AppServerConnectionError(code))
        elif "result" in message:
            future.set_result(message.get("result"))
        else:
            future.set_exception(AppServerConnectionError("codex_app_server_future_schema"))
            await self._fail("codex_app_server_future_schema")
            return False
        return True

    async def _deny_server_request(self, message: dict[str, object]) -> bool:
        request_id = message.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, (int, str)):
            await self._fail("codex_app_server_future_schema")
            return False
        try:
            async with self._write_lock:
                await self._write_json(
                    {
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": "server request unsupported",
                        },
                    }
                )
        except (OSError, RuntimeError):
            await self._fail("codex_app_server_write_failed")
            return False
        return True

    async def _dispatch_notification(self, message: dict[str, object]) -> bool:
        targets = set(self._streams)
        turn_id = _notification_turn_id(message)
        if turn_id is not None:
            targets.update(self._turn_streams.get(turn_id, ()))
        for queue in targets:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                await self._fail("codex_app_server_event_overflow")
                return False
        return True

    async def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    return
                self._stderr_hash.update(line)
                self._stderr_bytes += len(line)
                self._stderr_tail.extend(line)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError):
            await self._fail("codex_app_server_stderr_failed")
            await self._stop_process()

    async def _write_json(self, payload: Mapping[str, object]) -> None:
        stdin = self._process.stdin
        if stdin is None:
            raise AppServerConnectionError("codex_app_server_stream_unavailable")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AppServerConnectionError("codex_app_server_write_failed") from exc
        if len(encoded) > JSON_OBJECT_LIMIT_BYTES:
            raise AppServerConnectionError("codex_app_server_message_too_large")
        stdin.write(encoded + b"\n")
        await stdin.drain()

    async def _fail(self, code: str) -> None:
        if self._terminal is not None:
            return
        error = AppServerConnectionError(code)
        self._terminal = error
        pending, self._pending = self._pending, {}
        for request in pending.values():
            future = request.response
            if not future.done():
                future.set_exception(AppServerConnectionError(code))
        for queue in self._all_streams():
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                queue.put_nowait(AppServerConnectionError(code))
            except asyncio.QueueFull:
                pass

    def _raise_if_terminal(self) -> None:
        if self._terminal is not None:
            raise AppServerConnectionError(self._terminal.code)
        if self._closed:
            raise AppServerConnectionError("codex_app_server_closed")

    def _all_streams(
        self,
    ) -> set[asyncio.Queue[dict[str, object] | AppServerConnectionError]]:
        result = set(self._streams)
        for queues in self._turn_streams.values():
            result.update(queues)
        return result

    def _remove_stream(
        self,
        queue: asyncio.Queue[dict[str, object] | AppServerConnectionError],
        turn_id: str | None,
    ) -> None:
        if turn_id is None:
            self._streams.discard(queue)
            return
        queues = self._turn_streams.get(turn_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._turn_streams.pop(turn_id, None)

    async def _stop_process(self) -> None:
        if self._process.returncode is not None:
            return
        self._signal_process(signal.SIGTERM)
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
            return
        except TimeoutError:
            self._signal_process(signal.SIGKILL)
            await self._process.wait()

    def _signal_process(self, sig: signal.Signals) -> None:
        if self._owns_process_group:
            try:
                os.killpg(self._process.pid, sig)
                return
            except (OSError, ProcessLookupError):
                pass
        try:
            if sig is signal.SIGTERM:
                self._process.terminate()
            else:
                self._process.kill()
        except (OSError, ProcessLookupError):
            pass


def _notification_turn_id(message: Mapping[str, object]) -> str | None:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return None
    direct = params.get("turnId")
    if isinstance(direct, str) and direct:
        return direct
    turn = params.get("turn")
    if isinstance(turn, Mapping):
        nested = turn.get("id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _is_missing_resumed_thread_error(error: object, request: _PendingRequest) -> bool:
    if request.method != "thread/resume" or request.requested_thread_id is None:
        return False
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = error.get("message")
    return (
        isinstance(code, int)
        and not isinstance(code, bool)
        and code == -32600
        and message == f"no rollout found for thread id {request.requested_thread_id}"
    )


__all__ = [
    "AppServerConnectionError",
    "AppServerEventStream",
    "AppServerRequest",
    "CodexAppServerConnection",
]
