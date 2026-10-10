"""A desktop coordinator relays the user's own decisions: sender/author `human`, `via` the coordinator."""
import time

from xmuse import cli, db

TWO = [("dog", "claude", {"desktop": True}), ("oc", "opencode")]


def test_relayed_decision_is_the_users_with_via(make):
    h = make(TWO)
    h.oc.plan = [{"result": "done"}]
    out = h.tool("dog", "xmuse_send", to="oc", body="use tabs everywhere", kind="decision", on_behalf_of="human")
    assert "result" in out, out
    [m] = h.q("select * from messages where kind='decision'")
    assert (m["sender"], m["via"]) == ("human", "dog")
    [e] = h.q("select * from entries")
    assert (e["author"], e["via"], e["kind"]) == ("human", "dog", "decision")
    assert h.q("select recipient, wake from deliveries") == [{"recipient": "oc", "wake": 1}]  # as a human message
    h.wait(lambda: h.turns(), what="peer woken")
    assert h.q("select via from messages where sender='dog'") == []
    # authorship is shown everywhere
    ctx = h.tool("oc", "xmuse_context")["result"]
    pubs = [x for es in ctx["layers"].values() for x in es]
    assert pubs and pubs[0]["author"] == "human" and pubs[0]["via"] == "dog"
    assert h.tool("oc", "xmuse_inbox", unread_only=False)["result"][0]["via"] == "dog"
    h.wait_quiet()


def test_group_relay_mentions_wake_peers_not_the_coordinator(make):
    h = make(TWO)
    h.oc.plan = [{"result": "done"}]
    h.tool("dog", "xmuse_send", to="#task", body="oc please start", mentions=["oc"], on_behalf_of="human")
    assert {(d["recipient"], d["wake"]) for d in h.q("select recipient, wake from deliveries")} == {("oc", 1)}
    h.wait_quiet()


def test_woken_never_lists_the_desktop_coordinator(make):
    h = make(TWO)
    assert h.tool("oc", "xmuse_send", to="dog", body="fyi")["result"]["woken"] == []  # DM to the coordinator
    time.sleep(0.5)
    assert h.turns() == []  # and the hub never starts a turn for it (its delivery waits to be polled)


def test_handoff_assignment_author_is_human_via(make):
    h = make(TWO)
    h.oc.plan = [{"result": "done"}]
    why = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
    out = h.tool("dog", "xmuse_send", to="oc", body="build it", kind="handoff", why=why, on_behalf_of="human")
    assert "result" in out, out
    [e] = h.q("select * from entries where kind='assignment'")
    assert (e["author"], e["via"], e["assignee"]) == ("human", "dog", "oc")
    h.wait_quiet()


def test_non_desktop_agent_cannot_relay(make):
    h = make([("cat", "claude"), ("oc", "opencode")])
    out = h.tool("cat", "xmuse_send", to="oc", body="x", on_behalf_of="human")
    assert out["error"]["code"] == "invalid_arguments" and "on_behalf_of" in out["error"]["message"]
    assert h.q("select * from messages") == []
    bad = h.tool("cat", "xmuse_send", to="oc", body="x", on_behalf_of="cat")
    assert bad["error"]["code"] == "invalid_arguments"


def test_log_align_and_wake_tag_show_via(make, capsys):
    from xmuse import wakepack
    h = make(TWO)
    h.oc.plan = [{"result": "done"}]
    h.tool("dog", "xmuse_send", to="oc", body="use tabs", kind="decision", on_behalf_of="human")
    h.wait_quiet()
    cli.log(h.state, None, False)
    assert "human (via dog)" in capsys.readouterr().out
    assert "human (via dog)" in cli.align_lines(h.state, False)[0]
    m = h.q("select * from messages where kind='decision'")[0]
    assert 'from="human" via="dog"' in wakepack.tag(m, {})
    assert "via=" not in wakepack.tag({**m, "via": None}, {})


def test_old_database_without_via_columns_still_opens(tmp_path):
    p = tmp_path / "hub.db"
    db.init(p).close()
    c = db.connect(p)
    c.execute("alter table messages drop column via")
    c.execute("alter table entries drop column via")
    c.commit()
    c.close()
    c = db.init(p)  # migration adds the columns back
    assert "via" in {r[1] for r in c.execute("pragma table_info(messages)")}
    assert "via" in {r[1] for r in c.execute("pragma table_info(entries)")}


# ---- replies to the user also reach the desktop coordinator --------------------------------------

def test_replies_to_human_also_reach_the_coordinator(make):
    h = make(TWO)
    out = h.tool("oc", "xmuse_send", to="human", body="result is ready")
    assert out["result"]["woken"] == []
    [d] = h.q("select recipient, wake, state, read_at from deliveries")
    assert (d["recipient"], d["wake"], d["state"], d["read_at"]) == ("dog", 0, "passive", None)
    [m] = h.tool("dog", "xmuse_inbox")["result"]
    assert m["body"] == "result is ready" and m["from"] == "oc"
    # the coordinator may read a thread it is not a member of because the user is in it
    assert h.tool("dog", "xmuse_thread", id=m["thread"])["result"]["messages"][0]["body"] == "result is ready"
    # done messages too
    h.tool("oc", "xmuse_done", summary="finished", next="nothing")
    assert [x["kind"] for x in h.tool("dog", "xmuse_inbox")["result"]] == ["done"]


def test_coordinator_delivery_not_duplicated_and_never_to_itself(make):
    h = make(TWO)
    h.oc.plan = [{"result": "done"}]
    h.tool("oc", "xmuse_send", to="#g", body="to all", mentions=["dog"])  # dog is a member already
    assert len(h.q("select * from deliveries where recipient='dog'")) == 1
    mid = h.tool("dog", "xmuse_send", to="human", body="hello user")["result"]["id"]
    assert h.q("select * from deliveries where recipient='dog' and message_id=?", mid) == []
    # a message from the user gets no extra coordinator copy
    h.send("oc", "do it")
    assert len(h.q("select * from deliveries where recipient='dog'")) == 1
    h.wait(lambda: h.turns(), what="peer woken")


def test_coordinator_cannot_read_threads_without_the_user(make):
    h = make(TWO + [("oc2", "opencode")])
    h.tool("oc", "xmuse_send", to="oc2", body="private")
    out = h.tool("dog", "xmuse_thread", id="dm:oc+oc2")
    assert "error" in out, out
    h.wait_quiet()
