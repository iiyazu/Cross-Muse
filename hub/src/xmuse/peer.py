"""Who is on the other end of a loopback connection (Linux /proc), for the human-only admin actions (audit B2-1).

The admin token is a file the hub's own user can read, and so can every agent running as that user. Holding it is
therefore not proof that a human is acting. For the actions that grant power (approve a held command, confirm or
reject an alignment proposal, resume a paused agent) the hub also requires that the calling process
  1. can be found (a loopback TCP peer in /proc; callers from the Windows side cannot), and
  2. has a controlling terminal (hub-run agents are started in their own session, without one), and
  3. does not descend from a process the hub knows as an agent (running turns, Claude TUI leases, the
     OpenCode server), so a shell tool inside a TUI agent is refused too.
This raises the bar against an agent using the token by accident or on a peer's suggestion. It is not a boundary
against an agent that sets out to defeat it (a detached process given a new pty passes all three); that needs a
separate OS user for agents, which is the user's call.
"""
import os
from pathlib import Path


def _inode(client_port: int, server_port: int) -> str | None:
    """The socket inode of the client end: its local port is client_port, its remote port server_port."""
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) > 9 and int(f[1].rsplit(":", 1)[1], 16) == client_port \
                    and int(f[2].rsplit(":", 1)[1], 16) == server_port:
                return f[9]
    return None


def pid_of(client_port: int, server_port: int) -> int | None:
    inode = _inode(client_port, server_port)
    if not inode or inode == "0":
        return None
    target = f"socket:[{inode}]"
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            for fd in (p / "fd").iterdir():
                if os.readlink(fd) == target:
                    return int(p.name)
        except OSError:  # gone, or not ours
            continue
    return None


def _stat(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return raw[raw.rindex(")") + 2:].split()  # fields after "pid (comm) "; [0]=state [1]=ppid [4]=tty_nr


def ancestors(pid: int) -> list[int]:
    out, seen = [], set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        out.append(pid)
        st = _stat(pid)
        if st is None:
            break
        pid = int(st[1])
    return out


def has_ctty(pid: int) -> bool:
    st = _stat(pid)
    return bool(st) and int(st[4]) != 0


def human_check(client_port: int, server_port: int, agent_pids: set[int]) -> str | None:
    """None when the caller looks like a human at a terminal; otherwise the reason it does not."""
    pid = pid_of(client_port, server_port)
    if pid is None:
        return "the calling process cannot be identified (only a local terminal may do this)"
    if not has_ctty(pid):
        return f"the calling process (pid {pid}) has no controlling terminal"
    hit = agent_pids.intersection(ancestors(pid))
    if hit:
        return f"the calling process (pid {pid}) runs inside agent process {min(hit)}"
    return None
