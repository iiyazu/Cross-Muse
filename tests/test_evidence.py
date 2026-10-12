"""Evidence on xmuse_done (contract XMUSE2-VIEW-API 8.5): checks against each vendor's turn log, the view fields and
the reviewer gate."""
import itertools
import json
from pathlib import Path

import pytest

from test_room import open_room, view
from xmuse import db, evidence, mail, tools

FIX = Path(__file__).parent / "fixtures"
FG = {"foreground": True}  # never woken by the hub: tests drive these members by hand
_n = itertools.count()


# ---- turn logs ------------------------------------------------------------------------------------------------

def mkdb(tmp_path):
    state = tmp_path / "state"
    (state / "runs").mkdir(parents=True)
    return db.init(state / "hub.db"), state


def mkturn(conn, state, adapter, lines, tid=1, started=100.0, session_id=None):
    conn.execute("insert into turns(id, agent_id, session_id, adapter, state, started_at) values(?,?,?,?,?,?)",
                 (tid, "a", session_id, adapter, "running", started))
    if lines is not None:
        (state / "runs" / f"turn-{tid}.jsonl").write_text(
            "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines), encoding="utf-8")
    return db.row(conn.execute("select * from turns where id=?", (tid,)))


def fixture_lines(name):
    return [json.loads(x) for x in (FIX / name).open(encoding="utf-8")]


def verdict(tmp_path, adapter, lines, *items):
    conn, state = mkdb(tmp_path / f"v{next(_n)}")
    return evidence.check(conn, mkturn(conn, state, adapter, lines), list(items))


def ev(kind, ref, result=""):
    return {"kind": kind, "ref": ref, "result": result}


def c_use(i, name, **inp):
    return {"type": "assistant", "message": {"id": f"m{i}", "content": [
        {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}}


def c_res(i, text, err=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": text, "is_error": err}]}}


CLAUDE = [c_use(1, "Bash", command="cd /ws && python -m pytest -q tests/test_a.py"), c_res(1, "5 passed in 0.2s"),
          c_use(2, "Bash", command="pytest tests/test_b.py"), c_res(2, "Exit code 1\n2 failed, 3 passed", True),
          c_use(3, "Write", file_path="/ws/src/a.py"), c_res(3, "File created"),
          c_use(4, "Edit", file_path="/ws/src/denied.py"), c_res(4, "permission denied", True),
          c_use(5, "Read", file_path="/ws/src/read_only.py"), c_res(5, "x = 1")]


def test_claude_commands_tests_and_diffs(tmp_path):
    ok = lambda *items: verdict(tmp_path, "claude_resume", CLAUDE, *items)  # noqa: E731
    assert ok(ev("test", "python -m pytest -q tests/test_a.py", "passed")) == ("verified", [])
    # whitespace is normalised; the command only has to be contained in what ran
    assert ok(ev("command", "python  -m   pytest -q   tests/test_a.py", "exit 0")) == ("verified", [])
    assert ok(ev("diff", "src/a.py")) == ("verified", [])
    assert ok(ev("diff", "/ws/src/a.py")) == ("verified", [])
    # a failing run is a problem when passing is claimed, and fine when the failure is what is reported
    st, problems = ok(ev("test", "pytest tests/test_b.py", "all passed"))
    assert st == "unverified" and "exited 1" in problems[0]
    assert ok(ev("test", "pytest tests/test_b.py", "2 failed")) == ("verified", [])
    assert ok(ev("test", "pytest tests/test_b.py", "exit 1")) == ("verified", [])
    st, problems = ok(ev("test", "pytest -q tests/test_a.py", "exit 3"))
    assert st == "unverified" and "exited 0" in problems[0]
    # never ran / never written / written only by a call that failed / only read
    assert ok(ev("test", "pytest tests/test_c.py", "passed"))[0] == "unverified"
    assert "not run in this turn" in ok(ev("command", "make deploy"))[1][0]
    for path in ("src/b.py", "src/denied.py", "src/read_only.py"):
        assert "not written in this turn" in ok(ev("diff", path))[1][0]
    # all items must check out; the problems name each one that does not
    st, problems = ok(ev("diff", "src/a.py"), ev("diff", "src/b.py"), ev("test", "pytest nothing", "passed"))
    assert st == "unverified" and len(problems) == 2


def test_claude_real_recording(tmp_path):
    lines = fixture_lines("claude-code.jsonl")
    assert verdict(tmp_path, "claude_resume", lines, ev("diff", "calc.py")) == ("verified", [])
    assert verdict(tmp_path, "claude_resume", lines, ev("diff", "other.py"))[0] == "unverified"


def oc_tool(i, name, inp, text="", meta=None, error=False):
    def event(typ, **d):
        return {"type": typ, "data": {"sessionID": "s", "id": f"c{i}", **d}}
    end = event("session.tool.error", error={"message": text}) if error else event(
        "session.tool.success", content=[{"type": "text", "text": text}], metadata=meta or {})
    return [event("session.tool.input.started", name=name), event("session.tool.called", input=inp), end]


def test_opencode_events(tmp_path):
    lines = [*oc_tool(1, "shell", {"command": "pytest -q"}, "4 passed", {"exit": 0}),
             *oc_tool(2, "shell", {"command": "pytest -q tests/bad"}, "1 failed", {"exitCode": 1}),
             *oc_tool(3, "bash", {"command": "make lint"}, "lint ok"),
             *oc_tool(4, "bash", {"command": "make build"}, "3 errors found"),
             *oc_tool(5, "shell", {"command": "make dist"}, "boom", error=True),
             *oc_tool(6, "write", {"path": "/ws/new.py", "content": "x"}, "wrote"),
             *oc_tool(7, "apply_patch", {"patchText": "*** Begin Patch\n*** Update File: lib/p.py\n@@\n"}, "ok"),
             *oc_tool(8, "edit", {"path": "/ws/fail.py"}, "no match", error=True),
             {"type": "session.step.ended", "data": {"sessionID": "s", "files": ["via_step.py"]}},
             {"type": "server.connected", "data": {}}]
    ok = lambda *items: verdict(tmp_path, "opencode", lines, *items)  # noqa: E731
    assert ok(ev("test", "pytest -q", "passed")) == ("verified", [])
    assert ok(ev("test", "pytest -q tests/bad", "passed"))[0] == "unverified"
    assert ok(ev("test", "pytest -q tests/bad", "1 failed")) == ("verified", [])
    assert ok(ev("command", "make lint", "ok")) == ("verified", [])  # no exit code stated, no failure in the output
    assert "output shows failures" in ok(ev("command", "make build", "passed"))[1][0]
    assert "tool reported an error" in ok(ev("command", "make dist", "ok"))[1][0]
    for path in ("new.py", "lib/p.py", "via_step.py"):
        assert ok(ev("diff", path)) == ("verified", []), path
    assert ok(ev("diff", "fail.py"))[0] == "unverified"
    real = fixture_lines("oc-code.events.jsonl")
    assert verdict(tmp_path / "r", "opencode", real, ev("diff", "calc.py")) == ("verified", [])
    assert verdict(tmp_path / "r2", "opencode", real, ev("diff", "other.py"))[0] == "unverified"


def d_tool(i, tool, inp, result="", status="completed"):
    return [{"type": "tool_call", "callId": f"c{i}", "tool": tool, "input": inp},
            {"type": "tool_result", "callId": f"c{i}", "status": status, "result": result}]


def test_dsh_ndjson(tmp_path):
    lines = [{"type": "session", "sessionId": "x"},
             *d_tool(1, "pwsh", {"command": "python -m pytest -q"}, "6 passed in 1s"),
             *d_tool(2, "pwsh", {"command": "python -m pytest -q tests/x"}, "FAILED tests/x.py::t\n1 failed, 2 passed"),
             *d_tool(3, "pwsh", {"command": "node build.js"}, "build finished\nexit code 2"),
             *d_tool(4, "pwsh", {"command": "dir nope"}, "Error: sandbox refused", status="error"),
             *d_tool(5, "edit", {"file_path": "calc.py", "old_string": "a", "new_string": "b"}, "updated"),
             *d_tool(6, "write", {"file_path": "C:\\ws\\out\\r.txt", "content": "r"}, "written"),
             *d_tool(7, "edit", {"file_path": "locked.py"}, "Error: access denied", status="error")]
    ok = lambda *items: verdict(tmp_path, "dsh", lines, *items)  # noqa: E731
    assert ok(ev("test", "python -m pytest -q", "passed")) == ("verified", [])
    assert ok(ev("test", "python -m pytest -q tests/x", "passed"))[0] == "unverified"  # failures in the output
    assert ok(ev("test", "python -m pytest -q tests/x", "1 failed")) == ("verified", [])
    assert "exited 2" in ok(ev("command", "node build.js", "ok"))[1][0]
    assert "tool reported an error" in ok(ev("command", "dir nope", "ok"))[1][0]
    assert ok(ev("diff", "calc.py")) == ("verified", [])
    assert ok(ev("diff", "out/r.txt")) == ("verified", [])  # Windows backslashes
    assert ok(ev("diff", "locked.py"))[0] == "unverified"
    assert verdict(tmp_path / "r", "dsh", fixture_lines("dsh-code.jsonl"), ev("diff", "calc.py")) == ("verified", [])


def test_wsl_and_windows_spell_one_file(tmp_path):
    lines = [c_use(1, "Write", file_path="C:\\Users\\me\\ws\\a.py"), c_res(1, "ok")]
    assert verdict(tmp_path, "claude_resume", lines, ev("diff", "/mnt/c/Users/me/ws/a.py")) == ("verified", [])


def test_claim_reading():
    c = evidence._claim
    assert c("passed") == c("3 passed, 0 failed") == c("all green") == "pass"
    assert c("exit 0") == 0 and c("exited with code 2") == 2 and c("exit status: 1") == 1
    assert c("2 failed, 5 passed") == c("failed") == c("errors") == "fail"
    assert c("all passed after I fixed the failing case") == "pass"
    assert c("") is None and c("printed the version") is None


def test_transcript_unavailable(tmp_path):
    conn, state = mkdb(tmp_path)
    items = [ev("test", "pytest", "passed")]
    unavailable = ("unverified", ["transcript unavailable"])
    assert evidence.check(conn, mkturn(conn, state, "claude_resume", None), items) == unavailable  # no log written
    assert evidence.check(conn, mkturn(conn, state, "dsh", [], tid=2), items) == unavailable  # empty log
    assert evidence.check(conn, mkturn(conn, state, "dsh", ["not json", "[1]"], tid=3), items) == unavailable
    assert evidence.check(conn, mkturn(conn, state, "carrier-pigeon", [{"type": "x"}], tid=4), items) == unavailable
    assert evidence.check(conn, None, items) == unavailable  # no turn: a polled desktop or foreground member
    # a log that is there but does not show the command is a different thing: the claim is false
    st, problems = evidence.check(conn, mkturn(conn, state, "claude_resume", [{"type": "system"}], tid=5), items)
    assert st == "unverified" and "not run in this turn" in problems[0]


def test_claude_tui_turn_reads_the_session_transcript_from_its_start(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    proj = home / ".claude" / "projects" / "-ws"
    proj.mkdir(parents=True)
    old, new = "2026-10-12T10:00:00.000Z", "2026-10-12T10:05:00.000Z"
    lines = [{**c_use(1, "Bash", command="pytest old"), "timestamp": old}, {**c_res(1, "1 passed"), "timestamp": old},
             {**c_use(2, "Bash", command="pytest new"), "timestamp": new}, {**c_res(2, "2 passed"), "timestamp": new}]
    (proj / "SESS.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    conn, state = mkdb(tmp_path)
    sid = conn.execute("insert into sessions(agent_id, vendor_session, origin, created_at) values('a','SESS','tui',1)"
                       ).lastrowid
    started = evidence.datetime.fromisoformat("2026-10-12T10:03:00+00:00").timestamp()
    turn = mkturn(conn, state, "claude_channel", None, started=started, session_id=sid)
    assert evidence.check(conn, turn, [ev("test", "pytest new", "passed")]) == ("verified", [])
    assert evidence.check(conn, turn, [ev("test", "pytest old", "passed")])[0] == "unverified"  # an earlier turn's
    conn.execute("update sessions set vendor_session='GONE'")
    assert evidence.check(conn, turn, [ev("test", "pytest new")]) == ("unverified", ["transcript unavailable"])


# ---- schema, storage, view ------------------------------------------------------------------------------------

def test_done_schema_takes_evidence():
    props = tools.BY_NAME["xmuse_done"]["inputSchema"]["properties"]
    assert props["evidence"]["items"]["properties"]["kind"]["enum"] == ["test", "diff", "command"]
    good = {"summary": "s", "next": "none", "evidence": [{"kind": "test", "ref": "pytest", "result": "passed"}]}
    assert tools.validate("xmuse_done", good) == good
    for bad, msg in (({"kind": "lint", "ref": "x"}, "must be one of: test, diff, command"),
                     ({"kind": "test"}, "missing: ref"), ({"kind": "test", "ref": "x", "why": "y"}, "unknown fields: why")):
        with pytest.raises(tools.ToolError, match=msg):
            tools.validate("xmuse_done", {"summary": "s", "next": "none", "evidence": [bad]})
    plain = {t["name"]: t for t in tools.tools_for({"info_layer": "off"})}
    assert "evidence" in plain["xmuse_done"]["inputSchema"]["properties"]


def test_old_database_gets_the_evidence_table(tmp_path):
    conn, state = mkdb(tmp_path)
    conn.execute("drop table evidence")
    conn.close()
    conn = db.init(state / "hub.db")
    assert evidence.status(conn, 1) == ("none", [])


def running_turn(h, agent, adapter="claude_resume", lines=None):
    """A turn the hub believes is running, with the run log an adapter would have written for it."""
    with db.tx(h.conn()) as c:
        tid = c.execute("insert into turns(agent_id, adapter, state, started_at) values(?,?,?,?)",
                        (agent, adapter, "running", db.now())).lastrowid
    (h.state / "runs").mkdir(exist_ok=True)
    if lines is not None:
        (h.state / "runs" / f"turn-{tid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines),
                                                            encoding="utf-8")
    return tid


def done(h, agent, **kw):
    out = h.tool(agent, "xmuse_done", **{"summary": "finished", "next": "none", **kw})
    assert "result" in out, out
    return out["result"]


def test_done_records_the_check_and_the_view_shows_it(make):
    h = make([("dev", "dsh", FG)])
    running_turn(h, "dev", lines=CLAUDE)
    out = done(h, "dev", evidence=[{"kind": "test", "ref": "pytest -q tests/test_a.py", "result": "passed"},
                                   {"kind": "diff", "ref": "src/a.py"}])
    assert out["evidence_status"] == "verified" and out["evidence_problems"] == []
    mid = h.q("select id from messages where kind='done'")[0]["id"]
    conn = h.conn()
    assert evidence.status(conn, mid) == ("verified", [])
    assert [e["ref"] for e in evidence.items(conn, mid)] == ["pytest -q tests/test_a.py", "src/a.py"]
    # the second turn lies
    with db.tx(conn):
        conn.execute("update turns set state='succeeded'")
    running_turn(h, "dev", lines=CLAUDE)
    done(h, "dev", summary="again", evidence=[{"kind": "test", "ref": "pytest tests/test_b.py", "result": "passed"},
                                              {"kind": "diff", "ref": "src/zzz.py"}])
    done(h, "dev", summary="nothing to show")
    bad, none = [r["id"] for r in h.q("select id from messages where kind='done' order by id")][1:]
    st, problems = evidence.status(conn, bad)
    assert st == "unverified" and len(problems) == 2 and evidence.status(conn, none) == ("none", [])
    st, v = view(h, open_room(h)["operator_token"])
    assert st == 200, v
    got ={t["id"]: t for t in v["timeline"] if t["kind"] == "done"}
    assert got[mid]["evidence_status"] == "verified" and got[mid]["evidence_problems"] == []
    assert got[bad]["evidence_status"] == "unverified" and got[bad]["evidence_problems"] == problems
    assert got[none]["evidence_status"] == "none" and got[none]["evidence_problems"] == []
    assert all("evidence_status" not in t for t in v["timeline"] if t["kind"] != "done")


def test_done_without_a_readable_log_is_unverified_not_refused(make):
    h = make([("dev", "dsh", FG)])
    out = done(h, "dev", evidence=[{"kind": "command", "ref": "make", "result": "ok"}])  # no turn at all
    assert (out["evidence_status"], out["evidence_problems"]) == ("unverified", ["transcript unavailable"])
    running_turn(h, "dev", adapter="dsh")  # a turn whose log was never written
    out = done(h, "dev", summary="two", evidence=[{"kind": "command", "ref": "make", "result": "ok"}])
    assert out["evidence_problems"] == ["transcript unavailable"]
    mid = h.q("select max(id) m from messages where kind='done'")[0]["m"]
    assert evidence.status(h.conn(), mid) == ("unverified", ["transcript unavailable"])


def test_claude_turn_log_is_readable_while_the_turn_runs(make):
    """claude_resume flushes each stream line, so the done call inside the turn sees the earlier tool calls."""
    h = make()
    h.plan_claude({"as": "claude-1", "fixture": "claude-evidence.jsonl", "pause": 0.5, "calls": [
        ["xmuse_done", {"summary": "built", "next": "none", "evidence": [
            {"kind": "test", "ref": "python -m pytest -q tests/test_x.py", "result": "3 passed"},
            {"kind": "diff", "ref": "src/feature.py"}]}]]})
    h.send("claude-1", "build the feature")
    h.wait_quiet()
    mid = h.q("select id from messages where kind='done'")[0]["id"]
    assert evidence.status(h.conn(), mid) == ("verified", [])
    assert h.q("select state from turns")[0]["state"] == "succeeded"


# ---- reviewer gate --------------------------------------------------------------------------------------------

def roster(h, **roles):
    with db.tx(h.conn()) as c:
        for aid, role in roles.items():
            c.execute("update agents set role=? where id=?", (role, aid))


def handoffs(h):
    return h.q("select m.*, d.recipient, d.wake from messages m join deliveries d on d.message_id=m.id"
               " where m.sender='hub' and m.kind='handoff'")


def test_done_next_none_goes_to_the_reviewer(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)])
    roster(h, rev="reviewer")
    running_turn(h, "dev", lines=CLAUDE)
    out = done(h, "dev", summary="added a.py", evidence=[{"kind": "diff", "ref": "src/a.py", "result": "created"},
                                                       {"kind": "test", "ref": "pytest nothing", "result": "passed"}])
    assert out["review"] == "rev"
    [m] = handoffs(h)
    assert (m["recipient"], m["wake"], m["thread_id"]) == ("rev", 1, "dm:hub+rev")
    assert m["body"].startswith("REVIEW REQUEST")
    done_id = h.q("select id from messages where kind='done'")[0]["id"]
    for needle in (f"#{done_id}", "dev", "added a.py", "diff src/a.py -> created", "hub check: unverified",
                   "not run in this turn: 'pytest nothing'", "xmuse_done"):
        assert needle in m["body"], needle
    assert json.loads(m["why"])["what"].startswith("Review dev's")
    [e] = h.q("select * from entries where kind='assignment'")
    assert (e["assignee"], e["author"]) == ("rev", "hub")
    assert h.tool("rev", "xmuse_inbox")["result"][0]["body"].startswith("REVIEW REQUEST")


def test_the_reviewers_own_done_ends_the_chain(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)])
    roster(h, rev="reviewer")
    assert done(h, "dev")["review"] == "rev"
    assert "review" not in done(h, "rev", summary="looks good")
    assert len(handoffs(h)) == 1  # nobody reviews the reviewer
    assert "review" not in done(h, "dev", summary="handing over", next="rev")  # only a finished task is reviewed
    assert len(handoffs(h)) == 1


def test_no_reviewer_no_review(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)])
    assert "review" not in done(h, "dev")
    roster(h, dev="reviewer")  # the only reviewer is the one who finished
    assert "review" not in done(h, "dev")
    roster(h, dev="", rev="Reviewer ")
    with db.tx(h.conn()) as c:
        c.execute("update agents set removed=1 where id='rev'")  # a removed member reviews nothing
    assert "review" not in done(h, "dev")
    assert handoffs(h) == []


