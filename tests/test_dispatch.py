"""Host dispatch (contract XMUSE2-VIEW-API §8.4, TOPO T0): the user's unaddressed words go to the host, results carry
outcome labels, and the host is woken by label, completed results once per batch. Executors here are desktop members
(never run by the hub) driven through their tools; the host is either hub-run (fake claude) or a desktop session."""
import time

from test_room import act, view
from xmuse import db, dispatch, mail, room as rooms, wakepack

WHY = {k: k for k in ("what", "why", "tradeoff", "open_questions", "next_action")}


def team(make, desktop_host=False, **cfg):
    h = make([("coord", "claude", {"desktop": True} if desktop_host else {}), ("e1", "claude", {"desktop": True}),
              ("e2", "claude", {"desktop": True})], **cfg)
    h.plan_claude(*[{}] * 20)  # every host turn: a plain reply, no tool calls
    with h.conn() as c:
        c.execute("insert into room(id, name, dir, host, created_at) values('r-t', 'dev', ?, 'coord', ?)",
                  (str(h.ws), time.time()))
    h.ot = rooms.operator_token(h.conn(), "coord")  # the user, from the host's sidebar
    return h


def quiet(h):
    """Every kick handled and every hub turn finished (desktop members' mail stays queued: they are never run)."""
    def still():
        return h.q("select 1 from turns where state='running'") or h.q(
            "select 1 from deliveries d join agents a on a.id=d.recipient where d.state='queued' and d.wake=1"
            " and a.settings not like '%desktop%'")
    for _ in range(2):
        h.hub.engine.call(lambda: None)
        h.wait(lambda: not still(), 15, "quiet hub")


def handoff(h, to, **kw):
    out = h.tool("coord", "xmuse_send", to=to, body=f"task for {to}", kind="handoff", why=WHY, **kw)
    assert "result" in out, out
    return out["result"]["id"]


def done(h, who, **kw):
    out = h.tool(who, "xmuse_done", **{"summary": f"{who} finished", "next": "coord", **kw})
    assert "result" in out, out
    return out["result"]


def host_turns(h):
    return h.q("select count(*) n from turns where agent_id='coord'")[0]["n"]


def last_done(h, who):
    return h.q("select * from messages where sender=? and kind='done' order by id desc limit 1", who)[0]


def held(h):
    return [r["message_id"] for r in h.q("select message_id from dispatch_holds where released_at is null")]


# ---- the user's words go to the host --------------------------------------------------------------------------------

def test_unaddressed_user_words_wake_only_the_host(make):
    h = team(make, wake="all")  # wake=all: a group message would otherwise wake every member
    st, out = act(h, h.ot, act="say", to="#team", text="build the parser")
    assert st == 200 and out["routed_to"] == "coord"
    assert {r["recipient"]: (r["wake"], r["state"]) for r in h.q(
        "select recipient, wake, state from deliveries where message_id=?", out["id"])} == {
        "coord": (1, "queued"), "e1": (0, "passive"), "e2": (0, "passive")}
    quiet(h)
    assert host_turns(h) == 1
    st, out = act(h, h.ot, act="say", text="no to: the room")  # no `to` at all
    assert out["thread"] == "#room" and out["routed_to"] == "coord"
    out = h.send("#team", "from the terminal")  # the CLI is the user too
    assert out["routed_to"] == "coord" and out["woken"] == ["coord"]
    # named: as before
    st, out = act(h, h.ot, act="say", to="#team", text="e1, this one is yours", mentions=["e1"])
    assert "routed_to" not in out
    assert {r["recipient"] for r in h.q("select recipient from deliveries where message_id=? and wake=1",
                                        out["id"])} == {"coord", "e1", "e2"}  # wake=all, as before
    st, out = act(h, h.ot, act="say", to="e2", text="a DM")
    assert "routed_to" not in out and out["thread"] == "dm:e2+human"
    # a member's words are not the user's
    out = h.tool("e1", "xmuse_send", to="#team", body="anyone?")["result"]
    assert "routed_to" not in out and set(out["woken"]) == {"coord"}  # wake=all; e2 is desktop, never woken by the hub


def test_no_room_no_routing(make):
    h = make([("coord", "claude"), ("e1", "claude", {"desktop": True})])
    out = h.send("#team", "nobody hosts")
    assert "routed_to" not in out and out["woken"] == []


# ---- the host's identity -------------------------------------------------------------------------------------------

