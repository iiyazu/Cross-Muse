"""Launcher adapters for different agent runtimes."""

from xmuse_core.agents.launchers.base import LauncherAdapter
from xmuse_core.agents.launchers.claude_code import ClaudeCodeLauncher
from xmuse_core.agents.launchers.codex import CodexLauncher
from xmuse_core.agents.registry import AgentRuntime

__all__ = [
    "ClaudeCodeLauncher",
    "CodexLauncher",
    "LauncherAdapter",
    "build_default_launchers",
]


def build_default_launchers(
    *,
    mcp_port: int = 8100,
    codex_model: str | None = None,
) -> dict[AgentRuntime, LauncherAdapter]:
    """Return a launcher map covering every supported agent runtime."""
    return {
        AgentRuntime.CODEX: CodexLauncher(
            mcp_port=mcp_port,
            **({"model": codex_model} if codex_model else {}),
        ),
        AgentRuntime.CLAUDE_CODE: ClaudeCodeLauncher(),
    }
