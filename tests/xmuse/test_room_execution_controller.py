from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from xmuse_core.chat import room_execution_controller as controller
from xmuse_core.chat.room_execution_controller import (
    EXECUTION_ATTEMPT_MARKER_SCHEMA,
    ExactPatchCandidate,
    RoomExecutionControllerError,
    classify_observed_image,
    inspect_repository,
    promote_exact_patch,
    recover_owned_execution_attempts,
    repository_execution_lock,
    stage_exact_patch,
    validate_candidate,
    validate_patch_path,
    verify_stage_unchanged,
)


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "README.md").write_text("old\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def _candidate(root: Path, changes: dict[str, str | None]) -> ExactPatchCandidate:
    tracked = set(_git(root, "ls-files").decode().splitlines())
    for path, content in changes.items():
        target = root / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    new_paths = [path for path in changes if path not in tracked and (root / path).exists()]
    if new_paths:
        _git(root, "add", "-N", "--", *new_paths)
    patch = _git(root, "diff", "--binary", "--", *sorted(changes)).decode("utf-8")
    if new_paths:
        _git(root, "reset", "-q", "--", *new_paths)
    tracked_changes = [path for path in changes if path in tracked]
    if tracked_changes:
        _git(root, "restore", "--worktree", "--", *tracked_changes)
    for path in changes:
        target = root / path
        if path not in tracked and target.exists():
            target.unlink()
    return ExactPatchCandidate(
        candidate_id="cand-1",
        patch_text=patch,
        patch_sha256=f"sha256:{hashlib.sha256(patch.encode()).hexdigest()}",
        candidate_digest="sha256:" + "c" * 64,
        base_head=_git(root, "rev-parse", "HEAD").decode().strip(),
        allowed_files=tuple(sorted(changes)),
        policy_revision=1,
        risk_policy_revision="room_execution_low_risk/v1",
    )


def test_stage_validates_actual_changed_set_and_cleans_only_owned_worktree(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    runtime = tmp_path / "runtime-root"
    candidate = _candidate(
        root,
        {"src/example.py": "VALUE = 2\n", "src/new.py": "NEW = True\n"},
    )

    with stage_exact_patch(
        xmuse_root=runtime,
        execution_root=root,
        run_id="run-1",
        candidate=candidate,
    ) as staged:
        assert staged.changed_files == ("src/example.py", "src/new.py")
        assert [entry.operation for entry in staged.entries] == ["modify", "create"]
        assert classify_observed_image(root, staged) == "pre"
        verify_stage_unchanged(staged)
        owned_stage = staged.stage

    assert not owned_stage.exists()
    assert (root / "src" / "example.py").read_text() == "VALUE = 1\n"
    assert inspect_repository(root).clean is True


def test_stage_rejects_allowed_files_that_do_not_equal_git_diff(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    candidate = _candidate(root, {"src/example.py": "VALUE = 2\n"})
    candidate = ExactPatchCandidate(**{**candidate.__dict__, "allowed_files": ("README.md",)})

    with pytest.raises(RoomExecutionControllerError) as error:
        with stage_exact_patch(
            xmuse_root=tmp_path / "runtime-root",
            execution_root=root,
            run_id="run-1",
            candidate=candidate,
        ):
            pytest.fail("invalid patch must not be yielded")

    assert error.value.code in {
        "execution_patch_apply_check_failed",
        "execution_patch_changed_files_mismatch",
    }
    assert inspect_repository(root).clean is True


def test_stage_detects_gate_mutating_a_tracked_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    candidate = _candidate(root, {"src/example.py": "VALUE = 2\n"})

    with stage_exact_patch(
        xmuse_root=tmp_path / "runtime-root",
        execution_root=root,
        run_id="run-1",
        candidate=candidate,
    ) as staged:
        (staged.stage / "src" / "example.py").write_text("MUTATED = True\n")
        with pytest.raises(RoomExecutionControllerError) as error:
            verify_stage_unchanged(staged)

    assert error.value.code == "execution_gate_workspace_mutated"


def test_promotion_requires_preimage_and_applies_same_patch_unstaged(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    candidate = _candidate(root, {"src/example.py": "VALUE = 2\n"})

    with stage_exact_patch(
        xmuse_root=tmp_path / "runtime-root",
        execution_root=root,
        run_id="run-1",
        candidate=candidate,
    ) as staged:
        observed = promote_exact_patch(execution_root=root, candidate=candidate, staged=staged)
        assert observed == staged.post_manifest_digest
        assert classify_observed_image(root, staged) == "post"

    assert (root / "src" / "example.py").read_text() == "VALUE = 2\n"
    assert _git(root, "diff", "--name-only").decode().strip() == "src/example.py"
    assert _git(root, "diff", "--cached", "--name-only") == b""


def test_repo_lock_is_common_to_linked_worktrees(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "--detach", str(linked), "HEAD")
    try:
        with repository_execution_lock(root):
            with pytest.raises(RoomExecutionControllerError) as error:
                with repository_execution_lock(linked):
                    pytest.fail("same repository lock must not be re-entered")
        assert error.value.code == "execution_repo_busy"
    finally:
        _git(root, "worktree", "remove", "--force", str(linked))


def test_orphan_recovery_is_marker_and_run_scoped_without_global_prune(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    execution_dir = tmp_path / "runtime" / "execution"
    orphan_dir = execution_dir / "owned-attempt"
    orphan_dir.mkdir(parents=True)
    orphan_stage = orphan_dir / "worktree"
    unrelated = tmp_path / "unrelated-worktree"
    foreign_dir = execution_dir / "foreign-attempt"
    foreign_dir.mkdir()
    foreign_stage = foreign_dir / "worktree"
    _git(root, "worktree", "add", "--detach", str(orphan_stage), "HEAD")
    _git(root, "worktree", "add", "--detach", str(unrelated), "HEAD")
    _git(root, "worktree", "add", "--detach", str(foreign_stage), "HEAD")
    repository_digest = controller._repository_identity_digest(root)
    (orphan_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema_version": EXECUTION_ATTEMPT_MARKER_SCHEMA,
                "attempt_id": "owned-attempt",
                "run_id": "run-1",
                "candidate_id": "candidate-1",
                "repository_digest": repository_digest,
                "owner": {
                    "controller_id": "dead-controller",
                    "controller_generation": "old-generation",
                    "pid": 999_999_999,
                    "start_identity": "dead-start-identity",
                },
            }
        ),
        encoding="utf-8",
    )
    (foreign_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema_version": EXECUTION_ATTEMPT_MARKER_SCHEMA,
                "attempt_id": "foreign-attempt",
                "run_id": "run-foreign",
                "candidate_id": "candidate-foreign",
                "repository_digest": repository_digest,
                "owner": {
                    "controller_id": "dead-controller",
                    "controller_generation": "old-generation",
                    "pid": 999_999_998,
                    "start_identity": "dead-start-identity",
                },
            }
        ),
        encoding="utf-8",
    )

    recovered = recover_owned_execution_attempts(
        execution_root=root,
        execution_dir=execution_dir,
        run_id="run-1",
        candidate_id="candidate-1",
        repository_digest=repository_digest,
    )

    assert recovered == ("owned-attempt",)
    assert not orphan_dir.exists()
    assert unrelated.exists()
    assert foreign_stage.exists()
    worktrees = _git(root, "worktree", "list", "--porcelain").decode()
    assert str(unrelated) in worktrees
    assert str(foreign_stage) in worktrees
    assert str(orphan_stage) not in worktrees
    _git(root, "worktree", "remove", "--force", str(unrelated))
    _git(root, "worktree", "remove", "--force", str(foreign_stage))


def test_orphan_recovery_preserves_unreadable_but_existing_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    execution_dir = tmp_path / "runtime" / "execution"
    attempt_dir = execution_dir / "uncertain-owner"
    attempt_dir.mkdir(parents=True)
    stage = attempt_dir / "worktree"
    _git(root, "worktree", "add", "--detach", str(stage), "HEAD")
    repository_digest = controller._repository_identity_digest(root)
    (attempt_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema_version": EXECUTION_ATTEMPT_MARKER_SCHEMA,
                "attempt_id": "uncertain-owner",
                "run_id": "run-uncertain",
                "candidate_id": "candidate-uncertain",
                "repository_digest": repository_digest,
                "owner": {
                    "controller_id": "controller",
                    "controller_generation": "generation",
                    "pid": os.getpid(),
                    "start_identity": "unreadable",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "read_process_start_identity", lambda _pid: None)

    recovered = recover_owned_execution_attempts(
        execution_root=root,
        execution_dir=execution_dir,
        run_id="run-uncertain",
        candidate_id="candidate-uncertain",
        repository_digest=repository_digest,
    )

    assert recovered == ()
    assert stage.exists()
    _git(root, "worktree", "remove", "--force", str(stage))


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/x",
        "../x",
        "a/../x",
        ".git/config",
        ".gitmodules",
        "docs/.GITMODULES",
        "a\\b",
        "a\x00b",
    ],
)
def test_patch_path_rejects_escape_and_git_metadata(path: str) -> None:
    with pytest.raises(RoomExecutionControllerError):
        validate_patch_path(path)


