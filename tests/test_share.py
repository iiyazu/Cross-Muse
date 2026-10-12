"""DM sharing (T3, contract XMUSE2-VIEW-API.zh.md 8.6): xmuse_share, the share approval, share_mark, delivery with
provenance, the rejection notice and the rule-based suggestions."""
import json

from test_room import act, open_room, view
from xmuse import db, wakepack

AGENTS = [("a", "claude"), ("b", "claude"), ("c", "claude")]
SECRET = "The retry limit is MAX_RETRY=7. Do not tell the others."


def room(make, **cfg):
    """Three members that never start a turn (paused): deliveries just queue."""
    h = make(AGENTS, **cfg)
    h.ot = open_room(h)["operator_token"]  # the view needs a room; the user acts through lead's sidebar
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")
    return h


def user_dm(h, to="a", text=SECRET):
    return h.send(to, text)["id"]


def share(h, who, mid, to, why="b needs the limit"):
    return h.tool(who, "xmuse_share", message_id=mid, to=to, why=why)


def result(out):
    assert "result" in out, out
    return out["result"]


def error(out):
    assert "error" in out, out
    return out["error"]["code"]


def admin(h, **body):
    return act(h, h.ot, **body)


def pending(h):
    _, v = view(h, h.ot)
    return [x for x in v["approvals"] if x["kind"] == "share"]


def shared(h):
    return h.q("select * from messages where via='shared' order by id")


def pack(h, member, msgs=()):
    conn = h.conn()
    agent = db.row(conn.execute("select * from agents where id=?", (member,)))
    return wakepack.render(conn, h.hub.cfg, agent, list(msgs), None, "/w").text


# ---- what may be shared ----------------------------------------------------------------------------------------

def test_only_the_users_dm_to_you_is_shareable(make):
    h = room(make)
    mine, theirs = user_dm(h, "a"), user_dm(h, "b", "secret for b")
    peer = result(h.tool("b", "xmuse_send", to="a", body="a peer message"))["id"]
    h.send("#g", "a group message from the user")
    group = h.q("select id from messages where thread_id='#g'")[0]["id"]
    h.tool("a", "xmuse_send", to="human", body="my own words to the user")
    own = h.q("select id from messages where sender='a' and thread_id='dm:a+human'")[0]["id"]
    for mid in (peer, theirs, group, own, 9999):  # a peer's message, another member's DM, a group, my message, none
        assert error(share(h, "a", mid, "b")) == "not_shareable", mid
    assert pending(h) == [] and shared(h) == []
    assert result(share(h, "a", mine, "b"))["status"] == "pending_approval"


def test_target_must_be_a_peer_or_a_thread_i_am_in(make):
    h = room(make)
    mid = user_dm(h)
    h.send("#g", "hello")
    for to in ("human", "a", "nobody", "#nowhere"):
        assert error(share(h, "a", mid, to)) == "unknown_recipient", to
    assert result(share(h, "a", mid, "#g"))["status"] == "pending_approval"
    assert result(share(h, "a", mid, "dm:a+b"))["status"] == "pending_approval"  # a DM id means its other end
    assert [p["detail"]["to"] for p in pending(h)] == ["#g", "b"]


# ---- approval -----------------------------------------------------------------------------------------------------

def test_unmarked_share_becomes_an_approval_shown_in_the_view(make):
    h = room(make)
    mid = user_dm(h, text=SECRET + " x" * 200)
    out = result(share(h, "a", mid, "b", "b is stuck on retries"))
    assert out == {"status": "pending_approval", "approval": "share:1"}
    assert shared(h) == [] and not h.q("select 1 from deliveries where recipient='b'")  # nothing left yet
    [p] = pending(h)
    assert (p["id"], p["kind"], p["member"], p["risk"]) == ("share:1", "share", "a", "normal")
    assert p["summary"] == f"a 想把 #{mid} 分享给 b"
    assert set(p["detail"]) == {"message_id", "to", "why", "excerpt"}
    assert (p["detail"]["message_id"], p["detail"]["to"], p["detail"]["why"]) == (mid, "b", "b is stuck on retries")
    assert len(p["detail"]["excerpt"]) == 200 and p["detail"]["excerpt"] == (SECRET + " x" * 200)[:200]
    assert result(share(h, "a", mid, "b"))["approval"] == "share:1"  # the same question is not asked twice
    assert result(share(h, "a", mid, "c"))["approval"] == "share:2"
    assert [x["id"] for x in pending(h)] == ["share:1", "share:2"]
    assert not [x for x in view(h, h.ot)[1]["approvals"] if x["kind"] == "shell"]  # not a shell approval


