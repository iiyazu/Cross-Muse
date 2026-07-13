"""Fixed, networkless sandbox for an authorized Room execution patch.

This module deliberately does not accept shell text.  A controller selects gate IDs
from :data:`GATE_SPECS`; this module turns those IDs into fixed argv and executes them
inside a Bubblewrap namespace.  Gate output is transient evidence: only a digest and
bounded process metadata leave this boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

from xmuse_core.chat.room_execution_profiles import (
    ExecutionGateProfile,
    get_execution_gate_profile,
)

SANDBOX_SCHEMA = "room_execution_sandbox/v2"
SANDBOX_ACTIVE_ENV = "XMUSE_EXECUTION_SANDBOX_ACTIVE"
DEFAULT_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024
DEFAULT_CANCEL_POLL_S = 0.25
_OUTPUT_DRAIN_BUDGET_BYTES = 1024 * 1024
_OUTPUT_DRAIN_BUDGET_S = 0.02
_DIRECTORY_SCAN_MAX_ENTRIES = 200_000
_DIRECTORY_SCAN_MAX_S = 5.0
_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_MAX_EVIDENCE_FILE_BYTES = 32 * _MIB
_MAX_PROFILE_MARKER_BYTES = 2 * _MIB


class RoomExecutionSandboxError(RuntimeError):
    """A stable sandbox or gate failure without raw child output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DirectoryScanDeadline(RuntimeError):
    """A bounded wall-clock scan ended without invalid filesystem evidence."""


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    argv: tuple[str, ...]
    cwd: str
    timeout_s: float


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    reason_code: str | None
    evidence_digest: str
    output_digest: str
    exit_code: int | None
    duration_ms: int
    output_bytes: int = 0


@dataclass(frozen=True)
class GateResourceLimits:
    max_rss_bytes: int
    max_processes: int
    max_scratch_bytes: int


@dataclass(frozen=True)
class GateResourceSample:
    rss_bytes: int
    process_count: int
    scratch_bytes: int


@dataclass(frozen=True)
class SandboxLayout:
    """Trusted host paths used to build the narrow Bubblewrap mount table."""

    stage: Path
    git_common_dir: Path
    git_dir: Path
    python_root: Path | None
    site_packages: Path | None
    ruff: Path | None
    frontend_node_modules: Path | None
    bwrap: Path


GATE_SPECS: Mapping[str, GateSpec] = {
    "patch_diff_check": GateSpec(
        "patch_diff_check",
        ("/usr/bin/git", "diff", "--check", "HEAD", "--"),
        "/workspace",
        60.0,
    ),
    "backend_ruff": GateSpec("backend_ruff", ("/tools/ruff", "check", "."), "/workspace", 180.0),
    "backend_mypy": GateSpec(
        "backend_mypy",
        (
            "/opt/python/bin/python3",
            "-m",
            "mypy",
            "--explicit-package-bases",
            "xmuse",
            "src/xmuse_core",
            "scripts/room_first_real_acceptance.py",
        ),
        "/workspace",
        600.0,
    ),
    "backend_pytest": GateSpec(
        "backend_pytest",
        ("/opt/python/bin/python3", "-m", "pytest", "-q"),
        "/workspace",
        1_800.0,
    ),
    "python_uv_ruff": GateSpec(
        "python_uv_ruff", ("/tools/ruff", "check", "."), "/workspace", 180.0
    ),
    "python_uv_mypy": GateSpec(
        "python_uv_mypy",
        ("/opt/python/bin/python3", "-m", "mypy", "src"),
        "/workspace",
        600.0,
    ),
    "python_uv_pytest": GateSpec(
        "python_uv_pytest",
        ("/opt/python/bin/python3", "-m", "pytest", "-q"),
        "/workspace",
        1_800.0,
    ),
    "frontend_typecheck": GateSpec(
        "frontend_typecheck",
        (
            "/usr/bin/node",
            "/workspace/frontend/node_modules/typescript/bin/tsc",
            "--noEmit",
        ),
        "/workspace/frontend",
        600.0,
    ),
    "frontend_lint": GateSpec(
        "frontend_lint",
        (
            "/usr/bin/node",
            "/workspace/frontend/node_modules/eslint/bin/eslint.js",
            ".",
        ),
        "/workspace/frontend",
        600.0,
    ),
    "frontend_vitest": GateSpec(
        "frontend_vitest",
        (
            "/usr/bin/node",
            "/workspace/frontend/node_modules/vitest/vitest.mjs",
            "run",
        ),
        "/workspace/frontend",
        900.0,
    ),
    "frontend_build": GateSpec(
        "frontend_build",
        (
            "/usr/bin/node",
            "/workspace/frontend/node_modules/next/dist/bin/next",
            "build",
        ),
        "/workspace/frontend",
        1_200.0,
    ),
}


