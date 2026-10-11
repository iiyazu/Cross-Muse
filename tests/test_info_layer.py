"""T14: module scopes, dependency wake, question routing, and the information-layer switch (T-plain)."""
import json

from xmuse import align, db, wakepack

WHY = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
TEAM = [("plan", "claude"), ("e1", "claude"), ("e2", "claude"), ("other", "claude")]


def team(make, **cfg):
    h = make(TEAM, **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"  # turns end at once; routing is the point
    return h


def ok(out):
    assert "result" in out, out
    return out["result"]


def ctx(h, agent):
    return ok(h.tool(agent, "xmuse_context"))


def visible(h, agent):
    v = ctx(h, agent)
    return {e["statement"] for es in v["layers"].values() for e in es} | {e["statement"] for e in v["assigned"]}


def plan(h):
    """P hands parser to e1 and lexer to e2; e1's part waits on a convention P has not settled yet (a question)."""
    q = ok(h.tool("plan", "xmuse_send", to="#g", body="token format: offsets or line/col?", kind="question",
                  scope="module:lexer"))["entries"][0]
    a1 = ok(h.tool("plan", "xmuse_send", to="#g", body="implement the parser", kind="handoff", why=WHY,
                   mentions=["e1"], scope="module:parser", depends_on=[q]))
    a2 = ok(h.tool("plan", "xmuse_send", to="#g", body="implement the lexer", kind="handoff", why=WHY,
                   mentions=["e2"], scope="module:lexer,tokens"))
    return q, a1, a2


def test_module_scoped_entries_reach_only_their_module(make):
    h = team(make)
    plan(h)
    with h.conn() as c:
        assert align.subscribed(c, "e1") == ["parser"] and align.subscribed(c, "e2") == ["lexer", "tokens"]
        assert align.subscribed(c, "plan") == ["lexer", "parser", "tokens"] and align.subscribed(c, "other") == []
    ok(h.tool("e1", "xmuse_send", to="#g", body="the parser needs byte offsets on every token", kind="assumption",
              scope="module:lexer"))
    ok(h.tool("e2", "xmuse_send", to="#g", body="parser errors are ParseError(pos)", kind="decision",
              scope="module:parser"))
    ok(h.tool("plan", "xmuse_send", to="#g", body="UTF-8 everywhere", kind="decision", scope="all"))
    assumption, decision = "the parser needs byte offsets on every token", "parser errors are ParseError(pos)"
    assert {assumption, "UTF-8 everywhere"} <= visible(h, "e2") and decision in visible(h, "e2")  # lexer + own entry
    assert decision in visible(h, "e1") and assumption in visible(h, "e1")  # parser module + own entry
    assert {assumption, decision} <= visible(h, "plan")  # the planner sees every module it handed out
    assert visible(h, "other") & {assumption, decision} == set() and "UTF-8 everywhere" in visible(h, "other")
    with h.conn() as c:
        snap = wakepack.snapshot(c, h.hub.cfg, "e2")
        assert "Module lexer:" in snap and assumption in snap
        assert assumption not in wakepack.snapshot(c, h.hub.cfg, "other")
        seq = align.current_seq(c)
    # the planner settles the assumption: no scope given, the decision keeps the module; its author learns the answer
    eid = next(e["id"] for e in ctx(h, "e2")["layers"]["module:lexer"] if e["statement"] == assumption)
    ok(h.tool("plan", "xmuse_send", to="#g", body="tokens carry byte offsets (start, end)", kind="decision",
              supersedes=eid))
    with h.conn() as c:
        new = db.row(c.execute("select * from entries where statement like 'tokens carry%'"))
        assert new["scope"] == "module:lexer"
        assert "tokens carry byte offsets" in wakepack.delta(c, h.hub.cfg, "e2", seq)
        d1 = wakepack.delta(c, h.hub.cfg, "e1", seq)  # e1 asked (authored the assumption) but is not on lexer
        assert f'superseded {eid}' in d1 and '"tokens carry byte offsets (start, end)"' in d1
        assert wakepack.delta(c, h.hub.cfg, "other", seq) == ""


def test_handoff_waits_for_its_dependencies_then_wakes_the_assignee(make):
    h = team(make)
    q, a1, a2 = plan(h)
    assert a1["woken"] == [] and a1["blocked"] == ["e1"]  # not handed out while the question is open
    assert a2["woken"] == ["e2"]
    d = h.q("select state from deliveries d join messages m on m.id=d.message_id where m.id=? and recipient='e1'",
            a1["id"])
    assert d == [{"state": "blocked"}]
    h.wait_quiet()
    assert not h.q("select 1 from turns where agent_id='e1'")
    out = ok(h.tool("plan", "xmuse_send", to="#g", body="offsets, (start, end) in bytes", kind="decision",
                    supersedes=q))
    assert out["released"] == ["e1"]
    h.wait(lambda: h.q("select 1 from turns where agent_id='e1'"), what="e1 woken after its dependency resolved")
    assert ok(h.tool("e1", "xmuse_context"))["ready"]


def test_dependency_released_by_resolve_and_by_close(make):
    h = team(make)
    a0 = ok(h.tool("plan", "xmuse_send", to="#g", body="set up the skeleton", kind="handoff", why=WHY,
                   mentions=["e2"]))
    a1 = ok(h.tool("plan", "xmuse_send", to="#g", body="build on the skeleton", kind="handoff", why=WHY,
                   mentions=["e1"], depends_on=a0["entries"]))
    assert a1["blocked"] == ["e1"]
    out = ok(h.tool("e2", "xmuse_send", to="#g", body="skeleton done", resolves=a0["entries"]))
    assert out["released"] == ["e1"]
    h2_dep = ok(h.tool("plan", "xmuse_send", to="#h", body="wait for #h to close", kind="question"))["entries"]
    a2 = ok(h.tool("plan", "xmuse_send", to="#g", body="after #h", kind="handoff", why=WHY, mentions=["e2"],
                   depends_on=h2_dep))
    assert a2["blocked"] == ["e2"]
    assert h.admin("close", id="#h")["result"]["released"] == ["e2"]


def test_question_wakes_the_planner_and_the_answer_wakes_the_asker(make):
    h = team(make)
    plan(h)
    out = ok(h.tool("e2", "xmuse_send", to="#g", body="may I rename Token.kind to Token.type?", kind="question",
                    scope="module:lexer"))
    assert out["woken"] == ["plan"]  # no mention needed: P handed e2 its work
    qid = out["entries"][0]
    ans = ok(h.tool("plan", "xmuse_send", to="#g", body="no: keep Token.kind", kind="decision", supersedes=qid))
    assert ans["woken"] == ["e2"]
    with h.conn() as c:
        assert db.row(c.execute("select scope from entries where statement='no: keep Token.kind'"))["scope"] == \
            "module:lexer"
    # a question from someone with no assignment goes where it always did: the mentions
    assert ok(h.tool("other", "xmuse_send", to="#g", body="who owns docs?", kind="question"))["woken"] == []


def test_information_layer_off_offers_and_does_nothing_of_it(make):
    h = team(make, info_layer="off")
    tools = {t["name"]: t for t in json.loads((h.state / "tools.json").read_text())}
    assert "xmuse_context" not in tools
    send = tools["xmuse_send"]["inputSchema"]["properties"]
    assert send["kind"]["enum"] == ["message"] and not {"scope", "supersedes", "resolves", "depends_on", "why"} & set(send)
    assert "declares" not in tools["xmuse_done"]["inputSchema"]["properties"]
    for text in [(h.ws / "AGENTS.md").read_text(), (h.ws / ".claude/skills/xmuse-collab/SKILL.md").read_text()]:
        for gone in ("decision", "assumption", "Why-First", "xmuse_context", "depends_on", "review_request",
                     "declares", "info:"):
            assert gone not in text, gone
        assert "xmuse_done(summary, next)" in text
    # every path refuses: the agent's tools, the coordinator/CLI send
    e = h.tool("plan", "xmuse_send", to="#g", body="x", kind="decision")["error"]
    assert "must be one of: message" in e["message"]
    e = h.tool("plan", "xmuse_send", to="#g", body="x", kind="handoff", mentions=["e1"], why=WHY)["error"]
    assert "unknown arguments: why" in e["message"]
    assert h.tool("plan", "xmuse_context")["error"]["code"] == "unknown_tool"
    assert "unknown arguments: declares" in h.tool("plan", "xmuse_done", summary="s", next="none",
                                                    declares=[{"kind": "decision", "statement": "x"}])["error"]["message"]
    e = h.admin("send", to="#g", body="x", kind="question")
    assert "information layer is off" in e["error"]["message"]
    # plain messages still work and wake by mention only; nothing is recorded, nothing injected
    out = ok(h.tool("e2", "xmuse_send", to="#g", body="question: rename Token.kind?", mentions=["plan"]))
    assert out["woken"] == ["plan"] and "entries" not in out
    assert h.q("select count(*) n from entries")[0]["n"] == 0
    with h.conn() as c:
        p = wakepack.render(c, h.hub.cfg, db.row(c.execute("select * from agents where id='plan'")), [], None, "ws")
        assert p.mode == "none" and "[alignment" not in p.text
        assert "xmuse_context" not in wakepack.relayed(c, [], h.hub.cfg)
    from xmuse import doctor
    checks = {c.name: c for c in doctor.workspace(h.state)}
    assert checks["tools.json"].level == "ok" and "information layer off" in checks["tools.json"].detail
    assert checks["skill"].level == "ok" and checks["AGENTS.md"].level == "ok"


def test_information_layer_on_renders_without_markers(make):
    h = team(make)
    text = (h.ws / "AGENTS.md").read_text() + (h.ws / ".agents/skills/xmuse-collab/SKILL.md").read_text()
    assert "info:" not in text and "Why-First" in text and "module:<name>" in text
    assert "xmuse_context" in {t["name"] for t in json.loads((h.state / "tools.json").read_text())}
