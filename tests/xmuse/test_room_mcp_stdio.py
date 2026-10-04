from __future__ import annotations

import json
import queue
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.testclient import TestClient

from xmuse.room_mcp_server import create_app
from xmuse_core.chat.room_mcp_contract import ROOM_OUTCOME_TOOL_NAME, ROOM_TOOL_NAMES

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _serve_room_mcp(xmuse_root: Path) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(xmuse_root),
            host="127.0.0.1",
            port=0,
            log_level="warning",
            access_log=False,
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("room mcp server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp/room"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class _StdioMcpProxy:
    def __init__(self, url: str) -> None:
        self._process = subprocess.Popen(
            [sys.executable, "-m", "xmuse.room_mcp_stdio", "--url", url],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()

    def _read_lines(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def next_message(self, timeout: float = 10.0) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(
                f"no proxy stdio response within {timeout}s: {self._stderr_tail()!r}"
            ) from None
        if line is None:
            raise AssertionError(f"proxy stdout closed: {self._stderr_tail()!r}")
        return json.loads(line)

    def assert_no_output(self, timeout: float = 0.5) -> None:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return
        raise AssertionError(f"unexpected proxy stdout output: {line!r}")

    def _stderr_tail(self) -> str:
        if self._process.poll() is None or self._process.stderr is None:
            return ""
        return self._process.stderr.read()

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=10)
        self._reader.join(timeout=5)
        for pipe in (self._process.stdout, self._process.stderr):
            if pipe is not None:
                pipe.close()


@contextmanager
def _stdio_proxy(url: str) -> Iterator[_StdioMcpProxy]:
    proxy = _StdioMcpProxy(url)
    try:
        yield proxy
    finally:
        proxy.close()


def test_stdio_proxy_initializes_and_lists_exactly_the_room_tools(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as url, _stdio_proxy(url) as proxy:
        proxy.send(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            }
        )
        initialized = proxy.next_message()
        assert initialized["id"] == "init"
        assert initialized["result"]["serverInfo"]["name"] == "xmuse-room-mcp"

        proxy.send({"jsonrpc": "2.0", "id": "tools", "method": "tools/list"})
        listed = proxy.next_message()
        assert listed["id"] == "tools"
        assert [tool["name"] for tool in listed["result"]["tools"]] == list(ROOM_TOOL_NAMES)


def test_stdio_proxy_forwards_tool_argument_error_faithfully(tmp_path: Path) -> None:
    call = {
        "jsonrpc": "2.0",
        "id": "call-missing-args",
        "method": "tools/call",
        "params": {"name": ROOM_OUTCOME_TOOL_NAME, "arguments": {}},
    }
    with _serve_room_mcp(tmp_path) as url, _stdio_proxy(url) as proxy:
        proxy.send(call)
        forwarded = proxy.next_message()

    direct = TestClient(create_app(tmp_path)).post("/mcp/room", json=call).json()
    assert forwarded == direct
    assert forwarded["id"] == "call-missing-args"
    assert forwarded["result"]["isError"] is True
    assert forwarded["result"]["structuredContent"]["error"]["code"] == "invalid_arguments"
    assert "missing required arguments" in forwarded["result"]["content"][0]["text"]


def test_stdio_proxy_notifications_produce_no_stdout_output(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as url, _stdio_proxy(url) as proxy:
        proxy.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        proxy.assert_no_output()

        proxy.send({"jsonrpc": "2.0", "id": "after-notification", "method": "tools/list"})
        listed = proxy.next_message()
        assert listed["id"] == "after-notification"
        assert [tool["name"] for tool in listed["result"]["tools"]] == list(ROOM_TOOL_NAMES)


def test_stdio_proxy_maps_transport_errors_to_json_rpc_error_with_request_id() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    with _stdio_proxy(f"http://127.0.0.1:{closed_port}/mcp/room") as proxy:
        proxy.send({"jsonrpc": "2.0", "id": "unreachable", "method": "tools/list"})
        failure = proxy.next_message()
        assert failure["id"] == "unreachable"
        assert failure["error"]["code"] == -32000
        assert "transport error" in failure["error"]["message"]

        proxy.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        proxy.assert_no_output()
