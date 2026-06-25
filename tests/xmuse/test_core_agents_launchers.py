from __future__ import annotations

import sys
from pathlib import Path

from xmuse_core.agents.launchers.claude_code import ClaudeCodeLauncher
from xmuse_core.agents.launchers.codex import CodexLauncher
from xmuse_core.agents.protocol import AgentOutput, StdoutMessage
from xmuse_core.providers.adapters.base import ProviderFailureKind
from xmuse_core.providers.goal_contract import WorkerResultStatus


def test_codex_build_command():
    launcher = CodexLauncher()
    cmd = launcher.build_command("my-feature", Path("/tmp/worktree"))
    assert cmd == [
        "codex", "exec", "--ignore-user-config", "-m", "gpt-5.4",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        'mcp_servers.xmuse-platform.type="sse"',
        "-c",
        'mcp_servers.xmuse-platform.url="http://localhost:8100/sse"',
        "-C", "/tmp/worktree",
    ]


def test_codex_build_command_uses_configured_mcp_port():
    launcher = CodexLauncher(mcp_port=8123)
    cmd = launcher.build_command("my-feature", Path("/tmp/worktree"))

    assert 'mcp_servers.xmuse-platform.url="http://localhost:8123/sse"' in cmd


def test_codex_supports_persistent_sessions_via_shim():
    launcher = CodexLauncher(mcp_port=8123, model="gpt-5.4")

    cmd = launcher.build_persistent_command("review", Path("/tmp/worktree"))

    assert launcher.supports_persistent_sessions is True
    assert cmd == [
        sys.executable,
        "-m",
        "xmuse_core.agents.codex_persistent",
        "--model",
        "gpt-5.4",
        "--mcp-port",
        "8123",
        "--worktree",
        "/tmp/worktree",
        "--role",
        "review",
    ]


def test_codex_launcher_builds_provider_invocation_compatibility_surface(
    tmp_path: Path,
) -> None:
    launcher = CodexLauncher(mcp_port=8123, model="gpt-5.4")

    invocation = launcher.build_provider_invocation(
        request_id="req-123",
        prompt="Implement the lane.",
        worktree=tmp_path,
        timeout_seconds=120,
    )

    assert launcher.provider_profile_ref == "codex.default"
    assert invocation.provider_profile_ref == "codex.default"
    assert launcher.build_command("my-feature", tmp_path) == (
        launcher.provider_adapter.build_command_for_invocation(invocation)
    )


def test_codex_launcher_builds_provider_failure_result_from_agent_output(
    tmp_path: Path,
) -> None:
    launcher = CodexLauncher()
    invocation = launcher.build_provider_invocation(
        request_id="req-123",
        prompt="Implement the lane.",
        worktree=tmp_path,
        timeout_seconds=120,
    )

    result = launcher.build_provider_result_from_output(
        invocation,
        AgentOutput(status="error", error_code="exit_2"),
    )

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.NON_ZERO_EXIT


def test_claude_code_build_command():
    launcher = ClaudeCodeLauncher()
    cmd = launcher.build_command("my-feature", Path("/tmp/worktree"))
    assert cmd == [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ]


def test_codex_format_prompt_with_context():
    launcher = CodexLauncher()
    result = launcher.format_prompt("do the thing", "some context")
    assert "some context" in result
    assert "do the thing" in result


def test_codex_format_prompt_without_context():
    launcher = CodexLauncher()
    result = launcher.format_prompt("do the thing", "")
    assert result == "do the thing"


def test_claude_code_format_prompt_with_context():
    launcher = ClaudeCodeLauncher()
    result = launcher.format_prompt("do the thing", "some context")
    assert "## Context" in result
    assert "## Task" in result


def test_codex_build_env():
    launcher = CodexLauncher()
    env = launcher.build_env("archive-rag")
    assert env["XMUSE_FEATURE_ID"] == "archive-rag"


def test_claude_code_build_env():
    launcher = ClaudeCodeLauncher()
    env = launcher.build_env("archive-rag")
    assert env["XMUSE_FEATURE_ID"] == "archive-rag"


def test_codex_parse_output_result():
    launcher = CodexLauncher()
    msg = StdoutMessage(type="result", status="success", artifacts={"key": "val"})
    output = launcher.parse_output(msg)
    assert output is not None
    assert output.status == "success"


def test_codex_parse_output_progress_returns_none():
    launcher = CodexLauncher()
    msg = StdoutMessage(type="progress", stage="running")
    assert launcher.parse_output(msg) is None


def test_build_default_launchers_covers_every_runtime():
    from xmuse_core.agents.launchers import build_default_launchers
    from xmuse_core.agents.registry import AgentRuntime

    launchers = build_default_launchers()
    assert set(launchers) == set(AgentRuntime)
    assert isinstance(launchers[AgentRuntime.CODEX], CodexLauncher)
    assert isinstance(launchers[AgentRuntime.CLAUDE_CODE], ClaudeCodeLauncher)


def test_build_default_launchers_passes_mcp_port_to_codex():
    from xmuse_core.agents.launchers import build_default_launchers
    from xmuse_core.agents.registry import AgentRuntime

    launchers = build_default_launchers(mcp_port=8123)
    cmd = launchers[AgentRuntime.CODEX].build_command("my-feature", Path("/tmp/worktree"))

    assert 'mcp_servers.xmuse-platform.url="http://localhost:8123/sse"' in cmd
    assert launchers[AgentRuntime.CODEX].supports_persistent_sessions is True
