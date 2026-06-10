from __future__ import annotations

from xmuse.mcp_server import _content_json as legacy_content_json
from xmuse.mcp_server import _json_rpc_error as legacy_json_rpc_error
from xmuse_core.platform import mcp_responses


def test_mcp_responses_module_owns_content_json() -> None:
    payload = {"ok": True, "value": "测试"}

    result = mcp_responses.content_json(payload)

    assert result["structuredContent"] == payload
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert '"ok": true' in result["content"][0]["text"]


def test_mcp_responses_module_owns_json_rpc_error() -> None:
    result = mcp_responses.json_rpc_error("req-1", -32602, "Invalid params")

    assert result == {
        "jsonrpc": "2.0",
        "id": "req-1",
        "error": {"code": -32602, "message": "Invalid params"},
    }


def test_mcp_server_preserves_response_helper_compat_exports() -> None:
    assert legacy_content_json is mcp_responses.content_json
    assert legacy_json_rpc_error is mcp_responses.json_rpc_error
