"""T8 H12: project brief, fresh-session entry-pack sections, join notice.

No engine turns run here: packs are rendered directly and members that would be
woken are paused, so results are deterministic.
"""
from test_room import act, call, open_room, view
from test_trust import OC
from xmuse import config, db, wakepack

WHY = {k: k for k in ("what", "why", "tradeoff", "open_questions", "next_action")}


def pause(h, *agents):
    with db.tx(h.conn()) as c:
        for a in agents:
            c.execute("update agents set paused=1 where id=?", (a,))


def test_brief_records_replaces_and_notices(make):
    h = make()
    ot = open_room(h)["operator_token"]
    st, out = act(h, ot, act="brief", text="Build a parser. Stack: Python.")
    assert st == 200 and out["entry"].startswith("E")
    eid = int(out["entry"][1:])
    e = h.q("select * from entries where id=?", eid)[0]
    assert (e["kind"], e["scope"], e["status"]) == ("convention", "global", "active")
    assert e["statement"].startswith("[brief] ")
    assert any(t["kind"] == "system" and f"项目简介已更新 E{eid}" in t["text"] for t in view(h, ot)[1]["timeline"])
    st, out2 = act(h, ot, act="brief", text="Build a parser. Stack: Rust.")
    assert st == 200 and out2["entry"] != out["entry"]
    assert h.q("select status from entries where id=?", eid)[0]["status"] == "superseded"
    assert act(h, ot, act="brief", text="  ")[0] == 400


def test_brief_needs_operator_or_host(make):
    h = make()
    ot = open_room(h)["operator_token"]
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    assert act(h, ot, act="brief", text="x")[0] == 200  # operator
    assert act(h, lead_tok, "S-lead", act="brief", text="y")[0] == 200  # the host itself
    assert act(h, h.token("claude-1"), act="brief", text="z")[0] == 403  # another member: no


def test_rooms_reports_brief_missing(make):
    h = make()
    st, out = call(h, "POST", "/v1/rooms", {"dir": str(h.ws), "name": "dev", "vendor": "claude",
                                            "session_id": "S"}, key=h.key())
    assert st == 200 and out["brief_missing"] is True


def test_rooms_reports_brief_present(make):
    h = make(())  # a room opens once per hub: this one gets its brief before the host opens it
    st, out = call(h, "POST", "/v1/act", {"act": "brief", "text": "Some project."}, h.token("human"))
    assert st == 200
    st, out = call(h, "POST", "/v1/rooms", {"dir": str(h.ws), "name": "dev", "vendor": "claude",
                                            "session_id": "S"}, key=h.key())
    assert st == 200 and out["brief_missing"] is False


def pack(h, member, session=None):
    conn = h.conn()
    a = db.row(conn.execute("select * from agents where id=?", (member,)))
    return wakepack.render(conn, h.hub.cfg, a, [], session, str(h.ws))


def fresh_team(make):
    """lead hosts, brief written, opencode-1 paused holding a handoff, oc-new just added (paused)."""
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    act(h, ot, act="brief", text="Build a parser.")
    pause(h, "opencode-1")
    h.tool("lead", "xmuse_send", to="opencode-1", body="parse this file", kind="handoff", why=WHY,
           _session="S-lead")
    act(h, ot, act="member_add", vendor="opencode", name="oc-new", role="executor")
    pause(h, "oc-new")
    return h


def test_fresh_pack_has_brief_and_wip_but_rewake_has_neither(make):
    h = fresh_team(make)
    fresh = pack(h, "oc-new")
    assert "Project brief:\n[brief] Build a parser." in fresh.text
    assert "Work in progress:" in fresh.text
    assert "- opencode-1: paused" in fresh.text and "parse this file" in fresh.text
    assert "- lead: idle" in fresh.text and "no open work" in fresh.text
    again = pack(h, "oc-new", session=7)
    assert "Project brief:" not in again.text and "Work in progress:" not in again.text


def test_wip_truncates_from_the_back_with_more(make):
    h = make(OC)
    open_room(h, vendor="claude")
    from types import SimpleNamespace
    conn = h.conn()
    roster = {"me": {"id": "me"}} | {f"m{i:02d}-{'x' * 200}": {"id": f"m{i:02d}-{'x' * 200}"} for i in range(30)}
    x = SimpleNamespace(conn=conn, cfg=h.hub.cfg, agent={"id": "me"}, roster=roster, fresh=True)
    t = wakepack.wip(x)
    assert wakepack.tokens(t) <= 1500 + 20 and "…(" in t and "more)" in t


def test_member_add_notices_once_and_wakes_the_host(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]  # lead hosts
    act(h, ot, act="member_add", vendor="opencode", name="oc-new", role="executor")
    want = f"oc-new 已加入（opencode · {config.MODELS['opencode']}）"
    bodies = [m["body"] for m in h.q("select body from messages where thread_id='#room' and kind='notice'")]
    assert bodies.count(want) == 1
    assert h.q("select wake, state from deliveries d join messages m on m.id=d.message_id"
               " where m.body = ? and d.recipient='lead'", want) == [{"wake": 1, "state": "queued"}]
    h.hub._member_joined(h.conn(), "oc-new", "opencode", config.MODELS["opencode"])
    assert bodies == [m["body"] for m in h.q("select body from messages where thread_id='#room' and kind='notice'")]
