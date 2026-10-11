"""Identity enforcement: a foreground agent is bound to one dsh session on the hub; admin sends are visibly `via cli`."""
from xmuse import cli, config, wakepack

FG = {"foreground": True}
A, B = "dsh-sess-A", "dsh-sess-B"


def bind(h, agent, sid):
    return h.post("/v1/relay/bind", {"session_id": sid}, h.token(agent), sid)


def notices(h):
    return [m["body"] for m in h.q("select body from messages where kind='notice' order by id")]


def test_bind_records_single_session_and_notifies_the_dm_thread(make):
    h = make([("dsh-1", "dsh", FG)])
    assert bind(h, "dsh-1", A)["result"] == {"bound": A, "replaced": None}
    assert h.q("select bound_session from agents")[0]["bound_session"] == A
    n = h.q("select thread_id, sender, kind, body from messages")
    assert n[0]["thread_id"] == "dm:dsh-1+human" and n[0]["sender"] == "hub" and A in n[0]["body"]
    assert bind(h, "dsh-1", A)["result"]["replaced"] is None and len(notices(h)) == 1  # same session: silent
    assert bind(h, "dsh-1", B)["result"] == {"bound": B, "replaced": A}
    assert h.q("select bound_session from agents")[0]["bound_session"] == B  # rebinding replaces
    assert A in notices(h)[1] and B in notices(h)[1]
    assert cli.status(h.state)["agents"][0]["bound_session"] == B


