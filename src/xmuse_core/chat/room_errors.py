"""Errors exposed by the Room application boundary."""

from __future__ import annotations

from typing import Any


class RoomApplicationError(RuntimeError):
    """Stable, client-safe failure raised by Room application services."""

    code: str
    message: str
    details: dict[str, Any]

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