def discover_sandbox_layout(
    *,
    stage: Path,
    execution_root: Path,
    gate_ids: Iterable[str] = (),
    bwrap_path: str | Path | None = None,
) -> SandboxLayout:
    """Resolve trusted dependency paths without consulting candidate content."""

    root = execution_root.resolve(strict=True)
    worktree = stage.resolve(strict=True)
    bwrap = Path(bwrap_path or shutil.which("bwrap") or "")
    if not bwrap or not bwrap.is_file():
        raise RoomExecutionSandboxError("execution_sandbox_unavailable")

    selected = tuple(gate_ids)
    unknown = set(selected).difference(GATE_SPECS)
    if unknown:
        raise RoomExecutionSandboxError("execution_gate_unknown")
    needs_python = any(_gate_uses_python(value) for value in selected)
    needs_frontend = any(value.startswith("frontend_") for value in selected)

    git_common = _git_path(root, "--git-common-dir")
    git_dir = _git_path(worktree, "--git-dir")
    python_root: Path | None = None
    site_packages: Path | None = None
    ruff: Path | None = None
    if needs_python:
        _python_entry, python, ruff_entry, dependency_root, _venv_config = _target_python_layout(
            root
        )
        python_root = python.parent.parent
        site_packages = dependency_root.resolve(strict=True)
        ruff = ruff_entry.resolve(strict=True)
    node_modules = root / "frontend" / "node_modules"
    if needs_frontend and not node_modules.is_dir():
        raise RoomExecutionSandboxError("execution_frontend_dependencies_unavailable")
    return SandboxLayout(
        stage=worktree,
        git_common_dir=git_common,
        git_dir=git_dir,
        python_root=python_root,
        site_packages=site_packages,
        ruff=ruff,
        frontend_node_modules=(node_modules.resolve(strict=True) if needs_frontend else None),
        bwrap=bwrap.resolve(strict=True),
    )


def build_repository_manifest_digest(execution_root: Path, profile: ExecutionGateProfile) -> str:
    """Digest fixed repository markers without persisting their paths or content."""

    trusted = _trusted_profile(profile)
    root = execution_root.resolve(strict=True)
    _git_path(root, "--git-common-dir")
    marker_names: tuple[str, ...]
    if trusted.profile_id == "docs/v1":
        marker_names = ()
    elif trusted.profile_id == "python-uv/v1":
        marker_names = ("pyproject.toml", "uv.lock")
    elif trusted.profile_id == "xmuse-monorepo/v2":
        marker_names = (
            "pyproject.toml",
            "uv.lock",
            "frontend/package.json",
            "frontend/package-lock.json",
        )
    else:  # pragma: no cover - registry exhaustiveness fence
        raise RoomExecutionSandboxError("execution_gate_profile_unknown")
    marker_contract = _validated_repository_marker_contract(root, trusted)
    markers = [{"name": name, "digest": _trusted_file_digest(root / name)} for name in marker_names]
    return _canonical_digest(
        {
            "schema_version": SANDBOX_SCHEMA,
            "profile_digest": trusted.profile_digest,
            "head": _git_head(root),
            "marker_contract": marker_contract,
            "markers": markers,
        }
    )