def test_bind_validation(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    assert h.post("/v1/relay/bind", {}, h.token("dsh-1"), A)["error"]["code"] == "invalid_arguments"
    assert h.post("/v1/relay/bind", {"session_id": A}, h.token("dsh-1"), B)["error"]["code"] == "invalid_arguments"  # header mismatch
    assert h.post("/v1/relay/bind", {"session_id": A}, h.token("oc"), A)["error"]["code"] == "invalid_arguments"
    assert h.post("/v1/relay/bind", {"session_id": A}, h.token("human"), A)["error"]["code"] == "not_found"


def test_tools_need_the_bound_session_once_bound(make):
    h = make([("dsh-1", "dsh", FG), ("oc", "opencode")])
    # no binding yet: `xmuse tool --agent` keeps working for a foreground session without the bundle
    assert h.tool("dsh-1", "xmuse_whoami")["result"]["id"] == "dsh-1"
    bind(h, "dsh-1", A)
    assert h.tool("dsh-1", "xmuse_whoami", A)["result"]["id"] == "dsh-1"
    for sid in (None, B):
        err = h.tool("dsh-1", "xmuse_send", sid, to="oc", body="hi")["error"]
        assert err["code"] == "not_bound_session"
        assert f"bound to dsh session {A}" in err["message"] and "run /xmuse bind in the session that should act as dsh-1" in err["message"]
    assert h.q("select * from messages where sender='dsh-1'") == []  # nothing was sent
    # not-foreground agents ignore the header; rebinding moves the right
    assert h.tool("oc", "xmuse_whoami", B)["result"]["id"] == "oc"
    bind(h, "dsh-1", B)
    assert h.tool("dsh-1", "xmuse_whoami", A)["error"]["code"] == "not_bound_session"
    assert h.tool("dsh-1", "xmuse_whoami", B)["result"]["id"] == "dsh-1"


def test_another_agents_session_id_does_not_help(make):
    h = make([("dsh-1", "dsh", FG), ("dsh-2", "dsh", FG)])
    bind(h, "dsh-1", A)
    bind(h, "dsh-2", B)
    assert h.tool("dsh-2", "xmuse_whoami", A)["error"]["code"] == "not_bound_session"
    assert h.tool("dsh-1", "xmuse_whoami", B)["error"]["code"] == "not_bound_session"


def test_relay_poll_and_delivered_need_a_binding_and_the_session(make):
    h = make([("dsh-1", "dsh", FG)])
    tok = h.token("dsh-1")
    err = h.post("/v1/relay/poll", {}, tok, A)["error"]
    assert err["code"] == "not_bound_session" and "not bound" in err["message"] and "/xmuse bind dsh-1" in err["message"]
    bind(h, "dsh-1", A)
    assert h.post("/v1/relay/poll", {}, tok)["error"]["code"] == "not_bound_session"
    assert h.post("/v1/relay/poll", {}, tok, B)["error"]["code"] == "not_bound_session"
    assert h.post("/v1/relay/poll", {}, tok, A)["result"]["items"] == []
    h.send("dsh-1", "x")
    did = h.post("/v1/relay/poll", {}, tok, A)["result"]["items"][0]["delivery_id"]
    body = {"delivery_ids": [did], "session_id": A}
    assert h.post("/v1/relay/delivered", body, tok, B)["error"]["code"] == "not_bound_session"
    assert h.post("/v1/relay/delivered", body, tok)["error"]["code"] == "not_bound_session"
    assert h.q("select state from deliveries")[0]["state"] == "queued"
    assert h.post("/v1/relay/delivered", body, tok, A)["result"]["delivered"] == 1


def test_unbind(make):
    h = make([("dsh-1", "dsh", FG)])
    tok = h.token("dsh-1")
    assert h.post("/v1/relay/unbind", {}, tok, A)["result"] == {"unbound": None}  # nothing bound: no-op
    bind(h, "dsh-1", A)
    assert h.post("/v1/relay/unbind", {}, tok, B)["error"]["code"] == "not_bound_session"  # only the bound session
    assert h.post("/v1/relay/unbind", {}, tok, A)["result"] == {"unbound": A}
    assert h.q("select bound_session from agents")[0]["bound_session"] is None
    assert "no longer bound" in notices(h)[-1]
    assert h.tool("dsh-1", "xmuse_whoami")["result"]["id"] == "dsh-1"  # back to the CLI path
    assert h.post("/v1/relay/poll", {}, tok, A)["error"]["code"] == "not_bound_session"


def test_admin_send_is_recorded_via_cli_and_shown_to_agents(make, capsys):
    h = make([("oc", "opencode"), ("dog", "claude", {"desktop": True})])
    h.oc.plan = [{"result": "done"}]
    h.send("oc", "from a terminal")
    [m] = h.q("select sender, via from messages where body='from a terminal'")
    assert (m["sender"], m["via"]) == ("human", "cli") == (config.HUMAN, config.VIA_CLI)
    # inbox, wake tag and the log all say so
    h.wait(lambda: h.turns(), what="oc woken")
    h.wait_quiet()
    inbox = h.tool("oc", "xmuse_inbox", unread_only=False)["result"]
    assert inbox[0]["from"] == "human" and inbox[0]["via"] == "cli"
    assert 'from="human" via="cli"' in wakepack.tag({**h.q("select * from messages")[0]}, {})
    h.send("dog", "to the coordinator")
    pend = h.tool("dog", "xmuse_inbox")["result"]
    assert pend[0]["via"] == "cli"
    cli.log(h.state, None, False)
    assert "human (via cli)" in capsys.readouterr().out
    # a coordinator's on_behalf_of relay keeps its own via
    h.tool("dog", "xmuse_send", to="oc", body="relayed", on_behalf_of="human")
    assert h.q("select via from messages where body='relayed'") == [{"via": "dog"}]


def test_identity_rules_are_in_the_templates_skill_and_foreground_block():
    from pathlib import Path
    from xmuse.adapters import dsh
    texts = {f: " ".join(f.read_text().split())
             for f in (config.TEMPLATES / "AGENTS.xmuse.md", config.TEMPLATES.parent / "skill" / "xmuse-collab" / "SKILL.md")}
    for f, t in texts.items():
        assert "Never read `tokens/`" in t and "never use the admin `xmuse send` command to speak" in t, f
        assert "`xmuse tool --agent <your id>`" in t, f
        assert "human (via cli)" in t and "confirm with the user" in t, f
    block = " ".join(dsh.foreground_section(Path("/ws"), {"id": "dsh-1"}).split())
    assert "Never read `tokens/`" in block and "never use the admin `xmuse send` command to speak" in block
    assert "/xmuse bind dsh-1" in block