def test_host_identity_in_its_wake_pack(make):
    h = team(make)
    h.send("#team", "plan the release")
    quiet(h)
    [c] = h.claude_calls()
    assert dispatch.HOST_DUTY in c["prompt"] and "Do not write code yourself" in c["prompt"]
    h.send("#team", "and the changelog")
    quiet(h)
    second = h.claude_calls()[1]["prompt"]
    assert dispatch.HOST_LINE in second and dispatch.HOST_DUTY not in second  # resumed session: one line
    conn = h.conn()
    e1 = db.row(conn.execute("select * from agents where id='e1'"))
    assert "You host" not in wakepack.render(conn, h.hub.cfg, e1, [], None, str(h.ws)).text
    coord = db.row(conn.execute("select * from agents where id='coord'"))
    assert dispatch.HOST_DUTY in wakepack.inject(conn, h.hub.cfg, coord, None).text  # a desktop host's new session
    assert dispatch.HOST_DUTY not in wakepack.inject(conn, h.hub.cfg, e1, None).text


# ---- outcome labels and the hub's upgrade --------------------------------------------------------------------------

def test_upgrade_rules():
    up = dispatch.upgrade
    assert up("completed", None, "e1") == ("completed", None)
    assert up("completed", [{"kind": "decision", "statement": "x", "scope": "agent:e1"}], "e1") == ("completed", None)
    assert up("completed", [{"kind": "assumption", "statement": "x", "scope": "member:e1"}], "e1") == ("completed", None)
    o, why = up("completed", [{"kind": "decision", "statement": "x", "scope": "global"}], "e1")
    assert o == "needs_alignment" and "decision" in why
    assert up("completed", [{"kind": "question", "statement": "x"}], "e1")[0] == "needs_alignment"  # thread scope
    o, why = up("completed", [{"kind": "decision", "statement": "x", "scope": "agent:e1", "supersedes": "E3"}], "e1")
    assert o == "needs_alignment" and "E3" in why
    assert up("progress", [{"kind": "decision", "statement": "x"}], "e1") == ("progress", None)
    assert up("blocked", [{"kind": "decision", "statement": "x"}], "e1") == ("blocked", None)
    # evidence (§8.5, the evidence package passes its status): unverified -> blocked, unless no transcript
    o, why = up("completed", None, "e1", "unverified", ["test pytest: exit 1, claimed pass"])
    assert o == "blocked" and "exit 1" in why
    assert up("completed", None, "e1", "unverified", ["transcript unavailable"]) == ("completed", None)
    assert up("completed", None, "e1", "verified") == ("completed", None)
    assert up("progress", None, "e1", "unverified", ["x"]) == ("progress", None)


def test_done_records_the_label(make):
    h = team(make)
    r = done(h, "e1", next="none")
    assert r == {"recorded": True, "thread": "dm:e1+human"}  # the default left alone: the reply it always had
    m = last_done(h, "e1")
    assert (m["outcome"], m["outcome_by"], m["outcome_reason"]) == ("completed", "member", None)
    r = done(h, "e1", next="none", outcome="progress")
    assert r["outcome"] == "progress" and last_done(h, "e1")["outcome_by"] == "member"
    r = done(h, "e2", next="none", declares=[{"kind": "decision", "statement": "dates are UTC", "scope": "global"}])
    assert r["outcome"] == "needs_alignment" and r["outcome_by"] == "hub" and "decision" in r["outcome_reason"]
    m = last_done(h, "e2")
    assert (m["outcome"], m["outcome_by"]) == ("needs_alignment", "hub") and "decision" in m["outcome_reason"]
    assert "outcome must be one of" in h.tool("e1", "xmuse_done", summary="s", next="none", outcome="meh")["error"]["message"]
    err = h.tool("coord", "xmuse_send", to="e1", body="x", notify="now")["error"]
    assert "notify" in err["message"]


# ---- waking the host by label (hub-run host) ----------------------------------------------------------------------

