"""`xmuse init` / `agent add` config generation and the CLI against a real hub process."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FAKE_CLAUDE
from xmuse import config, init as xinit
from xmuse.tools import TOOLS

XMUSE = [sys.executable, "-m", "xmuse"]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    w = tmp_path / "ws"
    w.mkdir()
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    return w


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_init_creates_state_outside_the_workspace(ws):
    state = xinit.init(ws)
    assert not state.is_relative_to(ws) and state.parent == Path(os.environ["XMUSE_STATE_ROOT"])
    assert json.loads((ws / ".xmuse.json").read_text()) == {"state": str(state)}
    assert mode(state) == 0o700 and mode(state / "tokens" / "_admin") == 0o600
    assert json.loads((state / "tools.json").read_text()) == TOOLS
    for d in (".claude/skills", ".opencode/skills"):
        assert "Exit check" in (ws / d / "xmuse-collab" / "SKILL.md").read_text()
    assert (ws / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    excl = (ws / ".git" / "info" / "exclude").read_text().splitlines()
    assert {".xmuse.json", ".mcp.json", ".claude/", "opencode.json"} <= set(excl)
    assert config.find_state(ws / "sub" if (ws / "sub").mkdir() is None else ws) == state


def test_agents_md_section_is_appended_once_and_replaced(ws):
    (ws / "AGENTS.md").write_text("# Project\n\nOwn rules.\n")
    (ws / "CLAUDE.md").write_text("# Claude notes\n")
    xinit.init(ws)
    xinit.init(ws)
    text = (ws / "AGENTS.md").read_text()
    assert text.startswith("# Project\n\nOwn rules.\n") and text.count("<!-- xmuse:begin") == 1
    assert "user assigned" in text and "Why-First" in text and "xmuse_done" in text  # relay trust, handoff, exit
    assert (ws / "CLAUDE.md").read_text() == "# Claude notes\n\n@AGENTS.md\n"
    (ws / "AGENTS.md").write_text(text.replace("Why-First", "OLD") + "\ntail\n")
    xinit.init(ws)
    text = (ws / "AGENTS.md").read_text()
    assert "OLD" not in text and "Why-First" in text and text.rstrip().endswith("tail")


def test_claude_config(ws):
    state = xinit.init(ws)
    a = xinit.add_agent(state, "claude-1", "claude", role="implementer")
    assert a["model"] == "claude-opus-5-5" and a["family"] == "anthropic"
    mcp = json.loads((ws / ".mcp.json").read_text())["mcpServers"]["xmuse"]
    assert mcp["command"] == "node" and mcp["args"] == [str(config.SHIM)]
    assert mcp["env"] == {"XMUSE_STATE": str(state), "XMUSE_AGENT": "claude-1", "XMUSE_CHANNEL": "1"}
    s = json.loads((ws / ".claude" / "settings.json").read_text())
    assert s["permissions"] == {"allow": ["mcp__xmuse__*"]} and s["enabledMcpjsonServers"] == ["xmuse"]
    assert set(s["hooks"]) == {"SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"}
    assert "XMUSE_AGENT=claude-1" in s["hooks"]["Stop"][0]["hooks"][0]["command"]
    [plain, compact] = s["hooks"]["SessionStart"]
    assert "matcher" not in plain and compact["matcher"] == "compact"
    assert compact["hooks"][0]["command"] == f"XMUSE_STATE={state} {sys.executable} -m xmuse hook compact"
    assert mode(state / "tokens" / "claude-1") == 0o600
    with pytest.raises(SystemExit, match="already has a claude agent"):
        xinit.add_agent(state, "claude-2", "claude")
    with pytest.raises(SystemExit, match="agent id"):
        xinit.add_agent(state, "human", "opencode")


def test_opencode_config_asks_for_consequential_commands(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "opencode-1", "opencode", settings={"note": 9})
    cfg = json.loads((ws / "opencode.json").read_text())
    srv = cfg["mcp"]["servers"]["xmuse"]
    assert srv["environment"] == {"XMUSE_STATE": str(state), "XMUSE_AGENT": "opencode-1"}
    rules = {(r["action"], r["resource"]): r["effect"] for r in cfg["permissions"]}
    assert rules[("xmuse_*", "*")] == "allow"
    assert rules[("shell", "git push*")] == rules[("shell", "rm -r*")] == "ask"
    assert rules[("shell", "*=* git push*")] == "ask"
    assert ("edit", "*") not in rules  # edits stay OpenCode's default (allowed)


def run(ws, *args, check=True):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "hub" / "src")}
    r = subprocess.run([*XMUSE, *args], cwd=ws, env=env, capture_output=True, text=True, timeout=60)
    if check and r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r


def test_hub_start_gives_up_after_the_deadline_and_stops_the_hub(tmp_path, monkeypatch):
    from xmuse import cli
    state = tmp_path / "state"
    (state / "logs").mkdir(parents=True)
    procs = []
    real_popen = subprocess.Popen

    def fake_popen(argv, **kw):  # a "hub" that never writes hub.json
        p = real_popen(["sleep", "60"], **kw)
        procs.append(p)
        return p

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli, "HUB_START_TIMEOUT_S", 1)
    with pytest.raises(SystemExit) as e:
        cli.hub_start(state)
    assert "did not start" in str(e.value) and "stopped it" in str(e.value)
    assert procs[0].wait(timeout=10) == -15  # SIGTERM from killpg


def test_cli_end_to_end_with_a_fake_agent(ws):
    run(ws, "init", ".")
    run(ws, "agent", "add", "claude-1", "--vendor", "claude", "--allow", "Bash(make test)")
    state = config.find_state(ws)
    cfg = json.loads((state / "config.json").read_text())
    (state / "config.json").write_text(json.dumps({**cfg, "claude_bin": str(FAKE_CLAUDE)}))
    home = Path(os.environ["HOME"]) / "fake-claude"
    home.mkdir()
    (home / "plan.json").write_text(json.dumps([{"as": "claude-1", "calls": [
        ["xmuse_send", {"to": "human", "body": "pong"}], ["xmuse_done", {"summary": "ok", "next": "none"}]]}]))
    try:
        assert "hub started" in run(ws, "hub", "start").stdout
        assert "already running" in run(ws, "hub", "start").stdout
        sent = json.loads(run(ws, "send", "claude-1", "ping").stdout)
        assert sent["woken"] == ["claude-1"]
        assert run(ws, "wait", "--timeout", "30", "--settle", "1").stdout.strip() == "quiet"
        log = run(ws, "log").stdout
        assert "#1" in log and "human → dm:claude-1+human" in log and "pong" in log
        assert "turn 1 claude-1 claude_resume fresh" in log and "succeeded chat tokens=" in log
        usage = run(ws, "usage", "--json").stdout
        [u] = json.loads(usage)
        assert u["agent_id"] == "claude-1" and u["wakes"] == 1 and u["total"] > 0
        st = json.loads(run(ws, "hub", "status").stdout)
        assert st["hub"]["port"] and st["agents"][0]["wakes"] == 1 and st["running"] == []
        assert "Bash(make test)" in json.loads((home / "calls.jsonl").read_text())["argv"]
        assert "--resume" in run(ws, "attach", "claude-1").stdout
        assert json.loads(run(ws, "stop").stdout) == {"canceled_deliveries": 0, "interrupted_turns": []}
        assert "no approval" in run(ws, "approve", "per_x", "once", check=False).stderr
    finally:
        run(ws, "hub", "stop")
    assert not (state / "hub.json").exists()
    assert "not running" in run(ws, "send", "claude-1", "x", check=False).stderr
    assert "no xmuse workspace" in run(ws.parent, "log", check=False).stderr