def build_toolchain_capability_digest(
    execution_root: Path,
    profile: ExecutionGateProfile,
    *,
    gate_ids: Iterable[str] | None = None,
    bwrap_path: str | Path | None = None,
) -> str:
    """Digest trusted local capabilities for the exact selected fixed gates."""

    trusted = _trusted_profile(profile)
    selected = tuple(trusted.gate_ids if gate_ids is None else gate_ids)
    expected_order = tuple(value for value in trusted.gate_ids if value in set(selected))
    if selected != expected_order or any(value not in GATE_SPECS for value in selected):
        raise RoomExecutionSandboxError("execution_gate_plan_invalid")
    root = execution_root.resolve(strict=True)
    bwrap = Path(bwrap_path or shutil.which("bwrap") or "")
    if not bwrap or not bwrap.is_file():
        raise RoomExecutionSandboxError("execution_sandbox_unavailable")
    facts: dict[str, object] = {
        "schema_version": SANDBOX_SCHEMA,
        "profile_digest": trusted.profile_digest,
        "gate_ids": list(selected),
        "gate_semantics": [_gate_semantics(value) for value in selected],
        "bwrap": _tool_version(bwrap, "--version"),
        "git": _tool_version(Path(shutil.which("git") or ""), "--version"),
    }
    if any(_gate_uses_python(value) for value in selected):
        _python_entry, python, ruff_entry, site_packages, venv_config = _target_python_layout(root)
        if (
            not site_packages.is_dir()
            or not (site_packages / "mypy").is_dir()
            or not (site_packages / "pytest").is_dir()
        ):
            raise RoomExecutionSandboxError("execution_backend_dependencies_unavailable")
        facts["python"] = _trusted_file_digest(python)
        facts["ruff"] = _trusted_file_digest(ruff_entry.resolve(strict=True))
        facts["pyvenv"] = _trusted_file_digest(venv_config)
        facts["python_dependencies"] = _dependency_metadata_digest(
            site_packages, ("mypy", "pytest")
        )
    if any(value.startswith("frontend_") for value in selected):
        node_modules = root / "frontend" / "node_modules"
        if not node_modules.is_dir():
            raise RoomExecutionSandboxError("execution_frontend_dependencies_unavailable")
        node = Path(shutil.which("node") or "")
        if not node.is_file():
            raise RoomExecutionSandboxError("execution_frontend_dependencies_unavailable")
        facts["node"] = _tool_version(node, "--version")
        installed_lock = node_modules / ".package-lock.json"
        facts["frontend_dependencies"] = _trusted_file_digest(installed_lock)
        facts["frontend_gate_entries"] = _frontend_gate_entry_digest(root, selected)
    return _canonical_digest(facts)


def probe_sandbox_capability(
    layout: SandboxLayout,
    *,
    resource_sampler: Callable[[int], GateResourceSample] | None = None,
) -> str:
    """Run a real namespace probe and return a stable capability digest."""

    if layout.python_root is None or layout.site_packages is None:
        probe = GateSpec(
            gate_id="sandbox_capability_probe",
            argv=("/usr/bin/git", "--version"),
            cwd="/workspace",
            timeout_s=10.0,
        )
    else:
        probe = GateSpec(
            gate_id="sandbox_capability_probe",
            argv=(
                "/opt/python/bin/python3",
                "-c",
                (
                    "import os,pathlib,socket;"
                    "p=pathlib.Path('/workspace/.xmuse-sandbox-probe');"
                    "p.write_text('ok');p.unlink();"
                    "assert not pathlib.Path(os.environ.get('XMUSE_ROOT','/missing')).exists();"
                    "s=socket.socket();s.settimeout(.1);"
                    "r=s.connect_ex(('1.1.1.1',53));assert r!=0"
                ),
            ),
            cwd="/workspace",
            timeout_s=10.0,
        )
    result = run_gate(layout, probe=probe, resource_sampler=resource_sampler)
    if result.status != "passed":
        raise RoomExecutionSandboxError("execution_sandbox_probe_failed")
    return result.evidence_digest