def test_completed_results_wait_for_the_whole_batch(make):
    h = team(make)
    h1, h2 = handoff(h, "e1"), handoff(h, "e2")
    assert {(d["member"], d["message_id"]) for d in h.q("select * from dispatches")} == {("e1", h1), ("e2", h2)}
    m1 = h.tool("e1", "xmuse_send", to="coord", body="parser done, see parser.py")["result"]  # its report: held
    assert m1["woken"] == []
    done(h, "e1")
    quiet(h)
    assert host_turns(h) == 0 and len(held(h)) == 2
    assert not h.q("select 1 from deliveries where recipient='coord' and message_id in (?, ?)",
                   m1["id"], last_done(h, "e1")["id"])
    done(h, "e2", next="none")  # answers coord's handoff, so it is the host's result whatever `next` says
    quiet(h)
    assert host_turns(h) == 1 and held(h) == []
    [c] = h.claude_calls()
    assert "parser done" in c["prompt"] and "e1 finished" in c["prompt"] and "e2 finished" in c["prompt"]
    assert 'kind="done" outcome="completed"' in c["prompt"]
    assert h.q("select count(*) n from dispatches where returned_at is null")[0]["n"] == 0


def test_alignment_blocked_and_questions_wake_at_once_progress_never(make):
    h = team(make)
    handoff(h, "e1"), handoff(h, "e2")
    done(h, "e2")  # completed: held, e1 still out
    quiet(h)
    assert host_turns(h) == 0
    r = done(h, "e1", outcome="progress")
    quiet(h)
    assert host_turns(h) == 0 and r["outcome"] == "progress"
    assert h.q("select wake, state from deliveries where recipient='coord' and message_id=?",
               last_done(h, "e1")["id"]) == [{"wake": 0, "state": "passive"}]
    assert [d["member"] for d in dispatch.waiting(h.conn(), "coord")] == ["e1"]  # progress keeps it out
    h.tool("e1", "xmuse_send", to="coord", body="which date format?", kind="question")
    quiet(h)
    assert host_turns(h) == 1 and held(h) == []  # the question woke it; e2's held result went along
    assert "e2 finished" in h.claude_calls()[0]["prompt"]
    for outcome in ("needs_alignment", "blocked"):
        handoff(h, "e2")
        done(h, "e2", outcome=outcome)
        quiet(h)
    assert host_turns(h) == 3


def test_upgraded_result_wakes_at_once(make):
    h = team(make)
    handoff(h, "e1"), handoff(h, "e2")
    r = done(h, "e1", declares=[{"kind": "assumption", "statement": "input is utf-8", "scope": "global"}])
    assert r["outcome"] == "needs_alignment"
    quiet(h)
    assert host_turns(h) == 1 and 'outcome="needs_alignment"' in h.claude_calls()[0]["prompt"]


def test_batch_times_out(make):
    h = team(make, host_batch_max_s=0.5)
    handoff(h, "e1"), handoff(h, "e2")
    done(h, "e1")
    quiet(h)
    assert host_turns(h) == 0 and len(held(h)) == 1
    time.sleep(0.6)
    h.hub.engine.kick()  # the periodic sweep kicks the same way
    quiet(h)
    assert host_turns(h) == 1 and held(h) == []
    assert h.q("select why from dispatch_holds")[0]["why"] == "timeout"


def test_notify_now_and_wake_host(make):
    h = team(make)
    handoff(h, "e1", notify="now"), handoff(h, "e2")
    assert h.q("select notify from dispatches order by id") == [{"notify": "now"}, {"notify": "batch"}]
    done(h, "e1")
    quiet(h)
    assert host_turns(h) == 1  # e2 still out, but this one was wanted at once
    handoff(h, "e1")
    done(h, "e1")
    quiet(h)
    assert host_turns(h) == 1 and len(held(h)) == 1
    st, out = act(h, h.ot, act="wake_host")
    assert st == 200 and out == {"ok": True, "released": 1}
    quiet(h)
    assert host_turns(h) == 2 and held(h) == []
    st, out = act(h, rooms.operator_token(h.conn(), "e1"), act="wake_host")
    assert st == 200 and out["released"] == 0  # nothing held
    st, out = act(h, h.token("e1"), act="wake_host")
    assert st == 403  # the member token cannot


def test_results_match_the_handoff_they_answer(make):
    h = team(make)
    h1 = handoff(h, "e1")
    h2 = handoff(h, "e1")
    mail.ack(h.conn(), "e1", [h2], None)  # e1 has seen only the second one
    done(h, "e1")
    assert h.q("select message_id from dispatches where returned_at is not null") == [{"message_id": h2}]
    done(h, "e1")  # nothing else seen: the oldest open one
    assert h.q("select count(*) n from dispatches where returned_at is null")[0]["n"] == 0 and h1 < h2
    quiet(h)


