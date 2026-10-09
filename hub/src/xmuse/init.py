"""`xmuse init` and `xmuse agent add`: hub state outside the workspace, project-level configs inside it.

Nothing global is touched. Generated files that should not be committed are listed in
.git/info/exclude (not in the project's .gitignore).
"""
import json
import secrets
import shutil
from pathlib import Path

from . import config, db
from .adapters import claude, dsh, opencode
from .server import digest
from .tools import TOOLS

WRITERS = {"claude": claude.write_config, "opencode": opencode.write_config, "dsh": dsh.DshDriver.write_config}
# Headless Claude coding profile: edits in the workspace plus test/inspection commands. Anything else
# (push, rm, network) is denied in -p mode and reported as permission_denied.
CLAUDE_ALLOW = ["Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)", "Bash(pytest:*)",
                "Bash(python3 -m unittest:*)", "Bash(python -m unittest:*)", "Bash(git diff:*)",
                "Bash(git status:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)",
                "Bash(git commit:*)", "Bash(ls:*)"]
# Python projects also get the interpreter (user 10-09): unittest plus free edits already run arbitrary code,
# so this adds no real risk and lets a reviewer run its own probe scripts. Per workspace: config.json claude_allow.
PYTHON_ALLOW = ["Bash(python3:*)", "Bash(python:*)"]
SKILL_DIRS = [".claude/skills", ".opencode/skills", ".agents/skills"]  # .agents/skills: dsh


def _token(path: Path) -> str:
    tok = "xmt_" + secrets.token_urlsafe(32)
    path.write_text(tok)
    path.chmod(0o600)
    return tok


def _exclude(ws: Path, paths: list[str]) -> None:
    ex = ws / ".git" / "info" / "exclude"
    if not ex.parent.exists():
        return
    have = ex.read_text().splitlines() if ex.exists() else []
    ex.write_text("\n".join(have + [p for p in paths if p not in have]) + "\n")


def init(ws: Path) -> Path:
    ws = ws.resolve()
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
                                   "claude_allow": CLAUDE_ALLOW + (PYTHON_ALLOW if python else [])}, indent=2))
    if not (state / "tokens" / "_admin").exists():
        _token(state / "tokens" / "_admin")
    (state / "tools.json").write_text(json.dumps(TOOLS, indent=1))
    (ws / ".xmuse.json").write_text(json.dumps({"state": str(state)}) + "\n")
    for d in SKILL_DIRS:
        dst = ws / d / "xmuse-collab"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(config.SKILL / "SKILL.md", dst / "SKILL.md")
    section = (config.TEMPLATES / "AGENTS.xmuse.md").read_text()
    agents_md = ws / "AGENTS.md"
    text = agents_md.read_text() if agents_md.exists() else ""
    if "<!-- xmuse:begin" in text:
        text = text[:text.index("<!-- xmuse:begin")] + section + text[text.index("<!-- xmuse:end -->") + 18:].lstrip("\n")
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + section
    agents_md.write_text(text)
    claude_md = ws / "CLAUDE.md"  # Claude Code reads CLAUDE.md; import AGENTS.md instead of copying it
    if not claude_md.exists():
        claude_md.write_text("@AGENTS.md\n")
    elif "@AGENTS.md" not in claude_md.read_text():
        claude_md.write_text(claude_md.read_text().rstrip() + "\n\n@AGENTS.md\n")
    _exclude(ws, [".xmuse.json", ".mcp.json", ".claude/", ".opencode/", ".agents/", "opencode.json"])
    return state


def add_agent(state: Path, agent_id: str, vendor: str, model: str | None = None, role: str = "",
              settings: dict | None = None) -> dict:
    if vendor not in WRITERS:
        raise SystemExit(f"vendor must be one of: {', '.join(WRITERS)}")
    if not agent_id.replace("-", "").isalnum() or agent_id in (config.HUMAN, config.HUB):
        raise SystemExit("agent id: letters, digits and '-', not 'human' or 'hub'")
    cfg = config.load(state)
    ws = Path(cfg["workspace"])
    conn = db.connect(state / "hub.db")
    other = conn.execute("select id from agents where vendor=? and id!=?", (vendor, agent_id)).fetchone()
    if other:  # project configs carry one identity per vendor (M1 limit)
        raise SystemExit(f"workspace already has a {vendor} agent: {other[0]}")
    s = {"allowed_tools": cfg.get("claude_allow", CLAUDE_ALLOW)} if vendor == "claude" else {}
    s.update(settings or {})
    tok = _token(state / "tokens" / agent_id)
    with db.tx(conn):
        conn.execute("insert or replace into agents(id, vendor, model, family, role, settings, token_digest,"
                     " created_at) values(?,?,?,?,?,?,?,?)",
                     (agent_id, vendor, model or config.MODELS[vendor], config.FAMILIES[vendor], role,
                      json.dumps(s), digest(tok), db.now()))
    agent = db.row(conn.execute("select * from agents where id=?", (agent_id,)))
    WRITERS[vendor](ws, agent, state)
    return agent
