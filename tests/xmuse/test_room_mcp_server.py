from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.room_mcp_server import create_app
from xmuse_core.chat.room_mcp_contract import ROOM_OUTCOME_TOOL_NAME, room_tool_schemas


def test_default_room_mcp_has_one_bounded_surface(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "xmuse-room-mcp",
        "server": "xmuse-room-mcp",
        "version": "0.1.0",
        "surface": "room",
        "endpoints": {"mcp_room": "/mcp/room"},
    }
    assert str(tmp_path) not in health.text

    listed = client.post(
        "/mcp/room",
        json={"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
    )
    assert listed.status_code == 200
    assert listed.json()["result"]["tools"] == room_tool_schemas()
    assert [item["name"] for item in listed.json()["result"]["tools"]] == [ROOM_OUTCOME_TOOL_NAME]
    rpc = {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"}
    for path in ("/mcp", "/mcp/chat", "/sse", "/messages"):
        assert client.post(path, json=rpc).status_code == 404
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_room_mcp_import_does_not_load_compatibility_graph(tmp_path: Path) -> None:
    script = r"""
import json
import sys
from pathlib import Path
from xmuse.room_mcp_server import create_app

create_app(Path(sys.argv[1]))
forbidden = sorted(
    name for name in sys.modules
    if name.startswith((
        "xmuse.compat",
        "xmuse_core.platform",
        "xmuse_core.structuring",
        "xmuse_core.self_evolution",
        "xmuse_core.integrations.a2a",
        "a2a",
    ))
)
print(json.dumps(forbidden))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )

    assert json.loads(completed.stdout) == []


def test_room_mcp_rejects_non_god_write_role(tmp_path: Path) -> None:
    result = TestClient(create_app(tmp_path)).post(
        "/mcp/room",
        headers={"x-xmuse-mcp-role": "viewer"},
        json={
            "jsonrpc": "2.0",
            "id": "denied",
            "method": "tools/call",
            "params": {"name": ROOM_OUTCOME_TOOL_NAME, "arguments": {}},
        },
    )

    assert result.status_code == 200
    assert result.json()["result"]["isError"] is True
    assert "viewer cannot mutate" in result.json()["result"]["content"][0]["text"]
