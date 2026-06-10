from __future__ import annotations

import inspect
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EventBus:
    def __init__(self, *, audit_log_path: Path | str | None = None) -> None:
        self._subscribers: dict[str, list[Callable]] = {}
        self._audit_log_path = (
            Path(audit_log_path) if audit_log_path is not None else None
        )

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self._append_audit_event(event_type, payload)
        for handler in self._subscribers.get(event_type, []):
            if inspect.iscoroutinefunction(handler):
                await handler(payload)
            else:
                handler(payload)

    def _append_audit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._audit_log_path is None:
            return
        path = self._audit_log_path
        data = _read_json(path, {"events": []})
        events = data.setdefault("events", [])
        events.append(
            {
                "event_id": f"evt-{uuid.uuid4().hex[:12]}",
                "event_type": event_type,
                "timestamp": _utc_timestamp(),
                "metadata": payload,
            }
        )
        _write_json(path, data)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
