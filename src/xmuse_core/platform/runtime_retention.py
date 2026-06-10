from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

TRANSIENT_RUNTIME_DIRS = ("logs", "work", "history")
DURABLE_AUTHORITY_NAMES = {
    "chat.db",
    "planning_events.sqlite3",
    "feature_lanes.json",
}
DURABLE_AUTHORITY_DIRS = {
    "lane_graphs",
    "feature_plans",
    "read_models",
}


class RuntimeCleanupReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deleted_relative_paths: list[str] = Field(default_factory=list)
    preserved_authority_paths: list[str] = Field(default_factory=list)


def cleanup_runtime_state(root: Path | str, *, max_age_seconds: int) -> RuntimeCleanupReport:
    base = Path(root)
    cutoff = time.time() - max_age_seconds
    deleted: list[str] = []
    preserved: list[str] = []
    for directory_name in TRANSIENT_RUNTIME_DIRS:
        directory = base / directory_name
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative = path.relative_to(base).as_posix()
            if _is_durable_authority_path(path, base):
                preserved.append(relative)
                continue
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                deleted.append(relative)
    for path in _durable_authority_paths(base):
        if path.exists():
            preserved.append(path.relative_to(base).as_posix())
    return RuntimeCleanupReport(
        deleted_relative_paths=sorted(deleted),
        preserved_authority_paths=sorted(set(preserved)),
    )


def _durable_authority_paths(base: Path) -> list[Path]:
    paths = [base / name for name in DURABLE_AUTHORITY_NAMES]
    for directory_name in DURABLE_AUTHORITY_DIRS:
        directory = base / directory_name
        if directory.exists():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    return paths


def _is_durable_authority_path(path: Path, base: Path) -> bool:
    try:
        relative = path.relative_to(base)
    except ValueError:
        return False
    parts = relative.parts
    return relative.name in DURABLE_AUTHORITY_NAMES or (
        bool(parts) and parts[0] in DURABLE_AUTHORITY_DIRS
    )
