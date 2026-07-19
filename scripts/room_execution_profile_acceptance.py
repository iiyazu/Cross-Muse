#!/usr/bin/env python3
"""Real, non-recursive acceptance for fixed Room execution gate profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_api_models import ParticipantInit, RoomConversationCreate
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_controller import (
    ControllerConfig,
    build_workspace_guard,
    run_execution_controller,
)
from xmuse_core.chat.room_execution_controller_store import RoomExecutionControllerStore
from xmuse_core.chat.room_execution_operator_store import RoomExecutionOperatorStore
from xmuse_core.chat.room_execution_profiles import (
    build_execution_gate_plan,
    gate_ids_for_profile_paths,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_execution_sandbox import (
    RoomExecutionSandboxError,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    discover_python_extension_artifacts,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_runtime import read_process_start_identity
from xmuse_core.chat.room_setup import RoomSetupService

RESULT_SCHEMA = "room_execution_profile_acceptance/v1"
MEMORYOS_FIXTURE_SHA256 = "sha256:38c76b8323a30479925bbb58f82fa5d34b218d4dd1d98fb9ce47648a678bc393"
XMUSE_SCENARIOS = {
    "xmuse-backend": (
        "xmuse-monorepo/v2",
        ("src/xmuse_core/chat/room_execution_profiles.py",),
    ),
    "xmuse-frontend": ("xmuse-monorepo/v2", ("frontend/src/app/globals.css",)),
    "xmuse-mixed": (
        "xmuse-monorepo/v2",
        (
            "src/xmuse_core/chat/room_execution_profiles.py",
            "frontend/src/app/globals.css",
        ),
    ),
}
MEMORYOS_SCENARIO = (
    "python-uv/v1",
    (
        "src/memoryos_lite/agent_kernel.py",
        "src/memoryos_lite/api/app.py",
        "src/memoryos_lite/core_memory.py",
        "src/memoryos_lite/llm_judge.py",
        "src/memoryos_lite/retrieval/providers/qdrant.py",
        "src/memoryos_lite/retrieval/query_rewriter.py",
        "src/memoryos_lite/retrieval/reranker.py",
        "src/memoryos_lite/v3_contracts.py",
        "tests/fixtures/public_failure_replay/phase8_failed_rows.json",
        "tests/test_public_failure_replay.py",
    ),
)


class AcceptanceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SourceGuard:
    head: str
    status_digest: str
    worktree_digest: str
    content_digest: str


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            input=input_bytes,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except OSError as exc:
        raise AcceptanceError("acceptance_git_unavailable") from exc
    if result.returncode != 0:
        raise AcceptanceError("acceptance_git_failed")
    return result.stdout


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(128 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _snapshot_paths(root: Path) -> tuple[str, ...]:
    raw = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    values = tuple(item.decode("utf-8") for item in raw.split(b"\0") if item)
    for value in values:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
            raise AcceptanceError("acceptance_source_path_invalid")
    return tuple(sorted(values))


def _content_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for value in _snapshot_paths(root):
        path = root / value
        info = path.lstat()
        digest.update(value.encode("utf-8") + b"\0")
        digest.update(f"{stat.S_IMODE(info.st_mode):o}".encode("ascii") + b"\0")
        if stat.S_ISLNK(info.st_mode):
            digest.update(os.readlink(path).encode("utf-8"))
        elif stat.S_ISREG(info.st_mode):
            with path.open("rb") as handle:
                while chunk := handle.read(128 * 1024):
                    digest.update(chunk)
        else:
            raise AcceptanceError("acceptance_source_file_invalid")
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _working_tree_changed_paths(root: Path) -> tuple[str, ...]:
    """Return unstaged exact-patch paths, including promoted new files."""

    raw = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    paths: list[str] = []
    for item in (value for value in raw.split(b"\0") if value):
        if len(item) < 4 or item[:3] not in {b" M ", b" D ", b"?? "}:
            raise AcceptanceError("acceptance_target_status_unexpected")
        try:
            value = item[3:].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AcceptanceError("acceptance_target_status_unexpected") from exc
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
            raise AcceptanceError("acceptance_target_status_unexpected")
        paths.append(value)
    return tuple(sorted(paths))


def _source_guard(root: Path) -> SourceGuard:
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    return SourceGuard(
        head=head,
        status_digest=_digest(
            _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
        ),
        worktree_digest=_digest(_git(root, "worktree", "list", "--porcelain", "-z")),
        content_digest=_content_digest(root),
    )


def _require_source_guard(root: Path, expected: SourceGuard) -> None:
    if _source_guard(root) != expected:
        raise AcceptanceError("acceptance_source_guard_changed")


def _git_environment() -> dict[str, str]:
    """Return the fixed environment used for non-interactive local Git operations."""

    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _require_full_object_id(value: str, *, kind: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise AcceptanceError(f"acceptance_frozen_{kind}_invalid")


def _clone_frozen_commit(
    source: Path,
    destination: Path,
    *,
    frozen_commit: str,
    frozen_tree: str,
) -> None:
    """Clone and detach at an exact commit whose tree was frozen by the caller.

    The source working tree is deliberately not inspected: both proofs come from Git's
    object database, and clone uses ``--no-checkout`` before the exact detached checkout.
    """

    _require_full_object_id(frozen_commit, kind="commit")
    _require_full_object_id(frozen_tree, kind="tree")
    source_commit = _git(source, "rev-parse", f"{frozen_commit}^{{commit}}")
    if source_commit.decode("ascii").strip() != frozen_commit:
        raise AcceptanceError("acceptance_frozen_commit_mismatch")
    source_tree = _git(source, "rev-parse", f"{frozen_commit}^{{tree}}")
    if source_tree.decode("ascii").strip() != frozen_tree:
        raise AcceptanceError("acceptance_frozen_tree_mismatch")
    try:
        result = subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--no-checkout",
                "--no-hardlinks",
                str(source),
                str(destination),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except OSError as exc:
        raise AcceptanceError("acceptance_clone_failed") from exc
    if result.returncode != 0:
        raise AcceptanceError("acceptance_clone_failed")
    _git(destination, "checkout", "-q", "--detach", frozen_commit)
    if _git(destination, "rev-parse", "HEAD").decode("ascii").strip() != frozen_commit:
        raise AcceptanceError("acceptance_clone_commit_mismatch")
    if _git(destination, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != frozen_tree:
        raise AcceptanceError("acceptance_clone_tree_mismatch")
    if _git(destination, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise AcceptanceError("acceptance_clone_dirty")


def _copy_working_snapshot(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for value in _snapshot_paths(source):
        origin = source / value
        target = destination / value
        target.parent.mkdir(parents=True, exist_ok=True)
        info = origin.lstat()
        if stat.S_ISLNK(info.st_mode):
            os.symlink(os.readlink(origin), target)
        elif stat.S_ISREG(info.st_mode):
            shutil.copy2(origin, target, follow_symlinks=False)
        else:
            raise AcceptanceError("acceptance_source_file_invalid")
    _git(destination, "init", "-q")
    _git(destination, "config", "user.email", "acceptance@example.invalid")
    _git(destination, "config", "user.name", "xmuse acceptance")
    _git(destination, "add", "-A")
    _git(destination, "commit", "-qm", "working-tree snapshot")
    if _git(destination, "status", "--porcelain=v1"):
        raise AcceptanceError("acceptance_snapshot_dirty")


def _clone_no_hardlinks(source: Path, destination: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(source), str(destination)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except OSError as exc:
        raise AcceptanceError("acceptance_clone_failed") from exc
    if result.returncode != 0:
        raise AcceptanceError("acceptance_clone_failed")


def _link_dependencies(
    target: Path,
    source: Path,
    *,
    frontend: bool,
    python: bool = True,
    node: bool = False,
) -> None:
    exclude = target / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write("\n.venv\nnode_modules\nfrontend/node_modules\n")
    if python:
        python_root = source / ".venv"
        if not python_root.is_dir():
            raise AcceptanceError("acceptance_python_dependencies_missing")
        os.symlink(python_root.resolve(strict=True), target / ".venv", target_is_directory=True)
        try:
            artifacts = discover_python_extension_artifacts(source)
        except RoomExecutionSandboxError as exc:
            raise AcceptanceError("acceptance_python_dependencies_invalid") from exc
        for artifact, relative_value, digest in artifacts:
            relative = Path(relative_value)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact, destination, follow_symlinks=False)
            if _file_digest(destination) != digest:
                raise AcceptanceError("acceptance_python_dependencies_invalid")
    if node:
        node_modules = source / "node_modules"
        if not node_modules.is_dir():
            raise AcceptanceError("acceptance_frontend_dependencies_missing")
        os.symlink(
            node_modules.resolve(strict=True),
            target / "node_modules",
            target_is_directory=True,
        )
    if frontend:
        node_modules = source / "frontend" / "node_modules"
        if not node_modules.is_dir():
            raise AcceptanceError("acceptance_frontend_dependencies_missing")
        destination = target / "frontend" / "node_modules"
        os.symlink(node_modules.resolve(strict=True), destination, target_is_directory=True)
    if _git(target, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise AcceptanceError("acceptance_dependency_link_not_ignored")


def _candidate_patch(root: Path, paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    originals: dict[str, str] = {}
    for index, value in enumerate(paths):
        target = root / value
        original = target.read_text(encoding="utf-8")
        originals[value] = original
        suffix = (
            f"\n/* xmuse execution acceptance {index} */\n"
            if target.suffix == ".css"
            else f"\n# xmuse execution acceptance {index}\n"
        )
        target.write_text(original.rstrip("\n") + suffix, encoding="utf-8")
    patch = _git(root, "diff", "--binary", "--", *paths).decode("utf-8")
    for value, original in originals.items():
        (root / value).write_text(original, encoding="utf-8")
    if not patch or _git(root, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise AcceptanceError("acceptance_patch_generation_failed")
    return patch, originals


def _fixture_candidate_patch(
    root: Path, paths: tuple[str, ...], fixture: str
) -> tuple[str, dict[str, str | None]]:
    originals = {
        value: ((root / value).read_text(encoding="utf-8") if (root / value).is_file() else None)
        for value in paths
    }
    _git(root, "apply", "--check", input_bytes=fixture.encode("utf-8"))
    if _git(root, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise AcceptanceError("acceptance_fixture_mutated_preimage")
    return fixture, originals


def _expected_patch_digests(root: Path, paths: tuple[str, ...], patch: str) -> dict[str, str]:
    """Prove the exact post-patch bytes without leaving the validation clone dirty."""

    _git(root, "apply", "--check", input_bytes=patch.encode("utf-8"))
    _git(root, "apply", input_bytes=patch.encode("utf-8"))
    try:
        if _working_tree_changed_paths(root) != tuple(sorted(paths)):
            raise AcceptanceError("acceptance_patch_paths_mismatch")
        expected = {value: _file_digest(root / value) for value in paths}
    finally:
        _git(root, "apply", "--reverse", input_bytes=patch.encode("utf-8"))
    if _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise AcceptanceError("acceptance_patch_preimage_restore_failed")
    return expected


def _sentinel_path(root: Path, changed_paths: tuple[str, ...]) -> Path:
    changed = frozenset(changed_paths)
    for value in _snapshot_paths(root):
        path = root / value
        if value not in changed and path.is_file() and not path.is_symlink():
            return path
    raise AcceptanceError("acceptance_sentinel_missing")


def _authorize_run(
    *,
    runtime: Path,
    repository: Path,
    profile_id: str,
    paths: tuple[str, ...],
    patch: str,
) -> tuple[RoomExecutionControllerStore, ControllerConfig, tuple[str, ...]]:
    runtime.mkdir(parents=True, exist_ok=False)
    RoomDatabase(runtime / "chat.db").initialize()
    setup = RoomSetupService(runtime).create_conversation(
        RoomConversationCreate(
            title="Execution profile acceptance",
            client_request_id="acceptance-room",
            initial_participants=[ParticipantInit(role="architect", display_name="Architect")],
        )
    )
    conversation_id = str(setup["id"])
    db = runtime / "chat.db"
    participant = ParticipantStore(db).list_by_conversation(conversation_id)[0]
    registry_path = runtime / "god_sessions.json"
    session = GodSessionRegistry(registry_path).create(
        participant.role,
        participant.display_name,
        "codex",
        "acceptance-provider",
        "acceptance-inbox",
        conversation_id,
        participant.participant_id,
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="acceptance-human",
        content="Propose the fixed acceptance patch.",
        client_request_id="acceptance-human-root",
    )
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="acceptance-lease",
    )
    if claim is None:
        raise AcceptanceError("acceptance_observation_missing")
    proposal = RoomApplicationService(db, registry_path).submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        god_session_id=session.god_session_id,
        observation_id=str(claim["observation"]["observation_id"]),
        lease_token=str(claim["observation"]["lease_token"]),
        client_request_id="acceptance-proposal",
        outcome_type="propose",
        outcome_payload={
            "proposal_type": "execution_patch",
            "content": "Acceptance-only exact patch",
            "references": [],
            "execution_patch": {
                "schema_version": "room_execution_patch/v1",
                "base_head": _git(repository, "rev-parse", "HEAD").decode().strip(),
                "summary": "Exercise fixed execution gates",
                "unified_diff": patch,
                "allowed_files": list(paths),
            },
        },
    )
    execution_candidate = proposal.get("execution_candidate")
    if not isinstance(execution_candidate, dict):
        raise AcceptanceError("acceptance_candidate_missing")
    reader = RoomExecutionLedgerReader(db)
    operator_store = RoomExecutionOperatorStore(db)
    candidate_id = str(execution_candidate["candidate_id"])
    candidate = reader.get_candidate(candidate_id, include_patch=True)
    if candidate is None:
        raise AcceptanceError("acceptance_candidate_missing")
    allowed = tuple(str(value) for value in candidate["allowed_files"])
    guard = build_workspace_guard(
        repository,
        SimpleNamespace(base_head=candidate["base_head"], allowed_files=allowed),
    )
    profile = get_execution_gate_profile(profile_id)
    gate_ids = gate_ids_for_profile_paths(profile_id, allowed)
    plan = build_execution_gate_plan(
        profile_id=profile_id,
        changed_paths=allowed,
        repository_manifest_digest=build_repository_manifest_digest(repository, profile),
        toolchain_capability_digest=build_toolchain_capability_digest(
            repository, profile, gate_ids=profile.gate_ids
        ),
    )
    policy = reader.get_policy(conversation_id)
    if policy is None:
        raise AcceptanceError("acceptance_policy_missing")
    decision = operator_store.apply_operator_decision(
        candidate_id=candidate_id,
        decision="execute",
        client_action_id="acceptance-execute",
        operator_identity="acceptance-operator",
        expected_candidate_digest=str(candidate["candidate_digest"]),
        expected_candidate_revision=int(candidate["revision"]),
        expected_policy_revision=int(policy["revision"]),
        workspace_guard=guard,
        gate_plan=plan,
    )
    run = decision.get("run")
    if not isinstance(run, dict):
        raise AcceptanceError("acceptance_run_missing")
    pid = os.getpid()
    identity = read_process_start_identity(pid)
    if identity is None:
        raise AcceptanceError("acceptance_controller_identity_missing")
    return (
        RoomExecutionControllerStore(db),
        ControllerConfig(
            xmuse_root=runtime,
            execution_root=repository,
            run_id=str(run["run_id"]),
            controller_id="acceptance-controller",
            controller_generation="acceptance-generation",
            controller_pid=pid,
            controller_start_identity=identity,
        ),
        gate_ids,
    )


def _run_scenario(
    *,
    name: str,
    repository: Path,
    dependency_source: Path,
    runtime: Path,
    profile_id: str,
    paths: tuple[str, ...],
    fixture_patch: str | None = None,
    link_dependencies: bool = True,
) -> dict[str, Any]:
    if link_dependencies:
        node_profile = profile_id.startswith("node-pnpm-")
        _link_dependencies(
            repository,
            dependency_source,
            python=not node_profile,
            node=node_profile,
            frontend=(
                profile_id == "xmuse-monorepo/v2"
                or any(value.startswith("frontend/") for value in paths)
            ),
        )
    head = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    worktrees = _digest(_git(repository, "worktree", "list", "--porcelain", "-z"))
    sentinel = _sentinel_path(repository, paths)
    sentinel_digest = _file_digest(sentinel)
    patch, originals = (
        _fixture_candidate_patch(repository, paths, fixture_patch)
        if fixture_patch is not None
        else _candidate_patch(repository, paths)
    )
    expected_digests = _expected_patch_digests(repository, paths, patch)
    store, config, expected_gates = _authorize_run(
        runtime=runtime,
        repository=repository,
        profile_id=profile_id,
        paths=paths,
        patch=patch,
    )
    result = run_execution_controller(store, config)
    if result.get("state") != "succeeded":
        raise AcceptanceError("acceptance_controller_failed")
    changed = _working_tree_changed_paths(repository)
    if changed != tuple(sorted(paths)) or tuple(result.get("gate_ids", ())) != expected_gates:
        raise AcceptanceError("acceptance_promotion_mismatch")
    if _git(repository, "rev-parse", "HEAD").decode("ascii").strip() != head:
        raise AcceptanceError("acceptance_head_changed")
    if _file_digest(sentinel) != sentinel_digest:
        raise AcceptanceError("acceptance_sentinel_changed")
    if _digest(_git(repository, "worktree", "list", "--porcelain", "-z")) != worktrees:
        raise AcceptanceError("acceptance_worktree_leaked")
    for value, original in originals.items():
        target = repository / value
        if original is None:
            if not target.is_file():
                raise AcceptanceError("acceptance_patch_not_promoted")
        elif target.read_text(encoding="utf-8") == original:
            raise AcceptanceError("acceptance_patch_not_promoted")
        if _file_digest(target) != expected_digests[value]:
            raise AcceptanceError("acceptance_promoted_bytes_mismatch")
    evidence = result.get("evidence_digest")
    if not isinstance(evidence, str) or not evidence.startswith("sha256:"):
        raise AcceptanceError("acceptance_evidence_missing")
    return {
        "name": name,
        "status": "passed",
        "gate_count": len(expected_gates),
        "changed_file_count": len(paths),
        "evidence_digest": evidence,
        "execution_started": True,
        "promotion_applied": True,
        "target_bytes_exact": True,
        "sandbox_boundary_preserved": True,
    }


def _run_expected_blocked_scenario(
    repository: Path,
    *,
    name: str = "unknown-repository",
    profile_id: str = "xmuse-monorepo/v2",
    expected_reason: str | None = None,
) -> dict[str, Any]:
    head = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    status = _digest(_git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=normal"))
    worktrees = _digest(_git(repository, "worktree", "list", "--porcelain", "-z"))
    profile = get_execution_gate_profile(profile_id)
    try:
        build_repository_manifest_digest(repository, profile)
        build_toolchain_capability_digest(repository, profile, gate_ids=profile.gate_ids)
    except RoomExecutionSandboxError as exc:
        reason_code = exc.code
    else:
        raise AcceptanceError("acceptance_unknown_repository_not_blocked")
    if reason_code not in {
        "execution_gate_profile_marker_missing",
        "execution_gate_profile_marker_invalid",
        "execution_backend_dependencies_unavailable",
        "execution_frontend_dependencies_unavailable",
    }:
        raise AcceptanceError("acceptance_unknown_repository_wrong_blocker")
    if expected_reason is not None and reason_code != expected_reason:
        raise AcceptanceError("acceptance_unknown_repository_wrong_blocker")
    if (
        _git(repository, "rev-parse", "HEAD").decode("ascii").strip() != head
        or _digest(
            _git(
                repository,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=normal",
            )
        )
        != status
        or _digest(_git(repository, "worktree", "list", "--porcelain", "-z")) != worktrees
    ):
        raise AcceptanceError("acceptance_blocked_repository_changed")
    return {
        "name": name,
        "status": "expected_blocked",
        "reason_code": reason_code,
        "changed_file_count": 0,
        "gate_count": 0,
        "execution_started": False,
        "promotion_applied": False,
        "target_bytes_exact": True,
        "sandbox_boundary_preserved": True,
        "evidence_digest": _digest(
            json.dumps(
                {
                    "name": name,
                    "profile_id": profile_id,
                    "reason_code": reason_code,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.xmuse_repo).resolve(strict=True)
    memoryos = Path(args.memoryos_repo).resolve(strict=True)
    blocked = Path(args.blocked_repo).resolve(strict=True)
    source_guard = _source_guard(source)
    memory_guard = _source_guard(memoryos)
    blocked_guard = _source_guard(blocked)
    if source_guard.head != args.xmuse_expected_head:
        raise AcceptanceError("acceptance_xmuse_head_mismatch")
    if memory_guard.head != args.memoryos_expected_head:
        raise AcceptanceError("acceptance_memoryos_head_mismatch")
    if blocked_guard.head != args.blocked_expected_head:
        raise AcceptanceError("acceptance_blocked_head_mismatch")
    if _git(memoryos, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise AcceptanceError("acceptance_memoryos_dirty")
    if _git(blocked, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise AcceptanceError("acceptance_blocked_source_dirty")
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="xmuse-execution-profile-acceptance-") as raw:
        temporary = Path(raw)
        snapshot = temporary / "xmuse-snapshot"
        _copy_working_snapshot(source, snapshot)
        for index, (name, (profile_id, paths)) in enumerate(XMUSE_SCENARIOS.items()):
            repository = temporary / f"xmuse-{index}"
            _clone_no_hardlinks(snapshot, repository)
            results.append(
                _run_scenario(
                    name=name,
                    repository=repository,
                    dependency_source=source,
                    runtime=temporary / f"runtime-{index}",
                    profile_id=profile_id,
                    paths=paths,
                )
            )
        memory_clone = temporary / "memoryos"
        _clone_no_hardlinks(memoryos, memory_clone)
        fixture_bytes = (
            Path(__file__).resolve().parent / "fixtures" / "memoryos-python-uv-7e85e85.patch"
        ).read_bytes()
        if _digest(fixture_bytes) != MEMORYOS_FIXTURE_SHA256:
            raise AcceptanceError("acceptance_memoryos_fixture_drift")
        results.append(
            _run_scenario(
                name="memoryos-python",
                repository=memory_clone,
                dependency_source=memoryos,
                runtime=temporary / "runtime-memoryos",
                profile_id=MEMORYOS_SCENARIO[0],
                paths=MEMORYOS_SCENARIO[1],
                fixture_patch=fixture_bytes.decode("utf-8", errors="strict"),
            )
        )
        blocked_clone = temporary / "blocked-repository"
        _clone_no_hardlinks(blocked, blocked_clone)
        results.append(_run_expected_blocked_scenario(blocked_clone))
    _require_source_guard(source, source_guard)
    _require_source_guard(memoryos, memory_guard)
    _require_source_guard(blocked, blocked_guard)
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "passed",
        "scenario_count": len(results),
        "scenarios": results,
        "source_guards_unchanged": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xmuse-repo", default=str(Path.cwd()))
    parser.add_argument("--xmuse-expected-head", required=True)
    parser.add_argument("--memoryos-repo", required=True)
    parser.add_argument("--memoryos-expected-head", required=True)
    parser.add_argument("--blocked-repo", required=True)
    parser.add_argument("--blocked-expected-head", required=True)
    return parser


def main() -> int:
    try:
        result = run_acceptance(_parser().parse_args())
    except AcceptanceError as exc:
        result = {
            "schema_version": RESULT_SCHEMA,
            "status": "failed",
            "reason_code": exc.code,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    except Exception:
        result = {
            "schema_version": RESULT_SCHEMA,
            "status": "failed",
            "reason_code": "acceptance_internal_error",
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
