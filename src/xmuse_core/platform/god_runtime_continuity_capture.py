from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def capture_selected_god_runtime_continuity_artifact(
    *,
    conversation_id: str,
    selection_store_path: str | Path,
    registry_path: str | Path,
    output_path: str | Path,
    registration_store_path: str | Path | None = None,
    now_utc: str | None = None,
    heartbeat_ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Capture selected GOD runtime continuity from durable local stores."""
    registration_store = (
        GodCliRegistrationStore(Path(registration_store_path))
        if registration_store_path is not None
        else None
    )
    god_cli_registry = build_default_god_cli_registry(
        extra_registrations=registration_store.list_registrations()
        if registration_store is not None
        else (),
    )
    artifact = build_selected_god_runtime_continuity_view(
        conversation_id=conversation_id,
        selections=GodCliSelectionStore(Path(selection_store_path)).list_records(),
        sessions=GodSessionRegistry(registry_path).list(),
        god_cli_registry=god_cli_registry,
        now_utc=now_utc,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
    )
    _write_json(Path(output_path), artifact)
    return artifact


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


__all__ = ["capture_selected_god_runtime_continuity_artifact"]
