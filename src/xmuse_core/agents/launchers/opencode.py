from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.agents.opencode_persistent import (
    DEFAULT_OPENCODE_MODEL_REF,
    DEFAULT_OPENCODE_VARIANT,
)
from xmuse_core.agents.protocol import AgentOutput, StdoutMessage


@dataclass
class OpenCodeLauncher:
    mcp_port: int = 8100
    model: str = DEFAULT_OPENCODE_MODEL_REF
    variant: str = DEFAULT_OPENCODE_VARIANT
    opencode_binary: str = "opencode"
    supports_persistent_sessions: bool = True

    @property
    def provider_profile_ref(self) -> str:
        return "opencode.deepseek_flash_worker"

    def build_command(self, feature_id: str, worktree: Path) -> list[str]:
        return [
            self.opencode_binary,
            "run",
            "--model",
            self.model,
            "--variant",
            self.variant,
            "--format",
            "json",
            "--dir",
            str(worktree),
        ]

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "xmuse_core.agents.opencode_persistent",
            "--model",
            self.model,
            "--variant",
            self.variant,
            "--mcp-port",
            str(self.mcp_port),
            "--worktree",
            str(worktree),
            "--role",
            role,
            "--opencode-binary",
            self.opencode_binary,
        ]

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
