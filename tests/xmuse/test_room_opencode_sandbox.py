"""Read-only bubblewrap confinement for OpenCode Room participants."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from xmuse_core.chat.room_opencode_sandbox import (
    OPENCODE_WRITABLE_HOME_PATHS,
    build_opencode_sandbox_command,
    drive_masks,
    windows_drive_mounts,
)

_WSL_MOUNTS = "\n".join(
    [
        "/dev/sdc / ext4 rw,relatime 0 0",
        "none /mnt/wsl tmpfs rw,relatime 0 0",
        "drivers /usr/lib/wsl/drivers 9p ro,nosuid,aname=drivers;fmask=222,cache=0x5 0 0",
        r"C:\134 /mnt/c 9p rw,noatime,aname=drvfs;path=C:\;uid=1000;symlinkroot=/mnt/ 0 0",
        r"D:\134 /mnt/d 9p rw,noatime,aname=drvfs;path=D:\;uid=1000;symlinkroot=/mnt/ 0 0",
        r"E:\134 /win/e\040drive drvfs rw,noatime,uid=1000 0 0",
        "drvfsF /mnt/f virtiofs rw,relatime 0 0",
        "",
    ]
)


def _pairs(argv: tuple[str, ...], flag: str) -> list[tuple[int, str]]:
    return [(index, argv[index + 1]) for index, item in enumerate(argv) if item == flag]


def test_windows_drive_mounts_finds_drvfs_and_wsl_automounts(tmp_path: Path) -> None:
    mounts = tmp_path / "mounts"
    mounts.write_text(_WSL_MOUNTS)
    wsl = tmp_path / "osrelease-wsl"
    wsl.write_text("6.6.87.2-microsoft-standard-WSL2\n")
    linux = tmp_path / "osrelease-linux"
    linux.write_text("6.12.1-arch1-1\n")

    assert windows_drive_mounts(mounts, wsl) == (
        Path("/mnt/c"),
        Path("/mnt/d"),
        Path("/win/e drive"),
        Path("/mnt/f"),
    )
    # drvfs is a WSL-only filesystem, so it is masked wherever it shows up; a
    # bare /mnt/<letter> mount counts only on a WSL kernel.
    assert windows_drive_mounts(mounts, linux) == (
        Path("/mnt/c"),
        Path("/mnt/d"),
        Path("/win/e drive"),
    )


def test_windows_drive_mounts_is_empty_off_wsl(tmp_path: Path) -> None:
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "/dev/nvme0n1p2 / ext4 rw,relatime 0 0\n"
        "tmpfs /tmp tmpfs rw,nosuid,nodev 0 0\n"
        "/dev/sdb1 /mnt/b ext4 rw,relatime 0 0\n"
    )
    osrelease = tmp_path / "osrelease"
    osrelease.write_text("6.12.1-arch1-1\n")
    assert windows_drive_mounts(mounts, osrelease) == ()
    assert windows_drive_mounts(tmp_path / "missing", osrelease) == ()


def test_sandbox_masks_windows_drives_and_rebinds_a_workspace_on_one(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    drive_c = tmp_path / "mnt" / "c"
    drive_c.mkdir(parents=True)
    drive_d = tmp_path / "mnt" / "d"
    workspace = drive_d / "Dev" / "repo"
    workspace.mkdir(parents=True)

    argv = build_opencode_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        opencode=Path("/opt/opencode"),
        home=home,
        workspace=workspace,
        drive_mounts=(drive_c, drive_d, tmp_path / "mnt" / "z"),
    )

    position = {target: index for index, target in _pairs(argv, "--tmpfs")}
    workspace_bind = next(
        index for index, target in _pairs(argv, "--ro-bind") if target == str(workspace.resolve())
    )
    first_state_bind = min(index for index, _ in _pairs(argv, "--bind"))
    for drive in (drive_c, drive_d):
        assert position[str(drive.resolve())] < first_state_bind < workspace_bind
    assert str(tmp_path / "mnt" / "z") not in argv

    plain = build_opencode_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        opencode=Path("/opt/opencode"),
        home=home,
        workspace=workspace,
        drive_mounts=(),
    )
    assert str(drive_c.resolve()) not in plain


def test_sandbox_masks_credentials_and_keeps_only_opencode_state_writable(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    (home / ".ssh").mkdir()
    workspace = tmp_path / "repo"
    workspace.mkdir()

    argv = build_opencode_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        opencode=Path("/opt/opencode"),
        home=home,
        workspace=workspace,
    )

    assert argv[:5] == ("/usr/bin/bwrap", "--ro-bind", "/", "/", "--dev")
    assert argv[-2:] == ("/opt/opencode", "acp")
    writable = {target for _, target in _pairs(argv, "--bind")}
    assert writable == {str(home / relative) for relative in OPENCODE_WRITABLE_HOME_PATHS}
    assert all((home / relative).is_dir() for relative in OPENCODE_WRITABLE_HOME_PATHS)
    tmpfs = {target for _, target in _pairs(argv, "--tmpfs")}
    assert {"/tmp", str(home / ".claude"), str(home / ".ssh")} <= tmpfs
    assert ("--ro-bind", "/dev/null", str(home / ".claude.json")) in {
        argv[index : index + 3] for index in range(len(argv) - 2)
    }
    # Absent credential stores are not mounted at all.
    assert str(home / ".aws") not in argv
    assert argv[argv.index("--chdir") + 1] == str(workspace.resolve())


def test_drive_masks_drops_mounts_nested_under_another_drive(tmp_path: Path) -> None:
    drive = tmp_path / "mnt" / "d"
    nested = drive / "Dev" / "repo"
    nested.mkdir(parents=True)
    other = tmp_path / "mnt" / "c"
    other.mkdir(parents=True)

    assert drive_masks((drive, nested, other)) == [drive.resolve(), other.resolve()]
    # Order-independent: the nested mount is dropped either way.
    assert drive_masks((nested, drive)) == [drive.resolve()]


def test_sandbox_orders_masks_around_the_workspace(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    enclosing_root = tmp_path / "outer-root"
    workspace = enclosing_root / "workspace"
    workspace.mkdir(parents=True)
    inner_root = workspace / "xmuse-data"
    inner_root.mkdir()

    argv = build_opencode_sandbox_command(
        bwrap=Path("/usr/bin/bwrap"),
        opencode=Path("/opt/opencode"),
        home=home,
        workspace=workspace,
        masked_paths=(enclosing_root, inner_root),
    )

    position = {target: index for index, target in _pairs(argv, "--tmpfs")}
    workspace_bind = next(
        index for index, target in _pairs(argv, "--ro-bind") if target == str(workspace.resolve())
    )
    # An enclosing mask must not hide the workspace; an inner mask must not be
    # re-exposed by it.
    assert position[str(enclosing_root.resolve())] < workspace_bind
    assert position[str(inner_root.resolve())] > workspace_bind


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is not installed")
def test_sandbox_refuses_workspace_and_masked_writes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "secret").write_text("token")
    # The workspace lives under the sandbox's private /tmp and is re-exposed
    # read-only; the fake home under /tmp is hidden by that tmpfs as well.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("readable\n")
    argv = build_opencode_sandbox_command(
        bwrap=Path(str(shutil.which("bwrap"))),
        opencode=Path("/bin/sh"),
        home=home,
        workspace=workspace,
        agent_args=(
            "-c",
            f"cat notes.txt; touch created.txt; echo exit=$?; "
            f"cat {home}/.claude/secret || echo masked",
        ),
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    if "Operation not permitted" in result.stderr or "No permissions" in result.stderr:
        pytest.skip("unprivileged user namespaces are unavailable")
    assert "readable" in result.stdout
    assert "exit=1" in result.stdout
    assert "token" not in result.stdout
    assert "masked" in result.stdout
    assert not (workspace / "created.txt").exists()
