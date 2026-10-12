"""Sidebar API (D2, contract docs/design/XMUSE2-VIEW-API.zh.md v0): rooms, invitations, member vs operator tokens,
session binding, the long-polled view and the acts."""
import json
import threading
import time
import urllib.error
import urllib.request

from test_trust import OC, held_approval
from xmuse import db


def pause(h, agent):
    """Keep the engine from admitting (and so marking read) the agent's mail while a test reads it."""
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1 where id=?", (agent,))


def call(h, method, path, body=None, token=None, session=None, timeout=40, key=None):
    port = json.loads((h.state / "hub.json").read_text(encoding="utf-8"))["port"]
    headers = {"content-type": "application/json", **({"authorization": f"Bearer {token}"} if token else {}),
               **({"x-xmuse-session": session} if session else {}), **({"x-xmuse-sidebar": key} if key else {})}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def open_room(h, vendor="claude", member_id="lead", session="S-lead", **kw):
    st, out = call(h, "POST", "/v1/rooms", {"dir": str(h.ws), "name": "dev", "vendor": vendor, "session_id": session,
                                            "member_id": member_id, **kw}, key=h.key())
    assert st == 200, out
    return out


def act(h, token, session=None, **body):
    return call(h, "POST", "/v1/act", body, token, session)


def view(h, token, session=None, since=0, wait=0):
    return call(h, "GET", f"/v1/view?since={since}&wait={wait}", None, token, session)


# ---- rooms, tokens, binding ----------------------------------------------------------------------------------

def test_rooms_creates_the_host_with_both_tokens(make):
    h = make()
    st, out = call(h, "POST", "/v1/rooms", {"dir": "/elsewhere", "vendor": "claude", "session_id": "S"}, key=h.key())
    assert st == 400 and out["error"] == "wrong_dir"
    room = open_room(h, description="plans and reviews")
    assert room["member_id"] == "lead" and room["room"]["host"] == "lead" and room["room"]["name"] == "dev"
    mt, ot = room["member_token"], room["operator_token"]
    assert mt != ot and mt.startswith("xmt_") and ot.startswith("xmo_")
    st, out = call(h, "POST", "/v1/rooms", {"dir": str(h.ws), "vendor": "claude", "session_id": "S2"}, key=h.key())
    assert st == 409 and out["error"] == "room_exists"
    st, v = view(h, mt, "S-lead")
    assert st == 200 and v["me"] == {"kind": "member", "id": "lead"} and v["room"]["host"] == "lead"
    lead = next(m for m in v["members"] if m["id"] == "lead")
    assert lead["description"] == "plans and reviews" and lead["online"] and lead["vendor"] == "claude"
    assert any(t["kind"] == "system" and "opened the room" in t["text"] for t in v["timeline"])
    # a bound member must name its session; the operator token is the plugin's, not a session's
    assert view(h, mt)[0] == 409 and view(h, mt, "other")[1]["error"] == "not_bound_session"
    st, v = view(h, ot)
    assert st == 200 and v["me"] == {"kind": "operator", "id": "lead"}
    assert view(h, "xmt_nope")[0] == 401
    assert call(h, "GET", "/v1/nothing", None, ot)[0] == 404


def test_member_token_says_and_acks_only(make):
    h = make()
    room = open_room(h)
    mt, ot = room["member_token"], room["operator_token"]
    for name, extra in (("invite", {"vendor": "claude"}), ("approve", {"id": "x", "decision": "once"}),
                        ("pause", {"member": "claude-1"}), ("align", {"id": "E1", "decision": "confirm"}),
                        ("promote", {"message_id": 1}), ("read", {"thread": "#room"})):
        st, out = act(h, mt, "S-lead", act=name, **extra)
        assert st == 403 and out["error"] == "operator_only", name
    st, out = act(h, mt, "S-lead", act="say", to="#plan", text="as the member")
    assert st == 200 and h.q("select sender, via from messages where id=?", out["id"]) == [{"sender": "lead", "via": None}]
    assert act(h, mt, "S-lead", act="ack", ids=[out["id"]]) == (200, {"ok": True, "acked": 0})
    assert act(h, ot, act="bogus")[1]["error"] == "unknown_act"


