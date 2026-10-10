"""Pure pieces: vendor stream parsing, transcript usage and forks, wake-pack rendering, sweep."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from xmuse import db, mail, wakepack
from xmuse.adapters.claude import branch_points, parse_stream, transcript, transcript_usage
from xmuse.adapters.opencode import OpenCodePrompt, Tracked
from xmuse.adapters.base import TurnSpec

FIX = Path(__file__).parent / "fixtures"


def test_parse_stream_uses_per_run_result_and_last_call_context():
    lines = (FIX / "claude-chat.jsonl").read_text().splitlines(keepends=True)
    info, u = parse_stream(lines)
    res = [json.loads(x) for x in lines if '"type": "result"' in x][0]
    assert info["ok"] and info["session"] == res["session_id"] and info["denied"] == []
    assert u.cache_read == res["usage"]["cache_read_input_tokens"] and u.output == res["usage"]["output_tokens"]
    last = [json.loads(x) for x in lines if '"type": "assistant"' in x][-1]["message"]["usage"]
    assert u.context == last["input_tokens"] + last["cache_read_input_tokens"] + last["cache_creation_input_tokens"]
    assert u.model == "claude-opus-5-5" and u.mode == "chat"
    assert u.calls == len({json.loads(x)["message"]["id"] for x in lines if '"type": "assistant"' in x})


def test_parse_stream_without_result_is_not_ok():
    lines = [x for x in (FIX / "claude-chat.jsonl").read_text().splitlines() if '"type": "result"' not in x]
    info, u = parse_stream(lines + ["not json", ""])
    assert not info.get("ok") and u.total == 0 and u.context > 0


def test_branch_points(tmp_path):
    p = tmp_path / "s.jsonl"
    assert branch_points(p) == 0
    rows = [("a", None, "user"), ("b", "a", "assistant"), ("c", "b", "user"), ("d", "b", "user"),
            ("e", "c", "assistant"), ("s", "e", "assistant")]
    with p.open("w") as f:
        for u, parent, typ in rows:
            f.write(json.dumps({"type": typ, "uuid": u, "parentUuid": parent,
                                "isSidechain": u == "s"}) + "\n")
        f.write(json.dumps({"type": "system", "uuid": "x", "parentUuid": "b"}) + "\n")
        # parallel tool calls: two tool_use records under one parent, results under each (not a fork)
        res = {"content": [{"type": "tool_result", "tool_use_id": "t"}]}
        for u, parent, typ, msg in (("p1", "e", "assistant", {}), ("p2", "p1", "assistant", {}),
                                    ("r1", "p1", "user", res), ("r2", "p2", "user", res)):
            f.write(json.dumps({"type": typ, "uuid": u, "parentUuid": parent, "message": msg}) + "\n")
    assert branch_points(p) == 1


def test_transcript_path_matches_claude_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert transcript(Path("/home/u/dev/my_ws.1"), "sid") == \
        tmp_path / ".claude" / "projects" / "-home-u-dev-my-ws-1" / "sid.jsonl"


def test_transcript_usage_counts_only_new_calls_once(tmp_path):
    p = tmp_path / "t.jsonl"
    old = "2020-01-01T00:00:00.000Z"
    new = "2030-01-01T00:00:00.500Z"
    u = {"input_tokens": 1, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 10, "output_tokens": 5}
    with p.open("w") as f:
        for ts, mid in ((old, "m0"), (new, "m1"), (new, "m1"), (new, "m2")):
            f.write(json.dumps({"type": "assistant", "timestamp": ts, "message": {
                "id": mid, "model": "x", "usage": u, "content": [{"type": "text", "text": "hi"}]}}) + "\n")
        f.write(json.dumps({"type": "user", "timestamp": new}) + "\n")
    got = transcript_usage(p, since=time.time())
    assert (got.calls, got.cache_read, got.output, got.context, got.mode) == (2, 200, 10, 111, "chat")


def test_host_facts_are_derived_or_a_clear_error(tmp_path, monkeypatch):
    import pytest
    from xmuse import host
    monkeypatch.setenv("XMUSE_WSL_DISTRO", "Debian")
    assert host.distro() == "Debian"  # the override wins over WSL_DISTRO_NAME
    monkeypatch.delenv("XMUSE_WSL_DISTRO")
    monkeypatch.delenv("WSL_DISTRO_NAME")
    with pytest.raises(SystemExit, match="XMUSE_WSL_DISTRO"):
        host.distro()
    assert host.win_home() == tmp_path / "winhome"  # XMUSE_WIN_HOME (conftest)
    monkeypatch.delenv("XMUSE_WIN_HOME")
    monkeypatch.setenv("PATH", str(tmp_path))  # no cmd.exe / wslpath: not WSL, or interop off
    host._userprofile.cache_clear()
    try:
        with pytest.raises(SystemExit, match="XMUSE_WIN_HOME"):
            host.win_home()
    finally:
        host._userprofile.cache_clear()


def test_channel_stop_waits_for_late_transcript_flush(tmp_path):
    """The Stop hook can beat the TUI's transcript write; the turn's usage must not be recorded as 0."""
    import threading
    from xmuse.adapters.claude import ClaudeChannel

    class Sink:
        def __init__(self): self.ended, self.done = [], threading.Event()
        def turn_ended(self, e): self.ended.append(e); self.done.set()

    sink, p = Sink(), tmp_path / "t.jsonl"
    p.write_text("")
    ch = ClaudeChannel(sink, None)
    ch.turns["s1"] = {"turn_id": 7, "since": time.time(), "cwd": tmp_path}
    assert ch.stopped("s1", str(p)) and not sink.ended  # nothing flushed yet: not ended with zeros
    ts = datetime.now(timezone.utc).isoformat()
    u = {"input_tokens": 2, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 0, "output_tokens": 9}
    p.write_text(json.dumps({"type": "assistant", "timestamp": ts, "message": {
        "id": "m1", "model": "x", "usage": u, "content": [{"type": "text", "text": "ok"}]}}) + "\n")
    assert sink.done.wait(5)
    assert (sink.ended[0].turn_id, sink.ended[0].usage.context, sink.ended[0].usage.calls) == (7, 302, 1)


def test_opencode_event_accounting_dedupes_and_flags_code(tmp_path):
    class Sink:
        ended, kicked = [], 0

        def turn_ended(self, e): self.ended.append(e)
        def kick(self): Sink.kicked += 1
        def approval(self, *a): pass

    p = OpenCodePrompt.__new__(OpenCodePrompt)
    p.sink, p.turns, p.human = Sink(), {}, {}
    import threading
    p.lock = threading.Lock()
    spec = TurnSpec(5, {"id": "opencode-1"}, "ses_1", "x", tmp_path, tmp_path / "t.jsonl")
    p.turns["ses_1"] = Tracked(spec)
    evs = [json.loads(x) for x in (FIX / "oc-code.events.jsonl").open()]
    for ev in evs:
        if "sessionID" in (ev.get("data") or {}):
            ev["data"]["sessionID"] = "ses_1"
    steps = [e for e in evs if e["type"] == "session.step.ended"]
    for ev in evs + steps:  # replayed step events are counted once
        if ev["type"].startswith("session.execution."):
            continue
        p.handle(ev)
    p.handle({"type": "session.inbox.delivered", "data": {"sessionID": "ses_1"}})
    p.handle({"type": "session.execution.succeeded", "data": {"sessionID": "ses_1"}})
    [end] = Sink.ended
    assert end.turn_id == 5 and end.status == "succeeded" and end.usage.mode == "code"
    assert end.usage.calls == len(steps) and end.usage.model == "muse-spark-1.3-contributor-free"
    # a human execution on another session only kicks
    p.handle({"type": "session.inbox.enqueued", "data": {"sessionID": "ses_2", "item": {"payload": {"text": "hi"}}}})
    assert p.human == {"ses_2": True}
    p.handle({"type": "session.execution.succeeded", "data": {"sessionID": "ses_2"}})
    assert p.human == {} and Sink.kicked == 1 and len(Sink.ended) == 1


def test_wakepack_tags_relay_and_passive_summary(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude")])
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    h.send("#g", "background chatter")
    h.tool("claude-2", "xmuse_send", to="claude-1", body="handing over", kind="handoff",
           why={"what": "w", "why": "y", "tradeoff": "t", "open_questions": "none", "next_action": "n"})
    conn = h.conn()
    agent = db.row(conn.execute("select * from agents where id='claude-1'"))
    msgs = db.rows(conn.execute("select * from messages where sender='claude-2'"))
    cfg = {**h.hub.cfg, "recent_n": 5}
    text = wakepack.render(conn, cfg, agent, msgs, None, "/w").text
    assert text.startswith("[xmuse] Messages relayed by xmuse") and "collaborators the user assigned" in text
    assert "You are claude-1 (anthropic) in workspace /w. Peers: claude-2 (anthropic)" in text
    assert '<xmuse from="claude-2" family="anthropic" thread="dm:claude-1+claude-2" kind="handoff" id="2">' in text
    assert "next_action: n" in text and "Also 1 unread message(s)" in text
    resume = wakepack.render(conn, cfg, agent, msgs, 1, "/w").text
    assert "You are" not in resume and "Earlier in" not in resume


def test_wakepack_recent_thread_excludes_new_messages(make):
    h = make()
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    for i in range(12):
        mail.notice(h.conn(), "#g", f"old {i}")
    m = h.send("#g", "new one", mentions=["claude-1"])
    conn = h.conn()
    agent = db.row(conn.execute("select * from agents"))
    text = wakepack.render(conn, h.hub.cfg, agent, db.rows(conn.execute("select * from messages where id=?", (m["id"],))),
                           None, "/w").text
    earlier = text.split("Earlier in #g (most recent 8):\n")[1].split("\n\n")[0]
    assert earlier.count("\n- ") == 7 and "old 11" in earlier and "old 3" not in earlier and "new one" not in earlier


def test_sweep_interrupts_turns_past_the_timeout(make):
    h = make(turn_timeout=1)
    h.plan_claude({"sleep": 30})
    h.send("claude-1", "slow")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    time.sleep(1.2)
    h.hub.engine.call(h.hub.engine.sweep)
    # SIGINT, then SIGTERM after 5 s if the fake has not exited: under a loaded full run that can pass 10 s
    h.wait(lambda: h.q("select state from turns")[0]["state"] == "interrupted", timeout=20, what="interrupted")


def test_engine_call_propagates_errors(make):
    h = make()
    try:
        h.hub.engine.call(lambda: 1 / 0)
    except ZeroDivisionError:
        pass
    else:
        raise AssertionError("no error")
    assert h.hub.engine.call(lambda a: a + 1, 1) == 2


def test_chat_wake_over_50k_warns_but_code_wake_does_not(make, caplog):
    """Task 2 / v2-1: only chat wakes over chat_warn_tokens warn; code wakes never do."""
    import logging
    h = make()
    h.plan_claude({"as": "claude-1", "calls": [["xmuse_send", {"to": "human", "body": "hi"}]]},
                  {"fixture": "claude-code.jsonl"})
    h.send("claude-1", "chat hi")
    with caplog.at_level(logging.WARNING, logger="xmuse.engine"):
        h.wait_quiet()
    assert any("chat wake over 50000 tokens" in r.getMessage() for r in caplog.records)
    caplog.clear()
    h.send("claude-1", "code edit")
    with caplog.at_level(logging.WARNING, logger="xmuse.engine"):
        h.wait_quiet()
    assert h.turns()[1]["mode"] == "code" and h.turns()[1]["state"] == "succeeded"
    assert not [r for r in caplog.records if "wake over" in r.getMessage()]
