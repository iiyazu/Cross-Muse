"""Dashboard audit, error, and state-history read helpers."""
from __future__ import annotations

import json
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status


def _json_path(base_dir: Path, name: str) -> Path:
    return base_dir / name


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"invalid JSON in {path.name}: {exc.msg}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not read {path.name}: {exc}",
        ) from exc


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_errors(base_dir: Path) -> list[Any]:
    data = _read_json(_json_path(base_dir, "error_knowledge.json"), {"entries": []})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("entries", "errors"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _read_model_entries(base_dir: Path, file_name: str, key: str) -> list[Any]:
    data = _read_json(base_dir / "read_models" / file_name, {key: []})
    if not isinstance(data, dict):
        return []
    entries = data.get(key, [])
    return entries if isinstance(entries, list) else []


def _read_audit_events(
    base_dir: Path,
    *,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    data = _read_json(_json_path(base_dir, "audit_events.json"), {"events": []})
    if not isinstance(data, dict):
        return []
    raw = data.get("events", [])
    if not isinstance(raw, list):
        return []

    results: list[dict[str, Any]] = []
    for event in raw:
        if not isinstance(event, dict):
            continue
        if event_type is not None and event.get("event_type") != event_type:
            continue
        if since is not None or until is not None:
            ts = _parse_timestamp(event.get("timestamp"))
            if ts is None:
                continue
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
        results.append(event)

    return results


def _read_state_history(
    base_dir: Path,
    *,
    lane_id: str | None = None,
    state_key: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    data = _read_json(_json_path(base_dir, "state_history.json"), {"snapshots": []})
    if not isinstance(data, dict):
        return []
    raw = data.get("snapshots", [])
    if not isinstance(raw, list):
        return []

    results: list[dict[str, Any]] = []
    for snapshot in raw:
        if not isinstance(snapshot, dict):
            continue
        if lane_id is not None and snapshot.get("lane_id") != lane_id:
            continue
        if state_key is not None and snapshot.get("state_key") != state_key:
            continue
        if since is not None or until is not None:
            ts = _parse_timestamp(snapshot.get("timestamp"))
            if ts is None:
                continue
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
        results.append(snapshot)

    return results
