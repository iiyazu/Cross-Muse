"""`xmuse init` and `xmuse agent add`: hub state outside the workspace, project-level configs inside it.

Nothing global is touched. Generated files that should not be committed are listed in
.git/info/exclude (not in the project's .gitignore).
"""
import json
import os
import re
import subprocess
from pathlib import Path

from . import auth, config, db
from .adapters import agy, claude, dsh, opencode
from .auth import digest
from .tools import tools_for

WRITERS = {"claude": claude.write_config, "opencode": opencode.write_config, "dsh": dsh.DshDriver.write_config,
           "agy": agy.AgyDriver.write_config}
# Headless Claude coding profile: edits in the workspace plus test/inspection commands. Anything else
# (push, rm, network) is denied in -p mode and reported as permission_denied.
CLAUDE_ALLOW = ["Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)", "Bash(pytest:*)",
                "Bash(python3 -m unittest:*)", "Bash(python -m unittest:*)", "Bash(git diff:*)",
                "Bash(git status:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)",
                "Bash(git commit:*)", "Bash(ls:*)"]
# Python projects also get the interpreter (user 10-09): unittest plus free edits already run arbitrary code,
# so this adds no real risk and lets a reviewer run its own probe scripts. Per workspace: config.json claude_allow.
PYTHON_ALLOW = ["Bash(python3:*)", "Bash(python:*)"]
GENERATED = [".xmuse.json", ".mcp.json", ".claude/", ".opencode/", ".agents/", "opencode.json", ".dsh/", ".xmuse-tmp/"]
SKILL_DIRS = [".claude/skills", ".opencode/skills", ".agents/skills"]  # .agents/skills: dsh


def _token(state: Path, who: str) -> str:
    """A JWT for member `who` (or "human": the admin token), written to tokens/ (auth.issue)."""
    return auth.issue(state, who, "admin" if who == config.HUMAN else "member")


def _git_common_dir(ws: Path) -> Path | None:
    """The repository's shared git dir. In a linked worktree `.git` is a file and info/exclude lives under the
    common dir (git ignores <worktree gitdir>/info/exclude)."""
    if not (ws / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ws, capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out and out.returncode == 0 and out.stdout.strip():
        return (ws / out.stdout.strip()).resolve()
    if (ws / ".git").is_dir():
        return ws / ".git"
    gitdir = (ws / (ws / ".git").read_text(encoding="utf-8").split("gitdir:", 1)[-1].strip()).resolve()  # no git binary
    common = gitdir / "commondir"
    return (gitdir / common.read_text(encoding="utf-8").strip()).resolve() if common.exists() else gitdir


def _exclude(ws: Path, paths: list[str]) -> None:
    common = _git_common_dir(ws)
    if common is None:
        return
    ex = common / "info" / "exclude"
    ex.parent.mkdir(parents=True, exist_ok=True)
    have = ex.read_text(encoding="utf-8").splitlines() if ex.exists() else []
    ex.write_text("\n".join(have + [p for p in paths if p not in have]) + "\n", encoding="utf-8")


_INFO = re.compile(r"^<!-- info:(on|off|end) -->\n", re.M)


def render(text: str, info: bool) -> str:
    """Drop the template blocks for the other information-layer mode (T14): `<!-- info:on -->` ... and
    `<!-- info:off -->` ... up to the next marker; the marker lines themselves never reach the agent."""
    out, keep = [], True
    pos = 0
    for m in _INFO.finditer(text):
        if keep:
            out.append(text[pos:m.start()])
        keep = m[1] == "end" or (m[1] == "on") == info
        pos = m.end()
    if keep:
        out.append(text[pos:])
    return "".join(out)


def skill_text(cfg: dict) -> str:
    return render((config.SKILL / "SKILL.md").read_text(encoding="utf-8"), config.info_on(cfg))


def agents_section(cfg: dict) -> str:
    return render((config.TEMPLATES / "AGENTS.xmuse.md").read_text(encoding="utf-8"), config.info_on(cfg))


def write_prompts(ws: Path, state: Path, cfg: dict) -> None:
    """What agents are told and offered, for the workspace's current config: tools.json (read by the shim), the
    skill copies and the AGENTS.md section. Rewritten by `xmuse init` and on every hub start, so a run that turns the
    information layer off never offers what the hub would refuse."""
    (state / "tools.json").write_text(json.dumps(tools_for(cfg), indent=1), encoding="utf-8")
    skill = skill_text(cfg)
    for d in SKILL_DIRS:
        dst = ws / d / "xmuse-collab"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "SKILL.md").write_text(skill, encoding="utf-8")
    section = agents_section(cfg)
    agents_md = ws / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    if "<!-- xmuse:begin" in text:
        text = text[:text.index("<!-- xmuse:begin")] + section + text[text.index("<!-- xmuse:end -->") + 18:].lstrip("\n")
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + section
    agents_md.write_text(text, encoding="utf-8")