# ---- invitations ----------------------------------------------------------------------------------------------

def test_invite_join_once_within_ten_minutes_for_the_named_vendor(make):
    h = make()
    ot = open_room(h)["operator_token"]
    st, inv = act(h, ot, act="invite", vendor="claude", role="reviewer", description="reviews D4")
    assert st == 200 and inv["command"] == f"/xmuse join {inv['code']}"
    assert 590 < inv["expires_at"] - time.time() <= 600
    st, out = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "opencode", "session_id": "S2"})
    assert st == 403 and out["error"] == "vendor_mismatch"
    st, j = call(h, "POST", "/v1/join", {"code": inv["code"].lower(), "vendor": "claude", "session_id": "S2",
                                         "client_info": {"client": "test"}})
    assert st == 200 and j["member_id"] == "claude" and j["room"]["host"] == "lead"
    a = h.q("select role, description, bound_session, settings from agents where id='claude'")[0]
    assert (a["role"], a["description"], a["bound_session"]) == ("reviewer", "reviews D4", "S2")
    assert json.loads(a["settings"])["desktop"]  # lives in the user's session; the hub never runs it
    st, out = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S3"})
    assert st == 409 and out["error"] == "code_used"
    assert call(h, "POST", "/v1/join", {"code": "ZZZZ-ZZ", "vendor": "claude", "session_id": "S"})[0] == 404
    _, old = act(h, ot, act="invite", vendor="claude", name="rev-2")
    with h.conn() as c:
        c.execute("update invites set expires_at=? where code=?", (time.time() - 1, old["code"]))
    st, out = call(h, "POST", "/v1/join", {"code": old["code"], "vendor": "claude", "session_id": "S4"})
    assert st == 410 and out["error"] == "code_expired"
    st, v = view(h, j["member_token"], "S2")
    assert v["me"]["id"] == "claude" and any("claude joined the room" in t["text"] for t in v["timeline"])


def test_unread_leaves_out_hub_notices_for_every_vendor(make):
    """Hub notices are delivered to desktop (Claude) members only; a sidebar's unread must not count them."""
    h = make()
    ot = open_room(h)["operator_token"]  # lead: a Claude desktop member
    pause(h, "claude-1")  # hub-run: keep its wake deliveries unread while the test reads them
    _, inv = act(h, ot, act="invite", vendor="claude")
    _, j = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S2"})
    assert h.q("select count(*) n from deliveries d join messages m on m.id=d.message_id"
               " where m.kind='notice' and d.recipient='claude'")[0]["n"] >= 1  # the join notice reached it
    unread = lambda v: {m["id"]: m["unread"] for m in v["members"] if m["id"] in ("lead", "claude")}  # noqa: E731
    _, v = view(h, j["member_token"], "S2")
    assert unread(v) == {"lead": 0, "claude": 0}
    act(h, ot, act="say", to="#room", text="hi all")
    _, v = view(h, j["member_token"], "S2")
    assert unread(v) == {"lead": 1, "claude": 1}
    assert next(t for t in v["threads"] if t["id"] == "#room")["unread"] == 1


def test_named_invite_takes_over_a_registered_member(make):
    """A member `xmuse agent add` registered (no session yet) is taken over by the sidebar that joins as it."""
    h = make([("dog", "claude", {"desktop": True})])
    _, inv = act(h, h.token("human"), act="invite", vendor="claude", name="dog", description="coordinator")
    st, j = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S-dog"})
    assert st == 200 and j["member_id"] == "dog" and j["member_token"] == h.token("dog")
    _, inv2 = act(h, h.token("human"), act="invite", vendor="claude", name="dog")
    st, out = call(h, "POST", "/v1/join", {"code": inv2["code"], "vendor": "claude", "session_id": "S-x"})
    assert st == 409 and out["error"] == "member_exists"
    assert h.q("select used_at from invites where code=?", inv2["code"])[0]["used_at"] is None  # still usable


