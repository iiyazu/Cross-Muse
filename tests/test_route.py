"""Duty routing (contract §8.7, T4): a member's unaddressed question in a public group wakes only the
1-2 members whose role + description best match. Members here are desktop (never run by the hub), so wake
decisions are read straight off the deliveries rows."""
import json
import sqlite3
import time

from xmuse import db, dispatch, mail, room as rooms, threads
from xmuse.config import DEFAULTS


def team(make, **cfg):
    h = make([("coord", "claude", {"desktop": True}), ("e1", "claude", {"desktop": True}),
              ("e2", "claude", {"desktop": True}), ("e3", "claude", {"desktop": True})],
             wake="all", route_by_duty=True, **cfg)  # T4 tests run with the duty switch on (default off, T8a H8)
    with h.conn() as c:
        c.execute("insert into room(id, name, dir, host, created_at) values('r-t', 'dev', ?, 'coord', ?)",
                  (str(h.ws), time.time()))
    return h


def describe(h, **roles):
    """describe(h, e1=("executor", "sidebar drawer"), ...)"""
    with h.conn() as c:
        for mid, (role, desc) in roles.items():
            c.execute("update agents set role=?, description=? where id=?", (role, desc, mid))


def ask(h, who, body, to="#team", **kw):
    out = h.tool(who, "xmuse_send", to=to, body=body, kind="question", **kw)
    assert "result" in out, out
    return out["result"]


def woken(h, mid):
    return {r["recipient"] for r in h.q(
        "select recipient from deliveries where message_id=? and wake=1", mid)}


def item_of(h, mid, reader="e2"):
    conn = h.conn()
    m = db.row(conn.execute("select * from messages where id=?", (mid,)))
    item = rooms._item(conn, m, reader, rooms._thread_members(conn),
                       {r[0] for r in conn.execute("select id from agents")})
    conn.close()
    return item


# ---- hits -----------------------------------------------------------------------------------------------------------

def test_hit_one_member(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"), e2=("reviewer", "approvals evidence gate"),
             e3=("executor", "opencode serve"), coord=("coordinator", "plans and reviews"))
    out = ask(h, "e3", "how do I render the sidebar drawer?")
    assert woken(h, out["id"]) == {"e1"}
    row = h.q("select route_to, route_reason from messages where id=?", out["id"])[0]
    assert json.loads(row["route_to"]) == ["e1"] and row["route_reason"] == "e1: drawer, sidebar"


def test_hit_two_members(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer"), e2=("executor", "sidebar plugin toast"),
             e3=("executor", "opencode serve"))
    out = ask(h, "e3", "sidebar drawer plugin toast render?")
    assert woken(h, out["id"]) == {"e1", "e2"}  # e2 scores 3, e1 scores 2 >= ceil(3/2)
    row = h.q("select route_to from messages where id=?", out["id"])[0]
    assert json.loads(row["route_to"]) == ["e1", "e2"]


