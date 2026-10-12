"""No silent stops (T7): a turn that ends with handoffs unreturned notifies the assigner.

Members here are desktop (never run by the hub): handoffs and dones go through the tools, and stall.on_turn_end
is called directly with a fabricated turn row. The engine hook itself is one call in _on_end (covered by the
wake-cost test's neighbors running the full suite)."""
import time

from xmuse import stall
from xmuse.adapters.base import TurnEnd

WHY = {k: k for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
KEY_CMD = "cat ~/.local/state/xmuse/sidebar.key"


def team(make, **cfg):
    h = make([("coord", "claude", {"desktop": True}), ("e1", "claude", {"desktop": True}),
              ("e2", "claude", {"desktop": True})], **cfg)
    with h.conn() as c:
        c.execute("insert into room(id, name, dir, host, created_at) values('r-t', 'dev', ?, 'coord', ?)",
                  (str(h.ws), time.time()))
    return h


def hand_off(h, who="coord", to="e1", body="do the thing"):
    out = h.tool(who, "xmuse_send", to=to, body=body, kind="handoff", why=WHY)
    assert "result" in out, out
    return out["result"]["id"]


def end_turn(h, agent, status, turn_id=7, error=None, session=None, cfg=None):
    turn = {"id": turn_id, "agent_id": agent, "error": error, "started_at": 0.0}
    stall.on_turn_end(h.conn(), h.hub.cfg if cfg is None else cfg, turn, TurnEnd(turn_id, status, session, error=error))
    return turn


def hub_notes(h, like="%stopped without handing back%"):
    return h.q("select thread_id, body from messages where sender='hub' and body like ?", like)


def test_succeeded_without_done_notifies(make):
    h = team(make)
    mid = hand_off(h)
    end_turn(h, "e1", "succeeded")
    [n] = hub_notes(h)
    assert f"handoff #{mid}: ended its turn without xmuse_done" in n["body"]
    assert "Decide: resend, reassign, or ask the user." in n["body"]
    rows = h.q("select m.body from deliveries d join messages m on m.id=d.message_id"
               " where d.recipient='coord' and d.wake=1 and m.sender='hub'")
    assert len(rows) == 1 and f"handoff #{mid}" in rows[0]["body"]


def test_progress_done_reports_progress(make):
    h = team(make)
    mid = hand_off(h)
    d = h.tool("e1", "xmuse_done", summary="partly", next="coord", outcome="progress")
    assert "result" in d, d
    with h.conn() as c:
        c.execute("update messages set turn_id=7 where sender='e1' and kind='done'")
    end_turn(h, "e1", "succeeded")
    [n] = hub_notes(h)
    assert f"handoff #{mid}: ended its turn after a progress report" in n["body"]


def test_failed_names_the_error(make):
    h = team(make)
    mid = hand_off(h)
    end_turn(h, "e1", "failed", error="boom")
    [n] = hub_notes(h)
    assert f"handoff #{mid}: turn failed: boom" in n["body"]


def test_interrupted_with_rejected_command(make):
    h = team(make)
    mid = hand_off(h)
    with h.conn() as c:
        c.execute("insert into approvals(id, agent_id, vendor_session, action, resources, state, decision,"
                  " created_at, decided_at) values('per_1', 'e1', 'sess1', 'shell', ?, 'decided', 'reject', 1, 2)",
                  (f'["{KEY_CMD}"]',))
    end_turn(h, "e1", "interrupted", error="no live adapter", session="sess1")
    [n] = hub_notes(h)
    assert f"handoff #{mid}: turn interrupted: no live adapter" in n["body"]
    assert "; command `cat " in n["body"] and "was auto-rejected by the shell policy" in n["body"]


def test_done_returned_stays_quiet(make):
    h = team(make)
    hand_off(h)
    for outcome in ("completed", "blocked", "needs_alignment"):
        d = h.tool("e1", "xmuse_done", summary="did it", next="coord", outcome=outcome)
        assert "result" in d, d
    end_turn(h, "e1", "succeeded")
    assert hub_notes(h) == []


def test_no_handoff_no_notice(make):
    h = team(make)
    end_turn(h, "e1", "succeeded")
    assert hub_notes(h) == []


def test_switch_off_stays_quiet(make):
    h = team(make)
    mid = hand_off(h)
    end_turn(h, "e1", "succeeded", cfg={**h.hub.cfg, "stall_notice": False})
    assert hub_notes(h) == []
    assert h.q("select * from messages where sender='hub'") == []


def test_info_layer_off_stays_quiet(make):
    h = team(make)
    mid = hand_off(h)
    end_turn(h, "e1", "succeeded", cfg={**h.hub.cfg, "info_layer": "off"})
    assert hub_notes(h) == []


def test_hub_sent_handoff_notifies_the_host(make):
    h = team(make)
    with h.conn() as c:
        ch = c.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at)"
                       " values('#g', 'hub', 5, 1000000, 0)").lastrowid
        mid = c.execute("insert into messages(thread_id, sender, kind, body, mentions, chain_id, created_at)"
                        " values('#g', 'hub', 'handoff', 'review this', '[]', ?, 0)", (ch,)).lastrowid
        c.execute("insert into deliveries(message_id, recipient, wake, state, updated_at) values(?,'e1',1,'queued',0)",
                  (mid,))
    end_turn(h, "e1", "succeeded")
    [n] = hub_notes(h)
    assert f"handoff #{mid}" in n["body"]
    rows = h.q("select m.body from deliveries d join messages m on m.id=d.message_id"
               " where d.recipient='coord' and d.wake=1 and m.sender='hub'")
    assert len(rows) == 1 and f"handoff #{mid}" in rows[0]["body"]


def test_human_sent_handoff_is_a_notice(make):
    h = team(make)
    out = h.send("e1", "please do this", kind="handoff", why=WHY)
    end_turn(h, "e1", "succeeded")
    [n] = hub_notes(h)
    assert n["thread_id"] == "dm:e1+human" and f"handoff #{out['id']}" in n["body"]


def test_one_notice_per_assigner(make):
    h = team(make)
    a = hand_off(h, body="first")
    b = hand_off(h, body="second")
    c = hand_off(h, who="e2", body="third")
    end_turn(h, "e1", "succeeded")
    notes = hub_notes(h)
    assert len(notes) == 2
    coord_note = [n for n in notes if f"#{a}" in n["body"]][0]
    assert f"#{a}" in coord_note["body"] and f"#{b}" in coord_note["body"] and f"#{c}" not in coord_note["body"]
    assert any(f"#{c}" in n["body"] for n in notes)
