"""xmuse chat-plane models and persistence."""

from xmuse_core.chat.acceptance_spine import (
    AcceptanceSpine,
    AcceptanceSpineStatus,
    AcceptanceSpineStore,
)
from xmuse_core.chat.models import (
    ChatMessage,
    Conversation,
    Proposal,
    ProposalStatus,
    ResolutionStatus,
    StructuredResolution,
)
from xmuse_core.chat.store import ChatStore


def __getattr__(name: str):
    if name in {"PeerForkRecord", "PeerForkStore", "PeerForkSummary"}:
        from xmuse_core.chat.peer_forks import (
            PeerForkRecord,
            PeerForkStore,
            PeerForkSummary,
        )

        values = {
            "PeerForkRecord": PeerForkRecord,
            "PeerForkStore": PeerForkStore,
            "PeerForkSummary": PeerForkSummary,
        }
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AcceptanceSpine",
    "AcceptanceSpineStatus",
    "AcceptanceSpineStore",
    "ChatMessage",
    "ChatStore",
    "PeerForkRecord",
    "PeerForkStore",
    "PeerForkSummary",
    "Conversation",
    "Proposal",
    "ProposalStatus",
    "ResolutionStatus",
    "StructuredResolution",
]
