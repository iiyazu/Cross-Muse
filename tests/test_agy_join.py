"""T8 join paths for agy: registry scan/trial, /v1/agents, adding a member while the hub runs (driver on
demand), rejoining the same session, the entry pack, context_tokens, and the absent compaction.

The agy CLI is always tests/fakes/fake_agy.py (conftest sets cfg agy_bin to it)."""
import pytest

from test_agents import ag
from test_onboard import WHY, pack, pause
from test_room import act, call, open_room
from xmuse import agents, config, db, doctor
from xmuse import room as rooms
from xmuse.adapters.agy import AgyDriver

SEND = ["xmuse_send", {"to": "human", "body": "pong"}]


# ---- registry -------------------------------------------------------------------------------------------

def test_cli_paths_find_agy_from_config_then_path_then_local_bin(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    def no_win_home():
        raise doctor.host.HostError("no")
    monkeypatch.setattr(doctor.host, "win_home", no_win_home)
    assert doctor.cli_paths({})["agy"] is None
    local = tmp_path / ".local/bin/agy"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n", encoding="utf-8")
    assert doctor.cli_paths({})["agy"] == str(local)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/agy" if name == "agy" else None)
    assert doctor.cli_paths({})["agy"] == "/usr/bin/agy"
    assert doctor.cli_paths({"agy_bin": "/opt/agy"})["agy"] == "/opt/agy"


def test_scan_and_trial_cover_agy():
    none = {"opencode": None, "dsh": None, "claude": None}
    out = agents.scan(paths={**none, "agy": "/x/agy"}, version_of=lambda p: "agy 1.2")
    by = {e["vendor"]: e for e in out}
    assert (by["agy"]["status"], by["agy"]["version"], by["agy"]["model"]) == ("installed", "agy 1.2",
                                                                              config.MODELS["agy"])
    seen = {}

    def run(argv, cwd, timeout):
        seen["argv"] = argv
        return (0, "Response: OK")
    e = agents.trial("agy", run=run)
    assert e["status"] == "ok"
    assert seen["argv"] == ["/x/agy", "--dangerously-skip-permissions", "-p", agents.TRIAL_PROMPT]
    e = agents.trial("agy", run=lambda argv, cwd, timeout: (1, "API_KEY=zzz\nRESOURCE_EXHAUSTED"))
    assert e["status"] == "failed" and "zzz" not in e["detail"]
    assert [x["vendor"] for x in agents.usable()] == []  # failed: not usable
    agents.trial("agy", run=run)
    assert [x["vendor"] for x in agents.usable()] == ["agy"]
    assert agents.set_model("agy", "gemini-x")["model"] == "gemini-x"
    agents.scan(paths={**none, "agy": None}, version_of=lambda p: "")
    with pytest.raises(agents.ToolError) as err:
        agents.trial("agy")
    assert err.value.code == "not_installed"


def test_agents_endpoints_scan_and_trial_the_configured_agy(make):
    h = make()
    open_room(h)
    key = h.key()
    st, out = ag(h, "POST", "/v1/agents/scan", None, key=key)
    assert st == 200
    by = {e["vendor"]: e for e in out["agents"]}
    assert by["agy"]["path"].endswith("fake_agy.py") and by["agy"]["version"] == "agy 0.0-fake"
    assert by["agy"]["status"] == "installed"
    st, out = ag(h, "POST", "/v1/agents/trial", {"vendor": "agy"}, key=key)
    assert st == 200 and (out["status"], out["model"]) == ("ok", config.MODELS["agy"])
    listed = ag(h, "GET", "/v1/agents", key=key)[1]["agents"]
    assert [e["vendor"] for e in listed] == ["opencode", "dsh", "claude", "agy"]
    assert [e["status"] for e in listed if e["vendor"] == "agy"] == ["ok"]
    st, out = ag(h, "POST", "/v1/agents/model", {"vendor": "agy", "model": "gemini-x"}, key=key)
    assert st == 200 and (out["model"], out["status"]) == ("gemini-x", "installed")


# ---- adding a member while the hub runs -----------------------------------------------------------------

def test_member_add_agy_creates_the_driver_and_writes_its_config(make):
    h = make()
    ot = open_room(h)["operator_token"]
    assert "agy" not in h.hub.engine.drivers
    agents.set_model("agy", "gemini-registry")
    st, out = act(h, ot, act="member_add", vendor="agy", name="agy-new", role="reviewer")
    assert (st, out) == (200, {"member_id": "agy-new"})
    assert isinstance(h.hub.engine.drivers["agy"], AgyDriver)
    a = h.q("select * from agents where id='agy-new'")[0]
    assert (a["vendor"], a["model"], a["family"]) == ("agy", "gemini-registry", "google")
    assert (h.ws / ".agents" / "plugins" / "xmuse" / "mcp_config.json").exists()
    assert (h.ws / ".agents" / "hooks.json").exists()
    st, out = act(h, ot, act="member_add", vendor="agy", name="agy-new")
    assert (st, out["error"]) == (409, "member_exists")
    st, out = act(h, ot, act="member_add", vendor="nope")
    assert (st, out["error"]) == (400, "bad_vendor") and "agy" in out["message"]
    # the new member is runnable at once: a turn goes through the on-demand driver
    h.plan_agy({"as": "agy-new", "calls": [SEND]})
    h.send("agy-new", "ping")
    h.wait(lambda: h.q("select 1 from turns where state='succeeded'"), what="agy turn")  # the host's join wake stays queued
    [t] = h.turns()
    assert (t["state"], t["adapter"]) == ("succeeded", "agy")


def join(h, **body):
    return call(h, "POST", "/v1/join", {"dir": str(h.ws), "vendor": "agy", **body}, key=h.key())


def test_agy_joins_and_rejoins_the_same_session(make):
    h = make()
    open_room(h)
    st, out = join(h, session_id="conv-1", name="agy-j", role="reviewer")
    assert st == 200 and out["member_id"] == "agy-j", out
    assert isinstance(h.hub.engine.drivers["agy"], AgyDriver)
    assert h.q("select bound_session from agents where id='agy-j'")[0]["bound_session"] == "conv-1"
    st, out = join(h, session_id="conv-1", name="agy-j")
    assert st == 200 and out["member_id"] == "agy-j"  # the same session is taken back
    st, out = join(h, session_id="conv-2", name="agy-j")  # another session: the sidebar takes the member over
    assert st == 200 and out["member_id"] == "agy-j"
    assert h.q("select bound_session from agents where id='agy-j'")[0]["bound_session"] == "conv-2"
    st, out = join(h, vendor="claude", session_id="conv-1", name="agy-j")
    assert (st, out["error"]) == (409, "member_exists")  # another vendor cannot take the name
    st, out = join(h, session_id="conv-3")
    assert st == 200 and out["member_id"] == "agy"  # unnamed: the free id


def test_invite_code_for_agy(make):
    h = make()
    ot = open_room(h)["operator_token"]
    st, out = act(h, ot, act="invite", vendor="agy", name="agy-i")
    assert st == 200
    st, j = call(h, "POST", "/v1/join", {"code": out["code"], "vendor": "agy", "session_id": "c9"})
    assert st == 200 and j["member_id"] == "agy-i"


# ---- entry pack, context, progress, compaction -----------------------------------------------------------

def test_woken_agy_gets_the_same_entry_pack_as_other_vendors(make):
    h = make(())
    ot = open_room(h)["operator_token"]
    act(h, ot, act="brief", text="Build a parser.")
    h.tool("lead", "xmuse_send", to="#g", body="ids are int", kind="decision", scope="global", _session="S-lead")
    act(h, ot, act="member_add", vendor="agy", name="agy-new", role="executor")
    pause(h, "agy-new")
    r = h.tool("lead", "xmuse_send", to="agy-new", body="parse this file", kind="handoff", why=WHY,
               _session="S-lead")
    assert "result" in r, r
    fresh = pack(h, "agy-new")
    assert "Project brief:\n[brief] Build a parser." in fresh.text
    assert "[decision] ids are int" in fresh.text
    assert "[assignment] parse this file -> agy-new" in fresh.text
    # the real wake: the CLI prompt carries identity and the same sections
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=0 where id='agy-new'")
    h.plan_agy({"as": "agy-new", "calls": [SEND]}, {"as": "agy-new", "calls": [SEND]})
    h.hub.engine.kick()
    h.wait(lambda: len(h.q("select 1 from turns where state='succeeded'")) == 1, what="first agy turn")
    prompt = h.agy_calls()[0]["prompt"]
    assert "You are agy-new" in prompt
    assert "[brief] Build a parser." in prompt and "[decision] ids are int" in prompt
    assert "[assignment] parse this file -> agy-new" in prompt
    # a re-wake in the same thread is a delta: no identity or brief again. (Sessions are
    # bound per thread: the follow-up goes to the handoff's DM thread, not the human's.)
    h.tool("lead", "xmuse_send", to="agy-new", body="again", _session="S-lead")
    h.wait(lambda: len(h.q("select 1 from turns where state='succeeded'")) == 2, what="second agy turn")
    second = h.agy_calls()[1]["prompt"]
    assert "You are agy-new" not in second and "Project brief:" not in second


def test_context_tokens_come_from_the_turn_usage_progress_stays_empty(make):
    h = make([("agy-1", "agy")])
    open_room(h)
    h.plan_agy({"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "x" * 400)
    h.wait_quiet()
    [u] = h.q("select context from usage")
    assert u["context"] > 0  # estimated from prompt and output (no transcript in the fake)
    [m] = [x for x in rooms.members(h.conn(), h.hub.cfg) if x["id"] == "agy-1"]
    assert m["context_tokens"] == u["context"] and m["compacting"] is False
    assert m["progress"] is None  # headless -p gives no live tool events: reported as none, not faked


def test_compact_is_unsupported_for_agy(make):
    h = make([("agy-1", "agy")])
    ot = open_room(h)["operator_token"]
    h.plan_agy({"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "hi")
    h.wait_quiet()
    st, out = act(h, ot, act="compact", member="agy-1")
    assert (st, out["error"]) == (400, "unsupported") and "agy" in out["message"]
