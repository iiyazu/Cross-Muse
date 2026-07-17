from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import room_execution_profile_acceptance as acceptance


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _git_output(root: Path, *args: str) -> str:
    return (
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        .stdout.decode("ascii")
        .strip()
    )


def _commit_file(root: Path, value: str) -> tuple[str, str]:
    (root / "tracked.txt").write_text(value, encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-qm", value.strip())
    return _git_output(root, "rev-parse", "HEAD"), _git_output(root, "rev-parse", "HEAD^{tree}")


def _repository(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")


def test_working_snapshot_is_byte_copied_and_committed_clean(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = tmp_path / "snapshot"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Test")
    tracked = source / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-qm", "base")
    pending = source / "pending.txt"
    pending.write_text("pending\n", encoding="utf-8")

    acceptance._copy_working_snapshot(source, snapshot)

    assert (snapshot / "tracked.txt").read_bytes() == tracked.read_bytes()
    assert (snapshot / "pending.txt").read_bytes() == pending.read_bytes()
    assert (snapshot / "tracked.txt").stat().st_ino != tracked.stat().st_ino
    status = subprocess.run(
        ["git", "-C", str(snapshot), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout
    assert status == b""


def test_frozen_commit_clone_rejects_tree_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _repository(source)
    commit, _tree = _commit_file(source, "base\n")
    _other_commit, other_tree = _commit_file(source, "other\n")

    try:
        acceptance._clone_frozen_commit(
            source,
            tmp_path / "clone",
            frozen_commit=commit,
            frozen_tree=other_tree,
        )
    except acceptance.AcceptanceError as exc:
        assert exc.code == "acceptance_frozen_tree_mismatch"
    else:
        raise AssertionError("mismatched frozen tree was accepted")


def test_frozen_commit_clone_ignores_dirty_source_working_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    clone = tmp_path / "clone"
    _repository(source)
    commit, tree = _commit_file(source, "committed\n")
    (source / "tracked.txt").write_text("dirty source bytes\n", encoding="utf-8")
    (source / "untracked.txt").write_text("untracked source bytes\n", encoding="utf-8")

    acceptance._clone_frozen_commit(source, clone, frozen_commit=commit, frozen_tree=tree)

    assert (clone / "tracked.txt").read_text(encoding="utf-8") == "committed\n"
    assert not (clone / "untracked.txt").exists()
    assert _git_output(clone, "rev-parse", "HEAD") == commit
    assert _git_output(clone, "rev-parse", "HEAD^{tree}") == tree
    assert _git_output(clone, "status", "--porcelain=v1") == ""
    assert _git_output(source, "rev-parse", "HEAD") == commit
    assert _git_output(source, "rev-parse", "HEAD^{tree}") == tree
    assert _git_output(source, "status", "--porcelain=v1") == "M tracked.txt\n?? untracked.txt"


def test_frozen_commit_clone_checks_out_non_head_commit_detached(tmp_path: Path) -> None:
    source = tmp_path / "source"
    clone = tmp_path / "clone"
    _repository(source)
    frozen_commit, frozen_tree = _commit_file(source, "frozen\n")
    head, _head_tree = _commit_file(source, "new head\n")

    acceptance._clone_frozen_commit(
        source,
        clone,
        frozen_commit=frozen_commit,
        frozen_tree=frozen_tree,
    )

    assert _git_output(source, "rev-parse", "HEAD") == head
    assert _git_output(clone, "rev-parse", "HEAD") == frozen_commit
    detached = subprocess.run(
        ["git", "-C", str(clone), "symbolic-ref", "-q", "HEAD"],
        check=False,
        capture_output=True,
    )
    assert detached.returncode == 1
    assert detached.stdout == b""
    assert (clone / "tracked.txt").read_text(encoding="utf-8") == "frozen\n"


def test_frozen_commit_clone_ignores_global_git_configuration(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    clone = tmp_path / "clone"
    _repository(source)
    commit, tree = _commit_file(source, "base\n")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        f'[url "file:///definitely-not-the-source/"]\n\tinsteadOf = {source}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "0")

    acceptance._clone_frozen_commit(source, clone, frozen_commit=commit, frozen_tree=tree)

    assert _git_output(clone, "rev-parse", "HEAD") == commit


def test_frozen_commit_clone_requires_full_lowercase_object_ids(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _repository(source)
    commit, tree = _commit_file(source, "base\n")

    for invalid_commit in (commit[:12], commit.upper()):
        try:
            acceptance._clone_frozen_commit(
                source,
                tmp_path / f"clone-{len(invalid_commit)}-{invalid_commit[:1]}",
                frozen_commit=invalid_commit,
                frozen_tree=tree,
            )
        except acceptance.AcceptanceError as exc:
            assert exc.code == "acceptance_frozen_commit_invalid"
        else:
            raise AssertionError("invalid frozen commit was accepted")


def test_main_fails_closed_without_traceback_or_exception_text(monkeypatch, capsys) -> None:
    class Parser:
        @staticmethod
        def parse_args():
            return SimpleNamespace()

    monkeypatch.setattr(acceptance, "_parser", lambda: Parser())
    monkeypatch.setattr(
        acceptance,
        "run_acceptance",
        lambda _args: (_ for _ in ()).throw(RuntimeError("/secret/workspace token-value")),
    )

    assert acceptance.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "reason_code": "acceptance_internal_error",
        "schema_version": acceptance.RESULT_SCHEMA,
        "status": "failed",
    }


def test_memoryos_fixture_digest_is_pinned_and_unknown_repo_blocks_cleanly(
    tmp_path: Path,
) -> None:
    fixture = (
        Path(acceptance.__file__).resolve().parent / "fixtures" / "memoryos-python-uv-7e85e85.patch"
    ).read_bytes()
    assert acceptance._digest(fixture) == acceptance.MEMORYOS_FIXTURE_SHA256

    unknown = tmp_path / "unknown"
    unknown.mkdir()
    _git(unknown, "init", "-q")
    _git(unknown, "config", "user.email", "test@example.invalid")
    _git(unknown, "config", "user.name", "Test")
    (unknown / "README.md").write_text("unknown\n", encoding="utf-8")
    _git(unknown, "add", "README.md")
    _git(unknown, "commit", "-qm", "base")

    result = acceptance._run_expected_blocked_scenario(unknown)

    assert result["status"] == "expected_blocked"
    assert result["changed_file_count"] == 0
    status = subprocess.run(
        ["git", "-C", str(unknown), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout
    assert status == b""