def test_released_results_keep_chain_states(make):
    h = team(make)
    handoff(h, "e1")
    a = h.tool("e1", "xmuse_send", to="coord", body="in a capped chain")["result"]
    b = h.tool("e1", "xmuse_send", to="coord", body="in a stopped chain")["result"]
    with h.conn() as c:
        for m, state in ((a, "capped"), (b, "stopped")):
            c.execute("update chains set state=? where id=(select chain_id from messages where id=?)", (state, m["id"]))
    done(h, "e1")  # the batch is complete
    quiet(h)
    assert host_turns(h) == 1
    st = {r["message_id"]: r["state"] for r in h.q("select message_id, state from deliveries where recipient='coord'")}
    assert st[a["id"]] == "held" and b["id"] not in st and st[last_done(h, "e1")["id"]] == "done"
    assert "in a capped chain" not in h.claude_calls()[0]["prompt"]
    assert h.q("select why from dispatch_holds where message_id=?", b["id"])[0]["why"] == "stopped"


# ---- the desktop host: held results are invisible until released --------------------------------------------------

def test_desktop_host_sees_held_results_only_after_release(make):
    h = team(make, desktop_host=True)
    handoff(h, "e1"), handoff(h, "e2")
    msg = h.tool("e1", "xmuse_send", to="coord", body="parser done")["result"]["id"]
    done(h, "e1")
    d1 = last_done(h, "e1")["id"]

    def mine():
        _, v = view(h, h.ot)
        items = {t["id"]: t for t in v["timeline"]}
        me = next(m for m in v["members"] if m["id"] == "coord")
        return items, me, v
    items, me, v = mine()
    assert not items[msg]["for_me"] and not items[d1]["for_me"] and me["unread"] == 0
    assert v["host_wait"]["results_held"] == 2 and [w["member"] for w in v["host_wait"]["waiting_on"]] == ["e2"]
    assert v["host_wait"]["wake_at"] > time.time() + 500
    assert items[d1]["outcome"] == "completed" and items[d1]["outcome_by"] == "member"
    assert h.tool("coord", "xmuse_inbox")["result"] == [] and mail.pending(h.conn(), "coord")["pending"] == 0
    assert host_turns(h) == 0  # never run by the hub, held or not
    done(h, "e2")
    items, me, v = mine()
    d2 = last_done(h, "e2")["id"]
    assert items[msg]["for_me"] and items[d1]["for_me"] and items[d2]["for_me"] and me["unread"] == 3
    assert v["host_wait"] == {"waiting_on": [], "results_held": 0, "wake_at": None}
    assert {m["id"] for m in h.tool("coord", "xmuse_inbox")["result"]} == {msg, d1, d2}


def test_desktop_host_progress_is_not_for_me(make):
    h = team(make, desktop_host=True)
    handoff(h, "e1")
    done(h, "e1", outcome="progress")
    d = last_done(h, "e1")["id"]
    _, v = view(h, h.ot)
    assert not next(t for t in v["timeline"] if t["id"] == d)["for_me"]
    done(h, "e1", outcome="blocked", summary="tests fail")
    d = last_done(h, "e1")["id"]
    _, v = view(h, h.ot)
    item = next(t for t in v["timeline"] if t["id"] == d)
    assert item["for_me"] and item["outcome"] == "blocked"


# ---- view fields ---------------------------------------------------------------------------------------------------

def test_view_fields(make):
    h = team(make)
    _, v = view(h, h.ot)
    assert v["host_wait"] == {"waiting_on": [], "results_held": 0, "wake_at": None}
    assert {m["id"]: m["wakes_hour"] for m in v["members"]} == {"coord": 0, "e1": 0, "e2": 0}
    h1 = handoff(h, "e1")
    _, v = view(h, h.ot)
    [w] = v["host_wait"]["waiting_on"]
    assert w["member"] == "e1" and w["handoff_id"] == h1 and w["since"] <= time.time()
    assert v["host_wait"]["results_held"] == 0 and v["host_wait"]["wake_at"] is None
    assert {m["id"]: m["wakes_hour"] for m in v["members"]}["e1"] == 1  # a desktop member: the handoff's wake
    h.send("#team", "status?")
    quiet(h)
    _, v = view(h, h.ot)
    assert {m["id"]: m["wakes_hour"] for m in v["members"]}["coord"] == 1
    done(h, "e1", outcome="progress")
    _, v = view(h, h.ot)
    item = next(t for t in v["timeline"] if t["kind"] == "done")
    assert (item["outcome"], item["outcome_by"]) == ("progress", "member")
    assert all("outcome" not in t for t in v["timeline"] if t["kind"] != "done")
