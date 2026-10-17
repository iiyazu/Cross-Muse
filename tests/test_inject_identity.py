"""Desktop prompt notes: they name the room and member they speak for, and a burst of identical hub notices
(10-13: a sidebar re-joined every 27 s, 120 'joined the room' notices) is one line, not 120."""
from xmuse import mail, wakepack
from xmuse import room as rooms


def prompt(h, sid="S1"):
    return h.hook("dog", "UserPromptSubmit", desktop=True, session_id=sid, pid=1)["result"]["context"]


def test_identical_notices_collapse_into_one_line(make):
    h = make([("dog", "claude", {"desktop": True})])
    for _ in range(5):
        rooms.notice(h.conn(), "claude joined the room (claude)")
    mail.notice(h.conn(), "#room", "something else")
    ctx = prompt(h)
    joined = [ln for ln in ctx.splitlines() if "joined the room" in ln]
    assert len(joined) == 1 and "(5x)" in joined[0] and "..#" in joined[0]
    assert "something else" in ctx
    assert len(h.tool("dog", "xmuse_inbox")["result"]) == 6  # nothing hidden: the inbox still has each one


def test_collapsed_runs_count_every_message_when_capped(make):
    h = make([("dog", "claude", {"desktop": True})], align_delta_tokens=60)
    for _ in range(30):
        rooms.notice(h.conn(), "claude joined the room (claude)")
    for i in range(12):
        h.send("dog", f"message number {i} " + "y" * 150)
    ctx = prompt(h)
    shown = sum(int(ln.split("(")[1].split("x)")[0]) if "x) " in ln else 1
                for ln in ctx.splitlines() if ln.startswith("- #"))
    more = int(ctx.split("... ")[1].split(" more")[0])
    assert shown + more == 42


def test_prompt_notes_name_the_room_and_member(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.send("dog", "hello")
    ctx = prompt(h)
    first = ctx.splitlines()[0]
    assert first.startswith("[xmuse] These notes are for dog in ") and "start a new session in" in first
    assert h.tool("dog", "xmuse_inbox")["result"]
    assert prompt(h) == ""  # nothing new: no identity line either


def test_single_messages_keep_their_old_shape(make):
    h = make([("dog", "claude", {"desktop": True})])
    h.send("dog", "a")
    h.send("dog", "a")  # the same text from the user is not a hub notice: two lines
    lines = [ln for ln in prompt(h).splitlines() if ln.startswith("- #")]
    assert len(lines) == 2 and all("x)" not in ln for ln in lines)
    assert wakepack._runs([]) == []
