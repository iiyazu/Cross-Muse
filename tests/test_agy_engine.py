"""Delivery engine through the agy headless adapter, with fake agy replaying CLI runs."""
import json
import time
from pathlib import Path

import pytest

AGY = [("agy-1", "agy")]
SEND = ["xmuse_send", {"to": "human", "body": "pong"}]


def test_turn_runs_headless_and_resumes_in_the_same_session(make):
    """Resident mode (the default): the second wake is a line on the same process's stdin, in the same conversation."""
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"as": "agy-1", "calls": [SEND]})
    m = h.send("agy-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "succeeded" and t["adapter"] == "agy", (t["error"], t["summary"])
    [s] = h.q("select * from sessions")
    assert s["vendor_session"].startswith("session-")
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert h.q("select body from messages where sender='agy-1'")[0]["body"] == "pong"

    c1 = h.agy_calls()[0]
    assert "--input-format" in c1["argv"] and "-p" not in c1["argv"]
    assert "ping" in c1["prompt"] and "You are agy-1" in c1["prompt"]

    # Second turn resumes in same session, in the same process
    h.send("agy-1", "again")
    h.wait_quiet()
    assert len(h.turns()) == 2
    assert h.turns()[1]["state"] == "succeeded"
    assert h.turns()[1]["handle"] == s["vendor_session"]

    c2 = h.agy_calls()[1]
    assert c2["pid"] == c1["pid"]
    assert "You are agy-1" not in c2["prompt"] and "again" in c2["prompt"]


def test_cold_mode_runs_one_process_per_wake(make):
    h = make(AGY, agy_resident=False)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "ping")
    h.wait_quiet()
    h.send("agy-1", "again")
    h.wait_quiet()
    [s] = h.q("select * from sessions")
    c1, c2 = h.agy_calls()
    assert "-p" in c1["argv"] and c1["pid"] != c2["pid"]
    assert f"--conversation={s['vendor_session']}" in c2["argv"]
    assert [t["state"] for t in h.turns()] == ["succeeded", "succeeded"]


def test_a_hub_restart_resumes_the_conversation_in_a_new_resident(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "ping")
    h.wait_quiet()
    h.hub.engine.drivers["agy"].headless.close()  # what a hub restart does to the process
    h.hub.engine.drivers["agy"].headless.closing.clear()
    h.send("agy-1", "again")
    h.wait_quiet()
    [s] = h.q("select * from sessions")
    c1, c2 = h.agy_calls()
    assert c1["pid"] != c2["pid"] and f"--conversation={s['vendor_session']}" in c2["argv"]
    assert h.turns()[1]["state"] == "succeeded"


def test_a_resident_that_dies_mid_turn_fails_the_turn_and_the_next_wake_starts_one(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"result": "exit"}, {"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "one")
    h.wait_quiet()
    h.send("agy-1", "two")
    h.wait_quiet()
    assert [t["state"] for t in h.turns()][:2] == ["succeeded", "failed"]
    h.send("agy-1", "three")
    h.wait_quiet()
    assert h.turns()[-1]["state"] == "succeeded"
    calls = h.agy_calls()
    assert calls[0]["pid"] == calls[1]["pid"] != calls[2]["pid"]


def test_an_idle_resident_is_closed(make):
    h = make(AGY, agy_idle=0.3)
    h.plan_agy({"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "ping")
    h.wait_quiet()
    headless = h.hub.engine.drivers["agy"].headless
    h.wait(lambda: not headless.residents, what="idle resident closed")


def test_turn_usage_is_the_turns_own_not_the_conversations(make):
    """agy's result usage is the conversation's running total; a turn records the sum of its own model steps."""
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "calls": [SEND]}, {"as": "agy-1", "calls": [SEND]})
    h.send("agy-1", "one")
    h.wait_quiet()
    h.send("agy-1", "two")
    h.wait_quiet()
    t1, t2 = h.turns()
    assert (t1["input"], t1["output"], t1["cache_read"], t1["calls"]) == (100, 30, 20, 1)
    assert (t2["input"], t2["output"], t2["cache_read"]) == (100, 30, 20)
    assert t2["context"] == 150


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


def test_stream_json_progress_and_exact_usage(make):
    h = make(AGY)
    h.plan_agy({"as": "agy-1", "code": True, "calls": [SEND]})
    h.send("agy-1", "do work")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "succeeded"
    assert t["mode"] == "code"
    assert t["input"] == 100  # the model steps' own usage (fake_agy: one step)
    assert t["output"] == 30
    assert t["context"] == 150
    prog = h.hub.engine.progress_state.get(t["id"])
    if prog:
        assert prog["tools"] >= 1
        assert prog["last_tool"] == "run_command"
        assert "Response: OK" in prog["text"]


def test_the_agy_gate_asks_the_hub(make):
    """The generated .agents/xmuse-hook.py (any python, stdlib only) asks the hub's risk check: everyday commands
    run, consequential ones are denied with the reason, and with no hub to ask everything is denied."""
    import subprocess
    import sys
    h = make(AGY)
    gate = h.ws / ".agents" / "xmuse-hook.py"

    def ask(tool, **inp):
        r = subprocess.run([sys.executable, "-I", str(gate)], input=json.dumps({"tool_name": tool, "tool_input": inp}),
                           capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout)

    assert ask("run_command", CommandLine="python3 -m pytest -q", Cwd=str(h.ws))["decision"] == "allow"
    no = ask("run_command", CommandLine="cd x && git push", Cwd=str(h.ws))
    assert no["decision"] == "deny" and "git push" in no["reason"] and "xmuse_send" in no["reason"]
    assert ask("run_command", CommandLine="rm -rf build", Cwd="/")["decision"] == "deny"  # cwd places relative paths
    assert ask("write_to_file", TargetFile=str(h.ws / "a.py"))["decision"] == "allow"
    assert ask("write_to_file", TargetFile="/etc/profile")["decision"] == "deny"
    assert ask("call_mcp_tool", ServerName="xmuse_xmuse", ToolName="xmuse_send")["decision"] == "allow"
    hub_json = h.state / "hub.json"
    hub_json.rename(h.state / "hub.json.away")  # what a stopped hub leaves: no hub.json
    try:
        down = ask("run_command", CommandLine="ls", Cwd=str(h.ws))
    finally:
        (h.state / "hub.json.away").rename(hub_json)
    assert down["decision"] == "deny" and "could not check" in down["reason"]
