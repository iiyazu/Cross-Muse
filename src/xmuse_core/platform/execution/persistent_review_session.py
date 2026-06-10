from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor


@dataclass(frozen=True)
class ConfiguredReviewPeerAttempt:
    attempted: bool = False
    delivered: bool = False
    required_failed: bool = False


class PersistentReviewSessionLayer(Protocol):
    async def ensure_conversation_session(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        role: str,
        agent: AgentDescriptor,
        worktree: Path,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord: ...

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None: ...

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None: ...

    async def abort_session(self, god_session_id: str) -> None: ...
