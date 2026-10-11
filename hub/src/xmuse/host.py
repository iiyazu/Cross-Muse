"""The host this hub runs on: in WSL, the distro name and the Windows user's home, derived, never hard-coded.
A Windows-native hub (D1) needs neither: its own home is the Windows home and no path is translated.

Overrides (in this order): environment XMUSE_WSL_DISTRO / XMUSE_WIN_HOME, then what WSL itself reports
(WSL_DISTRO_NAME; %USERPROFILE% through cmd.exe and wslpath). When neither works the caller gets a HostError
saying what to set, instead of a path that silently points at someone else's machine.
"""
import functools
import os
import subprocess
from pathlib import Path


class HostError(SystemExit):
    pass


def distro() -> str:
    d = os.environ.get("XMUSE_WSL_DISTRO") or os.environ.get("WSL_DISTRO_NAME")
    if not d:
        raise HostError("cannot tell the WSL distro name (WSL_DISTRO_NAME is unset: not running inside WSL?); "
                        "set XMUSE_WSL_DISTRO, e.g. XMUSE_WSL_DISTRO=Ubuntu-24.04")
    return d


@functools.cache
def _userprofile() -> Path | None:
    try:
        raw = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"], cwd="/mnt/c" if Path("/mnt/c").is_dir() else None,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if not raw or "%" in raw:
            return None
        p = subprocess.run(["wslpath", "-u", raw], capture_output=True, text=True, timeout=10).stdout.strip()
        return Path(p) if p else None
    except (OSError, subprocess.TimeoutExpired):
        return None


WINDOWS = os.name == "nt"  # Windows-native hub (D1): no WSL in between, Windows paths everywhere


def win_home() -> Path:
    if os.environ.get("XMUSE_WIN_HOME"):
        return Path(os.environ["XMUSE_WIN_HOME"])
    if WINDOWS:
        return Path.home()
    p = _userprofile()
    if p and p.is_dir():
        return p
    raise HostError("cannot find the Windows user's home (cmd.exe/wslpath unavailable, or WSL interop is off); "
                    "set XMUSE_WIN_HOME, e.g. XMUSE_WIN_HOME=/mnt/c/Users/<name>")
