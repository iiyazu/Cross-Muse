from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from xmuse_core.chat import room_execution_sandbox as sandbox
from xmuse_core.chat.room_execution_profiles import get_execution_gate_profile
from xmuse_core.chat.room_execution_sandbox import (
    GATE_SPECS,
    GateResourceSample,
    GateSpec,
    RoomExecutionSandboxError,
    SandboxLayout,
    build_bwrap_command,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    resource_limits_for_gate,
    run_gate,
)


def _layout(tmp_path: Path) -> SandboxLayout:
    paths = {
        name: tmp_path / name
        for name in ("stage", "git", "git/worktrees/stage", "python", "site", "node")
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    ruff = tmp_path / "ruff"
    ruff.write_bytes(b"ruff")
    bwrap = tmp_path / "bwrap"
    bwrap.write_bytes(b"bwrap")
    node = tmp_path / "trusted-node"
    node.write_bytes(b"node")
    return SandboxLayout(
        stage=paths["stage"],
        git_common_dir=paths["git"],
        git_dir=paths["git/worktrees/stage"],
        python_root=paths["python"],
        site_packages=paths["site"],
        ruff=ruff,
        node=node,
        frontend_node_modules=paths["node"],
        bwrap=bwrap,
    )


def test_gate_resource_profiles_are_fixed_and_do_not_use_address_space_limits() -> None:
    python = resource_limits_for_gate("backend_pytest")
    node = resource_limits_for_gate("frontend_build")

    assert (python.max_rss_bytes, python.max_processes, python.max_scratch_bytes) == (
        2 * 1024**3,
        64,
        1024**3,
    )
    assert (node.max_rss_bytes, node.max_processes, node.max_scratch_bytes) == (
        4 * 1024**3,
        128,
        2 * 1024**3,
    )


def test_bwrap_command_has_no_host_environment_or_arbitrary_shell(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    command = build_bwrap_command(layout, GATE_SPECS["backend_ruff"])

    for required in (
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--cap-drop",
    ):
        assert required in command
    assert command[-6:] == [
        "--chdir",
        "/workspace",
        "--",
        "/tools/ruff",
        "check",
        ".",
    ]
    joined = "\0".join(command)
    assert "XMUSE_OPERATOR_TOKEN" not in joined
    assert "auth.json" not in joined
    assert "/home/iiyatu" not in joined
    assert "/bin/sh" not in command
    assert "-c" not in command

    frontend = build_bwrap_command(layout, GATE_SPECS["frontend_build"])
    assert "/usr/bin/npm" not in frontend
    assert frontend[-3:] == [
        "/tools/node",
        "/workspace/frontend/node_modules/next/dist/bin/next",
        "build",
    ]
    assert layout.node is not None
    assert ["--ro-bind", str(layout.node), "/tools/node"] == frontend[
        frontend.index(str(layout.node)) - 1 : frontend.index(str(layout.node)) + 2
    ]

    pnpm_modules = tmp_path / "pnpm-node-modules"
    pnpm_modules.mkdir()
    node_profile_layout = SandboxLayout(
        **{
            **layout.__dict__,
            "frontend_node_modules": None,
            "node_modules": pnpm_modules,
            "node_modules_mount_path": "/workspace/node_modules",
        }
    )
    pnpm = build_bwrap_command(node_profile_layout, GATE_SPECS["node_pnpm_jest"])
    assert "/usr/bin/npm" not in pnpm
    assert "/usr/bin/pnpm" not in pnpm
    assert "/bin/sh" not in pnpm
    assert pnpm[-6:] == [
        "--chdir",
        "/workspace",
        "--",
        "/tools/node",
        "/workspace/node_modules/jest/bin/jest.js",
        "--runInBand",
    ]


def test_bwrap_mounts_digest_bound_ignored_python_extensions_read_only(
    tmp_path: Path,
) -> None:
    repo = _marker_repository(tmp_path)
    extension = repo / "src" / "demo" / "_core.abi3.so"
    extension.parent.mkdir(parents=True)
    extension.write_bytes(b"native-extension")
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("\n*.so\n")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "ignore build"], check=True)
    artifacts = sandbox.discover_python_extension_artifacts(repo)

    assert len(artifacts) == 1
    assert artifacts[0][1] == "src/demo/_core.abi3.so"
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir(mode=0o700)
    snapshot = snapshot_root / "artifact.so"
    sandbox._snapshot_artifact(artifacts[0][0], snapshot, artifacts[0][2])
    extension.write_bytes(b"replaced-after-proof")
    layout = _layout(tmp_path / "layout")
    layout = SandboxLayout(
        **{
            **layout.__dict__,
            "python_extension_artifacts": ((snapshot, artifacts[0][1]),),
            "artifact_snapshot_root": snapshot_root,
        }
    )
    try:
        assert snapshot.read_bytes() == b"native-extension"
        assert snapshot.stat().st_mode & 0o777 == 0o400
        command = build_bwrap_command(layout, GATE_SPECS["python_uv_pytest"])
        source = str(snapshot)
        index = command.index(source)
        assert command[index - 1 : index + 2] == [
            "--ro-bind",
            source,
            "/workspace/src/demo/_core.abi3.so",
        ]
    finally:
        layout.close()
    assert not snapshot_root.exists()


