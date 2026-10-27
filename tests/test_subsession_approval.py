"""Subsession (task-tool) permission requests belong to their parent turn's member.

A permission.asked from a session the hub never started (opencode's `task` tool runs in a child
session carrying parentID) must resolve to the member running the parent turn, register in approvals,
and approve back into the child session. A session nobody owns must not leave a phantom notice.
"""
import json
import time

OC = [("opencode-1", "opencode")]


def _tracked(h):
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "go")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")


def test_subsession_permission_registers_and_approves_into_child(make):
    h = make(OC)
    _tracked(h)
    h.oc.subsession("ses_fake1", "ses_child1")
    h.oc.ask_permission("ses_child1", "per_sub1")
    h.wait(lambda: h.q("select 1 from approvals"), what="subsession approval")
    [a] = h.q("select * from approvals")
    assert (a["agent_id"], a["vendor_session"]) == ("opencode-1", "ses_child1")
    assert any("xmuse approve per_sub1" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    assert not any("unknown" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    assert h.admin("approve", id="per_sub1", decision="once")["result"]["ok"]
    assert h.oc.replies == [{"session": "ses_child1", "request": "per_sub1", "decision": "once"}]
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "once"}
    h.admin("stop")


def test_grandchild_permission_walks_the_parent_chain(make):
    h = make(OC)
    _tracked(h)
    h.oc.subsession("ses_fake1", "ses_mid")
    h.oc.subsession("ses_mid", "ses_leaf")
    h.oc.ask_permission("ses_leaf", "per_leaf", "git status --short")
    h.wait(lambda: h.oc.replies, what="auto reply")
    assert h.oc.replies == [{"session": "ses_leaf", "request": "per_leaf", "decision": "once"}]
    h.wait(lambda: h.q("select 1 from approvals where state='decided'"), what="decided row")  # written after the reply
    [a] = h.q("select * from approvals")
    assert (a["agent_id"], a["vendor_session"], a["state"]) == ("opencode-1", "ses_leaf", "decided")
    assert json.loads(a["resources"]) == ["git status --short"]
    h.admin("stop")


def test_unknown_session_is_rejected_with_no_phantom_notice(make):
    h = make(OC)
    _tracked(h)
    h.oc.ask_permission("ses_ghost", "per_ghost")
    h.wait(lambda: h.oc.replies, what="orphan reject")
    assert h.oc.replies == [{"session": "ses_ghost", "request": "per_ghost", "decision": "reject"}]
    assert h.q("select 1 from approvals") == []
    assert not h.q("select 1 from messages where kind='notice' and body like '%per_ghost%'")
    h.admin("stop")


def test_child_of_idle_known_session_registers(make):
    """The parent session is in the sessions table but has no turn running: its child still finds the member."""
    h = make(OC)
    _tracked(h)
    h.admin("stop")
    h.wait_quiet()
    assert not h.q("select 1 from turns where state='running'")
    assert h.q("select agent_id from sessions where vendor_session='ses_fake1'") == [{"agent_id": "opencode-1"}]
    h.oc.subsession("ses_fake1", "ses_child_idle")
    h.oc.ask_permission("ses_child_idle", "per_idle")
    h.wait(lambda: h.q("select 1 from approvals"), what="idle-parent approval")
    [a] = h.q("select * from approvals")
    assert (a["agent_id"], a["vendor_session"], a["state"]) == ("opencode-1", "ses_child_idle", "pending")
    assert h.oc.replies == []  # consequential: waits for the human, not auto-rejected
    assert h.admin("approve", id="per_idle", decision="once")["result"]["ok"]
    assert h.oc.replies == [{"session": "ses_child_idle", "request": "per_idle", "decision": "once"}]


def test_human_driven_session_is_left_alone(make):
    """The user drives the session themselves: the hub neither rejects nor records nor notifies."""
    h = make(OC)
    _tracked(h)
    drv = h.hub.engine.drivers["opencode"]
    h.oc.human("ses_user1")
    h.wait(lambda: drv.headless.human.get("ses_user1"), what="human seen")
    h.oc.ask_permission("ses_user1", "per_user")
    time.sleep(1.0)  # the tracked turn still runs, so no wait_quiet: just give the engine a chance to (wrongly) act
    assert h.oc.replies == []
    assert h.q("select 1 from approvals") == []
    assert not h.q("select 1 from messages where kind='notice' and body like '%per_user%'")
    h.admin("stop")


def test_human_driving_an_idle_member_session_is_left_alone(make):
    """A member's stored session, no turn running, the user typing into it: the request is theirs to answer."""
    h = make(OC)
    _tracked(h)
    h.admin("stop")
    h.wait_quiet()
    assert h.q("select agent_id from sessions where vendor_session='ses_fake1'") == [{"agent_id": "opencode-1"}]
    drv = h.hub.engine.drivers["opencode"]
    h.oc.human("ses_fake1", seconds=3.0)  # still executing when the request arrives
    h.wait(lambda: drv.headless.human.get("ses_fake1"), what="human seen")
    h.oc.ask_permission("ses_fake1", "per_mine", "git status --short")  # harmless: would be auto-approved if recorded
    time.sleep(1.0)
    assert h.oc.replies == []
    assert h.q("select 1 from approvals") == []
    assert not h.q("select 1 from messages where kind='notice' and body like '%per_mine%'")
