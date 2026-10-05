"""Working-directory to room bindings.

Local file only; the binding never touches the server. Stored as
``{cwd: conversation_id}`` under
``${XDG_CONFIG_HOME:-~/.config}/xmuse-ctl/bindings.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def bindings_dir() -> Path:
    """Directory holding the bindings file (0700)."""
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    if raw.strip() != "":
        base = Path(raw).expanduser()
    else:
        base = Path.home() / ".config"
    return base / "xmuse-ctl"


def bindings_path() -> Path:
    """Full path of the bindings file."""
    return bindings_dir() / "bindings.json"


def load_bindings() -> dict[str, str]:
    """Read ``{cwd: conversation_id}``; corrupt data reads as empty."""
    path = bindings_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str) and key != "" and value != "":
            out[key] = value
    return out


def save_bindings(bindings: dict[str, str]) -> None:
    """Write bindings atomically; file 0600, directory 0700."""
    target_dir = bindings_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, 0o700)
    tmp = target_dir / ("bindings.json.tmp." + str(os.getpid()))
    try:
        tmp.write_text(
            json.dumps(bindings, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, target_dir / "bindings.json")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