def run_gate(
    layout: SandboxLayout,
    gate_id: str | None = None,
    *,
    probe: GateSpec | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    resource_sampler: Callable[[int], GateResourceSample] | None = None,
) -> GateResult:
    """Execute one fixed gate and return only bounded, non-content evidence."""

    if (gate_id is None) == (probe is None):
        raise ValueError("exactly one gate_id or internal probe must be supplied")
    try:
        spec = probe if probe is not None else GATE_SPECS[str(gate_id)]
    except KeyError as exc:
        raise RoomExecutionSandboxError("execution_gate_unknown") from exc
    assert spec is not None
    _validate_spec(spec)
    if spec.gate_id.startswith("frontend_") and layout.frontend_node_modules is None:
        raise RoomExecutionSandboxError("execution_frontend_dependencies_unavailable")

    command = build_bwrap_command(layout, spec)
    limits = (
        _resource_limits_for_spec(spec)
        if probe is not None
        else resource_limits_for_gate(spec.gate_id)
    )
    sample_resources = resource_sampler or GateResourceMonitor(layout.stage)
    started = time.monotonic()
    try:
        process = popen(
            command,
            cwd="/",
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_set_child_limits,
        )
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_sandbox_start_failed") from exc
    if process.stdout is None:
        _terminate_fenced_process(process)
        raise RoomExecutionSandboxError("execution_sandbox_output_unavailable")
    collector = _OutputCollector(output_limit_bytes)
    cancelled = False
    timed_out = False
    limit_reason: str | None = None
    try:
        os.set_blocking(process.stdout.fileno(), False)
        deadline = started + spec.timeout_s
        try:
            while process.poll() is None:
                collector.drain(process.stdout)
                if cancel_requested is not None and cancel_requested():
                    cancelled = True
                    _terminate_fenced_process(process)
                    break
                try:
                    sample = sample_resources(process.pid)
                except Exception:
                    if process.poll() is not None:
                        break
                    # A successful child can disappear from /proc just before
                    # Popen observes its exit. Give that narrow race one bounded
                    # reaping window; a still-live child continues to fail closed.
                    try:
                        process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        limit_reason = "execution_gate_resource_probe_failed"
                    else:
                        break
                else:
                    limit_reason = _resource_limit_reason(sample, limits)
                if limit_reason is not None:
                    _terminate_fenced_process(process)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    _terminate_fenced_process(process)
                    break
                time.sleep(DEFAULT_CANCEL_POLL_S)
        finally:
            if process.poll() is None:
                _terminate_fenced_process(process)
        exit_code = process.wait()
        _drain_after_exit(process, process.stdout, collector)
    finally:
        process.stdout.close()
    output_digest = collector.digest()

    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    if cancelled:
        status, code = "cancelled", "execution_cancelled"
    elif limit_reason is not None:
        status, code = "failed", limit_reason
    elif timed_out:
        status, code = "failed", "execution_gate_timeout"
    elif exit_code == 0:
        status, code = "passed", None
    else:
        status, code = "failed", "execution_gate_failed"
    evidence = _evidence_digest(
        gate_id=spec.gate_id,
        status=status,
        reason_code=code,
        exit_code=exit_code,
        output_digest=output_digest,
    )
    return GateResult(
        gate_id=spec.gate_id,
        status=status,
        reason_code=code,
        evidence_digest=evidence,
        output_digest=output_digest,
        exit_code=exit_code,
        duration_ms=duration_ms,
        output_bytes=collector.total_bytes,
    )


def build_bwrap_command(layout: SandboxLayout, spec: GateSpec) -> list[str]:
    """Build the auditable Bubblewrap argv; no caller-provided argv is accepted."""

    command = [
        str(layout.bwrap),
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/etc",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tmp/home",
        "--dir",
        "/workspace",
        "--dir",
        "/repo-git",
        "--dir",
        "/opt",
        "--dir",
        "/opt/python",
        "--dir",
        "/deps",
        "--dir",
        "/deps/site-packages",
        "--dir",
        "/tools",
    ]
    for system_path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(system_path).exists():
            command.extend(("--ro-bind", system_path, system_path))
    if Path("/etc/hosts").is_file():
        command.extend(("--ro-bind", "/etc/hosts", "/etc/hosts"))
    command.extend(
        (
            "--bind",
            str(layout.stage),
            "/workspace",
            "--ro-bind",
            str(layout.git_common_dir),
            "/repo-git",
        )
    )
    if layout.python_root is not None:
        if layout.site_packages is None or layout.ruff is None:
            raise RoomExecutionSandboxError("execution_backend_dependencies_unavailable")
        command.extend(
            (
                "--ro-bind",
                str(layout.python_root),
                "/opt/python",
                "--ro-bind",
                str(layout.site_packages),
                "/deps/site-packages",
                "--ro-bind",
                str(layout.ruff),
                "/tools/ruff",
            )
        )
    if layout.frontend_node_modules is not None:
        command.extend(
            (
                "--dir",
                "/workspace/frontend/node_modules",
                "--ro-bind",
                str(layout.frontend_node_modules),
                "/workspace/frontend/node_modules",
            )
        )
    git_dir_in_sandbox = _sandbox_git_dir(layout)
    safe_environment = {
        "CI": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": "/tmp/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_CACHE": "/tmp/npm-cache",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_OFFLINE": "true",
        "NEXT_TELEMETRY_DISABLED": "1",
        "NO_COLOR": "1",
        "PATH": "/tools:/opt/python/bin:/usr/bin:/bin",
        "PYTHONPATH": "/deps/site-packages:/workspace/src:/workspace",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",
        "TZ": "UTC",
        SANDBOX_ACTIVE_ENV: "1",
    }
    if spec.gate_id == "patch_diff_check":
        safe_environment.update(
            {
                "GIT_DIR": git_dir_in_sandbox,
                "GIT_COMMON_DIR": "/repo-git",
                "GIT_WORK_TREE": "/workspace",
            }
        )
    for key, value in safe_environment.items():
        command.extend(("--setenv", key, value))
    command.extend(("--chdir", spec.cwd, "--", *spec.argv))
    return command


