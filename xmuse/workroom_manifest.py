"""Workroom manifest persistence without lifecycle ownership.

This module deliberately does not acquire the Workroom lifecycle lock.  Callers that
coordinate processes must hold that lock while performing generation-sensitive writes.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xmuse_workroom_runtime/v1"


class ManifestError(RuntimeError):
    """A malformed or unsupported Workroom manifest."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def read_manifest(
    path: Path,
    *,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any] | None:
    """Read a manifest without creating its parent or otherwise mutating the root."""

    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError("invalid_manifest", f"invalid Workroom manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise ManifestError("invalid_manifest", f"unsupported Workroom manifest: {path}")
    return payload


def atomic_write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably replace a manifest; lifecycle serialization remains the caller's job."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def base_manifest(
    *,
    generation: str,
    version: str,
    started_at: str,
    repo_root: Path,
    xmuse_root: Path,
    manager_pid: int,
    manager_start_identity: str,
    runner_pid_file: Path,
    mcp_pid_file: Path,
    runner_status_file: Path,
    execution_workspace: Path,
    execution_gate_profile: Mapping[str, Any],
    memory_enabled: bool,
) -> dict[str, Any]:
    """Build the initial manifest value from already validated lifecycle inputs."""

    return {
        "schema_version": SCHEMA_VERSION,
        "generation": generation,
        "state": "starting",
        "version": version,
        "started_at": started_at,
        "updated_at": started_at,
        "repo_root": str(repo_root),
        "xmuse_root": str(xmuse_root),
        "manager": {
            "pid": manager_pid,
            "start_identity": manager_start_identity,
        },
        "services": {},
        "supervised": {
            "room_runner_pid_file": str(runner_pid_file),
            "room_mcp_pid_file": str(mcp_pid_file),
            "room_runner_status_file": str(runner_status_file),
        },
        "execution": {
            "workspace_root": str(execution_workspace),
            "gate_profile": copy.deepcopy(dict(execution_gate_profile)),
        },
        "features": {"memoryos": bool(memory_enabled)},
    }


def update_manifest(
    manifest: Mapping[str, Any],
    *,
    updated_at: str,
    state: str | None = None,
) -> dict[str, Any]:
    """Return an updated manifest value without mutating the caller's mapping."""

    updated = copy.deepcopy(dict(manifest))
    if state is not None:
        updated["state"] = state
    updated["updated_at"] = updated_at
    return updated


def generation_is_current(
    current: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> bool:
    """Apply the existing CAS rule used while the caller owns the lifecycle lock."""

    return current is None or current.get("generation") == candidate.get("generation")


def write_if_generation_current(
    path: Path,
    manifest: Mapping[str, Any],
    *,
    state: str,
    updated_at: str,
    terminal_at: str | None = None,
) -> dict[str, Any] | None:
    """Perform the manifest CAS while an external lifecycle lock is held.

    ``None`` means a newer generation owns the root and no write occurred.
    """

    current = read_manifest(path)
    if not generation_is_current(current, manifest):
        return None
    updated = update_manifest(manifest, updated_at=updated_at, state=state)
    if state in {"stopped", "failed"}:
        updated[f"{state}_at"] = terminal_at if terminal_at is not None else updated_at
    atomic_write_manifest(path, updated)
    return updated
