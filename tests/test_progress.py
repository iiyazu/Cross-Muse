"""H4 live progress in members[].progress + H13 auto-forwarded turn replies.

Members are desktop (never run by the hub): turns are fabricated rows, and engine._on_end is driven directly,
so nothing wakes spuriously and no broadcast pitfall applies."""
import time
from pathlib import Path

from xmuse import db, mail
from xmuse import room as rooms
from xmuse.adapters.base import TurnEnd, Usage

FIX = Path(__file__).parent / "fixtures"


def team(make, **cfg):
    h = make([("coord", "claude", {"desktop": True}), ("e1", "claude", {"desktop": True}),
              ("e2", "claude", {"desktop": True})], **cfg)
    with h.conn() as c:
        c.execute("insert into room(id, name, dir, host, created_at) values('r-t', 'dev', ?, 'coord', ?)",
                  (str(h.ws), time.time()))
    return h


def mkturn(h, agent="e1", thread="#g", state="running"):
    with h.conn() as c:
        ch = c.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at)"
                       " values(?, ?, 5, 1000000, 0)", (thread, f"agent:{agent}")).lastrowid
        tid = c.execute("insert into turns(agent_id, session_id, adapter, chain_id, state, started_at)"
                        " values(?, null, 'opencode', ?, ?, 0)", (agent, ch, state)).lastrowid
    return tid, ch


def end(h, tid, status="succeeded", reply=None, session=None, error=None):
    h.hub.engine.call(lambda: h.hub.engine._on_end(TurnEnd(tid, status, session, Usage(), error, None, None, None, reply)))
    return tid


def hub_texts(h):
    return [r["body"] for r in h.q("select body from messages where sender=?", "e1")]


# ---- H13 ------------------------------------------------------------------

def test_reply_is_forwarded_as_member_message_without_waking(make):
    h = team(make)
    tid, _ = mkturn(h)
    end(h, tid, reply="hello done")
    [m] = h.q("select thread_id, sender, kind, body, via from messages where turn_id is null and sender='e1'")
    assert (m["thread_id"], m["sender"], m["kind"], m["body"], m["via"]) == ("#g", "e1", "message", "hello done", "auto_reply")
    assert h.q("select * from deliveries where wake=1") == []
    assert h.q("select * from messages where kind='notice' and body like '%reached no one%'") == []


def test_empty_reply_keeps_the_notice(make):
    h = team(make)
    for reply in (None, "", "   "):
        tid, _ = mkturn(h)
        end(h, tid, reply=reply)
    assert len(h.q("select * from messages where kind='notice' and body like '%reached no one%'")) == 3
    assert h.q("select * from messages where sender='e1'") == []


def test_long_reply_is_truncated(make):
    h = team(make)
    tid, _ = mkturn(h)
    limit = h.hub.cfg["body_limit"]
    end(h, tid, reply="x" * (limit + 100))
    [m] = h.q("select body from messages where sender='e1'")
    assert len(m["body"]) == limit + len("\n…（正文过长，已截断）") and m["body"].endswith("已截断）")


def test_dm_wake_gets_dm_reply(make):
    h = team(make)
    tid, _ = mkturn(h, thread="dm:e1+human")
    end(h, tid, reply="on it")
    [m] = h.q("select thread_id, body from messages where sender='e1'")
    assert (m["thread_id"], m["body"]) == ("dm:e1+human", "on it")
    assert h.q("select * from deliveries where wake=1") == []


# ---- H13 adapter sources --------------------------------------------------

def test_dsh_parse_keeps_last_text_as_reply():
    from xmuse.adapters.dsh import parse, scan_line
    import pathlib
    lines = (pathlib.Path("tests/fixtures/dsh-chat.jsonl")).read_text(encoding="utf-8").splitlines()
    info, _ = parse(lines)
    assert info["reply"] == "Acknowledged to hub: `ok-d1-1`."
    assert scan_line('{"type": "tool_call", "tool": "bash"}') == ("tool", "bash")
    assert scan_line('{"type": "text", "text": "hi"}') == ("text", "hi")
    assert scan_line('{"type": "final", "text": "done"}') == ("final", "done")
    assert scan_line("not json") is None and scan_line('{"type": "status"}') is None


