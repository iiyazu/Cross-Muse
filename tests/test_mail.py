"""Messages, threads, deliveries and the model-facing tools through the hub's HTTP surface."""
import pytest

from xmuse import tools
from xmuse.tools import ToolError


def three(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")])
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"  # turns start and fail fast; mail is the point
    return h


def pause(h, agent):
    """Keep the engine from admitting (and so marking read) the agent's mail while a test reads its inbox."""
    from xmuse import db
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1 where id=?", (agent,))


def test_send_writes_message_and_one_delivery_per_member(make):
    h = three(make)
    out = h.send("#g", "hello", mentions=["claude-2"])
    assert out["woken"] == ["claude-2"]
    ds = h.q("select recipient, wake, state from deliveries order by recipient")
    assert [(d["recipient"], d["wake"]) for d in ds] == [("claude-1", 0), ("claude-2", 1), ("claude-3", 0)]
    assert {d["state"] for d in ds if not d["wake"]} == {"passive"}
    assert h.q("select kind, owner from threads")[0] == {"kind": "group", "owner": None}
    members = [r["member"] for r in h.q("select member from thread_members order by member")]
    assert members == ["claude-1", "claude-2", "claude-3", "human"]


def test_dm_to_human_wakes_nobody(make):
    h = three(make)
    h.plan_claude({})
    r = h.tool("claude-1", "xmuse_send", to="human", body="status: done")["result"]
    assert r["woken"] == [] and r["thread"] == "dm:claude-1+human"
    assert h.q("select count(*) n from deliveries")[0]["n"] == 0


def test_agent_dm_wakes_recipient_not_sender(make):
    h = three(make)
    r = h.tool("claude-1", "xmuse_send", to="claude-3", body="hi")["result"]
    assert r == {"id": 1, "thread": "dm:claude-1+claude-3", "woken": ["claude-3"]}
    assert h.q("select recipient, wake from deliveries") == [{"recipient": "claude-3", "wake": 1}]
    # a message from an agent outside any turn starts its own chain
    assert h.q("select origin from chains")[0]["origin"] == "agent:claude-1"


def test_errors_name_fields_and_allowed_values(make):
    h = three(make)
    e = h.tool("claude-1", "xmuse_send", to="nobody", body="x")["error"]
    assert e["code"] == "unknown_recipient" and "claude-2" in e["message"] and "human" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="#g", body="x", mentions=["ghost"])["error"]
    assert e["code"] == "invalid_arguments" and "claude-2, claude-3" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="claude-2", body="x", kind="chat")["error"]
    assert "kind must be one of: message, handoff" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="claude-2", body="x", kind="handoff", why={"what": "a"})["error"]
    assert "why.why, why.tradeoff, why.open_questions, why.next_action" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="claude-1", body="x")["error"]
    assert "yourself" in e["message"]
    e = h.tool("claude-1", "xmuse_nope")["error"]
    assert e["code"] == "unknown_tool" and "xmuse_send" in e["message"]
    assert h.q("select count(*) n from messages")[0]["n"] == 0  # nothing half-written


def test_handoff_keeps_why_first_fields(make):
    h = three(make)
    why = {"what": "added sub()", "why": "spec", "tradeoff": "no bigints", "open_questions": "none",
           "next_action": "review calc.py"}
    pause(h, "claude-2")
    h.tool("claude-1", "xmuse_send", to="claude-2", body="handing over", kind="handoff", why=why)
    inbox = h.tool("claude-2", "xmuse_inbox")["result"]
    assert inbox[0]["why"] == why and inbox[0]["kind"] == "handoff"


def test_inbox_orders_mentions_first_and_marks_read(make):
    h = three(make)
    pause(h, "claude-2")
    h.send("#g", "fyi for all")
    h.send("#g", "claude-2 act", mentions=["claude-2"])
    first = h.tool("claude-2", "xmuse_inbox")["result"]
    assert [m["body"] for m in first] == ["claude-2 act", "fyi for all"]
    assert first[0]["mentioned"] is True and first[1]["mentioned"] is False
    assert h.tool("claude-2", "xmuse_inbox")["result"] == []
    assert len(h.tool("claude-2", "xmuse_inbox", unread_only=False)["result"]) == 2