def _git_path(worktree: Path, flag: str) -> Path:
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", flag],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RoomExecutionSandboxError("execution_target_not_git")
    return Path(result.stdout.strip()).resolve(strict=True)


def _sandbox_git_dir(layout: SandboxLayout) -> str:
    try:
        relative = layout.git_dir.relative_to(layout.git_common_dir)
    except ValueError as exc:
        raise RoomExecutionSandboxError("execution_git_metadata_invalid") from exc
    value = PurePosixPath("/repo-git", *relative.parts)
    return str(value)


def _validate_spec(spec: GateSpec) -> None:
    if not spec.gate_id or spec.timeout_s <= 0:
        raise RoomExecutionSandboxError("execution_gate_invalid")
    if not spec.cwd.startswith("/workspace") or ".." in PurePosixPath(spec.cwd).parts:
        raise RoomExecutionSandboxError("execution_gate_invalid")
    if not spec.argv or not spec.argv[0].startswith("/"):
        raise RoomExecutionSandboxError("execution_gate_invalid")


def resource_limits_for_gate(gate_id: str) -> GateResourceLimits:
    if gate_id not in GATE_SPECS and gate_id != "sandbox_capability_probe":
        raise RoomExecutionSandboxError("execution_gate_unknown")
    return _resource_limits_for_spec(
        GATE_SPECS.get(gate_id) or GateSpec(gate_id, ("/invalid",), "/workspace", 1.0)
    )


def _resource_limits_for_spec(spec: GateSpec) -> GateResourceLimits:
    if spec.gate_id.startswith("frontend_"):
        return GateResourceLimits(4 * _GIB, 128, 2 * _GIB)
    return GateResourceLimits(2 * _GIB, 64, _GIB)


def _gate_semantics(gate_id: str) -> dict[str, object]:
    try:
        spec = GATE_SPECS[gate_id]
    except KeyError as exc:
        raise RoomExecutionSandboxError("execution_gate_unknown") from exc
    limits = _resource_limits_for_spec(spec)
    return {
        "gate_id": spec.gate_id,
        "argv": list(spec.argv),
        "cwd": spec.cwd,
        "timeout_ms": int(spec.timeout_s * 1000),
        "max_rss_bytes": limits.max_rss_bytes,
        "max_processes": limits.max_processes,
        "max_scratch_bytes": limits.max_scratch_bytes,
    }


def _set_child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))


def _terminate_fenced_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    process.poll()
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)
    if not _process_group_exists(process.pid):
        process.wait(timeout=0.1)
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    process.poll()
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        raise RoomExecutionSandboxError("execution_gate_cleanup_pending")
    process.wait(timeout=0.1)


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _OutputCollector:
    def __init__(self, tail_limit: int) -> None:
        if tail_limit < 0:
            raise ValueError("output limit must be non-negative")
        self._digest = hashlib.sha256()
        self._tail = bytearray()
        self._tail_limit = tail_limit
        self.total_bytes = 0

    def drain(self, pipe: IO[bytes]) -> bool:
        """Drain every currently available byte; return True only at EOF."""

        drained = 0
        deadline = time.monotonic() + _OUTPUT_DRAIN_BUDGET_S
        while drained < _OUTPUT_DRAIN_BUDGET_BYTES and time.monotonic() < deadline:
            try:
                chunk = os.read(pipe.fileno(), 64 * 1024)
            except BlockingIOError:
                return False
            if not chunk:
                return True
            self._digest.update(chunk)
            self.total_bytes += len(chunk)
            drained += len(chunk)
            if self._tail_limit:
                self._tail.extend(chunk)
                del self._tail[: max(0, len(self._tail) - self._tail_limit)]
        return False

    def digest(self) -> str:
        return f"sha256:{self._digest.hexdigest()}"