def test_rebind_and_leave(make):
    h = make()
    room = open_room(h)
    mt = room["member_token"]
    assert call(h, "POST", "/v1/rebind", {"session_id": "S-new"}, mt)[0] == 200  # e.g. after /clear
    assert view(h, mt, "S-lead")[0] == 409 and view(h, mt, "S-new")[0] == 200
    assert call(h, "POST", "/v1/rebind", {"session_id": "x"}, room["operator_token"])[0] == 403
    assert call(h, "POST", "/v1/leave", {}, mt, "S-new")[0] == 200
    st, v = view(h, mt)  # unbound: no session needed any more
    assert st == 200 and h.q("select bound_session from agents where id='lead'")[0]["bound_session"] is None


# ---- the view: long poll, timeline, says --------------------------------------------------------------------------

def test_long_poll_returns_on_change_and_204_when_quiet(make):
    h = make()
    ot = open_room(h)["operator_token"]
    _, v = view(h, ot)
    ver = v["version"]
    assert view(h, ot, since=ver)[0] == 204  # wait=0: no change now
    t0 = time.time()
    assert view(h, ot, since=ver, wait=1)[0] == 204 and 0.9 < time.time() - t0 < 5
    got = {}
    th = threading.Thread(target=lambda: got.update(r=view(h, ot, since=ver, wait=20)))
    th.start()
    time.sleep(0.5)
    t1 = time.time()
    act(h, ot, act="say", to="#plan", text="wake the sidebars")
    th.join(25)
    st, nv = got["r"]
    assert st == 200 and nv["version"] > ver and time.time() - t1 < 3
    assert nv["timeline"][-1]["text"] == "wake the sidebars" and nv["timeline"][-1]["from"] == "human"
    assert view(h, ot, since=ver + 1000)[0] == 200  # a version from before a hub restart: full snapshot


def test_operator_say_is_the_users_via_the_sidebar_and_wakes(make):
    h = make()  # claude-1: headless, run by the hub
    room = open_room(h)
    h.plan_claude({})
    st, out = act(h, room["operator_token"], act="say", to="claude-1", text="please run the tests")
    assert st == 200 and out["thread"] == "dm:claude-1+human"
    assert h.q("select sender, via from messages where id=?", out["id"]) == [{"sender": "human", "via": "claude sidebar"}]
    assert h.q("select recipient, wake from deliveries where message_id=?", out["id"]) == [
        {"recipient": "claude-1", "wake": 1}]
    h.wait_quiet()
    assert any("please run the tests" in c["prompt"] for c in h.claude_calls())
    _, v = view(h, h.token("claude-1"))  # a hub-run member reads with its own token (never bound)
    item = next(t for t in v["timeline"] if t["id"] == out["id"])
    assert item["for_me"] and item["via"] == "claude sidebar" and item["to"] == ["claude-1"]
    st, out = act(h, room["operator_token"], act="say", to="dm:claude-1+human", text="again, by thread id")
    assert st == 200 and out["thread"] == "dm:claude-1+human"
    assert act(h, room["operator_token"], act="say", to="dm:a+b", text="x")[1]["error"] == "bad_target"


def test_timeline_pages_back(make):
    h = make()
    ot = open_room(h)["operator_token"]
    pause(h, "claude-1")  # broadcasts wake it; keep the engine out so paging stays about content
    for i in range(60):
        h.send("#log", f"m{i}")  # broadcasts: everyone is woken, nobody runs (paused)
    _, v = view(h, ot)
    assert len(v["timeline"]) == 50 and v["timeline_cursor"]["has_more"]
    assert v["timeline"][-1]["text"] == "m59" and v["timeline_cursor"]["oldest"] == v["timeline"][0]["id"]
    st, older = call(h, "GET", f"/v1/timeline?before={v['timeline_cursor']['oldest']}&limit=50", None, ot)
    assert st == 200 and older["items"][-1]["id"] < v["timeline"][0]["id"] and not older["has_more"]
    assert {t["kind"] for t in v["threads"]} == {"topic"} and v["threads"][0]["id"] in ("#log", "#room")


