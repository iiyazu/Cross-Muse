"""Alignment library: declaration, supersede/resolve, per-agent views, caps, ready work, thread close."""
import json

from xmuse import align, cli, db


def three(make, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")], **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"  # turns fail fast; the alignment library is the point
    return h


def decl(h, agent, body, kind="decision", to="#g", **kw):
    r = h.tool(agent, "xmuse_send", to=to, body=body, kind=kind, **kw)
    assert "result" in r, r
    return r["result"]


def entry(h, ref):
    return h.q("select * from entries where id=?", int(ref[1:]))[0]


def view(h, agent, **args):
    return h.tool(agent, "xmuse_context", **args)["result"]


def ids(layer):
    return [e["id"] for e in layer]


def test_send_declares_active_entries(make):
    h = three(make)
    r = decl(h, "claude-1", "ids are strings", scope="global")
    assert r["entries"] == ["E1"]
    e = entry(h, "E1")
    assert (e["kind"], e["scope"], e["status"], e["author"], e["thread_id"]) == ("decision", "global", "active", "claude-1", "#g")
    assert json.loads(e["refs"]) == [r["id"]] and e["invalid_at"] is None
    assert decl(h, "claude-1", "int or float?", "question")["entries"] == ["E2"]
    assert entry(h, "E2")["scope"] == "thread:#g"
    assert decl(h, "claude-1", "assume UTF-8", "assumption", to="claude-2")["entries"] == ["E3"]
    assert entry(h, "E3")["scope"] == "thread:dm:claude-1+claude-2"
    assert "entries" not in decl(h, "claude-1", "just chatting", "message")
    assert h.q("select seq, entry_id, op from entry_events order by seq") == [
        {"seq": i, "entry_id": i, "op": "add"} for i in (1, 2, 3)]


def test_long_statement_keeps_first_sentence_and_reference(make):
    h = three(make)
    body = "Use Decimal strings everywhere. " + "More reasoning. " * 40
    decl(h, "claude-1", body)
    assert entry(h, "E1")["statement"] == "Use Decimal strings everywhere. …"
    decl(h, "claude-1", "x" * 400)
    assert entry(h, "E2")["statement"] == "x" * 299 + "…"
    assert h.q("select body from messages where id=2")[0]["body"] == "x" * 400  # full text stays in the message


def test_supersede_invalidates_the_old_entry_and_never_deletes(make):
    h = three(make)
    decl(h, "claude-1", "ids are int")
    r = decl(h, "claude-2", "ids are Decimal strings", supersedes="E1")
    old, new = entry(h, "E1"), entry(h, "E2")
    assert (old["status"], new["status"], new["supersedes"]) == ("superseded", "active", 1)
    assert old["invalid_at"] is not None and new["invalid_at"] is None
    assert h.q("select entry_id, op from entry_events order by seq") == [
        {"entry_id": 1, "op": "add"}, {"entry_id": 2, "op": "add"}, {"entry_id": 1, "op": "supersede"}]
    assert (old["seq"], new["seq"]) == (3, 2)  # every change bumps the entry's seq
    assert ids(view(h, "claude-3")["layers"]["thread:#g"]) == ["E2"]
    e = h.tool("claude-1", "xmuse_send", to="#g", body="again", kind="decision", supersedes="E1")["error"]
    assert e["code"] == "invalid_arguments" and "E1" in e["message"]  # no longer active
    assert h.q("select count(*) n from messages")[0]["n"] == 2 and r["entries"] == ["E2"]  # rolled back


def test_resolve_questions_and_assignments_only(make):
    h = three(make)
    decl(h, "claude-1", "which float?", "question", mentions=["claude-2"])
    decl(h, "claude-1", "use float64")
    decl(h, "claude-2", "float64 it is", resolves=["E1"])
    assert entry(h, "E1")["status"] == "resolved" and entry(h, "E1")["invalid_at"] is not None
    assert h.q("select op from entry_events where entry_id=1 order by seq")[-1]["op"] == "resolve"
    e = h.tool("claude-2", "xmuse_send", to="#g", body="ok", resolves=["E2"])["error"]
    assert "E2" in e["message"] and "question/assignment" in e["message"]
    e = h.tool("claude-2", "xmuse_send", to="#g", body="ok", resolves=["x1"])["error"]
    assert e["code"] == "invalid_arguments"
    assert entry(h, "E2")["status"] == "active"


def test_send_argument_combinations_are_checked(make):
    h = three(make)
    e = h.tool("claude-1", "xmuse_send", to="#g", body="x", scope="global")["error"]
    assert "need kind=decision" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="#g", body="x", kind="decision", scope="team")["error"]
    assert "scope must be global, thread or role:<role>" in e["message"]
    e = h.tool("claude-1", "xmuse_send", to="#g", body="x", depends_on=["E1"])["error"]
    assert "depends_on needs kind=handoff" in e["message"]
    assert h.q("select count(*) n from entries")[0]["n"] == 0


