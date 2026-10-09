"""MemoryOS client against a fake that follows the contract: /recall ranking with fallback, background /curate
collab (triggers, proposed entries, conflicts), /similar, capability gating, and zero calls when disabled."""
import json

import pytest

from fakes.fake_memoryos import FakeMemoryOS
from xmuse import align, wakepack

WHY = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}


@pytest.fixture
def mo():
    made = []

    def _mo(**kw):
        made.append(FakeMemoryOS(**kw))
        return made[-1]
    yield _mo
    for f in made:
        f.close()


def hub(make, url="", **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")], memoryos_url=url, **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"  # nobody is mentioned, so no turn runs anyway
    return h


def decl(h, body, kind="decision", agent="claude-1", **kw):
    r = h.tool(agent, "xmuse_send", to="#g", body=body, kind=kind, **kw)
    assert "result" in r, r
    return r["result"]


def talk(h, n, start=0):
    for i in range(start, start + n):
        h.send("#g", f"message {i}")
    h.hub.curator.join()


def view(h, query="", agent="claude-2"):
    return align.view(h.conn(), h.hub.cfg, agent, query=query)


def layer(h, scope="thread:#g", **kw):
    return [e["id"] for e in view(h, **kw)["layers"][scope]]


def memory(statement, **kw):
    return {"id": "mem_" + statement[:6], "kind": "decision", "topic_key": "t", "statement": statement, "version": 1,
            "occurrences": 1, "sources": [], **kw}


def proposed(h):
    return h.q("select * from entries where author='curate' order by id")


def test_disabled_makes_no_calls(make, mo):
    fake = mo()
    h = hub(make, "", align_thread_cap=2)  # a MemoryOS exists, but the hub is not pointed at it
    for i in range(4):
        decl(h, f"rule {i}")
    talk(h, 8)
    h.admin("close", id="#g")
    assert layer(h) == []  # archived
    assert fake.calls == [] and h.hub.mo.caps == set() and not h.hub.curator.thread.is_alive()
    assert h.q("select count(*) n from curated")[0]["n"] == 0


def test_recall_ranking_replaces_the_seq_cut(make, mo):
    fake = mo()
    h = hub(make, fake.url, align_thread_cap=2)
    for body in ("parser rule", "lexer rule", "emitter rule", "cache rule"):
        decl(h, body)
    assert layer(h, query="parser") == ["E1", "E4"]                     # E1 ranked in although it is the oldest
    v = view(h, "parser")
    assert v["truncated"] == ["thread:#g"]
    path, req = fake.calls[-1]
    assert path == "/recall" and req["schema"] == "memoryos_recall/v1" and req["k"] == 2
    assert req["query"] == "parser" and req["budget_tokens"] == 2000 and req["hints"] == {"thread_id": "#g"}
    assert [(i["id"], i["text"], i["thread_id"]) for i in req["items"]][:2] == [("E4", "cache rule", "#g"),
                                                                              ("E3", "emitter rule", "#g")]
    s = wakepack.snapshot(h.conn(), h.hub.cfg, "claude-2", "fix the parser please")  # the wake text is the query
    assert "E1 [decision] parser rule" in s and "E2 " not in s and "Older entries omitted" in s
    assert fake.calls[-1][1]["query"] == "fix the parser please"


@pytest.mark.parametrize("mode", ["500", "slow", "garbage", "empty"])
def test_recall_failures_fall_back_to_newest_and_stop_asking(make, mo, mode):
    fake = mo()
    h = hub(make, fake.url, align_thread_cap=2, align_global_cap=1)
    h.hub.mo.timeout = 0.3
    for body in ("parser rule", "lexer rule", "emitter rule", "cache rule"):
        decl(h, body)
    decl(h, "old global", scope="global")
    decl(h, "new global", scope="global")
    fake.fail["/recall"] = mode
    v = view(h, "parser")
    assert [e["id"] for e in v["layers"]["thread:#g"]] == ["E3", "E4"] and [e["id"] for e in v["layers"]["global"]] == ["E6"]
    assert v["truncated"] == ["global", "thread:#g"]
    assert fake.paths() == ["/recall"]  # the first failure skipped MemoryOS for the other layer


def test_missing_capabilities_are_never_called(make, mo):
    fake = mo(caps=("curate",))
    h = hub(make, fake.url, align_thread_cap=2)
    for i in range(4):
        decl(h, f"rule {i}")
    assert layer(h, query="rule 0") == ["E3", "E4"]
    talk(h, 8)
    assert fake.paths() == [] and h.q("select count(*) n from curated")[0]["n"] == 0  # no curate.collab either


def test_unreachable_memoryos_means_not_used(make):
    h = hub(make, "http://127.0.0.1:1", align_thread_cap=2)  # /health fails at start: the hub still starts
    for i in range(4):
        decl(h, f"rule {i}")
    talk(h, 8)
    assert h.hub.mo.caps == set() and layer(h) == ["E3", "E4"]


def test_curate_triggers_on_eight_messages_handoff_and_close(make, mo):
    fake = mo()
    h = hub(make, fake.url)
    talk(h, 7)
    assert fake.paths() == []
    talk(h, 1, 7)  # the 8th message
    assert fake.paths() == ["/curate"]
    req = fake.calls[0][1]
    assert (req["profile"], req["scope_id"], req["active"], req["context"]) == ("collab", "#g", [], [])
    assert [(w["id"], w["kind"], w["type"], w["speaker"]) for w in req["window"]] == [
        (f"m{i}", "message", "message", "human") for i in range(1, 9)]
    assert h.q("select * from curated") == [{"thread_id": "#g", "msg_id": 8}]
    talk(h, 3, 8)
    assert len(fake.calls) == 1                                          # 3 new messages are not enough
    h.tool("claude-1", "xmuse_send", to="#g", body="build the parser", kind="handoff", why=WHY, mentions=["claude-2"])
    h.hub.curator.join()
    assert fake.paths() == ["/curate"] * 2
    req = fake.calls[1][1]
    assert [w["id"] for w in req["window"]] == ["m9", "m10", "m11", "m12"] and [w["id"] for w in req["context"]] == [
        f"m{i}" for i in range(1, 9)]
    assert req["window"][-1]["kind"] == "handoff" and "tradeoff: x" in req["window"][-1]["text"]
    assert req["active"] == []                                           # the assignment it created is not curated
    h.wait_quiet()                                                       # the woken peer's turn may post a notice
    last = h.send("#g", "wrapping up")["id"]
    h.admin("close", id="#g")
    h.hub.curator.join()
    assert fake.paths() == ["/curate"] * 3
    assert [w["id"] for w in fake.calls[2][1]["window"]] == [f"m{last}"]  # only what is new since the last curate
    assert h.q("select msg_id from curated")[0]["msg_id"] == last
    h.admin("close", id="#g")
    h.hub.curator.join()
    assert len(fake.calls) == 3                                          # nothing new, nothing to curate


def test_curate_failure_keeps_the_cursor_so_the_next_trigger_retries(make, mo):
    fake = mo()
    h = hub(make, fake.url)
    fake.fail["/curate"] = "500"
    talk(h, 8)
    assert h.q("select count(*) n from curated")[0]["n"] == 0 and proposed(h) == []
    del fake.fail["/curate"]
    talk(h, 1, 8)
    assert [w["id"] for w in fake.calls[-1][1]["window"]] == [f"m{i}" for i in range(1, 10)]
    assert h.q("select msg_id from curated")[0]["msg_id"] == 9


def test_curated_memories_are_proposed_and_need_confirmation(make, mo):
    fake = mo()
    h = hub(make, fake.url)
    decl(h, "ids are int")                                  # E1 (message 1)
    decl(h, "which float?", "question")                     # E2 (message 2)
    fake.curate = lambda req: {"scope_id": "#g", "memories": [
        memory("ids are Decimal strings", supersedes_id="E1", resolves_ids=["E2", "E77", "x"],
               sources=[{"activity_id": "m1", "quote": "ids are int"}, {"activity_id": "m99", "quote": "?"}]),
        memory("ids are int"),                              # already stated: not proposed again
        memory("a fact", kind="fact"),                      # not a collab kind
        memory("", id="mem_empty")]}
    talk(h, 6, 2)
    (p,) = proposed(h)
    assert (p["status"], p["kind"], p["scope"], p["thread_id"], p["supersedes"], json.loads(p["resolves"])) == (
        "proposed", "decision", "thread:#g", "#g", 1, [2])
    assert json.loads(p["refs"]) == [1] and p["statement"] == "ids are Decimal strings"
    assert h.q("select op from entry_events where entry_id=?", p["id"]) == [{"op": "add"}]
    assert layer(h) == ["E1", "E2"]                         # proposed is in no view, and changed nothing
    assert [e["status"] for e in h.q("select status from entries where id<3 order by id")] == ["active", "active"]
    assert h.admin("align", op="confirm", id=f"E{p['id']}")["result"] == {"ok": True}
    assert layer(h) == [f"E{p['id']}"]
    assert [e["status"] for e in h.q("select status from entries where id<3 order by id")] == ["superseded", "resolved"]


def test_rejecting_a_proposal_leaves_what_it_would_replace(make, mo):
    fake = mo()
    h = hub(make, fake.url)
    decl(h, "ids are int")
    fake.curate = lambda req: {"scope_id": "#g", "memories": [memory("ids are Decimal", supersedes_id="E1")]}
    talk(h, 7, 1)
    (p,) = proposed(h)
    h.admin("align", op="reject", id=f"E{p['id']}")
    assert layer(h) == ["E1"] and h.q("select status from entries where id=?", p["id"])[0]["status"] == "rejected"


def test_conflicts_become_a_notice_in_the_thread(make, mo):
    fake = mo()
    h = hub(make, fake.url)
    decl(h, "ids are int")
    decl(h, "ids are floats")
    fake.curate = lambda req: {"scope_id": "#g", "memories": [memory("ids are strings")], "conflicts": [
        {"a_id": "E1", "b_id": "E2", "reason": "int vs float", "sources": []},
        {"a_id": "E2", "b_id": "mem_ids ar", "reason": "float vs strings", "sources": []},
        {"a_id": "E1", "b_id": "E99", "reason": "unknown entry", "sources": []}]}
    talk(h, 6, 2)
    notes = h.q("select sender, kind, body from messages where kind='notice' order by id")
    assert [(n["sender"], n["body"]) for n in notes] == [
        ("hub", "curate: E1 and E2 may contradict each other: int vs float"),
        ("hub", "curate: E2 and E3 may contradict each other: float vs strings")]
    assert h.q("select count(*) n from deliveries d join messages m on m.id=d.message_id where m.kind='notice'")[0]["n"] == 0


@pytest.mark.parametrize("n, called", [(6, False), (7, True)])
def test_similar_is_asked_above_120_percent_of_the_layer_cap(make, mo, n, called):
    fake = mo()
    fake.pairs = [{"a": "E1", "b": "E2", "score": 0.91}]
    h = hub(make, fake.url, align_thread_cap=5)               # 120% of 5 is 6
    for i in range(n):
        decl(h, f"rule {i}")
    talk(h, 8 - n, n)
    assert fake.paths() == (["/similar"] if called else []) + ["/curate"]
    if called:
        path, req = fake.calls[0]
        assert req["threshold"] == 0.88 and [i["id"] for i in req["items"]] == [f"E{i}" for i in range(7, 0, -1)]
        last = fake.calls[1][1]["context"][-1]
        assert last["id"] == "hub-similar" and "E1~E2 (0.91)" in last["text"]
    else:
        assert all(c["id"] != "hub-similar" for c in fake.calls[0][1]["context"])