def test_extension_discovery_excludes_tracked_and_unignored_artifacts(tmp_path: Path) -> None:
    repo = _marker_repository(tmp_path)
    source = repo / "src" / "generated"
    source.mkdir(parents=True)
    tracked = source / "tracked.so"
    tracked.write_bytes(b"tracked")
    subprocess.run(["git", "-C", str(repo), "add", "src/generated/tracked.so"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "tracked extension"], check=True)
    (source / "unignored.so").write_bytes(b"unignored")

    assert sandbox.discover_python_extension_artifacts(repo) == ()


def test_extension_discovery_returns_stable_relative_order(tmp_path: Path) -> None:
    repo = _marker_repository(tmp_path)
    source = repo / "src" / "generated"
    source.mkdir(parents=True)
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("\n*.so\n")
    (source / "z.so").write_bytes(b"z")
    (source / "a.so").write_bytes(b"a")

    artifacts = sandbox.discover_python_extension_artifacts(repo)

    assert tuple(relative for _path, relative, _digest in artifacts) == (
        "src/generated/a.so",
        "src/generated/z.so",
    )


def test_extension_discovery_rejects_more_than_bounded_ignored_artifacts(
    tmp_path: Path,
) -> None:
    repo = _marker_repository(tmp_path)
    source = repo / "src" / "generated"
    source.mkdir(parents=True)
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("\n*.so\n")
    for index in range(17):
        (source / f"artifact-{index}.so").write_bytes(b"native")

    with pytest.raises(RoomExecutionSandboxError) as error:
        sandbox.discover_python_extension_artifacts(repo)

    assert error.value.code == "execution_backend_dependencies_unavailable"


def test_extension_discovery_rejects_aggregate_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _marker_repository(tmp_path)
    source = repo / "src" / "generated"
    source.mkdir(parents=True)
    (repo / ".gitignore").write_text("*.so\n", encoding="utf-8")
    (source / "artifact.so").write_bytes(b"too-large")
    monkeypatch.setattr(sandbox, "_MAX_PYTHON_EXTENSION_BYTES", 1)

    with pytest.raises(RoomExecutionSandboxError) as error:
        sandbox.discover_python_extension_artifacts(repo)

    assert error.value.code == "execution_backend_dependencies_unavailable"


def test_extension_discovery_rejects_ignored_symlink(tmp_path: Path) -> None:
    repo = _marker_repository(tmp_path)
    source = repo / "src" / "generated"
    source.mkdir(parents=True)
    (repo / ".gitignore").write_text("*.so\n", encoding="utf-8")
    target = source / "target.bin"
    target.write_bytes(b"target")
    (source / "artifact.so").symlink_to(target.name)

    with pytest.raises(RoomExecutionSandboxError) as error:
        sandbox.discover_python_extension_artifacts(repo)

    assert error.value.code == "execution_backend_dependencies_unavailable"


def test_internal_spec_rejects_workdir_escape(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    bad = GateSpec("bad", ("/usr/bin/true",), "/workspace/../etc", 1.0)
    with pytest.raises(RoomExecutionSandboxError) as error:
        run_gate(layout, probe=bad)
    assert error.value.code == "execution_gate_invalid"


def test_resource_sample_returns_stable_limit_reason_with_no_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)

    class Process:
        pid = 999_999

        def __init__(self) -> None:
            read_fd, self.write_fd = os.pipe()
            self.stdout = os.fdopen(read_fd, "rb", buffering=0)
            self.done = False

        def poll(self):
            return -15 if self.done else None

        def wait(self, timeout=None):
            return -15

    process = Process()

    def terminate(target):
        assert target is process
        process.done = True
        os.close(process.write_fd)

    monkeypatch.setattr(sandbox, "_terminate_fenced_process", terminate)

    result = run_gate(
        layout,
        probe=GateSpec("internal_probe", ("/usr/bin/true",), "/workspace", 1.0),
        popen=lambda *_args, **_kwargs: process,
        resource_sampler=lambda _pid: GateResourceSample(0, 65, 0),
    )

    assert result.status == "failed"
    assert result.reason_code == "execution_gate_process_limit"
    assert not hasattr(result, "output")


def test_gate_output_is_continuously_drained_and_fully_hashed_with_bounded_tail(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    payload_size = 2 * 1024 * 1024

    def launch(_command, **kwargs):
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                f"import os;os.write(1,b'x'*{payload_size})",
            ],
            **kwargs,
        )

    result = run_gate(
        layout,
        probe=GateSpec("output_probe", ("/usr/bin/true",), "/workspace", 10.0),
        output_limit_bytes=1024,
        popen=launch,
        resource_sampler=lambda _pid: GateResourceSample(0, 1, 0),
    )

    assert result.status == "passed"
    assert result.output_bytes == payload_size
    assert result.output_digest == f"sha256:{hashlib.sha256(b'x' * payload_size).hexdigest()}"
    assert not hasattr(result, "output")