WHY = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}


def test_handoff_creates_one_assignment_per_named_peer(make):
    h = three(make)
    r = h.tool("claude-1", "xmuse_send", to="#g", body="build the parser", kind="handoff", why=WHY,
               mentions=["claude-2", "claude-3"])["result"]
    assert r["entries"] == ["E1", "E2"]
    rows = h.q("select kind, scope, assignee, status, depends_on from entries order by id")
    assert rows == [{"kind": "assignment", "scope": "thread:#g", "assignee": a, "status": "active", "depends_on": None}
                    for a in ("claude-2", "claude-3")]
    r = h.tool("claude-1", "xmuse_send", to="claude-2", body="then execute", kind="handoff", why=WHY,
               depends_on=["E1"])["result"]
    assert r["entries"] == ["E3"] and entry(h, "E3")["assignee"] == "claude-2"  # a DM names its peer
    assert json.loads(entry(h, "E3")["depends_on"]) == [1]
    e = h.tool("claude-1", "xmuse_send", to="claude-2", body="x", kind="handoff", why=WHY, depends_on=["E9"])["error"]
    assert "E9" in e["message"]


def test_done_declares_reference_the_done_message(make):
    h = three(make)
    r = h.tool("claude-1", "xmuse_done", summary="parser ready", next="none", declares=[
        {"kind": "decision", "statement": "tokens are tuples", "scope": "global"},
        {"kind": "assumption", "statement": "input is UTF-8"}])["result"]
    assert r["entries"] == ["E1", "E2"]
    mid = h.q("select id from messages where kind='done'")[0]["id"]
    assert [(e["scope"], json.loads(e["refs"]), e["thread_id"]) for e in h.q("select * from entries")] == [
        ("global", [mid], "dm:claude-1+human"), ("thread:dm:claude-1+human", [mid], "dm:claude-1+human")]
    r = h.tool("claude-1", "xmuse_done", summary="s", next="none",
               declares=[{"kind": "decision", "statement": "tokens are dicts", "supersedes": "E1"}])["result"]
    assert entry(h, "E1")["status"] == "superseded" and r["entries"] == ["E3"]
    e = h.tool("claude-1", "xmuse_done", summary="s", next="none", declares=[{"kind": "decision"}])["error"]
    assert "declares[0] is missing: statement" in e["message"]
    e = h.tool("claude-1", "xmuse_done", summary="s", next="none", declares=[{"kind": "lesson", "statement": "x"}])["error"]
    assert "declares[0].kind must be one of: decision, assumption, question" in e["message"]


def test_view_layers_role_thread_membership_and_assignee(make):
    h = three(make)
    with db.tx(h.conn()) as c:
        c.execute("update agents set role='dev' where id='claude-2'")
        c.execute("update agents set role='qa' where id='claude-3'")
    decl(h, "claude-1", "project-wide rule", scope="global")
    decl(h, "claude-1", "dev rule", scope="role:dev")
    decl(h, "claude-1", "group topic")
    decl(h, "claude-1", "private to 1 and 2", to="claude-2")
    h.tool("claude-1", "xmuse_send", to="#g", body="qa does X", kind="handoff", why=WHY, mentions=["claude-3"])
    v2, v3 = view(h, "claude-2")["layers"], view(h, "claude-3")
    assert set(v2) == {"global", "role:dev", "agent:claude-2", "thread:#g", "thread:dm:claude-1+claude-2"}
    assert ids(v2["global"]) == ["E1"] and ids(v2["role:dev"]) == ["E2"]
    assert ids(v2["thread:#g"]) == ["E3", "E5"] and ids(v2["thread:dm:claude-1+claude-2"]) == ["E4"]
    assert set(v3["layers"]) == {"global", "role:qa", "agent:claude-3", "thread:#g"}  # not in the dm, not dev's rule
    assert ids(v3["layers"]["thread:#g"]) == ["E3"] and v3["layers"]["role:qa"] == []
    assert ids(v3["assigned"]) == ["E5"] and v3["assigned"][0]["assignee"] == "claude-3" and v3["ready"] == ["E5"]
    assert view(h, "claude-2")["assigned"] == []
    assert v3["layers"]["global"][0] == {"id": "E1", "kind": "decision", "statement": "project-wide rule",
                                         "author": "claude-1", "refs": [1]}
    assert view(h, "claude-3")["truncated"] == []


