from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class AgentRuntime(StrEnum):
    CODEX = "codex"


RuntimeKey = AgentRuntime | str


@dataclass
class SessionConfig:
    transport: Literal["local", "remote"] = "local"
    heartbeat_interval_s: int = 30
    heartbeat_timeout_s: int = 300
    max_context_tokens: int | None = None
    persistent_role: str | None = None


@dataclass
class AgentDescriptor:
    runtime: RuntimeKey
    name: str
    capabilities: list[str] = field(default_factory=list)
    session_config: SessionConfig = field(default_factory=SessionConfig)
