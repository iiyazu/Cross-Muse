from __future__ import annotations

from pathlib import Path

from xmuse_core.platform import master_loop_git


def test_process_result_output_joins_non_empty_streams() -> None:
    result = master_loop_git.ProcessResult(
        returncode=1,
        stdout="stdout\n",
        stderr="stderr\n",
    )

    assert result.output == "stdout\nstderr"


def test_worktree_diff_uses_base_ref_and_bounds_output(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[list[str], Path]] = []

    class Result:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, *, capture_output, text, cwd):  # type: ignore[no-untyped-def]
        calls.append((list(cmd), Path(cwd)))
        if cmd[:2] == ["git", "diff"] and "--stat" in cmd:
            return Result(0, "stat")
        return Result(0, "diff")

    monkeypatch.setattr(master_loop_git.subprocess, "run", fake_run)

    assert master_loop_git.get_worktree_diff(tmp_path, "base") == "stat\n\ndiff"
    assert calls == [
        (["git", "diff", "--stat", "base"], tmp_path),
        (["git", "diff", "base"], tmp_path),
    ]


def test_clean_worktree_before_dispatch_resets_dirty_git_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, *, capture_output, cwd, text=False):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if cmd == ["git", "status", "--porcelain"]:
            return Result(stdout=" M file.py\n")
        return Result()

    monkeypatch.setattr(master_loop_git.subprocess, "run", fake_run)

    master_loop_git.clean_worktree_before_dispatch(tmp_path)

    assert calls == [
        ["git", "status", "--porcelain"],
        ["git", "checkout", "--", "."],
        ["git", "clean", "-fd"],
    ]