def test_continuous_writer_cannot_starve_timeout_checks(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    def launch(_command, **kwargs):
        return subprocess.Popen(
            [sys.executable, "-c", "import os\nwhile True: os.write(1,b'x'*65536)"],
            **kwargs,
        )

    result = run_gate(
        layout,
        probe=GateSpec("writer_probe", ("/usr/bin/true",), "/workspace", 0.2),
        output_limit_bytes=1024,
        popen=launch,
        resource_sampler=lambda _pid: GateResourceSample(0, 1, 0),
    )

    assert result.status == "failed"
    assert result.reason_code == "execution_gate_timeout"
    assert result.duration_ms < 3_000


def test_resource_sampler_failure_fails_closed_and_reaps_child(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    spawned: list[subprocess.Popen[bytes]] = []

    def launch(_command, **kwargs):
        process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], **kwargs)
        spawned.append(process)
        return process

    def failed_sampler(_pid: int) -> GateResourceSample:
        raise OSError("proc unavailable")

    result = run_gate(
        layout,
        probe=GateSpec("resource_probe", ("/usr/bin/true",), "/workspace", 10.0),
        popen=launch,
        resource_sampler=failed_sampler,
    )

    assert result.status == "failed"
    assert result.reason_code == "execution_gate_resource_probe_failed"
    assert spawned[0].poll() is not None


def test_resource_probe_exit_race_preserves_a_successful_gate(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    spawned: list[subprocess.Popen[bytes]] = []

    def launch(_command, **kwargs):
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            **kwargs,
        )
        spawned.append(process)
        return process

    def raced_sampler(_pid: int) -> GateResourceSample:
        deadline = time.monotonic() + 10.0
        while spawned[0].poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        raise FileNotFoundError("process exited during /proc sampling")

    result = run_gate(
        layout,
        probe=GateSpec("resource_probe", ("/usr/bin/true",), "/workspace", 10.0),
        popen=launch,
        resource_sampler=raced_sampler,
    )

    assert result.status == "passed"
    assert result.reason_code is None


def test_proc_and_directory_probe_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read_text = Path.read_text
    children = f"/proc/{os.getpid()}/task/{os.getpid()}/children"

    def failed_children(path: Path, *args, **kwargs):
        if str(path) == children:
            raise PermissionError("unreadable proc")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failed_children)
    with pytest.raises(PermissionError):
        sandbox._process_tree(os.getpid())
    monkeypatch.undo()

    original_readlink = os.readlink

    def failed_namespace(path):
        if path == "/proc/self/ns/mnt":
            raise PermissionError("unreadable namespace")
        return original_readlink(path)

    monkeypatch.setattr(os, "readlink", failed_namespace)
    with pytest.raises(PermissionError):
        sandbox._sandbox_scratch_bytes((os.getpid(),))
    monkeypatch.undo()

    monkeypatch.setattr(os, "scandir", lambda _path: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(RoomExecutionSandboxError) as error:
        sandbox._directory_size(tmp_path)
    assert error.value.code == "execution_gate_resource_probe_failed"


def test_directory_probe_deadline_remains_hard_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "file").write_text("value", encoding="utf-8")
    clock = iter((10.0, 16.0))
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(clock))

    with pytest.raises(sandbox._DirectoryScanDeadline):
        sandbox._directory_size(tmp_path)


def test_resource_monitor_reuses_one_timeout_but_three_timeouts_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = sandbox.GateResourceMonitor(tmp_path)
    monkeypatch.setattr(sandbox, "_process_tree", lambda _pid: {123})
    monkeypatch.setattr(sandbox, "_process_rss", lambda _pid: 0)
    monkeypatch.setattr(sandbox, "_sandbox_scratch_bytes", lambda _pids: 7)
    responses: list[object] = [
        sandbox._DirectoryScanDeadline(),
        monitor._stage_baseline + 11,
    ]

    def scan(_root: Path) -> int:
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return int(value)

    monkeypatch.setattr(sandbox, "_directory_size", scan)
    monitor._last_scratch_scan = 0
    first = monitor(123)
    monitor._last_scratch_scan = 0
    second = monitor(123)

    assert first.scratch_bytes == 0
    assert second.scratch_bytes == 18

    monkeypatch.setattr(
        sandbox,
        "_directory_size",
        lambda _root: (_ for _ in ()).throw(sandbox._DirectoryScanDeadline()),
    )
    for _index in range(2):
        monitor._last_scratch_scan = 0
        monitor(123)
    monitor._last_scratch_scan = 0
    with pytest.raises(RoomExecutionSandboxError) as error:
        monitor(123)
    assert error.value.code == "execution_gate_resource_probe_failed"


def _unreaped_defunct_child() -> subprocess.Popen[bytes]:
    child = subprocess.Popen(["/usr/bin/true"])
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            raw = Path(f"/proc/{child.pid}/stat").read_text(encoding="ascii")
        except OSError:
            break
        if raw.rpartition(")")[2].split()[:1] == ["Z"]:
            return child
        time.sleep(0.01)
    child.wait()
    raise AssertionError("child never reached the unreaped defunct state")


def test_scratch_probe_ignores_unreaped_defunct_child_processes() -> None:
    child = _unreaped_defunct_child()
    try:
        assert sandbox._sandbox_scratch_bytes((child.pid,)) == 0
    finally:
        child.wait()


def test_private_tmpfs_probe_ignores_unreaped_defunct_child_processes() -> None:
    child = _unreaped_defunct_child()
    try:
        assert sandbox._process_has_private_tmpfs(child.pid) is False
    finally:
        child.wait()


