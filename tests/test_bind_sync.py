"""A desktop session that starts (or prompts) moves the sidebar member's binding to itself, so a re-join from the
new session is not refused as bound to another session."""
from conftest import *  # noqa: F401,F403  (the make fixture)


def test_desktop_session_start_moves_the_bound_member(make):
    h = make()
    with h.conn() as c:
        c.execute("update agents set bound_session='desk-old' where id='claude-1'")
    h.hook("claude-1", "SessionStart", desktop=True, session_id="desk-new", source="startup")
    assert h.q("select bound_session from agents where id='claude-1'")[0]["bound_session"] == "desk-new"


def test_an_unbound_member_is_not_bound_by_a_desktop_session(make):
    h = make()
    h.hook("claude-1", "SessionStart", desktop=True, session_id="desk-new", source="startup")
    assert h.q("select bound_session from agents where id='claude-1'")[0]["bound_session"] is None
