"""Delivery engine through the dsh headless adapter, with a fake dsh replaying M0-dsh NDJSON recordings."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import wsl_hub

from xmuse import init as xinit
from xmuse.adapters.dsh import human_turn, overlay, parse

FIX = Path(__file__).parent / "fixtures"
DSH = [("dsh-1", "dsh")]
SEND = ["xmuse_send", {"to": "human", "body": "done"}]


def fixture_usage(name):
    steps = [json.loads(x)["usage"] for x in (FIX / name).open(encoding="utf-8") if '"step_end"' in x and '"usage"' in x]
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
    assert rows[0]["id"] == "llm-pi-ai" and rows[0]["config"] == {"providers": {"opencode-go": {"apiKeyEnv": "OPENCODE_GO_API_KEY"}}}
    assert rows[1]["config"] == {"provider": "opencode-go", "model": "muse-spark-1.3-contributor"}
    [mcp] = rows[2]["insert"]
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
    h.wait(lambda: h.q("select 1 from messages where kind='notice'"), what="notice")  # posted after the pause is saved
    assert any("dsh-1 paused" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    h.admin("resume", agent="dsh-1")
    h.wait(lambda: h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done",
           what="delivered after resume")


def test_unknown_session_is_retried_in_a_fresh_session(make):
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]}, {}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    (h.home / "fake-dsh" / "sessions.json").write_text("{}", encoding="utf-8")  # dsh forgot the session
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
    info, u = parse((FIX / "dsh-bogus.jsonl").read_text(encoding="utf-8").splitlines())
    assert not info["ok"] and info["error"].startswith("INVALID_REQUEST:") and u.calls == 0
    info, _ = parse(['{"type":"error","message":"session \\"s\\" is already owned by an active write handle"}'])
    assert info["owned"] and not info["unknown"]
    assert not human_turn(tmp_path / "missing.zstd")


@wsl_hub
def test_dsh_agent_needs_a_workspace_on_a_windows_drive(tmp_path, monkeypatch):
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    (tmp_path / "ws").mkdir()
    state = xinit.init(tmp_path / "ws")
    with pytest.raises(SystemExit, match="dsh needs the workspace on a Windows drive") as e:
        xinit.add_agent(state, "dsh-1", "dsh")
    assert "move the workspace under /mnt/c/" in str(e.value)
    assert json.loads(overlay({"id": "d", "model": "p/m"}, tmp_path, mcp=False))[1] == {"id": "tool-web",
                                                                                       "disabled": True}
    assert xinit._dsh_ws_ok("/mnt/c/Users/w") and xinit._dsh_ws_ok("/mnt/d/work")
    assert not xinit._dsh_ws_ok("/home/user/dev/ws")


@wsl_hub
def test_to_win_maps_mnt_drives_and_wsl_paths(monkeypatch):
    from xmuse.adapters.base import to_win
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    assert to_win("/mnt/c/Users/a/b") == r"C:\Users\a\b"
    assert to_win("/mnt/d/work") == r"D:\work"
    assert to_win("/home/user/dev/ws") == r"\\wsl.localhost\Ubuntu-24.04\home\user\dev\ws"


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
    # room binding (v1): the desktop session is adopted for room-less turns; the thread-bound hub session stays
    assert rows == [{"vendor_session": old, "origin": "hub", "state": "current"},
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
    subprocess.run([sys.executable, str(DSH_HOOK), "UserPromptSubmit", str(h.state), "dsh-1"],
                   input=json.dumps(payload), text=True, check=True, timeout=10)
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is True
    subprocess.run([sys.executable, str(DSH_HOOK), "Stop", str(h.state), "dsh-1"],
                   input=json.dumps({"session_id": sid}), text=True, check=True, timeout=10)
    assert h.hub.engine.drivers["dsh"].presence({"id": "dsh-1"}, sid).human_turn is False
    # never blocks dsh, even when the hub is gone
    r = subprocess.run([sys.executable, str(DSH_HOOK), "Stop", "/nonexistent", "dsh-1"],
                       input="{}", text=True, timeout=10)
    assert r.returncode == 0


def test_dsh_write_config_installs_workspace_hooks(tmp_path):
    from xmuse.adapters.dsh import DshDriver
    ws = tmp_path / "ws"
    ws.mkdir()
    paths = DshDriver.write_config(ws, {"id": "dsh-1"}, tmp_path / "state")
    hooks = json.loads((ws / ".dsh" / "hooks.json").read_text(encoding="utf-8"))
    assert set(hooks["hooks"]) == {"SessionStart", "UserPromptSubmit", "Stop"}
    for ev, groups in hooks["hooks"].items():
        [g] = groups
        [ho] = g["hooks"]
        assert ho["type"] == "command" and "xmuse-dsh-hook.py " + ev in ho["command"] \
            and "dsh-1" in ho["command"]
    assert (ws / ".dsh" / "xmuse-dsh-hook.py").read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")
    assert [p.name for p in paths] == ["hooks.json", "xmuse-dsh-hook.py"]


def test_presence_falls_back_to_the_session_log_without_hooks(make):
    """No hook ever seen for the session (desktop bridge not mounted): M1b log reading."""
    import zstandard
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    drv = h.hub.engine.drivers["dsh"]
    assert drv.presence({"id": "dsh-1"}, sid).human_turn is False  # quiet log, no hooks
    log = h.tmp / "dsh-home" / "sessions" / "--C-ws--" / sid / "session.v4.jsonl.zstd"
    log.parent.mkdir(parents=True)
    log.write_bytes(zstandard.ZstdCompressor().compress(
        "".join(json.dumps(r) + "\n" for r in [
            {"type": "turn/end", "data": {"turn": 1}},
            {"type": "user/message", "data": {"source": {"kind": "user", "rpcId": "r1"}}}]).encode()))
    assert drv.presence({"id": "dsh-1"}, sid).human_turn is True  # log fallback
    h.hook_dsh("dsh-1", "Stop", session_id=sid)
    assert drv.presence({"id": "dsh-1"}, sid).human_turn is False  # live hooks take over


def test_expired_human_flag_releases_admission(make):
    """A desktop closed mid-turn never sends Stop: the flag expires after turn_timeout."""
    h = make(DSH)
    h.plan_dsh({"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "first")
    h.wait_quiet()
    drv = h.hub.engine.drivers["dsh"]
    sid = h.q("select vendor_session from sessions")[0]["vendor_session"]
    h.hook_dsh("dsh-1", "UserPromptSubmit", session_id=sid, prompt="human typing")
    m = h.send("dsh-1", "while the desktop is gone")
    h.hub.engine.call(lambda: None)
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "queued"
    drv.human[sid] -= drv.cfg.get("turn_timeout", 1800) + 1  # Stop never arrives: backdate past expiry
    h.hub.engine.kick()
    h.hub.engine.call(lambda: None)
    h.wait_quiet()
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"


def test_overlay_registers_opencode_go_through_pi_ai_but_not_deepseek(tmp_path):
    oc = json.loads(overlay({"id": "d", "model": "opencode-go/m"}, tmp_path, mcp=False))
    assert oc[0] == {"id": "llm-pi-ai", "name": "@deepseek-ai/dsh-llm-pi-ai",
                     "config": {"providers": {"opencode-go": {"apiKeyEnv": "OPENCODE_GO_API_KEY"}}}}
    assert oc[1]["id"] == "agent-default-model"
    ds = json.loads(overlay({"id": "d", "model": "deepseek-official/m"}, tmp_path, mcp=False))
    assert ds[0]["id"] == "agent-default-model" and not any(r.get("id") == "llm-pi-ai" for r in ds)


def test_extra_mcp_from_agent_settings_is_mounted_after_xmuse_but_not_in_the_precheck(tmp_path):
    bench = {"name": "bench-tests", "command": "node", "args": ["C:\\phb\\mcp\\bench-tests.mjs"],
             "env": {"BENCH_WS": "/mnt/c/ws", "BENCH_PROJECT": "phb-e2"}}
    agent = {"id": "d", "model": "opencode-go/m", "settings": json.dumps({"extra_mcp": [bench]})}
    rows = json.loads(overlay(agent, tmp_path))
    names = [r["insert"][0]["config"]["serverName"] for r in rows if "insert" in r]
    assert names == ["xmuse", "bench-tests"]
    [x] = [r["insert"][0] for r in rows if "insert" in r and r["insert"][0]["id"] == "mcp-bench-tests"]
    assert x["config"] == {"serverName": "bench-tests", "transport": "stdio", "command": "node",
                           "args": ["C:\\phb\\mcp\\bench-tests.mjs"], "env": bench["env"], "failOnStartupError": True}
    assert not any("insert" in r for r in json.loads(overlay(agent, tmp_path, mcp=False)))
    assert names == [r["insert"][0]["config"]["serverName"] for r in json.loads(overlay({**agent, "settings": {"extra_mcp": [bench]}}, tmp_path)) if "insert" in r]
    for bad in ({"name": "xmuse", "command": "node"}, {"name": "a b", "command": "node"}, {"name": "x", "command": "node", "env": {"K": 1}}):
        with pytest.raises(ValueError):
            overlay({**agent, "settings": {"extra_mcp": [bad]}}, tmp_path)


def test_agent_add_extra_mcp_is_stored_for_headless_dsh_and_opencode_only(tmp_path, monkeypatch):
    from xmuse import cli, db
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "st"))
    monkeypatch.setattr(xinit, "_dsh_ws_ok", lambda ws: True)
    ws = tmp_path / "ws"
    ws.mkdir()
    cli.main(["init", str(ws)])
    spec = tmp_path / "extra.json"
    spec.write_text(json.dumps([{"name": "bench-tests", "command": "node", "args": ["x.mjs"], "env": {"BENCH_PROJECT": "p"}}]), encoding="utf-8")
    cli.main(["--ws", str(ws), "agent", "add", "d1", "--vendor", "dsh", "--extra-mcp", str(spec)])
    state = Path(json.loads((ws / ".xmuse.json").read_text(encoding="utf-8"))["state"])
    a = db.row(db.connect(state / "hub.db").execute("select * from agents where id='d1'"))
    assert db.settings(a)["extra_mcp"][0]["name"] == "bench-tests"
    cli.main(["--ws", str(ws), "agent", "add", "o1", "--vendor", "opencode", "--extra-mcp", str(spec)])
    o = db.row(db.connect(state / "hub.db").execute("select * from agents where id='o1'"))
    assert db.settings(o)["extra_mcp"][0]["name"] == "bench-tests"
    with pytest.raises(SystemExit):
        cli.main(["--ws", str(ws), "agent", "add", "c1", "--vendor", "claude", "--extra-mcp", str(spec)])


def test_launch_failure_is_retried_once_inside_the_same_turn(make):
    h = make(DSH, dsh_retry_wait=0.1)
    h.plan_dsh({"fail_start": True}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "ping")
    h.wait_quiet()
    [t] = h.turns()  # one turn record, one prompt delivery
    assert t["state"] == "succeeded" and len(h.dsh_calls()) == 2
    assert h.dsh_calls()[0]["prompt"] == h.dsh_calls()[1]["prompt"] and "--session-id" not in h.dsh_calls()[1]["argv"]


def test_launch_failing_twice_fails_the_turn_after_one_retry(make):
    h = make(DSH, dsh_retry_wait=0.1)
    h.plan_dsh({"fail_start": True}, {"fail_start": True}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed" and "exit 1" in t["error"] and len(h.dsh_calls()) == 2


def test_failure_after_the_agent_acted_is_not_retried(make):
    h = make(DSH, dsh_retry_wait=0.1)
    h.plan_dsh({"fail_mid": True}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed" and len(h.dsh_calls()) == 1


def test_stuck_launch_is_killed_by_the_first_event_watchdog_and_retried(make):
    h = make(DSH, dsh_retry_wait=0.1, dsh_first_event_timeout_s=1)
    h.plan_dsh({"hang": 30}, {"as": "dsh-1", "calls": [SEND]})
    h.send("dsh-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "succeeded" and len(h.dsh_calls()) == 2


def test_precheck_that_starts_but_never_finishes_is_killed_by_the_time_limit_and_retried_once(make):
    h = make(DSH, dsh_retry_wait=0.1, dsh_precheck_timeout_s=1)
    drv = h.hub.engine.drivers["dsh"]
    good = {"id": "dsh-1", "model": "deepseek-official/deepseek-v4-flash"}
    h.plan_dsh({"stall": 30}, {})
    assert drv.precheck(good, h.ws) is None and len(h.dsh_calls()) == 2
    h.plan_dsh({"stall": 30}, {"stall": 30})
    n = len(h.dsh_calls())
    err = drv.precheck(good, h.ws)
    assert "did not finish within 1s" in err and len(h.dsh_calls()) == n + 2


def test_precheck_retries_a_flaky_start_once_but_not_an_unknown_model(make):
    h = make(DSH, dsh_retry_wait=0.1)
    drv = h.hub.engine.drivers["dsh"]
    good = {"id": "dsh-1", "model": "deepseek-official/deepseek-v4-flash"}
    h.plan_dsh({"fail_start": True}, {})
    assert drv.precheck(good, h.ws) is None and len(h.dsh_calls()) == 2
    h.plan_dsh({"fail_start": True}, {"fail_start": True}, {})
    assert "exit 1" in drv.precheck(good, h.ws)
    bad = {"id": "dsh-1", "model": "deepseek-official/bogus-model"}
    h.plan_dsh({}, {})
    n = len(h.dsh_calls())
    assert "INVALID_REQUEST" in drv.precheck(bad, h.ws) and len(h.dsh_calls()) == n + 1
