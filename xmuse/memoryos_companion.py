"""Verification of the installed, optional MemoryOS companion.

The browser and Workroom never discover arbitrary executables.  This module only
examines the sibling ``memoryos`` payload installed beneath the active xmuse
version and returns a path after proving its receipt and full-local capability
metadata.  The payload remains optional at install time; a verified payload is
selected automatically by the Workroom ``auto`` memory mode.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse.install_contracts import (
    INSTALL_PLATFORM,
    INSTALL_RECEIPT_SCHEMA,
    parse_manifest,
    sha256_file,
)

COMPANION_CAPABILITY_SCHEMA = "xmuse_memoryos_bundle_capability/v1"


class MemoryOSCompanionError(RuntimeError):
    """Stable, safe companion verification failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MemoryOSCompanion:
    root: Path
    executable: Path
    version: str
    profile: str
    capability_digest: str


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryOSCompanionError(code) from exc
    if not isinstance(payload, dict):
        raise MemoryOSCompanionError(code)
    return payload


def _regular_file(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise MemoryOSCompanionError(code)


def _default_companion_root() -> Path:
    # Installed layout: <prefix>/active/.venv/bin/python and
    # <prefix>/active/memoryos/.venv/bin/memoryos.
    return Path(sys.prefix).resolve().parent / "memoryos"


def verify_companion(root: Path) -> MemoryOSCompanion:
    """Verify one installer-owned companion without starting it."""

    candidate = root.expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise MemoryOSCompanionError("memoryos_companion_missing")
    root = candidate.resolve(strict=True)
    manifest_path = root / "manifest.json"
    receipt_path = root / "install-receipt.json"
    _regular_file(manifest_path, "memoryos_companion_manifest_invalid")
    _regular_file(receipt_path, "memoryos_companion_receipt_invalid")
    try:
        manifest = parse_manifest(manifest_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise MemoryOSCompanionError("memoryos_companion_manifest_invalid") from exc
    if manifest.bundle_kind != "memoryos" or manifest.capability_manifest is None:
        raise MemoryOSCompanionError("memoryos_companion_manifest_invalid")
    for entry in manifest.files:
        path = root.joinpath(*entry.path.split("/"))
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise MemoryOSCompanionError("memoryos_companion_payload_invalid") from exc
        if (
            path.is_symlink()
            or not path.is_file()
            or not resolved.is_relative_to(root)
            or resolved != path.absolute()
        ):
            raise MemoryOSCompanionError("memoryos_companion_payload_invalid")
        try:
            if path.stat().st_size != entry.size or sha256_file(path) != entry.sha256:
                raise MemoryOSCompanionError("memoryos_companion_payload_invalid")
        except OSError as exc:
            raise MemoryOSCompanionError("memoryos_companion_payload_invalid") from exc
    capability_path = root.joinpath(*manifest.capability_manifest.split("/"))
    _regular_file(capability_path, "memoryos_companion_capability_invalid")
    receipt = _read_json(receipt_path, "memoryos_companion_receipt_invalid")
    if receipt != {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "bundle_kind": "memoryos",
        "version": manifest.version,
        "platform": INSTALL_PLATFORM,
    }:
        raise MemoryOSCompanionError("memoryos_companion_receipt_invalid")
    capability = _read_json(capability_path, "memoryos_companion_capability_invalid")
    if (
        capability.get("schema_version") != COMPANION_CAPABILITY_SCHEMA
        or capability.get("profile") != "full-local"
        or capability.get("fastembed_model") != "BAAI/bge-small-en-v1.5"
        or capability.get("hybrid") != {"bm25": True, "fastembed": True, "rrf": True}
    ):
        raise MemoryOSCompanionError("memoryos_companion_capability_invalid")
    model_cache = root / (manifest.model_cache_dir or "")
    if model_cache.is_symlink() or not model_cache.is_dir():
        raise MemoryOSCompanionError("memoryos_companion_capability_invalid")
    executable = root / ".venv" / "bin" / "memoryos"
    _regular_file(executable, "memoryos_companion_executable_invalid")
    if not os.access(executable, os.X_OK):
        raise MemoryOSCompanionError("memoryos_companion_executable_invalid")
    capability_digest = hashlib.sha256(
        json.dumps(capability, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MemoryOSCompanion(
        root=root,
        executable=executable,
        version=manifest.version,
        profile="full-local",
        capability_digest=f"sha256:{capability_digest}",
    )


def discover_managed_companion() -> MemoryOSCompanion | None:
    """Return the verified installed companion, or ``None`` when absent."""

    root = _default_companion_root()
    if not root.exists() and not root.is_symlink():
        return None
    return verify_companion(root)


def managed_companion_executable() -> Path | None:
    companion = discover_managed_companion()
    return companion.executable if companion is not None else None