def test_descriptions_reach_peers(make):
    h = make()
    open_room(h, description="owns the API contract")
    peers = h.tool("claude-1", "xmuse_whoami")["result"]["peers"]
    assert {"id": "lead", "family": "anthropic", "role": "coordinator", "description": "owns the API contract"} in peers


# ---- approvals and management -----------------------------------------------------------------------------------

def test_sidebar_approves_a_held_command(make):
    h = make(OC)
    held_approval(h)
    ot = open_room(h)["operator_token"]
    _, v = view(h, ot)
    [ap] = [a for a in v["approvals"] if a["kind"] == "shell"]
    assert ap["id"] == "per_1" and ap["member"] == "opencode-1" and "git push" in ap["summary"]
    assert act(h, ot, act="approve", id="per_1", decision="maybe")[0] == 400
    assert act(h, ot, act="approve", id="per_1", decision="once") == (200, {"ok": True})
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "once"}
    assert h.oc.replies
    assert any("decided by the user via claude sidebar" in n["body"]
               for n in h.q("select body from messages where kind='notice'"))
    assert act(h, ot, act="approve", id="nope", decision="once")[0] in (400, 404)
    h.admin("stop")


def test_pause_resume_remove_transfer(make):
    h = make()
    room = open_room(h)
    ot = room["operator_token"]
    assert act(h, ot, act="pause", member="claude-1")[0] == 200
    _, v = view(h, ot)
    assert next(m for m in v["members"] if m["id"] == "claude-1")["status"] == "paused"
    assert any(a["id"] == "resume:claude-1" for a in v["approvals"])
    assert act(h, ot, act="approve", id="resume:claude-1", decision="once")[0] == 200
    assert h.q("select paused from agents where id='claude-1'")[0]["paused"] == 0
    assert act(h, ot, act="remove", member="lead")[1]["error"] == "is_host"
    assert act(h, ot, act="transfer_host", member="claude-1")[0] == 200
    _, v = view(h, ot)
    assert v["room"]["host"] == "claude-1"
    tok = h.token("claude-1")
    assert act(h, ot, act="remove", member="claude-1")[0] == 409  # the host now
    act(h, ot, act="transfer_host", member="lead")
    assert act(h, ot, act="remove", member="claude-1") == (200, {"ok": True})
    assert view(h, tok)[0] == 401  # its token stopped working
    _, v = view(h, ot)
    assert [m["id"] for m in v["members"]] == ["lead"]
    assert act(h, ot, act="say", to="claude-1", text="x")[1]["error"] == "unknown_recipient"
    assert act(h, ot, act="pause", member="ghost")[0] == 404


def test_align_from_the_sidebar(make):
    h = make([("dog", "claude", {"desktop": True}), ("claude-1", "claude")])
    h.tool("dog", "xmuse_send", to="#plan", body="use tabs", kind="decision", on_behalf_of="human")
    with h.conn() as c:  # a proposal waiting for the user
        c.execute("update entries set status='proposed'")
    _, inv = act(h, h.token("human"), act="invite", vendor="claude", name="dog")
    ot = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S"})[1]["operator_token"]
    _, v = view(h, ot)
    [e] = [a for a in v["approvals"] if a["kind"] == "alignment"]
    assert act(h, ot, act="align", id=e["id"], decision="confirm") == (200, {"ok": True})
    _, v = view(h, ot)
    assert [x["status"] for x in v["alignment"]] == ["active"] and v["alignment"][0]["text"] == "use tabs"
    assert v["alignment"][0]["author"] == "human"


def test_members_show_queued_wake_deliveries(make):
    """T8a H5: queued counts wake deliveries the member has not taken yet."""
    h = make()
    room = open_room(h)
    h.plan_claude({"sleep": 30})
    h.send("claude-1", "first")  # a DM wakes it; the turn sleeps
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.send("claude-1", "second")
    h.send("claude-1", "third")
    _, v = view(h, room["operator_token"])
    assert next(m for m in v["members"] if m["id"] == "claude-1")["queued"] == 2
    assert next(m for m in v["members"] if m["id"] == "lead")["queued"] == 0


