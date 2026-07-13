#!/usr/bin/env python3
"""Minimal MCP-over-HTTP server for durable Room outcomes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from xmuse_core import mcp_responses
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_mcp_contract import (
    ROOM_OUTCOME_TOOL_NAME,
    room_tool_schemas,
)
from xmuse_core.runtime.data_guard import assert_data_operation_complete
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)
SERVER_NAME = "xmuse-room-mcp"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", DEFAULT_PROTOCOL_VERSION}
MCP_ROLE_HEADER = "x-xmuse-mcp-role"
MCP_ROLE_ENV = "XMUSE_MCP_ROLE"


def _initialize_result(params: object) -> dict[str, object]:
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    protocol_version = (
        requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
    )
    return {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_NAME,
            "title": "xmuse Room MCP",
            "version": SERVER_VERSION,
        },
    }


def _authorize(request: Request) -> None:
    role = request.headers.get(MCP_ROLE_HEADER, os.environ.get(MCP_ROLE_ENV, "god"))
    normalized = role.strip().lower()
    if normalized in {"admin", "operator", "god"}:
        return
    if normalized == "viewer":
        raise PermissionError(
            f"MCP authorization denied for {ROOM_OUTCOME_TOOL_NAME}: "
            f"role viewer cannot mutate write tool {ROOM_OUTCOME_TOOL_NAME}"
        )
    raise PermissionError(
        f"MCP authorization denied for {ROOM_OUTCOME_TOOL_NAME}: unknown MCP role: {normalized}"
    )


def _validate_tool_call(params: object) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    name = params.get("name")
    if name != ROOM_OUTCOME_TOOL_NAME:
        raise ValueError(f"tool is not exposed on this MCP endpoint: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    required = room_tool_schemas()[0]["inputSchema"]["required"]
    missing = [item for item in required if item not in arguments]
    if missing:
        raise ValueError(
            f"{ROOM_OUTCOME_TOOL_NAME} missing required arguments: " + ", ".join(sorted(missing))
        )
    return arguments


def _submit_outcome(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return RoomApplicationService(
            root / "chat.db",
            root / "god_sessions.json",
        ).submit_participant_outcome(**arguments)
    except RoomApplicationError as exc:
        return {"error": {"code": exc.code, "message": exc.message}}
    except (TypeError, ValueError) as exc:
        return {"error": {"code": "invalid_arguments", "message": str(exc)}}


async def _handle_rpc(request: Request, root: Path) -> Response:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(mcp_responses.json_rpc_error(None, -32700, "invalid JSON"))
    if not isinstance(payload, dict):
        return JSONResponse(mcp_responses.json_rpc_error(None, -32600, "request must be an object"))
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    try:
        if method == "initialize":
            result = _initialize_result(params)
        elif method == "notifications/initialized":
            return Response(status_code=202)
        elif method == "tools/list":
            result = {"tools": room_tool_schemas()}
        elif method == "tools/call":
            _authorize(request)
            try:
                arguments = _validate_tool_call(params)
            except (TypeError, ValueError) as exc:
                result = mcp_responses.structured_error("invalid_arguments", str(exc))
            else:
                outcome = _submit_outcome(root, arguments)
                result = mcp_responses.content_json(outcome, is_error="error" in outcome)
        else:
            return JSONResponse(
                mcp_responses.json_rpc_error(
                    request_id,
                    -32601,
                    f"method not found: {method}",
                )
            )
        return JSONResponse(mcp_responses.json_rpc_response(request_id, result))
    except Exception as exc:
        return JSONResponse(
            mcp_responses.json_rpc_response(
                request_id,
                mcp_responses.error_content(str(exc)),
            )
        )


def create_app(xmuse_root: Path | str = DEFAULT_XMUSE_ROOT) -> FastAPI:
    root = Path(xmuse_root)
    assert_data_operation_complete(root)
    app = FastAPI(
        title="xmuse Room MCP",
        version=SERVER_VERSION,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": SERVER_NAME,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "surface": "room",
            "endpoints": {"mcp_room": "/mcp/room"},
        }

    @app.post("/mcp/room")
    async def room_mcp(request: Request) -> Response:
        return await _handle_rpc(request, root)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Room-only xmuse MCP server.")
    parser.add_argument(
        "--xmuse-root",
        type=Path,
        default=DEFAULT_XMUSE_ROOT,
        help="runtime root containing chat.db and Room state",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8100, help="bind port")
    parser.add_argument("--surface", choices=("room",), default="room", help=argparse.SUPPRESS)
    args = parser.parse_args()
    uvicorn.run(create_app(args.xmuse_root), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
