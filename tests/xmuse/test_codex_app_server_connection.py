from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from xmuse_core.agents.codex_app_server_connection import (
    AppServerConnectionError,
    CodexAppServerConnection,
)


class FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise RuntimeError("closed")
        self.writes.append(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeWriter()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.pid = 999_999
        self.returncode: int | None = None
        self.terminated = 0
        self.killed = 0
        self._waiter = asyncio.Event()

    def terminate(self) -> None:
        self.terminated += 1
        self.returncode = -15
        self._waiter.set()

    def kill(self) -> None:
        self.killed += 1
        self.returncode = -9
        self._waiter.set()

    async def wait(self) -> int:
        await self._waiter.wait()
        assert self.returncode is not None
        return self.returncode

    def feed_stdout(self, payload: object) -> None:
        self.stdout.feed_data(json.dumps(payload).encode() + b"\n")

    def feed_stdout_bytes(self, payload: bytes) -> None:
        self.stdout.feed_data(payload)

    def exit(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._waiter.set()


def _writes(process: FakeProcess) -> list[dict[str, object]]:
    return [json.loads(item) for item in process.stdin.writes]


@pytest.mark.asyncio
async def test_request_with_none_omits_params_for_null_schema_methods() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    pending = await connection.start_request("config/mcpServer/reload", None)
    process.feed_stdout({"id": pending.request_id, "result": {}})

    assert await pending.response == {}
    assert _writes(process) == [{"id": pending.request_id, "method": "config/mcpServer/reload"}]
    await connection.close()


@pytest.mark.asyncio
async def test_sole_reader_routes_interleaved_messages_and_denies_server_request() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=7, owns_process_group=False)
    events = connection.subscribe()
    first = await connection.start_request("first", {"value": 1})
    second = await connection.start_request("second", {"value": 2})

    process.feed_stdout({"method": "turn/started", "params": {"turn": {"id": "t1"}}})
    process.feed_stdout({"id": "server-1", "method": "item/requestApproval", "params": {}})
    process.feed_stdout({"id": second.request_id, "result": {"order": 2}})
    process.feed_stdout({"id": first.request_id, "result": {"order": 1}})

    assert await second.response == {"order": 2}
    assert await first.response == {"order": 1}
    assert (await events.receive())["method"] == "turn/started"
    await asyncio.sleep(0)
    assert _writes(process)[-1] == {
        "id": "server-1",
        "error": {"code": -32601, "message": "server request unsupported"},
    }
    events.close()
    await connection.close()


@pytest.mark.asyncio
async def test_turn_stream_receives_only_exact_turn_notifications() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    exact = connection.subscribe(turn_id="turn-b")
    all_events = connection.subscribe()

    process.feed_stdout({"method": "item/started", "params": {"turnId": "turn-a"}})
    process.feed_stdout({"method": "item/completed", "params": {"turnId": "turn-b"}})

    assert (await all_events.receive())["method"] == "item/started"
    assert (await all_events.receive())["method"] == "item/completed"
    assert (await exact.receive())["method"] == "item/completed"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(exact.receive(), timeout=0.01)
    exact.close()
    all_events.close()
    await connection.close()


@pytest.mark.asyncio
async def test_stderr_is_continuously_drained_hashed_and_bounded() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    payload = b"secret-provider-diagnostic\n" * 2_000
    process.stderr.feed_data(payload)
    process.stderr.feed_eof()
    await asyncio.sleep(0.01)

    digest, byte_count, tail = connection.stderr_evidence()
    assert digest == f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert byte_count == len(payload)
    assert tail == payload[-16 * 1024 :]
    await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not-json\n", "codex_app_server_malformed_json"),
        (b"[]\n", "codex_app_server_future_schema"),
        (b'{"id":999,"result":{}}\n', "codex_app_server_unknown_response"),
    ],
)
async def test_protocol_failure_finishes_every_pending_request_once(
    payload: bytes, code: str
) -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    first = await connection.start_request("first", {})
    second = await connection.start_request("second", {})
    process.feed_stdout_bytes(payload)

    for response in (first.response, second.response):
        with pytest.raises(AppServerConnectionError) as error:
            await response
        assert error.value.code == code
    assert connection.terminal_code == code
    with pytest.raises(AppServerConnectionError) as rejected:
        await connection.request("later", {})
    assert rejected.value.code == code
    await connection.close()


