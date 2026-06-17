from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.models import ChatInboxItem, ChatMessage


class PeerChatError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class PeerMessageResult:
    message: ChatMessage
    inbox_items: list[ChatInboxItem]

    def to_json(self) -> dict[str, Any]:
        return {
            "message": self.message.model_dump(mode="json"),
            "inbox_items": [item.model_dump(mode="json") for item in self.inbox_items],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> PeerMessageResult:
        return cls(
            message=ChatMessage(**payload["message"]),
            inbox_items=[ChatInboxItem(**item) for item in payload["inbox_items"]],
        )