def test_ack_with_outcome(make):
    h = three(make)
    m = h.send("#g", "please review", mentions=["claude-2"])
    assert h.tool("claude-2", "xmuse_ack", ids=[m["id"]], outcome="approved")["result"] == {"acked": 1}
    assert h.q("select outcome from deliveries where recipient='claude-2'")[0]["outcome"] == "approved"
    assert h.tool("claude-2", "xmuse_inbox", unread_only=False)["result"] == []
    assert h.tool("claude-2", "xmuse_ack", ids=["x"])["error"]["message"] == "xmuse_ack argument ids[0] must be a integer"


def test_thread_read_search_and_membership(make):
    h = three(make)
    h.send("#g", "alpha decision")
    h.send("#g", "beta")
    h.tool("claude-1", "xmuse_send", to="claude-2", body="private")
    r = h.tool("claude-3", "xmuse_thread", id="#g")["result"]
    assert [m["body"] for m in r["messages"]] == ["alpha decision", "beta"]
    assert [m["body"] for m in h.tool("claude-3", "xmuse_thread", id="#g", query="alp")["result"]["messages"]] == \
        ["alpha decision"]
    assert len(h.tool("claude-3", "xmuse_thread", id="#g", limit=1)["result"]["messages"]) == 1
    e = h.tool("claude-3", "xmuse_thread", id="dm:claude-1+claude-2")["error"]
    assert e["code"] == "unknown_thread" and "#g" in e["message"]


def test_context_returns_the_alignment_view(make):
    h = three(make)
    h.tool("claude-1", "xmuse_send", to="#g", body="use snake_case", kind="decision")
    q = h.tool("claude-1", "xmuse_send", to="#g", body="int or float?", kind="question", mentions=["claude-2"])
    h.tool("claude-2", "xmuse_send", to="#g", body="float", resolves=["E2"])
    v = h.tool("claude-3", "xmuse_context")["result"]
    assert [e["statement"] for e in v["layers"]["thread:#g"]] == ["use snake_case"]
    assert v["assigned"] == [] and v["ready"] == [] and v["truncated"] == [] and q["result"]["entries"] == ["E2"]


def test_whoami(make):
    h = three(make)
    r = h.tool("claude-2", "xmuse_whoami")["result"]
    assert r["id"] == "claude-2" and r["workspace"] == str(h.ws)
    assert [p["id"] for p in r["peers"]] == ["claude-1", "claude-3", "human"]


def test_done_outside_a_turn_goes_to_the_human_dm(make):
    h = three(make)
    r = h.tool("claude-1", "xmuse_done", summary="finished", next="none")["result"]
    assert r == {"recorded": True, "thread": "dm:claude-1+human"}
    assert h.q("select kind, body from messages")[0] == {"kind": "done", "body": "finished\nnext: none"}


def test_hub_notice_never_wakes(make):
    from xmuse import mail
    h = three(make)
    mail.notice(h.conn(), "#g", "fyi from hub")
    assert h.q("select sender, kind from messages") == [{"sender": "hub", "kind": "notice"}]
    assert h.q("select count(*) n from deliveries")[0]["n"] == 0


def test_auth(make):
    h = three(make)
    assert h.post("/v1/tools/xmuse_whoami", {"args": {}}, "xmt_forged")["status"] == 401
    assert h.post("/v1/admin/send", {"to": "claude-1", "body": "x"}, h.token("claude-1"))["error"]["code"] == "not_found"
    assert h.post("/v1/tools/xmuse_whoami", {"args": {}}, h.token("human"))["error"]["code"] == "not_found"
    assert h.post("/v1/admin/send", {"to": "claude-1"}, h.token("human"))["status"] == 400


