from __future__ import annotations

import hashlib
import json
import os
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
    artifacts = sandbox._python_extension_artifacts(repo)

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

    def launch(_command, **kwargs):
        return subprocess.Popen(
            [sys.executable, "-c", "pass"],
            **kwargs,
        )

    def raced_sampler(_pid: int) -> GateResourceSample:
        time.sleep(0.02)
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
