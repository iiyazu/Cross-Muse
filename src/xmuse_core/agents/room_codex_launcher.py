"""Room-only Codex launcher without lane/worker provider contracts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from xmuse_core.agents.codex_app_server_transport import (
    CODEX_ROOM_READ_ONLY_SANDBOX,
    CodexSandboxProfile,
    _normalize_mcp_path,
)
from xmuse_core.agents.codex_persistent_session import CodexAppServerSession
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    build_default_provider_registry,
    normalize_codex_model_id,
)


@dataclass
class RoomCodexLauncher:
    mcp_port: int = 8100
    mcp_path: str = "/mcp/room"
    model: str = DEFAULT_CODEX_GOD_MODEL_ID
    profile_id: ProviderProfileId = ProviderProfileId.DEFAULT
    sandbox_profile: CodexSandboxProfile = CODEX_ROOM_READ_ONLY_SANDBOX
    codex_home: Path | None = None
    supports_persistent_sessions: bool = field(init=False)
    _isolated_home_spawn_lock: asyncio.Lock | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.sandbox_profile, CodexSandboxProfile):
            raise TypeError("sandbox_profile must be a CodexSandboxProfile")
        if self.codex_home is not None:
            if not isinstance(self.codex_home, Path):
                raise TypeError("codex_home must be a Path or None")
            self.codex_home = self.codex_home.expanduser().resolve()
        self.mcp_path = _normalize_mcp_path(self.mcp_path)
        self.model = normalize_codex_model_id(
            self.model,
            profile_id=self.profile_id,
            allow_final_quality=False,
        )
        profile = build_default_provider_registry().get(f"codex.{self.profile_id.value}")
        self.supports_persistent_sessions = profile.supports_persistent_sessions
        self._isolated_home_spawn_lock = asyncio.Lock() if self.codex_home is not None else None

    async def spawn_persistent_session(
        self,
        *,
        role: str,
        worktree: Path,
        model: str | None = None,
        provider_session_id: str | None = None,
        db_path: Path | None = None,
    ) -> CodexAppServerSession:
        resolved_model = normalize_codex_model_id(
            model if model is not None else self.model,
            profile_id=self.profile_id,
            allow_final_quality=False,
        )

        async def spawn() -> CodexAppServerSession:
            return await CodexAppServerSession.spawn(
                god_id=f"codex-{role}",
                role=role,
                display_name=_display_name_for_role(role),
                model=resolved_model,
                worktree=worktree,
                db_path=db_path,
                mcp_port=self.mcp_port,
                mcp_path=self.mcp_path,
                enable_mcp=True,
                resume_thread_id=provider_session_id,
                sandbox_profile=self.sandbox_profile,
                codex_home=self.codex_home,
            )

        if self._isolated_home_spawn_lock is None:
            return await spawn()
        async with self._isolated_home_spawn_lock:
            return await spawn()


def build_room_launchers(
    *,
    mcp_port: int = 8100,
    codex_model: str | None = None,
    codex_home: Path | None = None,
) -> dict[AgentRuntime, object]:
    return {
        AgentRuntime.CODEX: RoomCodexLauncher(
            mcp_port=mcp_port,
            model=codex_model or DEFAULT_CODEX_GOD_MODEL_ID,
            codex_home=codex_home,
        )
    }


def _display_name_for_role(role: str) -> str:
    aliases = {
        "architect": "Architect",
        "execute": "Builder",
        "builder": "Builder",
        "review": "Reviewer",
        "reviewer": "Reviewer",
        "critic": "Critic",
        INIT_GOD_ROLE: "xmuse",
    }
    normalized = role.strip().lower()
    return aliases.get(normalized, role.strip().replace("_", " ").title() or "Codex")