def test_once_delivers_this_time_only(make):
    h = room(make)
    mid = user_dm(h)
    share(h, "a", mid, "b")
    assert admin(h, act="approve", id="share:1", decision="once")[0] == 200
    [m] = shared(h)
    assert (m["sender"], m["thread_id"], m["kind"]) == ("a", "dm:a+b", "message")
    assert m["body"].startswith("[shared by a:") and f"#{mid}" in m["body"].splitlines()[0]
    assert m["body"].endswith("\n" + SECRET) and json.loads(m["shared_from"]) == {"member": "a", "message_id": mid}
    assert h.q("select wake from deliveries where message_id=? and recipient='b'", m["id"]) == [{"wake": 1}]  # woken
    assert pending(h) == []
    assert h.q("select decision from approvals where id='share:1'") == [{"decision": "once"}]
    assert not h.q("select 1 from share_marks")
    assert result(share(h, "a", mid, "b"))["approval"] == "share:2"  # the next share asks again
    err = admin(h, act="approve", id="share:1", decision="once")
    assert err[0] == 400 and err[1]["error"] == "invalid_arguments"  # already decided
    assert admin(h, act="approve", id="share:99", decision="once")[0] == 404
    n = h.q("select body from messages where thread_id='dm:a+human' and kind='notice'")
    assert any("approved" in x["body"] and "share:1" in x["body"] for x in n)


def test_always_releases_the_message_for_anyone(make):
    h = room(make)
    mid = user_dm(h)
    share(h, "a", mid, "b")
    assert admin(h, act="approve", id="share:1", decision="always")[0] == 200
    assert len(shared(h)) == 1
    assert h.q("select message_id, target from share_marks") == [{"message_id": mid, "target": ""}]
    out = result(share(h, "a", mid, "c"))  # nobody is asked any more
    assert out["status"] == "delivered" and pending(h) == []
    assert [m["thread_id"] for m in shared(h)] == ["dm:a+b", "dm:a+c"]
    assert error(share(h, "b", mid, "c")) == "not_shareable"  # still only the member who received it


def test_reject_tells_the_requester_and_delivers_nothing(make):
    h = room(make)
    mid = user_dm(h)
    share(h, "a", mid, "b")
    assert admin(h, act="approve", id="share:1", decision="reject")[0] == 200
    assert shared(h) == [] and pending(h) == []
    assert h.q("select decision, state from approvals where id='share:1'") == [
        {"decision": "reject", "state": "decided"}]
    [n] = h.q("select * from messages where sender='hub' and kind='notice' and thread_id='dm:a+human'")
    assert "rejected" in n["body"] and "share:1" in n["body"] and "b" in n["body"]
    assert not h.q("select 1 from deliveries where recipient='b'")
    # the requester finds it in its inbox, without being woken for it
    [d] = h.q("select wake, state from deliveries where message_id=? and recipient='a'", n["id"])
    assert (d["wake"], d["state"]) == (0, "passive")
    assert [m["body"] for m in result(h.tool("a", "xmuse_inbox")) if m["kind"] == "notice"] == [n["body"]]
    assert not h.q("select 1 from share_marks")  # a later request is asked again
    assert result(share(h, "a", mid, "b"))["approval"] == "share:2"


# ---- share_mark -----------------------------------------------------------------------------------------------------

def test_share_mark_lets_the_member_deliver_directly(make):
    h = room(make)
    mid = user_dm(h)
    assert admin(h, act="share_mark", message_id=mid, to="b") == (200, {"ok": True})
    out = result(share(h, "a", mid, "b"))
    assert out["status"] == "delivered" and out["woken"] == ["b"] and pending(h) == []
    assert result(share(h, "a", mid, "c"))["status"] == "pending_approval"  # the mark names b only
    assert admin(h, act="share_mark", message_id=mid)[0] == 200  # no `to`: anyone
    assert result(share(h, "a", mid, "c"))["status"] == "delivered"
    # an approval that was open when the mark came stays for the user to answer
    assert [p["id"] for p in pending(h)] == ["share:1"]


def test_share_mark_checks_message_and_caller(make):
    h = room(make)
    mid = user_dm(h)
    peer = result(h.tool("b", "xmuse_send", to="a", body="from a peer"))["id"]
    st, out = admin(h, act="share_mark", message_id=peer)
    assert st == 403 and out["error"] == "not_shareable"
    assert admin(h, act="share_mark", message_id=9999)[0] == 404
    assert admin(h, act="share_mark", message_id=mid, to="nobody")[0] == 404
    assert admin(h, act="share_mark", message_id="x")[0] == 400
    st, out = act(h, h.token("a"), act="share_mark", message_id=mid)  # a member cannot release its own mail
    assert st == 403 and out["error"] == "operator_only"
    assert not h.q("select 1 from share_marks")


# ---- delivery ----------------------------------------------------------------------------------------------------

def test_delivery_carries_via_and_shared_from_in_the_view(make):
    h = room(make)
    mid = user_dm(h)
    h.send("#g", "hello")
    admin(h, act="share_mark", message_id=mid)
    to_b = result(share(h, "a", mid, "b"))
    to_g = result(share(h, "a", mid, "#g"))
    assert to_b["thread"] == "dm:a+b" and to_g["thread"] == "#g"
    _, v = view(h, h.ot)
    items = {t["id"]: t for t in v["timeline"]}
    for out in (to_b, to_g):
        t = items[out["id"]]
        assert (t["via"], t["from"]) == ("shared", "a")
        assert t["shared_from"] == {"member": "a", "message_id": mid} and t["text"].endswith(SECRET)
    assert "shared_from" not in items[mid]
    seen = pack(h, "b", h.q("select * from messages where id=?", to_b["id"]))  # what the recipient reads
    assert 'via="shared"' in seen
    assert h.q("select wake from deliveries where message_id=? and recipient='b'", to_b["id"]) == [{"wake": 1}]