@pytest.mark.asyncio
async def test_stdout_exit_fails_pending_request_and_event_stream() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=3, owns_process_group=False)
    events = connection.subscribe()
    pending = await connection.start_request("waiting", {})
    process.exit(17)

    with pytest.raises(AppServerConnectionError) as response_error:
        await pending.response
    assert response_error.value.code == "codex_app_server_exited"
    with pytest.raises(AppServerConnectionError) as stream_error:
        await events.receive()
    assert stream_error.value.code == "codex_app_server_exited"
    events.close()
    await connection.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_poison_connection_generation() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=3, owns_process_group=False)
    cancelled = await connection.start_request("cancelled", {})
    cancelled.response.cancel()
    process.feed_stdout({"id": cancelled.request_id, "result": {}})
    healthy = await connection.start_request("healthy", {})
    process.feed_stdout({"id": healthy.request_id, "result": {"ok": True}})

    assert await healthy.response == {"ok": True}
    assert connection.terminal_code is None
    await connection.close()


@pytest.mark.asyncio
async def test_exact_missing_resumed_thread_error_maps_to_content_free_code() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    pending = await connection.start_request(
        "thread/resume", {"threadId": "thread-missing", "cwd": "/private/workspace"}
    )
    process.feed_stdout(
        {
            "id": pending.request_id,
            "error": {
                "code": -32600,
                "message": "no rollout found for thread id thread-missing",
                "data": {"private": "provider detail"},
            },
        }
    )

    with pytest.raises(AppServerConnectionError) as error:
        await pending.response

    assert error.value.code == "codex_app_server_thread_not_found"
    assert str(error.value) == "codex_app_server_thread_not_found"
    assert "thread-missing" not in str(error.value)
    assert "provider detail" not in str(error.value)
    assert connection.terminal_code is None
    await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params", "error"),
    [
        (
            "thread/read",
            {"threadId": "thread-missing"},
            {"code": -32600, "message": "no rollout found for thread id thread-missing"},
        ),
        (
            "thread/resume",
            {"threadId": "thread-missing"},
            {"code": -32601, "message": "no rollout found for thread id thread-missing"},
        ),
        (
            "thread/resume",
            {"threadId": "thread-missing"},
            {"code": -32600.0, "message": "no rollout found for thread id thread-missing"},
        ),
        (
            "thread/resume",
            {"threadId": "thread-missing"},
            {"code": -32600, "message": "no rollout found for thread id thread-other"},
        ),
        (
            "thread/resume",
            {"threadId": "thread-missing"},
            {"code": -32600, "message": "no rollout found for thread id thread-missing "},
        ),
    ],
)
async def test_missing_thread_error_mapping_fails_closed_for_non_exact_errors(
    method: str,
    params: dict[str, object],
    error: dict[str, object],
) -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=1, owns_process_group=False)
    pending = await connection.start_request(method, params)
    process.feed_stdout({"id": pending.request_id, "error": error})

    with pytest.raises(AppServerConnectionError) as raised:
        await pending.response

    assert raised.value.code == "codex_app_server_request_failed"
    assert str(raised.value) == "codex_app_server_request_failed"
    assert connection.terminal_code is None
    await connection.close()


@pytest.mark.asyncio
async def test_event_overflow_is_terminal_and_wakes_subscriber() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(
        process,
        generation=1,
        event_queue_size=1,
        owns_process_group=False,
    )
    events = connection.subscribe()
    process.feed_stdout({"method": "one", "params": {}})
    process.feed_stdout({"method": "two", "params": {}})
    await asyncio.sleep(0.01)

    assert connection.terminal_code == "codex_app_server_event_overflow"
    with pytest.raises(AppServerConnectionError) as error:
        await events.receive()
    assert error.value.code == "codex_app_server_event_overflow"
    events.close()
    await connection.close()


@pytest.mark.asyncio
async def test_close_is_idempotent_generation_local_and_terminates_owned_child() -> None:
    process = FakeProcess()
    connection = CodexAppServerConnection(process, generation=11, owns_process_group=False)
    pending = await connection.start_request("waiting", {})

    await connection.close()
    await connection.close()

    with pytest.raises(AppServerConnectionError) as error:
        await pending.response
    assert error.value.code == "codex_app_server_closed"
    assert connection.generation == 11
    assert process.terminated == 1
    assert process.killed == 0
    assert process.stdin.closed is True
