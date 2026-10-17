"""Consistency auditor (audit.py) against the fake MemoryOS /audit: what it sends after a supersede, how flags reach
the host (notice) and the authors (wake pack), and that failures, foreign ids and invented quotes change nothing."""
import pytest

from fakes.fake_memoryos import FakeMemoryOS
from xmuse import align, audit, db, wakepack

CAPS = ("audit", "recall")
DEP = "Done: the parser returns integer cents, tests assert parse('3.5') == 350."


@pytest.fixture
def mo():
    made = []

    def _mo(**kw):
        made.append(FakeMemoryOS(**kw))
        return made[-1]
    yield _mo
    for f in made:
        f.close()


def hub(make, url, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")], memoryos_url=url,
             audit_poll_s=3600, **cfg)  # the tests run the auditor themselves
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")  # nobody runs a turn: only the auditor talks to MemoryOS
    return h


def say(h, agent, body, to="#g", **kw):
    r = h.tool(agent, "xmuse_send", to=to, body=body, **kw)
    assert "result" in r, r
    return r["result"]["id"]


def flag_quotes(fake, needle):
    """A fake judge: every item whose text contains `needle` is flagged with it as the quote."""
    def judge(req):
        flagged = [{"id": i["id"], "quote": needle} for i in req["items"] if needle in i["text"]]
        return {"schema": "memoryos_audit/v1", "flagged": flagged, "candidates": [i["id"] for i in req["items"]],
                "diagnostics": {"queries": 1, "expanded": 0, "dense": False, "judged": 0, "dropped_quotes": 0}}
    fake.audit = judge


def scenario(h):
    """E1 (thread #g) is relied on by claude-2's report, then replaced by E2. Returns the ids that matter."""
    say(h, "claude-1", "Amounts are integer cents everywhere.", kind="decision")
    dep = say(h, "claude-2", DEP)
    other = say(h, "claude-3", "CI is green; next is the report layout.")
    elsewhere = say(h, "claude-2", "Over here the parser also returns integer cents.", to="#h", mentions=[])
    say(h, "claude-1", "Amounts are decimal strings with two places.", kind="decision", supersedes="E1")
    return dep, other, elsewhere


def test_a_supersede_is_audited_once_and_flags_reach_host_and_author(make, mo):
    fake = mo(caps=CAPS)
    flag_quotes(fake, "integer cents")
    h = hub(make, fake.url)
    dep, other, elsewhere = scenario(h)
    h.hub.auditor.run_pending()  # the sends also kicked the poller: the lock makes it one audit either way
    assert h.hub.auditor.run_pending() == 0                       # audited once
    [(path, req)] = fake.calls
    assert path == "/audit" and req["old"]["id"] == "E1" and req["new"]["id"] == "E2"
    assert "integer cents" in req["old"]["text"] and "decimal strings" in req["new"]["text"]
    ids = [i["id"] for i in req["items"]]
    assert ids == [f"m{dep}", f"m{other}"]                        # the window, this thread, no decision messages
    assert req["items"][0]["speaker"] == "claude-2" and req["k"] == 20
    assert h.q("select entry_id, by_id, state from audits") == [{"entry_id": 1, "by_id": 2, "state": "done"}]
    flags = h.q("select entry_id, by_id, message_id, agent_id, quote from audit_flags")
    assert flags == [{"entry_id": 1, "by_id": 2, "message_id": dep, "agent_id": "claude-2", "quote": "integer cents"}]
    [note] = h.q("select body from messages where kind='notice' and body like 'audit:%'")
    assert note["body"].startswith("audit: E2 replaced E1. 1 earlier message(s) relied on the old version:")
    assert f'#{dep} claude-2: "integer cents"' in note["body"] and "may miss some" in note["body"]
    conn = h.conn()
    agent = lambda a: db.row(conn.execute("select * from agents where id=?", (a,)))  # noqa: E731
    pack = wakepack.render(conn, h.hub.cfg, agent("claude-2"), [], None, "/ws").text
    assert f"#{dep} relied on E1, replaced by E2" in pack and '"integer cents"' in pack
    assert "[audit]" not in wakepack.render(conn, h.hub.cfg, agent("claude-3"), [], None, "/ws").text
    since = conn.execute("select seq from entry_events where entry_id=1 and op='add'").fetchone()[0]
    d = align.delta(conn, "claude-2", since)                      # the audit version is not an alignment change
    assert [e["id"] for e, _ in d["superseded"]] == ["E1"] and [e["id"] for e in d["added"]] == ["E2"]
    assert not d["resolved"] and not d["archived"]


