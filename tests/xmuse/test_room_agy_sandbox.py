"""Bubblewrap confinement for Antigravity CLI (agy) Room participants."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.xmuse.sandbox_support import bwrap_usable
from xmuse_core.chat.room_agy_sandbox import (
    ROOM_AGY_READ_ONLY_CONFINEMENT,
    build_agy_sandbox_command,
    resolve_agy_python3,
    write_agy_mcp_config,
)
from xmuse_core.chat.room_workspace_sandbox import ROOM_WORKSPACE_WRITE_CONFINEMENT


def _pairs(argv: tuple[str, ...], flag: str) -> list[tuple[int, str]]:
    return [(index, argv[index + 1]) for index, item in enumerate(argv) if item == flag]


def _bind_mounts(argv: tuple[str, ...], flag: str) -> list[tuple[str, str]]:
    """Return (source, destination) for two-argument bind flags."""

    mounts: list[tuple[str, str]] = []
    for index, item in enumerate(argv):
        if item == flag and index + 2 < len(argv) + 1:
            mounts.append((argv[index + 1], argv[index + 2]))
    return mounts


def _base_kwargs(tmp_path: Path, *, workspace: Path | None = None) -> dict[str, object]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    work = workspace or (tmp_path / "repo")
    work.mkdir(parents=True, exist_ok=True)
    mcp_config = tmp_path / "mcp_config.json"
    mcp_config.write_text("{}")
    bridge = tmp_path / "room_mcp_stdio.py"
    bridge.write_text("# bridge\n")
    agy = tmp_path / "agy"
    agy.write_text("#!/bin/sh\n")
    return {
        "bwrap": Path("/usr/bin/bwrap"),
        "agy": agy,
        "home": home,
        "workspace": work,
        "workspace_writable": False,
        "mcp_config": mcp_config,
        "bridge_script": bridge,
        "python3": Path("/usr/bin/python3"),
        "agy_args": ("--model", "gemini-3.8-flash-high", "-p="),
    }


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_python3_skips_a_virtualenv_under_home_for_one_later_on_path(tmp_path: Path) -> None:
    # `uv run` puts the project's .venv/bin (under $HOME) first on PATH.
    home = tmp_path / "home"
    venv_python = _executable(home / "repo" / ".venv" / "bin" / "python3")
    system_python = _executable(tmp_path / "usr" / "bin" / "python3")
    environ = {"HOME": str(home), "PATH": f"{venv_python.parent}:{system_python.parent}"}

    found = resolve_agy_python3(environ, lambda name: str(venv_python))
    assert found == system_python.resolve()

    only_home = {"HOME": str(home), "PATH": str(venv_python.parent)}
    assert resolve_agy_python3(only_home, lambda name: str(venv_python)) is None


def test_confinement_levels() -> None:
    assert ROOM_AGY_READ_ONLY_CONFINEMENT == "os_read_only_sandbox"
    assert ROOM_WORKSPACE_WRITE_CONFINEMENT == "os_workspace_write_sandbox"


def test_write_agy_mcp_config_mounts_the_bridge(tmp_path: Path) -> None:
    dest = write_agy_mcp_config(
        tmp_path / "agy" / "mcp_config.json",
        python3=Path("/usr/bin/python3"),
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
    )
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload == {
        "mcpServers": {
            "xmuse-room": {
                "command": "/usr/bin/python3",
                "args": [
                    "/tmp/xmuse-bridge/room_mcp_stdio.py",
                    "--url",
                    "http://127.0.0.1:8100/mcp/room",
                ],
            }
        }
    }


def test_argv_allowlists_home_and_mounts_config_and_bridge(tmp_path: Path) -> None:
    kwargs = _base_kwargs(tmp_path)
    home = kwargs["home"]
    assert isinstance(home, Path)
    (home / ".gemini" / "config").mkdir(parents=True)
    argv = build_agy_sandbox_command(**kwargs)  # type: ignore[arg-type]

    assert argv[:5] == ("/usr/bin/bwrap", "--ro-bind", "/", "/", "--dev")
    assert argv[-4:] == (
        str((tmp_path / "agy").resolve()),
        "--model",
        "gemini-3.8-flash-high",
        "-p=",
    )
    # The whole home is masked, then only agy's own paths return.
    assert ("--tmpfs", str(home)) in {
        (argv[index], argv[index + 1]) for index in range(len(argv) - 1)
    }
    ro_binds = {dest for _, dest in _bind_mounts(argv, "--ro-bind")}
    assert str((tmp_path / "agy").resolve()) in ro_binds
    assert str(home / ".gemini" / "config") in {target for _, target in _pairs(argv, "--dir")}
    assert str(home / ".gemini" / "config" / "mcp_config.json") in ro_binds
    assert "/tmp/xmuse-bridge/room_mcp_stdio.py" in ro_binds
    assert (home / ".gemini" / "antigravity-cli").is_dir()
    binds = {dest for _, dest in _bind_mounts(argv, "--bind")}
    assert str(home / ".gemini" / "antigravity-cli") in binds
    setenv = {argv[i + 1]: argv[i + 2] for i, item in enumerate(argv) if item == "--setenv"}
    assert setenv == {"HOME": str(home), "TMPDIR": "/tmp", "TMP": "/tmp", "TEMP": "/tmp"}
    assert argv[argv.index("--chdir") + 1] == str((tmp_path / "repo").resolve())
    assert "--die-with-parent" in argv and "--new-session" in argv


def test_workspace_writability_follows_the_flag(tmp_path: Path) -> None:
    read_only = build_agy_sandbox_command(
        **{**_base_kwargs(tmp_path), "workspace_writable": False}  # type: ignore[arg-type]
    )
    workspace = (tmp_path / "repo").resolve()
    ro_binds = [dest for _, dest in _bind_mounts(read_only, "--ro-bind")]
    assert str(workspace) in ro_binds

    writable = build_agy_sandbox_command(
        **{**_base_kwargs(tmp_path), "workspace_writable": True}  # type: ignore[arg-type]
    )
    binds = [dest for _, dest in _bind_mounts(writable, "--bind")]
    assert str(workspace) in binds
    assert str(workspace) not in [dest for _, dest in _bind_mounts(writable, "--ro-bind")]


def test_masks_enclosing_the_workspace_come_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    enclosing_root = tmp_path / "outer-root"
    workspace = enclosing_root / "workspace"
    workspace.mkdir(parents=True)
    inner_root = workspace / "xmuse-data"
    inner_root.mkdir()
    kwargs = _base_kwargs(tmp_path, workspace=workspace)
    kwargs["home"] = home
    argv = build_agy_sandbox_command(
        **kwargs,  # type: ignore[arg-type]
        masked_paths=(enclosing_root, inner_root),
    )

    position = {target: index for index, target in _pairs(argv, "--tmpfs")}
    workspace_bind = argv.index(str(workspace.resolve()))
    home_mask = position[str(home)]
    assert position[str(enclosing_root.resolve())] < workspace_bind
    assert position[str(enclosing_root.resolve())] < home_mask
    assert position[str(inner_root.resolve())] > workspace_bind


def test_windows_drives_are_masked_before_every_rebind(tmp_path: Path) -> None:
    drive_c = tmp_path / "mnt" / "c"
    agy_on_drive = drive_c / "tools" / "agy"
    agy_on_drive.parent.mkdir(parents=True)
    agy_on_drive.write_text("#!/bin/sh\n")
    drive_d = tmp_path / "mnt" / "d"
    workspace = drive_d / "Dev" / "repo"
    kwargs = _base_kwargs(tmp_path, workspace=workspace)
    argv = build_agy_sandbox_command(
        **{**kwargs, "agy": agy_on_drive},  # type: ignore[arg-type]
        drive_mounts=(drive_c, drive_d),
    )

    position = {target: index for index, target in _pairs(argv, "--tmpfs")}
    workspace_bind = argv.index(str(workspace.resolve()))
    agy_bind = argv.index(str(agy_on_drive.resolve()))
    home_mask = position[str(kwargs["home"])]
    for drive in (drive_c, drive_d):
        assert position[str(drive.resolve())] < home_mask < agy_bind < workspace_bind

    plain = build_agy_sandbox_command(**kwargs, drive_mounts=())  # type: ignore[arg-type]
    assert str(drive_d.resolve()) not in plain


def test_missing_masked_paths_are_skipped(tmp_path: Path) -> None:
    kwargs = _base_kwargs(tmp_path)
    argv = build_agy_sandbox_command(
        **kwargs,
        masked_paths=(tmp_path / "does-not-exist",),  # type: ignore[arg-type]
    )
    assert str(tmp_path / "does-not-exist") not in argv


def test_readonly_binds_must_stay_inside_the_workspace(tmp_path: Path) -> None:
    kwargs = _base_kwargs(tmp_path)
    workspace = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    board = tmp_path / "board"
    board.mkdir()
    with pytest.raises(ValueError, match="room_agy_bind_unsafe"):
        build_agy_sandbox_command(
            **kwargs,  # type: ignore[arg-type]
            readonly_binds=((board, outside / ".xmuse"),),
        )
    with pytest.raises(ValueError, match="room_agy_bind_unsafe"):
        build_agy_sandbox_command(
            **kwargs,  # type: ignore[arg-type]
            readonly_binds=((board, workspace.resolve()),),
        )
    with pytest.raises(ValueError, match="room_agy_bind_unsafe"):
        build_agy_sandbox_command(
            **kwargs,  # type: ignore[arg-type]
            readonly_binds=((tmp_path / "missing", workspace / ".xmuse"),),
        )
    mount = workspace / ".xmuse"
    mount.mkdir()
    argv = build_agy_sandbox_command(
        **kwargs,  # type: ignore[arg-type]
        readonly_binds=((board, mount),),
    )
    ro_dests = {dest for _, dest in _bind_mounts(argv, "--ro-bind")}
    assert str(mount) in ro_dests


def test_unsafe_workspaces_are_rejected(tmp_path: Path) -> None:
    kwargs = _base_kwargs(tmp_path)
    home = tmp_path / "home"
    with pytest.raises(ValueError, match="room_agy_workspace_unsafe"):
        build_agy_sandbox_command(**{**kwargs, "workspace": Path("/")})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="room_agy_workspace_unsafe"):
        build_agy_sandbox_command(**{**kwargs, "workspace": home})  # type: ignore[arg-type]
    nested_home = (tmp_path / "repo" / "home-nest").resolve()
    nested_home.mkdir(parents=True)
    with pytest.raises(ValueError, match="room_agy_workspace_unsafe"):
        build_agy_sandbox_command(  # type: ignore[arg-type]
            **{**kwargs, "workspace": tmp_path / "repo", "home": nested_home}
        )
    with pytest.raises(ValueError, match="room_agy_workspace_unsafe"):
        build_agy_sandbox_command(  # type: ignore[arg-type]
            **{**kwargs, "workspace": tmp_path / "missing-workspace"}
        )


def test_python3_under_home_is_rejected_but_agy_is_rebound(tmp_path: Path) -> None:
    kwargs = _base_kwargs(tmp_path)
    home = tmp_path / "home"
    home_python = home / "bin" / "python3"
    home_python.parent.mkdir(parents=True)
    home_python.write_text("#!/bin/sh\n")
    with pytest.raises(ValueError, match="room_agy_python_unavailable"):
        build_agy_sandbox_command(**{**kwargs, "python3": home_python})  # type: ignore[arg-type]

    home_agy = home / "bin" / "agy"
    home_agy.write_text("#!/bin/sh\n")
    argv = build_agy_sandbox_command(**{**kwargs, "agy": home_agy})  # type: ignore[arg-type]
    ro_dests = {dest for _, dest in _bind_mounts(argv, "--ro-bind")}
    assert str(home_agy.resolve()) in ro_dests


@pytest.mark.skipif(not bwrap_usable(), reason="bubblewrap is not usable here")
@pytest.mark.parametrize(
    ("writable", "operator_mcp_file"), [(False, True), (True, True), (False, False)]
)
def test_sandbox_home_allowlist_and_workspace_flag(
    tmp_path: Path, writable: bool, operator_mcp_file: bool
) -> None:
    home = tmp_path / "home"
    (home / ".gemini" / "config").mkdir(parents=True)
    (home / ".gemini" / "config" / "other.json").write_text('{"other": true}')
    if operator_mcp_file:
        # The generated per-session file overlays an operator MCP file; without
        # one the config dir still has to accept the new mount point.
        (home / ".gemini" / "config" / "mcp_config.json").write_text('{"dummy": true}')
    (home / "secret.txt").write_text("operator-secret")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("readable\n")
    mcp_config = write_agy_mcp_config(
        tmp_path / "mcp_config.json",
        python3=Path("/usr/bin/python3"),
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
    )
    bridge = tmp_path / "room_mcp_stdio.py"
    bridge.write_text("# bridge\n")
    probe = (
        'python3 -c "import json,os; print(json.dumps({'
        "'home': sorted(os.listdir(os.environ['HOME'])),"
        "'gemini': sorted(os.listdir(os.path.join(os.environ['HOME'], '.gemini'))),"
        "'secret_visible': os.path.exists(os.path.join(os.environ['HOME'], 'secret.txt'))"
        '}))"; '
        'cat "$HOME/.gemini/config/mcp_config.json"; echo; '
        'cat "$HOME/.gemini/config/other.json"; echo; '
        "touch probe.tmp && echo workspace_write_ok=yes || echo workspace_write_ok=no"
    )
    argv = build_agy_sandbox_command(
        bwrap=Path(str(shutil.which("bwrap"))),
        agy=Path("/bin/sh"),
        home=home,
        workspace=workspace,
        workspace_writable=writable,
        mcp_config=mcp_config,
        bridge_script=bridge,
        python3=Path("/usr/bin/python3"),
        agy_args=("-c", probe),
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    if "Operation not permitted" in result.stderr or "No permissions" in result.stderr:
        pytest.skip("unprivileged user namespaces are unavailable")
    assert result.returncode == 0, result.stderr
    first_line = result.stdout.splitlines()[0]
    seen = json.loads(first_line)
    assert seen["home"] == [".gemini"]
    assert seen["gemini"] == ["antigravity-cli", "config"]
    assert seen["secret_visible"] is False
    # The generated per-session MCP file overlays the operator's dummy file.
    assert "http://127.0.0.1:8100/mcp/room" in result.stdout
    assert '"dummy"' not in result.stdout
    assert '{"other": true}' in result.stdout
    assert f"workspace_write_ok={'yes' if writable else 'no'}" in result.stdout
    assert (workspace / "probe.tmp").exists() is writable
