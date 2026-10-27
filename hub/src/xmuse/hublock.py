"""Single-instance lock for the hub: one hub process per state dir.

The lock is an exclusive non-blocking OS lock on `<state>/hub.lock`, held by the open file object for the life of
the hub. The OS drops it when the process dies, so a crash never leaves a stale lock. The file itself is never
deleted (unlinking a locked file would let a second hub lock a fresh inode). Release = close the file.

POSIX: flock on the whole file; the holder pid is written into it. Windows: msvcrt byte-range lock on byte 0; a
locked range cannot be read by others there, so the pid is stored from offset 1 on.
"""
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

NAME = "hub.lock"
PID_OFFSET = 1  # byte 0 is the Windows lock byte


class HubLocked(Exception):
    def __init__(self, state: Path, pid: int | None):
        self.state, self.pid = state, pid
        super().__init__(f"another hub already runs for {state}" + (f" (pid {pid})" if pid else ""))


def _read_pid(f) -> int | None:
    try:
        f.seek(PID_OFFSET)
        return int(f.read(32).decode("ascii", "ignore").strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _try_lock(f) -> bool:
    try:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def acquire(state: Path):
    """The open lock file (keep it referenced; close it to release), or raise HubLocked."""
    state.mkdir(parents=True, exist_ok=True)
    f = open(state / NAME, "a+b")  # not inheritable by default (PEP 446)
    if not _try_lock(f):
        pid = None
        for _ in range(20):  # the holder may be between locking and writing its pid
            pid = _read_pid(f)
            if pid:
                break
            time.sleep(0.05)
        f.close()
        raise HubLocked(state, pid)
    f.seek(0)
    f.truncate()
    f.write(b" " + str(os.getpid()).encode("ascii") + b"\n")  # byte 0 stays a blank for the Windows lock byte
    f.flush()
    return f


def holder(state: Path) -> int | None:
    """Pid of the hub holding the lock, or None when it is free (probe: lock and release at once)."""
    try:
        f = acquire(state)
    except HubLocked as e:
        return e.pid or -1  # held, pid unreadable (a hub that is between lock and pid write)
    f.close()
    return None