def _drain_after_exit(
    process: subprocess.Popen[bytes],
    pipe: IO[bytes],
    collector: _OutputCollector,
) -> None:
    deadline = time.monotonic() + 1.0
    while not collector.drain(pipe) and time.monotonic() < deadline:
        time.sleep(0.01)
    if time.monotonic() >= deadline:
        _terminate_fenced_process(process)
        collector.drain(pipe)


class GateResourceMonitor:
    """Measure a host-visible process tree and writable growth without cgroups."""

    def __init__(self, stage: Path) -> None:
        self._stage = stage
        self._stage_baseline = _initial_directory_size(stage)
        self._stage_growth = 0
        self._private_tmp_size = 0
        self._last_scratch_scan = 0.0
        self._consecutive_scan_deadlines = 0

    def __call__(self, root_pid: int) -> GateResourceSample:
        pids = _process_tree(root_pid)
        rss = sum(_process_rss(pid) for pid in pids)
        now = time.monotonic()
        if now - self._last_scratch_scan >= 1.0:
            self._last_scratch_scan = now
            try:
                stage_size = _directory_size(self._stage)
                private_tmp_size = _sandbox_scratch_bytes(pids)
            except _DirectoryScanDeadline as exc:
                self._consecutive_scan_deadlines += 1
                if self._consecutive_scan_deadlines >= 3:
                    raise RoomExecutionSandboxError("execution_gate_resource_probe_failed") from exc
            else:
                self._stage_growth = max(0, stage_size - self._stage_baseline)
                self._private_tmp_size = private_tmp_size
                self._consecutive_scan_deadlines = 0
        scratch = self._stage_growth + self._private_tmp_size
        return GateResourceSample(rss, len(pids), scratch)


def _initial_directory_size(root: Path) -> int:
    for _attempt in range(3):
        try:
            return _directory_size(root)
        except _DirectoryScanDeadline:
            continue
    raise RoomExecutionSandboxError("execution_gate_resource_probe_failed")


def _process_tree(root_pid: int) -> set[int]:
    found: set[int] = set()
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.add(pid)
        children_path = Path(f"/proc/{pid}/task/{pid}/children")
        try:
            raw = children_path.read_text(encoding="ascii")
        except OSError:
            if pid != root_pid and not Path(f"/proc/{pid}").exists():
                continue
            raise
        pending.extend(int(value) for value in raw.split() if value.isdecimal())
    return found


def _process_rss(pid: int) -> int:
    statm = Path(f"/proc/{pid}/statm")
    try:
        pages = int(statm.read_text(encoding="ascii").split()[1])
    except OSError:
        if not Path(f"/proc/{pid}").exists():
            return 0
        raise
    except (IndexError, ValueError) as exc:
        raise OSError("invalid proc statm") from exc
    return pages * os.sysconf("SC_PAGE_SIZE")


def _sandbox_scratch_bytes(pids: Iterable[int]) -> int:
    own_namespace = os.readlink("/proc/self/ns/mnt")
    for pid in pids:
        try:
            if os.readlink(f"/proc/{pid}/ns/mnt") == own_namespace:
                continue
        except OSError:
            if not Path(f"/proc/{pid}").exists():
                continue
            raise
        if _process_has_private_tmpfs(pid):
            try:
                return _directory_size(Path(f"/proc/{pid}/root/tmp"))
            except (_DirectoryScanDeadline, RoomExecutionSandboxError):
                if not Path(f"/proc/{pid}").exists():
                    return 0
                raise
    return 0


