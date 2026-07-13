from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import room_execution_profile_acceptance as acceptance


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


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
