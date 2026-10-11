"""dsh relay: a polled (foreground) agent's bundle long-polls the hub and reports deliveries into its dsh session."""
import threading
import time

from xmuse import db

FG = {"foreground": True}
SID = "dsh-sess-1"


def bound(h, agent, sid=SID):
    """Bind `sid` as the agent's session once (the bundle does this on /xmuse bind)."""
    if not h.q("select 1 from agents where id=? and bound_session=?", agent, sid):
        out = h.post("/v1/relay/bind", {"session_id": sid}, h.token(agent), sid)
        assert "result" in out, out
    return sid


def poll(h, agent, cursor=0, wait_s=0):
    return h.post("/v1/relay/poll", {"cursor": cursor, "wait_s": wait_s}, h.token(agent), bound(h, agent))


def delivered(h, agent, ids, sid=SID):
    return h.post("/v1/relay/delivered", {"delivery_ids": ids, "session_id": sid}, h.token(agent), bound(h, agent, sid))


def test_poll_returns_rendered_text_and_items(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    assert poll(h, "dsh-1")["result"] == {"cursor": 0, "items": [], "text": ""}
    h.send("dsh-1", "please do X")
    h.send("oc", "not for dsh-1")
    r = poll(h, "dsh-1")["result"]
    assert len(r["items"]) == 1 and r["cursor"] == r["items"][0]["delivery_id"]
    it = r["items"][0]
    assert it["from"] == "human" and it["kind"] == "message" and it["thread"] == "dm:dsh-1+human" and it["wake"] is True
    assert "[xmuse] Messages relayed by xmuse" in r["text"]
    assert '<xmuse from="human" via="cli" family="human" thread="dm:dsh-1+human" kind="message"' in r["text"]
    assert "please do X" in r["text"] and "xmuse_send" in r["text"] and "not for dsh-1" not in r["text"]
    # same cursor -> same items until delivered; higher cursor -> none
    assert poll(h, "dsh-1")["result"]["items"] == r["items"]
    assert poll(h, "dsh-1", cursor=r["cursor"])["result"]["items"] == []


def test_poll_blocks_until_a_message_arrives(make):
    h = make([("dsh-1", "dsh", FG)])
    out = {}
    t = threading.Thread(target=lambda: out.update(poll(h, "dsh-1", wait_s=10)))
    t0 = time.time()
    t.start()
    time.sleep(0.8)
    assert t.is_alive()
    h.send("dsh-1", "wake", mentions=["dsh-1"])
    t.join(5)
    assert not t.is_alive() and time.time() - t0 < 5
    assert "wake" in out["result"]["text"]


def test_poll_timeout_returns_empty_and_other_calls_stay_responsive(make):
    h = make([("dsh-1", "dsh", FG)])
    bound(h, "dsh-1")
    t = threading.Thread(target=lambda: poll(h, "dsh-1", wait_s=1.5))
    t.start()
    time.sleep(0.3)
    t1 = time.time()
    assert h.tool("dsh-1", "xmuse_whoami", SID)["result"]["id"] == "dsh-1"  # not blocked by the poll
    assert time.time() - t1 < 1
    t.join(5)
    assert not t.is_alive()


def test_poll_works_for_group_mentions_and_skips_passive_acked_canceled(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    h.send("#t", "passive for dsh-1", mentions=["oc"])
    h.send("dsh-1", "acked")
    h.send("dsh-1", "canceled")
    h.send("#t", "mentioned", mentions=["dsh-1"])
    mid = {r["body"]: r["id"] for r in h.q("select id, body from messages")}
    h.tool("dsh-1", "xmuse_ack", ids=[mid["acked"]])
    with db.tx(h.conn()) as c:
        c.execute("update deliveries set state='canceled' where message_id=? and recipient='dsh-1'", (mid["canceled"],))
    r = poll(h, "dsh-1")["result"]
    assert [i["message_id"] for i in r["items"]] == [mid["mentioned"]] and r["items"][0]["mentions"] == ["dsh-1"]


def test_relay_only_for_polled_agents_and_agent_tokens(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    assert h.post("/v1/relay/poll", {}, h.token("oc"), "s")["error"]["code"] == "invalid_arguments"
    assert h.post("/v1/relay/bind", {"session_id": "s"}, h.token("oc"), "s")["error"]["code"] == "invalid_arguments"
    assert h.post("/v1/relay/delivered", {"delivery_ids": [1], "session_id": "s"}, h.token("oc"), "s")["error"]["code"] == "invalid_arguments"
    assert h.post("/v1/relay/poll", {}, h.token("human"), "s")["error"]["code"] == "not_found"  # admin token has no relay
    assert h.post("/v1/relay/poll", {}, "nope")["status"] == 401


def test_delivered_marks_state_session_and_never_wakes(make):
    h = make([("dsh-1", "dsh", FG)])
    h.plan_dsh({})
    h.send("dsh-1", "one")
    h.send("dsh-1", "two")
    r = poll(h, "dsh-1")["result"]
    ids = [i["delivery_id"] for i in r["items"]]
    out = delivered(h, "dsh-1", ids)
    assert out["result"] == {"delivered": 2, "session": "dsh-sess-1"}
    ds = h.q("select state, delivered_at, delivered_session, read_at from deliveries order by id")
    assert all(d["state"] == "delivered" and d["delivered_session"] == "dsh-sess-1" and d["delivered_at"] and d["read_at"]
               for d in ds)
    assert poll(h, "dsh-1")["result"]["items"] == []
    s = h.q("select vendor_session, origin, state, wakes from sessions where agent_id='dsh-1'")
    assert s == [{"vendor_session": "dsh-sess-1", "origin": "relay", "state": "current", "wakes": 1}]
    # not queued anywhere any more; engine did nothing
    from xmuse import cli
    assert cli.status(h.state)["queued"] == [] and h.turns() == [] and h.dsh_calls() == []
    # a second delivery in another session retires the first; idempotent re-report counts 0
    h.send("dsh-1", "three")
    r = poll(h, "dsh-1")["result"]
    bound(h, "dsh-1", "dsh-sess-2")  # the user re-bound: the old session loses the role
    r = h.post("/v1/relay/poll", {}, h.token("dsh-1"), "dsh-sess-2")["result"]
    delivered(h, "dsh-1", [i["delivery_id"] for i in r["items"]], "dsh-sess-2")
    assert delivered(h, "dsh-1", ids, "dsh-sess-2")["result"]["delivered"] == 0
    cur = h.q("select vendor_session, state from sessions where agent_id='dsh-1' order by id")
    assert [(c["vendor_session"], c["state"]) for c in cur] == [("dsh-sess-1", "retired"), ("dsh-sess-2", "current")]


def test_delivered_cannot_touch_other_agents_and_validates(make):
    h = make([("dsh-1", "dsh", FG), ("dsh-2", "dsh", FG)])
    h.send("dsh-2", "for 2")
    did = poll(h, "dsh-2")["result"]["items"][0]["delivery_id"]
    bound(h, "dsh-1", "s")
    assert delivered(h, "dsh-1", [did], "s")["result"]["delivered"] == 0
    assert h.q("select state from deliveries where id=?", did)[0]["state"] == "queued"
    bad = h.post("/v1/relay/delivered", {"delivery_ids": "x", "session_id": "s"}, h.token("dsh-1"), "s")
    assert bad["error"]["code"] == "invalid_arguments"


def test_reply_via_tools_after_relay_reaches_the_sender(make):
    h = make([("dsh-1", "dsh", FG), ("dog", "claude", {"desktop": True})])
    h.tool("dog", "xmuse_send", to="dsh-1", body="do it")
    r = poll(h, "dsh-1")["result"]
    assert 'from="dog"' in r["text"]
    delivered(h, "dsh-1", [r["items"][0]["delivery_id"]])
    assert h.tool("dsh-1", "xmuse_send", SID, to="dog", body="done")["result"]["id"]
    assert [m["body"] for m in h.tool("dog", "xmuse_inbox")["result"] if m["from"] != "hub"] == ["done"]  # + the bind notice


def test_coordinator_rule_text():
    from xmuse import config
    for f in (config.TEMPLATES / "AGENTS.xmuse.md", config.TEMPLATES.parent / "skill" / "xmuse-collab" / "SKILL.md"):
        t = " ".join(f.read_text(encoding="utf-8").split())
        assert "Send as yourself by default" in t and "explicitly asks for the message to go out in their name" in t
        assert "offer to resend in their name" in t and "Replies addressed to the user arrive in your inbox" in t
        assert "directly asks for something to be done by a peer" not in t
        assert "mention only the implementer; the implementer requests the review" in t
        assert "restart it immediately without being asked" in t and "read the inbox once" in t


def test_dsh_bundle_tool_schemas_match_tools_py():
    """integrations/dsh-bundle/tools.json is the bundle's fallback copy of TOOLS (the hub's <state>/tools.json wins)."""
    import json
    from pathlib import Path
    from xmuse.tools import TOOLS
    mirrored = json.loads((Path(__file__).parents[1] / "integrations" / "dsh-bundle" / "tools.json").read_text(encoding="utf-8"))
    assert mirrored == json.loads(json.dumps(TOOLS)), (
        "regenerate: python -c 'import json;from xmuse.tools import TOOLS;"
        "print(json.dumps(TOOLS, indent=1, ensure_ascii=False))' > integrations/dsh-bundle/tools.json")
