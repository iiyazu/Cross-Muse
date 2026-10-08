"""Read-only OS sandbox for OpenCode Room participants.

OpenCode runs its own tools (shell, file writes, MCP calls) without asking the ACP
client, so the client cannot enforce the Room's read-only boundary.  The agent
process instead runs under bubblewrap: the whole filesystem is bound read-only,
``/tmp`` is a private tmpfs, and only OpenCode's own state directories stay
writable.  Credential stores of other tools and the xmuse data root are masked so
a shell inside the sandbox cannot read them.  The network is shared because the
model API and the loopback Room MCP need it.

On WSL the Windows drives (drvfs mounts such as ``/mnt/c``) are masked too: they
hold the Windows-side credential stores and browser profiles.  A workspace on such
a drive is re-bound over its mask.

OpenCode's own data directory necessarily stays readable to its shell; that is
the known residual exposure of this confinement level.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

OPENCODE_EXECUTABLE_ENV = "XMUSE_OPENCODE_BIN"
OPENCODE_BWRAP_ENV = "XMUSE_OPENCODE_BWRAP"

# Paths under $HOME that hold another tool's credentials or session state.
MASKED_HOME_PATHS: tuple[str, ...] = (
    ".claude",
    ".claude.json",
    ".codex",
    ".gemini",
    ".antigravity-server",
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".config/gh",
    ".config/gcloud",
    ".local/share/keyrings",
)
# OpenCode keeps sessions, its database, caches, and logs here.
OPENCODE_WRITABLE_HOME_PATHS: tuple[str, ...] = (
    ".local/share/opencode",
    ".local/state/opencode",
    ".cache/opencode",
)

_PROC_MOUNTS = Path("/proc/mounts")
_KERNEL_OSRELEASE = Path("/proc/sys/kernel/osrelease")
_WSL_AUTOMOUNT_RE = re.compile(r"/mnt/[A-Za-z]\Z")
_MOUNTS_ESCAPE_RE = re.compile(r"\\([0-7]{3})")


def windows_drive_mounts(
    mounts: Path = _PROC_MOUNTS,
    osrelease: Path = _KERNEL_OSRELEASE,
) -> tuple[Path, ...]:
    """Return the WSL mount points that expose Windows drives; empty elsewhere.

    A drvfs mount (WSL1 ``drvfs``, WSL2 ``9p`` with ``aname=drvfs``) counts
    wherever it is mounted; on a WSL kernel any mount at ``/mnt/<letter>``
    counts too, covering transports whose options do not name drvfs.
    """

    try:
        table = mounts.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    try:
        wsl_kernel = "microsoft" in osrelease.read_text(encoding="ascii").lower()
    except (OSError, UnicodeDecodeError):
        wsl_kernel = False
    found: list[Path] = []
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        mount_point = _MOUNTS_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 8)), fields[1])
        fs_type, options = fields[2], fields[3].split(",")
        drvfs = fs_type == "drvfs" or any(
            part == "aname=drvfs" or part.startswith("aname=drvfs;") for part in options
        )
        automount = wsl_kernel and _WSL_AUTOMOUNT_RE.match(mount_point) is not None
        path = Path(mount_point)
        if (drvfs or automount) and path not in found:
            found.append(path)
    return tuple(found)


def drive_masks(drive_mounts: Iterable[Path] | None) -> list[Path]:
    """Resolve existing Windows drive mounts (detected when ``None``) to mask."""

    candidates = windows_drive_mounts() if drive_mounts is None else drive_mounts
    masks: list[Path] = []
    for item in candidates:
        path = Path(item)
        if path.is_dir() and path.resolve() not in masks:
            masks.append(path.resolve())
    # A mount nested under another masked drive is already hidden by the outer
    # mask. Emitting it as well would make bubblewrap re-create its parent
    # directories inside the outer tmpfs when creating the nested mount point,
    # leaving phantom entries the agent can see.
    masks.sort(key=lambda path: len(path.parts))
    outer: list[Path] = []
    for path in masks:
        if not any(path.is_relative_to(kept) for kept in outer):
            outer.append(path)
    return outer


def resolve_opencode_executable(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Locate the OpenCode CLI: explicit override, PATH, then the installer default."""

    source = os.environ if environ is None else environ
    override = str(source.get(OPENCODE_EXECUTABLE_ENV) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    found = which("opencode")
    if found:
        return Path(found)
    default = Path(str(source.get("HOME") or Path.home())) / ".opencode" / "bin" / "opencode"
    return default if default.is_file() else None


def resolve_bwrap_executable(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    source = os.environ if environ is None else environ
    override = str(source.get(OPENCODE_BWRAP_ENV) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    found = which("bwrap")
    return Path(found) if found else None


# Every provider sandbox mounts a private tmpfs at /tmp. The host's temp variables usually name
# a directory the sandbox makes read-only (or masks), so they are pinned to /tmp inside.
SANDBOX_TEMP_ENV_ARGS: tuple[str, ...] = (
    "--setenv",
    "TMPDIR",
    "/tmp",
    "--setenv",
    "TMP",
    "/tmp",
    "--setenv",
    "TEMP",
    "/tmp",
)


def build_opencode_sandbox_command(
    *,
    bwrap: Path,
    opencode: Path,
    home: Path,
    workspace: Path,
    masked_paths: Iterable[Path] = (),
    agent_args: Sequence[str] = ("acp",),
    drive_mounts: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Return the bubblewrap argv that runs ``opencode <agent_args>`` read-only.

    Writable OpenCode state directories are created on the host first so the
    bind mounts exist.  Masked directories become empty tmpfs mounts and masked
    files are replaced by ``/dev/null``; missing masked paths are skipped.
    ``drive_mounts`` overrides Windows drive detection (``None`` detects).
    """

    home = home.expanduser()
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
    # Windows drives are masked before anything is re-bound, so a workspace or
    # state directory living on one stays reachable.
    drives = drive_masks(drive_mounts)
    for path in drives:
        argv.extend(_mask(path))
    for relative in OPENCODE_WRITABLE_HOME_PATHS:
        path = home / relative
        path.mkdir(parents=True, exist_ok=True)
        argv.extend(["--bind", str(path), str(path)])
    workspace = workspace.expanduser().resolve()
    masked: list[Path] = [home / relative for relative in MASKED_HOME_PATHS]
    masked.extend(Path(item).expanduser() for item in masked_paths)
    unique: list[Path] = []
    for path in masked:
        if path.exists() and path.resolve() not in unique and path.resolve() not in drives:
            unique.append(path.resolve())
    # Mount order matters: a mask that contains the workspace goes first so the
    # workspace can be re-exposed over it; a mask inside the workspace (such as a
    # data root kept in the repository) goes after so it stays hidden.
    enclosing = [path for path in unique if workspace.is_relative_to(path)]
    others = [path for path in unique if path not in enclosing]
    for path in enclosing:
        argv.extend(_mask(path))
    # The read-only workspace is re-exposed so neither the /tmp tmpfs nor an
    # enclosing mask hides it, and the agent starts inside it.
    argv.extend(["--ro-bind", str(workspace), str(workspace)])
    for path in others:
        argv.extend(_mask(path))
    argv.extend(SANDBOX_TEMP_ENV_ARGS)
    argv.extend(["--chdir", str(workspace), "--die-with-parent", "--new-session"])
    argv.extend([str(opencode), *agent_args])
    return tuple(argv)


def _mask(path: Path) -> list[str]:
    # bubblewrap creates missing mount points, so masks under the private /tmp
    # are harmless as well.
    if path.is_dir():
        return ["--tmpfs", str(path)]
    return ["--ro-bind", "/dev/null", str(path)]
