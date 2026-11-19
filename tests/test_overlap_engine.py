"""File-overlap detection through the real engine (fake claude members, no models).

Two members take turns while a shared file in the workspace repo changes inside
each turn window; the engine's own wiring (pre-turn snapshot in _admit,
record_turn_end in _on_end) must produce touched rows plus one host-only #room
notice that wakes nobody and admits no new turn. A second test with
file_overlap_notice off asserts nothing is recorded and nothing is sent.
"""
import time


def _churn_until_turn_done(h, agent, tag):
    """Rewrite ws/shared.txt with distinct content until this agent's turn leaves
    running: at least one write is then strictly inside the turn's
    (pre-snapshot, post-snapshot) window, so the change is always detected."""
    h.send(agent, f"work {tag}")
    for i in range(2000):
        (h.ws / "shared.txt").write_text(f"{tag}-{i}\n", encoding="utf-8")
        if h.q("select 1 from turns where agent_id=? and state!='running'", agent):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("turn never completed")
    h.wait_quiet()
    h.wait(lambda: h.q("select 1 from touched where agent_id=?", agent), what="touched rows")


def test_engine_records_and_notifies_without_waking(make):
    h = make([("a1", "claude"), ("a2", "claude")])
    h.plan_claude({}, {})
    _churn_until_turn_done(h, "a1", "a1")
    _churn_until_turn_done(h, "a2", "a2")

    turns = h.turns()
    assert [t["agent_id"] for t in turns] == ["a1", "a2"]
    got = {r["turn_id"] for r in h.q("select turn_id from touched where path='shared.txt'")}
    assert got == {turns[0]["id"], turns[1]["id"]}

    notes = h.q("select body from messages where thread_id='#room' and kind='notice'"
                " and body like '%文件重叠%shared.txt%'")
    assert len(notes) == 1

    # the notice wakes nobody and admits no new turn
    h.wait_quiet()
    time.sleep(2)
    h.wait_quiet()
    assert len(h.turns()) == 2
    assert h.q("select count(*) c from deliveries d join messages m on m.id=d.message_id"
               " where m.sender='hub' and m.kind='notice' and d.wake=1")[0]["c"] == 0


def test_engine_off_records_nothing(make):
    h = make([("a1", "claude"), ("a2", "claude")], file_overlap_notice=False)
    h.plan_claude({}, {})
    for agent, tag in (("a1", "a1"), ("a2", "a2")):
        h.send(agent, f"work {tag}")
        (h.ws / "shared.txt").write_text(f"{tag}\n", encoding="utf-8")
        h.wait_quiet()
    assert h.q("select count(*) c from touched")[0]["c"] == 0
    assert h.q("select count(*) c from messages where kind='notice' and body like '%文件重叠%'")[0]["c"] == 0