def test_human_read_cursor_drives_thread_unread_and_mentions_me(make):
    """T8a H6: threads[].unread for the human reader counts past its cursor (not its own words, no notices);
    mentions_me counts unread @user and replies to the user's messages; the cursor only moves forward."""
    h = make()
    ot = open_room(h)["operator_token"]
    pause(h, "claude-1")
    m1 = h.tool("lead", "xmuse_send", to="#room", body="one")["result"]["id"]  # the user's reader counts others' words
    m2 = h.tool("lead", "xmuse_send", to="#room", body="two")["result"]["id"]
    m3 = h.tool("lead", "xmuse_send", to="#room", body="three")["result"]["id"]
    own = h.send("#room", "mine")["id"]  # the user's own message: never unread for the user
    admin = h.token("human")
    _, v = view(h, admin)
    assert next(t for t in v["threads"] if t["id"] == "#room")["unread"] == 3
    assert v["mentions_me"] == 0
    ver = v["version"]
    st, out = act(h, ot, act="read", thread="#room", upto=m2)
    assert (st, out) == (200, {"ok": True, "thread": "#room", "last_read_id": m2})
    _, v = view(h, admin)
    assert v["version"] > ver  # a read moves the view on, so a long-polling panel clears its badge
    assert next(t for t in v["threads"] if t["id"] == "#room")["unread"] == 1
    st, out = act(h, ot, act="read", thread="#room", upto=m1)  # backward: stays
    assert out["last_read_id"] == m2
    _, v = view(h, admin)
    assert next(t for t in v["threads"] if t["id"] == "#room")["unread"] == 1
    st, out = act(h, ot, act="read", thread="#room")  # default upto: the newest
    assert out["last_read_id"] == own
    assert act(h, ot, act="read", thread="")[0] == 400
    # a reply to the user's message: mentions_me + for_me for the human reader, no member woken
    r = h.tool("lead", "xmuse_send", to="#room", body="on it", reply_to=own)["result"]
    _, v = view(h, admin)
    assert v["mentions_me"] == 1
    assert next(t for t in v["timeline"] if t["id"] == r["id"])["for_me"] is True
    assert next(t for t in v["threads"] if t["id"] == "#room")["unread"] == 1
    # the room view carries reply_to on every item that has one
    assert next(t for t in v["timeline"] if t["id"] == r["id"])["reply_to"] == own
    assert all("reply_to" not in t for t in v["timeline"] if t["id"] != r["id"])


def test_promote_turns_a_message_into_a_decision(make):
    """T8a H10: promote records a decision by the original sender, notices #room, shows in snapshots."""
    from xmuse import wakepack
    h = make()
    ot = open_room(h)["operator_token"]
    mid = h.send("#room", "use tabs everywhere")["id"]
    st, out = act(h, ot, act="promote", message_id=mid)
    assert st == 200 and out["entry"].startswith("E")
    eid = int(out["entry"][1:])
    e = h.q("select * from entries where id=?", eid)[0]
    assert (e["kind"], e["scope"], e["author"]) == ("decision", "global", "human") and e["via"] == "human"
    assert any(t["kind"] == "system" and f"#{mid} 已设为决定 E{eid}" in t["text"] for t in view(h, ot)[1]["timeline"])
    conn = h.conn()
    a = db.row(conn.execute("select * from agents where id='claude-1'"))
    assert f"E{eid}" in wakepack.inject(conn, h.hub.cfg, a, None).text  # the next wake carries it
    st, out = act(h, ot, act="promote", message_id=mid, scope="role:reviewer")
    assert st == 200 and h.q("select scope from entries where id=?", int(out["entry"][1:]))[0]["scope"] == "role:reviewer"
    assert act(h, ot, act="promote", message_id=9999)[1]["error"] == "unknown_message"
    assert act(h, ot, act="promote", message_id="x")[0] == 400