def test_runner_up_below_half_is_dropped(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin toast dialog"), e2=("executor", "sidebar"))
    out = ask(h, "e3", "sidebar drawer plugin toast dialog?")
    assert woken(h, out["id"]) == {"e1"}  # 5 vs 1: 1 < ceil(5/2)
    row = h.q("select route_to from messages where id=?", out["id"])[0]
    assert json.loads(row["route_to"]) == ["e1"]


def test_no_hit_wakes_everyone_as_before(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer"), e2=("reviewer", "approvals evidence"))
    out = ask(h, "e3", "how to bake sourdough bread?")
    assert "routed_to" not in out
    assert woken(h, out["id"]) == {"coord", "e1", "e2"}  # wake=all baseline, sender excluded
    row = h.q("select route_to, route_reason from messages where id=?", out["id"])[0]
    assert row["route_to"] is None and row["route_reason"] is None


# ---- routing does not apply -----------------------------------------------------------------------------------------

def test_mentioned_question_is_not_routed(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"))
    out = ask(h, "e3", "how do I render the sidebar drawer?", mentions=["e1"])
    assert "routed_to" not in out
    assert woken(h, out["id"]) == {"coord", "e1", "e2"}


def test_dm_question_is_not_routed(make):
    h = team(make)
    describe(h, e2=("executor", "sidebar drawer plugin"))
    out = h.tool("e1", "xmuse_send", to="e2", body="how do I render the sidebar drawer?", kind="question")
    assert "result" in out, out
    out = out["result"]
    assert "routed_to" not in out
    assert woken(h, out["id"]) == {"e2"}


def test_private_group_question_is_not_routed(make):
    h = team(make)
    describe(h, e2=("executor", "sidebar drawer plugin"))
    with h.conn() as c:
        threads.create(c, "#priv", "e1", ["e1", "e2"], {"coord", "e1", "e2", "e3"})
    out = ask(h, "e1", "how do I render the sidebar drawer?", to="#priv")
    assert "routed_to" not in out
    assert woken(h, out["id"]) == {"e2"}


def test_user_question_does_not_take_this_path(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"))
    out = h.send("#team", "how do I render the sidebar drawer?", kind="question")  # the user, via admin
    assert "routed_to" not in out  # 8.4 host routing only takes kind=message; §8.7 is members only
    assert woken(h, out["id"]) == {"coord", "e1", "e2", "e3"}


def test_duty_routing_defaults_off(make):
    """T8a H8: without route_by_duty, an unaddressed member question wakes the group, not the best match."""
    from xmuse.config import DEFAULTS
    assert DEFAULTS["route_by_duty"] is False
    h = make([("coord", "claude", {"desktop": True}), ("e1", "claude", {"desktop": True}),
              ("e2", "claude", {"desktop": True}), ("e3", "claude", {"desktop": True})], wake="all")
    with h.conn() as c:
        c.execute("insert into room(id, name, dir, host, created_at) values('r-t', 'dev', ?, 'coord', ?)",
                  (str(h.ws), time.time()))
    describe(h, e1=("executor", "sidebar drawer plugin"))
    out = ask(h, "e3", "how do I render the sidebar drawer?")
    assert "routed_to" not in out
    assert woken(h, out["id"]) == {"coord", "e1", "e2"}  # wake=all baseline, sender excluded
    row = h.q("select route_to from messages where id=?", out["id"])[0]
    assert row["route_to"] is None


def test_chinese_description_matches(make):
    h = team(make)
    describe(h, e1=("executor", "负责侧栏抽屉界面"), e2=("reviewer", "approvals evidence"))
    out = ask(h, "e3", "抽屉侧栏怎么渲染？")
    assert woken(h, out["id"]) == {"e1"}
    row = h.q("select route_to from messages where id=?", out["id"])[0]
    assert json.loads(row["route_to"]) == ["e1"]


def test_send_return_carries_routed_to(make):
    """mail.send's own return (spec step 4); the /v1/tools wrapper does not forward it (see report)."""
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"))
    ask(h, "e3", "how do I render the sidebar drawer?")  # creates #team
    cfg = {**DEFAULTS, **json.loads((h.state / "config.json").read_text(encoding="utf-8"))}
    conn = h.conn()
    out = mail.send(conn, cfg, "e3", "#team", "another sidebar drawer question?", kind="question")
    conn.close()
    assert out["routed_to"] == ["e1"]
    assert woken(h, out["id"]) == {"e1"}


# ---- view fields and old libraries ----------------------------------------------------------------------------------

def test_item_fields(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"))
    out = ask(h, "e3", "how do I render the sidebar drawer?")
    item = item_of(h, out["id"])
    assert item["routed_to"] == ["e1"] and item["route_reason"] == "e1: drawer, sidebar"
    plain = ask(h, "e3", "how to bake sourdough bread?")
    plain_item = item_of(h, plain["id"])
    assert "routed_to" not in plain_item and "route_reason" not in plain_item
    # dispatch.item has no routed_to: the view field comes only from route.py (no conflict)
    assert "routed_to" not in dispatch.item({"kind": "done", "outcome": "completed", "outcome_by": "member"})


def test_old_library_opens(tmp_path):
    p = tmp_path / "old.db"  # a library from before T4: schema only, no route columns
    raw = sqlite3.connect(p)
    raw.executescript(db.SCHEMA)
    raw.execute("insert into room(id, name, dir, host, created_at) values('r', 'd', '/x', 'h', 0)")
    raw.commit()
    raw.close()
    conn = db.init(str(p))
    cols = {r[1] for r in conn.execute("pragma table_info(messages)")}
    assert {"route_to", "route_reason", "reply_to"} <= cols  # T4 + T8a H9 reply_to migrate old libraries too
    assert "human_reads" in {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    conn.execute("insert into messages(thread_id, sender, kind, body, mentions, chain_id, created_at)"
                 " values('#room', 'e1', 'message', 'hi', '[]', 1, 0)")
    conn.commit()
    conn.close()


def test_question_also_wakes_who_handed_the_work_and_the_tool_reports_the_route(make):
    h = team(make)
    describe(h, e1=("executor", "sidebar drawer plugin"), e2=("reviewer", "approvals evidence gate"))
    why = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
    assert "result" in h.tool("e2", "xmuse_send", to="e3", body="build it", kind="handoff", why=why)
    out = ask(h, "e3", "how do I render the sidebar drawer?")
    assert out["routed_to"] == ["e1"]
    assert woken(h, out["id"]) == {"e1", "e2"}  # e2 handed e3 its work