def test_review_gate_off_changes_nothing(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)], review_gate=False)
    roster(h, rev="reviewer")
    before = h.q("select count(*) n from messages")[0]["n"]
    out = done(h, "dev")
    assert out == {"recorded": True, "thread": "dm:dev+human"}
    assert h.q("select count(*) n from messages")[0]["n"] == before + 1 and handoffs(h) == []
    assert h.q("select count(*) n from entries")[0]["n"] == 0


def test_the_smallest_id_reviews(make):
    h = make([("dev", "dsh", FG), ("rev-b", "dsh", FG), ("rev-a", "dsh", FG)])
    roster(h, **{"rev-b": "reviewer", "rev-a": "reviewer"})
    assert done(h, "dev")["review"] == "rev-a"


def test_info_layer_off_skips_the_gate(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)], info_layer="off")
    roster(h, rev="reviewer")
    assert "review" not in done(h, "dev")  # plain messages only: a handoff is not allowed there


def test_work_without_a_turn_is_reviewed_and_one_done_gets_one_handoff(make):
    h = make([("dev", "dsh", FG), ("rev", "dsh", FG)])
    roster(h, rev="reviewer")
    conn, cfg = h.conn(), h.hub.cfg
    out = mail.done(conn, "dev", "same", "none", cfg=cfg)
    assert out["review"] == "rev"
    mid = h.q("select id from messages where kind='done'")[0]["id"]
    again = mail.send(conn, cfg, "hub", "rev", "x", "handoff", why={k: "y" for k in tools.WHY_FIELDS},
                      idem=f"review:{mid}")
    assert again["duplicate"] is True and len(handoffs(h)) == 1


def test_reviewer_is_woken_by_the_hub_when_it_runs_in_the_background(make):
    h = make([("dev", "dsh", FG), ("rev", "claude")])
    roster(h, rev="reviewer")
    h.plan_claude({"as": "rev", "calls": [["xmuse_done", {"summary": "approved", "next": "none"}]]})
    done(h, "dev")
    h.wait_quiet()
    [t] = h.turns()
    assert t["agent_id"] == "rev" and t["state"] == "succeeded"
    assert "REVIEW REQUEST" in h.claude_calls()[0]["prompt"]
    assert len(handoffs(h)) == 1  # the reviewer's done did not start another review
