#!/usr/bin/env python3
"""Newline-delimited MCP stdio bridge to the Room MCP HTTP endpoint.

The bridge is a dumb pipe: every JSON-RPC line read from stdin is forwarded
verbatim to the configured ``--url`` with the server-only god role header, and
the HTTP JSON-RPC response body is copied back to stdout. Logging goes to
stderr so stdout stays a clean protocol channel.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request

DEFAULT_MCP_URL = "http://127.0.0.1:8100/mcp/room"
MCP_ROLE_HEADER = "x-xmuse-mcp-role"
MCP_ROLE = "god"
REQUEST_TIMEOUT_S = 30.0
JSON_RPC_PARSE_ERROR = -32700
JSON_RPC_PROXY_ERROR = -32000

_LOGGER = logging.getLogger("xmuse.room_mcp_stdio")


def _json_rpc_error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write_raw(payload: bytes) -> None:
    buffer = sys.stdout.buffer
    buffer.write(payload)
    buffer.flush()


def _write_message(message: dict[str, object]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _write_raw(payload + b"\n")


def _post(url: str, body: bytes) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", MCP_ROLE_HEADER: MCP_ROLE},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return bytes(response.read())


def _bridge_line(url: str, raw_line: bytes) -> None:
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError:
        _write_message(_json_rpc_error(None, JSON_RPC_PARSE_ERROR, "request line is not utf-8"))
        return
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        _write_message(_json_rpc_error(None, JSON_RPC_PARSE_ERROR, "request line is not JSON"))
        return
    request_id = message.get("id") if isinstance(message, dict) else None
    notification = isinstance(message, dict) and "id" not in message
    try:
        response_body = _post(url, text.encode("utf-8"))
    except urllib.error.HTTPError as exc:
        _LOGGER.error("room mcp proxy http error for id=%r: %s", request_id, exc)
        if not notification:
            _write_message(
                _json_rpc_error(
                    request_id,
                    JSON_RPC_PROXY_ERROR,
                    f"room mcp proxy http error: {exc.code} {exc.reason}",
                )
            )
        return
    except Exception as exc:
        _LOGGER.error("room mcp proxy transport error for id=%r: %r", request_id, exc)
        if not notification:
            _write_message(
                _json_rpc_error(
                    request_id,
                    JSON_RPC_PROXY_ERROR,
                    f"room mcp proxy transport error: {exc}",
                )
            )
        return
    if notification:
        return
    if not response_body.endswith(b"\n"):
        response_body += b"\n"
    _write_raw(response_body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bridge newline-delimited MCP stdio to the Room MCP HTTP endpoint."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MCP_URL,
        help=f"Room MCP HTTP endpoint (default: {DEFAULT_MCP_URL})",
    )
    args = parser.parse_args()
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _LOGGER.info("room mcp stdio bridge forwarding to %s", args.url)
    for raw_line in sys.stdin.buffer:
        if raw_line.strip():
            _bridge_line(args.url, raw_line)


if __name__ == "__main__":
    main()
