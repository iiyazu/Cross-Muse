"""Startup for the hub: set up what the host gives it, fix what xmuse generated itself, refuse the rest.

`hub start` (and `hub start --unit NAME`, the systemd user unit that outlives the caller) runs this before it spawns
the hub:
- host_env(): the variables the hub needs from its host (WSL_DISTRO_NAME, WSL_INTEROP, PATH, HOME). A systemd unit
  inherits none of them, which is how the dev room's hub failed to find its distro.
- run(): doctor's checks, then the stale files xmuse generates are rewritten: the workspace files (`init`), and a
  member's own config (.mcp.json and hooks of a claude member, the server config of an opencode member) through the
  writer `agent add` uses. Nothing else is changed here.
- a FAIL that is left (a CLI a headless member needs, a missing dsh, ...) stops the start with its fix line.
"""
import glob
import os
from pathlib import Path

from . import config, db, doctor
from .init import WRITERS, init

HOST_KEYS = ("XMUSE_SHELL_POLICY", "XMUSE_WIN_HOME", "XMUSE_WSL_DISTRO", "XMUSE_REGISTRY_DIR")


def _newest_interop() -> str | None:
    socks = glob.glob("/run/WSL/*_interop")
    return max(socks, key=os.path.getmtime) if socks else None


def host_env(state: Path) -> dict[str, str]:
    """The environment a hub process needs from this host. Passed explicitly, so a unit gets it too."""
    env = {"XMUSE_STATE": str(state), "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    distro = os.environ.get("WSL_DISTRO_NAME") or os.environ.get("XMUSE_WSL_DISTRO")
    if distro:
        env["WSL_DISTRO_NAME"] = distro
    interop = os.environ.get("WSL_INTEROP") or _newest_interop()
    if interop:
        env["WSL_INTEROP"] = interop
    env.update({k: os.environ[k] for k in HOST_KEYS if k in os.environ})
    return env


def run(state: Path) -> tuple[list[doctor.Check], list[str]]:
    """The checks after the fixes, and what was rewritten (one line each)."""
    checks = doctor.run(state)
    fixed = _fix(state, checks)
    return (doctor.run(state), fixed) if fixed else (checks, fixed)


def _fix(state: Path, checks: list[doctor.Check]) -> list[str]:
    ws = Path(config.load(state)["workspace"])
    fixed = []
    if any(c.level != "ok" and c.fix.startswith("xmuse init") for c in checks):
        init(ws)
        fixed.append("workspace files regenerated (tools.json, skill, AGENTS.md section)")
    conn = db.connect(state / "hub.db")
    try:
        done = set()
        for c in checks:
            # a member directory that does not exist is a fact about the user's setup, not a stale file
            if c.level != "FAIL" or not c.name.startswith("agent ") or "does not exist" in c.detail:
                continue
            agent_id = c.name[len("agent "):]
            a = db.row(conn.execute("select * from agents where id=?", (agent_id,)))
            if a and a["vendor"] in ("claude", "opencode") and agent_id not in done:
                WRITERS[a["vendor"]](ws, a, state)
                done.add(agent_id)
                fixed.append(f"{c.name}: {a['vendor']} config rewritten")
    finally:
        conn.close()
    return fixed