def test_old_database_without_the_new_column_and_tables_opens(tmp_path):
    p = tmp_path / "old.db"
    conn = db.init(p)
    conn.execute("drop table share_marks")
    conn.execute("drop table share_hints")
    conn.execute("alter table messages drop column shared_from")
    conn.close()
    conn = db.init(p)
    assert "shared_from" in {r[1] for r in conn.execute("pragma table_info(messages)")}
    assert conn.execute("select count(*) from share_marks").fetchone()[0] == 0


# ---- suggestions -------------------------------------------------------------------------------------------------

def test_question_with_a_shared_identifier_hints_the_holder_once(make):
    h = room(make)
    mid = user_dm(h)
    before = h.q("select count(*) n from deliveries where recipient='a'")[0]["n"]
    out = result(h.tool("b", "xmuse_send", to="c", body="What should MAX_RETRY be?", kind="question"))
    assert out["woken"] == ["c"]  # the question wakes its addressee, never the holder because of the hint
    assert h.q("select count(*) n from deliveries where recipient='a'")[0]["n"] == before
    assert not h.q("select 1 from turns")
    text = pack(h, "a")
    assert f"你有一条用户私信（#{mid}）可能与 b 的问题有关，需要的话用 xmuse_share 申请" in text
    assert text.count("xmuse_share") == 1
    assert "xmuse_share" not in pack(h, "a")  # the same pair is shown once
    assert "xmuse_share" not in pack(h, "c")  # only the holder of that DM
    result(h.tool("c", "xmuse_send", to="b", body="no idea about MAX_RETRY either", kind="question"))
    assert "可能与 c 的问题有关" in pack(h, "a")  # another question, another pair
    assert not h.q("select 1 from turns")
    assert h.q("select count(*) n from deliveries where recipient='a'")[0]["n"] == before


def test_handoff_hints_too_but_only_on_real_overlap(make):
    h = room(make)
    mid = user_dm(h)
    why = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
    h.tool("b", "xmuse_send", to="c", body="please tune the loop and write tests", kind="handoff", why=why)
    h.tool("b", "xmuse_send", to="c", body="which one is better?", kind="question")  # no identifiers: nothing in common
    assert "xmuse_share" not in pack(h, "a")
    h.tool("b", "xmuse_send", to="c", body="Raise the MAX_RETRY cap in the client", kind="handoff", why=why)
    assert f"（#{mid}）可能与 b 的问题有关" in pack(h, "a")
    # a message is not a question or a handoff, and the holder's own question is no hint for itself
    h.tool("b", "xmuse_send", to="c", body="just saying MAX_RETRY", kind="message")
    h.tool("a", "xmuse_send", to="c", body="my own MAX_RETRY question", kind="question")
    assert "xmuse_share" not in pack(h, "a")


def test_no_hint_once_the_message_is_released(make):
    h = room(make)
    mid = user_dm(h)
    h.tool("b", "xmuse_send", to="c", body="What is MAX_RETRY?", kind="question")
    admin(h, act="share_mark", message_id=mid)
    assert "xmuse_share" not in pack(h, "a")
    mid2 = user_dm(h, "a", "TIMEOUT_MS is 3000")
    h.tool("b", "xmuse_send", to="c", body="Who sets TIMEOUT_MS?", kind="question")
    result(share(h, "a", mid2, "b"))
    admin(h, act="approve", id="share:1", decision="once")  # delivered to b: no suggestion for it any more
    assert "xmuse_share" not in pack(h, "a")


def test_rule_picks_code_like_names_and_numbers():
    from xmuse.share import idents
    got = idents("set MAX_RETRY and retryLimit, port 8080, use utf8; the old one")
    assert got == {"max_retry", "retrylimit", "8080", "utf8"}
    assert idents("a b is on it") == set()


def test_hint_reaches_the_holder_in_a_real_wake(make):
    h = room(make)
    h.plan_claude({})
    mid = user_dm(h, "a", "MAX_RETRY is 7")  # a is paused: the message just waits
    h.tool("b", "xmuse_send", to="c", body="What is MAX_RETRY?", kind="question")
    assert not h.claude_calls()
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=0 where id='a'")
    h.hub.engine.kick()
    h.wait_quiet()
    [call] = h.claude_calls()
    assert "New for you:" in call["prompt"] and f"你有一条用户私信（#{mid}）可能与 b 的问题有关" in call["prompt"]
    assert h.q("select count(*) n from turns")[0]["n"] == 1  # a's own wake only: the hint woke nobody
