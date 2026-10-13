"""Room-bound sessions: each (member, thread) pair resumes its own vendor session.

Opening a thread pulls that thread's session; a thread's session compacts and retires
independently; `new_session` retires one thread's session so its next wake starts fresh.
"""
from xmuse import db

OC = [("opencode-1", "opencode")]


def sessions(h):
    return h.q("select id, thread_id, vendor_session, state from sessions order by id")


def test_threads_get_separate_sessions_and_resume(make):
    h = make(OC)
    h.oc.plan = [{}, {}, {}]
    h.send("#a", "first in a", mentions=["opencode-1"])
    h.wait_quiet()
    h.send("#b", "first in b", mentions=["opencode-1"])
    h.wait_quiet()
    h.send("#a", "again in a", mentions=["opencode-1"])
    h.wait_quiet()
    rows = sessions(h)
    assert [(r["thread_id"], r["state"]) for r in rows] == [("#a", "current"), ("#b", "current")]
    assert rows[0]["vendor_session"] != rows[1]["vendor_session"]
    assert [p["session"] for p in h.oc.prompts] == [
        rows[0]["vendor_session"], rows[1]["vendor_session"], rows[0]["vendor_session"]]
    assert [t["session_id"] for t in h.turns()] == [rows[0]["id"], rows[1]["id"], rows[0]["id"]]


def test_legacy_hub_session_is_claimed_by_first_thread(make):
    h = make(OC)
    h.oc.plan = [{}, {}]
    h.send("#a", "hi a", mentions=["opencode-1"])
    h.wait_quiet()
    with db.tx(h.conn()) as c:  # simulate a pre-binding row
        c.execute("update sessions set thread_id=null")
    h.send("#b", "hi b", mentions=["opencode-1"])
    h.wait_quiet()
    rows = sessions(h)
    assert len(rows) == 1 and rows[0]["thread_id"] == "#b" and rows[0]["state"] == "current"
    assert [p["session"] for p in h.oc.prompts] == [rows[0]["vendor_session"]] * 2
    assert len(h.oc.sessions) == 1  # resumed, not recreated


def test_new_session_retires_only_that_thread(make):
    h = make(OC)
    h.oc.plan = [{}, {}, {}]
    h.send("#a", "hi a", mentions=["opencode-1"])
    h.wait_quiet()
    h.send("#b", "hi b", mentions=["opencode-1"])
    h.wait_quiet()
    out = h.admin("new_session", agent="opencode-1", thread="#a")
    assert out["result"] == {"ok": True, "retired": 1}
    h.send("#a", "fresh a", mentions=["opencode-1"])
    h.wait_quiet()
    rows = sessions(h)
    by_thread = {}
    for r in rows:
        by_thread.setdefault(r["thread_id"], []).append(r)
    assert sorted(by_thread) == ["#a", "#b"]
    assert sorted(r["state"] for r in by_thread["#a"]) == ["current", "retired"]
    assert [r["state"] for r in by_thread["#b"]] == ["current"]
    assert h.oc.prompts[-1]["session"] != h.oc.prompts[0]["session"]
    assert h.oc.prompts[-1]["session"] == by_thread["#a"][-1]["vendor_session"]


def test_attach_reports_thread_session(make):
    h = make(OC)
    h.oc.plan = [{}, {}]
    h.send("#a", "hi a", mentions=["opencode-1"])
    h.wait_quiet()
    h.send("#b", "hi b", mentions=["opencode-1"])
    h.wait_quiet()
    rows = sessions(h)
    for r in rows:
        out = h.admin("attach", agent="opencode-1", thread=r["thread_id"])
        assert r["vendor_session"] in out["result"]["command"]
