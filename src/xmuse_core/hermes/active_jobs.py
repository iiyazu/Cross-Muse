from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from xmuse_core.hermes.json_artifacts import atomic_write_json, read_json


def git_status_short(path: str | Path) -> str | None:
    repo = Path(path)
    if not repo.exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def pid_alive_default(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def write_active_job(
    loop_root: str | Path,
    *,
    pid: int,
    phase_id: str | None,
    prompt_file: str,
    attempt: int,
    output_path: str,
    idle_timeout_seconds: int,
    started_at: str | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    timestamp = started_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {
        "pid": int(pid),
        "phase_id": phase_id,
        "prompt_file": prompt_file,
        "attempt": int(attempt),
        "output_path": output_path,
        "idle_timeout_seconds": int(idle_timeout_seconds),
        "started_at": timestamp,
        "status": "running",
    }
    path = loop / "active_job.json"
    atomic_write_json(path, payload)
    return {"ok": True, "path": str(path), **payload}


def classify_active_job(
    loop_root: str | Path,
    *,
    now: float | None = None,
    pid_alive: Callable[[int], bool] | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    job_path = loop / "active_job.json"
    if not job_path.exists():
        return {"ok": True, "state": "missing", "reason": "missing active_job.json"}

    try:
        job = read_json(job_path)
    except Exception as exc:
        return {"ok": False, "state": "invalid", "reason": f"invalid active_job.json: {exc}"}

    if not isinstance(job, dict):
        return {"ok": False, "state": "invalid", "reason": "active_job root is not an object"}
    if job.get("status") and job.get("status") != "running":
        return {
            "ok": True,
            "state": str(job.get("status")),
            "reason": "job is not running",
            **job,
        }

    pid = int(job.get("pid", 0) or 0)
    alive_checker = pid_alive_default if pid_alive is None else pid_alive
    alive = alive_checker(pid) if pid else False
    if not alive:
        return {
            "ok": True,
            "state": "exited_or_missing",
            "reason": "pid is not alive",
            **job,
        }

    output_path = loop / str(job.get("output_path", "codex_output.log"))
    current_time = time.time() if now is None else now
    if not output_path.exists():
        return {
            "ok": True,
            "state": "running",
            "reason": "output file missing but pid alive",
            "output_age_seconds": None,
            **job,
        }

    output_age = int(max(0, current_time - output_path.stat().st_mtime))
    timeout = int(job.get("idle_timeout_seconds", 0) or 0)
    if timeout > 0 and output_age > timeout:
        return {
            "ok": False,
            "state": "stalled",
            "reason": "output stale beyond idle timeout",
            "output_age_seconds": output_age,
            **job,
        }
    return {
        "ok": True,
        "state": "running",
        "reason": "pid alive and output fresh",
        "output_age_seconds": output_age,
        **job,
    }


def complete_active_job(
    loop_root: str | Path,
    *,
    exit_code: int,
    status: str,
    completed_at: str | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    job_path = loop / "active_job.json"
    job: dict[str, Any] = {}
    if job_path.exists():
        loaded = read_json(job_path)
        if isinstance(loaded, dict):
            job = loaded
    timestamp = completed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    job.update(
        {
            "status": status,
            "exit_code": int(exit_code),
            "completed_at": timestamp,
        }
    )
    atomic_write_json(job_path, job)
    return {"ok": True, "path": str(job_path), **job}


_git_status_short = git_status_short
_pid_alive_default = pid_alive_default
