"""Host-owned per-owner git clones with mirror-based patch export.

An owner agent works inside its own clone, whose ``.git`` directory is
agent-writable.  The host therefore never runs git inside the clone after
creation: its config could set ``core.fsmonitor``, ``diff.external``, a textconv
driver, or hooks that execute arbitrary code on the host.  Patch export fetches
the owner branch into a host-owned bare mirror and computes the diff there with
external diff drivers, textconv filters, and color disabled.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

OWNER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Read-only board view (charter + contracts) mounted inside every owner clone.
OWNER_BOARD_DIR_NAME = ".xmuse"
_OWNER_BRANCH_PREFIX = "owner/"
_MIRROR_DIR_NAME = ".mirror.git"
_META_DIR_NAME = ".meta"


class OwnerCloneError(RuntimeError):
    """Stable owner-clone failure carrying a reason code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class OwnerClone:
    owner_id: str
    path: Path
    branch: str
    base_commit: str


@dataclass(frozen=True)
class OwnerPatch:
    owner_id: str
    base_commit: str
    head_commit: str
    unified_diff: str
    changed_paths: tuple[str, ...]


class OwnerCloneManager:
    """Create, diff, and remove per-owner clones rooted at ``clones_root``."""

    def __init__(self, clones_root: Path, *, git: str = "git", timeout_s: float = 120.0) -> None:
        self._clones_root = clones_root
        self._git = git
        self._timeout_s = timeout_s

    def ensure(
        self,
        source_repo: Path,
        owner_id: str,
        *,
        base_ref: str = "HEAD",
        prepare: Callable[[Path], None] | None = None,
    ) -> OwnerClone:
        """Return the existing clone for ``owner_id`` or create it.

        Reuse never runs git inside the existing clone (its config is
        owner-controlled): the branch and base commit come from host-owned
        metadata written by :meth:`create`.
        """

        if OWNER_ID_RE.fullmatch(owner_id) is None:
            raise OwnerCloneError("owner_id_invalid")
        target = self._clones_root / owner_id
        if target.exists() or target.is_symlink():
            return self._read_metadata_clone(owner_id)
        return self.create(source_repo, owner_id, base_ref=base_ref, prepare=prepare)

    def create(
        self,
        source_repo: Path,
        owner_id: str,
        *,
        base_ref: str = "HEAD",
        prepare: Callable[[Path], None] | None = None,
    ) -> OwnerClone:
        if OWNER_ID_RE.fullmatch(owner_id) is None:
            raise OwnerCloneError("owner_id_invalid")
        self._clones_root.mkdir(parents=True, exist_ok=True)
        target = self._clones_root / owner_id
        if target.exists() or target.is_symlink():
            raise OwnerCloneError("owner_clone_exists")
        branch = f"{_OWNER_BRANCH_PREFIX}{owner_id}"
        base_commit = self._rev_parse_in(
            source_repo, f"{base_ref}^{{commit}}", error_code="owner_base_ref_invalid"
        )
        try:
            self._run_git(
                ["clone", "--no-hardlinks", "--no-checkout", str(source_repo), str(target)],
                cwd=None,
            )
            self._run_git(["checkout", "-b", branch, base_commit], cwd=target)
            self._run_git(["remote", "remove", "origin"], cwd=target)
            alternates = target / ".git" / "objects" / "info" / "alternates"
            if alternates.exists():
                raise OwnerCloneError("owner_clone_shares_objects")
            # The board view is mounted read-only at ``.xmuse``; keep it out of
            # the owner's commits (export also rejects the path outright).
            exclude = target / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(f"\n/{OWNER_BOARD_DIR_NAME}/\n")
            (target / OWNER_BOARD_DIR_NAME).mkdir(exist_ok=True)
        except OwnerCloneError as exc:
            shutil.rmtree(target, ignore_errors=True)
            if exc.code in {"owner_clone_shares_objects", "owner_base_ref_invalid"}:
                raise
            raise OwnerCloneError("owner_clone_create_failed", str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise OwnerCloneError(
                "owner_clone_create_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        if prepare is not None:
            try:
                prepare(target)
            except Exception as exc:
                shutil.rmtree(target, ignore_errors=True)
                self._remove_metadata(owner_id)
                if isinstance(exc, OwnerCloneError):
                    raise
                raise OwnerCloneError(
                    "owner_clone_prepare_failed", f"{type(exc).__name__}: {exc}"
                ) from exc
        self._write_metadata_clone(owner_id, branch=branch, base_commit=base_commit)
        return OwnerClone(owner_id=owner_id, path=target, branch=branch, base_commit=base_commit)

    def read_base_commit(self, owner_id: str) -> str:
        """Return the host-owned base commit for ``owner_id`` without running git.

        The branch and base commit come from host-owned metadata written at
        creation; the clone itself is owner-controlled and is never inspected
        here.
        """

        if OWNER_ID_RE.fullmatch(owner_id) is None:
            raise OwnerCloneError("owner_id_invalid")
        return self._read_metadata_clone(owner_id).base_commit

    def export_patch(
        self, owner_id: str, *, base_commit: str, max_bytes: int = 200_000, max_files: int = 32
    ) -> OwnerPatch:
        if OWNER_ID_RE.fullmatch(owner_id) is None:
            raise OwnerCloneError("owner_id_invalid")
        clone_path = self._clones_root / owner_id
        if not self._is_inside_root(clone_path) or not clone_path.is_dir():
            raise OwnerCloneError("owner_clone_missing")
        mirror = self._clones_root / _MIRROR_DIR_NAME
        if not mirror.is_dir():
            try:
                self._clones_root.mkdir(parents=True, exist_ok=True)
                self._run_git(["init", "--bare", str(mirror)], cwd=None)
            except OwnerCloneError as exc:
                raise OwnerCloneError("owner_patch_fetch_failed", str(exc)) from exc
        ref = f"refs/owners/{owner_id}"
        branch = f"{_OWNER_BRANCH_PREFIX}{owner_id}"
        try:
            self._run_git(
                [
                    "fetch",
                    "--no-tags",
                    str(clone_path),
                    f"+refs/heads/{branch}:{ref}",
                ],
                cwd=mirror,
                allow_file_protocol=True,
            )
        except OwnerCloneError as exc:
            raise OwnerCloneError("owner_patch_fetch_failed", str(exc)) from exc
        try:
            head_commit = self._rev_parse_in(mirror, f"{ref}^{{commit}}")
            unified_diff = self._run_git(
                [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    base_commit,
                    ref,
                ],
                cwd=mirror,
            )
            name_only = self._run_git(
                [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    "--name-only",
                    base_commit,
                    ref,
                ],
                cwd=mirror,
            )
            numstat = self._run_git(
                [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    "--numstat",
                    base_commit,
                    ref,
                ],
                cwd=mirror,
            )
        except OwnerCloneError as exc:
            raise OwnerCloneError("owner_patch_fetch_failed", str(exc)) from exc
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] == "-" and parts[1] == "-":
                raise OwnerCloneError("owner_patch_binary")
        changed_paths = tuple(line for line in name_only.splitlines() if line.strip())
        if not changed_paths or not unified_diff.strip():
            raise OwnerCloneError("owner_patch_empty")
        if any(
            path == OWNER_BOARD_DIR_NAME or path.startswith(f"{OWNER_BOARD_DIR_NAME}/")
            for path in changed_paths
        ):
            raise OwnerCloneError("owner_patch_reserved_path")
        if len(changed_paths) > max_files:
            raise OwnerCloneError("owner_patch_too_many_files")
        if len(unified_diff.encode("utf-8")) > max_bytes:
            raise OwnerCloneError("owner_patch_too_large")
        return OwnerPatch(
            owner_id=owner_id,
            base_commit=base_commit,
            head_commit=head_commit,
            unified_diff=unified_diff,
            changed_paths=changed_paths,
        )

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is ``descendant`` or one of its ancestors, in the mirror.

        Both commits must already be in the host mirror (a previous
        :meth:`export_patch` fetched them). A commit the mirror does not hold is
        not an ancestor.
        """

        mirror = self._clones_root / _MIRROR_DIR_NAME
        if not mirror.is_dir():
            return False
        result = self._git_process(
            ["merge-base", "--is-ancestor", ancestor, descendant], cwd=mirror
        )
        return result.returncode == 0

    def remove(self, owner_id: str) -> None:
        if OWNER_ID_RE.fullmatch(owner_id) is None:
            raise OwnerCloneError("owner_id_invalid")
        target = self._clones_root / owner_id
        if not self._is_inside_root(target):
            raise OwnerCloneError("owner_id_invalid")
        if target.is_symlink() or target.is_file():
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        self._remove_metadata(owner_id)
        mirror = self._clones_root / _MIRROR_DIR_NAME
        if mirror.is_dir():
            try:
                self._run_git(["update-ref", "-d", f"refs/owners/{owner_id}"], cwd=mirror)
            except OwnerCloneError:
                pass

    def _meta_path(self, owner_id: str) -> Path:
        return self._clones_root / _META_DIR_NAME / f"{owner_id}.json"

    def _write_metadata_clone(self, owner_id: str, *, branch: str, base_commit: str) -> None:
        meta_dir = self._clones_root / _META_DIR_NAME
        try:
            meta_dir.mkdir(parents=True, exist_ok=True)
            self._meta_path(owner_id).write_text(
                json.dumps(
                    {"owner_id": owner_id, "branch": branch, "base_commit": base_commit},
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            shutil.rmtree(self._clones_root / owner_id, ignore_errors=True)
            self._remove_metadata(owner_id)
            raise OwnerCloneError("owner_clone_create_failed", str(exc)) from exc

    def _read_metadata_clone(self, owner_id: str) -> OwnerClone:
        try:
            payload = json.loads(self._meta_path(owner_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OwnerCloneError("owner_clone_metadata_invalid", str(exc)) from exc
        if not isinstance(payload, dict):
            raise OwnerCloneError("owner_clone_metadata_invalid")
        branch = payload.get("branch")
        base_commit = payload.get("base_commit")
        expected_branch = f"{_OWNER_BRANCH_PREFIX}{owner_id}"
        if (
            payload.get("owner_id") != owner_id
            or branch != expected_branch
            or not isinstance(base_commit, str)
            or not base_commit.strip()
        ):
            raise OwnerCloneError("owner_clone_metadata_invalid")
        return OwnerClone(
            owner_id=owner_id,
            path=self._clones_root / owner_id,
            branch=branch,
            base_commit=base_commit,
        )

    def _remove_metadata(self, owner_id: str) -> None:
        try:
            self._meta_path(owner_id).unlink(missing_ok=True)
        except OSError:
            pass

    def _is_inside_root(self, path: Path) -> bool:
        root = self._clones_root.resolve()
        resolved = path.resolve()
        return resolved != root and resolved.is_relative_to(root)

    def _rev_parse_in(
        self, cwd: Path, rev: str, *, error_code: str = "owner_patch_fetch_failed"
    ) -> str:
        try:
            output = self._run_git(["rev-parse", "--verify", rev], cwd=cwd)
        except OwnerCloneError as exc:
            raise OwnerCloneError(error_code, str(exc)) from exc
        commit = output.strip()
        if not commit:
            raise OwnerCloneError(error_code)
        return commit

    def _run_git(
        self, args: list[str], *, cwd: Path | None, allow_file_protocol: bool = False
    ) -> str:
        result = self._git_process(args, cwd=cwd, allow_file_protocol=allow_file_protocol)
        if result.returncode != 0:
            raise OwnerCloneError(
                "owner_git_failed",
                (result.stderr or result.stdout or f"exit {result.returncode}").strip(),
            )
        return result.stdout

    def _git_process(
        self, args: list[str], *, cwd: Path | None, allow_file_protocol: bool = False
    ) -> subprocess.CompletedProcess[str]:
        argv: list[str] = [
            self._git,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
        ]
        if allow_file_protocol:
            argv.extend(["-c", "protocol.file.allow=always"])
        if cwd is not None:
            argv.extend(["-C", str(cwd)])
        argv.extend(args)
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
        }
        try:
            result = subprocess.run(
                argv,
                cwd=None,
                env=env,
                timeout=self._timeout_s,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OwnerCloneError("owner_git_timeout", str(exc)) from exc
        except OSError as exc:
            raise OwnerCloneError("owner_git_failed", f"{type(exc).__name__}: {exc}") from exc
        return result
