"""Panel "撤回": the user takes back one of their own messages. Pending deliveries are canceled, a running
turn that took the message is interrupted, the body is replaced everywhere it is read. Members that must not
move are paused, so the message stays queued until the test decides."""
from test_compact import pause
from test_room import act, open_room, view
from test_trust import OC
from xmuse import db


def test_retract_cancels_pending_and_blanks_the_body(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    st, out = act(h, ot, act="say", to="opencode-1", text="delete the prod table")
    assert st == 200
    mid = out["id"]
    assert h.q("select state from deliveries where message_id=?", mid)[0]["state"] == "queued"
    st, out = act(h, ot, act="retract", id=mid)
    assert st == 200 and out["canceled"] == ["opencode-1"] and out["interrupted"] == []
    assert h.q("select state from deliveries where message_id=?", mid)[0]["state"] == "canceled"
    body = h.q("select body, retracted_at from messages where id=?", mid)[0]
    assert "delete the prod table" not in body["body"] and body["retracted_at"]
    item = [m for m in view(h, ot)[1]["timeline"] if m["id"] == mid][0]
    assert item["retracted"] is True and "撤回" in item["text"]
    assert act(h, ot, act="retract", id=mid)[1]["already"] is True  # twice is harmless


def test_retract_interrupts_the_turn_that_took_it(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    mid = act(h, ot, act="say", to="opencode-1", text="rewrite everything")[1]["id"]
    with db.tx(h.conn()) as c:  # opencode-1 has taken it into a running turn
        tid = c.execute("insert into turns(agent_id, adapter, state, started_at)"
                        " values('opencode-1','opencode','running',?)", (db.now(),)).lastrowid
        c.execute("update deliveries set state='admitted', turn_id=? where message_id=?", (tid, mid))
    st, out = act(h, ot, act="retract", id=mid)
    assert st == 200 and out["interrupted"] == ["opencode-1"] and out["canceled"] == []
    assert h.q("select state from turns where id=?", tid)[0]["state"] != "running"
    assert h.q("select state from deliveries where message_id=?", mid)[0]["state"] == "canceled"


def test_retract_only_the_users_own_messages(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    pause(h, "opencode-1", "lead")
    h.tool("lead", "xmuse_send", to="#room", body="a member's note", _session="S-lead")
    other = h.q("select id from messages where sender='lead' order by id desc limit 1")[0]["id"]
    assert act(h, ot, act="retract", id=other)[0] == 403
    assert act(h, ot, act="retract", id=999999)[0] == 404
    assert act(h, ot, act="retract", id="1")[0] == 400
    mine = act(h, ot, act="say", to="#room", text="hello")[1]["id"]
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    assert act(h, lead_tok, "S-lead", act="retract", id=mine)[0] == 403  # operator only
