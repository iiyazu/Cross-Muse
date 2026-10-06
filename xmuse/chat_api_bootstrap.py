"""Safe first-load capability projection for the Workbench."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from xmuse.memoryos_companion import MemoryOSCompanionError, discover_managed_companion
from xmuse.provider_capabilities import ROOM_PROVIDER_KINDS, detect_provider_capabilities
from xmuse_core.runtime.sqlite_connection import ClosingConnection

BOOTSTRAP_SCHEMA = "xmuse_bootstrap_projection/v1"


def _provider_projection(
    provider: Callable[[], Mapping[str, Mapping[str, object]]] | None,
) -> dict[str, dict[str, object]]:
    """Whitelist provider facts; executable paths and addresses never project."""

    try:
        detected = provider() if provider is not None else detect_provider_capabilities()
    except Exception:  # pragma: no cover - detection failure is reported as unavailable
        detected = {}
    projection: dict[str, dict[str, object]] = {}
    for kind in ROOM_PROVIDER_KINDS:
        record = detected.get(kind)
        record = record if isinstance(record, Mapping) else {}
        projection[kind] = {
            "available": bool(record.get("available", False)),
            "enabled": bool(record.get("enabled", False)),
            "confinement": str(record.get("confinement") or "unknown"),
        }
    return projection


def _has_rooms(root: Path) -> bool:
    db_path = root / "chat.db"
    if not db_path.is_file():
        return False
    try:
        with sqlite3.connect(db_path, factory=ClosingConnection) as conn:
            return conn.execute("select 1 from conversations limit 1").fetchone() is not None
    except sqlite3.DatabaseError:
        return False


def register_bootstrap_route(
    app: FastAPI,
    *,
    root: Path,
    memory_status_provider: Callable[[], Mapping[str, Any]],
    execution_profile_provider: Callable[[], Mapping[str, Any]],
    provider_capabilities_provider: (
        Callable[[], Mapping[str, Mapping[str, object]]] | None
    ) = None,
) -> None:
    @app.get("/api/chat/bootstrap")
    def bootstrap() -> dict[str, object]:
        try:
            memory_status = dict(memory_status_provider())
        except Exception:  # pragma: no cover - optional runtime status is non-authoritative
            memory_status = {"state": "degraded", "code": "memoryos_status_unavailable"}
        try:
            companion = discover_managed_companion()
            companion_state = "installed" if companion is not None else "missing"
            companion_version = companion.version if companion is not None else None
            capability_digest = companion.capability_digest if companion is not None else None
        except MemoryOSCompanionError as exc:
            companion_state = "invalid"
            companion_version = None
            capability_digest = None
            memory_status.setdefault("code", exc.code)
        profile = dict(execution_profile_provider())
        profile.pop("profile_digest", None)
        profile.pop("repository_manifest_digest", None)
        profile.pop("toolchain_capability_digest", None)
        codex_available = shutil.which("codex") is not None
        providers = _provider_projection(provider_capabilities_provider)
        has_rooms = _has_rooms(root)
        recommended = (
            "open_room"
            if has_rooms
            else (
                "repair_memory"
                if companion_state == "invalid"
                else "install_memory"
                if companion_state == "missing"
                else "create_room"
            )
        )
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "has_rooms": has_rooms,
            "codex": {"launcher_available": codex_available},
            "providers": providers,
            "memory": {
                "mode": "auto",
                "companion": companion_state,
                "version": companion_version,
                "profile": ("full-local" if companion_state == "installed" else "unavailable"),
                "runtime": {
                    "state": str(memory_status.get("state") or "unknown"),
                    "code": str(memory_status.get("code") or "unknown"),
                },
                "capability_digest": capability_digest,
            },
            "execution": {
                "profile_id": profile.get("profile_id"),
                "revision": profile.get("revision"),
                "readiness": profile.get("readiness", {"state": "unknown", "ready": False}),
            },
            "recommended_action": recommended,
        }
