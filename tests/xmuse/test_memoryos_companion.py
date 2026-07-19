from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xmuse.install_contracts import (
    INSTALL_BUNDLE_SCHEMA,
    INSTALL_PLATFORM,
    INSTALL_PYTHON_ABI,
    INSTALL_RECEIPT_SCHEMA,
)
from xmuse.memoryos_companion import (
    COMPANION_CAPABILITY_SCHEMA,
    MemoryOSCompanionError,
    verify_companion,
)


def _write_companion(root: Path) -> None:
    model_cache = root / "payload" / "memoryos" / "model-cache"
    model_cache.mkdir(parents=True)
    (model_cache / "model.bin").write_bytes(b"model")
    capability = {
        "schema_version": COMPANION_CAPABILITY_SCHEMA,
        "profile": "full-local",
        "fastembed_model": "BAAI/bge-small-en-v1.5",
        "hybrid": {"bm25": True, "fastembed": True, "rrf": True},
    }
    capability_path = root / "payload" / "memoryos" / "capability.json"
    capability_path.write_text(json.dumps(capability), encoding="utf-8")
    executable = root / ".venv" / "bin" / "memoryos"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    entries = []
    for path in (root / "payload").rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": len(raw),
                }
            )
    manifest = {
        "schema_version": INSTALL_BUNDLE_SCHEMA,
        "bundle_kind": "memoryos",
        "version": "0.2.1",
        "platform": INSTALL_PLATFORM,
        "python_abi": INSTALL_PYTHON_ABI,
        "files": entries,
        "memory": {
            "memoryos_wheel": entries[0]["path"],
            "capability_manifest": "payload/memoryos/capability.json",
            "model_cache_dir": "payload/memoryos/model-cache",
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "install-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": INSTALL_RECEIPT_SCHEMA,
                "bundle_kind": "memoryos",
                "version": "0.2.1",
                "platform": INSTALL_PLATFORM,
            }
        ),
        encoding="utf-8",
    )


def test_verified_companion_requires_receipt_and_payload_proof(tmp_path: Path) -> None:
    root = tmp_path / "memoryos"
    _write_companion(root)

    companion = verify_companion(root)

    assert companion.profile == "full-local"
    assert companion.executable == root / ".venv" / "bin" / "memoryos"
    assert companion.capability_digest.startswith("sha256:")

    (root / "payload" / "memoryos" / "model-cache" / "model.bin").write_bytes(b"tampered")
    with pytest.raises(MemoryOSCompanionError, match="memoryos_companion_payload_invalid"):
        verify_companion(root)


def test_symlinked_companion_is_not_discovered(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _write_companion(real)
    link = tmp_path / "memoryos"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(MemoryOSCompanionError, match="memoryos_companion_missing"):
        verify_companion(link)


def test_invalid_capability_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "memoryos"
    _write_companion(root)
    capability_path = root / "payload" / "memoryos" / "capability.json"
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    capability["hybrid"]["bm25"] = False
    raw = json.dumps(capability).encode()
    capability_path.write_bytes(raw)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    capability_entry = next(
        item for item in manifest["files"] if item["path"] == "payload/memoryos/capability.json"
    )
    capability_entry["sha256"] = hashlib.sha256(raw).hexdigest()
    capability_entry["size"] = len(raw)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(MemoryOSCompanionError, match="memoryos_companion_capability_invalid"):
        verify_companion(root)
