"""Context compaction (T8 H3): hub-written instructions, opencode trigger, auto-compact,
manual compact/stop acts, view fields. External calls (the opencode compact API) are faked;
no real agent runs here. Members that must not move are paused."""
import json
import threading
import time
import types

from test_room import act, call, open_room, view
from test_trust import OC
from xmuse import align, db


def pause(h, *agents):
    with db.tx(h.conn()) as c:
        for a in agents:
            c.execute("update agents set paused=1 where id=?", (a,))


def test_instructions_carry_requirements_assignments_and_brief(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    act(h, ot, act="brief", text="Build a parser.")
    h.tool("lead", "xmuse_send", to="opencode-1", body="parse this file", kind="handoff",
           why={"what": "w", "why": "y", "tradeoff": "t", "open_questions": "none", "next_action": "n"},
           _session="S-lead")
    from xmuse import compact as mod
    text = mod.instructions(h.conn(), h.hub.cfg, "opencode-1")
    assert "当前任务和进度" in text and "测试结果行原文" in text and "删掉排查过程" in text
    assert "parse this file" in text  # its assignment
    assert "[brief] Build a parser." in text
    for i in range(30):  # over budget: cut to 2000 tokens, fixed part survives
        align.assign(h.conn(), "lead", "#room", 1, "do part %d with a very long description text. " % i * 10,
                     ["opencode-1"], [])
    text = mod.instructions(h.conn(), h.hub.cfg, "opencode-1")
    assert "当前任务和进度" in text and "[brief] Build a parser." in text
    assert len(text) // 3 <= 2000 + 200


def test_write_config_carries_the_compaction_prompt(tmp_path):
    from xmuse.adapters.opencode import write_config
    ws, state = tmp_path / "ws", tmp_path / "state"
    ws.mkdir()
    agent = {"id": "oc-1", "settings": "{}"}
    write_config(ws, agent, state, "PROMPT-1")
    import json
    inst = json.loads((state / "oc" / "oc-1" / "opencode.json").read_text(encoding="utf-8"))
    assert inst["agent"] == {"compaction": {"prompt": "PROMPT-1"}}
    write_config(ws, agent, state)
    inst = json.loads((state / "oc" / "oc-1" / "opencode.json").read_text(encoding="utf-8"))
    assert "agent" not in inst


class FakeServer:
    """An opencode server double: records compact POSTs, never runs anything."""

    def __init__(self):
        self.calls = []
        self.base = "http://127.0.0.1:9/"

    def api(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {"ok": True}

    def events(self):
        while True:
            time.sleep(3600)
            yield {}


def driver_with(sink, agent_id="oc-1"):
    from xmuse.adapters.opencode import OpenCodeDriver, OpenCodePrompt
    drv = OpenCodeDriver.__new__(OpenCodeDriver)
    drv.sink, drv.servers, drv.autostart, drv.prompts, drv.lock = sink, {}, False, {}, threading.Lock()
    srv = FakeServer()
    drv.servers[agent_id] = srv
    prompt = OpenCodePrompt(sink, srv)
    drv.prompts[srv.base] = prompt
    return drv, srv, prompt


def test_driver_compact_posts_waits_and_returns(make):
    h = make()  # default member claude-1; the fake server never runs anything
    got = {}
    sink = types.SimpleNamespace(db=h.conn, ws=h.ws, state=h.state,
                                 cfg=h.hub.cfg, compacted=lambda sid: got.setdefault("compacted", sid))
    drv, srv, prompt = driver_with(sink, "claude-1")
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("out", drv.compact("claude-1", "ses-1", "INSTR", timeout=5)),
                         daemon=True)
    t.start()
    h.wait(lambda: ("POST", "/api/session/ses-1/compact", {"delivery": "steer"}) in srv.calls, what="compact POST")
    prompt.handle({"type": "session.compaction.ended", "data": {"sessionID": "ses-1"}})
    t.join(5)
    assert box["out"] == {"ok": True} and got["compacted"] == "ses-1"  # watermark path also fires
    with open(h.state / "oc" / "claude-1" / "opencode.json", encoding="utf-8") as f:
        assert json.load(f)["agent"] == {"compaction": {"prompt": "INSTR"}}
    # failed event: no watermark reset, error out
    t2 = threading.Thread(target=lambda: box.setdefault("out2", drv.compact("claude-1", "ses-1", "I", timeout=5)),
                          daemon=True)
    t2.start()
    h.wait(lambda: ("POST", "/api/session/ses-1/compact", {"delivery": "steer"}) in srv.calls[1:], what="compact POST")
    prompt.handle({"type": "session.compaction.failed", "data": {"sessionID": "ses-1", "error": "boom"}})
    t2.join(5)
    assert box["out2"] == {"ok": False, "error": "compaction failed: boom"}
    assert got["compacted"] == "ses-1"  # still only the ended one
    out = drv.compact("claude-1", "ses-1", "I", timeout=0.2)
    assert out == {"ok": False, "error": "no compaction end event within 0.2s"}


def test_manual_compact_ok_busy_unsupported_and_auth(make, monkeypatch):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    with db.tx(h.conn()) as c:
        c.execute("insert into sessions(agent_id, vendor_session, origin, state, created_at)"
                  " values('opencode-1','ses-oc','hub','current',?)", (db.now(),))
    gate = threading.Event()
    calls = []

    class FakeDriver:
        def close(self):
            pass

        def compact(self, agent_id, session_id, instructions, timeout=300):
            calls.append((agent_id, session_id, instructions))
            assert "当前任务和进度" in instructions
            gate.wait(15)
            return {"ok": True}

    monkeypatch.setitem(h.hub.engine.drivers, "opencode", FakeDriver())
    st, out = act(h, ot, act="compact", member="opencode-1")
    assert (st, out) == (200, {"ok": True})
    assert h.q("select compacting from sessions where vendor_session='ses-oc'") == [{"compacting": 1}]
    gate.set()
    h.wait(lambda: h.q("select compacting from sessions where vendor_session='ses-oc'")[0]["compacting"] == 0,
           what="flag cleared")
    assert any("opencode-1 已压缩" in m["body"] for m in
               h.q("select body from messages where kind='notice'"))  # the notice
    assert calls and calls[0][1] == "ses-oc"
    with db.tx(h.conn()) as c:  # busy: a running turn
        c.execute("insert into turns(agent_id, adapter, state, started_at) values('opencode-1','opencode','running',?)",
                  (db.now(),))
    try:
        st, out = act(h, ot, act="compact", member="opencode-1")
        assert (st, out["error"]) == (409, "busy")
    finally:
        with db.tx(h.conn()) as c:
            c.execute("delete from turns where agent_id='opencode-1'")
    assert act(h, ot, act="compact", member="lead")[1]["error"] == "unsupported"  # claude: never hub-compacted
    assert act(h, ot, act="compact", member="ghost")[0] == 404
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    assert act(h, lead_tok, "S-lead", act="compact", member="opencode-1")[0] == 403


def test_auto_compact_fires_once_resets_and_skips(make, monkeypatch):
    h = make(OC)
    open_room(h, vendor="claude")
    calls = []

    class FakeDriver:
        def close(self):
            pass

        def compact(self, agent_id, session_id, instructions, timeout=300):
            calls.append((agent_id, session_id))
            return {"ok": True}

    monkeypatch.setitem(h.hub.engine.drivers, "opencode", FakeDriver())
    with db.tx(h.conn()) as c:
        c.execute("insert into sessions(agent_id, vendor_session, origin, state, context_tokens, created_at)"
                  " values('opencode-1','ses-big','hub','current',600000,?)", (db.now(),))
    h.hub.engine._compact_tick(h.conn())
    h.wait(lambda: len(calls) == 1, what="auto launch")
    assert calls == [("opencode-1", "ses-big")]
    assert h.q("select auto_compacted from sessions where vendor_session='ses-big'") == [{"auto_compacted": 1}]
    h.hub.engine._compact_tick(h.conn())
    assert len(calls) == 1  # same session: not twice
    with db.tx(h.conn()) as c:  # dropped back under: mark resets...
        c.execute("update sessions set context_tokens=100 where vendor_session='ses-big'")
    h.hub.engine._compact_tick(h.conn())
    assert h.q("select auto_compacted from sessions where vendor_session='ses-big'") == [{"auto_compacted": 0}]
    with db.tx(h.conn()) as c:  # ...so re-exceeding fires again
        c.execute("update sessions set context_tokens=700000 where vendor_session='ses-big'")
    h.hub.engine._compact_tick(h.conn())
    h.wait(lambda: len(calls) == 2, what="auto relaunch")
    with db.tx(h.conn()) as c:  # a queued wake blocks it...
        c.execute("insert into deliveries(message_id, recipient, wake, state, updated_at)"
                  " values(1,'opencode-1',1,'queued',?)", (db.now(),))
        c.execute("insert into sessions(agent_id, vendor_session, origin, state, context_tokens, created_at)"
                  " values('opencode-1','ses-hold','hub','current',800000,?)", (db.now(),))
    h.hub.engine._compact_tick(h.conn())
    assert len(calls) == 2
    with db.tx(h.conn()) as c:  # ...as does a running turn
        c.execute("delete from deliveries where recipient='opencode-1'")
        c.execute("insert into turns(agent_id, adapter, state, started_at)"
                  " values('opencode-1','opencode','running',?)", (db.now(),))
    try:
        h.hub.engine._compact_tick(h.conn())
        assert len(calls) == 2
    finally:
        with db.tx(h.conn()) as c:
            c.execute("delete from turns where agent_id='opencode-1'")


def test_view_fields_and_instructions_endpoint(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    with db.tx(h.conn()) as c:
        c.execute("insert into turns(agent_id, adapter, state, started_at) values('opencode-1','opencode','succeeded',?)",
                  (db.now(),))
        tid = c.execute("select id from turns where agent_id='opencode-1'").fetchone()[0]
        c.execute("insert into usage(turn_id, agent_id, vendor, model, mode, input, cache_read, cache_write,"
                  " output, context, calls, created_at) values(?, 'opencode-1','opencode','m','chat',"
                  " 1,2,3,4,123456,5,?)", (tid, db.now()))
        c.execute("insert into sessions(agent_id, vendor_session, origin, state, compacting, created_at)"
                  " values('opencode-1','ses-1','hub','current',1,?)", (db.now(),))
    _, v = view(h, ot)
    m = next(m for m in v["members"] if m["id"] == "opencode-1")
    assert (m["context_tokens"], m["compacting"]) == (123456, True)
    assert next(m for m in v["members"] if m["id"] == "lead")["context_tokens"] == 0
    st, out = call(h, "GET", "/v1/compact_instructions?member=opencode-1", None, ot)
    assert st == 200 and "当前任务和进度" in out["text"]
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    assert call(h, "GET", "/v1/compact_instructions?member=opencode-1", None, lead_tok, "S-lead")[0] == 403
    assert call(h, "GET", "/v1/compact_instructions?member=ghost", None, ot)[1]["error"] == "unknown_member"


def test_stop_stops_running_and_reports_idle(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    with db.tx(h.conn()) as c:
        c.execute("insert into turns(agent_id, adapter, state, started_at)"
                  " values('opencode-1','opencode','running',?)", (db.now(),))
    st, out = act(h, ot, act="stop", member="opencode-1")
    assert st == 200 and out == {"ok": True, "stopped": True}
    assert h.q("select state from turns where agent_id='opencode-1'")[0]["state"] != "running"
    st, out = act(h, ot, act="stop", member="opencode-1")
    assert (st, out) == (200, {"ok": True, "stopped": False})
    assert act(h, ot, act="stop", member="ghost")[0] == 404
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    assert act(h, lead_tok, "S-lead", act="stop", member="opencode-1")[0] == 403