def test_resource_monitor_real_scan_error_fails_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = sandbox.GateResourceMonitor(tmp_path)
    monkeypatch.setattr(sandbox, "_process_tree", lambda _pid: {123})
    monkeypatch.setattr(sandbox, "_process_rss", lambda _pid: 0)
    monkeypatch.setattr(
        sandbox,
        "_directory_size",
        lambda _root: (_ for _ in ()).throw(
            RoomExecutionSandboxError("execution_gate_resource_probe_failed")
        ),
    )
    monitor._last_scratch_scan = 0

    with pytest.raises(RoomExecutionSandboxError) as error:
        monitor(123)

    assert error.value.code == "execution_gate_resource_probe_failed"


def test_repository_evidence_binds_head_and_gate_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    readme = repo / "README.md"
    readme.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "one"], check=True)
    profile = get_execution_gate_profile("docs/v1")
    first = build_repository_manifest_digest(repo, profile)
    capability = build_toolchain_capability_digest(
        repo,
        profile,
        gate_ids=("patch_diff_check",),
        bwrap_path="/usr/bin/true",
    )
    original = GATE_SPECS["patch_diff_check"]
    monkeypatch.setitem(
        sandbox.GATE_SPECS,
        "patch_diff_check",
        GateSpec(original.gate_id, original.argv, original.cwd, original.timeout_s + 1),
    )
    changed_capability = build_toolchain_capability_digest(
        repo,
        profile,
        gate_ids=("patch_diff_check",),
        bwrap_path="/usr/bin/true",
    )

    readme.write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "two", "-q"], check=True)
    second = build_repository_manifest_digest(repo, profile)

    assert first != second
    assert capability.startswith("sha256:")
    assert capability != changed_capability
    assert not (repo / ".venv").exists()


def _marker_repository(tmp_path: Path, *, project_name: str = "demo") -> Path:
    repo = tmp_path / "marker-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        f"[project]\nname = {project_name!r}\n",
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        "version = 1\n\n"
        "[[package]]\n"
        f"name = {project_name!r}\n"
        "version = '0.1.0'\n"
        "source = { editable = '.' }\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "markers"], check=True)
    return repo


def test_python_profile_manifest_requires_matching_editable_uv_root(tmp_path: Path) -> None:
    repo = _marker_repository(tmp_path)
    profile = get_execution_gate_profile("python-uv/v1")

    digest = build_repository_manifest_digest(repo, profile)

    assert digest.startswith("sha256:")
    (repo / "uv.lock").write_text(
        "version = 1\n\n"
        "[[package]]\nname = 'demo'\nversion = '0.1.0'\n"
        "source = { registry = 'https://example.invalid' }\n",
        encoding="utf-8",
    )
    with pytest.raises(RoomExecutionSandboxError) as raised:
        build_repository_manifest_digest(repo, profile)
    assert raised.value.code == "execution_gate_profile_marker_invalid"