def test_the_wake_pack_shows_a_flag_once_per_session(make, mo):
    fake = mo(caps=CAPS)
    flag_quotes(fake, "integer cents")
    h = hub(make, fake.url)
    scenario(h)
    conn = h.conn()
    before = align.current_seq(conn)
    h.hub.auditor.run_pending()
    a = db.row(conn.execute("select * from agents where id='claude-2'"))
    x = lambda seen: type("X", (), {"conn": conn, "cfg": h.hub.cfg, "agent": a, "seen": seen,  # noqa: E731
                                    "seq": align.current_seq(conn)})
    assert "[audit]" in wakepack.audits(x(before))                # new since the last wake
    assert wakepack.audits(x(align.current_seq(conn))) == ""      # already shown


def test_supersedes_from_before_the_auditor_started_are_skipped(make, mo):
    fake = mo(caps=("recall",))                                   # no audit capability: no auditor thread
    h = hub(make, fake.url)
    scenario(h)
    assert not h.hub.auditor.thread.is_alive()
    h.hub.mo.caps.add("audit")                                    # as if the hub restarted with an /audit MemoryOS
    late = audit.Auditor(h.hub.mo, h.hub.db, h.hub.cfg)
    try:
        assert late.run_pending() == 0 and fake.paths() == []
        assert h.q("select entry_id, state from audits") == [{"entry_id": 1, "state": "skipped"}]
    finally:
        late.stop()


def test_disabled_without_the_capability(make, mo):
    fake = mo()                                                   # the default fake has no "audit"
    h = hub(make, fake.url)
    scenario(h)
    assert not h.hub.auditor.thread.is_alive()
    assert "/audit" not in fake.paths() and h.q("select * from audits") == []


@pytest.mark.parametrize("mode", ["500", "garbage"])
def test_a_failed_or_unusable_audit_changes_nothing(make, mo, mode):
    fake = mo(caps=CAPS)
    fake.fail["/audit"] = mode
    h = hub(make, fake.url)
    scenario(h)
    h.hub.auditor.run_pending()
    assert h.q("select state from audits") == [{"state": "failed" if mode == "500" else "done"}]
    assert h.q("select * from audit_flags") == []
    assert h.q("select * from messages where kind='notice' and body like 'audit:%'") == []


def test_foreign_ids_and_invented_quotes_are_dropped(make, mo):
    fake = mo(caps=CAPS)
    h = hub(make, fake.url)
    dep, other, _ = scenario(h)
    fake.audit = lambda req: {"flagged": [{"id": "m999", "quote": "integer cents"},
                                          {"id": f"m{dep}", "quote": "returns cents as int"},  # not in the text
                                          {"id": f"m{other}", "quote": ""}], "candidates": []}
    h.hub.auditor.run_pending()
    assert h.q("select state from audits") == [{"state": "done"}] and h.q("select * from audit_flags") == []


def test_an_answered_question_is_not_audited(make, mo):
    fake = mo(caps=CAPS)
    h = hub(make, fake.url)
    say(h, "claude-1", "Do amounts stay in integer cents?", kind="question")
    say(h, "claude-2", DEP)
    say(h, "claude-1", "Yes, integer cents.", kind="decision", supersedes="E1")
    h.hub.auditor.run_pending()
    assert fake.paths() == [] and h.q("select state, by_id from audits") == [{"state": "skipped", "by_id": 2}]


def test_memoryos_skip_turns_off_one_capability(make, mo):
    fake = mo(caps=("curate", "curate.collab", "audit", "recall"))
    h = hub(make, fake.url, memoryos_skip=["curate.collab"])  # the auditor alone, no curated proposals
    assert h.hub.mo.caps == {"curate", "audit", "recall"}
    assert h.hub.auditor.thread.is_alive() and not h.hub.curator.thread.is_alive()
