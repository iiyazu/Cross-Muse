"""Child processes on POSIX and Windows (D1: the hub runs natively on Windows as well as in WSL/Linux).

POSIX keeps the original semantics: every agent process starts in its own session (`start_new_session`) and is
stopped with a signal to its whole process group (`killpg`).

Windows has no process groups in that sense. Each child starts in a new process group without a console window
and is put into its own Job Object right after it starts; stopping it terminates the job, which takes every
process the child started with it (node, git, shells). `taskkill /T` is the fallback when no job could be
created. There is no graceful SIGINT for a console-less child, so "int" and "term" both end the tree.
"""
import functools
import os
import shutil
import signal
import subprocess
import sys

WINDOWS = os.name == "nt"
SIGNALS = {"kill": getattr(signal, "SIGKILL", signal.SIGTERM), "term": signal.SIGTERM, "int": signal.SIGINT}

_jobs: dict[int, int] = {}  # pid -> job handle (Windows)


def argv(binary) -> list[str]:
    """A configured program: a path or name (str), or a command prefix (list, e.g. [python, script.py]).

    On Windows a bare name is resolved through PATH and PATHEXT (`claude` may be claude.exe or claude.cmd), which
    CreateProcess alone does not do."""
    if isinstance(binary, (list, tuple)):
        return [str(x) for x in binary]
    b = str(binary)
    if WINDOWS and not os.path.dirname(b):
        b = shutil.which(b) or b
    if WINDOWS and b.lower().endswith(".py"):  # no shebangs on Windows
        return [sys.executable, b]
    return [b]


def popen(args, *, detach: bool = False, **kw) -> subprocess.Popen:
    """subprocess.Popen in a new session (POSIX) or process group + job object (Windows).

    detach (Windows): also try to break away from the caller's job, so that a hub started from a terminal or an
    app that kills its job on exit keeps running (falls back when the caller's job forbids breakaway)."""
    if not WINDOWS:
        return subprocess.Popen(args, start_new_session=True, **kw)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    p = None
    if detach:
        try:
            p = subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
        except OSError:
            p = None
    if p is None:
        p = subprocess.Popen(args, creationflags=flags, **kw)
    _adopt(p)
    return p


def kill_tree(p, how: str = "kill") -> None:
    """Stop a process started with popen() and everything it started. `p` is a Popen or a pid."""
    pid = p if isinstance(p, int) else p.pid
    if not WINDOWS:
        try:
            os.killpg(pid, SIGNALS[how])
        except (ProcessLookupError, PermissionError):
            pass
        return
    job = _jobs.pop(pid, None)
    if job is not None:
        _k32().TerminateJobObject(job, 1)
        _k32().CloseHandle(job)
        return
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)


def terminate(pid: int) -> None:
    """Ask one process to stop (SIGTERM on POSIX; on Windows this is TerminateProcess)."""
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    if not WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
    k = _k32()
    h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return k.GetLastError() == 5  # ERROR_ACCESS_DENIED: exists, not ours
    try:
        import ctypes
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


# ---- Windows job objects (ctypes, stdlib only) ---------------------------------------------------

@functools.cache
def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=False)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulong))
    return k


def _adopt(p: subprocess.Popen) -> None:
    try:
        k = _k32()
        for pid in [x for x in _jobs if not alive(x)]:  # finished children: release their job handles
            k.CloseHandle(_jobs.pop(pid))
        job = k.CreateJobObjectW(None, None)
        if not job:
            return
        if k.AssignProcessToJobObject(job, int(p._handle)):
            _jobs[p.pid] = job
        else:
            k.CloseHandle(job)
    except (OSError, AttributeError):  # no job: kill_tree falls back to taskkill /T
        pass
