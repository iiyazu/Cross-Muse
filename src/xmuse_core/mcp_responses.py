"""Transport-neutral MCP JSON-RPC response helpers."""

from __future__ import annotations

import json
from typing import Any


def content_json(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def structured_error(code: str, message: str) -> dict[str, Any]:
    return content_json(
        {"error": {"code": code, "message": message}},
        is_error=True,
    )


def error_content(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def json_rpc_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


__all__ = [
    "content_json",
    "error_content",
    "json_rpc_error",
    "json_rpc_response",
    "structured_error",
]
