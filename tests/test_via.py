"""A desktop coordinator relays the user's own decisions: sender/author `human`, `via` the coordinator."""

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
