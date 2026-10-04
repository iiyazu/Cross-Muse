"""Writable owner workspace sandbox for long-lived Room owner agents.

Each owner agent works in its own local clone with full native tools, confined by
an OS sandbox (bubblewrap): the whole filesystem is bound read-only, ``/tmp`` is a
private tmpfs, only the owner clone (the workspace) and the agent provider's own
state directories stay writable, and every other provider's state plus known
credential stores are masked.  On WSL the Windows drives (``/mnt/c`` and the
other drvfs mounts) are masked as well and an owner clone on one is re-bound over
its mask.  The network stays shared because dependency installs need it.

Known residual exposure: a provider's own credential necessarily stays readable
to its own shell inside the sandbox (for example ``~/.claude`` for Claude or
OpenCode's state directories for OpenCode); nothing else credential-like is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from xmuse_core.chat.room_opencode_sandbox import (
    MASKED_HOME_PATHS,
    OPENCODE_WRITABLE_HOME_PATHS,
    drive_masks,
)

ROOM_WORKSPACE_WRITE_CONFINEMENT = "os_workspace_write_sandbox"

PROVIDER_STATE_HOME_PATHS: Mapping[str, tuple[str, ...]] = {
    "claude": (".claude", ".claude.json", ".npm"),
    "opencode": OPENCODE_WRITABLE_HOME_PATHS,
}


def build_workspace_write_sandbox_command(
    *,
    bwrap: Path,
    provider: str,
    home: Path,
    workspace: Path,
    agent_argv: Sequence[str],
    masked_paths: Iterable[Path] = (),
    readonly_binds: Sequence[tuple[Path, Path]] = (),
    drive_mounts: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Return the bubblewrap argv that runs ``agent_argv`` with a writable workspace.

    Only the workspace and this provider's own state stay writable; every other
    provider's state and every :data:`MASKED_HOME_PATHS` entry is masked.
    ``readonly_binds`` mounts host directories read-only at destinations strictly
    inside the workspace (the board's charter/contract view at ``.xmuse``).
    ``drive_mounts`` overrides Windows drive detection (``None`` detects).
    """

    if provider not in PROVIDER_STATE_HOME_PATHS:
        raise ValueError("room_workspace_sandbox_provider_unknown")
    if not agent_argv or not all(isinstance(part, str) and part for part in agent_argv):
        raise ValueError("room_workspace_sandbox_agent_argv_invalid")

    home_expanded = home.expanduser()
    home_resolved = home_expanded.resolve()
    workspace_resolved = workspace.expanduser().resolve()
    if not workspace_resolved.is_dir():
        raise ValueError("room_workspace_sandbox_workspace_unsafe")
    if workspace_resolved == Path("/") or workspace_resolved == home_resolved:
        raise ValueError("room_workspace_sandbox_workspace_unsafe")
    if home_resolved.is_relative_to(workspace_resolved):
        raise ValueError("room_workspace_sandbox_workspace_unsafe")
    binds: list[tuple[Path, Path]] = []
    for source, destination in readonly_binds:
        source_resolved = Path(source).expanduser().resolve()
        destination_path = Path(destination)
        # The destination must be a real (non-symlink) path strictly inside the
        # workspace; the owner controls the workspace, so a symlinked component
        # could otherwise redirect the mount elsewhere.
        if (
            not source_resolved.is_dir()
            or not destination_path.is_absolute()
            or ".." in destination_path.parts
            or destination_path.resolve() != destination_path
            or destination_path == workspace_resolved
            or not destination_path.is_relative_to(workspace_resolved)
        ):
            raise ValueError("room_workspace_sandbox_bind_unsafe")
        binds.append((source_resolved, destination_path))

    own_rels = PROVIDER_STATE_HOME_PATHS[provider]
    own_resolved = {(home_expanded / rel).resolve() for rel in own_rels}

    candidates: list[Path] = [home_expanded / rel for rel in MASKED_HOME_PATHS]
    for other_provider, rels in PROVIDER_STATE_HOME_PATHS.items():
        if other_provider == provider:
            continue
        candidates.extend(home_expanded / rel for rel in rels)
    candidates.extend(Path(item).expanduser() for item in masked_paths)

    drives = drive_masks(drive_mounts)
    unique: list[Path] = []
    seen: set[Path] = set(drives)
    for candidate in candidates:
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if resolved in own_resolved or resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)

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
    # Windows drives and masks enclosing the workspace go before every re-bind.
    for path in [*drives, *enclosing]:
        argv.extend(_mask(path))
    for rel in own_rels:
        path = home_expanded / rel
        if path.exists():
            argv.extend(["--bind", str(path), str(path)])
        elif not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
            argv.extend(["--bind", str(path), str(path)])
    argv.extend(["--bind", str(workspace_resolved), str(workspace_resolved)])
    for source_resolved, destination_path in binds:
        argv.extend(["--ro-bind", str(source_resolved), str(destination_path)])
    for path in others:
        argv.extend(_mask(path))
    argv.extend(["--chdir", str(workspace_resolved), "--die-with-parent", "--new-session"])
    argv.extend(list(agent_argv))
    return tuple(argv)


def _mask(path: Path) -> list[str]:
    if path.is_dir():
        return ["--tmpfs", str(path)]
    return ["--ro-bind", "/dev/null", str(path)]
