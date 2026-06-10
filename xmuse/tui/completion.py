from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompletionCandidate:
    type: str  # "command" or "mention"
    value: str
    display: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


_SLASH_COMMANDS = [
    {"name": "help", "description": "Show available commands", "params": ""},
    {"name": "sessions", "description": "List or switch to a session",
     "params": "[number|id|title]"},
    {"name": "resume", "description": "Alias for /sessions",
     "params": "[number|id|title]"},
    {"name": "new", "description": "Create a new group conversation", "params": "<title>"},
    {
        "name": "approve",
        "description": "Approve latest or named proposal",
        "params": "[latest|proposal_id]",
    },
    {"name": "where", "description": "Show current conversation and location", "params": ""},
    {"name": "participants", "description": "List GOD participants", "params": ""},
    {"name": "dashboard", "description": "Alias for /overview runtime dashboard", "params": ""},
    {"name": "discussion", "description": "Show discussion run status", "params": ""},
    {"name": "blockers", "description": "Show active blockers and vetoes", "params": ""},
    {"name": "god add", "description": "Add a GOD participant", "params": "<role> [display name]"},
    {"name": "god rm", "description": "Remove a GOD participant",
     "params": "<role|participant_id>"},
    {"name": "archive", "description": "Toggle archive view", "params": ""},
    {"name": "copy", "description": "Toggle copy view", "params": ""},
]


class CompletionEngine:
    def get_candidates(
        self,
        text: str,
        *,
        participants: list[dict] | None = None,
    ) -> list[CompletionCandidate]:
        if not text:
            return []

        if text.startswith("/"):
            return self._slash_candidates(text)

        at_pos = text.rfind(" @")
        if at_pos >= 0:
            after_at = text[at_pos + 2 :]
            if " " not in after_at:
                return self._mention_candidates(after_at, participants or [])

        if text.startswith("@") and " " not in text[1:]:
            return self._mention_candidates(text[1:], participants or [])

        return []

    def _slash_candidates(self, text: str) -> list[CompletionCandidate]:
        prefix = text[1:].lower()
        results: list[CompletionCandidate] = []
        for cmd in _SLASH_COMMANDS:
            name = cmd["name"]
            if name.startswith(prefix):
                param_hint = f" {cmd['params']}" if cmd["params"] else ""
                results.append(
                    CompletionCandidate(
                        type="command",
                        value=f"/{name}",
                        display=f"/{name}{param_hint}",
                        description=cmd["description"],
                    )
                )
        return results

    def _mention_candidates(
        self,
        prefix: str,
        participants: list[dict],
    ) -> list[CompletionCandidate]:
        lowered = prefix.lower()
        seen: set[str] = set()
        results: list[CompletionCandidate] = []
        for p in participants:
            role = str(p.get("role", "") or "")
            if not role or role in seen:
                continue
            display_name = str(p.get("display_name") or role)
            if role.lower().startswith(lowered) or display_name.lower().startswith(lowered):
                seen.add(role)
                results.append(
                    CompletionCandidate(
                        type="mention",
                        value=f"@{role}",
                        display=f"@{role} ({display_name})",
                        description=display_name,
                        metadata={"participant_id": str(p.get("participant_id", "") or "")},
                    )
                )
        return results
