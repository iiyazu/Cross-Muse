"""Private small groups (T2, contract XMUSE2-VIEW-API section 8.3): making them, who is in, who is kept out, the
member-token view filter, and the error codes."""
import sqlite3
import time

from test_mail import pause
from test_room import act, call, open_room, view
from xmuse import align, db, wakepack


def trio(make, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")], **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"  # turns start and fail fast; mail is the point
    for a in ("claude-1", "claude-2", "claude-3"):
        pause(h, a)  # deliveries stay queued/passive where a test looks at them
    return h


def members(h, tid):
    return [r["member"] for r in h.q("select member from thread_members where thread_id=? order by member", tid)]


def got(h, mid):
    return {r["recipient"]: r["wake"] for r in h.q("select recipient, wake from deliveries where message_id=?", mid)}


def room_with_pair(make):
    """claude-1 and claude-2 in a private #pair made by the user; claude-3 and the coordinator `lead` outside."""
    h = trio(make)
    ot = open_room(h)["operator_token"]
    assert act(h, ot, act="thread_new", id="#pair", members=["claude-1", "claude-2"]) == (200, {"thread": "#pair"})
    return h, ot


# ---- making private groups -------------------------------------------------------------------------------------------

def test_user_makes_a_private_group_with_thread_new(make):
    h = trio(make)
    ot = open_room(h)["operator_token"]
    assert act(h, ot, act="thread_new", id="#sec", members=["claude-1", "claude-2"], title="Secret plans") == (
        200, {"thread": "#sec"})
    assert h.q("select kind, private, title from threads where id='#sec'") == [
        {"kind": "group", "private": 1, "title": "Secret plans"}]
    assert members(h, "#sec") == ["claude-1", "claude-2", "human"]  # the user is in automatically
    out = h.send("#sec", "only us", mentions=["claude-1"])
    assert out["woken"] == ["claude-1"] and got(h, out["id"]) == {"claude-1": 1, "claude-2": 0}  # nobody else
    _, v = view(h, ot)
    t = next(t for t in v["threads"] if t["id"] == "#sec")
    assert t["private"] is True and t["members"] == ["claude-1", "claude-2", "human"] and t["title"] == "Secret plans"
    assert any(m["kind"] == "system" and m["thread"] == "#sec" and "#sec" in m["text"] for m in v["timeline"])


def test_member_makes_a_private_group_by_sending_with_members(make):
    h = trio(make)
    r = h.tool("claude-1", "xmuse_send", to="#duo", body="between us", members=["claude-2"], mentions=["claude-2"])
    assert r["result"]["woken"] == ["claude-2"], r
    assert h.q("select private from threads where id='#duo'") == [{"private": 1}]
    assert members(h, "#duo") == ["claude-1", "claude-2", "human"]  # sender and user are in automatically
    assert got(h, r["result"]["id"]) == {"claude-2": 1}
    # `members` only counts when the group is created: a later send cannot pull anybody in
    r = h.tool("claude-1", "xmuse_send", to="#duo", body="more", members=["claude-3"])
    assert "result" in r and members(h, "#duo") == ["claude-1", "claude-2", "human"]
    # the same retry from a non-member is refused, not turned into a join
    assert h.tool("claude-3", "xmuse_send", to="#duo", body="let me in", members=["claude-3"])["error"][
        "code"] == "not_a_member"


def test_a_member_can_make_a_group_of_only_itself_and_the_user(make):
    h = trio(make)
    assert "result" in h.tool("claude-1", "xmuse_send", to="#notes", body="mine", members=[])
    assert members(h, "#notes") == ["claude-1", "human"]


def test_public_groups_are_unchanged(make):
    h = trio(make)
    out = h.send("#pub", "hello all", mentions=["claude-2"])
    assert h.q("select private from threads where id='#pub'") == [{"private": 0}]
    assert members(h, "#pub") == ["claude-1", "claude-2", "claude-3", "human"]
    assert got(h, out["id"]) == {"claude-1": 0, "claude-2": 1, "claude-3": 0}
    # a member who was not in the group at creation still joins by sending to it
    h.add_raw("late", "claude")
    assert "result" in h.tool("late", "xmuse_send", to="#pub", body="here too")
    assert "late" in members(h, "#pub")
    # sending without `members` to a new group keeps making public groups
    assert "result" in h.tool("claude-1", "xmuse_send", to="#open", body="x")
    assert h.q("select private from threads where id='#open'") == [{"private": 0}]


# ---- keeping non-members out -----------------------------------------------------------------------------------------

def test_non_members_get_no_delivery_cannot_read_and_cannot_write(make):
    h, ot = room_with_pair(make)
    lead_t = h.token("lead")
    out = h.send("#pair", "secret", mentions=["claude-1"])
    sent = h.tool("claude-2", "xmuse_send", to="#pair", body="secret reply")["result"]
    for mid in (out["id"], sent["id"]):
        assert not set(got(h, mid)) & {"claude-3", "lead"}  # not even a passive copy, not even the coordinator's
    assert h.q("select 1 from deliveries d join messages m on m.id=d.message_id where m.thread_id='#pair'"
               " and d.recipient in ('claude-3', 'lead')") == []
    # reading
    e = h.tool("claude-3", "xmuse_thread", id="#pair")["error"]
    assert e["code"] == "unknown_thread" and "#pair" not in e["message"].split(":", 1)[1]
    assert h.tool("claude-3", "xmuse_context", topic="#pair")["error"]["code"] == "unknown_thread"
    assert "#pair" not in h.tool("claude-3", "xmuse_whoami")["result"]["threads"]
    assert h.tool("lead", "xmuse_thread", "S-lead", id="#pair")["error"]["code"] == "unknown_thread"  # no desk right
    assert [m["body"] for m in h.tool("claude-2", "xmuse_thread", id="#pair")["result"]["messages"]][-2:] == [
        "secret", "secret reply"]
    # writing
    e = h.tool("claude-3", "xmuse_send", to="#pair", body="let me in")["error"]
    assert e["code"] == "not_a_member"
    assert h.q("select count(*) n from messages where sender='claude-3'")[0]["n"] == 0
    assert members(h, "#pair") == ["claude-1", "claude-2", "human"]  # a send is not a join
    st, body = act(h, h.token("claude-3"), act="say", to="#pair", text="via the sidebar")
    assert (st, body["error"]) == (403, "not_a_member")
    assert act(h, ot, act="say", to="#pair", text="the user is always in")[0] == 200


def test_coordinator_outside_a_private_group_gets_nothing_from_it_and_inside_gets_a_copy(make):
    h, ot = room_with_pair(make)
    n0 = h.q("select count(*) n from deliveries where recipient='lead'")[0]["n"]
    h.tool("claude-1", "xmuse_send", to="#pair", body="quiet", mentions=["claude-2"])
    act(h, ot, act="thread_add", thread="#pair", member="claude-3")  # hub notice in the group
    assert h.q("select count(*) n from deliveries where recipient='lead'")[0]["n"] == n0
    act(h, ot, act="thread_add", thread="#pair", member="lead")
    out = h.tool("claude-1", "xmuse_send", to="#pair", body="now lead hears")["result"]
    assert got(h, out["id"]).get("lead") == 0  # passive copy, as in any thread with the user
    assert "result" in h.tool("lead", "xmuse_thread", "S-lead", id="#pair")


def test_thread_entries_of_a_private_group_stay_out_of_non_member_packs(make):
    h, _ = room_with_pair(make)
    since = align.current_seq(h.conn())
    assert "result" in h.tool("claude-1", "xmuse_send", to="#pair", body="the codeword is plum", kind="decision")
    assert "result" in h.tool("claude-1", "xmuse_send", to="#pair", body="mind the budget", kind="question")
    with h.conn() as c:
        assert "codeword is plum" in wakepack.snapshot(c, h.hub.cfg, "claude-2")
        assert "codeword is plum" in wakepack.delta(c, h.hub.cfg, "claude-2", since)
        assert wakepack.snapshot(c, h.hub.cfg, "claude-3") == ""
        assert wakepack.delta(c, h.hub.cfg, "claude-3", since) == ""
        for text in (wakepack.snapshot(c, h.hub.cfg, "lead"), wakepack.delta(c, h.hub.cfg, "lead", since)):
            assert "plum" not in text
    ctx = h.tool("claude-3", "xmuse_context")["result"]
    assert "thread:#pair" not in ctx["layers"] and "plum" not in str(ctx)
    assert "codeword is plum" in str(h.tool("claude-2", "xmuse_context", topic="#pair")["result"])


# ---- adding and removing ---------------------------------------------------------------------------------------------

def test_adding_a_member_gives_it_the_threads_snapshot_and_later_mail(make):
    h, ot = room_with_pair(make)
    h.tool("claude-1", "xmuse_send", to="#pair", body="the codeword is plum", kind="decision")
    with h.conn() as c:  # claude-3 has a session that was already shown everything it may see
        sid = c.execute("insert into sessions(agent_id, origin, created_at) values('claude-3','hub',?)",
                        (time.time(),)).lastrowid
        c.execute("insert into seen values(?,?)", (sid, align.current_seq(c)))
    assert act(h, ot, act="thread_add", thread="#pair", member="claude-3") == (200, {"ok": True})
    assert members(h, "#pair") == ["claude-1", "claude-2", "claude-3", "human"]
    assert h.q("select * from seen") == []  # next wake: a snapshot, not a delta
    with h.conn() as c:
        assert "Thread #pair:\nE1 [decision] the codeword is plum" in wakepack.snapshot(c, h.hub.cfg, "claude-3")
    notices = h.q("select body from messages where thread_id='#pair' and kind='notice' order by id")
    assert notices[-1]["body"] == "claude-3 was added to #pair"
    out = h.send("#pair", "welcome", mentions=["claude-3"])
    assert got(h, out["id"])["claude-3"] == 1
    assert h.tool("claude-3", "xmuse_send", to="#pair", body="thanks")["result"]["thread"] == "#pair"
    n = h.q("select count(*) n from messages where kind='notice'")[0]["n"]
    assert act(h, ot, act="thread_add", thread="#pair", member="claude-3") == (200, {"ok": True})  # already in: no-op
    assert h.q("select count(*) n from messages where kind='notice'")[0]["n"] == n


def test_removing_a_member_stops_delivery_and_cancels_what_it_had_not_taken(make):
    h, ot = room_with_pair(make)
    before = h.send("#pair", "before", mentions=["claude-2"])
    assert h.q("select state from deliveries where message_id=? and recipient='claude-2'", before["id"]) == [
        {"state": "queued"}]
    assert act(h, ot, act="thread_remove", thread="#pair", member="claude-2") == (200, {"ok": True})
    assert members(h, "#pair") == ["claude-1", "human"]
    assert h.q("select state from deliveries where message_id=? and recipient='claude-2'", before["id"]) == [
        {"state": "canceled"}]
    assert h.tool("claude-2", "xmuse_inbox")["result"] == []
    after = h.send("#pair", "after", mentions=["claude-1"])
    assert got(h, after["id"]) == {"claude-1": 1}
    assert h.q("select body from messages where thread_id='#pair' and kind='notice' order by id desc limit 1") == [
        {"body": "claude-2 was removed from #pair"}]
    assert h.tool("claude-2", "xmuse_thread", id="#pair")["error"]["code"] == "unknown_thread"
    assert h.tool("claude-2", "xmuse_send", to="#pair", body="still here?")["error"]["code"] == "not_a_member"
    # its other mail is untouched
    other = h.send("claude-2", "unrelated")
    assert got(h, other["id"]) == {"claude-2": 1}
    # coming back means a snapshot again
    act(h, ot, act="thread_add", thread="#pair", member="claude-2")
    assert members(h, "#pair") == ["claude-1", "claude-2", "human"]


def test_a_member_leaves_a_private_group_it_is_in(make):
    h, _ = room_with_pair(make)
    assert h.tool("claude-2", "xmuse_leave_thread", thread="#pair")["result"] == {"ok": True, "thread": "#pair"}
    assert members(h, "#pair") == ["claude-1", "human"]
    assert h.q("select body from messages where thread_id='#pair' and kind='notice' order by id desc limit 1") == [
        {"body": "claude-2 left #pair"}]
    out = h.send("#pair", "after", mentions=["claude-1"])
    assert got(h, out["id"]) == {"claude-1": 1}
    assert h.tool("claude-2", "xmuse_thread", id="#pair")["error"]["code"] == "unknown_thread"
    # leaving twice, leaving a group one was never in, and leaving a public group
    assert h.tool("claude-2", "xmuse_leave_thread", thread="#pair")["error"]["code"] == "unknown_thread"
    assert h.tool("claude-3", "xmuse_leave_thread", thread="#pair")["error"]["code"] == "unknown_thread"
    assert h.tool("claude-3", "xmuse_leave_thread", thread="#nowhere")["error"]["code"] == "unknown_thread"
    h.send("#pub", "hi")
    assert h.tool("claude-3", "xmuse_leave_thread", thread="#pub")["error"]["code"] == "public_thread"
    assert "claude-3" in members(h, "#pub")
    assert h.tool("claude-3", "xmuse_leave_thread")["error"]["code"] == "invalid_arguments"


# ---- error codes -----------------------------------------------------------------------------------------------------

def test_thread_acts_errors(make):
    h, ot = room_with_pair(make)
    h.send("#pub", "a public group")
    new = lambda **kw: act(h, ot, act="thread_new", **kw)  # noqa: E731
    err = lambda r: (r[0], r[1]["error"])  # noqa: E731
    assert err(new(id="#pair", members=["claude-3"])) == (409, "thread_exists")
    assert err(new(id="#pub", members=["claude-3"])) == (409, "thread_exists")  # also a public group
    assert err(new(id="#room", members=[])) == (409, "thread_exists")
    assert err(new(id="#fresh", members=["claude-1", "ghost"])) == (400, "unknown_member")
    assert h.q("select 1 from threads where id='#fresh'") == []  # nothing half-made
    assert err(new(id="fresh", members=[]))[0] == 400
    assert err(new(id="#fresh"))[0] == 400
    assert err(new(id="#fresh", members="claude-1"))[0] == 400
    assert err(act(h, ot, act="thread_add", thread="#pub", member="claude-3")) == (400, "public_thread")
    assert err(act(h, ot, act="thread_remove", thread="#pub", member="claude-1")) == (400, "public_thread")
    assert err(act(h, ot, act="thread_add", thread="#pair", member="ghost")) == (400, "unknown_member")
    assert err(act(h, ot, act="thread_add", thread="#nothing", member="claude-3")) == (404, "unknown_thread")
    assert err(act(h, ot, act="thread_remove", thread="#nothing", member="claude-3")) == (404, "unknown_thread")
    assert err(act(h, ot, act="thread_remove", thread="#pair", member="claude-3")) == (400, "not_in_thread")
    assert err(act(h, ot, act="thread_remove", thread="#pair", member="human"))[0] == 400
    assert members(h, "#pair") == ["claude-1", "claude-2", "human"]
    # a member is told no
    for body in ({"act": "thread_new", "id": "#x", "members": []},
                 {"act": "thread_add", "thread": "#pair", "member": "claude-3"},
                 {"act": "thread_remove", "thread": "#pair", "member": "claude-2"}):
        st, out = call(h, "POST", "/v1/act", body, h.token("claude-1"))
        assert (st, out["error"]) == (403, "operator_only")
    # tool-side errors
    e = h.tool("claude-1", "xmuse_send", to="#oops", body="x", members=["ghost"])["error"]
    assert e["code"] == "unknown_member" and "claude-2" in e["message"]
    assert h.q("select 1 from threads where id='#oops'") == [] and h.q("select 1 from messages where body='x'") == []
    assert h.tool("claude-1", "xmuse_send", to="#oops", body="x", members="claude-2")["error"]["code"] == \
        "invalid_arguments"


# ---- the sidebar view ------------------------------------------------------------------------------------------------

def test_member_token_view_holds_only_its_threads_and_room(make):
    h, ot = room_with_pair(make)
    h.tool("claude-1", "xmuse_send", to="#pair", body="pair secret", kind="decision")
    h.send("#pub", "public chatter")
    h.tool("claude-1", "xmuse_send", to="claude-2", body="a dm of others")
    h.tool("claude-3", "xmuse_send", to="human", body="my own dm with the user")
    seen = lambda v: {t["id"] for t in v["threads"]}  # noqa: E731
    texts = lambda v: {t["text"] for t in v["timeline"]}  # noqa: E731
    _, v3 = view(h, h.token("claude-3"))
    assert seen(v3) == {"#pub", "#room", "dm:claude-3+human"}
    assert "public chatter" in texts(v3) and "my own dm with the user" in texts(v3)
    assert not {"pair secret", "a dm of others"} & texts(v3) and not any(t["thread"] == "#pair" for t in v3["timeline"])
    assert all(isinstance(t["private"], bool) for t in v3["threads"]) and not any(t["private"] for t in v3["threads"])
    assert all(e["scope"] != "thread:#pair" for e in v3["alignment"])
    _, v2 = view(h, h.token("claude-2"))
    assert seen(v2) == {"#pair", "#pub", "#room", "dm:claude-1+claude-2"}
    assert "pair secret" in texts(v2) and "a dm of others" in texts(v2)
    assert next(t for t in v2["threads"] if t["id"] == "#pair")["private"] is True
    assert any(e["scope"] == "thread:#pair" for e in v2["alignment"])
    # the user's operator token still sees everything
    _, vo = view(h, ot)
    assert {"#pair", "#pub", "#room", "dm:claude-1+claude-2", "dm:claude-3+human"} <= seen(vo)
    assert {"pair secret", "public chatter", "a dm of others", "my own dm with the user"} <= texts(vo)
    assert any(e["scope"] == "thread:#pair" for e in vo["alignment"])
    # the coordinator's member token is a member's too: outside the group, no group
    _, vl = call(h, "GET", "/v1/view?since=0&wait=0", None, h.token("lead"), "S-lead")
    assert "#pair" not in seen(vl) and "pair secret" not in texts(vl)


def test_timeline_paging_is_filtered_for_member_tokens(make):
    h, ot = room_with_pair(make)
    for i in range(60):
        h.send("#pair", f"private {i}")
        h.send("#pub", f"public {i}")
    t3 = h.token("claude-3")
    _, v = view(h, t3)
    assert len(v["timeline"]) == 50 and v["timeline_cursor"]["has_more"]
    assert all(t["thread"] != "#pair" for t in v["timeline"]) and v["timeline"][-1]["text"] == "public 59"
    st, older = call(h, "GET", f"/v1/timeline?before={v['timeline_cursor']['oldest']}&limit=50", None, t3)
    assert st == 200 and not older["has_more"] and all(t["thread"] != "#pair" for t in older["items"])
    assert len(older["items"]) >= 10 and {"public 0", "public 9"} <= {t["text"] for t in older["items"]}
    # a member of the group pages through both
    st, p = call(h, "GET", "/v1/timeline?limit=200", None, h.token("claude-1"))
    assert any(t["thread"] == "#pair" for t in p["items"]) and any(t["thread"] == "#pub" for t in p["items"])
    # and the user's token sees all of it
    st, p = call(h, "GET", "/v1/timeline?limit=200", None, ot)
    assert {t["thread"] for t in p["items"]} >= {"#pair", "#pub"}


# ---- the schema ------------------------------------------------------------------------------------------------------

def test_an_old_database_without_the_private_column_opens(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("create table threads(id text primary key, kind text not null, title text not null default '',"
                " owner text, created_at real not null)")
    old.execute("insert into threads(id, kind, created_at) values('#g', 'group', 1.0)")
    old.commit()
    old.close()
    conn = db.init(path)
    assert tuple(conn.execute("select id, private from threads").fetchone()) == ("#g", 0)
    db.init(path).close()  # and again: the migration is idempotent
