"""Fixes from the agy alignment probe (10-13): a fresh wake pack carries the brief once, and a done re-sent in the
same turn (once with declares, once without) is one done."""
from test_onboard import pack
from test_room import act, open_room
from test_trust import OC
from xmuse import db, mail


def test_fresh_pack_carries_the_brief_once(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    act(h, ot, act="brief", text="Build a small parser.")
    text = pack(h, "opencode-1").text
    assert "Project brief:" in text and text.count("Build a small parser.") == 1
    from xmuse import wakepack
    snap = wakepack.snapshot(h.conn(), h.hub.cfg, "opencode-1")  # a bare snapshot (compaction hook) keeps it
    assert "Build a small parser." in snap


def test_replacing_a_decision_asks_the_author_of_a_restatement_to_check_it(make):
    """The probe case: the user's E6-like decision is restated by a member (E8-like); when the user replaces it,
    that member's next delta names its own entry; another member's does not. Lines say who wrote each entry."""
    from xmuse import align, wakepack
    h = make(OC)
    open_room(h, vendor="claude")
    conn, cfg = h.conn(), h.hub.cfg
    with db.tx(conn):
        old = align.declare(conn, "human", "#room", 1, "decision", "bad input raises ValueError", "global")
        mine = align.declare(conn, "opencode-1", "#room", 2, "decision", "parse() raises ValueError on bad input",
                             "global")
        other = align.declare(conn, "opencode-1", "#room", 3, "decision", "a note for one thread only")
    since = align.current_seq(conn)
    with db.tx(conn):
        new = align.declare(conn, "human", "#room", 4, "decision", "bad input returns None", supersedes=f"E{old}")
    d = wakepack.delta(conn, cfg, "opencode-1", since)
    assert f"+ E{new} [decision] bad input returns None (refs #4) · user" in d
    assert f"superseded E{old} (by E{new})" in d
    assert f"your E{mine} is in the same scope" in d and f"supersedes: E{mine}" in d
    assert f"E{other} " not in d  # another scope (its thread), not asked about
    assert "your E" not in wakepack.delta(conn, cfg, "lead", since)  # lead wrote nothing there
    snap = wakepack.snapshot(conn, cfg, "lead")
    assert "prevails" in snap and f"E{mine} [decision] parse() raises ValueError on bad input (refs #2) · opencode-1" in snap


def test_done_resent_in_one_turn_is_one_done(make):
    h = make()
    conn, cfg = h.conn(), h.hub.cfg
    with db.tx(conn):
        conn.execute("update agents set paused=1 where id='claude-1'")
        conn.execute("insert into turns(agent_id, adapter, state, started_at) values('claude-1','claude',"
                     "'running',?)", (db.now(),))
    dec = [{"kind": "decision", "statement": "dates travel as ISO strings", "scope": "global"}]
    a = mail.done(conn, "claude-1", "wrote dates.py", "human", dec, cfg=cfg)
    b = mail.done(conn, "claude-1", "wrote dates.py", "human", None, cfg=cfg)  # the same done, declares left out
    assert "duplicate" not in a and b["duplicate"] is True
    assert len(h.q("select id from messages where sender='claude-1' and kind='done'")) == 1
    c = mail.done(conn, "claude-1", "wrote dates.py", "human",
                  dec + [{"kind": "decision", "statement": "errors return None", "scope": "global"}], cfg=cfg)
    assert c["duplicate"] is True and len(c["entries"]) == 2  # only the new declare was added
    assert len(h.q("select id from entries where kind='decision'")) == 2
    d = mail.done(conn, "claude-1", "a second report", "human", None, cfg=cfg)  # a different report still posts
    assert "duplicate" not in d