def test_candidate_rejects_binary_and_digest_drift() -> None:
    patch = "GIT binary patch\nliteral 0\n"
    candidate = ExactPatchCandidate(
        candidate_id="candidate",
        patch_text=patch,
        patch_sha256=f"sha256:{hashlib.sha256(patch.encode()).hexdigest()}",
        candidate_digest="sha256:" + "c" * 64,
        base_head="a" * 40,
        allowed_files=("src/a.py",),
        policy_revision=1,
        risk_policy_revision="room_execution_low_risk/v1",
    )
    with pytest.raises(RoomExecutionControllerError) as binary:
        validate_candidate(candidate)
    assert binary.value.code == "execution_patch_unsupported_form"

    drifted = ExactPatchCandidate(**{**candidate.__dict__, "patch_sha256": "0" * 64})
    with pytest.raises(RoomExecutionControllerError) as digest:
        validate_candidate(drifted)
    assert digest.value.code == "execution_patch_digest_mismatch"


def test_stage_rejects_symlink_target_even_if_patch_is_text(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    os.symlink("README.md", root / "linked")
    _git(root, "add", "linked")
    _git(root, "commit", "-qm", "symlink")
    (root / "linked").unlink()
    (root / "linked").write_text("not a link\n", encoding="utf-8")
    patch = _git(root, "diff", "--", "linked").decode()
    (root / "linked").unlink()
    os.symlink("README.md", root / "linked")
    candidate = ExactPatchCandidate(
        candidate_id="cand-link",
        patch_text=patch,
        patch_sha256=f"sha256:{hashlib.sha256(patch.encode()).hexdigest()}",
        candidate_digest="sha256:" + "c" * 64,
        base_head=_git(root, "rev-parse", "HEAD").decode().strip(),
        allowed_files=("linked",),
        policy_revision=1,
        risk_policy_revision="room_execution_low_risk/v1",
    )

    with pytest.raises(RoomExecutionControllerError) as error:
        with stage_exact_patch(
            xmuse_root=tmp_path / "runtime-root",
            execution_root=root,
            run_id="run-link",
            candidate=candidate,
        ):
            pass

    assert error.value.code in {
        "execution_patch_symlink_rejected",
        "execution_patch_special_file_rejected",
    }
