"""Participant-owned Codex sub-session scopes.

Codex native Goal turns and Room outcome turns have different lifecycle and tool
requirements. Keeping their provider threads distinct prevents native Goal state
from changing the sole MCP surface used to commit Room truth, while both sessions
remain bound to the same durable participant identity.
"""

ROOM_DELIVERY_SESSION_SCOPE = "room_delivery_v1"
ROOM_NATIVE_SESSION_SCOPE = "room_native_v1"


__all__ = ["ROOM_DELIVERY_SESSION_SCOPE", "ROOM_NATIVE_SESSION_SCOPE"]
