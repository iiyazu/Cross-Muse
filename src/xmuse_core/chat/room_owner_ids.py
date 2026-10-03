"""Stable host-owned owner ids for workspace-write participants."""

from __future__ import annotations

from hashlib import sha256


def owner_id_for_participant(conversation_id: str, participant_id: str) -> str:
    """Derive the host-owned clone id for one participant (always OWNER_ID_RE)."""

    digest = sha256(f"{conversation_id}\0{participant_id}".encode()).hexdigest()[:20]
    return f"p-{digest}"


__all__ = ["owner_id_for_participant"]