def test_claude_parse_stream_keeps_result_and_scan_folds_lines():
    from xmuse.adapters.claude import parse_stream, scan_claude_line
    lines = ['{"type": "assistant", "message": {"id": "m1", "model": "x", "usage": {},'
             ' "content": [{"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "hi"}]}}',
             '{"type": "result", "subtype": "success", "result": "all done", "usage": {}}']
    info, _ = parse_stream(lines)
    assert info["reply"] == "all done"
    acc = {"tools": 0, "last_tool": None, "text": ""}
    assert scan_claude_line(acc, lines[0]) is True
    assert (acc["tools"], acc["last_tool"], acc["text"]) == (1, "Bash", "hi")
    assert scan_claude_line(acc, lines[1]) is False
    assert scan_claude_line(acc, "garbage") is False


def test_opencode_handle_tracks_tools_text_and_reply(tmp_path):
    import json
    import threading
    from xmuse.adapters.opencode import OpenCodePrompt, Tracked
    from xmuse.adapters.base import TurnSpec

    class Sink:
        def __init__(self): self.ended, self.prog = [], []
        def turn_ended(self, e): self.ended.append(e)
        def kick(self): pass
        def approval(self, *a): pass
        def progress(self, turn_id, update): self.prog.append((turn_id, update))

    sink = Sink()
    p = OpenCodePrompt.__new__(OpenCodePrompt)
    p.sink, p.turns, p.human, p.known = sink, {}, {}, set()
    p.lock = threading.Lock()
    spec = TurnSpec(5, {"id": "opencode-1"}, "ses_1", "x", tmp_path, tmp_path / "t.jsonl")
    p.turns["ses_1"] = Tracked(spec)
    evs = [json.loads(x) for x in (FIX / "oc-chat.events.jsonl").open(encoding="utf-8")]
    for ev in evs:
        if "sessionID" in (ev.get("data") or {}):
            ev["data"]["sessionID"] = "ses_1"
        if ev["type"].startswith("session.execution."):
            continue
        p.handle(ev)
    kinds = [e for e in evs if e["type"] in ("session.tool.called", "session.text.ended")]
    assert kinds and sink.prog  # progress flowed while handling
    assert sink.prog[-1][0] == 5 and sink.prog[-1][1]["tools"] >= 1
    p.handle({"type": "session.inbox.delivered", "data": {"sessionID": "ses_1"}})
    p.handle({"type": "session.execution.succeeded", "data": {"sessionID": "ses_1"}})
    [end] = sink.ended
    assert end.reply == "ok"


# ---- H4 -------------------------------------------------------------------

def test_progress_shows_in_members_and_clears_on_end(make):
    h = team(make)
    tid, _ = mkturn(h)
    eng = h.hub.engine
    eng.progress(tid, {"tools": 9, "last_tool": "bash", "text": "y" * 500})
    [m] = [x for x in rooms.members(h.conn(), h.hub.cfg) if x["id"] == "e1"]
    assert m["progress"]["turn"] == tid and m["progress"]["tools"] == 9
    assert m["progress"]["last_tool"] == "bash" and len(m["progress"]["text"]) == 400
    assert [x for x in rooms.members(h.conn(), h.hub.cfg) if x["id"] == "e2"][0]["progress"] is None
    end(h, tid)
    [m] = [x for x in rooms.members(h.conn(), h.hub.cfg) if x["id"] == "e1"]
    assert m["progress"] is None


def test_progress_bumps_version_at_most_twice_a_second(make):
    from xmuse import room as rooms2
    h = team(make)
    tid, _ = mkturn(h)
    eng = h.hub.engine
    seen = set()
    for i in range(20):
        eng.progress(tid, {"tools": i, "text": "t"})
        seen.add(rooms2.fingerprint(h.conn()))
    assert len(seen) <= 3  # at most two version advances within one second
