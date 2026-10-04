"""Bubblewrap sandbox for the standalone Antigravity CLI (``agy``).

``agy`` runs its own tools without asking the client, so unattended turns use
``--dangerously-skip-permissions`` strictly inside this sandbox.  The design
is an allowlist over ``$HOME``: the whole filesystem is bound read-only,
``/tmp`` is a private tmpfs, ``$HOME`` itself is masked, and only agy's own
state (``~/.gemini/antigravity-cli``) and config (``~/.gemini/config`` plus a
generated per-session MCP file) are re-exposed.  On WSL the Windows drives
(``/mnt/c`` and the other drvfs mounts) are masked before any re-bind, so a
workspace on one stays reachable.  The Room MCP stdio bridge is
mounted read-only at ``/tmp/xmuse-bridge/room_mcp_stdio.py`` and reached by
agy through its ``call_mcp_tool`` tool.  The network stays shared because the
model API and the loopback Room MCP need it.

Known residual exposure: agy's own credential necessarily stays readable to
its own shell inside the sandbox; nothing else credential-like is.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from xmuse_core.chat.room_opencode_sandbox import drive_masks
from xmuse_core.chat.room_workspace_sandbox import (
    ROOM_WORKSPACE_WRITE_CONFINEMENT as ROOM_AGY_OWNER_CONFINEMENT,
)

ROOM_AGY_READ_ONLY_CONFINEMENT = "os_read_only_sandbox"

AGY_EXECUTABLE_ENV = "XMUSE_AGY_COMMAND"
AGY_MODEL_ENV = "XMUSE_AGY_MODEL"
AGY_DEFAULT_MODEL = "gemini-3.8-flash-high"

_AGY_BRIDGE_DEST = Path("/tmp/xmuse-bridge/room_mcp_stdio.py")
_AGY_MCP_CONFIG_DEST_REL = Path(".gemini/config/mcp_config.json")
_AGY_CONFIG_DIR_REL = Path(".gemini/config")
_AGY_STATE_DIR_REL = Path(".gemini/antigravity-cli")


def resolve_agy_executable(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Locate the agy CLI: explicit override, then PATH."""

    source = os.environ if environ is None else environ
    override = str(source.get(AGY_EXECUTABLE_ENV) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    found = which("agy")
    return Path(found) if found else None


def resolve_agy_python3(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Locate a system python3 outside $HOME for the Room MCP stdio bridge."""

    source = os.environ if environ is None else environ
    home = Path(str(source.get("HOME") or Path.home())).expanduser().resolve()
    found = which("python3")
    if not found:
        return None
    candidate = Path(found).expanduser().resolve()
    if candidate == home or candidate.is_relative_to(home):
        return None
    return candidate


def resolve_agy_model(environ: Mapping[str, str] | None = None) -> str:
    """Read the agy model name, defaulting to the pinned contributor model."""

    source = os.environ if environ is None else environ
    return str(source.get(AGY_MODEL_ENV) or "").strip() or AGY_DEFAULT_MODEL


def write_agy_mcp_config(path: Path | str, *, python3: Path | str, room_mcp_url: str) -> Path:
    """Write the agy MCP config file mounting the Room bridge; return the path."""

    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mcpServers": {
            "xmuse-room": {
                "command": str(python3),
                "args": [str(_AGY_BRIDGE_DEST), "--url", str(room_mcp_url)],
            }
        }
    }
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def build_agy_sandbox_command(
    *,
    bwrap: Path,
    agy: Path,
    home: Path,
    workspace: Path,
    workspace_writable: bool,
    mcp_config: Path,
    bridge_script: Path,
    python3: Path,
    agy_args: Sequence[str],
    masked_paths: Iterable[Path] = (),
    readonly_binds: Sequence[tuple[Path, Path]] = (),
    drive_mounts: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Return the bubblewrap argv that runs ``agy *agy_args`` confined.

    ``agy_args`` are the raw agy CLI arguments (``--conversation`` included by
    the caller when resuming).  ``readonly_binds`` mounts host directories
    read-only at destinations strictly inside the workspace (the board view).
    ``drive_mounts`` overrides Windows drive detection (``None`` detects).
    """

    if not agy_args or not all(isinstance(part, str) and part for part in agy_args):
        raise ValueError("room_agy_agent_argv_invalid")

    # Mount on the resolved home: bwrap cannot mount over a symlinked $HOME.
    home_resolved = home.expanduser().resolve()
    home_expanded = home_resolved
    workspace_resolved = workspace.expanduser().resolve()
    if not workspace_resolved.is_dir():
        raise ValueError("room_agy_workspace_unsafe")
    if workspace_resolved == Path("/") or workspace_resolved == home_resolved:
        raise ValueError("room_agy_workspace_unsafe")
    if home_resolved.is_relative_to(workspace_resolved):
        raise ValueError("room_agy_workspace_unsafe")

    binds: list[tuple[Path, Path]] = []
    for source, destination in readonly_binds:
        source_resolved = Path(source).expanduser().resolve()
        destination_path = Path(destination)
        if (
            not source_resolved.is_dir()
            or not destination_path.is_absolute()
            or ".." in destination_path.parts
            or destination_path.resolve() != destination_path
            or destination_path == workspace_resolved
            or not destination_path.is_relative_to(workspace_resolved)
        ):
            raise ValueError("room_agy_bind_unsafe")
        binds.append((source_resolved, destination_path))

    agy_resolved = Path(agy).expanduser().resolve()
    python3_resolved = Path(python3).expanduser().resolve()
    python3_outside_home = (
        python3_resolved != home_resolved and not python3_resolved.is_relative_to(home_resolved)
    )
    if not python3_outside_home:
        raise ValueError("room_agy_python_unavailable")

    mcp_config_path = Path(mcp_config).expanduser()
    bridge_path = Path(bridge_script).expanduser()

    masked: list[Path] = [Path(item).expanduser() for item in masked_paths]
    drives = drive_masks(drive_mounts)
    unique: list[Path] = []
    seen: set[Path] = set(drives)
    for candidate in masked:
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    # Masks that enclose the workspace come first so the workspace can be
    # re-bound over them; masks inside the workspace stay hidden after it.
    enclosing = [path for path in unique if workspace_resolved.is_relative_to(path)]
    others = [path for path in unique if path not in enclosing]

    argv: list[str] = [
        str(bwrap),
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
    ]
    # Windows drives and masks enclosing the workspace go before every re-bind
    # (agy itself, its state, the workspace).
    for path in [*drives, *enclosing]:
        argv.extend(_mask(path))
    # Allowlisted home: mask everything, then re-expose only agy's own state
    # and config.
    argv.extend(["--tmpfs", str(home_expanded)])
    argv.extend(["--ro-bind", str(agy_resolved), str(agy_resolved)])
    state_dir = home_expanded / _AGY_STATE_DIR_REL
    state_dir.mkdir(parents=True, exist_ok=True)
    argv.extend(["--bind", str(state_dir.resolve()), str(state_dir)])
    # The config dir is rebuilt on the home tmpfs entry by entry (read-only), so
    # the generated MCP file can be mounted even when the operator never
    # created one: a read-only bound dir cannot gain a new mount point.
    config_dir = home_expanded / _AGY_CONFIG_DIR_REL
    mcp_dest = home_expanded / _AGY_MCP_CONFIG_DEST_REL
    argv.extend(["--dir", str(config_dir)])
    if config_dir.is_dir():
        for entry in sorted(config_dir.iterdir()):
            if entry.name == mcp_dest.name or not entry.exists():
                continue
            argv.extend(["--ro-bind", str(entry.resolve()), str(config_dir / entry.name)])
    argv.extend(["--ro-bind", str(mcp_config_path.resolve()), str(mcp_dest)])
    argv.extend(["--ro-bind", str(bridge_path.resolve()), str(_AGY_BRIDGE_DEST)])
    if workspace_writable:
        argv.extend(["--bind", str(workspace_resolved), str(workspace_resolved)])
    else:
        argv.extend(["--ro-bind", str(workspace_resolved), str(workspace_resolved)])
    for source_resolved, destination_path in binds:
        argv.extend(["--ro-bind", str(source_resolved), str(destination_path)])
    for path in others:
        argv.extend(_mask(path))
    argv.extend(
        [
            "--setenv",
            "HOME",
            str(home_expanded),
            "--chdir",
            str(workspace_resolved),
            "--die-with-parent",
            "--new-session",
        ]
    )
    argv.extend([str(agy_resolved), *agy_args])
    return tuple(argv)


def _mask(path: Path) -> list[str]:
    if path.is_dir():
        return ["--tmpfs", str(path)]
    return ["--ro-bind", "/dev/null", str(path)]


__all__ = [
    "AGY_DEFAULT_MODEL",
    "AGY_EXECUTABLE_ENV",
    "AGY_MODEL_ENV",
    "ROOM_AGY_OWNER_CONFINEMENT",
    "ROOM_AGY_READ_ONLY_CONFINEMENT",
    "build_agy_sandbox_command",
    "resolve_agy_executable",
    "resolve_agy_model",
    "resolve_agy_python3",
    "write_agy_mcp_config",
]