def _process_has_private_tmpfs(pid: int) -> bool:
    try:
        lines = Path(f"/proc/{pid}/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        if not Path(f"/proc/{pid}").exists():
            return False
        raise
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError as exc:
            raise OSError("invalid proc mountinfo") from exc
        if len(fields) > separator + 1 and fields[4] == "/tmp":
            return fields[separator + 1] == "tmpfs"
    return False


def _directory_size(root: Path) -> int:
    total = 0
    pending = [root]
    seen: set[tuple[int, int]] = set()
    scanned = 0
    deadline = time.monotonic() + _DIRECTORY_SCAN_MAX_S
    while pending:
        if scanned > _DIRECTORY_SCAN_MAX_ENTRIES:
            raise RoomExecutionSandboxError("execution_gate_resource_probe_failed")
        if time.monotonic() >= deadline:
            raise _DirectoryScanDeadline
        current = pending.pop()
        try:
            iterator = os.scandir(current)
        except FileNotFoundError as exc:
            if current != root:
                continue
            raise RoomExecutionSandboxError("execution_gate_resource_probe_failed") from exc
        except OSError as exc:
            raise RoomExecutionSandboxError("execution_gate_resource_probe_failed") from exc
        with iterator:
            for entry in iterator:
                scanned += 1
                if scanned > _DIRECTORY_SCAN_MAX_ENTRIES:
                    raise RoomExecutionSandboxError("execution_gate_resource_probe_failed")
                if time.monotonic() >= deadline:
                    raise _DirectoryScanDeadline
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise RoomExecutionSandboxError("execution_gate_resource_probe_failed") from exc
                key = (info.st_dev, info.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += info.st_size
                if time.monotonic() >= deadline:
                    raise _DirectoryScanDeadline
    return total


def _resource_limit_reason(sample: GateResourceSample, limits: GateResourceLimits) -> str | None:
    if sample.process_count > limits.max_processes:
        return "execution_gate_process_limit"
    if sample.rss_bytes > limits.max_rss_bytes:
        return "execution_gate_memory_limit"
    if sample.scratch_bytes > limits.max_scratch_bytes:
        return "execution_gate_scratch_limit"
    return None


def _gate_uses_python(gate_id: str) -> bool:
    return gate_id.startswith(("backend_", "python_uv_"))


def _trusted_profile(profile: ExecutionGateProfile) -> ExecutionGateProfile:
    try:
        trusted = get_execution_gate_profile(profile.profile_id)
    except (AttributeError, ValueError) as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_unknown") from exc
    if trusted != profile:
        raise RoomExecutionSandboxError("execution_gate_profile_invalid")
    return trusted


def _trusted_file_digest(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise RoomExecutionSandboxError("execution_gate_profile_marker_missing")
        size = path.stat().st_size
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_missing") from exc
    if size > _MAX_EVIDENCE_FILE_BYTES:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(128 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid") from exc
    return f"sha256:{digest.hexdigest()}"


def _bounded_marker_bytes(path: Path) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_missing") from exc
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > _MAX_PROFILE_MARKER_BYTES
        ):
            raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
        payload = bytearray()
        while len(payload) <= _MAX_PROFILE_MARKER_BYTES:
            remaining = _MAX_PROFILE_MARKER_BYTES + 1 - len(payload)
            chunk = os.read(descriptor, min(128 * 1024, remaining))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid") from exc
    finally:
        os.close(descriptor)
    if (
        len(payload) > _MAX_PROFILE_MARKER_BYTES
        or len(payload) != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return bytes(payload)


def _toml_marker(path: Path) -> Mapping[str, object]:
    try:
        payload = tomllib.loads(_bounded_marker_bytes(path).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid") from exc
    if not isinstance(payload, Mapping):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return payload


def _json_marker(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(_bounded_marker_bytes(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid") from exc
    if not isinstance(payload, Mapping):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return payload


def _marker_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 214
        or any(ord(character) < 32 for character in value)
    ):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return value


def _python_marker_contract(root: Path) -> dict[str, object]:
    pyproject = _toml_marker(root / "pyproject.toml")
    project = pyproject.get("project")
    if not isinstance(project, Mapping):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    project_name = _marker_name(project.get("name"))
    lock = _toml_marker(root / "uv.lock")
    lock_version = lock.get("version")
    packages = lock.get("package")
    if isinstance(lock_version, bool) or lock_version != 1 or not isinstance(packages, list):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    editable = [
        package
        for package in packages
        if isinstance(package, Mapping)
        and package.get("name") == project_name
        and isinstance(package.get("source"), Mapping)
        and package["source"].get("editable") == "."
    ]
    if len(editable) != 1:
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return {
        "project_name": project_name,
        "uv_lock_version": lock_version,
        "editable_root_package": project_name,
    }


def _frontend_marker_contract(root: Path) -> dict[str, object]:
    expected_name = "xmuse-chat-frontend"
    package = _json_marker(root / "frontend" / "package.json")
    lock = _json_marker(root / "frontend" / "package-lock.json")
    packages = lock.get("packages")
    lock_root = packages.get("") if isinstance(packages, Mapping) else None
    lock_version = lock.get("lockfileVersion")
    if (
        _marker_name(package.get("name")) != expected_name
        or _marker_name(lock.get("name")) != expected_name
        or not isinstance(lock_root, Mapping)
        or _marker_name(lock_root.get("name")) != expected_name
        or isinstance(lock_version, bool)
        or lock_version != 3
    ):
        raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
    return {
        "package_name": expected_name,
        "package_lock_root_name": expected_name,
        "package_lock_version": lock_version,
    }


def _validated_repository_marker_contract(
    root: Path,
    profile: ExecutionGateProfile,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "room_execution_repository_markers/v1",
        "policy_revision": profile.marker_policy_revision,
    }
    if profile.profile_id == "docs/v1":
        return result
    python = _python_marker_contract(root)
    if profile.profile_id == "python-uv/v1":
        result["python"] = python
        return result
    if profile.profile_id == "xmuse-monorepo/v2":
        if python["project_name"] != "xmuse":
            raise RoomExecutionSandboxError("execution_gate_profile_marker_invalid")
        result["python"] = python
        result["frontend"] = _frontend_marker_contract(root)
        return result
    raise RoomExecutionSandboxError("execution_gate_profile_unknown")


def _dependency_metadata_digest(site_packages: Path, names: tuple[str, ...]) -> str:
    values: list[dict[str, str]] = []
    for name in names:
        metadata = sorted(site_packages.glob(f"{name}-*.dist-info/METADATA"))
        if len(metadata) != 1:
            raise RoomExecutionSandboxError("execution_backend_dependencies_unavailable")
        values.append({"name": name, "digest": _trusted_file_digest(metadata[0])})
    return _canonical_digest(values)


def _frontend_gate_entry_digest(root: Path, gate_ids: tuple[str, ...]) -> str:
    relative_by_gate = {
        "frontend_typecheck": "typescript/bin/tsc",
        "frontend_lint": "eslint/bin/eslint.js",
        "frontend_vitest": "vitest/vitest.mjs",
        "frontend_build": "next/dist/bin/next",
    }
    values: list[dict[str, str]] = []
    for gate_id in gate_ids:
        relative = relative_by_gate.get(gate_id)
        if relative is None:
            continue
        entry = root / "frontend" / "node_modules" / relative
        try:
            digest = _trusted_file_digest(entry)
        except RoomExecutionSandboxError as exc:
            raise RoomExecutionSandboxError("execution_frontend_dependencies_unavailable") from exc
        values.append({"gate_id": gate_id, "digest": digest})
    return _canonical_digest(values)


def _tool_version(path: Path, *args: str) -> str:
    try:
        executable = path.resolve(strict=True)
        result = subprocess.run(
            [str(executable), *args],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RoomExecutionSandboxError("execution_toolchain_unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > 16 * 1024:
        raise RoomExecutionSandboxError("execution_toolchain_unavailable")
    return f"sha256:{hashlib.sha256(result.stdout).hexdigest()}"


def _target_python_layout(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Resolve target dependency files without executing workspace-derived bytes."""

    try:
        venv = (root / ".venv").resolve(strict=True)
        python_entry = venv / "bin" / "python3"
        ruff_entry = venv / "bin" / "ruff"
        venv_config = venv / "pyvenv.cfg"
        python = python_entry.resolve(strict=True)
        ruff = ruff_entry.resolve(strict=True)
        candidates = tuple(
            path
            for path in (venv / "lib").glob("python*/site-packages")
            if path.is_dir() and re.fullmatch(r"python[0-9]+\.[0-9]+", path.parent.name) is not None
        )
    except OSError as exc:
        raise RoomExecutionSandboxError("execution_backend_dependencies_unavailable") from exc
    if (
        len(candidates) != 1
        or not python.is_file()
        or not ruff.is_file()
        or not venv_config.is_file()
    ):
        raise RoomExecutionSandboxError("execution_backend_dependencies_unavailable")
    return python_entry, python, ruff_entry, candidates[0], venv_config


def _git_head(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            timeout=5.0,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RoomExecutionSandboxError("execution_target_not_git") from exc
    value = result.stdout.strip()
    if (
        result.returncode != 0
        or len(value) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RoomExecutionSandboxError("execution_target_not_git")
    return value


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _evidence_digest(
    *,
    gate_id: str,
    status: str,
    reason_code: str | None,
    exit_code: int | None,
    output_digest: str,
) -> str:
    canonical = "\0".join((gate_id, status, reason_code or "", str(exit_code), output_digest))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
