from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.agents.grok_persistent import DEFAULT_GROK_MODEL_ID
from xmuse_core.agents.protocol import AgentOutput, StdoutMessage


@dataclass
class GrokLauncher:
    mcp_port: int = 8100
    model: str = DEFAULT_GROK_MODEL_ID
    grok_binary: str = "grok"
    supports_persistent_sessions: bool = True

    @property
    def provider_profile_ref(self) -> str:
        return "grok.god_peer"

    def build_command(self, feature_id: str, worktree: Path) -> list[str]:
        return [
            self.grok_binary,
            "-m",
            self.model,
            "-w",
            str(worktree),
        ]

    def build_persistent_command(
        self,
        role: str,
        worktree: Path,
        *,
        provider_session_id: str | None = None,
    ) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "xmuse_core.agents.grok_persistent",
            "--model",
            self.model,
            "--mcp-port",
            str(self.mcp_port),
            "--worktree",
            str(worktree),
            "--role",
            role,
            "--grok-binary",
            self.grok_binary,
        ]
        if provider_session_id:
            command.extend(["--session-id", provider_session_id])
        return command

    def format_prompt(self, task: str, context: str) -> str:
        if context:
            return f"## Context\n\n{context}\n\n## Task\n\n{task}"
        return task

    def build_env(self, feature_id: str) -> dict[str, str]:
        env = dict(os.environ)
        env["XMUSE_FEATURE_ID"] = feature_id
        return env

    def persistent_model(self) -> str:
        return self.model

    def parse_output(self, msg: StdoutMessage) -> AgentOutput | None:
        if msg.type == "result":
            return AgentOutput.from_result(msg)
        if msg.type == "error":
            return AgentOutput.from_error(msg)
        return None
