"""`xmuse doctor`: check the install and the workspace, one line per item, with the command that fixes it. Read-only.

Levels: ok, warn (works, but something optional is missing or stale), FAIL (xmuse will not work as configured).
Exit status 1 when anything FAILs.
"""
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config, db, host

PY_MIN = (3, 12)
NODE_MIN = 20
REPO = config.REPO


@dataclass
class Check:
    level: str  # ok | warn | FAIL
    name: str
    detail: str
    fix: str = ""


def _run(cmd: list[str], timeout: float = 10) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# ---- install ------------------------------------------------------------------------------------

def python_env() -> list[Check]:
    v = sys.version_info[:3]
    out = [Check("ok" if v[:2] >= PY_MIN else "FAIL", "python", f"{sys.executable} {'.'.join(map(str, v))}",
                 "" if v[:2] >= PY_MIN else f"uv sync --project {REPO / 'hub'} --python 3.12")]
    missing = []
    for mod in ("zstandard",):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    out.append(Check("FAIL" if missing else "ok", "python deps", f"missing: {', '.join(missing)}" if missing
                     else "hub dependencies importable", f"uv sync --project {REPO / 'hub'}" if missing else ""))
    return out


def node_env() -> list[Check]:
    node = shutil.which("node")
    if not node:
        return [Check("FAIL", "node", "not on PATH (the MCP shim runs on node)", f"install node >= {NODE_MIN}")]
    v = _run([node, "--version"]) or "?"
    try:
        major = int(v.lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    out = [Check("ok" if major >= NODE_MIN else "FAIL", "node", f"{node} {v}",
                 "" if major >= NODE_MIN else f"install node >= {NODE_MIN}")]
    shim = REPO / "shim"
    lock, installed = shim / "package-lock.json", shim / "node_modules" / ".package-lock.json"
    if not (shim / "node_modules" / "@modelcontextprotocol" / "sdk").is_dir():
        out.append(Check("FAIL", "shim deps", "shim/node_modules is missing", f"cd {shim} && npm ci"))
    elif lock.exists() and installed.exists() and installed.stat().st_mtime < lock.stat().st_mtime:
        out.append(Check("warn", "shim deps", "package-lock.json is newer than node_modules", f"cd {shim} && npm ci"))
    else:
        out.append(Check("ok", "shim deps", "shim/node_modules present"))
    return out


def dsh_candidate(cfg: dict) -> Path:
    """The dsh binary path before checking it exists (shared with agents.scan). May raise host.HostError."""
    return Path(cfg.get("dsh_exe") or host.win_home() / "AppData/Local/Programs/DeepSeek Harness"
                / "DeepSeek Harness.exe")


def cli_paths(cfg: dict) -> dict[str, str | None]:
    """CLI paths per vendor (shared with agents.scan): lookup only, no checks."""
    try:
        dsh_exe = dsh_candidate(cfg)
        dsh = str(dsh_exe) if dsh_exe.exists() else None
    except host.HostError:
        dsh = None
    oc = shutil.which("opencode") or (str(Path.home() / ".opencode/bin/opencode")
                                      if (Path.home() / ".opencode/bin/opencode").exists() else None)
    return {"claude": cfg.get("claude_bin") or shutil.which("claude"), "opencode": oc, "dsh": dsh}


def vendor_clis(vendors: set[str], cfg: dict) -> list[Check]:
    """Each vendor CLI: FAIL when a configured agent needs it, warn when it is merely absent."""
    out = []
    paths = cli_paths(cfg)
    for name, how in (("claude", "install Claude Code (https://docs.anthropic.com/claude-code)"),
                      ("opencode", "install OpenCode (https://opencode.ai)")):
        found = paths[name]
        if found:
            out.append(Check("ok", f"{name} cli", found))
        else:
            out.append(Check("FAIL" if name in vendors else "warn", f"{name} cli", "not found", how))
    if "dsh" in vendors or cfg.get("dsh_exe"):
        if paths["dsh"] is not None:
            out.append(Check("ok", "dsh", paths["dsh"], ""))
        else:
            try:
                exe = str(dsh_candidate(cfg))
            except host.HostError as e:
                out.append(Check("FAIL", "dsh", str(e), "set XMUSE_WIN_HOME or dsh_exe"))
            else:
                out.append(Check("FAIL", "dsh", exe,
                                 "install DeepSeek Harness on Windows, or set dsh_exe in the hub config.json"))
    return out


def wsl() -> list[Check]:
    if host.WINDOWS:  # Windows-native hub: no distro to find, the home is this user's
        return [Check("ok", "host", "Windows-native hub (no WSL translation)"),
                Check("ok", "windows home", str(host.win_home()))]
    out = []
    try:
        out.append(Check("ok", "wsl distro", host.distro()))
    except host.HostError as e:
        out.append(Check("warn", "wsl distro", str(e), "only needed for Windows-side agents (desktop Claude, dsh)"))
    try:
        out.append(Check("ok", "windows home", str(host.win_home())))
    except host.HostError as e:
        out.append(Check("warn", "windows home", str(e), "only needed for dsh"))
    return out


# ---- workspace ----------------------------------------------------------------------------------

def _same(path: Path, text: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == text


def workspace(state: Path) -> list[Check]:
    from .init import SKILL_DIRS, agents_section, skill_text
    from .tools import tools_for
    cfg = config.load(state)
    ws = Path(cfg["workspace"])
    out = [Check("ok", "state dir", str(state))]
    fix_init = f"xmuse init {ws}"
    # hub
    hub = state / "hub.json"
    if not hub.exists():
        out.append(Check("warn", "hub", "not running", f"xmuse --ws {ws} hub start"))
    else:
        h = json.loads(hub.read_text(encoding="utf-8"))
        from .proc import alive as _alive
        alive = _alive(h["pid"])
        out.append(Check("ok" if alive else "FAIL", "hub", f"pid {h['pid']} port {h['port']}" if alive else
                         f"hub.json names pid {h['pid']}, which is not running (stale)",
                         "" if alive else f"xmuse --ws {ws} hub start  # replaces the stale hub.json"))
    # files generated by init: current with this checkout?
    tools = state / "tools.json"
    info = "" if config.info_on(cfg) else " (information layer off)"
    out.append(Check("ok" if tools.exists() and json.loads(tools.read_text(encoding="utf-8")) == tools_for(cfg) else "warn",
                     "tools.json", ("matches this checkout" + info) if tools.exists() else "missing", fix_init))
    skill = skill_text(cfg)
    stale = [d for d in SKILL_DIRS if not _same(ws / d / "xmuse-collab" / "SKILL.md", skill)]
    out.append(Check("warn" if stale else "ok", "skill", f"stale or missing in {', '.join(stale)}" if stale
                     else "xmuse-collab skill current", fix_init if stale else ""))
    section = agents_section(cfg)
    agents_md = (ws / "AGENTS.md").read_text(encoding="utf-8") if (ws / "AGENTS.md").exists() else ""
    out.append(Check("ok" if section.strip() in agents_md else "warn", "AGENTS.md",
                     "xmuse section current" if section.strip() in agents_md else "xmuse section missing or stale",
                     "" if section.strip() in agents_md else fix_init))
    # per agent
    conn = db.connect(state / "hub.db")
    agents = db.rows(conn.execute("select * from agents order by id"))
    if not agents:
        out.append(Check("warn", "agents", "none yet", f"xmuse --ws {ws} agent add <id> --vendor claude|opencode|dsh"))
    else:
        out.append(_instances(ws, agents))
    for a in agents:
        out += _agent_files(ws, state, a)
    if any(db.settings(a).get("foreground") for a in agents):
        try:
            out.append(Check("ok", "dsh bundle config.state", _bundle_state(state)))
        except host.HostError as e:
            out.append(Check("warn", "dsh bundle config.state", str(e)))
    return out


def _bundle_state(state: Path) -> str:
    from .adapters.base import to_win
    return to_win(state)


def _agent_files(ws: Path, state: Path, a: dict) -> list[Check]:
    fix = f"xmuse --ws {ws} agent add {a['id']} --vendor {a['vendor']}" + (
        " --desktop" if db.polled(a) else "") + (
        f" --cwd {db.settings(a)['cwd']}" if a["vendor"] == "claude" and db.settings(a).get("cwd") else "") + (
        f" --effort {db.settings(a)['effort']}" if a["vendor"] == "claude" and db.settings(a).get("effort") else "")
    if a["vendor"] == "claude":
        d = db.workdir(a, ws)  # the member's own directory (agent add --cwd), else the workspace root
        mcp = d / ".mcp.json"
        if not d.is_dir():
            return [Check("FAIL", f"agent {a['id']}", f"member directory {d} does not exist", fix)]
        try:
            srv = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]["xmuse"]
        except (OSError, ValueError, KeyError):
            return [Check("FAIL", f"agent {a['id']}", f"{mcp} has no xmuse server", fix)]
        flat = " ".join(_strings(srv))  # not json.dumps: it doubles the backslashes of Windows paths
        problems = [p for p, bad in ((f"not this agent ({a['id']})", f"XMUSE_AGENT={a['id']}" not in flat
                                      and srv.get("env", {}).get("XMUSE_AGENT") != a["id"]),
                                     ("points at another state dir", str(state) not in flat),
                                     ("shim path is not this checkout's", str(config.SHIM) not in flat)) if bad]
        if not (d / ".claude" / "settings.json").exists():
            problems.append(".claude/settings.json missing (hooks)")
        where = f" in {d}" if d != ws else ""
        return [Check("FAIL" if problems else "ok", f"agent {a['id']}",
                      "; ".join(problems) if problems else f"claude: .mcp.json and hooks current{where}",
                      fix if problems else "")]
    # adapters import lazily: doctor must still run when a dependency they need (zstandard) is missing
    if a["vendor"] == "opencode":
        from .adapters.opencode import instance_dir
        inst = instance_dir(state, a["id"]) / "opencode.json"
        try:
            env = json.loads(inst.read_text(encoding="utf-8"))["mcp"]["servers"]["xmuse"]["environment"]
        except (OSError, ValueError, KeyError, TypeError):
            env = None
        problems = [p for p, bad in ((f"{inst} missing or has no xmuse server", env is None),
                                     (f"instance config names {env and env.get('XMUSE_AGENT')}",
                                      env is not None and env.get("XMUSE_AGENT") != a["id"]),
                                     ("instance config points at another state dir",
                                      env is not None and env.get("XMUSE_STATE") != str(state)),
                                     ("workspace opencode.json missing", not (ws / "opencode.json").exists()),
                                     ("workspace opencode.json carries an agent identity (shared by every instance)",
                                      "XMUSE_AGENT" in _read(ws / "opencode.json"))) if bad]
        return [Check("FAIL" if problems else "ok", f"agent {a['id']}", "; ".join(problems) if problems else
                      f"opencode: own server config {inst}", fix if problems else "")]
    if a["vendor"] == "dsh" and not db.polled(a):
        try:
            from .adapters.dsh import hooks_owner
        except ImportError as e:
            return [Check("FAIL", f"agent {a['id']}", f"dsh adapter unusable: {e}", "pip install -e hub")]
        owner = hooks_owner(ws)
        note = "desktop presence hooks" if owner == a["id"] else \
            f"headless only (desktop presence hooks belong to {owner})" if owner else "no desktop presence hooks"
        return [Check("ok", f"agent {a['id']}", f"dsh: {note}")]
    return [Check("ok", f"agent {a['id']}", f"{a['vendor']}{' (foreground)' if db.polled(a) else ''}")]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _strings(o) -> list[str]:
    """Every string inside a JSON value (keys included)."""
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [s for k, v in o.items() for s in (k, *_strings(v))]
    if isinstance(o, list):
        return [s for v in o for s in _strings(v)]
    return []


def _instances(ws: Path, agents: list[dict]) -> Check:
    by: dict[str, list[str]] = {}
    dirs: dict[Path, list[str]] = {}
    for a in agents:
        by.setdefault(a["vendor"], []).append(a["id"])
        if a["vendor"] == "claude":
            dirs.setdefault(db.workdir(a, ws).resolve(), []).append(a["id"])
    shared = {d: ids for d, ids in dirs.items() if len(ids) > 1}
    return Check("FAIL" if shared else "ok", "instances",
                 ", ".join(f"{v} x{len(ids)} ({', '.join(ids)})" for v, ids in sorted(by.items())),
                 "one claude agent per directory (.mcp.json carries one identity): " + "; ".join(
                     f"{', '.join(ids)} share {d}" for d, ids in shared.items())
                 + f"; give each its own: xmuse --ws {ws} agent add <id> --vendor claude --cwd <dir>" if shared else "")


def run(state: Path | None) -> list[Check]:
    checks = python_env() + node_env() + wsl()
    vendors, cfg = set(), {}
    if state is not None:
        cfg = config.load(state)
        vendors = {r[0] for r in db.connect(state / "hub.db").execute("select distinct vendor from agents")}
    checks += vendor_clis(vendors, cfg)
    if state is None:
        checks.append(Check("warn", "workspace", "no xmuse workspace here (no .xmuse.json above the cwd)",
                            "xmuse init <workspace>"))
    else:
        checks += workspace(state)
    return checks


def report(checks: list[Check], out=sys.stdout) -> int:
    for c in checks:
        print(f"{c.level:4} {c.name}: {c.detail}", file=out)
        if c.fix and c.level != "ok":
            print(f"     fix: {c.fix}", file=out)
    bad = sum(c.level == "FAIL" for c in checks)
    print(f"\n{bad} failed, {sum(c.level == 'warn' for c in checks)} warnings", file=out)
    return 1 if bad else 0


def find_state(ws: Path | None) -> Path | None:
    try:
        return config.find_state(ws)
    except (SystemExit, OSError, ValueError, KeyError):  # no workspace, or a broken .xmuse.json pointer
        return None