def _claude_md(d: Path) -> None:
    claude_md = d / "CLAUDE.md"  # Claude Code reads CLAUDE.md; import AGENTS.md instead of copying it
    if not claude_md.exists():
        claude_md.write_text("@AGENTS.md\n", encoding="utf-8")
    elif "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
        claude_md.write_text(claude_md.read_text(encoding="utf-8").rstrip() + "\n\n@AGENTS.md\n", encoding="utf-8")


def sync_member_dir(ws: Path, d: Path, state: Path, cfg: dict) -> None:
    """A Claude member working in its own git worktree outside the workspace gets what a worktree lacks (the generated
    files are untracked): .xmuse.json (the CLI and the agent's tools find the state through it), AGENTS.md and the
    skill, as the plan-split-integrate preset copies them. A member directory inside the workspace inherits them from
    the workspace root (CLAUDE.md and .xmuse.json are found upward) and gets nothing."""
    ws, d = ws.resolve(), d.resolve()
    if d == ws or d.is_relative_to(ws):
        return
    (d / ".xmuse.json").write_text(json.dumps({"state": str(state)}) + "\n", encoding="utf-8")
    write_prompts(d, state, cfg)
    _claude_md(d)
    _exclude(d, GENERATED)


def sync_member_dirs(ws: Path, state: Path, cfg: dict) -> None:
    """Hub start: refresh the member worktrees' prompts for the current config (see write_prompts)."""
    conn = db.connect(state / "hub.db")
    try:
        agents = db.rows(conn.execute("select * from agents where vendor='claude'"))
    finally:
        conn.close()  # the hub starts in tests by the hundred: do not leave a descriptor per start
    for a in agents:
        c = db.settings(a).get("cwd")
        if c and Path(c).is_dir():
            sync_member_dir(ws, Path(c), state, cfg)


def init(ws: Path) -> Path:
    ws = ws.resolve()
    if config.is_home(ws):
        raise SystemExit(f"{ws} is a home folder: its .claude/ is your own Claude Code configuration. "
                         "Open the room in a project folder instead.")
    state = config.state_dir_for(ws)
    for d in ("tokens", "logs", "runs"):
        (state / d).mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    db.init(state / "hub.db").close()
    cfg = state / "config.json"
    if not cfg.exists():
        python = any((ws / f).exists() for f in ("pyproject.toml", "setup.py", "requirements.txt")) or \
            any(ws.glob("*.py")) or any(ws.glob("*/*.py"))
        cfg.write_text(json.dumps({"workspace": str(ws),
                                   "claude_allow": CLAUDE_ALLOW + (PYTHON_ALLOW if python else [])}, indent=2), encoding="utf-8")
    if not (state / "tokens" / "_admin").exists():
        _token(state, config.HUMAN)
    (ws / ".xmuse.json").write_text(json.dumps({"state": str(state)}) + "\n", encoding="utf-8")
    write_prompts(ws, state, config.load(state))
    _claude_md(ws)
    _exclude(ws, GENERATED)
    return state


def _dsh_ws_ok(ws) -> bool:
    """Any /mnt/<drive>/ workspace maps to its DRIVE-colon form; native WSL paths do not. On a Windows-native hub the
    workspace is a Windows path already; only a UNC path (\\\\wsl.localhost\\...) is refused."""
    if os.name == "nt":
        return not str(ws).startswith("\\\\")
    return re.match(r"/mnt/[a-zA-Z]/", str(ws)) is not None


def _member_cwd(ws: Path, raw: str) -> Path | None:
    """--cwd of a Claude member. The directory must exist and be either inside the workspace, or the root of a git
    worktree of the workspace's repository (same git common dir); a relative path is taken from the current
    directory. The workspace root itself is the default and is stored as no cwd."""
    d = Path(raw).expanduser().resolve()
    if not d.is_dir():
        raise SystemExit(f"--cwd {d}: not an existing directory (create it, or: git -C {ws} worktree add {d})")
    ws = ws.resolve()
    if d == ws:
        return None
    if d.is_relative_to(ws):
        return d
    common, mine = _git_common_dir(ws), _git_common_dir(d)
    if mine is None or common is None or mine != common:
        raise SystemExit(f"--cwd {d}: must be inside the workspace {ws} or the root of a git worktree of its "
                         f"repository (git -C {ws} worktree add {d})")
    return d


