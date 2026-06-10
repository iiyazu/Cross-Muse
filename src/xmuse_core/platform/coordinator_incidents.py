from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COORDINATOR_INCIDENTS_FILENAME = "coordinator_incidents.jsonl"
COORDINATOR_INCIDENT_KINDS = ("dead_letter", "degraded", "lifecycle")


def summarize_coordinator_incidents(
    *,
    xmuse_root: Path | None,
    active_runner_ids: set[str] | None = None,
    latest_limit: int = 5,
) -> dict[str, Any]:
    counts = {kind: 0 for kind in COORDINATOR_INCIDENT_KINDS}
    active_counts = {kind: 0 for kind in COORDINATOR_INCIDENT_KINDS}
    scoped_runner_ids = sorted(active_runner_ids or set())
    empty = {
        "path": None,
        "counts": counts,
        "active_runner_ids": scoped_runner_ids,
        "active_counts": active_counts,
        "latest_dead_letters": [],
        "latest_degraded": [],
        "latest_lifecycle": [],
        "latest_active_dead_letters": [],
        "latest_active_degraded": [],
        "read_error": None,
    }
    if xmuse_root is None:
        return empty

    incident_path = xmuse_root / COORDINATOR_INCIDENTS_FILENAME
    empty["path"] = str(incident_path)
    if not incident_path.exists():
        return empty

    try:
        records = _read_coordinator_incident_records(incident_path)
    except OSError as exc:
        empty["read_error"] = {"type": type(exc).__name__, "error": str(exc)}
        return empty
    active_records = [
        record for record in records if record.get("runner_id") in scoped_runner_ids
    ]
    for record in records:
        kind = record.get("kind")
        if kind in counts:
            counts[str(kind)] += 1
    for record in active_records:
        kind = record.get("kind")
        if kind in active_counts:
            active_counts[str(kind)] += 1
    return {
        "path": str(incident_path),
        "counts": counts,
        "active_runner_ids": scoped_runner_ids,
        "active_counts": active_counts,
        "latest_dead_letters": _latest_incidents(
            records, kind="dead_letter", limit=latest_limit
        ),
        "latest_degraded": _latest_incidents(
            records, kind="degraded", limit=latest_limit
        ),
        "latest_lifecycle": _latest_incidents(
            records, kind="lifecycle", limit=latest_limit
        ),
        "latest_active_dead_letters": _latest_incidents(
            active_records, kind="dead_letter", limit=latest_limit
        ),
        "latest_active_degraded": _latest_incidents(
            active_records, kind="degraded", limit=latest_limit
        ),
        "read_error": None,
    }


def _read_coordinator_incident_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _latest_incidents(
    records: list[dict[str, Any]],
    *,
    kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    matching = [record for record in records if record.get("kind") == kind]
    return list(reversed(matching[-limit:]))
