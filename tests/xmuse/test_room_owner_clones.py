"""Host-owned per-owner clones with mirror-based patch export."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from xmuse_core.chat.room_owner_clones import (
    OwnerCloneError,
    OwnerCloneManager,
)

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _init_source(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / "a.txt").write_text("hello\n")
    _git("add", "a.txt", cwd=path)
    _git("commit", "-m", "initial", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path).strip()


def _owner_commit(clone: Path, filename: str, content: str | bytes, message: str) -> None:
    if isinstance(content, bytes):
        (clone / filename).write_bytes(content)
    else:
        (clone / filename).write_text(content)
    _git("add", filename, cwd=clone)
    _git(
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test",
        "commit",
        "-m",
        message,
        cwd=clone,
    )


def test_create_ok(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    calls: list[Path] = []

    def _prepare(path: Path) -> None:
        calls.append(path)

    clone = manager.create(source, "alice", prepare=_prepare)
    assert clone.owner_id == "alice"
    assert clone.branch == "owner/alice"
    assert clone.base_commit == head
    assert clone.path.is_dir()
    assert (clone.path / ".git").is_dir()
    # Branch checked out (read the file directly; never run git in the clone).
    assert (clone.path / ".git" / "HEAD").read_text().strip() == "ref: refs/heads/owner/alice"
    # No origin remote remains.
    config_text = (clone.path / ".git" / "config").read_text()
    assert '[remote "origin"]' not in config_text
    # No shared object store.
    assert not (clone.path / ".git" / "objects" / "info" / "alternates").exists()
    assert calls == [clone.path]


def test_create_duplicate_and_invalid(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    manager.create(source, "alice")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.create(source, "alice")
    assert exc_info.value.code == "owner_clone_exists"
    for bad in ("", "Alice", "a b", "../evil", "a" * 65, "-"):
        with pytest.raises(OwnerCloneError) as exc_info:
            manager.create(source, bad)
        assert exc_info.value.code == "owner_id_invalid"


def test_create_invalid_base_ref(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.create(source, "bob", base_ref="no-such-ref")
    assert exc_info.value.code == "owner_base_ref_invalid"


def test_export_patch_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    _owner_commit(clone.path, "b.txt", "new file\n", "add b")
    patch = manager.export_patch("alice", base_commit=head)
    assert patch.owner_id == "alice"
    assert patch.base_commit == head
    assert patch.head_commit != head
    assert "b.txt" in patch.changed_paths
    assert "new file" in patch.unified_diff


def test_board_dir_is_excluded_and_never_exported(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    assert (clone.path / ".xmuse").is_dir()
    assert "/.xmuse/" in (clone.path / ".git" / "info" / "exclude").read_text()
    # A plain `git add -A` leaves the board view out of the owner's commit.
    (clone.path / ".xmuse" / "charter.md").write_text("charter\n")
    (clone.path / "b.txt").write_text("work\n")
    _git("add", "-A", cwd=clone.path)
    _git("-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-m", "w", cwd=clone.path)
    patch = manager.export_patch("alice", base_commit=head)
    assert patch.changed_paths == ("b.txt",)
    # Force-adding it anyway makes the export fail closed.
    _git("add", "-f", ".xmuse/charter.md", cwd=clone.path)
    _git("-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-m", "f", cwd=clone.path)
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head)
    assert exc_info.value.code == "owner_patch_reserved_path"


def test_export_patch_empty(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    manager.create(source, "alice")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head)
    assert exc_info.value.code == "owner_patch_empty"


def test_export_patch_too_large(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    _owner_commit(clone.path, "b.txt", "new file\n", "add b")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head, max_bytes=10)
    assert exc_info.value.code == "owner_patch_too_large"


def test_export_patch_too_many_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    _owner_commit(clone.path, "b.txt", "one\n", "add b")
    _owner_commit(clone.path, "c.txt", "two\n", "add c")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head, max_files=1)
    assert exc_info.value.code == "owner_patch_too_many_files"


def test_export_patch_binary(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    _owner_commit(clone.path, "blob.bin", b"\x00\x01\x02binary\n", "add binary")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head)
    assert exc_info.value.code == "owner_patch_binary"


def test_export_patch_missing_clone(tmp_path: Path) -> None:
    manager = OwnerCloneManager(tmp_path / "clones")
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("ghost", base_commit="0" * 40)
    assert exc_info.value.code == "owner_clone_missing"


def test_remove(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    _owner_commit(clone.path, "b.txt", "new\n", "add b")
    assert manager.export_patch("alice", base_commit=head).changed_paths == ("b.txt",)
    manager.remove("alice")
    assert not clone.path.exists()
    with pytest.raises(OwnerCloneError) as exc_info:
        manager.export_patch("alice", base_commit=head)
    assert exc_info.value.code == "owner_clone_missing"
    # Removing again is tolerated.
    manager.remove("alice")


def test_export_ignores_malicious_clone_config(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = _init_source(source)
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.create(source, "alice")
    # Commit the attributes and content first with a clean config.
    (clone.path / ".gitattributes").write_text("*.txt diff=evil\n")
    _owner_commit(clone.path, ".gitattributes", "*.txt diff=evil\n", "attributes")
    _owner_commit(clone.path, "evil.txt", "innocent\n", "add text")
    # Now the "owner" poisons its own git config: the host must never execute it.
    sentinel = tmp_path / "pwned"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit 0\n")
    script.chmod(0o755)
    with (clone.path / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n[core]\n"
            f"\tfsmonitor = {script}\n"
            "[diff]\n"
            f"\texternal = {script}\n"
            '[diff "evil"]\n'
            f"\ttextconv = {script}\n"
            # The mirror fetch runs upload-pack against the clone; git honors this
            # hook only from system/global config, never from the repository.
            "[uploadpack]\n"
            f"\tpackObjectsHook = {script}\n"
        )
    assert not sentinel.exists()
    patch = manager.export_patch("alice", base_commit=head)
    assert "evil.txt" in patch.changed_paths
    assert not sentinel.exists()
