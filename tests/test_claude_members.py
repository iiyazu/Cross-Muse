"""Several Claude members in one workspace: each in its own directory (agent add --cwd), each with its own
.mcp.json / .claude/ there, and a per-member `claude --effort`."""
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import set_home, wsl_hub
from test_init_cli import run
from xmuse import doctor, init as xinit
from xmuse.adapters import claude
from xmuse.config import SHIM


@pytest.fixture
def ws(tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    w = tmp_path / "ws"
    w.mkdir()
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    return w


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def identity(d: Path) -> str:
    return json.loads((d / ".mcp.json").read_text())["mcpServers"]["xmuse"]["env"]["XMUSE_AGENT"]


def settings_of(h, aid):
    return json.loads(h.q("select settings from agents where id=?", aid)[0]["settings"])


# ---- coexistence and uniqueness -------------------------------------------------------------------

def test_two_claude_members_in_different_dirs_coexist(ws):
    state = xinit.init(ws)
    (ws / "dev1").mkdir()
    (ws / "dev2").mkdir()
    xinit.add_agent(state, "lead", "claude")  # no --cwd: the workspace root, as before
    xinit.add_agent(state, "dev-1", "claude", settings={"cwd": str(ws / "dev1")})
    xinit.add_agent(state, "dev-2", "claude", settings={"cwd": str(ws / "dev2")})
    assert [identity(d) for d in (ws, ws / "dev1", ws / "dev2")] == ["lead", "dev-1", "dev-2"]
    for d, aid in ((ws, "lead"), (ws / "dev1", "dev-1"), (ws / "dev2", "dev-2")):
        st = json.loads((d / ".claude" / "settings.json").read_text())
        assert st["permissions"] == {"allow": ["mcp__xmuse__*"]}
        assert f"XMUSE_AGENT={aid} " in st["hooks"]["Stop"][0]["hooks"][0]["command"]
        env = json.loads((d / ".mcp.json").read_text())["mcpServers"]["xmuse"]["env"]
        assert env == {"XMUSE_STATE": str(state), "XMUSE_AGENT": aid, "XMUSE_CHANNEL": "1"}
    row = {a["id"]: json.loads(a["settings"]) for a in xinit.db.rows(
        xinit.db.connect(state / "hub.db").execute("select * from agents"))}
    assert "cwd" not in row["lead"] and row["dev-1"]["cwd"] == str(ws / "dev1")
    excl = (ws / ".git" / "info" / "exclude").read_text().splitlines()
    assert {".mcp.json", ".claude/"} <= set(excl)  # unanchored patterns: they cover the member dirs too


def test_same_directory_second_claude_is_refused(ws):
    state = xinit.init(ws)
    (ws / "dev1").mkdir()
    xinit.add_agent(state, "lead", "claude")
    xinit.add_agent(state, "dev-1", "claude", settings={"cwd": str(ws / "dev1")})
    with pytest.raises(SystemExit, match=r"already has a claude agent in .*dev1: dev-1.*--cwd <dir>"):
        xinit.add_agent(state, "dev-x", "claude", settings={"cwd": str(ws / "dev1")})
    with pytest.raises(SystemExit, match=r"already has a claude agent in .*: lead.*--cwd <dir>"):
        xinit.add_agent(state, "dev-y", "claude")  # the workspace root belongs to lead
    with pytest.raises(SystemExit, match="already has a claude agent"):
        xinit.add_agent(state, "dev-z", "claude", settings={"cwd": str(ws)})  # the root spelled out
    with pytest.raises(SystemExit, match="already has a claude agent"):
        xinit.add_agent(state, "dev-w", "claude", settings={"cwd": str(ws / "dev1" / "..")})  # same dir, other spelling
    xinit.add_agent(state, "dev-1", "claude", settings={"cwd": str(ws / "dev1")})  # re-adding yourself is fine
    assert not (ws / "dev-x").exists()


def test_cwd_must_exist_and_be_inside_or_a_worktree(ws, tmp_path):
    state = xinit.init(ws)
    with pytest.raises(SystemExit, match="not an existing directory"):
        xinit.add_agent(state, "a", "claude", settings={"cwd": str(ws / "nope")})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(SystemExit, match="inside the workspace .* or the root of a git worktree"):
        xinit.add_agent(state, "a", "claude", settings={"cwd": str(elsewhere)})
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    git(other_repo, "init", "-q")
    with pytest.raises(SystemExit, match="git worktree"):  # a repository, but not this one
        xinit.add_agent(state, "a", "claude", settings={"cwd": str(other_repo)})
    with pytest.raises(SystemExit, match="--cwd is only for --vendor claude"):
        xinit.add_agent(state, "oc", "opencode", settings={"cwd": str(ws)})
    assert not (elsewhere / ".mcp.json").exists()
    git(ws, "commit", "-q", "--allow-empty", "-m", "init")
    git(ws, "worktree", "add", "-q", "-b", "dev-1", str(tmp_path / "wt-dev1"))
    xinit.add_agent(state, "lead", "claude")
    xinit.add_agent(state, "dev-1", "claude", settings={"cwd": str(tmp_path / "wt-dev1")})
    wt = tmp_path / "wt-dev1"
    assert identity(wt) == "dev-1" and identity(ws) == "lead"
    # a worktree lacks the untracked generated files: the member gets state pointer, instructions and the skill
    assert json.loads((wt / ".xmuse.json").read_text()) == {"state": str(state)}
    assert "xmuse:begin" in (wt / "AGENTS.md").read_text() and "@AGENTS.md" in (wt / "CLAUDE.md").read_text()
    assert (wt / ".claude" / "skills" / "xmuse-collab" / "SKILL.md").exists()
    # git ignores a linked worktree's own info/exclude: the shared one carries the patterns
    common = (ws / ".git" / "info" / "exclude").read_text().splitlines()
    assert {".mcp.json", ".claude/", ".xmuse.json"} <= set(common)
    out = subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout
    assert ".mcp.json" not in out and ".claude" not in out.replace("AGENTS.md", "")


def test_readd_in_another_dir_removes_the_old_configs(ws):
    state = xinit.init(ws)
    (ws / "a").mkdir()
    (ws / "b").mkdir()
    xinit.add_agent(state, "dev", "claude", settings={"cwd": str(ws / "a")})
    (ws / "a" / ".claude" / "settings.local.json").write_text("{}")  # the user's own file stays
    xinit.add_agent(state, "dev", "claude", settings={"cwd": str(ws / "b")})
    assert identity(ws / "b") == "dev"
    assert not (ws / "a" / ".mcp.json").exists() and not (ws / "a" / ".claude" / "settings.json").exists()
    assert (ws / "a" / ".claude" / "settings.local.json").exists()
    xinit.add_agent(state, "dev", "claude")  # back to the workspace root
    assert identity(ws) == "dev" and not (ws / "b" / ".mcp.json").exists()
    assert not (ws / "b" / ".claude").exists()
    # clean_config never touches another member's file
    (ws / "a" / ".mcp.json").write_text(json.dumps({"mcpServers": {"xmuse": {"env": {"XMUSE_AGENT": "other"}}}}))
    assert claude.clean_config(ws / "a", "dev") == [] and (ws / "a" / ".mcp.json").exists()


def test_no_cwd_changes_nothing(ws):
    state = xinit.init(ws)
    a = xinit.add_agent(state, "cat", "claude")
    s = json.loads(a["settings"])
    assert "cwd" not in s and "effort" not in s
    assert identity(ws) == "cat" and claude.config_dir(ws, a) == ws
    xinit.add_agent(state, "cat", "claude", settings={"cwd": str(ws)})  # the root spelled out is the same thing
    assert "cwd" not in json.loads(xinit.db.row(xinit.db.connect(state / "hub.db").execute(
        "select settings from agents where id='cat'"))["settings"])


# ---- desktop ----------------------------------------------------------------------------------------------

@wsl_hub  # the Windows-native form (node, the hub's python) is test_desktop.test_desktop_config_on_a_windows_hub
def test_desktop_member_writes_into_its_cwd(ws):
    state = xinit.init(ws)
    (ws / "dev1").mkdir()
    xinit.add_agent(state, "lead", "claude", settings={"desktop": True})
    xinit.add_agent(state, "dev-1", "claude", settings={"desktop": True, "cwd": str(ws / "dev1")})
    d = ws / "dev1"
    mcp = json.loads((d / ".mcp.json").read_text())["mcpServers"]["xmuse"]
    assert mcp["command"] == "wsl.exe" and "XMUSE_AGENT=dev-1" in mcp["args"] and mcp["args"][-1] == str(SHIM)
    assert "XMUSE_AGENT=lead" in json.loads((ws / ".mcp.json").read_text())["mcpServers"]["xmuse"]["args"]
    assert "'agent': 'dev-1'" in (d / ".claude" / "xmuse-hook.py").read_text().splitlines()[1]
    assert "'agent': 'lead'" in (ws / ".claude" / "xmuse-hook.py").read_text().splitlines()[1]
    st = json.loads((d / ".claude" / "settings.json").read_text())
    assert st["hooks"]["Stop"][0]["hooks"][0]["command"].endswith('python3 .claude/xmuse-hook.py Stop"')


def test_attach_commands_name_the_member_dir(make, tmp_path):
    (tmp_path / "ws" / "dev1").mkdir(parents=True)
    (tmp_path / "ws" / "dev2").mkdir()
    h = make([("lead", "claude"), ("dev-1", "claude", {"cwd": str(tmp_path / "ws" / "dev1"), "effort": "high"}),
              ("dev-2", "claude", {"desktop": True, "cwd": str(tmp_path / "ws" / "dev2")})])
    assert h.admin("attach", agent="lead")["result"]["command"].startswith("claude --model ")
    cmd = h.admin("attach", agent="dev-1")["result"]["command"]
    assert cmd.startswith(f"cd {shlex.quote(str(tmp_path / 'ws' / 'dev1'))} && claude --model ")
    assert " --effort high " in cmd
    desk = h.admin("attach", agent="dev-2")["result"]["command"]
    assert "ws\\dev2 in the Claude desktop app" in desk and str(h.ws) in desk and "watch --agent dev-2" in desk


# ---- headless turns: cwd and --effort ------------------------------------------------------------------------

def test_headless_turn_runs_in_member_dir_with_its_effort(make, tmp_path):
    (tmp_path / "ws" / "dev1").mkdir(parents=True)
    h = make([("lead", "claude", {"effort": "xhigh"}), ("dev-1", "claude", {"cwd": str(tmp_path / "ws" / "dev1")})])
    h.plan_claude({}, {})
    h.send("lead", "hi lead")
    h.send("dev-1", "hi dev")
    h.wait_quiet()
    calls = {c["prompt"].split("hi ")[-1].split()[0]: c for c in h.claude_calls() if "hi " in c["prompt"]}
    lead, dev = calls["lead"], calls["dev"]
    assert lead["argv"][lead["argv"].index("--effort") + 1] == "xhigh"
    assert Path(lead["cwd"]).resolve() == h.ws.resolve()
    assert "--effort" not in dev["argv"]  # not set: not passed
    assert Path(dev["cwd"]).resolve() == (tmp_path / "ws" / "dev1").resolve()
    sess = h.q("select a.id agent, s.cwd from sessions s join agents a on a.id=s.agent_id order by a.id")
    assert {r["agent"]: r["cwd"] for r in sess} == {"dev-1": str(tmp_path / "ws" / "dev1"), "lead": str(h.ws)}
    # the transcript is where claude put it: under the project directory the turn ran in
    sid = h.q("select vendor_session from sessions s join agents a on a.id=s.agent_id where a.id='dev-1'")[0][
        "vendor_session"]
    assert claude.transcript(tmp_path / "ws" / "dev1", sid).exists()


def test_effort_values_and_other_vendors(ws, capsys):
    state = xinit.init(ws)
    for lvl in claude.EFFORTS:
        a = xinit.add_agent(state, "c", "claude", settings={"effort": lvl})
        assert json.loads(a["settings"])["effort"] == lvl
    with pytest.raises(SystemExit, match="--effort must be one of: low, medium, high, xhigh, max"):
        xinit.add_agent(state, "c", "claude", settings={"effort": "ultra"})
    capsys.readouterr()
    a = xinit.add_agent(state, "oc", "opencode", settings={"effort": "high"})
    assert "ignored for opencode" in capsys.readouterr().out and "effort" not in json.loads(a["settings"])


def test_tui_adopt_records_the_member_dir(make, tmp_path):
    (tmp_path / "ws" / "dev1").mkdir(parents=True)
    h = make([("lead", "claude"), ("dev-1", "claude", {"cwd": str(tmp_path / "ws" / "dev1")})])
    h.hook("dev-1", "SessionStart", session_id="S1", pid=os.getpid(), entrypoint="cli")
    h.hook("lead", "SessionStart", session_id="S2", pid=os.getpid(), entrypoint="cli")
    cwds = {r["vendor_session"]: r["cwd"] for r in h.q("select vendor_session, cwd from sessions")}
    assert cwds == {"S1": str(tmp_path / "ws" / "dev1"), "S2": None}  # None: the workspace


# ---- CLI, doctor -----------------------------------------------------------------------------------------------

def test_cli_cwd_and_effort(ws):
    run(ws, "init", str(ws))
    (ws / "dev1").mkdir()
    run(ws, "agent", "add", "lead", "--vendor", "claude")
    run(ws, "agent", "add", "dev-1", "--vendor", "claude", "--cwd", "dev1", "--effort", "max")  # relative to the cwd
    assert identity(ws / "dev1") == "dev-1"
    listed = {a["id"]: a for a in json.loads(run(ws, "agent", "list").stdout)}
    assert listed["dev-1"]["cwd"] == str(ws / "dev1") and listed["dev-1"]["effort"] == "max"
    assert "cwd" not in listed["lead"]
    bad = run(ws, "agent", "add", "dev-2", "--vendor", "claude", "--cwd", "dev1", check=False)
    assert bad.returncode != 0 and "already has a claude agent" in bad.stderr
    bad = run(ws, "agent", "add", "dev-3", "--vendor", "claude", "--effort", "ultra", check=False)
    assert bad.returncode != 0 and "invalid choice" in bad.stderr
    r = run(ws, "agent", "add", "oc", "--vendor", "opencode", "--effort", "high")
    assert "ignored for opencode" in r.stdout


def test_doctor_checks_the_member_dir(ws):
    state = xinit.init(ws)
    (ws / "dev1").mkdir()
    xinit.add_agent(state, "lead", "claude")
    xinit.add_agent(state, "dev-1", "claude", settings={"cwd": str(ws / "dev1")})
    c = {x.name: x for x in doctor.workspace(state)}
    assert c["instances"].level == "ok" and c["instances"].detail == "claude x2 (dev-1, lead)"
    assert c["agent dev-1"].level == "ok" and str(ws / "dev1") in c["agent dev-1"].detail
    (ws / "dev1" / ".mcp.json").unlink()
    c = {x.name: x for x in doctor.workspace(state)}
    assert c["agent dev-1"].level == "FAIL" and str(ws / "dev1" / ".mcp.json") in c["agent dev-1"].detail
    assert f"--cwd {ws / 'dev1'}" in c["agent dev-1"].fix and c["agent lead"].level == "ok"
    (ws / "dev1").rename(ws / "gone")
    c = {x.name: x for x in doctor.workspace(state)}
    assert c["agent dev-1"].level == "FAIL" and "does not exist" in c["agent dev-1"].detail
    # two members on one directory (a database edited by hand): the instances check fails
    conn = xinit.db.connect(state / "hub.db")
    with xinit.db.tx(conn):
        conn.execute("update agents set settings=json_remove(settings, '$.cwd') where id='dev-1'")
    c = {x.name: x for x in doctor.workspace(state)}
    assert c["instances"].level == "FAIL" and "dev-1, lead share" in c["instances"].fix
    assert doctor.report(list(c.values()), io.StringIO()) == 1


def test_preset_worktree_gets_the_executors_own_claude_config(make, tmp_path):
    """The preset copies the workspace's .mcp.json into an executor's worktree: with several Claude members that file
    may name another one, so the executor's own is written there."""
    (tmp_path / "ws" / "dev1").mkdir(parents=True)
    h = make([("lead", "claude"), ("dev-1", "claude", {"cwd": str(tmp_path / "ws" / "dev1"), "effort": "high"})])
    git(h.ws, "commit", "-q", "--allow-empty", "-m", "base")
    h.plan_claude({})
    run_ = h.hub.preset.start("t", "lead", ["dev-1"])
    h.wait_quiet()
    wt = Path(run_["worktrees"]["dev-1"])
    assert identity(wt) == "dev-1" and identity(h.ws) == "lead"
    s = settings_of(h, "dev-1")
    assert s["cwd"] == str(wt) and s["effort"] == "high"


def test_a_hub_run_member_runs_bash_behind_the_gate(make):
    """Auto mode: hook.py PreToolUse asks the hub's risk check (POST /v1/risk) and denies what it flags for a hub-run
    member, says nothing for the user's own sessions (desktop, interactive cli), lets everyday commands through, and
    denies everything when the hub cannot answer."""
    import os
    import subprocess
    import sys
    from xmuse.config import HOOK
    h = make()

    def gate(cmd, cwd=None, **env):
        r = subprocess.run([sys.executable, "-I", str(HOOK), "PreToolUse"], capture_output=True, text=True,
                           timeout=20, input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd},
                                                         "cwd": cwd or str(h.ws)}),
                           env={**os.environ, "XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1",
                                "CLAUDE_CODE_ENTRYPOINT": "sdk-cli", **env})
        return r.stdout.strip()

    assert gate("pytest -q") == ""
    out = json.loads(gate("git push origin main"))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "git push" in out["permissionDecisionReason"]
    # the member's directory is the workspace, whatever directory its shell has moved to
    assert "outside" in json.loads(gate("rm -rf build", cwd="/"))["hookSpecificOutput"]["permissionDecisionReason"]
    assert gate("git push origin main", CLAUDE_CODE_ENTRYPOINT="cli") == ""  # the user's own interactive claude
    assert gate("git push origin main", XMUSE_DESKTOP="1") == ""  # the desktop coordinator
    (h.state / "hub.json").rename(h.state / "hub.json.away")  # no hub to ask: fail closed
    try:
        out = json.loads(gate("ls"))["hookSpecificOutput"]
    finally:
        (h.state / "hub.json.away").rename(h.state / "hub.json")
    assert out["permissionDecision"] == "deny" and "could not check" in out["permissionDecisionReason"]
