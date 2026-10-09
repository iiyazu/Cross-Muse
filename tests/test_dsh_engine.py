"""Delivery engine through the dsh headless adapter, with a fake dsh replaying M0-dsh NDJSON recordings."""
import json
import subprocess
from pathlib import Path

import pytest

from xmuse import init as xinit
from xmuse.adapters.dsh import human_turn, overlay, parse

FIX = Path(__file__).parent / "fixtures"
DSH = [("dsh-1", "dsh")]
SEND = ["xmuse_send", {"to": "human", "body": "done"}]


def fixture_usage(name):
    steps = [json.loads(x)["usage"] for x in (FIX / name).open() if '"step_end"' in x and '"usage"' in x]
    return sum(s["inputTokens"] for s in steps), sum(s["cacheReadTokens"] for s in steps), len(steps)


def test_turn_runs_headless_with_overlay_and_resumes_in_the_same_session(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    inp, cache, steps = fixture_usage("dsh-chat.jsonl")
    assert t["state"] == "succeeded" and (t["input"], t["cache_read"], t["cache_write"], t["calls"]) == (inp, cache, 0, steps)
    [s] = h.q("select * from sessions")
    assert s["vendor_session"].startswith("session-") and s["cwd"].endswith("ws")  # Windows-shaped in real runs
    c1 = h.dsh_calls()[0]
    a = c1["argv"]
    assert a[a.index("--profile") + 1] == "headless" and "--json" in a and a[-1] == "-" and "--session-id" not in a
    assert "You are dsh-1" in c1["prompt"] and c1["env"] == {
        "DSH_TELEMETRY_DISABLED": "1", "ELECTRON_RUN_AS_NODE": "1", "WSLENV": "DSH_TELEMETRY_DISABLED:ELECTRON_RUN_AS_NODE"}
    rows = c1["overlay"]
    assert rows[0]["config"] == {"provider": "deepseek-official", "model": "deepseek-v4-flash"}
    [mcp] = rows[1]["insert"]
    assert mcp["config"]["serverName"] == "xmuse" and mcp["config"]["env"]["XMUSE_AGENT"] == "dsh-1"
    assert {"id": "tool-web", "disabled": True} in rows and not any(r.get("id") == "tool-pwsh" for r in rows)
    h.send("dsh-1", "again")
    h.wait_quiet()
    c2 = h.dsh_calls()[1]["argv"]
    assert c2[c2.index("--session-id") + 1] == s["vendor_session"]
    assert "You are" not in h.dsh_calls()[1]["prompt"]


def test_coding_turn_is_flagged_code(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "fixture": "dsh-code.jsonl", "calls": [SEND]})
    h.send("dsh-1", "edit calc.py")
    h.wait_quiet()
    assert h.turns()[0]["mode"] == "code"


def test_turn_end_error_fails_the_turn_and_notifies(make):
    h = make(DSH)
    h.plan_dsh({"result": "error"})
    m = h.send("dsh-1", "x")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed" and "PROVIDER_ERROR" in t["error"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "failed"
    assert "failed" in h.q("select body from messages where kind='notice'")[0]["body"]


def test_already_owned_backs_off_then_succeeds(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"owned": True}, {"owned": True}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    m = h.send("dsh-1", "second")
    h.wait_quiet()
    assert [t["state"] for t in h.turns()] == ["succeeded", "succeeded"] and len(h.dsh_calls()) == 4
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"


