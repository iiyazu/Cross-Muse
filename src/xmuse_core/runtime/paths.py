from __future__ import annotations

import os
from pathlib import Path

XMUSE_ROOT_ENV = "XMUSE_ROOT"


def resolve_xmuse_root(value: str | Path | None, *, fallback: str | Path) -> Path:
    """Resolve the authoritative xmuse runtime root.

    ``XMUSE_ROOT`` intentionally wins over embedded repository-relative defaults
    so xmuse can be moved out of the MemoryOS checkout without editing entry
    points.
    """

    configured = os.environ.get(XMUSE_ROOT_ENV)
    candidate = configured if configured else value
    if candidate is None:
        candidate = fallback
    return Path(candidate).expanduser().resolve()


def default_xmuse_root(fallback: str | Path) -> Path:
    return resolve_xmuse_root(None, fallback=fallback)


__all__ = ["XMUSE_ROOT_ENV", "default_xmuse_root", "resolve_xmuse_root"]