def add_agent(state: Path, agent_id: str, vendor: str, model: str | None = None, role: str = "",
              settings: dict | None = None, description: str | None = None) -> dict:
    """description: what the member is responsible for (peers see it; None keeps a re-added member's)."""
    if vendor not in WRITERS:
        raise SystemExit(f"vendor must be one of: {', '.join(WRITERS)}")
    if not agent_id.replace("-", "").isalnum() or agent_id in (config.HUMAN, config.HUB):
        raise SystemExit("agent id: letters, digits and '-', not 'human' or 'hub'")
    if (settings or {}).get("desktop") and vendor != "claude":
        raise SystemExit("--desktop is only for --vendor claude or --vendor dsh")
    if (settings or {}).get("foreground") and vendor != "dsh":
        raise SystemExit("foreground mode is only for --vendor dsh")
    cfg = config.load(state)
    ws = Path(cfg["workspace"])
    settings = dict(settings or {})
    if "cwd" in settings and vendor != "claude":
        raise SystemExit("--cwd is only for --vendor claude (a member directory holding its own .mcp.json)")
    if settings.get("effort") and vendor != "claude":
        print(f"--effort is only passed to claude; ignored for {vendor} agent {agent_id}")
    if vendor != "claude":
        settings.pop("effort", None)
    elif settings.get("effort") is not None and settings["effort"] not in claude.EFFORTS:
        raise SystemExit(f"--effort must be one of: {', '.join(claude.EFFORTS)}")
    if vendor == "claude":
        member = _member_cwd(ws, settings["cwd"]) if settings.get("cwd") else None
        settings.pop("cwd", None)
        settings.update({"cwd": str(member)} if member else {})
    conn = db.connect(state / "hub.db")
    old = db.row(conn.execute("select * from agents where id=?", (agent_id,)))
    if old and old["vendor"] != vendor:
        raise SystemExit(f"agent {agent_id} exists with vendor {old['vendor']}")
    if vendor == "claude":  # .mcp.json carries one identity: one Claude member per directory (opencode and dsh: T12)
        here = claude.config_dir(ws, {"settings": json.dumps(settings)}).resolve()
        for o in db.rows(conn.execute("select * from agents where vendor='claude' and id!=?", (agent_id,))):
            if claude.config_dir(ws, o).resolve() == here:
                raise SystemExit(
                    f"workspace already has a claude agent in {here}: {o['id']} (its .mcp.json carries one identity "
                    f"per directory). Give {agent_id} its own directory: xmuse agent add {agent_id} --vendor claude "
                    f"--cwd <dir>, with <dir> inside the workspace or a git worktree of it "
                    f"(git -C {ws} worktree add <dir>)")
    if vendor == "dsh" and not _dsh_ws_ok(ws):  # dsh cannot write through the wsl.localhost UNC form
        raise SystemExit(
            "dsh needs the workspace on a Windows drive (under /mnt/<drive>/, e.g. /mnt/c/), not " + str(ws) + ": "
            "dsh runs as a Windows app and its sandbox cannot write through the wsl.localhost UNC form "
            "(probe 2026-10-10: ENOTSUP on file writes); move the workspace under /mnt/c/ and retry")
    s = {"allowed_tools": cfg.get("claude_allow", CLAUDE_ALLOW)} if vendor == "claude" else {}
    s.update(settings)
    with db.tx(conn):
        if old:  # re-add: new settings, same token and history
            m = model or old["model"]
            conn.execute("update agents set model=?, family=?, role=?, settings=?, description=? where id=?",
                         (m, config.family(vendor, m), role or old["role"], json.dumps(s),
                          old["description"] if description is None else description, agent_id))
        else:
            tok = _token(state, agent_id)
            m = model or config.MODELS[vendor]
            conn.execute("insert into agents(id, vendor, model, family, role, settings, token_digest, created_at,"
                         " description) values(?,?,?,?,?,?,?,?,?)",
                         (agent_id, vendor, m, config.family(vendor, m), role, json.dumps(s), digest(tok), db.now(),
                          description or ""))
    agent = db.row(conn.execute("select * from agents where id=?", (agent_id,)))
    WRITERS[vendor](ws, agent, state)
    if vendor == "claude":
        mine = claude.config_dir(ws, agent).resolve()
        if old and (was := claude.config_dir(ws, old).resolve()) != mine:  # moved: drop the configs left behind
            claude.clean_config(was, agent_id)
        if mine != ws.resolve():
            _exclude(mine, GENERATED)
            sync_member_dir(ws, mine, state, cfg)
    if s.get("foreground"):
        _exclude(ws, [".xmuse-tmp/"])
    return agent
