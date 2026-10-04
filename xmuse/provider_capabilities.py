"""Server-side Room provider capability detection for the local Workroom.

Detection is deliberately safe to project: it reports only availability,
enablement, and confinement posture per provider kind.  Executable paths,
PIDs, and tokens never leave the server.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from xmuse_core.chat.room_acp_transport import ROOM_ACP_CONFINEMENT, ROOM_OPENCODE_CONFINEMENT
from xmuse_core.chat.room_agy_sandbox import (
    AGY_EXECUTABLE_ENV,
    AGY_MODEL_ENV,
    ROOM_AGY_READ_ONLY_CONFINEMENT,
    resolve_agy_executable,
    resolve_agy_python3,
)
from xmuse_core.chat.room_opencode_sandbox import (
    OPENCODE_BWRAP_ENV,
    OPENCODE_EXECUTABLE_ENV,
    resolve_bwrap_executable,
    resolve_opencode_executable,
)

ROOM_PROVIDER_KINDS = ("codex", "claude", "antigravity", "opencode")
CODEX_CONFINEMENT = "read_only_sandbox"
ROOM_MCP_PINNED_PORT = 8100
ROOM_MCP_PINNED_HOST = "127.0.0.1"
CLAUDE_FLAG_ENV = "XMUSE_CLAUDE_ACP"
CLAUDE_COMMAND_ENV = "XMUSE_CLAUDE_ACP_COMMAND"
ANTIGRAVITY_FLAG_ENV = "XMUSE_ANTIGRAVITY"
OPENCODE_FLAG_ENV = "XMUSE_OPENCODE"
OPENCODE_MODEL_ENV = "XMUSE_OPENCODE_MODEL"
ROOM_RUNNER_PROVIDER_ENV_KEYS = (
    CLAUDE_FLAG_ENV,
    CLAUDE_COMMAND_ENV,
    ANTIGRAVITY_FLAG_ENV,
    AGY_EXECUTABLE_ENV,
    AGY_MODEL_ENV,
    OPENCODE_FLAG_ENV,
    OPENCODE_MODEL_ENV,
    OPENCODE_EXECUTABLE_ENV,
    OPENCODE_BWRAP_ENV,
)


def env_flag(name: str, environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _flag_configured(name: str, environ: Mapping[str, str]) -> bool:
    return bool(str(environ.get(name) or "").strip())


def _codex_credentials_present(environ: Mapping[str, str]) -> bool:
    """A Codex participant cannot run without an ambient authentication carrier."""

    if str(environ.get("OPENAI_API_KEY") or "").strip():
        return True
    configured = str(environ.get("CODEX_HOME") or "").strip()
    home = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return (home / "auth.json").is_file()


def detect_provider_capabilities(
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, dict[str, object]]:
    """Detect one safe capability record per provider kind.

    ``enabled`` honors an explicit ``XMUSE_CLAUDE_ACP``/``XMUSE_ANTIGRAVITY``/
    ``XMUSE_OPENCODE`` flag (the managed Workroom always writes one); without a flag a provider is
    enabled exactly when it is available.  Codex has no admission flag and is
    enabled by the persistent Room composition whenever it is usable.
    """

    source = os.environ if environ is None else environ

    codex_available = which("codex") is not None and _codex_credentials_present(source)
    claude_available = which("claude") is not None and which("npx") is not None
    antigravity_available = (
        resolve_agy_executable(source, which) is not None
        and resolve_bwrap_executable(source, which) is not None
        and resolve_agy_python3(source, which) is not None
    )
    # OpenCode runs only inside its read-only bubblewrap sandbox.
    opencode_available = (
        resolve_opencode_executable(source, which) is not None
        and resolve_bwrap_executable(source, which) is not None
    )

    def resolved_enabled(name: str, available: bool) -> bool:
        if _flag_configured(name, source):
            return env_flag(name, source)
        return available

    return {
        "codex": {
            "available": codex_available,
            "enabled": codex_available,
            "confinement": CODEX_CONFINEMENT,
        },
        "claude": {
            "available": claude_available,
            "enabled": resolved_enabled(CLAUDE_FLAG_ENV, claude_available),
            "confinement": ROOM_ACP_CONFINEMENT,
        },
        "antigravity": {
            "available": antigravity_available,
            "enabled": resolved_enabled(ANTIGRAVITY_FLAG_ENV, antigravity_available),
            "confinement": ROOM_AGY_READ_ONLY_CONFINEMENT,
        },
        "opencode": {
            "available": opencode_available,
            "enabled": resolved_enabled(OPENCODE_FLAG_ENV, opencode_available),
            "confinement": ROOM_OPENCODE_CONFINEMENT,
        },
    }
