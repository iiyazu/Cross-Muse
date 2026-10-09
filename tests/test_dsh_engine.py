"""Delivery engine through the dsh headless adapter, with a fake dsh replaying M0-dsh NDJSON recordings."""
import json
from pathlib import Path

import pytest
import zstandard

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
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    log = h.tmp / "dsh-home" / "sessions" / "--C-ws--" / sid / "session.v4.jsonl.zstd"
    log.parent.mkdir(parents=True)
    rec = [{"type": "turn/end", "data": {"turn": 1}},
           {"type": "user/message", "data": {"source": {"kind": "user", "rpcId": "r1"}}}]
    write = lambda recs: log.write_bytes(zstandard.ZstdCompressor().compress(  # noqa: E731
        "".join(json.dumps(r) + "\n" for r in recs).encode()))
    write(rec)
    m = h.send("dsh-1", "while the human types")
    h.hub.engine.call(lambda: None)
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "queued"
    assert not h.q("select 1 from turns where id=2")
    write(rec + [{"type": "turn/end", "data": {"turn": 2}}])
    h.hub.engine.kick()
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
