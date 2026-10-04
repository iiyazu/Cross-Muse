"""Writable owner workspace sandbox command builder."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from xmuse_core.chat.room_opencode_sandbox import (
    OPENCODE_WRITABLE_HOME_PATHS,
    windows_drive_mounts,
)
from xmuse_core.chat.room_workspace_sandbox import (
    PROVIDER_STATE_HOME_PATHS,
    ROOM_WORKSPACE_WRITE_CONFINEMENT,
    build_workspace_write_sandbox_command,
)


def _pairs(argv: tuple[str, ...], flag: str) -> list[tuple[int, str]]:
    return [(index, argv[index + 1]) for index, item in enumerate(argv) if item == flag]


def _make_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    (home / ".npm").mkdir(parents=True)
    (home / ".ssh").mkdir(parents=True)
    (home / ".local" / "share" / "opencode").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return home, workspace


def test_confinement_name() -> None:
    assert ROOM_WORKSPACE_WRITE_CONFINEMENT == "os_workspace_write_sandbox"
    assert set(PROVIDER_STATE_HOME_PATHS) == {"claude", "opencode"}
    assert tuple(PROVIDER_STATE_HOME_PATHS["opencode"]) == tuple(OPENCODE_WRITABLE_HOME_PATHS)


def test_argv_order(tmp_path: Path) -> None:
    home, workspace = _make_home(tmp_path)
    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("claude", "acp"),
    )
    assert argv[:10] == (
        "/usr/bin/bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
    )
    assert argv[-2:] == ("claude", "acp")
    chdir = argv.index("--chdir")
    assert argv[chdir + 1] == str(workspace.resolve())
    assert argv[chdir + 2 : chdir + 4] == ("--die-with-parent", "--new-session")
    binds = _pairs(argv, "--bind")
    workspace_bind = next(i for i, t in binds if t == str(workspace.resolve()))
    own_bind = next(i for i, t in binds if t == str(home / ".claude"))
    assert own_bind < workspace_bind < chdir


def test_claude_own_state_writable_other_masked(tmp_path: Path) -> None:
    home, workspace = _make_home(tmp_path)
    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("agent",),
    )
    writable = {target for _, target in _pairs(argv, "--bind")}
    assert str(home / ".claude") in writable
    assert str(home / ".claude.json") in writable
    assert str(workspace.resolve()) in writable
    # Other provider's state is masked, never bound writable.
    assert str(home / ".local" / "share" / "opencode") not in writable
    assert str(home / ".local" / "share" / "opencode") in argv
    tmpfs = {target for _, target in _pairs(argv, "--tmpfs")}
    assert str(home / ".ssh") in tmpfs
    assert str(home / ".local" / "share" / "opencode") in tmpfs
    # Own state is never masked.
    own = {str(home / ".claude"), str(home / ".claude.json"), str(home / ".npm")}
    assert not (own & tmpfs)
    null_targets = {
        argv[index + 2]
        for index in range(len(argv) - 2)
        if argv[index] == "--ro-bind" and argv[index + 1] == "/dev/null"
    }
    assert not (own & null_targets)


def test_opencode_own_state_writable_other_masked(tmp_path: Path) -> None:
    home, workspace = _make_home(tmp_path)
    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="opencode",
        home=home,
        workspace=workspace,
        agent_argv=("agent",),
    )
    writable = {target for _, target in _pairs(argv, "--bind")}
    assert str(home / ".local" / "share" / "opencode") in writable
    assert str(home / ".claude") not in writable
    assert str(home / ".npm") in argv
    assert str(home / ".claude") in argv


def test_masked_paths_enclosing_vs_inside(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    enclosing_root = tmp_path / "outer-root"
    workspace = enclosing_root / "workspace"
    workspace.mkdir(parents=True)
    inner_root = workspace / "xmuse-data"
    inner_root.mkdir()

    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("agent",),
        masked_paths=(enclosing_root, inner_root),
    )
    position = {target: index for index, target in _pairs(argv, "--tmpfs")}
    workspace_bind = next(
        index for index, target in _pairs(argv, "--bind") if target == str(workspace.resolve())
    )
    assert position[str(enclosing_root.resolve())] < workspace_bind
    assert position[str(inner_root.resolve())] > workspace_bind


def test_windows_drives_masked_before_rebinds(tmp_path: Path) -> None:
    home, _ = _make_home(tmp_path)
    drive_c = tmp_path / "mnt" / "c"
    drive_c.mkdir(parents=True)
    drive_d = tmp_path / "mnt" / "d"
    workspace = drive_d / "Dev" / "clone"
    workspace.mkdir(parents=True)
    inner_root = workspace / "xmuse-data"
    inner_root.mkdir()

    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("agent",),
        masked_paths=(inner_root, drive_d),
        drive_mounts=(drive_c, drive_d),
    )
    tmpfs = _pairs(argv, "--tmpfs")
    position = {target: index for index, target in tmpfs}
    binds = _pairs(argv, "--bind")
    workspace_bind = next(i for i, t in binds if t == str(workspace.resolve()))
    own_bind = next(i for i, t in binds if t == str(home / ".claude"))
    for drive in (drive_c, drive_d):
        assert position[str(drive.resolve())] < own_bind < workspace_bind
    # A drive named again in masked_paths is masked once, and masks inside the
    # workspace still stay hidden after it is re-bound.
    assert [t for _, t in tmpfs].count(str(drive_d.resolve())) == 1
    assert position[str(inner_root.resolve())] > workspace_bind


def test_no_drive_masks_off_wsl(tmp_path: Path) -> None:
    home, workspace = _make_home(tmp_path)
    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("agent",),
        drive_mounts=(),
    )
    masked = {t for _, t in _pairs(argv, "--tmpfs")}
    masked |= {
        argv[index + 2]
        for index in range(len(argv) - 2)
        if argv[index] == "--ro-bind" and argv[index + 1] == "/dev/null"
    }
    assert all(Path(target).is_relative_to(home) or target == "/tmp" for target in masked)


def test_unknown_provider(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="room_workspace_sandbox_provider_unknown"):
        build_workspace_write_sandbox_command(
            bwrap=Path("/usr/bin/bwrap"),
            provider="gemini",
            home=home,
            workspace=workspace,
            agent_argv=("agent",),
        )


def test_empty_agent_argv(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="room_workspace_sandbox_agent_argv_invalid"):
        build_workspace_write_sandbox_command(
            bwrap=Path("/usr/bin/bwrap"),
            provider="claude",
            home=home,
            workspace=workspace,
            agent_argv=(),
        )


@pytest.mark.parametrize("kind", ["root", "home", "ancestor", "missing", "file"])
def test_unsafe_workspaces(tmp_path: Path, kind: str) -> None:
    home = tmp_path / "home"
    home.mkdir()
    if kind == "root":
        workspace = Path("/")
    elif kind == "home":
        workspace = home
    elif kind == "ancestor":
        workspace = tmp_path
    elif kind == "missing":
        workspace = tmp_path / "no-such-dir"
    else:
        workspace = tmp_path / "file"
        workspace.write_text("x")
    with pytest.raises(ValueError, match="room_workspace_sandbox_workspace_unsafe"):
        build_workspace_write_sandbox_command(
            bwrap=Path("/usr/bin/bwrap"),
            provider="claude",
            home=home,
            workspace=workspace,
            agent_argv=("agent",),
        )


def test_readonly_bind_follows_workspace_bind(tmp_path: Path) -> None:
    home, workspace = _make_home(tmp_path)
    board = tmp_path / "board"
    board.mkdir()
    mount = workspace.resolve() / ".xmuse"
    argv = build_workspace_write_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=("claude",),
        readonly_binds=((board, mount),),
    )
    workspace_bind = next(i for i, t in _pairs(argv, "--bind") if t == str(workspace.resolve()))
    ro_bind = next(i for i, t in _pairs(argv, "--ro-bind") if t == str(board.resolve()))
    assert workspace_bind < ro_bind
    assert argv[ro_bind + 2] == str(mount)


@pytest.mark.parametrize(
    "kind", ["outside", "workspace_itself", "relative", "symlink", "no_source"]
)
def test_readonly_bind_rejects_unsafe_destinations(tmp_path: Path, kind: str) -> None:
    home, workspace = _make_home(tmp_path)
    resolved = workspace.resolve()
    board = tmp_path / "board"
    board.mkdir()
    source = board
    destination: Path
    if kind == "outside":
        destination = tmp_path / "elsewhere"
    elif kind == "workspace_itself":
        destination = resolved
    elif kind == "relative":
        destination = Path(".xmuse")
    elif kind == "symlink":
        (resolved / ".xmuse").symlink_to(home / ".ssh")
        destination = resolved / ".xmuse"
    else:
        source = tmp_path / "missing"
        destination = resolved / ".xmuse"
    with pytest.raises(ValueError, match="room_workspace_sandbox_bind_unsafe"):
        build_workspace_write_sandbox_command(
            bwrap=Path("/usr/bin/bwrap"),
            provider="claude",
            home=home,
            workspace=workspace,
            agent_argv=("claude",),
            readonly_binds=((source, destination),),
        )


def _bwrap_works() -> bool:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return False
    try:
        result = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "true"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap is not usable here")
def test_bwrap_workspace_writable_home_not_writable_masked_empty(tmp_path: Path) -> None:
    bwrap = Path(str(shutil.which("bwrap")))
    home = tmp_path / "home"
    masked = home / ".ssh"
    masked.mkdir(parents=True)
    (masked / "secret").write_text("token")
    (home / ".claude").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("readable\n")
    # The sandbox's /tmp tmpfs covers anything under /tmp (including this
    # tmp_path), so the "not writable $HOME" check uses the real home, which
    # lives under the read-only / bind; the masked dir is checked by absolute
    # tmp path instead of via $HOME.
    real_home = str(Path.home())
    argv = build_workspace_write_sandbox_command(
        bwrap=bwrap,
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=(
            "/bin/sh",
            "-c",
            "cat notes.txt; touch created.txt && echo workspace_ok; "
            'test -w "$HOME" && echo home_writable || echo home_not_writable; '
            f'cat "{masked}"/secret || echo masked; '
            f'ls "{masked}"',
        ),
    )
    import os

    env = {"HOME": real_home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False, env=env)
    if "Operation not permitted" in result.stderr or "No permissions" in result.stderr:
        pytest.skip("unprivileged user namespaces are unavailable")
    assert "readable" in result.stdout
    assert "workspace_ok" in result.stdout
    assert "home_not_writable" in result.stdout
    assert "token" not in result.stdout
    assert "masked" in result.stdout
    assert (workspace / "created.txt").exists()
    assert (masked / "secret").read_text() == "token"


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap is not usable here")
def test_bwrap_board_view_is_read_only_inside_writable_workspace(tmp_path: Path) -> None:
    import os

    bwrap = Path(str(shutil.which("bwrap")))
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    (workspace / ".xmuse").mkdir(parents=True)
    board = tmp_path / "board"
    board.mkdir()
    (board / "charter.md").write_text("module: api\n")
    argv = build_workspace_write_sandbox_command(
        bwrap=bwrap,
        provider="claude",
        home=home,
        workspace=workspace,
        agent_argv=(
            "/bin/sh",
            "-c",
            "cat .xmuse/charter.md; "
            "echo x > .xmuse/charter.md && echo board_writable || echo board_read_only; "
            "touch work.txt && echo workspace_ok",
        ),
        readonly_binds=((board, workspace.resolve() / ".xmuse"),),
    )
    env = {"HOME": str(Path.home()), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False, env=env)
    if "Operation not permitted" in result.stderr or "No permissions" in result.stderr:
        pytest.skip("unprivileged user namespaces are unavailable")
    assert "module: api" in result.stdout
    assert "board_read_only" in result.stdout
    assert "workspace_ok" in result.stdout
    assert (board / "charter.md").read_text() == "module: api\n"


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap is not usable here")
@pytest.mark.skipif(not windows_drive_mounts(), reason="no Windows drives mounted (not WSL)")
def test_bwrap_hides_windows_drives_but_keeps_a_workspace_on_one(tmp_path: Path) -> None:
    import tempfile

    bwrap = Path(str(shutil.which("bwrap")))
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    drives = [path for path in windows_drive_mounts() if path.is_dir()]
    host_drive = next((drive for drive in drives if Path.cwd().is_relative_to(drive)), drives[0])
    try:
        holder = tempfile.TemporaryDirectory(prefix="xmuse-drive-sandbox-", dir=host_drive)
    except OSError:
        pytest.skip("Windows drive is not writable here")
    with holder as raw:
        workspace = Path(raw)
        (workspace / "notes.txt").write_text("readable\n")
        listings = "; ".join(
            f'echo "{drive}=[$(ls -A "{drive}" | tr "\\n" " ")]"' for drive in drives
        )
        argv = build_workspace_write_sandbox_command(
            bwrap=bwrap,
            provider="claude",
            home=home,
            workspace=workspace,
            agent_argv=(
                "/bin/sh",
                "-c",
                f"cat notes.txt; touch created.txt && echo workspace_ok; {listings}",
            ),
        )
        env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, check=False, env=env
        )
        if "Operation not permitted" in result.stderr or "No permissions" in result.stderr:
            pytest.skip("unprivileged user namespaces are unavailable")
        assert result.returncode == 0, result.stderr
        assert "readable" in result.stdout
        assert "workspace_ok" in result.stdout
        assert (workspace / "created.txt").exists()
        # Only the path down to the re-bound workspace survives on its drive;
        # every other drive is an empty tmpfs.
        for drive in drives:
            if workspace.is_relative_to(drive):
                first = workspace.relative_to(drive).parts[0]
                assert f"{drive}=[{first} ]" in result.stdout
            else:
                assert f"{drive}=[]" in result.stdout
