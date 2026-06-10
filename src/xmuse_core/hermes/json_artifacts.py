from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_json_bytes(payload: Any, *, exclude_keys: set[str] | None = None) -> bytes:
    """Return stable JSON bytes for digest-bound control-plane artifacts."""
    if exclude_keys and isinstance(payload, dict):
        payload = {key: value for key, value in payload.items() if key not in exclude_keys}
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_json_digest(payload: Any, *, exclude_keys: set[str] | None = None) -> str:
    return (
        "sha256:"
        + hashlib.sha256(canonical_json_bytes(payload, exclude_keys=exclude_keys)).hexdigest()
    )


def file_json_digest(path: str | Path) -> str:
    return canonical_json_digest(read_json(path))


def atomic_write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(target)


def atomic_write_json(path: str | Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


_read_json = read_json
_atomic_write_text = atomic_write_text
_atomic_write_json = atomic_write_json