def test_repeated_refusals_pause_the_agent_and_keep_the_messages(make):
    h = make(DSH, dsh_refusals=1)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"owned": True}, {"owned": True}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    m = h.send("dsh-1", "second")
    h.wait(lambda: h.q("select paused from agents")[0]["paused"] == 1, what="paused")
    assert "held by another dsh process" in h.turns()[1]["error"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "queued"
    assert any("dsh-1 paused" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    h.admin("resume", agent="dsh-1")
    h.wait(lambda: h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done",
           what="delivered after resume")


def test_unknown_session_is_retried_in_a_fresh_session(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    (h.home / "fake-dsh" / "sessions.json").write_text("{}")  # dsh forgot the session
    m = h.send("dsh-1", "second")
    h.wait_quiet()
    assert [t["state"] for t in h.turns()] == ["succeeded", "failed", "succeeded"]
    assert "does not exist" in h.turns()[1]["error"]
    third = h.dsh_calls()[2]
    assert "--session-id" not in third["argv"] and "You are dsh-1" in third["prompt"] and "second" in third["prompt"]
    assert [s["state"] for s in h.q("select state from sessions order by id")] == ["retired", "current"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert h.q("select wakes from chains where id=?", m["chain"])[0]["wakes"] == 1


def test_precheck_reports_an_unknown_model(make):
    h = make([("dsh-1", "dsh", {"model": "deepseek-official/bogus-model"})])
    [err] = h.hub.precheck()
    assert err.startswith("dsh-1: model deepseek-official/bogus-model unusable: INVALID_REQUEST")
    assert "deepseek-v4-pro" in err  # dsh's message names the models that exist
    good = {"id": "dsh-1", "model": "deepseek-official/deepseek-v4-flash"}
    assert h.hub.engine.drivers["dsh"].precheck(good, h.ws) is None


def test_human_typing_in_the_desktop_app_holds_admission(make):
    """Live hooks (SessionStart/UserPromptSubmit/Stop dialect, probe hooks.log shape)."""
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    h.hook_dsh("dsh-1", "UserPromptSubmit", session_id=sid, prompt="human typing")
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is True
    m = h.send("dsh-1", "while the human types")
    h.hub.engine.call(lambda: None)
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "queued"
    assert not h.q("select 1 from turns where id=2")
    h.hook_dsh("dsh-1", "Stop", session_id=sid)
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is False
    h.wait_quiet()
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"


def test_stop_interrupts_a_running_dsh_turn(make):
    h = make(DSH)
    h.plan_dsh({"sleep": 30})
    h.send("dsh-1", "slow")
    h.wait(lambda: len(h.dsh_calls()) == 1, what="dsh started")
    out = h.admin("stop", agent="dsh-1")["result"]
    assert out["interrupted_turns"] == [1]
    h.wait(lambda: h.turns()[0]["state"] == "interrupted", what="interrupted")


def test_parse_and_human_turn_units(tmp_path):
    info, u = parse((FIX / "dsh-bogus.jsonl").read_text().splitlines())
    assert not info["ok"] and info["error"].startswith("INVALID_REQUEST:") and u.calls == 0
    info, _ = parse(['{"type":"error","message":"session \\"s\\" is already owned by an active write handle"}'])
    assert info["owned"] and not info["unknown"]
    assert not human_turn(tmp_path / "missing.zstd")


def test_dsh_agent_needs_a_workspace_on_c(tmp_path, monkeypatch):
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    (tmp_path / "ws").mkdir()
    state = xinit.init(tmp_path / "ws")
    with pytest.raises(SystemExit, match="dsh needs the workspace on C:"):
        xinit.add_agent(state, "dsh-1", "dsh")
    assert json.loads(overlay({"id": "d", "model": "p/m"}, tmp_path, mcp=False))[1] == {"id": "tool-web",
                                                                                       "disabled": True}


def test_hub_prompt_hook_is_ignored(make):
    """The hub's own headless prompts (wakepack relay) never look human."""
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    h.hook_dsh("dsh-1", "UserPromptSubmit", session_id=sid,
               prompt="[xmuse] Messages relayed by xmuse, the collaboration layer")
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is False
    m = h.send("dsh-1", "second")
    h.wait_quiet()
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert len(h.turns()) == 2


def test_session_start_hook_adopts_a_desktop_session(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    old = h.q("select vendor_session from sessions")[0]["vendor_session"]
    h.hook_dsh("dsh-1", "SessionStart", session_id="desktop-new", source="desktop", cwd="C:\\ws")
    rows = h.q("select vendor_session, origin, state from sessions order by id")
    assert rows == [{"vendor_session": old, "origin": "hub", "state": "retired"},
                    {"vendor_session": "desktop-new", "origin": "tui", "state": "current"}]
    h.hook_dsh("dsh-1", "SessionStart", session_id="desktop-new", source="desktop", cwd="C:\\ws")
    assert len(h.q("select * from sessions")) == 2  # adopting the current session is a no-op


def test_dsh_hook_script_reports_to_the_hub(make):
    """dsh_hook.py as dsh runs it: event + state + agent argv, payload on stdin."""
    from xmuse.config import DSH_HOOK
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "warm up")
    h.wait_quiet()
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    payload = {"session_id": sid, "hook_event_name": "UserPromptSubmit",
               "cwd": "C:\\ws", "prompt": "typed by the human"}
    subprocess.run(["python3", str(DSH_HOOK), "UserPromptSubmit", str(h.state), "dsh-1"],
                   input=json.dumps(payload), text=True, check=True, timeout=10)
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is True
    subprocess.run(["python3", str(DSH_HOOK), "Stop", str(h.state), "dsh-1"],
                   input=json.dumps({"session_id": sid}), text=True, check=True, timeout=10)
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is False
    # never blocks dsh, even when the hub is gone
    r = subprocess.run(["python3", str(DSH_HOOK), "Stop", "/nonexistent", "dsh-1"],
                       input="{}", text=True, timeout=10)
    assert r.returncode == 0


def test_dsh_write_config_installs_workspace_hooks(tmp_path):
    from xmuse.adapters.dsh import DshDriver
    ws = tmp_path / "ws"
    ws.mkdir()
    paths = DshDriver.write_config(ws, {"id": "dsh-1"}, tmp_path / "state")
    hooks = json.loads((ws / ".dsh" / "hooks.json").read_text())
    assert set(hooks["hooks"]) == {"SessionStart", "UserPromptSubmit", "Stop"}
    for ev, groups in hooks["hooks"].items():
        [g] = groups
        [ho] = g["hooks"]
        assert ho["type"] == "command" and "xmuse-dsh-hook.py " + ev in ho["command"] \
            and "dsh-1" in ho["command"]
    assert (ws / ".dsh" / "xmuse-dsh-hook.py").read_text().startswith("#!/usr/bin/env python3")
    assert [p.name for p in paths] == ["hooks.json", "xmuse-dsh-hook.py"]
