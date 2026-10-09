"""Watermark, snapshot/delta alignment injection, budgets, body cap, size notice, per-turn metrics."""
from xmuse import align, db, mail, wakepack

DECISION = "decision"


def two(make, **cfg):
    return make([("claude-1", "claude"), ("claude-2", "claude")], **cfg)


def declare(h, body, agent="claude-2", **kw):
    r = h.tool(agent, "xmuse_send", to="#g", body=body, kind=kw.pop("kind", DECISION), **kw)
    assert "result" in r, r
    return r["result"]


def wake(h, text="go"):
    n = len(h.claude_calls())
    h.send("claude-1", text)
    h.wait_quiet()
    return h.claude_calls()[n]["prompt"]


def agent_row(h, aid="claude-1"):
    return db.row(h.conn().execute("select * from agents where id=?", (aid,)))


def test_first_wake_is_a_snapshot_then_only_deltas(make):
    h = two(make)
    h.plan_claude({}, {}, {}, {})
    declare(h, "ids are int", scope="global")
    declare(h, "tokens are tuples")
    p1 = wake(h)
    assert "[alignment: current shared decisions" in p1 and "Project-wide:\nE1 [decision] ids are int (refs #1)" in p1
    assert "Thread #g:\nE2 [decision] tokens are tuples (refs #2)" in p1
    assert p1.index("You are claude-1") < p1.index("[alignment") < p1.index("New for you:")
    assert h.q("select seq from seen")[0]["seq"] == align.current_seq(h.conn()) == 2
    declare(h, "ids are Decimal strings", scope="global", supersedes="E1")
    declare(h, "which float?", kind="question")
    p2 = wake(h)
    assert "[alignment update since your last wake]" in p2 and "[alignment:" not in p2 and "You are" not in p2
    assert "+ E3 [decision] ids are Decimal strings (refs #" in p2 and "+ E4 [question] which float? (refs #" in p2
    assert 'superseded E1 (by E3): was "ids are int"' in p2
    p3 = wake(h)
    assert "alignment" not in p3
    t = h.turns()
    assert [(x["align_mode"], x["align_tokens"] > 0) for x in t[:3]] == [("snapshot", True), ("delta", True), ("none", False)]


def test_delta_text_is_stable_and_complete(make):
    h = two(make)
    declare(h, "task rule")                      # E1
    declare(h, "which float?", kind="question")  # E2
    declare(h, "old plan")                       # E3
    declare(h, "dev only", scope="role:dev")     # E4 (not in claude-1's scope)
    since = align.current_seq(h.conn())
    declare(h, "float64", resolves=["E2"])       # E5, resolves E2
    declare(h, "new plan", supersedes="E3")      # E6
    declare(h, "gone soon")                      # E7
    declare(h, "gone sooner", supersedes="E7")   # E8 (E7 was never shown)
    text = wakepack.delta(h.conn(), h.hub.cfg, "claude-1", since)
    assert text == "\n".join([
        "[alignment update since your last wake]",
        "+ E5 [decision] float64 (refs #5)",
        "+ E6 [decision] new plan (refs #6)",
        "+ E8 [decision] gone sooner (refs #8)",
        'superseded E3 (by E6): was "old plan"',
        "resolved E2"])
    assert text == wakepack.delta(h.conn(), h.hub.cfg, "claude-1", since)
    since = align.current_seq(h.conn())
    align.close_thread(h.conn(), "#g")
    assert wakepack.delta(h.conn(), h.hub.cfg, "claude-1", since) == \
        "[alignment update since your last wake]\narchived: thread #g, 4 entries"
    assert wakepack.delta(h.conn(), h.hub.cfg, "claude-1", align.current_seq(h.conn())) == ""


def test_over_budget_delta_lists_counts_and_snapshot_truncates(make):
    h = two(make, align_delta_tokens=40, align_snapshot_tokens=60)
    since = align.current_seq(h.conn())
    for i in range(6):
        declare(h, f"decision number {i} with some words")
    d = wakepack.delta(h.conn(), h.hub.cfg, "claude-1", since)
    assert d.endswith("6 new, 0 superseded, 0 resolved, 0 archived; too many to list, call xmuse_context")
    s = wakepack.snapshot(h.conn(), h.hub.cfg, "claude-1")
    assert 0 < s.count("\nE") < 6 and "more not shown (call xmuse_context)" in s
    assert wakepack.tokens(s) < 60 + 60


def test_snapshot_budget_keeps_assigned_work_first(make):
    h = two(make, align_snapshot_tokens=40)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    for i in range(5):
        declare(h, f"filler decision number {i}")
    why = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
    h.tool("claude-2", "xmuse_send", to="#g", body="do the thing", kind="handoff", why=why, mentions=["claude-1"])
    s = wakepack.snapshot(h.conn(), h.hub.cfg, "claude-1")
    assert s.splitlines()[1] == "Assigned to you; ready now: E6:"
    assert "E6 [assignment] do the thing -> claude-1 (refs #6)" in s