def test_xmuse_manifest_requires_exact_frontend_package_and_lock_root_names(
    tmp_path: Path,
) -> None:
    repo = _marker_repository(tmp_path, project_name="xmuse")
    frontend = repo / "frontend"
    frontend.mkdir()
    package = {"name": "xmuse-chat-frontend", "version": "0.1.0"}
    lock = {
        "name": "xmuse-chat-frontend",
        "lockfileVersion": 3,
        "packages": {"": {"name": "xmuse-chat-frontend", "version": "0.1.0"}},
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    profile = get_execution_gate_profile("xmuse-monorepo/v2")

    assert build_repository_manifest_digest(repo, profile).startswith("sha256:")
    lock["packages"][""]["name"] = "wrong-frontend"
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(RoomExecutionSandboxError) as raised:
        build_repository_manifest_digest(repo, profile)
    assert raised.value.code == "execution_gate_profile_marker_invalid"


def test_profile_marker_parsing_is_bounded_and_fail_closed(tmp_path: Path) -> None:
    repo = _marker_repository(tmp_path)
    (repo / "pyproject.toml").write_bytes(b"#" * (2 * 1024 * 1024 + 1))

    with pytest.raises(RoomExecutionSandboxError) as raised:
        build_repository_manifest_digest(repo, get_execution_gate_profile("python-uv/v1"))

    assert raised.value.code == "execution_gate_profile_marker_invalid"


def test_profile_marker_fd_rejects_symlinks_and_concurrent_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "marker.toml"
    marker.write_bytes(b"x" * (256 * 1024))
    link = tmp_path / "marker-link.toml"
    link.symlink_to(marker)
    with pytest.raises(RoomExecutionSandboxError) as symlinked:
        sandbox._bounded_marker_bytes(link)
    assert symlinked.value.code == "execution_gate_profile_marker_invalid"

    original_read = os.read
    grew = False

    def grow_after_first_read(descriptor: int, amount: int) -> bytes:
        nonlocal grew
        chunk = original_read(descriptor, amount)
        if chunk and not grew:
            grew = True
            with marker.open("ab") as handle:
                handle.write(b"y")
        return chunk

    monkeypatch.setattr(os, "read", grow_after_first_read)
    with pytest.raises(RoomExecutionSandboxError) as growing:
        sandbox._bounded_marker_bytes(marker)
    assert growing.value.code == "execution_gate_profile_marker_invalid"


def test_python_toolchain_evidence_never_executes_workspace_binaries(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sentinel = tmp_path / "must-not-exist"
    (repo / "pyproject.toml").write_text("[project]\nname='probe'\n", encoding="utf-8")
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    bin_dir = repo / ".venv" / "bin"
    site = repo / ".venv" / "lib" / "python3.11" / "site-packages"
    bin_dir.mkdir(parents=True)
    for name in ("mypy", "pytest"):
        (site / name).mkdir(parents=True)
        metadata = site / f"{name}-1.0.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text(f"Name: {name}\nVersion: 1.0\n", encoding="utf-8")
    malicious = f"#!/bin/sh\ntouch {sentinel}\n"
    for name in ("python3", "ruff"):
        target = bin_dir / name
        target.write_text(malicious, encoding="utf-8")
        target.chmod(0o755)
    (repo / ".venv" / "pyvenv.cfg").write_text("home = /untrusted\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "pyproject.toml", "uv.lock"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    profile = get_execution_gate_profile("python-uv/v1")

    digest = build_toolchain_capability_digest(
        repo,
        profile,
        gate_ids=profile.gate_ids,
        bwrap_path="/usr/bin/true",
    )

    assert digest.startswith("sha256:")
    assert not sentinel.exists()


def test_python_toolchain_accepts_bounded_executable_larger_than_marker_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bin_dir = repo / ".venv" / "bin"
    site = repo / ".venv" / "lib" / "python3.11" / "site-packages"
    bin_dir.mkdir(parents=True)
    for name in ("mypy", "pytest"):
        (site / name).mkdir(parents=True)
        metadata = site / f"{name}-1.0.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text(f"Name: {name}\nVersion: 1.0\n", encoding="utf-8")
    python = bin_dir / "python3"
    python.write_bytes(b"python")
    python.chmod(0o755)
    ruff = bin_dir / "ruff"
    with ruff.open("wb") as handle:
        handle.truncate(sandbox._MAX_EVIDENCE_FILE_BYTES + 1)
    ruff.chmod(0o755)
    (repo / ".venv" / "pyvenv.cfg").write_text("home = /trusted\n", encoding="utf-8")
    monkeypatch.setattr(sandbox, "_tool_version", lambda *_args: "fixed")

    digest = build_toolchain_capability_digest(
        repo,
        get_execution_gate_profile("python-uv/v1"),
        gate_ids=("python_uv_ruff", "python_uv_mypy", "python_uv_pytest"),
        bwrap_path="/usr/bin/true",
    )

    assert digest.startswith("sha256:")


def test_discovery_rejects_extension_bytes_changed_after_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _marker_repository(tmp_path)
    bin_dir = repo / ".venv" / "bin"
    site = repo / ".venv" / "lib" / "python3.11" / "site-packages"
    bin_dir.mkdir(parents=True)
    for name in ("mypy", "pytest"):
        (site / name).mkdir(parents=True)
        metadata = site / f"{name}-1.0.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text(f"Name: {name}\nVersion: 1.0\n", encoding="utf-8")
    for name in ("python3", "ruff"):
        executable = bin_dir / name
        executable.write_bytes(name.encode("ascii"))
        executable.chmod(0o755)
    (repo / ".venv" / "pyvenv.cfg").write_text("home = /trusted\n", encoding="utf-8")
    extension = repo / "src" / "demo" / "_core.abi3.so"
    extension.parent.mkdir(parents=True)
    extension.write_bytes(b"authorized")
    (repo / ".gitignore").write_text(".venv\n*.so\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "toolchain"], check=True)
    monkeypatch.setattr(sandbox, "_tool_version", lambda *_args: "fixed")
    profile = get_execution_gate_profile("python-uv/v1")
    expected = build_toolchain_capability_digest(repo, profile, gate_ids=profile.gate_ids)

    extension.write_bytes(b"replaced-after-authorization")

    with pytest.raises(RoomExecutionSandboxError) as error:
        sandbox.discover_sandbox_layout(
            stage=repo,
            execution_root=repo,
            gate_ids=profile.gate_ids,
            profile=profile,
            expected_toolchain_capability_digest=expected,
        )
    assert error.value.code == "execution_toolchain_capability_drift"
    assert not tuple(tmp_path.glob(".xmuse-python-artifacts-*"))


def test_discovery_reproves_complete_profile_for_path_selected_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _marker_repository(tmp_path)
    (repo / "frontend" / "node_modules").mkdir(parents=True)
    profile = get_execution_gate_profile("xmuse-monorepo/v2")
    selected = ("patch_diff_check", "frontend_typecheck")
    observed_gate_ids: list[tuple[str, ...]] = []

    def capability(
        _root: Path,
        _profile,
        *,
        gate_ids,
        bwrap_path,
        python_extension_evidence,
    ) -> str:
        del bwrap_path, python_extension_evidence
        observed_gate_ids.append(tuple(gate_ids))
        return "sha256:" + "a" * 64

    monkeypatch.setattr(sandbox, "build_toolchain_capability_digest", capability)
    monkeypatch.setattr(
        sandbox.shutil,
        "which",
        lambda name: "/usr/bin/true" if name in {"bwrap", "node"} else None,
    )

    with sandbox.discover_sandbox_layout(
        stage=repo,
        execution_root=repo,
        gate_ids=selected,
        bwrap_path="/usr/bin/true",
        profile=profile,
        expected_toolchain_capability_digest="sha256:" + "a" * 64,
    ):
        pass

    assert observed_gate_ids == [profile.gate_ids]


def test_frontend_toolchain_requires_every_fixed_gate_entry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    node_modules = repo / "frontend" / "node_modules"
    node_modules.mkdir(parents=True)
    (node_modules / ".package-lock.json").write_text("{}\n", encoding="utf-8")
    profile = get_execution_gate_profile("xmuse-monorepo/v2")

    with pytest.raises(RoomExecutionSandboxError) as error:
        build_toolchain_capability_digest(
            repo,
            profile,
            gate_ids=("patch_diff_check", "frontend_build"),
            bwrap_path="/usr/bin/true",
        )

    assert error.value.code == "execution_frontend_dependencies_unavailable"


def test_frontend_toolchain_digest_binds_discovered_node_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    entry = repo / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next"
    entry.parent.mkdir(parents=True)
    entry.write_text("next\n", encoding="utf-8")
    (repo / "frontend" / "node_modules" / ".package-lock.json").write_text("{}\n", encoding="utf-8")
    node = tmp_path / "setup-node"
    node.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n# first\n", encoding="utf-8")
    node.chmod(0o755)
    original_which = sandbox.shutil.which
    original_tool_version = sandbox._tool_version
    monkeypatch.setattr(
        sandbox.shutil,
        "which",
        lambda name: str(node) if name == "node" else original_which(name),
    )
    monkeypatch.setattr(
        sandbox,
        "_tool_version",
        lambda path, *args: "v22.0.0" if Path(path) == node else original_tool_version(path, *args),
    )
    profile = get_execution_gate_profile("xmuse-monorepo/v2")

    first = build_toolchain_capability_digest(
        repo,
        profile,
        gate_ids=("frontend_build",),
        bwrap_path="/usr/bin/true",
    )
    node.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n# second\n", encoding="utf-8")
    second = build_toolchain_capability_digest(
        repo,
        profile,
        gate_ids=("frontend_build",),
        bwrap_path="/usr/bin/true",
    )

    assert first != second


REMIX_RUNNER_FILES = (
    "packages/test/src/cli.ts",
    "packages/test/src/lib/runner.ts",
    "packages/assert/src/index.ts",
    "packages/node-tsx/src/load-module.ts",
    "packages/terminal/src/index.ts",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _remix_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "remix-repo"
    files = {
        "package.json": json.dumps({"name": "remix-monorepo", "packageManager": "pnpm@10.34.2"}),
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "pnpm-workspace.yaml": "packages:\n  - packages/*\n",
        "packages/headers/package.json": json.dumps({"name": "@remix-run/headers"}),
        "packages/headers/src/index.ts": "export {}\n",
        **{name: "export {}\n" for name in REMIX_RUNNER_FILES},
    }
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    # Installed, untracked dependencies: root store plus per-package links.
    (repo / "node_modules" / ".pnpm").mkdir(parents=True)
    (repo / "node_modules" / ".modules.yaml").write_text("layoutVersion: 5\n", encoding="utf-8")
    tsc = repo / "node_modules" / "typescript" / "bin" / "tsc"
    tsc.parent.mkdir(parents=True)
    tsc.write_text("// tsc\n", encoding="utf-8")
    for package in ("headers", "test"):
        installed = repo / "packages" / package / "node_modules" / "@remix-run"
        installed.mkdir(parents=True)
        (installed / "assert").symlink_to("../../../assert")
    return repo


def _remix_stage(repo: Path, tmp_path: Path) -> Path:
    stage = tmp_path / "stage"
    _git(repo, "worktree", "add", "-q", "--detach", str(stage))
    return stage


def test_remix_gate_command_mounts_runner_read_only_from_the_execution_root(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    root_modules = tmp_path / "root-node-modules"
    headers_modules = tmp_path / "headers-node-modules"
    runner = tmp_path / "trusted-runner-test"
    for path in (root_modules, headers_modules, runner):
        path.mkdir()
    remix_layout = SandboxLayout(
        **{
            **layout.__dict__,
            "frontend_node_modules": None,
            "node_modules": root_modules,
            "node_modules_mount_path": "/workspace/node_modules",
            "gate_packages": ("headers", "multipart-parser"),
            "package_node_modules": (
                (headers_modules, "/workspace/packages/headers/node_modules"),
            ),
            "runner_mounts": ((runner, "/workspace/packages/test"),),
        }
    )

    command = build_bwrap_command(remix_layout, GATE_SPECS["node_pnpm_remix_test"])

    def bound(source: Path) -> list[str]:
        index = command.index(str(source))
        return command[index - 1 : index + 2]

    assert command[-6:] == [
        "--chdir",
        "/workspace",
        "--",
        "/tools/node",
        sandbox.REMIX_GATE_DRIVER_MOUNT,
        "test",
    ]
    assert bound(sandbox.REMIX_GATE_DRIVER) == [
        "--ro-bind",
        str(sandbox.REMIX_GATE_DRIVER),
        sandbox.REMIX_GATE_DRIVER_MOUNT,
    ]
    # The runner replaces the stage copy read-only, after the writable stage bind.
    assert bound(runner) == ["--ro-bind", str(runner), "/workspace/packages/test"]
    assert command.index(str(runner)) > command.index("/workspace")
    assert bound(headers_modules) == [
        "--ro-bind",
        str(headers_modules),
        "/workspace/packages/headers/node_modules",
    ]
    packages = command.index("XMUSE_GATE_PACKAGES")
    assert command[packages + 1] == "headers,multipart-parser"
    assert "/bin/sh" not in command
    # Other node gates never see the driver, the runner mount or the package list.
    jest = build_bwrap_command(remix_layout, GATE_SPECS["node_pnpm_jest"])
    assert str(sandbox.REMIX_GATE_DRIVER) not in jest
    assert str(runner) not in jest
    assert "XMUSE_GATE_PACKAGES" not in jest

    for forged in (
        SandboxLayout(**{**remix_layout.__dict__, "gate_packages": ("../etc",)}),
        SandboxLayout(**{**remix_layout.__dict__, "runner_mounts": ()}),
    ):
        with pytest.raises(RoomExecutionSandboxError) as raised:
            build_bwrap_command(forged, GATE_SPECS["node_pnpm_remix_test"])
        assert raised.value.code == "execution_gate_plan_invalid"


@pytest.mark.parametrize("runner_file", REMIX_RUNNER_FILES)
def test_remix_manifest_freezes_every_runner_package(tmp_path: Path, runner_file: str) -> None:
    repo = _remix_repository(tmp_path)
    profile = get_execution_gate_profile("remix-monorepo/v1")

    before = sandbox._validated_repository_marker_contract(repo, profile)
    assert build_repository_manifest_digest(repo, profile).startswith("sha256:")
    # A package source change leaves the runner evidence alone ...
    (repo / "packages/headers/src/index.ts").write_text("export const x = 1\n", encoding="utf-8")
    assert sandbox._validated_repository_marker_contract(repo, profile) == before
    # ... while a byte of any runner package changes it.
    (repo / runner_file).write_text("export const pass = true\n", encoding="utf-8")
    assert sandbox._validated_repository_marker_contract(repo, profile) != before


def test_remix_manifest_requires_the_runner_entry(tmp_path: Path) -> None:
    repo = _remix_repository(tmp_path)
    (repo / "packages/test/src/cli.ts").unlink()

    with pytest.raises(RoomExecutionSandboxError) as raised:
        build_repository_manifest_digest(repo, get_execution_gate_profile("remix-monorepo/v1"))
    assert raised.value.code == "execution_gate_profile_marker_invalid"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_remix_capability_reproves_runner_bytes_and_package_dependencies(
    tmp_path: Path,
) -> None:
    repo = _remix_repository(tmp_path)
    profile = get_execution_gate_profile("remix-monorepo/v1")

    def capability() -> str:
        return build_toolchain_capability_digest(repo, profile, bwrap_path="/usr/bin/true")

    first = capability()
    assert capability() == first
    (repo / "packages/terminal/src/index.ts").write_text("export const y = 2\n", encoding="utf-8")
    second = capability()
    assert second != first
    link = repo / "packages/headers/node_modules/@remix-run/assert"
    link.unlink()
    link.symlink_to("../../../test")
    assert capability() != second


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_remix_layout_takes_runner_and_dependencies_from_the_execution_root(
    tmp_path: Path,
) -> None:
    repo = _remix_repository(tmp_path)
    stage = _remix_stage(repo, tmp_path)
    # A symlinked node_modules is never mounted; a package missing from the
    # stage gets no mount either.
    (repo / "packages/ghost").mkdir()
    (repo / "packages/ghost/node_modules").symlink_to(repo / "node_modules")
    bwrap = tmp_path / "bwrap"
    bwrap.write_bytes(b"bwrap")
    gate_ids = ("node_pnpm_remix_typecheck", "node_pnpm_remix_test")

    layout = sandbox.discover_sandbox_layout(
        stage=stage,
        execution_root=repo,
        gate_ids=gate_ids,
        bwrap_path=bwrap,
        gate_packages=("headers",),
    )

    assert layout.gate_packages == ("headers",)
    # Runner packages come whole from the root (their node_modules included).
    assert layout.package_node_modules == (
        (
            (repo / "packages/headers/node_modules").resolve(),
            "/workspace/packages/headers/node_modules",
        ),
    )
    assert dict((mount, source) for source, mount in layout.runner_mounts) == {
        f"/workspace/packages/{name}": (repo / "packages" / name).resolve()
        for name in ("assert", "node-tsx", "terminal", "test")
    }
    for bad_gate_ids, packages in (
        (("node_pnpm_jest",), ("headers",)),
        (gate_ids, ("Headers",)),
    ):
        with pytest.raises(RoomExecutionSandboxError) as raised:
            sandbox.discover_sandbox_layout(
                stage=stage,
                execution_root=repo,
                gate_ids=bad_gate_ids,
                bwrap_path=bwrap,
                gate_packages=packages,
            )
        assert raised.value.code == "execution_gate_plan_invalid"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_remix_driver_runs_fixed_entrypoints_per_package_and_never_passes_unchecked(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    log = tmp_path / "calls.jsonl"
    record = (
        'import { appendFileSync, existsSync } from "node:fs";\n'
        "const call = (extra) => appendFileSync("
        f"{json.dumps(str(log))}, JSON.stringify({{cwd: process.cwd(), ...extra}}) + '\\n');\n"
    )
    for relative, content in {
        "node_modules/typescript/bin/tsc": (
            record
            + "call({tool: 'tsc', argv: process.argv.slice(2)});\n"
            + 'process.exit(existsSync("fail-here") ? 1 : 0);\n'
        ),
        # The frozen runner: only its public runRemixTest API is used.
        "packages/test/src/cli.ts": (
            record
            + "export async function runRemixTest(options) {\n"
            + "  call({tool: 'runRemixTest', options});\n"
            + '  return existsSync("fail-here") ? 1 : 0;\n'
            + "}\n"
        ),
        "packages/ok/package.json": json.dumps(
            {"scripts": {"typecheck": "exit 1", "test": "exit 1"}}
        ),
        "packages/broken/package.json": json.dumps({"scripts": {"typecheck": "x", "test": "x"}}),
        "packages/broken/fail-here": "",
        "packages/untested/package.json": json.dumps({"scripts": {"typecheck": "x"}}),
    }.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None

    def drive(mode: str, packages: str) -> subprocess.CompletedProcess[str]:
        log.unlink(missing_ok=True)
        return subprocess.run(
            [node, str(sandbox.REMIX_GATE_DRIVER), mode],
            env={
                "PATH": "/usr/bin:/bin",
                "XMUSE_GATE_WORKSPACE": str(workspace),
                "XMUSE_GATE_PACKAGES": packages,
            },
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls() -> list[dict[str, object]]:
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    # The scripts say "exit 1": a pass proves script text is never executed.
    typecheck = drive("typecheck", "ok")
    assert typecheck.returncode == 0, typecheck.stdout + typecheck.stderr
    assert calls() == [{"cwd": str(workspace / "packages/ok"), "tool": "tsc", "argv": ["--noEmit"]}]
    test = drive("test", "ok")
    assert test.returncode == 0, test.stdout + test.stderr
    assert calls() == [
        {
            "cwd": str(workspace / "packages/ok"),
            "tool": "runRemixTest",
            "options": {
                "cwd": str(workspace / "packages/ok"),
                "type": ["server"],
                "concurrency": 2,
            },
        }
    ]
    # One failing package fails the gate; the others still run.
    failing = drive("test", "broken,ok")
    assert failing.returncode == 1
    assert [call["cwd"] for call in calls()] == [
        str(workspace / "packages/broken"),
        str(workspace / "packages/ok"),
    ]
    # Nothing passes unchecked: no script, no package.json, or no package at all.
    untested = drive("test", "untested")
    assert untested.returncode == 1 and calls() == []
    assert "declares no test script" in untested.stdout
    assert drive("test", "missing").returncode == 1
    assert drive("test", "").returncode == 1
    assert drive("test", "../etc").returncode == 2
    assert drive("install", "ok").returncode == 2


@pytest.mark.parametrize(
    "source",
    [
        "import { Headers } from '@remix-run/headers'\n",
        "export * from '../../../headers/src/index.ts'\n",
        "const cli = await import('remix/test/cli')\n",
        "import 'remix'\n",
    ],
)
def test_remix_runner_closure_rejects_imports_of_candidate_writable_code(
    tmp_path: Path, source: str
) -> None:
    repo = _remix_repository(tmp_path)
    (repo / "packages/test/src/lib/runner.ts").write_text(source, encoding="utf-8")
    _git(repo, "commit", "-qam", "runner imports outside the frozen set")

    with pytest.raises(RoomExecutionSandboxError) as raised:
        sandbox._remix_runner_contract(repo)
    assert raised.value.code == "execution_gate_profile_marker_invalid"


def test_remix_runner_closure_allows_itself_installed_deps_comments_and_own_tests(
    tmp_path: Path,
) -> None:
    repo = _remix_repository(tmp_path)
    (repo / "packages/test/src/lib/runner.ts").write_text(
        "import * as path from 'node:path'\n"
        "import { assert } from '@remix-run/assert'\n"
        "import { load } from '../../../node-tsx/src/load-module.ts'\n"
        "import picomatch from 'picomatch'\n"
        "/** import { runRemixTest } from 'remix/test/cli' */\n"
        "// import { Headers } from '@remix-run/headers'\n",
        encoding="utf-8",
    )
    # The runner's own tests and fixtures are never loaded for another package.
    for name in ("packages/test/src/test/e2e.ts", "packages/test/src/lib/runner.test.ts"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("import '@remix-run/node-fetch-server/test'\n", encoding="utf-8")
    _git(repo, "add", "packages/test/src")
    _git(repo, "commit", "-qm", "runner imports inside the frozen set")

    assert sandbox._remix_runner_contract(repo)["runner_entry"] == "packages/test/src/cli.ts"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_remix_capability_reproves_the_runner_packages_own_dependency_links(
    tmp_path: Path,
) -> None:
    repo = _remix_repository(tmp_path)
    profile = get_execution_gate_profile("remix-monorepo/v1")
    before = build_toolchain_capability_digest(repo, profile, bwrap_path="/usr/bin/true")

    link = repo / "packages/test/node_modules/@remix-run/assert"
    link.unlink()
    link.symlink_to("../../../headers")

    assert build_toolchain_capability_digest(repo, profile, bwrap_path="/usr/bin/true") != before
