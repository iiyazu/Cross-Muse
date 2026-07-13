"""Shared primitives for durable source-backed Room memory stores.

This module intentionally contains no SQLite statements or store composition.  It
is the dependency-neutral floor shared by schema, delivery, governance, and recall.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from xmuse_core.chat.room_memory_contracts import canonical_json

MEMORY_DOCUMENT_PREFIX = "xmuse-room-activity-"
MEMORY_BINDING_SCOPES = frozenset({"room", "local_user", "project"})
MEMORY_CANDIDATE_SCOPE_BY_KIND = {
    "room_fact": "room",
    "room_decision": "room",
    "user_preference": "local_user",
    "project_rule": "project",
}

_MEMORY_RETRY_BASE_SECONDS = 1
_MEMORY_RETRY_MAX_SECONDS = 30


class RoomMemoryStoreError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise RoomMemoryStoreError("room_memory_now_timezone_required")
    return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _retry_delay_seconds(failure_count: int) -> int:
    if isinstance(failure_count, bool) or failure_count < 1:
        raise RoomMemoryStoreError("room_memory_retry_count_invalid")
    exponent = min(failure_count - 1, 30)
    return min(_MEMORY_RETRY_MAX_SECONDS, _MEMORY_RETRY_BASE_SECONDS * (2**exponent))


def retry_not_before(current: datetime, failure_count: int) -> str:
    return timestamp(current + timedelta(seconds=_retry_delay_seconds(failure_count)))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_dumps(value: Any) -> str:
    return canonical_json(value)


def json_loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value is not None else default


def sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def require_text(value: object, code: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise RoomMemoryStoreError(code)
    return value.strip()
