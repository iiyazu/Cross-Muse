from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from xmuse_core.observability import log_event

logger = logging.getLogger(__name__)
MERGE_LOCK_TIMEOUT_S = 300.0
MERGE_LOCK_HEARTBEAT_TTL_S = 300.0
TARGET_DIRTY_RETRY_DELAY_S = 300.0


async def auto_merge(*, lane_id: str, lane: dict[str, Any], worktree: Path) -> bool:
    try:
        _clear_merge_failure(lane)
        if lane.get("integration_mode") == "noop":
            log_event(
                logger,
                logging.INFO,
                "lane_noop_integration_treated_as_applied",
                lane_id=lane_id,
            )
            return True

        branch = lane.get("branch")
        lane_worktree = lane.get("worktree")
        missing = [
            name
            for name, value in (("branch", branch), ("worktree", lane_worktree))
            if not value
        ]
        if missing:
            _record_merge_failure(
                lane,
                reason="merge_context_missing",
                detail=f"missing required integration metadata: {', '.join(missing)}",
            )
            log_event(
                logger,
                logging.WARNING,
                "merge_context_missing",
                lane_id=lane_id,
                missing=missing,
            )
            return False

        if not Path(str(lane_worktree)).exists():
            _record_merge_failure(
                lane,
                reason="merge_worktree_missing",
                detail=f"worktree path does not exist: {lane_worktree}",
            )
            log_event(
                logger,
                logging.WARNING,
                "merge_worktree_missing",
                lane_id=lane_id,
                worktree=str(lane_worktree),
            )
            return False

        branch_check = subprocess.run(
            ["git", "rev-parse", "--verify", str(branch)],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if branch_check.returncode != 0:
            _record_merge_failure(
                lane,
                reason="merge_branch_missing",
                detail=branch_check.stderr.strip() or f"branch not found: {branch}",
            )
            log_event(
                logger,
                logging.WARNING,
                "merge_branch_missing",
                lane_id=lane_id,
                branch=str(branch),
                stderr=branch_check.stderr,
            )
            return False

        lane_worktree_path = Path(str(lane_worktree))
        if not _commit_lane_worktree_if_dirty(
            lane_id=lane_id,
            lane=lane,
            lane_worktree=lane_worktree_path,
        ):
            return False

        target_branch = _target_branch_for_merge(lane, worktree)
        try:
            with _merge_lock(
                worktree,
                target_branch=target_branch,
                owner_id=f"lane:{lane_id}",
            ):
                current_target_head = _current_target_head(worktree, target_branch)
                if current_target_head is None:
                    _record_merge_failure(
                        lane,
                        reason="merge_target_head_unresolved",
                        detail=f"unable to resolve current target HEAD for {target_branch}",
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "merge_target_head_unresolved",
                        lane_id=lane_id,
                        target_branch=target_branch,
                    )
                    return False

                expected_base_head = lane.get("base_head_sha")
                if (
                    isinstance(expected_base_head, str)
                    and expected_base_head
                    and expected_base_head != current_target_head
                ):
                    lane["stale_against_current_target_head"] = True
                    lane["current_target_head"] = current_target_head
                    lane["stale_base_head_sha"] = expected_base_head
                    log_event(
                        logger,
                        logging.INFO,
                        "stale_target_head_merge_continuing",
                        lane_id=lane_id,
                        target_branch=target_branch,
                        expected_base_head=expected_base_head,
                        current_target_head=current_target_head,
                    )

                result = subprocess.run(
                    ["git", "checkout", target_branch],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    _record_merge_failure(
                        lane,
                        reason="checkout_target_failed",
                        detail=result.stderr.strip()
                        or f"unable to checkout target branch: {target_branch}",
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "checkout_target_failed",
                        lane_id=lane_id,
                        target_branch=target_branch,
                        stderr=result.stderr,
                    )
                    return False

                revalidated_target_head = _current_target_head(worktree, target_branch)
                if revalidated_target_head is None:
                    _record_merge_failure(
                        lane,
                        reason="merge_target_head_unresolved",
                        detail=(
                            "unable to revalidate current target HEAD for "
                            f"{target_branch} after checkout"
                        ),
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "merge_target_head_unresolved_after_checkout",
                        lane_id=lane_id,
                        target_branch=target_branch,
                    )
                    return False
                if revalidated_target_head != current_target_head:
                    lane["stale_against_current_target_head"] = True
                    lane["current_target_head"] = revalidated_target_head
                    _record_merge_failure(
                        lane,
                        reason="stale_target_head",
                        detail=(
                            "current target HEAD changed while merge lock was held: "
                            f"expected {current_target_head}, found {revalidated_target_head}"
                        ),
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "stale_target_head_changed_under_lock",
                        lane_id=lane_id,
                        target_branch=target_branch,
                        expected_target_head=current_target_head,
                        current_target_head=revalidated_target_head,
                    )
                    return False

                merge_branch = str(branch)
                dirty_conflict_paths = _target_dirty_conflicting_paths(
                    worktree,
                    target_head=revalidated_target_head,
                    merge_branch=merge_branch,
                )
                if dirty_conflict_paths is None:
                    _record_merge_failure(
                        lane,
                        reason="merge_target_dirty_check_failed",
                        detail="unable to inspect target worktree dirty/changed paths",
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "merge_target_dirty_check_failed",
                        lane_id=lane_id,
                        target_branch=target_branch,
                    )
                    return False
                if dirty_conflict_paths:
                    retry_after = time.time() + TARGET_DIRTY_RETRY_DELAY_S
                    lane["merge_retry_after_at"] = retry_after
                    lane["target_dirty_conflicting_paths"] = dirty_conflict_paths
                    _record_merge_failure(
                        lane,
                        reason="target_worktree_dirty_conflict",
                        detail=(
                            "target worktree has uncommitted changes that overlap "
                            "the lane merge:\n"
                            + "\n".join(dirty_conflict_paths)
                        ),
                        reworkable=False,
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "target_worktree_dirty_conflict",
                        lane_id=lane_id,
                        target_branch=target_branch,
                        dirty_conflicting_paths=dirty_conflict_paths,
                        retry_after=retry_after,
                    )
                    return False

                result = subprocess.run(
                    ["git", "merge", "--no-ff", merge_branch, "-m",
                     f"feat(xmuse): merge lane {lane_id}"],
                    cwd=worktree, capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    detail = _merge_failure_detail(result, worktree)
                    reworkable = _merge_failure_has_conflict_evidence(detail)
                    _record_merge_failure(
                        lane,
                        reason="merge_conflict_or_failed" if reworkable else "merge_failed",
                        detail=detail,
                        reworkable=reworkable,
                    )
                    log_event(
                        logger,
                        logging.WARNING,
                        "git_merge_failed",
                        lane_id=lane_id,
                        stderr=result.stderr,
                        stdout=result.stdout,
                    )
                    subprocess.run(["git", "merge", "--abort"],
                                   cwd=worktree, capture_output=True, timeout=5)
                    return False
        except TimeoutError as exc:
            _record_merge_failure(
                lane,
                reason="merge_lock_timeout",
                detail=str(exc),
            )
            log_event(
                logger,
                logging.WARNING,
                "merge_lock_timeout",
                lane_id=lane_id,
                target_branch=target_branch,
                detail=str(exc),
            )
            return False
        return True
    except Exception as exc:
        _record_merge_failure(
            lane,
            reason="auto_merge_error",
            detail=str(exc),
            reworkable=False,
        )
        log_event(
            logger,
            logging.ERROR,
            "auto_merge_error",
            lane_id=lane_id,
            error=str(exc),
            exc_info=True,
        )
        return False


def _clear_merge_failure(lane: dict[str, Any]) -> None:
    lane.pop("merge_failure_reason", None)
    lane.pop("merge_failure_detail", None)
    lane.pop("merge_failure_reworkable", None)
    lane.pop("merge_retry_after_at", None)
    lane.pop("stale_against_current_target_head", None)
    lane.pop("current_target_head", None)
    lane.pop("stale_base_head_sha", None)
    lane.pop("target_dirty_conflicting_paths", None)


def _record_merge_failure(
    lane: dict[str, Any],
    *,
    reason: str,
    detail: str,
    reworkable: bool = False,
) -> None:
    lane["merge_failure_reason"] = reason
    lane["merge_failure_detail"] = detail
    lane["merge_failure_reworkable"] = reworkable


def _merge_failure_detail(result: subprocess.CompletedProcess[str], worktree: Path) -> str:
    parts = []
    if result.stdout.strip():
        parts.append("git merge stdout:\n" + _compact_detail(result.stdout.strip()))
    if result.stderr.strip():
        parts.append("git merge stderr:\n" + _compact_detail(result.stderr.strip()))
    conflicts = _unmerged_paths(worktree)
    if conflicts:
        parts.append("unmerged paths:\n" + "\n".join(conflicts))
    return "\n\n".join(parts) or "git merge failed"


def _merge_failure_has_conflict_evidence(detail: str) -> bool:
    return "CONFLICT" in detail or "unmerged paths:" in detail


def _compact_detail(value: str, *, max_chars: int = 4000) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _unmerged_paths(worktree: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _target_dirty_conflicting_paths(
    repo: Path,
    *,
    target_head: str,
    merge_branch: str,
) -> list[str] | None:
    dirty_paths = _dirty_worktree_paths(repo)
    changed_paths = _merge_changed_paths(
        repo,
        target_head=target_head,
        merge_branch=merge_branch,
    )
    if dirty_paths is None or changed_paths is None:
        return None
    return sorted(dirty_paths & changed_paths)


def _dirty_worktree_paths(repo: Path) -> set[str] | None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if not path:
            continue
        if " -> " in path:
            before, after = path.split(" -> ", 1)
            if before:
                paths.add(before)
            if after:
                paths.add(after)
            continue
        paths.add(path)
    return paths


def _merge_changed_paths(
    repo: Path,
    *,
    target_head: str,
    merge_branch: str,
) -> set[str] | None:
    merge_base = subprocess.run(
        ["git", "merge-base", target_head, merge_branch],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if merge_base.returncode != 0:
        return set()
    base_sha = merge_base.stdout.strip()
    if not base_sha:
        return set()
    result = subprocess.run(
        ["git", "diff", "--name-only", base_sha, merge_branch],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _commit_lane_worktree_if_dirty(
    *,
    lane_id: str,
    lane: dict[str, Any],
    lane_worktree: Path,
) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=lane_worktree,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if status.returncode != 0:
        _record_merge_failure(
            lane,
            reason="merge_worktree_status_failed",
            detail=status.stderr.strip() or "unable to inspect lane worktree status",
        )
        return False
    if not status.stdout.strip():
        return True

    add_result = subprocess.run(
        ["git", "add", "-A"],
        cwd=lane_worktree,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if add_result.returncode != 0:
        _record_merge_failure(
            lane,
            reason="merge_worktree_commit_failed",
            detail=add_result.stderr.strip() or "unable to stage lane worktree changes",
        )
        return False

    insertions = _staged_insertion_count(lane_worktree)
    if insertions is None:
        _record_merge_failure(
            lane,
            reason="merge_worktree_diff_failed",
            detail="unable to inspect staged lane worktree diff",
        )
        return False
    if insertions > 1000:
        _record_merge_failure(
            lane,
            reason="merge_diff_too_large",
            detail=f"lane diff has {insertions} insertions",
        )
        log_event(
            logger,
            logging.WARNING,
            "lane_diff_too_large",
            lane_id=lane_id,
            insertions=insertions,
        )
        return False

    commit_result = subprocess.run(
        ["git", "commit", "-m", f"feat(xmuse): apply lane {lane_id}"],
        cwd=lane_worktree,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if commit_result.returncode != 0:
        _record_merge_failure(
            lane,
            reason="merge_worktree_commit_failed",
            detail=commit_result.stderr.strip() or "unable to commit lane worktree changes",
        )
        return False
    lane["merge_worktree_commit"] = commit_result.stdout.strip()
    return True


def _staged_insertion_count(lane_worktree: Path) -> int | None:
    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--numstat", "HEAD"],
        cwd=lane_worktree,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if diff_check.returncode != 0:
        return None
    insertions = 0
    for line in diff_check.stdout.splitlines():
        added, _deleted, *_path = line.split("\t")
        if added == "-":
            continue
        insertions += int(added)
    return insertions


def _target_branch_for_merge(lane: dict[str, Any], repo: Path) -> str:
    configured = lane.get("target_branch")
    if configured:
        return str(configured)
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    current = result.stdout.strip() if result.returncode == 0 else ""
    return current or "main"


def _current_target_head(repo: Path, target_branch: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", target_branch],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@contextmanager
def _merge_lock(
    repo: Path,
    *,
    target_branch: str | None = None,
    owner_id: str | None = None,
    now: float | None = None,
    timeout_s: float = MERGE_LOCK_TIMEOUT_S,
    heartbeat_ttl_s: float = MERGE_LOCK_HEARTBEAT_TTL_S,
    poll_interval_s: float = 0.05,
):
    lock_root = _merge_lock_root(repo)
    lock_filename = _merge_lock_filename(target_branch=target_branch)
    lock_path = lock_root / lock_filename
    metadata_path = lock_root / f"{lock_filename}.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    holder = _merge_lock_owner_description(
                        _read_merge_lock_metadata(metadata_path)
                    )
                    raise TimeoutError(
                        "timed out waiting for merge lock"
                        f" for {target_branch or repo.name}; held by {holder}"
                    ) from None
                time.sleep(poll_interval_s)

        lock_owner_id = owner_id or f"pid:{os.getpid()}"
        heartbeat_at = time.time() if now is None else now
        existing = _read_merge_lock_metadata(metadata_path)
        metadata = {
            "owner_id": lock_owner_id,
            "owner_pid": os.getpid(),
            "heartbeat_at": heartbeat_at,
            "expires_at": heartbeat_at + heartbeat_ttl_s,
        }
        if target_branch is not None:
            metadata["target_branch"] = target_branch
        if _merge_lock_metadata_is_stale(existing, now=heartbeat_at):
            reclaimed_from_owner_id = existing.get("owner_id")
            if (
                isinstance(reclaimed_from_owner_id, str)
                and reclaimed_from_owner_id
                and reclaimed_from_owner_id != lock_owner_id
            ):
                metadata["reclaimed_from_owner_id"] = reclaimed_from_owner_id
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        try:
            yield
        finally:
            persisted = _read_merge_lock_metadata(metadata_path)
            if (
                isinstance(persisted, dict)
                and persisted.get("owner_id") == lock_owner_id
                and persisted.get("owner_pid") == os.getpid()
            ):
                metadata_path.unlink(missing_ok=True)
            fcntl.flock(handle, fcntl.LOCK_UN)


def _merge_lock_path(repo: Path, *, target_branch: str | None = None) -> Path:
    return _merge_lock_root(repo) / _merge_lock_filename(target_branch=target_branch)


def _merge_lock_metadata_path(repo: Path, *, target_branch: str | None = None) -> Path:
    return _merge_lock_root(repo) / f"{_merge_lock_filename(target_branch=target_branch)}.json"


def _merge_lock_root(repo: Path) -> Path:
    common_dir = _git_common_dir(repo)
    if common_dir is None:
        return repo
    return common_dir / "xmuse" / "merge-locks"


def _git_common_dir(repo: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    raw_common_dir = result.stdout.strip()
    if not raw_common_dir:
        return None
    common_dir = Path(raw_common_dir)
    if common_dir.is_absolute():
        return common_dir
    return (repo / common_dir).resolve()


def _merge_lock_filename(*, target_branch: str | None = None) -> str:
    if not target_branch:
        return ".xmuse_merge.lock"
    target_parts = target_branch.split("/")
    branch_prefix = [".xmuse_merge.targets"]
    branch_suffix = f"{target_parts[-1]}.lock"
    return str(Path(*branch_prefix, *target_parts[:-1], branch_suffix))


def _read_merge_lock_metadata(metadata_path: Path) -> dict[str, Any] | None:
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_lock_metadata_is_stale(
    metadata: dict[str, Any] | None,
    *,
    now: float,
) -> bool:
    if not isinstance(metadata, dict):
        return False
    expires_at = metadata.get("expires_at")
    if (
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and expires_at <= now
    ):
        return True
    owner_pid = metadata.get("owner_pid")
    return (
        isinstance(owner_pid, int)
        and not isinstance(owner_pid, bool)
        and not _pid_exists(owner_pid)
    )


def _merge_lock_owner_description(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        return "unknown"
    owner_id = metadata.get("owner_id")
    owner_pid = metadata.get("owner_pid")
    expires_at = metadata.get("expires_at")
    parts = []
    if owner_id:
        parts.append(str(owner_id))
    if isinstance(owner_pid, int) and not isinstance(owner_pid, bool):
        parts.append(f"pid={owner_pid}")
    if isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool):
        parts.append(f"expires_at={expires_at}")
    return ", ".join(parts) or "unknown"


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
