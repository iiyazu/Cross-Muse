"""Claude desktop app mode: no push, no background wake; the agent polls xmuse_inbox every turn."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_init_cli import XMUSE, run
from xmuse import db, init as xinit
from xmuse.adapters.claude import write_config, win_path
from xmuse.config import SHIM

import xmuse

HOOK = Path(xmuse.__file__).parent / "hook.py"
BASH_ISH = ("||", "&&", "$", ";", "`", ">", "<")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    w = tmp_path / "ws"
    w.mkdir()
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    return w


# ---- generated config -------------------------------------------------------------------------

def test_desktop_config(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "dog", "claude", settings={"desktop": True})
    mcp = json.loads((ws / ".mcp.json").read_text())
    assert mcp == {"mcpServers": {"xmuse": {"command": "wsl.exe", "args": [
        "-d", "Ubuntu-Test", "--", "env", f"XMUSE_STATE={state}", "XMUSE_AGENT=dog", "XMUSE_DESKTOP=1", "node", str(SHIM)]}}}
    assert "XMUSE_CHANNEL" not in (ws / ".mcp.json").read_text()
    st = json.loads((ws / ".claude" / "settings.json").read_text())
    assert st["enabledMcpjsonServers"] == ["xmuse"] and st["permissions"] == {"allow": ["mcp__xmuse__*"]}
    pre = "wsl.exe -d Ubuntu-Test -- python3 .claude/xmuse-hook.py"
    for ev in ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"):
        h = st["hooks"][ev][0]["hooks"][0]
        assert h["command"] == f"{pre} {ev}" and h["timeout"] == 10
    compact = st["hooks"]["SessionStart"][1]
    assert compact["matcher"] == "compact"
    assert compact["hooks"][0]["command"] == f"{pre} compact"
    for ev in st["hooks"].values():
        for g in ev:
            for h in g["hooks"]:
                assert not any(t in h["command"] for t in BASH_ISH), h["command"]
                # Git Bash rewrites arguments that start with "/" (also NAME=/path): none may exist
                assert not any(t.startswith("/") or "=/" in t for t in h["command"].split()), h["command"]
    copy = (ws / ".claude" / "xmuse-hook.py").read_text()
    assert f"BAKED = {{'state': {str(state)!r}, 'agent': 'dog', 'desktop': True, 'python': {sys.executable!r}}}" in copy
    assert copy.endswith(HOOK.read_text())
    assert ".claude/" in (ws / ".git" / "info" / "exclude").read_text().splitlines()


def test_desktop_distro_is_derived_never_assumed(ws, monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME")
    state = xinit.init(ws)
    with pytest.raises(SystemExit, match="XMUSE_WSL_DISTRO"):  # no silent "Ubuntu-24.04" outside WSL
        xinit.add_agent(state, "dog", "claude", settings={"desktop": True})
    monkeypatch.setenv("XMUSE_WSL_DISTRO", "Debian")
    xinit.add_agent(state, "dog", "claude", settings={"desktop": True})
    assert json.loads((ws / ".mcp.json").read_text())["mcpServers"]["xmuse"]["args"][:2] == ["-d", "Debian"]


def test_non_desktop_config_is_unchanged(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "cat", "claude")
    env = {"XMUSE_STATE": str(state), "XMUSE_AGENT": "cat", "XMUSE_CHANNEL": "1"}
    mcp = {"mcpServers": {"xmuse": {"command": "node", "args": [str(SHIM)], "env": env}}}
    assert (ws / ".mcp.json").read_text() == json.dumps(mcp, indent=2) + "\n"
    hook = f"XMUSE_STATE={state} XMUSE_AGENT=cat python3 {HOOK}"
    hooks = {ev: [{"hooks": [{"type": "command", "command": f"{hook} {ev}", "timeout": 10}]}]
             for ev in ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop")}
    hooks["SessionStart"].append({"matcher": "compact", "hooks": [{
        "type": "command", "timeout": 10, "command": f"XMUSE_STATE={state} {sys.executable} -m xmuse hook compact"}]})
    settings = {"enabledMcpjsonServers": ["xmuse"], "permissions": {"allow": ["mcp__xmuse__*"]}, "hooks": hooks}
    assert (ws / ".claude" / "settings.json").read_text() == json.dumps(settings, indent=2) + "\n"


def test_desktop_replacing_a_cli_identity_prints_a_note(ws, capsys):
    state = xinit.init(ws)
    xinit.add_agent(state, "cat", "claude")
    assert "one interactive Claude identity" not in capsys.readouterr().out
    agent = {"id": "dog", "settings": json.dumps({"desktop": True})}
    write_config(ws, agent, state)
    assert "one interactive Claude identity per workspace; dog (desktop) replaces cat" in capsys.readouterr().out
    write_config(ws, agent, state)  # already desktop: no note
    assert capsys.readouterr().out == ""


def test_cli_desktop_flag(ws):
    run(ws, "init", str(ws))
    r = run(ws, "agent", "add", "dog", "--vendor", "claude", "--desktop")
    assert "dog" in r.stdout
    assert json.loads((ws / ".mcp.json").read_text())["mcpServers"]["xmuse"]["command"] == "wsl.exe"
    listed = json.loads(run(ws, "agent", "list").stdout)
    assert listed[0]["id"] == "dog" and listed[0]["desktop"] is True
    bad = run(ws, "agent", "add", "oc", "--vendor", "opencode", "--desktop", check=False)
    assert bad.returncode != 0 and "desktop" in bad.stderr


def test_xmuse_agent_add_non_claude_desktop_rejected(ws):
    state = xinit.init(ws)
    with pytest.raises(SystemExit):
        xinit.add_agent(state, "oc", "opencode", settings={"desktop": True})


# ---- path conversion / attach -----------------------------------------------------------------

def test_win_path(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    assert win_path(Path("/home/user/dev/xmuse2-dog")) == r"\\wsl.localhost\Ubuntu-Test\home\user\dev\xmuse2-dog"
    assert win_path(Path("/mnt/c/Users/me/proj")) == r"C:\Users\me\proj"


def test_attach_for_desktop_agent(make, monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    h = make([("dog", "claude", {"desktop": True})])
    cmd = h.admin("attach", agent="dog")["result"]["command"]
    win = r"\\wsl.localhost\Ubuntu-Test" + str(h.ws).replace("/", "\\")
    first, second = cmd.split("\n")
    assert first == (f"Open {win} in the Claude desktop app (Code tab), start a new session "
                     "and call xmuse_whoami to verify.")
    assert second == ("Monitor command (run once per session): MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-Test -- "
                      f"{sys.executable} -m xmuse --ws {h.ws} watch --agent dog")
    h.hub.engine.drivers["claude"].ws = Path("/mnt/c/work/dog")
    assert h.admin("attach", agent="dog")["result"]["command"].startswith(r"Open C:\work\dog in the Claude")


def test_attach_for_cli_agent_is_unchanged(make):
    h = make()
    cmd = h.admin("attach", agent="claude-1")["result"]["command"]
    assert cmd.startswith("claude --model ") and "--dangerously-load-development-channels server:xmuse" in cmd


# ---- hub: no wake, queue + inbox, hook handling -----------------------------------------------

def settle(h):
    h.hub.engine.kick()
    time.sleep(0.6)


def test_engine_never_wakes_desktop_agent(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.plan_claude({})
    h.hook("dog", "SessionStart", desktop=True, session_id="S1", pid=4242)
    h.send("dog", "first")
    h.send("dog", "second", mentions=["dog"])
    settle(h)
    assert h.claude_calls() == [] and h.turns() == []
    assert [d["state"] for d in h.q("select state from deliveries order by id")] == ["queued", "queued"]
    inbox = h.tool("dog", "xmuse_inbox")["result"]
    assert [m["body"] for m in inbox] == ["first", "second"]
    h.admin("resume", agent="dog")  # paused semantics untouched
    settle(h)
    assert h.claude_calls() == [] and h.turns() == []


def test_hook_session_start_and_end(make):
    h = make([("dog", "claude", {"desktop": True})])
    r = h.hook("dog", "SessionStart", desktop=True, session_id="S1", pid=999999, entrypoint=None)
    assert r["result"]["ok"] is True
    s = h.q("select * from sessions")
    assert [(x["vendor_session"], x["origin"], x["state"], x["online"]) for x in s] == [("S1", "desktop", "current", 1)]
    assert h.q("select * from leases") == []
    h.hook("dog", "SessionStart", desktop=True, session_id="S2", pid=999999)
    s = {x["vendor_session"]: x for x in h.q("select * from sessions")}
    assert s["S1"]["state"] == "retired" and s["S2"]["state"] == "current" and s["S2"]["origin"] == "desktop"
    h.hook("dog", "SessionEnd", desktop=True, session_id="S2", pid=999999)
    s = {x["vendor_session"]: x for x in h.q("select * from sessions")}
    assert s["S2"]["online"] == 0 and s["S2"]["state"] == "current"
    assert h.q("select * from leases") == []
    settle(h)
    assert h.claude_calls() == []


def test_hook_response_carries_pending_counts(make):
    h = make([("dog", "claude", {"desktop": True})])
    r = h.hook("dog", "UserPromptSubmit", desktop=True, session_id="S1", pid=1)["result"]
    assert (r["ok"], r["pending"], r["mentions"]) == (True, 0, 0)
    h.send("dog", "a")
    h.send("dog", "b", mentions=["dog"])
    r = h.hook("dog", "UserPromptSubmit", desktop=True, session_id="S1", pid=1)["result"]
    assert (r["pending"], r["mentions"]) == (2, 1)
    h.tool("dog", "xmuse_inbox")  # read
    assert h.hook("dog", "UserPromptSubmit", desktop=True, session_id="S1", pid=1)["result"]["pending"] == 0


def test_hub_status_marks_desktop_agents(make):
    from xmuse import cli
    h = make([("dog", "claude", {"desktop": True})])
    h.send("dog", "a")
    h.send("dog", "b", mentions=["dog"])
    a = cli.status(h.state)["agents"][0]
    assert a["desktop"] is True and a["pending"] == 2 and "settings" not in a
    assert cli.quiet(h.state)  # a desktop backlog does not block `xmuse wait`


def test_hub_status_plain_agent_has_no_desktop_fields(make):
    from xmuse import cli
    h = make()
    a = cli.status(h.state)["agents"][0]
    assert "desktop" not in a and "pending" not in a and "settings" not in a


# ---- hook.py as a subprocess ------------------------------------------------------------------

def run_hook(state, agent, event, stdin, desktop=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("XMUSE_")}
    env.update(XMUSE_STATE=str(state), XMUSE_AGENT=agent, **({"XMUSE_DESKTOP": "1"} if desktop else {}))
    return subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(stdin), env=env,
                          capture_output=True, text=True, timeout=20)


def test_hook_py_prompts_for_pending_messages(make):
    h = make([("dog", "claude", {"desktop": True})])
    r = run_hook(h.state, "dog", "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"})
    assert r.returncode == 0 and r.stdout == ""
    h.send("dog", "a")
    h.send("dog", "b", mentions=["dog"])
    r = run_hook(h.state, "dog", "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"})
    assert r.returncode == 0
    first, rest = r.stdout.split(chr(10), 1)
    assert first == ("[xmuse] 2 new message(s) (1 mention you). Call xmuse_inbox before anything else, "
                     "and xmuse_ack when handled.")
    assert "New for you (unread" in rest and "human" in rest and ": a" in rest
    # other events never print; the report went through as a desktop one
    r = run_hook(h.state, "dog", "Stop", {"session_id": "S1"})
    assert r.returncode == 0 and r.stdout == ""
    r = run_hook(h.state, "dog", "SessionStart", {"session_id": "S9", "source": "startup"})
    assert r.stdout == ""
    row = h.q("select * from sessions where vendor_session='S9'")
    assert row and row[0]["origin"] == "desktop" and h.q("select * from leases") == []


def test_hook_py_non_desktop_stays_silent(make):
    h = make()
    h.send("claude-1", "a")
    h.hub.engine.drain()
    r = run_hook(h.state, "claude-1", "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"}, desktop=False)
    assert r.returncode == 0 and r.stdout == ""


def test_hook_py_unreachable_hub_is_silent(tmp_path):
    state = tmp_path / "st"
    (state / "tokens").mkdir(parents=True)
    (state / "tokens" / "dog").write_text("xmt_dog")
    (state / "hub.json").write_text(json.dumps({"port": 9, "pid": 1}))
    r = run_hook(state, "dog", "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    r = run_hook(tmp_path / "nowhere", "dog", "UserPromptSubmit", {})
    assert r.returncode == 0 and r.stdout == ""


# ---- xmuse watch ------------------------------------------------------------------------------

def start_watch(h, agent, *extra):
    env = {**os.environ, "PYTHONPATH": str(Path(xmuse.__file__).parents[1])}
    env.pop("XMUSE_STATE", None)
    return subprocess.Popen([sys.executable, "-m", "xmuse", "--ws", str(h.ws), "watch", "--agent", agent,
                             "--interval", "0.2", *extra], cwd="/", env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def test_watch_reports_new_messages_only_for_its_agent_and_marks_nothing(make):
    h = make([("dog", "claude", {"desktop": True}), ("oc", "opencode")])
    with db.tx(h.conn()) as c:  # a real wake of oc ends with a hub notice to dog, which can beat the line read below
        c.execute("update agents set paused=1 where id='oc'")
    h.send("dog", "old one")  # before the watch starts: not reported
    w = start_watch(h, "dog")
    try:
        time.sleep(1)
        h.send("oc", "not for dog")
        h.send("dog", "line one\n  and   more " + "x" * 200, mentions=["dog"])
        line = w.stdout.readline()
        assert "new for dog: " in line and " from human [message] " in line  # (hub notices reach the coordinator too)
        assert "line one and more x" in line and "old one" not in line and "not for dog" not in line
        assert all(d["read_at"] is None and d["acked_at"] is None for d in h.q("select * from deliveries where recipient='dog'"))
        os.remove(h.state / "hub.json")
        rest = w.stdout.read().splitlines()
        assert rest[-1] == "[xmuse] hub stopped" and all("not for dog" not in x for x in rest)
        assert w.wait(10) == 0
    finally:
        w.kill()
        (h.state / "hub.json").write_text(json.dumps({"port": 0, "pid": os.getpid()}))  # let the hub shut down


# ---- coordinator: prompt injection (alignment + unread list) ----------------------------------

def prompt(h, sid="S1"):
    return h.hook("dog", "UserPromptSubmit", desktop=True, session_id=sid, pid=1)["result"]["context"]


def test_prompt_injection_snapshot_then_delta_and_watermark(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.hook("dog", "SessionStart", desktop=True, session_id="S1", pid=1)
    h.send("dog", "use tabs", kind="decision")
    ctx = prompt(h)
    assert "[alignment: current shared decisions" in ctx and "use tabs" in ctx
    assert "New for you (unread" in ctx and "- #" in ctx and " human " in ctx
    sid = h.q("select id from sessions")[0]["id"]
    assert h.q("select seq from seen where session_id=?", sid)  # watermark advanced
    assert [d["read_at"] for d in h.q("select read_at from deliveries")] == [None]  # nothing marked read
    assert len(h.tool("dog", "xmuse_inbox")["result"]) == 1
    assert prompt(h) == ""  # nothing new, nothing unread
    h.send("dog", "and use ruff", kind="decision")
    ctx = prompt(h)
    assert "[alignment update since your last wake]" in ctx and "use ruff" in ctx and "use tabs" not in ctx
    assert prompt(h).count("[alignment") == 0
    # compaction resets the watermark: next prompt is a snapshot again
    h.hook("dog", "SessionStart", desktop=True, session_id="S1", pid=1, source="compact")
    assert h.q("select * from seen") == []
    assert "[alignment: current shared decisions" in prompt(h)


def test_prompt_injection_caps_the_message_list(make):
    h = make([("dog", "claude", {"desktop": True})], align_delta_tokens=60)
    for i in range(12):
        h.send("dog", f"message number {i} " + "y" * 150)
    ctx = prompt(h)
    assert "more, call xmuse_inbox" in ctx and ctx.count("- #") < 12


def test_hook_py_prints_the_injected_context(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.send("dog", "use tabs", kind="decision")
    r = run_hook(h.state, "dog", "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"})
    assert r.stdout.startswith("[xmuse] 1 new message(s)") and "[alignment: current" in r.stdout


# ---- coordinator: approvals and pause notices reach the desktop agent -------------------------

def test_permission_ask_reaches_the_desktop_inbox(make):
    h = make([("opencode-1", "opencode"), ("dog", "claude", {"desktop": True})])
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "ship it")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_9")
    h.wait(lambda: h.q("select 1 from approvals"), what="approval")
    inbox = h.tool("dog", "xmuse_inbox")["result"]
    notes = [m for m in inbox if m["kind"] == "notice" and "xmuse approve per_9 once|always|reject" in m["body"]]
    assert len(notes) == 1 and "asks permission" in notes[0]["body"]
    d = h.q("select wake, state from deliveries where recipient='dog'")
    assert d and all(x["wake"] == 0 for x in d) and h.claude_calls() == []
    h.admin("approve", id="per_9", decision="once")
    h.admin("stop")


def test_notices_without_a_desktop_agent_make_no_deliveries(make):
    h = make([("opencode-1", "opencode")])
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "ship it")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_9")
    h.wait(lambda: h.q("select 1 from approvals"), what="approval")
    assert h.q("select * from deliveries where recipient not in ('opencode-1')") == []
    h.admin("approve", id="per_9", decision="once")
    h.admin("stop")


# ---- the per-workspace hook copy (Git Bash on Windows mangles absolute-path arguments) -------------

def run_copy(h, event, stdin):
    env = {k: v for k, v in os.environ.items() if not k.startswith("XMUSE_")}
    return subprocess.run([sys.executable, ".claude/xmuse-hook.py", event], input=json.dumps(stdin), env=env,
                          cwd=h.ws, capture_output=True, text=True, timeout=30)


def test_hook_copy_prints_the_injection_from_the_workspace_dir(make):
    h = make([("dog", "claude", {"desktop": True})])
    assert (h.ws / ".claude" / "xmuse-hook.py").exists()
    h.send("dog", "use tabs", kind="decision")
    r = run_copy(h, "UserPromptSubmit", {"session_id": "S1", "prompt": "hi"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("[xmuse] 1 new message(s)") and "[alignment: current shared decisions" in r.stdout
    r = run_copy(h, "SessionStart", {"session_id": "S2", "source": "startup"})
    assert r.returncode == 0 and r.stdout == ""
    assert h.q("select origin, online from sessions where vendor_session='S2'") == [{"origin": "desktop", "online": 1}]


def test_hook_copy_compact_runs_hook_compact(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.send("dog", "use tabs", kind="decision")
    h.hook("dog", "SessionStart", desktop=True, session_id="S1", pid=1)
    r = run_copy(h, "compact", {"session_id": "S1", "source": "compact"})
    assert r.returncode == 0, r.stderr
    assert "[alignment: current shared decisions" in r.stdout and "use tabs" in r.stdout
    # unreachable hub / unknown session: still silent and exit 0
    assert run_copy(h, "compact", {"session_id": "nope"}).returncode == 0
    assert run_copy(h, "compact", {}).returncode == 0
