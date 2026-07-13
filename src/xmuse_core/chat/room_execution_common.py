"""Shared value validation for durable Room execution ledgers.

This module owns no database connection or transaction and deliberately depends on
neither the public Store nor runtime/controller code.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

RUN_STATES = frozenset(
    {
        "requested",
        "preparing",
        "staging",
        "verifying",
        "ready_to_promote",
        "promoting",
        "cancel_requested",
        "cancel_pending",
        "cancelled",
        "succeeded",
        "failed",
        "blocked",
    }
)
TERMINAL_RUN_STATES = frozenset({"cancelled", "succeeded", "failed", "blocked"})
CONTROLLER_RUN_STATES = frozenset(
    {
        "preparing",
        "staging",
        "verifying",
        "ready_to_promote",
        "promoting",
        "cancel_requested",
        "cancel_pending",
    }
)
RUN_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "preparing": frozenset({"staging", "failed", "blocked", "cancel_requested"}),
    "staging": frozenset({"verifying", "failed", "blocked", "cancel_requested"}),
    "verifying": frozenset({"ready_to_promote", "failed", "blocked", "cancel_requested"}),
    "ready_to_promote": frozenset({"promoting", "failed", "blocked", "cancel_requested"}),
    "cancel_requested": frozenset({"cancel_pending", "cancelled"}),
    "cancel_pending": frozenset({"cancelled"}),
    "promoting": frozenset({"succeeded", "blocked"}),
}
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


class RoomExecutionStoreError(ValueError):
    """Stable durable execution authority failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise RoomExecutionStoreError("room_execution_now_timezone_required")
    return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_json(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value is not None else default


def digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(json_value(value).encode('utf-8')).hexdigest()}"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def require_text(value: object, code: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise RoomExecutionStoreError(code)
    return value.strip()


def require_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise RoomExecutionStoreError(code)
    return value
