"""Read-only OS sandbox for OpenCode Room participants.

OpenCode runs its own tools (shell, file writes, MCP calls) without asking the ACP
client, so the client cannot enforce the Room's read-only boundary.  The agent
process instead runs under bubblewrap: the whole filesystem is bound read-only,
``/tmp`` is a private tmpfs, and only OpenCode's own state directories stay
writable.  Credential stores of other tools and the xmuse data root are masked so
a shell inside the sandbox cannot read them.  The network is shared because the
model API and the loopback Room MCP need it.

OpenCode's own data directory necessarily stays readable to its shell; that is
the known residual exposure of this confinement level.
"""

from __future__ import annotations

import os
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


def build_opencode_sandbox_command(
    *,
    bwrap: Path,
    opencode: Path,
    home: Path,
    workspace: Path,
    masked_paths: Iterable[Path] = (),
    agent_args: Sequence[str] = ("acp",),
) -> tuple[str, ...]:
    """Return the bubblewrap argv that runs ``opencode <agent_args>`` read-only.

    Writable OpenCode state directories are created on the host first so the
    bind mounts exist.  Masked directories become empty tmpfs mounts and masked
    files are replaced by ``/dev/null``; missing masked paths are skipped.
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
    for relative in OPENCODE_WRITABLE_HOME_PATHS:
        path = home / relative
        path.mkdir(parents=True, exist_ok=True)
        argv.extend(["--bind", str(path), str(path)])
    workspace = workspace.expanduser().resolve()
    masked: list[Path] = [home / relative for relative in MASKED_HOME_PATHS]
    masked.extend(Path(item).expanduser() for item in masked_paths)
    unique: list[Path] = []
    for path in masked:
        if path.exists() and path.resolve() not in unique:
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
    argv.extend(["--chdir", str(workspace), "--die-with-parent", "--new-session"])
    argv.extend([str(opencode), *agent_args])
    return tuple(argv)


def _mask(path: Path) -> list[str]:
    # bubblewrap creates missing mount points, so masks under the private /tmp
    # are harmless as well.
    if path.is_dir():
        return ["--tmpfs", str(path)]
    return ["--ro-bind", "/dev/null", str(path)]