def test_removed_watermark_means_snapshot_again(make):
    h = two(make)
    h.plan_claude({}, {})
    declare(h, "ids are int", scope="global")
    wake(h)
    sid = h.q("select id from sessions")[0]["id"]
    assert align.watermark(h.conn(), sid) == 1
    align.reset_watermark(h.conn(), sid)
    assert align.watermark(h.conn(), sid) is None
    p = wake(h)
    assert "[alignment: current shared decisions" in p and "You are" not in p
    assert h.turns()[1]["align_mode"] == "snapshot"


def test_joining_a_thread_with_entries_means_snapshot_again(make):
    h = two(make)
    h.plan_claude({}, {}, {})
    declare(h, "task rule")                              # E1 in #g, which claude-3 is not a member of
    h.add_raw("claude-3", "claude")
    n = len(h.claude_calls())
    h.send("claude-3", "hello")
    h.wait_quiet()
    assert "task rule" not in h.claude_calls()[n]["prompt"] and len(h.q("select * from seen")) == 1
    assert "result" in h.tool("claude-3", "xmuse_send", to="claude-1", body="a new dm: no entries to miss")
    h.wait_quiet()
    assert len(h.q("select * from seen where session_id in (select id from sessions where agent_id='claude-3')")) == 1
    assert "result" in h.tool("claude-3", "xmuse_send", to="#g", body="joining the group")  # now a member of #g
    assert h.q("select * from seen where session_id in (select id from sessions where agent_id='claude-3')") == []
    n = len(h.claude_calls())
    h.send("claude-3", "again")
    h.wait_quiet()
    p = h.claude_calls()[n]["prompt"]
    assert "[alignment: current" in p and "Thread #g:\nE1 [decision] task rule (refs #" in p


def test_failed_turn_drops_the_watermark(make):
    h = two(make)
    h.plan_claude({}, {"result": "error"}, {})
    declare(h, "ids are int", scope="global")
    wake(h)
    wake(h)
    assert h.q("select * from seen") == []
    assert "[alignment: current" in wake(h)


def test_equal_state_renders_byte_identical(make):
    h = two(make)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    declare(h, "b rule", scope="global")
    declare(h, "a rule")
    agent = agent_row(h)
    m = h.send("claude-1", "go")
    msgs = db.rows(h.conn().execute("select * from messages where id=?", (m["id"],)))
    a = wakepack.render(h.conn(), h.hub.cfg, agent, msgs, None, "/w")
    b = wakepack.render(h.conn(), h.hub.cfg, agent, msgs, None, "/w")
    assert a.text == b.text and a.seq == b.seq == 2 and a.mode == "snapshot"


def test_send_body_limit(make):
    h = two(make)
    e = h.tool("claude-1", "xmuse_send", to="#g", body="x" * 4001)["error"]
    assert e["code"] == "body_too_long" and "4001" in e["message"] and "file in the workspace" in e["message"]
    assert "result" in h.tool("claude-1", "xmuse_send", to="#g", body="x" * 4000)
    assert h.q("select count(*) n from messages")[0]["n"] == 1


def test_size_notice_once_per_session(make):
    h = two(make, session_notice_tokens=1000)
    h.plan_claude({}, {}, {})
    wake(h)
    wake(h)
    ns = h.q("select thread_id, body from messages where body like '%session holds%'")
    assert len(ns) == 1 and ns[0]["thread_id"] == "dm:claude-1+human" and "claude-1 session holds about" in ns[0]["body"]
    assert h.q("select notified from sessions") == [{"notified": 1}]


def test_no_size_notice_below_threshold(make):
    h = two(make)
    h.plan_claude({})
    wake(h)
    assert h.q("select * from messages where body like '%session holds%'") == []


def test_old_database_gets_the_new_columns(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("create table turns(id integer primary key); create table sessions(id integer primary key);")
    c.close()
    conn = db.init(p)
    assert {"align_tokens", "align_mode"} <= {r[1] for r in conn.execute("pragma table_info(turns)")}
    assert "notified" in {r[1] for r in conn.execute("pragma table_info(sessions)")}
    db.init(p)  # idempotent


def test_retried_done_in_the_same_turn_declares_once(make):
    h = two(make)
    conn, cfg = h.conn(), h.hub.cfg
    with db.tx(conn):
        chain = conn.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at)"
                             " values(?,?,?,?,?)", ("#g", "agent:claude-1", 9, 9, db.now())).lastrowid
        conn.execute("insert into turns(agent_id, adapter, chain_id, state, started_at) values(?,?,?,?,?)",
                     ("claude-1", "claude_resume", chain, "running", db.now()))
    decl = [{"kind": "decision", "statement": "tokens are tuples"}]
    a = mail.done(conn, "claude-1", "parsed", "none", decl)
    b = mail.done(conn, "claude-1", "parsed", "none", decl)
    assert a["entries"] == b["entries"] == ["E1"] and b["duplicate"] is True and "duplicate" not in a
    assert conn.execute("select count(*) from entries").fetchone()[0] == 1
    assert conn.execute("select count(*) from messages where kind='done'").fetchone()[0] == 1
    c = mail.done(conn, "claude-1", "parsed", "none", decl + [{"kind": "assumption", "statement": "utf-8"}])
    assert c["entries"] == ["E2", "E3"] and "duplicate" not in c
    assert b["thread"] == "#g"
