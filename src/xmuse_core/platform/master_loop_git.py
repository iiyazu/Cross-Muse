"""Git and worktree helpers for the legacy Xmuse master loop."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("xmuse.master_loop.git")


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return "\n".join(
            part.rstrip() for part in (self.stdout, self.stderr) if part.strip()
        )


async def run_process(worktree: Path, *cmd: str) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=worktree,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    returncode = process.returncode
    if returncode is None:
        returncode = await process.wait()
    return ProcessResult(
        returncode=returncode,
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
    )


def current_head_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def get_worktree_diff(worktree: str | Path, base_ref: str | None) -> str:
    wt_path = Path(worktree)
    ref = base_ref or "HEAD~1"
    stat = subprocess.run(
        ["git", "diff", "--stat", ref],
        capture_output=True,
        text=True,
        cwd=wt_path,
    )
    diff = subprocess.run(
        ["git", "diff", ref],
        capture_output=True,
        text=True,
        cwd=wt_path,
    )
    stat_text = stat.stdout[:500] if stat.returncode == 0 else ""
    diff_text = diff.stdout[:3000] if diff.returncode == 0 else ""
    return f"{stat_text}\n\n{diff_text}".strip()


def clean_worktree_before_dispatch(worktree: str | Path) -> int:
    """Reset a dirty git worktree before dispatch and return dirty file count."""
    wt = Path(worktree)
    if not wt.exists() or str(wt) == ".":
        return 0
    if not (wt / ".git").exists() and not (wt / ".git").is_file():
        return 0
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=wt,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return 0
    dirty_count = len(result.stdout.strip().splitlines())
    subprocess.run(["git", "checkout", "--", "."], capture_output=True, cwd=wt)
    subprocess.run(["git", "clean", "-fd"], capture_output=True, cwd=wt)
    return dirty_count


async def auto_merge_worktree(
    *,
    task: Any,
    root: Path,
    merge_lock: Any,
) -> bool:
    """Merge worktree branch back to current branch after successful gate."""
    wt_path = Path(task.worktree)
    if not wt_path.exists() or str(wt_path) == ".":
        return True
    if not (wt_path / ".git").exists():
        return True
    branch = task.feature_id
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(wt_path),
        "rev-parse",
        "--abbrev-ref",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0:
        branch = stdout.decode().strip()

    proc = await asyncio.create_subprocess_exec(
        "git",
        "log",
        f"HEAD..{branch}",
        "--oneline",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=root,
    )
    stdout, _ = await proc.communicate()
    if not stdout.decode().strip():
        dirty_proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(wt_path),
            "status",
            "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        dirty_stdout, _ = await dirty_proc.communicate()
        if dirty_stdout.decode().strip():
            logger.warning(
                "Refusing auto-merge for %s: worktree has uncommitted changes",
                branch,
            )
            return False
        logger.info("No new commits on %s to merge", branch)
        return True

    proc = await asyncio.create_subprocess_exec(
        "git",
        "diff",
        "--shortstat",
        f"HEAD...{branch}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=root,
    )
    stat_out, _ = await proc.communicate()
    stat_text = stat_out.decode()
    insertions_match = re.search(r"(\d+)\s+insertion", stat_text)
    if insertions_match and int(insertions_match.group(1)) > 1000:
        logger.warning(
            "Refusing auto-merge for %s: %s insertions exceeds 1000 limit",
            branch,
            insertions_match.group(1),
        )
        return False

    async with merge_lock:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "merge",
            "--no-ff",
            branch,
            "-m",
            f"auto-merge: {task.feature_id} (lane done)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=root,
        )
        _, stderr = await proc.communicate()
    if proc.returncode == 0:
        logger.info("Auto-merged %s into main branch", branch)
        return True
    logger.warning("Auto-merge failed for %s: %s", branch, stderr.decode()[:500])
    return False
