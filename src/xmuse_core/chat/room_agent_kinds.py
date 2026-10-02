"""Provider-neutral classification of Room agent cli kinds.

A Room agent is any participant whose runtime kind is currently admitted by the
provider-neutral Room core.  Codex-native modules must not import this module to
widen their own capability checks.
"""

from __future__ import annotations

ROOM_AGENT_CLI_KINDS: tuple[str, ...] = ("codex", "claude", "antigravity", "opencode")


def room_agent_cli_kind_placeholders() -> str:
    """SQL placeholder list consuming ROOM_AGENT_CLI_KINDS in tuple order."""

    return ", ".join("?" for _ in ROOM_AGENT_CLI_KINDS)