def test_topic_narrows_to_one_thread_plus_global(make):
    h = three(make)
    decl(h, "claude-1", "everyone", scope="global")
    decl(h, "claude-1", "in group")
    decl(h, "claude-1", "in dm", to="claude-2")
    v = view(h, "claude-2", topic="#g")
    assert set(v["layers"]) == {"global", "thread:#g"} and ids(v["layers"]["thread:#g"]) == ["E2"]
    e = h.tool("claude-3", "xmuse_context", topic="dm:claude-1+claude-2")["error"]
    assert e["code"] == "unknown_thread" and "#g" in e["message"]


def test_layers_are_capped_by_newest_seq_and_flagged(make):
    h = three(make, align_thread_cap=2, align_global_cap=1)
    for i in range(4):
        decl(h, "claude-1", f"d{i}")
        decl(h, "claude-1", f"g{i}", scope="global")
    v = view(h, "claude-2")
    assert ids(v["layers"]["thread:#g"]) == ["E5", "E7"] and ids(v["layers"]["global"]) == ["E8"]
    assert v["truncated"] == ["global", "thread:#g"]
    decl(h, "claude-1", "d4", supersedes="E1")
    assert ids(view(h, "claude-2")["layers"]["thread:#g"]) == ["E7", "E9"]


def test_ready_work_waits_for_dependencies(make):
    h = three(make)
    h.tool("claude-1", "xmuse_send", to="#g", body="write parser", kind="handoff", why=WHY, mentions=["claude-2"])
    h.tool("claude-1", "xmuse_send", to="#g", body="write executor", kind="handoff", why=WHY, mentions=["claude-3"])
    h.tool("claude-1", "xmuse_send", to="#g", body="integrate", kind="handoff", why=WHY, mentions=["claude-3"],
           depends_on=["E1", "E2"])
    assert view(h, "claude-3")["ready"] == ["E2"] and ids(view(h, "claude-3")["assigned"]) == ["E2", "E3"]
    decl(h, "claude-2", "parser done", resolves=["E1"])
    assert view(h, "claude-3")["ready"] == ["E2"]
    decl(h, "claude-3", "executor done", resolves=["E2"])
    v = view(h, "claude-3")
    assert v["ready"] == ["E3"] and ids(v["assigned"]) == ["E3"]
    with db.tx(h.conn()) as c:
        align._move(c, 3, "archive", "archived")
    assert view(h, "claude-3")["assigned"] == []


def test_thread_close_archives_only_that_threads_entries(make):
    h = three(make)
    decl(h, "claude-1", "task rule")
    decl(h, "claude-1", "project rule", scope="global")
    decl(h, "claude-1", "other task", to="#other")
    h.tool("claude-1", "xmuse_send", to="#g", body="do it", kind="handoff", why=WHY, mentions=["claude-2"])
    assert align.close_thread(h.conn(), "#g") == {"archived": 2}
    assert [(e["id"], e["status"]) for e in h.q("select id, status from entries order by id")] == [
        (1, "archived"), (2, "active"), (3, "active"), (4, "archived")]
    assert h.q("select count(*) n from entry_events where op='archive'")[0]["n"] == 2
    assert entry(h, "E1")["invalid_at"] is not None
    v = view(h, "claude-2")
    assert ids(v["layers"]["global"]) == ["E2"] and ids(v["layers"]["thread:#other"]) == ["E3"] and v["assigned"] == []


def test_proposed_entries_stay_out_of_views_until_confirmed(make, capsys):
    h = three(make)
    with db.tx(h.conn()) as c:
        a = align.add(c, "decision", "global", "#g", "curated", 1, "curate", status="proposed")
        b = align.add(c, "decision", "global", "#g", "wrong", 1, "curate", status="proposed")
    assert view(h, "claude-1")["layers"]["global"] == []
    assert h.admin("align", op="confirm", id=f"E{a}")["result"] == {"ok": True}
    assert h.admin("align", op="reject", id=f"E{b}")["result"] == {"ok": True}
    assert (entry(h, "E1")["status"], entry(h, "E2")["status"]) == ("active", "rejected")
    assert ids(view(h, "claude-1")["layers"]["global"]) == ["E1"]
    assert h.admin("align", op="confirm", id="E1")["error"]["code"] == "invalid_arguments"  # not proposed any more
    cli.main(["--ws", str(h.ws), "align", "list"])
    assert capsys.readouterr().out.strip() == "E1 [decision] active global curate: curated"
    cli.main(["--ws", str(h.ws), "align", "list", "--all"])
    assert "E2 [decision] rejected" in capsys.readouterr().out


def test_cli_thread_close(make, capsys):
    h = three(make)
    decl(h, "claude-1", "task rule")
    cli.main(["--ws", str(h.ws), "thread", "close", "#g"])
    assert json.loads(capsys.readouterr().out) == {"archived": 1}
    cli.main(["--ws", str(h.ws), "thread", "#g", "--owner", "claude-2"])  # the old form still works
    assert h.q("select owner from threads")[0]["owner"] == "claude-2"
