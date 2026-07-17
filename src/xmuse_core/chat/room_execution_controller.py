"""One-shot exact-patch controller for the Room execution harness.

The controller is privileged infrastructure, never an Agent.  It consumes an already
authorized immutable candidate from the durable execution store, stages exactly that
patch at its recorded base commit, runs fixed gates in a networkless sandbox, and only
then promotes the same bytes into a still-clean target worktree.

The patch/worktree primitives in this module are intentionally independent from the
SQLite store.  ``run_execution_controller`` is the narrow adapter to the store contract;
tests can exercise the security boundary without constructing API state.
"""

from __future__ import annotations

import codecs
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, TypedDict

from xmuse_core.chat.room_execution_contracts import ExecutionWorkspaceGuard
from xmuse_core.chat.room_execution_profiles import (
    ExecutionGatePlan,
    RoomExecutionProfileError,
    execution_gate_plan_from_mapping,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_execution_sandbox import (
    GateResourceMonitor,
    GateResult,
    RoomExecutionSandboxError,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    discover_sandbox_layout,
    probe_sandbox_capability,
    run_gate,
)
from xmuse_core.chat.room_runtime import read_process_start_identity

MAX_PATCH_BYTES = 200 * 1024
MAX_PATCH_FILES = 32
MAX_PATCHED_TEXT_FILE_BYTES = 32 * 1024 * 1024
EXECUTION_CONTROLLER_SCHEMA = "room_execution_controller/v1"
EXECUTION_ATTEMPT_MARKER_SCHEMA = "room_execution_attempt_owner/v1"
PROMOTION_JOURNAL_SCHEMA = "room_execution_promotion_journal/v1"
_ZERO_OID = "0" * 40
_PATCH_FORBIDDEN_MARKERS = (
    "GIT binary patch",
    "Binary files ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "similarity index ",
    "dissimilarity index ",
)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class RoomExecutionControllerError(RuntimeError):
    """Stable controller failure safe for durable state."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExecutionCancelled(RoomExecutionControllerError):
    def __init__(self) -> None:
        super().__init__("execution_cancelled")


@dataclass(frozen=True)
class ExactPatchCandidate:
    candidate_id: str
    patch_text: str
    patch_sha256: str
    candidate_digest: str
    base_head: str
    allowed_files: tuple[str, ...]
    policy_revision: int
    risk_policy_revision: str
    workspace_guard_digest: str | None = None


@dataclass(frozen=True)
class PatchFileEntry:
    path: str
    operation: Literal["create", "modify", "delete"]
    pre_sha256: str | None
    post_sha256: str | None
    pre_mode: str | None
    post_mode: str | None

    def store_payload(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "pre_sha256": self.pre_sha256,
            "post_sha256": self.post_sha256,
        }


@dataclass(frozen=True)
class StagedExactPatch:
    stage: Path
    candidate_id: str
    patch_sha256: str
    changed_files: tuple[str, ...]
    entries: tuple[PatchFileEntry, ...]
    pre_manifest_digest: str
    post_manifest_digest: str


@dataclass(frozen=True)
class RepositoryGuard:
    head: str
    clean: bool


class WorkspaceCandidate(Protocol):
    @property
    def base_head(self) -> str: ...

    @property
    def allowed_files(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class ControllerConfig:
    xmuse_root: Path
    execution_root: Path
    run_id: str
    controller_id: str
    controller_generation: str
    controller_pid: int
    controller_start_identity: str


class ControllerIdentityKwargs(TypedDict):
    controller_id: str
    controller_generation: str
    controller_pid: int
    controller_start_identity: str


@dataclass(frozen=True)
class ExecutionAttemptOwner:
    controller_id: str
    controller_generation: str
    pid: int
    start_identity: str


class ExecutionStore(Protocol):
    """Goal 2 A-line CAS surface used by this controller."""

    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...

    def get_policy(self, conversation_id: str) -> Mapping[str, Any] | None: ...

    def list_controller_recovery(self, *, limit: int = 100) -> Sequence[Mapping[str, Any]]: ...

    def claim_requested_run(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def reclaim_run_controller(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        expected_execution_generation: int,
        prior_controller_id: str,
        prior_controller_generation: str,
        prior_controller_pid: int,
        prior_controller_start_identity: str,
        confirmed_dead: bool,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def get_controller_material(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        execution_generation: int,
    ) -> Mapping[str, Any]: ...

    def advance_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_state: str,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def record_gate_evidence(
        self,
        *,
        run_id: str,
        expected_run_state: str,
        expected_run_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        gate_id: str,
        status: Literal["running", "passed", "failed", "cancelled"],
        evidence_digest: str,
        started_at: str,
        finished_at: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def prepare_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_head: str,
        pre_manifest_digest: str,
        post_manifest_digest: str,
        file_entries: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def mark_promotion_applying(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def resolve_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        observed_manifest_digest: str,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def acknowledge_cancel(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        transport_stopped: bool,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def finalize_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        terminal_state: Literal["succeeded", "failed", "blocked", "cancelled"],
        reason_code: str,
        changed_files: Sequence[str] = (),
        gate_ids: Sequence[str] = (),
        evidence_digest: str | None = None,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...


@contextmanager
def repository_execution_lock(execution_root: Path) -> Iterator[None]:
    """Serialize promotion for every worktree belonging to one Git common dir."""

    common_dir = git_common_dir(execution_root)
    lock_path = common_dir / ".xmuse-room-execution.lock"
    if os.path.lexists(lock_path) and lock_path.is_symlink():
        raise RoomExecutionControllerError("execution_repo_lock_invalid")
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RoomExecutionControllerError("execution_repo_busy") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def git_common_dir(execution_root: Path) -> Path:
    root = execution_root.resolve(strict=True)
    result = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    path = Path(result.stdout.decode("utf-8").strip())
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise RoomExecutionControllerError("execution_target_not_git") from exc


def inspect_repository(execution_root: Path) -> RepositoryGuard:
    root = execution_root.resolve(strict=True)
    head = _git(root, "rev-parse", "HEAD").stdout.decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise RoomExecutionControllerError("execution_target_head_invalid")
    status_payload = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal").stdout
    return RepositoryGuard(head=head, clean=not status_payload)


def build_workspace_guard(
    execution_root: Path, candidate: WorkspaceCandidate
) -> ExecutionWorkspaceGuard:
    """Build the sole trusted authorization guard from target filesystem facts."""

    root = execution_root.resolve(strict=True)
    repository = inspect_repository(root)
    if repository.head != candidate.base_head:
        raise RoomExecutionControllerError("execution_target_head_mismatch")
    paths = tuple(sorted(candidate.allowed_files))
    if not paths or len(paths) > MAX_PATCH_FILES:
        raise RoomExecutionControllerError("execution_allowed_files_invalid")
    entries: list[PatchFileEntry] = []
    existing: set[str] = set()
    for value in paths:
        validate_patch_path(value)
        current = root
        for part in PurePosixPath(value).parts[:-1]:
            current = current / part
            if not os.path.lexists(current):
                break
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_symlink_ancestor")
            if not stat.S_ISDIR(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_path_invalid")
        path = root / value
        if os.path.lexists(path):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_symlink_rejected")
            if not stat.S_ISREG(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_special_file_rejected")
            existing.add(value)
            digest = _safe_regular_sha256(path)
            mode = _safe_regular_mode(path)
        else:
            digest = None
            mode = None
        entries.append(
            PatchFileEntry(
                path=value,
                operation="modify" if digest is not None else "create",
                pre_sha256=digest,
                post_sha256=digest,
                pre_mode=mode,
                post_mode=mode,
            )
        )
    return ExecutionWorkspaceGuard(
        base_head=repository.head,
        workspace_clean=repository.clean,
        target_files_digest=manifest_digest(entries, image="pre"),
        existing_regular_files=frozenset(existing),
    )


def validate_candidate(candidate: ExactPatchCandidate) -> bytes:
    try:
        patch = candidate.patch_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RoomExecutionControllerError("execution_patch_not_utf8") from exc
    if not patch or len(patch) > MAX_PATCH_BYTES:
        raise RoomExecutionControllerError("execution_patch_too_large")
    if b"\0" in patch:
        raise RoomExecutionControllerError("execution_patch_binary_rejected")
    digest = f"sha256:{hashlib.sha256(patch).hexdigest()}"
    if not _constant_digest_equal(digest, candidate.patch_sha256):
        raise RoomExecutionControllerError("execution_patch_digest_mismatch")
    if not re.fullmatch(r"[0-9a-f]{40,64}", candidate.base_head):
        raise RoomExecutionControllerError("execution_base_head_invalid")
    if not candidate.allowed_files or len(candidate.allowed_files) > MAX_PATCH_FILES:
        raise RoomExecutionControllerError("execution_patch_file_limit")
    if tuple(sorted(set(candidate.allowed_files))) != candidate.allowed_files:
        raise RoomExecutionControllerError("execution_allowed_files_invalid")
    for path in candidate.allowed_files:
        validate_patch_path(path)
    text = patch.decode("utf-8")
    if any(marker in text for marker in _PATCH_FORBIDDEN_MARKERS):
        raise RoomExecutionControllerError("execution_patch_unsupported_form")
    return patch


def validate_patch_path(value: str) -> None:
    if not value or "\\" in value or any(ord(char) < 32 for char in value):
        raise RoomExecutionControllerError("execution_patch_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise RoomExecutionControllerError("execution_patch_path_invalid")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RoomExecutionControllerError("execution_patch_path_invalid")
    folded = {part.casefold() for part in path.parts}
    if ".git" in folded or ".gitmodules" in folded:
        raise RoomExecutionControllerError("execution_patch_path_forbidden")


@contextmanager
def stage_exact_patch(
    *,
    xmuse_root: Path,
    execution_root: Path,
    run_id: str,
    candidate: ExactPatchCandidate,
    owner: ExecutionAttemptOwner | None = None,
) -> Iterator[StagedExactPatch]:
    """Create and exclusively clean one detached worktree owned by this invocation."""

    patch = validate_candidate(candidate)
    root = execution_root.resolve(strict=True)
    guard = inspect_repository(root)
    if guard.head != candidate.base_head:
        raise RoomExecutionControllerError("execution_target_head_mismatch")
    if not guard.clean:
        raise RoomExecutionControllerError("execution_target_dirty")
    runtime_root = xmuse_root.resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    actual_owner = owner or _current_attempt_owner()
    execution_dir = runtime_root / "runtime" / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    repository_digest = _repository_identity_digest(root)
    recover_owned_execution_attempts(
        execution_root=root,
        execution_dir=execution_dir,
        run_id=run_id,
        candidate_id=candidate.candidate_id,
        repository_digest=repository_digest,
    )
    attempt_key = hashlib.sha256(
        f"{run_id}\0{candidate.candidate_id}\0{uuid.uuid4().hex}".encode()
    ).hexdigest()[:32]
    attempt_dir = execution_dir / attempt_key
    stage = attempt_dir / "worktree"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    marker = attempt_dir / "owner.json"
    _write_owned_marker(
        marker,
        attempt_id=attempt_key,
        run_id=run_id,
        candidate_id=candidate.candidate_id,
        repository_digest=repository_digest,
        owner=actual_owner,
    )
    worktree_added = False
    try:
        _git(root, "worktree", "add", "--detach", str(stage), candidate.base_head)
        worktree_added = True
        _validate_allowed_ancestors(stage, candidate.allowed_files)
        _validate_ignored_additions(stage, candidate.allowed_files)
        _git_input(stage, patch, "apply", "--check", "--index")
        _git_input(stage, patch, "apply", "--index")
        entries = inspect_staged_patch(stage, candidate.allowed_files)
        pre_digest = manifest_digest(entries, image="pre")
        post_digest = manifest_digest(entries, image="post")
        if candidate.workspace_guard_digest and not _constant_digest_equal(
            candidate.workspace_guard_digest, pre_digest
        ):
            raise RoomExecutionControllerError("execution_workspace_guard_mismatch")
        yield StagedExactPatch(
            stage=stage,
            candidate_id=candidate.candidate_id,
            patch_sha256=candidate.patch_sha256,
            changed_files=tuple(entry.path for entry in entries),
            entries=entries,
            pre_manifest_digest=pre_digest,
            post_manifest_digest=post_digest,
        )
    finally:
        if worktree_added:
            _remove_owned_worktree(root, attempt_dir, stage, marker, attempt_id=attempt_key)
        else:
            _remove_owned_attempt_dir(attempt_dir, marker, attempt_id=attempt_key)


def inspect_staged_patch(stage: Path, allowed_files: Sequence[str]) -> tuple[PatchFileEntry, ...]:
    raw = _git(stage, "diff", "--cached", "--raw", "-z", "--no-abbrev", "HEAD", "--").stdout
    records = _parse_raw_diff(raw)
    actual = tuple(sorted(record["path"] for record in records))
    if actual != tuple(allowed_files):
        raise RoomExecutionControllerError("execution_patch_changed_files_mismatch")
    entries: list[PatchFileEntry] = []
    for record in sorted(records, key=lambda item: item["path"]):
        path = record["path"]
        old_mode = record["old_mode"]
        new_mode = record["new_mode"]
        old_oid = record["old_oid"]
        new_oid = record["new_oid"]
        if old_mode in {"120000", "160000"} or new_mode in {"120000", "160000"}:
            raise RoomExecutionControllerError("execution_patch_special_file_rejected")
        if old_mode not in {"000000", "100644", "100755"} or new_mode not in {
            "000000",
            "100644",
            "100755",
        }:
            raise RoomExecutionControllerError("execution_patch_mode_rejected")
        if old_mode != "000000" and new_mode != "000000" and old_mode != new_mode:
            raise RoomExecutionControllerError("execution_patch_mode_change_rejected")
        if old_oid == new_oid:
            raise RoomExecutionControllerError("execution_patch_mode_only_rejected")
        if old_mode == "000000":
            if new_mode != "100644":
                raise RoomExecutionControllerError("execution_patch_new_mode_rejected")
            operation: Literal["create", "modify", "delete"] = "create"
            pre_sha = None
        elif new_mode == "000000":
            operation = "delete"
            pre_sha = _git_blob_sha256(stage, "HEAD", path)
        else:
            operation = "modify"
            pre_sha = _git_blob_sha256(stage, "HEAD", path)
        post_sha = None if operation == "delete" else _safe_regular_sha256(stage / path)
        entries.append(
            PatchFileEntry(
                path=path,
                operation=operation,
                pre_sha256=pre_sha,
                post_sha256=post_sha,
                pre_mode=None if old_mode == "000000" else old_mode,
                post_mode=None if new_mode == "000000" else new_mode,
            )
        )
    if not entries:
        raise RoomExecutionControllerError("execution_patch_empty")
    return tuple(entries)


def verify_stage_unchanged(staged: StagedExactPatch) -> None:
    unstaged = _git(staged.stage, "diff", "--quiet", "--", check=False)
    if unstaged.returncode not in {0, 1}:
        raise RoomExecutionControllerError("execution_stage_inspection_failed")
    if unstaged.returncode == 1:
        raise RoomExecutionControllerError("execution_gate_workspace_mutated")
    current = inspect_image(staged.stage, staged.entries)
    if current != staged.post_manifest_digest:
        raise RoomExecutionControllerError("execution_gate_workspace_mutated")


def manifest_digest(entries: Sequence[PatchFileEntry], *, image: Literal["pre", "post"]) -> str:
    payload = []
    for entry in sorted(entries, key=lambda value: value.path):
        payload.append(
            {
                "path": entry.path,
                "sha256": entry.pre_sha256 if image == "pre" else entry.post_sha256,
            }
        )
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def inspect_image(root: Path, entries: Sequence[PatchFileEntry]) -> str:
    observed: list[PatchFileEntry] = []
    for entry in entries:
        path = root / entry.path
        if os.path.lexists(path):
            sha = _safe_regular_sha256(path)
            mode = _safe_regular_mode(path)
        else:
            sha = None
            mode = None
        observed.append(
            PatchFileEntry(
                path=entry.path,
                operation=entry.operation,
                pre_sha256=sha,
                post_sha256=sha,
                pre_mode=mode,
                post_mode=mode,
            )
        )
    return manifest_digest(observed, image="post")


def classify_observed_image(root: Path, staged: StagedExactPatch) -> str:
    observed = inspect_image(root, staged.entries)
    if observed == staged.pre_manifest_digest:
        return "pre"
    if observed == staged.post_manifest_digest:
        return "post"
    return "ambiguous"


def promote_exact_patch(
    *,
    execution_root: Path,
    candidate: ExactPatchCandidate,
    staged: StagedExactPatch,
) -> str:
    """Apply the original exact patch to an unchanged target and fsync its image."""

    root = execution_root.resolve(strict=True)
    guard = inspect_repository(root)
    if guard.head != candidate.base_head:
        raise RoomExecutionControllerError("execution_promotion_head_changed")
    if not guard.clean:
        raise RoomExecutionControllerError("execution_promotion_target_dirty")
    _validate_target_ancestors(root, staged.entries)
    if classify_observed_image(root, staged) != "pre":
        raise RoomExecutionControllerError("execution_promotion_preimage_mismatch")
    patch = validate_candidate(candidate)
    _git_input(root, patch, "apply", "--check")
    _validate_target_ancestors(root, staged.entries)
    _git_input(root, patch, "apply")
    _fsync_promoted_paths(root, staged.entries)
    observed = inspect_image(root, staged.entries)
    if observed != staged.post_manifest_digest:
        raise RoomExecutionControllerError("execution_promotion_postimage_mismatch")
    return observed


def run_execution_controller(store: ExecutionStore, config: ControllerConfig) -> Mapping[str, Any]:
    """Run one durable execution attempt under CAS and repo fencing."""

    _validate_controller_config(config)
    with repository_execution_lock(config.execution_root):
        run = _bind_controller(store, config)
        current_state = _run_state(run)
        if current_state in {"cancelled", "succeeded", "failed", "blocked"}:
            return run
        execution_generation = _execution_generation(run)
        if current_state == "promoting":
            promoting_candidate = _candidate_from_material(run)
            _recover_run_attempts(config, promoting_candidate)
            return _reconcile_promoting_run(store, config, run)
        if current_state in {"cancel_requested", "cancel_pending"}:
            cancelling_candidate = _candidate_from_material(run)
            _recover_run_attempts(config, cancelling_candidate)
            return _acknowledge_cancel(store, config, run)
        completed_gates: list[str] = []
        changed_files: tuple[str, ...] = ()
        try:
            candidate = _candidate_from_material(run)
            _recover_run_attempts(config, candidate)
            gate_plan = _gate_plan_from_material(run, candidate)
            _verify_gate_plan_evidence(config.execution_root, gate_plan)
            _raise_if_cancelled(store, config, run)
            if current_state == "preparing":
                run = _advance(store, config, run, target_state="staging")
                current_state = "staging"
            with stage_exact_patch(
                xmuse_root=config.xmuse_root,
                execution_root=config.execution_root,
                run_id=config.run_id,
                candidate=candidate,
                owner=ExecutionAttemptOwner(
                    config.controller_id,
                    config.controller_generation,
                    config.controller_pid,
                    config.controller_start_identity,
                ),
            ) as staged:
                changed_files = staged.changed_files
                gate_results: list[GateResult] = []
                if current_state == "staging":
                    run = _advance(store, config, run, target_state="verifying")
                    current_state = "verifying"
                if current_state == "verifying":
                    layout = discover_sandbox_layout(
                        stage=staged.stage,
                        execution_root=config.execution_root,
                        gate_ids=gate_plan.gate_ids,
                        profile=get_execution_gate_profile(gate_plan.profile_id),
                        expected_toolchain_capability_digest=(
                            gate_plan.toolchain_capability_digest
                        ),
                    )
                    resource_monitor = GateResourceMonitor(staged.stage)
                    try:
                        probe_sandbox_capability(layout, resource_sampler=resource_monitor)
                        for gate_id in gate_plan.gate_ids:
                            started_at = _utc_now()
                            running_digest = _running_gate_digest(gate_id, started_at)
                            run = _record_gate(
                                store,
                                config,
                                run,
                                gate_id=gate_id,
                                status="running",
                                evidence_digest=running_digest,
                                started_at=started_at,
                            )
                            result = run_gate(
                                layout,
                                gate_id,
                                cancel_requested=lambda: _cancel_requested(store, config),
                                resource_sampler=resource_monitor,
                            )
                            cancelled = result.status == "cancelled" or _cancel_requested(
                                store, config
                            )
                            if cancelled:
                                run = _bound_material(store, config, execution_generation)
                            run = _record_gate(
                                store,
                                config,
                                run,
                                gate_id=gate_id,
                                status=(
                                    "cancelled" if cancelled else cast_gate_status(result.status)
                                ),
                                evidence_digest=result.evidence_digest,
                                started_at=started_at,
                                finished_at=_utc_now(),
                                reason_code=(
                                    "execution_cancelled" if cancelled else result.reason_code
                                ),
                            )
                            completed_gates.append(gate_id)
                            if cancelled:
                                raise ExecutionCancelled()
                            gate_results.append(result)
                            if result.status != "passed":
                                raise RoomExecutionControllerError(
                                    result.reason_code or "execution_gate_failed"
                                )
                    finally:
                        close_layout = getattr(layout, "close", None)
                        if close_layout is not None:
                            close_layout()
                    verify_stage_unchanged(staged)
                    _raise_if_cancelled(store, config, run)
                    run = _advance(store, config, run, target_state="ready_to_promote")
                    current_state = "ready_to_promote"
                if current_state != "ready_to_promote":
                    raise RoomExecutionControllerError("execution_run_state_invalid")
                _verify_fresh_authority(store, config, run, candidate, staged, gate_plan)
                _raise_if_cancelled(store, config, run)
                prepared = store.prepare_promotion(
                    run_id=config.run_id,
                    expected_revision=_run_revision(run),
                    execution_generation=execution_generation,
                    **_identity(config),
                    target_head=candidate.base_head,
                    pre_manifest_digest=staged.pre_manifest_digest,
                    post_manifest_digest=staged.post_manifest_digest,
                    file_entries=[entry.store_payload() for entry in staged.entries],
                )
                if _run_state(prepared) == "blocked":
                    return prepared
                applying = store.mark_promotion_applying(
                    run_id=config.run_id,
                    expected_revision=_run_revision(prepared),
                    execution_generation=execution_generation,
                    **_identity(config),
                )
                observed = promote_exact_patch(
                    execution_root=config.execution_root,
                    candidate=candidate,
                    staged=staged,
                )
                resolved = store.resolve_promotion(
                    run_id=config.run_id,
                    expected_revision=_run_revision(applying),
                    execution_generation=execution_generation,
                    **_identity(config),
                    observed_manifest_digest=observed,
                )
                if str(resolved.get("resolution")) != "applied":
                    raise RoomExecutionControllerError("execution_promotion_ambiguous")
                evidence_digest = _combined_gate_digest(gate_results)
                return store.finalize_run(
                    run_id=config.run_id,
                    expected_state="promoting",
                    expected_revision=_run_revision(_resolved_run(resolved)),
                    execution_generation=execution_generation,
                    **_identity(config),
                    terminal_state="succeeded",
                    reason_code="execution_succeeded",
                    changed_files=changed_files,
                    gate_ids=completed_gates,
                    evidence_digest=evidence_digest,
                )
        except ExecutionCancelled:
            latest = _bound_material(store, config, execution_generation)
            return _acknowledge_cancel(store, config, latest)
        except (RoomExecutionControllerError, RoomExecutionSandboxError) as exc:
            public = store.get_run(config.run_id)
            if public is None:
                raise RoomExecutionControllerError("execution_run_not_found") from exc
            latest_state = _run_state(public)
            if latest_state == "promoting":
                latest = _bound_material(store, config, execution_generation)
                return _reconcile_promoting_run(store, config, latest)
            if latest_state in {"failed", "blocked", "cancelled", "succeeded"}:
                return public
            latest = _bound_material(store, config, execution_generation)
            if latest_state in {"cancel_requested", "cancel_pending"}:
                return _acknowledge_cancel(store, config, latest)
            terminal = "blocked" if _is_guard_failure(exc.code) else "failed"
            return store.finalize_run(
                run_id=config.run_id,
                expected_state=latest_state,
                expected_revision=_run_revision(latest),
                execution_generation=execution_generation,
                **_identity(config),
                terminal_state=cast_terminal_state(terminal),
                reason_code=exc.code,
                gate_ids=completed_gates,
            )


def _bind_controller(store: ExecutionStore, config: ControllerConfig) -> Mapping[str, Any]:
    public = store.get_run(config.run_id)
    if public is None:
        raise RoomExecutionControllerError("execution_run_not_found")
    state = _run_state(public)
    if state in {"cancelled", "succeeded", "failed", "blocked"}:
        return public
    matches = [
        row
        for row in store.list_controller_recovery(limit=500)
        if row.get("run_id") == config.run_id
    ]
    if len(matches) != 1:
        raise RoomExecutionControllerError("execution_controller_binding_unknown")
    binding = matches[0]
    prior_id = binding.get("controller_id")
    prior_generation = binding.get("controller_generation")
    prior_pid = binding.get("controller_pid")
    prior_start = binding.get("controller_start_identity")
    if prior_id is None and prior_generation is None and prior_pid is None and prior_start is None:
        return store.claim_requested_run(
            run_id=config.run_id,
            **_identity(config),
        )
    if (
        not isinstance(prior_id, str)
        or not isinstance(prior_generation, str)
        or isinstance(prior_pid, bool)
        or not isinstance(prior_pid, int)
        or not isinstance(prior_start, str)
    ):
        raise RoomExecutionControllerError("execution_controller_binding_invalid")
    execution_generation = _mapping_nonnegative_int(
        binding, "execution_generation", code="execution_controller_binding_invalid"
    )
    if (
        prior_id == config.controller_id
        and prior_generation == config.controller_generation
        and prior_pid == config.controller_pid
        and prior_start == config.controller_start_identity
    ):
        return _bound_material(store, config, execution_generation)
    if read_process_start_identity(prior_pid) == prior_start:
        raise RoomExecutionControllerError("execution_controller_already_live")
    return store.reclaim_run_controller(
        run_id=config.run_id,
        expected_state=_run_state(binding),
        expected_revision=_run_revision(binding),
        expected_execution_generation=execution_generation,
        prior_controller_id=prior_id,
        prior_controller_generation=prior_generation,
        prior_controller_pid=prior_pid,
        prior_controller_start_identity=prior_start,
        confirmed_dead=True,
        **_identity(config),
    )


def _bound_material(
    store: ExecutionStore, config: ControllerConfig, execution_generation: int
) -> Mapping[str, Any]:
    return store.get_controller_material(
        run_id=config.run_id,
        execution_generation=execution_generation,
        **_identity(config),
    )


def _advance(
    store: ExecutionStore,
    config: ControllerConfig,
    run: Mapping[str, Any],
    *,
    target_state: str,
) -> Mapping[str, Any]:
    return store.advance_run(
        run_id=config.run_id,
        expected_state=_run_state(run),
        expected_revision=_run_revision(run),
        execution_generation=_execution_generation(run),
        target_state=target_state,
        **_identity(config),
    )


def _record_gate(
    store: ExecutionStore,
    config: ControllerConfig,
    run: Mapping[str, Any],
    *,
    gate_id: str,
    status: Literal["running", "passed", "failed", "cancelled"],
    evidence_digest: str,
    started_at: str,
    finished_at: str | None = None,
    reason_code: str | None = None,
) -> Mapping[str, Any]:
    return store.record_gate_evidence(
        run_id=config.run_id,
        expected_run_state=_run_state(run),
        expected_run_revision=_run_revision(run),
        execution_generation=_execution_generation(run),
        gate_id=gate_id,
        status=status,
        evidence_digest=evidence_digest,
        started_at=started_at,
        finished_at=finished_at,
        reason_code=reason_code,
        **_identity(config),
    )


def _acknowledge_cancel(
    store: ExecutionStore, config: ControllerConfig, run: Mapping[str, Any]
) -> Mapping[str, Any]:
    return store.acknowledge_cancel(
        run_id=config.run_id,
        expected_revision=_run_revision(run),
        execution_generation=_execution_generation(run),
        transport_stopped=True,
        **_identity(config),
    )


def _candidate_from_material(material: Mapping[str, Any]) -> ExactPatchCandidate:
    raw_candidate = material.get("candidate")
    authorization = material.get("authorization")
    if not isinstance(raw_candidate, Mapping) or not isinstance(authorization, Mapping):
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    candidate = candidate_from_mapping(raw_candidate)
    if authorization.get("status") != "consumed":
        raise RoomExecutionControllerError("execution_authorization_invalid")
    if authorization.get("candidate_digest") != candidate.candidate_digest:
        raise RoomExecutionControllerError("execution_candidate_guard_changed")
    if authorization.get("policy_revision") != candidate.policy_revision:
        raise RoomExecutionControllerError("execution_policy_guard_changed")
    if authorization.get("risk_policy_revision") != candidate.risk_policy_revision:
        raise RoomExecutionControllerError("execution_policy_guard_changed")
    workspace_guard = authorization.get("workspace_guard_digest")
    if not isinstance(workspace_guard, str):
        raise RoomExecutionControllerError("execution_workspace_guard_mismatch")
    return replace(candidate, workspace_guard_digest=workspace_guard)


def _gate_plan_from_material(
    material: Mapping[str, Any], candidate: ExactPatchCandidate
) -> ExecutionGatePlan:
    try:
        return execution_gate_plan_from_mapping(
            material.get("gate_plan"), changed_paths=candidate.allowed_files
        )
    except RoomExecutionProfileError as exc:
        raise RoomExecutionControllerError("execution_gate_plan_invalid") from exc


def _recover_run_attempts(
    config: ControllerConfig, candidate: ExactPatchCandidate
) -> tuple[str, ...]:
    execution_dir = config.xmuse_root.resolve() / "runtime" / "execution"
    return recover_owned_execution_attempts(
        execution_root=config.execution_root.resolve(strict=True),
        execution_dir=execution_dir,
        run_id=config.run_id,
        candidate_id=candidate.candidate_id,
        repository_digest=_repository_identity_digest(config.execution_root),
    )


def _verify_gate_plan_evidence(execution_root: Path, plan: ExecutionGatePlan) -> None:
    try:
        profile = get_execution_gate_profile(plan.profile_id)
        manifest = build_repository_manifest_digest(execution_root, profile)
        toolchain = build_toolchain_capability_digest(
            execution_root, profile, gate_ids=profile.gate_ids
        )
    except RoomExecutionProfileError as exc:
        raise RoomExecutionControllerError("execution_gate_profile_drift") from exc
    if not _constant_digest_equal(manifest, plan.repository_manifest_digest):
        raise RoomExecutionControllerError("execution_repository_manifest_drift")
    if not _constant_digest_equal(toolchain, plan.toolchain_capability_digest):
        raise RoomExecutionControllerError("execution_toolchain_capability_drift")


def _verify_fresh_authority(
    store: ExecutionStore,
    config: ControllerConfig,
    run: Mapping[str, Any],
    expected: ExactPatchCandidate,
    staged: StagedExactPatch,
    expected_plan: ExecutionGatePlan,
) -> None:
    fresh = _bound_material(store, config, _execution_generation(run))
    observed = _candidate_from_material(fresh)
    if observed != expected:
        raise RoomExecutionControllerError("execution_candidate_guard_changed")
    if observed.workspace_guard_digest != staged.pre_manifest_digest:
        raise RoomExecutionControllerError("execution_workspace_guard_mismatch")
    if _gate_plan_from_material(fresh, observed) != expected_plan:
        raise RoomExecutionControllerError("execution_gate_plan_drift")
    _verify_gate_plan_evidence(config.execution_root, expected_plan)
    conversation_id = _required_string(fresh, "conversation_id")
    policy = store.get_policy(conversation_id)
    authorization = fresh.get("authorization")
    raw_candidate = fresh.get("candidate")
    policy_snapshot = (
        raw_candidate.get("policy_snapshot") if isinstance(raw_candidate, Mapping) else None
    )
    if (
        policy is None
        or not isinstance(authorization, Mapping)
        or not isinstance(policy_snapshot, Mapping)
    ):
        raise RoomExecutionControllerError("execution_policy_guard_changed")
    if (
        policy.get("revision") != policy_snapshot.get("revision")
        or policy.get("risk_policy_revision") != policy_snapshot.get("risk_policy_revision")
        or policy.get("mode") != policy_snapshot.get("mode")
        or authorization.get("policy_revision") != policy_snapshot.get("revision")
        or authorization.get("risk_policy_revision") != policy_snapshot.get("risk_policy_revision")
    ):
        raise RoomExecutionControllerError("execution_policy_guard_changed")
    current_guard = build_workspace_guard(config.execution_root, observed)
    if (
        not current_guard.workspace_clean
        or current_guard.target_files_digest != staged.pre_manifest_digest
    ):
        raise RoomExecutionControllerError("execution_promotion_guard_changed")


def _identity(config: ControllerConfig) -> ControllerIdentityKwargs:
    return {
        "controller_id": config.controller_id,
        "controller_generation": config.controller_generation,
        "controller_pid": config.controller_pid,
        "controller_start_identity": config.controller_start_identity,
    }


def _running_gate_digest(gate_id: str, started_at: str) -> str:
    canonical = f"room_execution_gate_running/v1\0{gate_id}\0{started_at}"
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def cast_gate_status(
    value: str,
) -> Literal["running", "passed", "failed", "cancelled"]:
    if value not in {"running", "passed", "failed", "cancelled"}:
        raise RoomExecutionControllerError("execution_gate_status_invalid")
    return value  # type: ignore[return-value]


def cast_terminal_state(
    value: str,
) -> Literal["succeeded", "failed", "blocked", "cancelled"]:
    if value not in {"succeeded", "failed", "blocked", "cancelled"}:
        raise RoomExecutionControllerError("execution_run_state_invalid")
    return value  # type: ignore[return-value]


def candidate_from_mapping(payload: Mapping[str, Any]) -> ExactPatchCandidate:
    patch = payload.get("patch")
    if patch is None:
        patch = payload.get("unified_diff")
    allowed = payload.get("allowed_files")
    if isinstance(allowed, str):
        try:
            allowed = json.loads(allowed)
        except json.JSONDecodeError as exc:
            raise RoomExecutionControllerError("execution_candidate_invalid") from exc
    guard = payload.get("workspace_guard")
    guard_digest: str | None = None
    if isinstance(guard, Mapping):
        raw_guard = guard.get("target_files_digest")
        guard_digest = str(raw_guard) if raw_guard else None
    raw_guard_digest = payload.get("target_files_digest")
    if raw_guard_digest:
        guard_digest = str(raw_guard_digest)
    if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)):
        raise RoomExecutionControllerError("execution_candidate_invalid")
    return ExactPatchCandidate(
        candidate_id=_required_string(payload, "candidate_id"),
        patch_text=str(patch) if isinstance(patch, str) else "",
        patch_sha256=_required_string(payload, "patch_sha256"),
        candidate_digest=_required_string(payload, "candidate_digest"),
        base_head=_required_string(payload, "base_head"),
        allowed_files=tuple(sorted(str(value) for value in allowed)),
        policy_revision=_policy_revision(payload),
        risk_policy_revision=_risk_policy_revision(payload),
        workspace_guard_digest=guard_digest,
    )


def _reconcile_promoting_run(
    store: ExecutionStore, config: ControllerConfig, run: Mapping[str, Any]
) -> Mapping[str, Any]:
    candidate = _candidate_from_material(run)
    execution_generation = _execution_generation(run)
    journal = run.get("promotion_journal")
    if not isinstance(journal, Mapping):
        raise RoomExecutionControllerError("execution_promotion_journal_missing")
    entries = _entries_from_journal(journal)
    staged = StagedExactPatch(
        stage=Path(),
        candidate_id=candidate.candidate_id,
        patch_sha256=candidate.patch_sha256,
        changed_files=tuple(entry.path for entry in entries),
        entries=entries,
        pre_manifest_digest=_required_string(journal, "pre_manifest_digest"),
        post_manifest_digest=_required_string(journal, "post_manifest_digest"),
    )
    journal_status = str(journal.get("status") or "")
    if journal_status == "ambiguous":
        return run
    if journal_status == "applied":
        return _finalize_reconciled_success(store, config, run, staged)
    observed_kind, observed_digest = _observe_promotion_image(config.execution_root, staged)
    if journal_status == "prepared":
        if observed_kind != "pre":
            return store.finalize_run(
                run_id=config.run_id,
                expected_state="promoting",
                expected_revision=_run_revision(run),
                execution_generation=execution_generation,
                **_identity(config),
                terminal_state="blocked",
                reason_code="execution_promotion_prepared_guard_changed",
            )
        blocked = _block_recovered_promotion_drift(store, config, run, candidate, staged)
        if blocked is not None:
            return blocked
        applying = store.mark_promotion_applying(
            run_id=config.run_id,
            expected_revision=_run_revision(run),
            execution_generation=execution_generation,
            **_identity(config),
        )
    elif journal_status == "applying":
        resolution = store.resolve_promotion(
            run_id=config.run_id,
            expected_revision=_run_revision(run),
            execution_generation=execution_generation,
            **_identity(config),
            observed_manifest_digest=observed_digest,
        )
        resolution_kind = str(resolution.get("resolution") or "")
        if resolution_kind == "ambiguous":
            return _resolved_run(resolution)
        if resolution_kind == "applied":
            return _finalize_reconciled_success(store, config, _resolved_run(resolution), staged)
        if resolution_kind != "not_applied":
            raise RoomExecutionControllerError("execution_promotion_ambiguous")
        prepared = _resolved_run(resolution)
        blocked = _block_recovered_promotion_drift(store, config, prepared, candidate, staged)
        if blocked is not None:
            return blocked
        applying = store.mark_promotion_applying(
            run_id=config.run_id,
            expected_revision=_run_revision(prepared),
            execution_generation=execution_generation,
            **_identity(config),
        )
    else:
        raise RoomExecutionControllerError("execution_promotion_journal_invalid")

    try:
        promoted = promote_exact_patch(
            execution_root=config.execution_root,
            candidate=candidate,
            staged=staged,
        )
    except RoomExecutionControllerError as exc:
        _kind, after_failure = _observe_promotion_image(config.execution_root, staged)
        resolution = store.resolve_promotion(
            run_id=config.run_id,
            expected_revision=_run_revision(applying),
            execution_generation=execution_generation,
            **_identity(config),
            observed_manifest_digest=after_failure,
        )
        if str(resolution.get("resolution")) == "applied":
            return _finalize_reconciled_success(store, config, _resolved_run(resolution), staged)
        if str(resolution.get("resolution")) == "ambiguous":
            return _resolved_run(resolution)
        prepared = _resolved_run(resolution)
        return store.finalize_run(
            run_id=config.run_id,
            expected_state="promoting",
            expected_revision=_run_revision(prepared),
            execution_generation=execution_generation,
            **_identity(config),
            terminal_state="blocked",
            reason_code=exc.code,
        )
    resolution = store.resolve_promotion(
        run_id=config.run_id,
        expected_revision=_run_revision(applying),
        execution_generation=execution_generation,
        **_identity(config),
        observed_manifest_digest=promoted,
    )
    if str(resolution.get("resolution")) != "applied":
        return _resolved_run(resolution)
    return _finalize_reconciled_success(store, config, _resolved_run(resolution), staged)


def _block_recovered_promotion_drift(
    store: ExecutionStore,
    config: ControllerConfig,
    run: Mapping[str, Any],
    candidate: ExactPatchCandidate,
    staged: StagedExactPatch,
) -> Mapping[str, Any] | None:
    try:
        plan = _gate_plan_from_material(run, candidate)
        _verify_fresh_authority(store, config, run, candidate, staged, plan)
    except (RoomExecutionControllerError, RoomExecutionSandboxError) as exc:
        if not _is_guard_failure(exc.code):
            raise
        return store.finalize_run(
            run_id=config.run_id,
            expected_state="promoting",
            expected_revision=_run_revision(run),
            execution_generation=_execution_generation(run),
            **_identity(config),
            terminal_state="blocked",
            reason_code=exc.code,
        )
    return None


def _finalize_reconciled_success(
    store: ExecutionStore,
    config: ControllerConfig,
    run: Mapping[str, Any],
    staged: StagedExactPatch,
) -> Mapping[str, Any]:
    return store.finalize_run(
        run_id=config.run_id,
        expected_state="promoting",
        expected_revision=_run_revision(run),
        execution_generation=_execution_generation(run),
        **_identity(config),
        terminal_state="succeeded",
        reason_code="execution_promotion_reconciled_postimage",
        changed_files=staged.changed_files,
        gate_ids=_passed_gate_ids(run),
    )


def _observe_promotion_image(root: Path, staged: StagedExactPatch) -> tuple[str, str]:
    try:
        observed = inspect_image(root, staged.entries)
    except RoomExecutionControllerError as exc:
        canonical = f"room_execution_ambiguous_image/v1\0{exc.code}"
        return "ambiguous", f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    if observed == staged.pre_manifest_digest:
        return "pre", observed
    if observed == staged.post_manifest_digest:
        return "post", observed
    return "ambiguous", observed


def _passed_gate_ids(run: Mapping[str, Any]) -> tuple[str, ...]:
    candidate = _candidate_from_material(run)
    plan = _gate_plan_from_material(run, candidate)
    raw = run.get("gates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise RoomExecutionControllerError("execution_gate_evidence_invalid")
    passed: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("gate_id"), str):
            raise RoomExecutionControllerError("execution_gate_evidence_invalid")
        gate_id = str(item["gate_id"])
        if gate_id not in plan.gate_ids:
            raise RoomExecutionControllerError("execution_gate_evidence_unplanned")
        if item.get("status") == "passed":
            passed.add(gate_id)
    return tuple(gate_id for gate_id in plan.gate_ids if gate_id in passed)


def _resolved_run(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    run = payload.get("run")
    if not isinstance(run, Mapping):
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    return run


def _entries_from_journal(journal: Mapping[str, Any]) -> tuple[PatchFileEntry, ...]:
    raw_entries = journal.get("file_entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
        raise RoomExecutionControllerError("execution_promotion_journal_invalid")
    entries: list[PatchFileEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise RoomExecutionControllerError("execution_promotion_journal_invalid")
        path = _required_string(raw, "path")
        validate_patch_path(path)
        pre = _optional_string(raw.get("pre_sha256"))
        post = _optional_string(raw.get("post_sha256"))
        operation: Literal["create", "modify", "delete"]
        if pre is None:
            operation = "create"
        elif post is None:
            operation = "delete"
        else:
            operation = "modify"
        entries.append(PatchFileEntry(path, operation, pre, post, None, None))
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _parse_raw_diff(payload: bytes) -> list[dict[str, str]]:
    chunks = payload.split(b"\0")
    records: list[dict[str, str]] = []
    index = 0
    while index < len(chunks) and chunks[index]:
        header = chunks[index]
        index += 1
        if not header.startswith(b":") or index >= len(chunks):
            raise RoomExecutionControllerError("execution_patch_diff_invalid")
        fields = header[1:].split()
        if len(fields) != 5:
            raise RoomExecutionControllerError("execution_patch_diff_invalid")
        old_mode, new_mode, old_oid, new_oid, status_field = fields
        status_code = status_field[:1]
        if status_code in {b"R", b"C"}:
            raise RoomExecutionControllerError("execution_patch_unsupported_form")
        if status_code not in {b"A", b"M", b"D"}:
            raise RoomExecutionControllerError("execution_patch_unsupported_form")
        path_bytes = chunks[index]
        index += 1
        try:
            path = path_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RoomExecutionControllerError("execution_patch_path_invalid") from exc
        validate_patch_path(path)
        records.append(
            {
                "path": path,
                "old_mode": old_mode.decode("ascii"),
                "new_mode": new_mode.decode("ascii"),
                "old_oid": old_oid.decode("ascii"),
                "new_oid": new_oid.decode("ascii"),
            }
        )
    return records


def _validate_allowed_ancestors(stage: Path, paths: Sequence[str]) -> None:
    for value in paths:
        current = stage
        for part in PurePosixPath(value).parts[:-1]:
            current = current / part
            if not os.path.lexists(current):
                break
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_symlink_ancestor")
            if not stat.S_ISDIR(info.st_mode):
                raise RoomExecutionControllerError("execution_patch_path_invalid")
        target = stage / value
        if os.path.lexists(target):
            mode = target.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise RoomExecutionControllerError("execution_patch_symlink_rejected")
            if not stat.S_ISREG(mode):
                raise RoomExecutionControllerError("execution_patch_special_file_rejected")


def _validate_target_ancestors(root: Path, entries: Sequence[PatchFileEntry]) -> None:
    """Recheck target path types immediately before touching target bytes."""

    for entry in entries:
        current = root
        for part in PurePosixPath(entry.path).parts[:-1]:
            current = current / part
            if not os.path.lexists(current):
                raise RoomExecutionControllerError("execution_promotion_path_invalid")
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise RoomExecutionControllerError("execution_promotion_symlink_ancestor")
            if not stat.S_ISDIR(info.st_mode):
                raise RoomExecutionControllerError("execution_promotion_path_invalid")
        target = root / entry.path
        exists = os.path.lexists(target)
        if entry.operation == "create":
            if exists:
                raise RoomExecutionControllerError("execution_promotion_preimage_mismatch")
            continue
        if not exists:
            raise RoomExecutionControllerError("execution_promotion_preimage_mismatch")
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise RoomExecutionControllerError("execution_promotion_symlink_rejected")
        if not stat.S_ISREG(info.st_mode):
            raise RoomExecutionControllerError("execution_promotion_special_file_rejected")


def _validate_ignored_additions(stage: Path, paths: Sequence[str]) -> None:
    for path in paths:
        exists = _git(stage, "cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0
        if exists:
            continue
        ignored = _git(stage, "check-ignore", "-q", "--", path, check=False)
        if ignored.returncode == 0:
            raise RoomExecutionControllerError("execution_patch_ignored_path")
        if ignored.returncode not in {0, 1}:
            raise RoomExecutionControllerError("execution_patch_path_invalid")


def _git_blob_sha256(stage: Path, revision: str, path: str) -> str:
    size_result = _git(stage, "cat-file", "-s", f"{revision}:{path}")
    try:
        size = int(size_result.stdout.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise RoomExecutionControllerError("execution_patch_binary_forbidden") from exc
    if size > MAX_PATCHED_TEXT_FILE_BYTES:
        raise RoomExecutionControllerError("execution_patch_text_file_too_large")
    result = _git(stage, "show", f"{revision}:{path}")
    _validate_text_content(result.stdout)
    return f"sha256:{hashlib.sha256(result.stdout).hexdigest()}"


def _safe_regular_sha256(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RoomExecutionControllerError("execution_patch_special_file_rejected") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RoomExecutionControllerError("execution_patch_special_file_rejected")
        if info.st_size > MAX_PATCHED_TEXT_FILE_BYTES:
            raise RoomExecutionControllerError("execution_patch_text_file_too_large")
        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(128 * 1024):
                if b"\0" in chunk:
                    raise RoomExecutionControllerError("execution_patch_binary_forbidden")
                try:
                    decoder.decode(chunk, final=False)
                except UnicodeDecodeError as exc:
                    raise RoomExecutionControllerError("execution_patch_binary_forbidden") from exc
                digest.update(chunk)
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise RoomExecutionControllerError("execution_patch_binary_forbidden") from exc
        return f"sha256:{digest.hexdigest()}"
    finally:
        os.close(descriptor)


def _safe_regular_mode(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RoomExecutionControllerError("execution_patch_special_file_rejected")
    return "100755" if info.st_mode & stat.S_IXUSR else "100644"


def _validate_text_content(value: bytes) -> None:
    if b"\0" in value:
        raise RoomExecutionControllerError("execution_patch_binary_forbidden")
    try:
        value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RoomExecutionControllerError("execution_patch_binary_forbidden") from exc


def _fsync_promoted_paths(root: Path, entries: Sequence[PatchFileEntry]) -> None:
    parents: set[Path] = set()
    for entry in entries:
        path = root / entry.path
        parents.add(path.parent)
        if entry.post_sha256 is not None:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise RoomExecutionControllerError("execution_promotion_postimage_mismatch")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for parent in sorted(parents):
        descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_owned_marker(
    path: Path,
    *,
    attempt_id: str,
    run_id: str,
    candidate_id: str,
    repository_digest: str,
    owner: ExecutionAttemptOwner,
) -> None:
    payload = {
        "schema_version": EXECUTION_ATTEMPT_MARKER_SCHEMA,
        "attempt_id": attempt_id,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "repository_digest": repository_digest,
        "owner": {
            "controller_id": owner.controller_id,
            "controller_generation": owner.controller_generation,
            "pid": owner.pid,
            "start_identity": owner.start_identity,
        },
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def recover_owned_execution_attempts(
    *,
    execution_root: Path,
    execution_dir: Path,
    run_id: str,
    candidate_id: str,
    repository_digest: str,
) -> tuple[str, ...]:
    """Recover only dead, marker-proven attempts for this exact durable run."""

    return _recover_dead_execution_attempts(
        execution_root=execution_root,
        execution_dir=execution_dir,
        repository_digest=repository_digest,
        run_id=run_id,
        candidate_id=candidate_id,
    )


def _recover_dead_execution_attempts(
    *,
    execution_root: Path,
    execution_dir: Path,
    repository_digest: str,
    run_id: str,
    candidate_id: str,
) -> tuple[str, ...]:

    try:
        children = tuple(execution_dir.iterdir())
    except OSError:
        return ()
    recovered: list[str] = []
    for attempt_dir in children:
        if attempt_dir.is_symlink() or not attempt_dir.is_dir():
            continue
        marker = attempt_dir / "owner.json"
        payload = _read_attempt_marker(attempt_dir, marker)
        if payload is None:
            continue
        if payload.get("repository_digest") != repository_digest:
            continue
        if payload.get("run_id") != run_id:
            continue
        if payload.get("candidate_id") != candidate_id:
            continue
        owner = payload.get("owner")
        if not isinstance(owner, Mapping):
            continue
        pid = owner.get("pid")
        start_identity = owner.get("start_identity")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or not isinstance(start_identity, str)
            or not start_identity
        ):
            continue
        observed_identity = read_process_start_identity(pid)
        if observed_identity == start_identity:
            continue
        if observed_identity is None and Path(f"/proc/{pid}").exists():
            continue
        attempt_id = str(payload["attempt_id"])
        if _remove_owned_worktree(
            execution_root,
            attempt_dir,
            attempt_dir / "worktree",
            marker,
            attempt_id=attempt_id,
        ):
            recovered.append(attempt_id)
    return tuple(sorted(recovered))


def _remove_owned_worktree(
    root: Path,
    attempt_dir: Path,
    stage: Path,
    marker: Path,
    *,
    attempt_id: str,
) -> bool:
    if not _marker_owns_attempt(attempt_dir, marker, attempt_id=attempt_id):
        return False
    removed = _git(root, "worktree", "remove", "--force", str(stage), check=False)
    if removed.returncode != 0 and _worktree_is_registered(root, stage):
        return False
    return _remove_owned_attempt_dir(attempt_dir, marker, attempt_id=attempt_id)


def _worktree_is_registered(root: Path, stage: Path) -> bool:
    result = _git(root, "worktree", "list", "--porcelain", "-z", check=False)
    if result.returncode != 0:
        return True
    expected = str(stage.resolve(strict=False)).encode("utf-8")
    return any(
        record.removeprefix(b"worktree ") == expected
        for record in result.stdout.split(b"\0")
        if record.startswith(b"worktree ")
    )


def _remove_owned_attempt_dir(attempt_dir: Path, marker: Path, *, attempt_id: str) -> bool:
    if not _marker_owns_attempt(attempt_dir, marker, attempt_id=attempt_id):
        return False
    try:
        resolved = attempt_dir.resolve(strict=True)
        execution_parent = attempt_dir.parent.resolve(strict=True)
        resolved.relative_to(execution_parent)
    except (OSError, ValueError):
        return False
    shutil.rmtree(resolved)
    return True


def _marker_owns_attempt(attempt_dir: Path, marker: Path, *, attempt_id: str) -> bool:
    payload = _read_attempt_marker(attempt_dir, marker)
    return payload is not None and payload.get("attempt_id") == attempt_id


def _read_attempt_marker(attempt_dir: Path, marker: Path) -> Mapping[str, Any] | None:
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected_keys = {
        "schema_version",
        "attempt_id",
        "run_id",
        "candidate_id",
        "repository_digest",
        "owner",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) != expected_keys
        or payload.get("schema_version") != EXECUTION_ATTEMPT_MARKER_SCHEMA
        or marker.parent != attempt_dir
        or not all(
            isinstance(payload.get(key), str) and bool(payload.get(key))
            for key in ("attempt_id", "run_id", "candidate_id", "repository_digest")
        )
    ):
        return None
    owner = payload.get("owner")
    if (
        not isinstance(owner, Mapping)
        or set(owner) != {"controller_id", "controller_generation", "pid", "start_identity"}
        or not isinstance(owner.get("controller_id"), str)
        or not owner.get("controller_id")
        or not isinstance(owner.get("controller_generation"), str)
        or not owner.get("controller_generation")
        or isinstance(owner.get("pid"), bool)
        or not isinstance(owner.get("pid"), int)
        or int(owner["pid"]) <= 0
        or not isinstance(owner.get("start_identity"), str)
        or not owner.get("start_identity")
    ):
        return None
    return payload


def _current_attempt_owner() -> ExecutionAttemptOwner:
    pid = os.getpid()
    identity = read_process_start_identity(pid)
    if identity is None:
        raise RoomExecutionControllerError("execution_controller_identity_invalid")
    return ExecutionAttemptOwner("direct", "direct", pid, identity)


def _repository_identity_digest(root: Path) -> str:
    common = git_common_dir(root)
    info = common.stat()
    canonical = f"{common}\0{info.st_dev}\0{info.st_ino}"
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_env(),
        )
    except OSError as exc:
        raise RoomExecutionControllerError("execution_git_unavailable") from exc
    if check and result.returncode != 0:
        code = "execution_target_not_git" if args[:1] == ("rev-parse",) else "execution_git_failed"
        raise RoomExecutionControllerError(code)
    return result


def _git_input(cwd: Path, patch: bytes, *args: str) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            input=patch,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_git_env(),
        )
    except OSError as exc:
        raise RoomExecutionControllerError("execution_git_unavailable") from exc
    if result.returncode != 0:
        code = (
            "execution_patch_apply_check_failed"
            if "--check" in args
            else "execution_patch_apply_failed"
        )
        raise RoomExecutionControllerError(code)


def _git_env() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _cancel_requested(store: ExecutionStore, config: ControllerConfig) -> bool:
    run = store.get_run(config.run_id)
    state = str(run.get("state") or "") if run is not None else ""
    return state in {"cancel_requested", "cancel_pending", "cancelled"}


def _raise_if_cancelled(
    store: ExecutionStore, config: ControllerConfig, _run: Mapping[str, Any]
) -> None:
    if _cancel_requested(store, config):
        raise ExecutionCancelled()


def _validate_controller_config(config: ControllerConfig) -> None:
    for value in (config.run_id, config.controller_id, config.controller_generation):
        if not _SAFE_ID.fullmatch(value):
            raise RoomExecutionControllerError("execution_controller_identity_invalid")
    if config.controller_pid <= 0 or not config.controller_start_identity:
        raise RoomExecutionControllerError("execution_controller_identity_invalid")
    if config.xmuse_root.resolve() == config.execution_root.resolve():
        # Runtime state must never be staged as candidate source.
        raise RoomExecutionControllerError("execution_runtime_root_overlaps_target")


def _run_revision(run: Mapping[str, Any]) -> int:
    raw = run.get("revision")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise RoomExecutionControllerError("execution_run_invalid")
    return raw


def _run_state(run: Mapping[str, Any]) -> str:
    state = run.get("state")
    if not isinstance(state, str) or not state:
        raise RoomExecutionControllerError("execution_run_invalid")
    return state


def _execution_generation(run: Mapping[str, Any]) -> int:
    return _mapping_nonnegative_int(run, "execution_generation", code="execution_run_invalid")


def _mapping_nonnegative_int(value: Mapping[str, Any], key: str, *, code: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise RoomExecutionControllerError(code)
    return raw


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    return value


def _policy_revision(payload: Mapping[str, Any]) -> int:
    snapshot = payload.get("policy_snapshot")
    if not isinstance(snapshot, Mapping):
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    value = snapshot.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    return value


def _risk_policy_revision(payload: Mapping[str, Any]) -> str:
    snapshot = payload.get("policy_snapshot")
    if not isinstance(snapshot, Mapping):
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    value = snapshot.get("risk_policy_revision")
    if not isinstance(value, str) or not value:
        raise RoomExecutionControllerError("execution_store_contract_invalid")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _constant_digest_equal(left: str, right: str) -> bool:
    clean_left = left.removeprefix("sha256:")
    clean_right = right.removeprefix("sha256:")
    return (
        len(clean_left) == len(clean_right)
        and hashlib.sha256(clean_left.encode()).digest()
        == hashlib.sha256(clean_right.encode()).digest()
    )


def _combined_gate_digest(results: Sequence[GateResult]) -> str:
    value = "\0".join(result.evidence_digest for result in results)
    return f"sha256:{hashlib.sha256(value.encode('ascii')).hexdigest()}"


def _is_guard_failure(code: str) -> bool:
    return code in {
        "execution_target_not_git",
        "execution_target_dirty",
        "execution_target_head_mismatch",
        "execution_workspace_guard_mismatch",
        "execution_candidate_guard_changed",
        "execution_policy_guard_changed",
        "execution_authorization_invalid",
        "execution_promotion_guard_changed",
        "execution_promotion_head_changed",
        "execution_promotion_target_dirty",
        "execution_promotion_preimage_mismatch",
        "execution_promotion_ambiguous",
        "execution_sandbox_unavailable",
        "execution_backend_dependencies_unavailable",
        "execution_frontend_dependencies_unavailable",
        "execution_gate_plan_invalid",
        "execution_gate_plan_drift",
        "execution_gate_profile_drift",
        "execution_gate_profile_unknown",
        "execution_gate_profile_invalid",
        "execution_gate_profile_marker_missing",
        "execution_gate_profile_marker_invalid",
        "execution_repository_manifest_drift",
        "execution_toolchain_capability_drift",
        "execution_toolchain_unavailable",
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
