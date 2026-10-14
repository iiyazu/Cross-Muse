"""Delivery engine through the agy headless adapter, with fake agy replaying CLI runs."""
import json
import time
from pathlib import Path

import pytest

AGY = [("agy-1", "agy")]
SEND = ["xmuse_send", {"to": "human", "body": "pong"}]


def test_turn_runs_headless_and_resumes_in_the_same_session(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"as": "agy-1", "calls": [SEND]})
    m = h.send("agy-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "succeeded" and t["adapter"] == "agy"
    [s] = h.q("select * from sessions")
    assert s["vendor_session"].startswith("session-")
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert h.q("select body from messages where sender='agy-1'")[0]["body"] == "pong"

    c1 = h.agy_calls()[0]
    assert "-p" in c1["argv"]
    assert "ping" in c1["prompt"] and "You are agy-1" in c1["prompt"]

    # Second turn resumes in same session
    h.send("agy-1", "again")
    h.wait_quiet()
    assert len(h.turns()) == 2
    assert h.turns()[1]["state"] == "succeeded"
    assert h.turns()[1]["handle"] == s["vendor_session"]

    c2 = h.agy_calls()[1]
    assert f"--conversation={s['vendor_session']}" in c2["argv"]
    assert "You are agy-1" not in c2["prompt"]


def test_coding_turn_is_flagged_code(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "code": True, "calls": [SEND]})
    h.send("agy-1", "edit main.py")
    h.wait_quiet()
    assert h.turns()[0]["mode"] == "code"


def test_turn_end_error_fails_the_turn_and_notifies(make):
    h = make(AGY)
    h.plan_agy({"result": "error"})
    m = h.send("agy-1", "bad")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed"
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "failed"


def test_quota_exceeded_sets_retry_at(make):
    h = make(AGY)
    h.plan_agy({"result": "quota"})
    m = h.send("agy-1", "quota test")
    h.wait(lambda: h.q("select paused_until from agents")[0]["paused_until"], what="paused")
    [t] = h.turns()
    assert t["state"] == "failed"
    paused = h.q("select paused_until from agents where id='agy-1'")[0]["paused_until"]
    assert paused is not None and paused > time.time()
    d = h.q("select * from deliveries where message_id=?", m["id"])[0]
    assert d["state"] == "queued"


def test_unknown_session_requeues_fresh(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"result": "unknown"}, {"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "first")
    h.wait_quiet()
    assert h.turns()[0]["state"] == "succeeded"

    h.send("agy-1", "retry in fresh")
    h.wait_quiet()
    turns = h.turns()
    # Second turn was unknown session -> retried in fresh session
    assert len(turns) >= 2


def test_stop_interrupts_running_turn(make):
    h = make(AGY)
    h.plan_agy({"result": "hang", "sleep": 30})
    m = h.send("agy-1", "hang prompt")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.admin("stop", agent="agy-1")
    h.wait_quiet()
    assert h.turns()[0]["state"] == "interrupted"
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "canceled"


def test_write_config_mounts_mcp_and_hook(make):
    h = make(AGY)
    mcp_file = h.ws / ".agents" / "plugins" / "xmuse" / "mcp_config.json"
    assert mcp_file.exists()
    mcp_cfg = json.loads(mcp_file.read_text(encoding="utf-8"))
    assert "xmuse" in mcp_cfg["mcpServers"]
    assert mcp_cfg["mcpServers"]["xmuse"]["env"]["XMUSE_AGENT"] == "agy-1"

    hooks_file = h.ws / ".agents" / "hooks.json"
    assert hooks_file.exists()
    hooks_cfg = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "xmuse-safety" in hooks_cfg
    assert hooks_cfg["xmuse-safety"]["PreToolUse"][0]["matcher"] == "*"


def test_a_429_in_a_successful_turns_output_is_not_a_quota():
    """agy's output carries timings and tool results: "0.082294294" once paused a healthy agy for an hour."""
    from xmuse.adapters.agy import _succeeded
    ok = '{"event":"step","duration_seconds":0.082294294}\n{"event":"result","result":{"status":"SUCCESS"}}\n'
    assert _succeeded(ok)
    assert not _succeeded("RESOURCE_EXHAUSTED: quota exceeded") and not _succeeded('{"event":"result","result":{}}')