@pytest.mark.parametrize("name,args,msg", [
    ("xmuse_send", {"to": "a"}, "missing required arguments: body"),
    ("xmuse_send", {"to": "a", "body": "b", "cc": 1}, "unknown arguments: cc; allowed: to, body, kind"),
    ("xmuse_send", {"to": 3, "body": "b"}, "to must be a string"),
    ("xmuse_send", {"to": "a", "body": "b", "mentions": "x"}, "mentions must be a array"),
    ("xmuse_send", {"to": "a", "body": "b", "mentions": [1]}, "mentions[0] must be a string"),
    ("xmuse_send", {"to": "a", "body": "b", "why": {"how": 1}}, "why got unknown fields: how; allowed: what"),
    ("xmuse_send", {"to": "a", "body": "b", "why": {"what": 1}}, "why.what must be a string"),
    ("xmuse_inbox", {"unread_only": "yes"}, "unread_only must be a boolean"),
    ("xmuse_thread", {"id": "#g", "limit": True}, "limit must be a integer"),
    ("xmuse_done", {"summary": "s"}, "missing required arguments: next"),
])
def test_validation_messages(name, args, msg):
    with pytest.raises(ToolError) as e:
        tools.validate(name, args)
    assert msg in e.value.message


def test_tool_count_and_short_descriptions():
    assert len(tools.TOOLS) == 9  # design §4.3 had 8 (xmuse_approve is the coordinator's); + xmuse_leave_thread (T2)
    assert all(len(t["description"]) <= 200 for t in tools.TOOLS)


def test_send_dedupes_across_resumed_turns(make, monkeypatch):
    """M1c task 3 (M1b report section 6 item 3): a killed turn's replay in the next turn
    collapses; the same content after a succeeded turn sends again (ping-pong)."""
    from xmuse import db, mail
    h = make()
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    conn, cfg = h.conn(), h.hub.cfg
    with db.tx(conn):
        chain = conn.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at)"
                             " values(?,?,?,?,?)",
                             ("dm:claude-1+human", "agent:claude-1",
                              cfg["max_chain_wakes"], cfg["max_chain_tokens"], db.now())).lastrowid
        t1 = conn.execute("insert into turns(agent_id, adapter, chain_id, state, started_at)"
                          " values(?,?,?,?,?)",
                          ("claude-1", "claude_resume", chain, "running", db.now())).lastrowid
    m1 = mail.send(conn, cfg, "claude-1", "human", "K1")
    assert "duplicate" not in m1
    with db.tx(conn):
        conn.execute("update turns set state='interrupted', ended_at=? where id=?", (db.now(), t1))
        conn.execute("insert into turns(agent_id, adapter, chain_id, state, started_at) values(?,?,?,?,?)",
                     ("claude-1", "claude_resume", chain, "running", db.now()))
    m2 = mail.send(conn, cfg, "claude-1", "human", "K1")
    assert m2["duplicate"] is True and m2["id"] == m1["id"]
    assert conn.execute("select count(*) from messages where sender='claude-1'").fetchone()[0] == 1
    with db.tx(conn):
        conn.execute("update turns set state='succeeded', ended_at=? where state='running'", (db.now(),))
        conn.execute("insert into turns(agent_id, adapter, chain_id, state, started_at) values(?,?,?,?,?)",
                     ("claude-1", "claude_resume", chain, "running", db.now()))
    m3 = mail.send(conn, cfg, "claude-1", "human", "K1")
    assert "duplicate" not in m3 and m3["id"] != m1["id"]
    m4 = mail.send(conn, cfg, "claude-1", "human", "K1")
    assert m4["duplicate"] is True and m4["id"] == m3["id"]


def test_wake_all_wakes_every_agent_member_but_the_sender(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")], wake="all")
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    assert h.send("#g", "hello")["woken"] == ["claude-1", "claude-2", "claude-3"]
    r = h.tool("claude-1", "xmuse_send", to="#g", body="hi all")["result"]
    assert r["woken"] == ["claude-2", "claude-3"]


def test_context_without_alignment_returns_recent_messages(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude")], alignment="off")
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    h.tool("claude-1", "xmuse_send", to="#g", body="use snake_case", kind="decision")
    v = h.tool("claude-2", "xmuse_context")["result"]
    assert [m["body"] for t in v["threads"] for m in t["messages"]] == ["use snake_case"] and "layers" not in v
    assert h.tool("claude-2", "xmuse_context", topic="#g")["result"]["threads"][0]["thread"] == "#g"
