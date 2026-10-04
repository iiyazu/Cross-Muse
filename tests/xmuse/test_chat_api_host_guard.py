from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.runtime.frontend_api import is_loopback_host_header


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:8201", "localhost", "LOCALHOST:3000", "[::1]", "[::1]:8201"],
)
def test_loopback_host_headers_are_accepted(host: str) -> None:
    assert is_loopback_host_header(host)


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "evil.example",
        "evil.example:8201",
        "127.0.0.1.evil.example",
        "localhost.evil.example:8201",
        "127.0.0.1:99999999",
        "127.0.0.1@evil.example",
        "0.0.0.0:8201",
    ],
)
def test_other_host_headers_are_rejected(host: str | None) -> None:
    assert not is_loopback_host_header(host)


def test_chat_api_rejects_a_rebound_host_before_any_route(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    ok = client.get("/health", headers={"Host": "127.0.0.1:8201"})
    rebound = client.get("/health", headers={"Host": "evil.example:8201"})
    write = client.post(
        "/api/chat/operator/board-splits/split-1/decision",
        headers={"Host": "evil.example:8201"},
        json={"conversation_id": "c", "decision": "approve"},
    )

    assert ok.status_code == 200
    assert rebound.status_code == 400
    assert rebound.json()["detail"]["code"] == "room_host_invalid"
    assert write.status_code == 400
    assert write.json()["detail"]["code"] == "room_host_invalid"
