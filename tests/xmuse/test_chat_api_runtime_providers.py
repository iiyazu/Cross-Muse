from __future__ import annotations

import json
from pathlib import Path

from xmuse import chat_api_runtime

DISABLED_CAPS = {
    "codex": {"available": True, "enabled": True, "confinement": "read_only_sandbox"},
    "claude": {"available": False, "enabled": False, "confinement": "client_permission_gated"},
    "antigravity": {
        "available": False,
        "enabled": False,
        "confinement": "instructed_read_only",
    },
    "opencode": {"available": False, "enabled": False, "confinement": "os_read_only_sandbox"},
}
ANTIGRAVITY_CAPS = {
    **DISABLED_CAPS,
    "antigravity": {
        "available": True,
        "enabled": True,
        "confinement": "instructed_read_only",
    },
}


def test_recorded_generation_port_is_reused_unless_antigravity_is_enabled(tmp_path: Path) -> None:
    (tmp_path / "workroom_room_runner.pid.json").write_text(
        json.dumps({"command": ["python", "xmuse/room_runner.py", "--mcp-port", "8117"]}),
        encoding="utf-8",
    )

    assert chat_api_runtime._workroom_mcp_port(tmp_path, DISABLED_CAPS) == 8117
    assert chat_api_runtime._workroom_mcp_port(tmp_path, ANTIGRAVITY_CAPS) == 8100


def _clear_provider_env(monkeypatch) -> None:
    for key in (
        "XMUSE_CLAUDE_ACP",
        "XMUSE_CLAUDE_ACP_COMMAND",
        "XMUSE_ANTIGRAVITY",
        "XMUSE_ANTIGRAVITY_AGENTAPI",
        "XMUSE_ANTIGRAVITY_BRAIN_DIR",
        "XMUSE_OPENCODE",
        "XMUSE_OPENCODE_MODEL",
        "XMUSE_OPENCODE_BIN",
        "XMUSE_OPENCODE_BWRAP",
    ):
        monkeypatch.delenv(key, raising=False)


def test_runtime_config_forwards_runner_env_only_without_browser_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(
        chat_api_runtime,
        "detect_provider_capabilities",
        lambda: ANTIGRAVITY_CAPS,
    )
    monkeypatch.setenv("XMUSE_CLAUDE_ACP_COMMAND", "/opt/claude-acp-bridge")
    monkeypatch.setenv("XMUSE_ANTIGRAVITY_AGENTAPI", "/opt/agentapi")

    config = chat_api_runtime._workroom_room_runtime_config(
        tmp_path,
        tmp_path / "repo",
        generation="generation-provider",
    )

    assert config.mcp_port == 8100
    assert config.room_runner_env == {
        "XMUSE_CLAUDE_ACP": "0",
        "XMUSE_ANTIGRAVITY": "1",
        "XMUSE_OPENCODE": "0",
        "XMUSE_CLAUDE_ACP_COMMAND": "/opt/claude-acp-bridge",
        "XMUSE_ANTIGRAVITY_AGENTAPI": "/opt/agentapi",
    }


def test_runtime_config_omits_blank_runner_env_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(
        chat_api_runtime,
        "detect_provider_capabilities",
        lambda: DISABLED_CAPS,
    )
    monkeypatch.setenv("XMUSE_CLAUDE_ACP_COMMAND", "   ")

    config = chat_api_runtime._workroom_room_runtime_config(
        tmp_path,
        tmp_path / "repo",
        generation="generation-provider",
    )

    assert config.room_runner_env == {
        "XMUSE_CLAUDE_ACP": "0",
        "XMUSE_ANTIGRAVITY": "0",
        "XMUSE_OPENCODE": "0",
    }
