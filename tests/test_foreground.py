"""dsh foreground mode: the dsh agent lives in a desktop session the hub never runs; it polls through the CLI."""
import codecs
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from xmuse import cli, db, init as xinit
import xmuse

FG = {"foreground": True}


def start_cli(h, *args, stdin=False, cwd="/"):
    env = {**os.environ, "PYTHONPATH": str(Path(xmuse.__file__).parents[1])}
    env.pop("XMUSE_STATE", None)
    return subprocess.Popen([sys.executable, "-m", "xmuse", "--ws", str(h.ws), *args], cwd=cwd, env=env,
                            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def finish(p, stdin=None, timeout=20):
    out, err = p.communicate(stdin, timeout=timeout)
    return p.returncode, out.decode(), err.decode()


# ---- add / re-add / config --------------------------------------------------------------------

@pytest.fixture
def wsc(tmp_path, monkeypatch):
    """A workspace that is treated as being on a Windows drive (dsh requires /mnt/<drive>/)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    w = tmp_path / "ws"
    w.mkdir()
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    monkeypatch.setattr(xinit, "_dsh_ws_ok", lambda ws: True)
    return w


def test_add_foreground_stores_settings_and_section(wsc):
    state = xinit.init(wsc)
    a = xinit.add_agent(state, "dsh-1", "dsh", settings=FG)
    assert db.settings(a) == FG and db.polled(a)
    text = (wsc / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("<!-- xmuse:fg dsh-1 begin") == 1 and "<!-- xmuse:fg dsh-1 end -->" in text
    prefix = f"wsl.exe -d Ubuntu-Test -- {sys.executable} -m xmuse --ws {wsc}"
    assert f"`{prefix}`" in text and "watch --agent dsh-1 --once" in text
    assert "BACKGROUND task" in text and "--args-file" in text and ".xmuse-tmp/" in text
    assert f'wsl.exe -d Ubuntu-Test -- bash -lc "cd {wsc} && ' in text
    assert "take priority" in text
    assert ".xmuse-tmp/" in (wsc / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert (wsc / ".xmuse-tmp").is_dir()
    assert text.index("<!-- xmuse:begin") < text.index("<!-- xmuse:fg dsh-1 begin")
    assert not (wsc / ".dsh" / "hooks.json").exists()  # no presence hooks: they would make the hub adopt the session


def test_readd_updates_settings_keeps_token_and_section(wsc):
    state = xinit.init(wsc)
    xinit.add_agent(state, "dsh-1", "dsh", settings=FG, role="coder")
    tok = (state / "tokens" / "dsh-1").read_text(encoding="utf-8")
    xinit.add_agent(state, "dsh-1", "dsh", settings=FG)
    assert (state / "tokens" / "dsh-1").read_text(encoding="utf-8") == tok
    assert (wsc / "AGENTS.md").read_text(encoding="utf-8").count("xmuse:fg dsh-1 begin") == 1
    conn = db.connect(state / "hub.db")
    assert conn.execute("select role from agents where id='dsh-1'").fetchone()[0] == "coder"
    # back to a background agent: section gone, hooks written, same token
    a = xinit.add_agent(state, "dsh-1", "dsh")
    assert db.settings(a) == {} and not db.polled(a)
    assert "xmuse:fg" not in (wsc / "AGENTS.md").read_text(encoding="utf-8")
    assert (wsc / ".dsh" / "hooks.json").exists() and (state / "tokens" / "dsh-1").read_text(encoding="utf-8") == tok
    with pytest.raises(SystemExit):
        xinit.add_agent(state, "dsh-1", "claude")


def test_init_rewrite_keeps_the_foreground_section(wsc):
    state = xinit.init(wsc)
    xinit.add_agent(state, "dsh-1", "dsh", settings=FG)
    xinit.init(wsc)
    assert (wsc / "AGENTS.md").read_text(encoding="utf-8").count("xmuse:fg dsh-1 begin") == 1


def test_foreground_validation(wsc):
    state = xinit.init(wsc)
    with pytest.raises(SystemExit):
        xinit.add_agent(state, "x", "claude", settings=FG)
    with pytest.raises(SystemExit):
        xinit.add_agent(state, "x", "opencode", settings={"desktop": True})


def test_cli_foreground_flag_and_readd(wsc, capsys):
    xinit.init(wsc)
    for _ in range(2):  # re-add is fine
        cli.main(["--ws", str(wsc), "agent", "add", "dsh-1", "--vendor", "dsh", "--desktop"])
    capsys.readouterr()
    cli.main(["--ws", str(wsc), "agent", "list"])
    listed = json.loads(capsys.readouterr().out)[0]
    assert listed["foreground"] is True and "desktop" not in listed


# ---- engine / coordinator-only behaviors ------------------------------------------------------

def test_engine_never_wakes_foreground_agent(make):
    h = make([("dsh-1", "dsh", FG)])
    h.plan_dsh({})
    first = h.send("dsh-1", "first")
    assert first["woken"] == [] and first["pushed"] == ["dsh-1"]  # T8: the relay pushes it; the hub never wakes it
    h.send("dsh-1", "second", mentions=["dsh-1"])
    h.hub.engine.kick()
    time.sleep(0.6)
    assert h.dsh_calls() == [] and h.turns() == []
    assert [d["state"] for d in h.q("select state from deliveries order by id")] == ["queued", "queued"]
    assert [m["body"] for m in h.tool("dsh-1", "xmuse_inbox")["result"]] == ["first", "second"]


def test_status_treats_foreground_as_polled(make):
    h = make([("dsh-1", "dsh", FG)])
    h.send("dsh-1", "a")
    a = cli.status(h.state)["agents"][0]
    assert a["foreground"] is True and "desktop" not in a and a["pending"] == 1 and "settings" not in a
    assert cli.quiet(h.state) and cli.status(h.state)["queued"] == []


def test_coordinator_behaviors_do_not_apply(make):
    h = make([("dsh-1", "dsh", FG), ("dog", "claude", {"desktop": True})])
    h.hub.engine.drivers["dsh"].precheck = lambda *a: pytest.fail("polled agent must not be prechecked")
    assert h.hub.precheck() == []
    # on_behalf_of is coordinator-only
    out = h.tool("dsh-1", "xmuse_send", to="dog", body="hi", on_behalf_of="human")
    assert out["error"]["code"] == "invalid_arguments"
    # hub notices reach the coordinator, not the foreground agent
    from xmuse import mail
    mail.notice(h.conn(), "#t", "paused")
    assert [r["recipient"] for r in h.q("select recipient from deliveries where recipient in ('dsh-1', 'dog')")] == ["dog"]


# ---- tools without a hub turn -----------------------------------------------------------------

def test_tools_work_without_a_running_turn(make):
    h = make([("dsh-1", "dsh", FG)])
    assert h.tool("dsh-1", "xmuse_whoami")["result"]["id"] == "dsh-1"
    sent = h.tool("dsh-1", "xmuse_send", to="human", body="hello")["result"]
    assert sent["id"] and sent["thread"]
    h.send("dsh-1", "ping")
    inbox = h.tool("dsh-1", "xmuse_inbox")["result"]
    assert [m["body"] for m in inbox] == ["ping"]
    assert h.tool("dsh-1", "xmuse_thread", id=inbox[0]["thread"])["result"]
    assert "result" in h.tool("dsh-1", "xmuse_context")
    assert h.tool("dsh-1", "xmuse_ack", ids=[inbox[0]["id"]])["result"] == {"acked": 1}
    done = h.tool("dsh-1", "xmuse_done", summary="did it", next="nothing")["result"]
    assert done["recorded"] is True
    m = h.q("select * from messages where kind='done'")[0]
    assert m["sender"] == "dsh-1" and m["body"] == "did it\nnext: nothing"
    assert h.q("select * from turns") == []


# ---- xmuse watch --once -----------------------------------------------------------------------

def test_watch_once_prints_waiting_unread_immediately(make):
    h = make([("dsh-1", "dsh", FG)])
    for b in ("waiting one", "read one", "acked one", "canceled one"):
        h.send("dsh-1", b)
    mid = {r["body"]: r["mid"] for r in h.q("select m.id mid, m.body from messages m")}
    h.tool("dsh-1", "xmuse_inbox")  # marks all read
    with db.tx(h.conn()) as c:
        c.execute("update deliveries set read_at=null where message_id=?", (mid["waiting one"],))
        c.execute("update deliveries set read_at=null, acked_at=1 where message_id=?", (mid["acked one"],))
        c.execute("update deliveries set read_at=null, state='canceled' where message_id=?", (mid["canceled one"],))
    code, out, _ = finish(start_cli(h, "watch", "--agent", "dsh-1", "--once", "--interval", "0.2"))
    assert code == 0 and out.count("\n") == 1
    assert "1 new for dsh-1: " in out and "waiting one" in out
    assert "read one" not in out and "acked one" not in out and "canceled one" not in out
    assert h.q("select read_at from deliveries where message_id=?", mid["waiting one"])[0]["read_at"] is None


def test_watch_once_blocks_until_a_new_delivery(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    h.send("dsh-1", "old, already read")
    h.tool("dsh-1", "xmuse_inbox")
    p = start_cli(h, "watch", "--agent", "dsh-1", "--once", "--interval", "0.2")
    time.sleep(1.2)
    assert p.poll() is None
    h.send("oc", "not for dsh-1")
    time.sleep(0.6)
    assert p.poll() is None
    h.send("dsh-1", "wake up", mentions=["dsh-1"])
    code, out, _ = finish(p)
    assert code == 0 and "1 new for dsh-1: " in out and "wake up" in out and "not for" not in out
    assert all(d["acked_at"] is None for d in h.q("select * from deliveries where recipient='dsh-1'"))


def test_watch_once_exits_1_when_hub_stops(make):
    h = make([("dsh-1", "dsh", FG)])
    p = start_cli(h, "watch", "--agent", "dsh-1", "--once", "--interval", "0.2")
    try:
        time.sleep(0.8)
        os.remove(h.state / "hub.json")
        code, out, _ = finish(p)
        assert code == 1 and out.strip() == "[xmuse] hub stopped"
    finally:
        (h.state / "hub.json").write_text(json.dumps({"port": 0, "pid": os.getpid()}), encoding="utf-8")


# ---- xmuse tool -------------------------------------------------------------------------------

BODY = {"to": "human", "body": "héllo 世界 #1"}
ENCODINGS = {"utf8": lambda t: t.encode(), "bom": lambda t: codecs.BOM_UTF8 + t.encode(),
             "utf16": lambda t: codecs.BOM_UTF16_LE + t.encode("utf-16-le"),
             "utf16be": lambda t: codecs.BOM_UTF16_BE + t.encode("utf-16-be")}


@pytest.mark.parametrize("enc", ENCODINGS)
def test_tool_args_file_encodings(make, tmp_path, enc):
    h = make([("dsh-1", "dsh", FG)])
    f = tmp_path / "a.json"
    f.write_bytes(ENCODINGS[enc](json.dumps(BODY, ensure_ascii=False)))
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "send", "--args-file", str(f)))
    assert code == 0, err
    assert json.loads(out)["id"] and h.q("select body from messages where sender='dsh-1'")[0]["body"] == BODY["body"]


def test_tool_relative_args_file_and_prefixed_name(make, tmp_path):
    h = make([("dsh-1", "dsh", FG)])
    (tmp_path / "a.json").write_text(json.dumps({"to": "human", "body": "rel"}), encoding="utf-8")
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "xmuse_send", "--args-file", "a.json", cwd=tmp_path))
    assert code == 0, err
    assert h.q("select body from messages where sender='dsh-1'")[0]["body"] == "rel"


def test_tool_stdin_pretty_unicode_and_empty_args(make):
    h = make([("dsh-1", "dsh", FG)])
    h.send("dsh-1", "你好")
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "inbox", stdin=True), b"")
    assert code == 0, err
    assert "你好" in out and out.startswith("[\n  {") and "\\u" not in out
    p = start_cli(h, "tool", "--agent", "dsh-1", "send", stdin=True)
    code, out, err = finish(p, json.dumps(BODY, ensure_ascii=False).encode())
    assert code == 0 and "thread" in json.loads(out)


def test_tool_errors_exit_nonzero(make, tmp_path):
    h = make([("dsh-1", "dsh", FG)])
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "send", stdin=True), b'{"to": "human"}')
    assert code != 0 and out == "" and "error:" in err
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "nosuch", stdin=True), b"")
    assert code != 0 and "error:" in err
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    code, out, err = finish(start_cli(h, "tool", "--agent", "dsh-1", "send", "--args-file", str(tmp_path / "bad.json")))
    assert code != 0 and "JSON object" in err
    code, out, err = finish(start_cli(h, "tool", "--agent", "ghost", "whoami", stdin=True), b"")
    assert code != 0
