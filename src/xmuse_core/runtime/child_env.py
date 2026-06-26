from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

_DEFAULT_CHILD_TMPDIR = "/tmp"
_CHILD_TMPDIR_OVERRIDE = "XMUSE_CHILD_TMPDIR"
_TEMP_ENV_NAMES = ("TMPDIR", "TMP", "TEMP")


def normalize_child_temp_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return child-process env with a Linux-native temp dir under WSL."""

    runtime_env = dict(env)
    override = runtime_env.get(_CHILD_TMPDIR_OVERRIDE)
    if override:
        target = override
    elif _has_windows_mount_temp(runtime_env):
        target = _DEFAULT_CHILD_TMPDIR
    else:
        return runtime_env

    Path(target).mkdir(parents=True, exist_ok=True)
    for name in _TEMP_ENV_NAMES:
        runtime_env[name] = target
    return runtime_env


def _has_windows_mount_temp(env: Mapping[str, str]) -> bool:
    return any(_is_windows_mount_path(env.get(name)) for name in _TEMP_ENV_NAMES)


def _is_windows_mount_path(value: str | None) -> bool:
    if not value:
        return False
    parts = Path(value).parts
    return (
        len(parts) >= 3
        and parts[0] == "/"
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    )
