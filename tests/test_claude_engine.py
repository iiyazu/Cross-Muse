"""Delivery engine through the Claude headless adapter, with a fake `claude -p` replaying M0 streams."""
import json
import time

FIX_CHAT = {"input": 6, "cache_read": 51779}  # spot values from fixtures/claude-chat.jsonl result.usage


def fixture_result(name):
    from conftest import FAKE_CLAUDE
    for line in (FAKE_CLAUDE.parent.parent / "fixtures" / name).open():
        o = json.loads(line)
        if o.get("type") == "result":
            return o["usage"]


def test_normal_completion_records_per_turn_usage(make):
    h = make()
    h.plan_claude({"as": "claude-1", "calls": [["xmuse_send", {"to": "human", "body": "pong"}],
                                                ["xmuse_done", {"summary": "replied", "next": "none"}]]})
    m = h.send("claude-1", "ping")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "succeeded" and t["adapter"] == "claude_resume" and t["fresh"] == 1
    u = fixture_result("claude-chat.jsonl")
    assert (t["input"], t["cache_read"], t["cache_write"], t["output"]) == (
        u["input_tokens"], u["cache_read_input_tokens"], u["cache_creation_input_tokens"], u["output_tokens"])
    assert t["mode"] == "chat" and t["calls"] >= 1 and t["context"] > 0
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    msgs = h.q("select sender, kind, body, chain_id, depth from messages order by id")
    assert [(x["sender"], x["kind"]) for x in msgs] == [("human", "message"), ("claude-1", "message"),
                                                         ("claude-1", "done")]
    assert {x["chain_id"] for x in msgs} == {m["chain"]} and msgs[1]["depth"] == 1
    assert h.q("select summary from turns")[0]["summary"] == "replied | next: none"


def test_explicit_model_clean_env_and_allowed_tools(make, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://leak")
    h = make()
    h.plan_claude({})
    h.send("claude-1", "hi")
    h.wait_quiet()
    [c] = h.claude_calls()
    argv = c["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert "mcp__xmuse__*" in argv and "--session-id" in argv and "--resume" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "Bash(python -m pytest:*)" in argv
    # the fake records its env through the turn log's absence of leaked vars: check the hub's env builder
    from xmuse.env import clean_env
    assert "CLAUDE_CODE_ENTRYPOINT" not in clean_env() and "ANTHROPIC_BASE_URL" not in clean_env()


def test_code_turn_is_classified_code(make):
    h = make()
    h.plan_claude({"fixture": "claude-code.jsonl"})
    h.send("claude-1", "edit calc.py")
    h.wait_quiet()
    assert h.turns()[0]["mode"] == "code"


def test_failed_turn_marks_deliveries_and_notifies(make):
    h = make()
    h.plan_claude({"result": "error"})
    m = h.send("claude-1", "do it")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed" and "error_during_execution" in t["error"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "failed"
    h.wait(lambda: h.q("select 1 from messages where kind='notice'"), what="notice")  # posted after the pause is saved
    [n] = h.q("select * from messages where kind='notice'")
    assert "failed" in n["body"] and n["thread_id"] == "dm:claude-1+human"


def test_usage_limit_requeues_and_pauses_until_reset(make):
    h = make()
    h.plan_claude({"limited": time.time() + 2}, {})
    m = h.send("claude-1", "do it")
    h.wait(lambda: h.q("select paused_until from agents")[0]["paused_until"], what="paused")
    assert h.turns()[0]["state"] == "failed" and h.turns()[0]["error"] == "usage limit reached"
    d = h.q("select * from deliveries where message_id=?", m["id"])[0]
    assert d["state"] == "queued" and d["turn_id"] is None
    assert h.q("select wakes from chains")[0]["wakes"] == 0
    [n] = h.q("select * from messages where kind='notice'")
    assert "usage limit" in n["body"] and n["thread_id"] == "dm:claude-1+human"
    time.sleep(2.1)
    h.hub.engine.kick()
    h.wait(lambda: h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done",
           what="retried after reset")
    assert len(h.claude_calls()) == 2


def test_exit_without_result_is_a_failure(make):
    h = make()
    h.plan_claude({"result": "none", "exit": 1})
    h.send("claude-1", "x")
    h.wait_quiet()
    assert h.turns()[0]["state"] == "failed" and "exit 1" in h.turns()[0]["error"]


def test_second_wake_resumes_the_same_session(make):
    h = make()
    h.plan_claude({}, {})
    h.send("claude-1", "one")
    h.wait_quiet()
    h.send("claude-1", "two")
    h.wait_quiet()
    c1, c2 = h.claude_calls()
    sid = c1["argv"][c1["argv"].index("--session-id") + 1]
    assert c2["argv"][c2["argv"].index("--resume") + 1] == sid
    assert "You are claude-1" in c1["prompt"] and "You are claude-1" not in c2["prompt"]
    [s] = h.q("select * from sessions")
    assert s["vendor_session"] == sid and s["wakes"] == 2 and s["state"] == "current"


def test_queued_messages_merge_into_one_turn(make):
    h = make()
    h.plan_claude({"sleep": 0.8}, {})
    h.send("claude-1", "first")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="turn 1 running")
    for body in ("second", "third", "fourth"):
        h.send("claude-1", body)
    assert len(h.q("select * from turns")) == 1  # one turn per recipient at a time
    h.wait_quiet()
    t1, t2 = h.claude_calls()
    assert "first" in t1["prompt"] and "second" not in t1["prompt"]
    assert all(b in t2["prompt"] for b in ("second", "third", "fourth"))
    assert len(h.turns()) == 2
    assert {d["turn_id"] for d in h.q("select turn_id from deliveries where message_id>1")} == {2}


def test_group_wakes_only_mentions_and_owner(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude"), ("claude-3", "claude")])
    h.plan_claude({}, {})
    h.send("#task", "kickoff", mentions=["claude-2"])
    h.wait_quiet()
    assert [t["agent_id"] for t in h.turns()] == ["claude-2"]
    assert h.admin("thread", id="#task", owner="claude-3")["result"]["ok"]
    h.send("#task", "fyi")
    h.wait_quiet()
    assert [t["agent_id"] for t in h.turns()] == ["claude-2", "claude-3"]
    passive = h.q("select recipient from deliveries where state='passive' order by id")
    assert [p["recipient"] for p in passive] == ["claude-1", "claude-3", "claude-1", "claude-2"]


def test_peer_reply_continues_the_chain_and_wakes_the_peer(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude")])
    h.plan_claude({"as": "claude-1", "calls": [["xmuse_send", {"to": "claude-2", "body": "please review"}]]},
                  {"as": "claude-2", "calls": [["xmuse_send", {"to": "human", "body": "lgtm"}]]})
    m = h.send("claude-1", "implement")
    h.wait_quiet()
    assert [t["agent_id"] for t in h.turns()] == ["claude-1", "claude-2"]
    msgs = h.q("select sender, chain_id, depth from messages order by id")
    assert [x["depth"] for x in msgs] == [0, 1, 2] and {x["chain_id"] for x in msgs} == {m["chain"]}
    assert h.q("select wakes from chains where id=?", m["chain"])[0]["wakes"] == 2
    assert '<xmuse from="claude-1" family="anthropic" thread="dm:claude-1+claude-2"' in h.claude_calls()[1]["prompt"]


def test_chain_cap_stops_ping_pong(make):
    h = make([("claude-a", "claude"), ("claude-b", "claude")], max_chain_wakes=5)
    steps = [{"as": a, "calls": [["xmuse_send", {"to": b, "body": f"ping {i}"}]]}
             for i, (a, b) in enumerate([("claude-a", "claude-b"), ("claude-b", "claude-a")] * 10)]
    h.plan_claude(*steps)
    m = h.send("claude-a", "start the ping-pong")
    h.wait_quiet(30)
    assert len(h.turns()) == 5
    chain = h.q("select * from chains where id=?", m["chain"])[0]
    assert chain["state"] == "capped" and chain["note"] == "max_chain_wakes" and chain["wakes"] == 5
    assert h.q("select count(*) n from deliveries where state='held'")[0]["n"] == 1
    assert any("capped" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    # a new human message starts a new chain and is delivered
    h.plan_claude({})
    h.send("claude-a", "new task")
    h.wait_quiet()
    assert len(h.turns()) == 6


def test_chain_token_cap(make):
    u = fixture_result("claude-chat.jsonl")
    per_turn = sum(u[k] for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                                  "output_tokens"))
    h = make([("claude-a", "claude"), ("claude-b", "claude")], max_chain_tokens=2 * per_turn)
    h.plan_claude(*[{"as": a, "calls": [["xmuse_send", {"to": b, "body": "again"}]]}
                    for a, b in [("claude-a", "claude-b"), ("claude-b", "claude-a")] * 3])
    m = h.send("claude-a", "go")
    h.wait_quiet()
    # the cap is checked at admission against finished turns, so a peer turn already admitted while
    # the sender was still running can overshoot it by one turn
    assert 2 <= len(h.turns()) <= 3
    c = h.q("select state, note, tokens from chains where id=?", m["chain"])[0]
    assert (c["state"], c["note"]) == ("capped", "max_chain_tokens") and c["tokens"] >= 2 * per_turn
    assert h.q("select count(*) n from deliveries where state='held'")[0]["n"] == 1


def test_stop_interrupts_running_turn_and_cancels_queue(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude")])
    h.plan_claude({"sleep": 30}, {})
    h.send("claude-1", "long task")
    h.send("claude-2", "other")
    h.wait(lambda: len(h.q("select 1 from turns where state='running'")) == 2, what="two running")
    h.send("claude-1", "queued behind")
    out = h.admin("stop", agent="claude-1")["result"]
    assert out["canceled_deliveries"] == 1 and out["interrupted_turns"] == [1]
    h.wait(lambda: h.q("select state from turns where id=1")[0]["state"] == "interrupted", what="interrupted")
    assert {d["state"] for d in h.q("select state from deliveries where recipient='claude-1'")} == {"canceled"}
    h.admin("stop", agent="claude-2")  # do not sit out the other fake's 30 s turn
    h.wait_quiet(40)
    assert h.q("select state from turns where id=2")[0]["state"] == "interrupted" or \
        h.q("select state from turns where id=2")[0]["state"] == "succeeded"


def test_stop_thread_stops_chain(make):
    h = make([("claude-a", "claude"), ("claude-b", "claude")])
    h.plan_claude({"as": "claude-a", "sleep": 30, "calls": [["xmuse_send", {"to": "claude-b", "body": "x"}]]})
    m = h.send("claude-a", "go")
    h.wait(lambda: h.q("select 1 from messages where sender='claude-a'"), what="peer message")
    h.admin("stop", thread="dm:claude-a+human")
    h.wait_quiet(20)
    assert h.q("select state from chains where id=?", m["chain"])[0]["state"] == "stopped"
    assert h.q("select state from turns")[0]["state"] == "interrupted"
    # the peer message was sent in the chain before the stop: its delivery is in another thread,
    # but a later message in the stopped chain is held
    assert [t["agent_id"] for t in h.turns()] in (["claude-a"], ["claude-a", "claude-b"])


def test_stop_everything(make):
    h = make()
    h.plan_claude({"sleep": 30})
    h.send("claude-1", "a")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.admin("stop")
    h.wait_quiet(10)
    assert h.q("select state from turns")[0]["state"] == "interrupted"
    assert {c["state"] for c in h.q("select state from chains")} == {"stopped"}


def test_idempotent_resend_within_a_turn(make):
    h = make()
    h.plan_claude({"as": "claude-1", "calls": [["xmuse_send", {"to": "human", "body": "same"}],
                                                ["xmuse_send", {"to": "human", "body": "same"}]]})
    h.send("claude-1", "go")
    h.wait_quiet()
    res = [json.loads(x) for x in (h.home / "fake-claude" / "tool-results.jsonl").open()]
    assert res[0]["out"]["result"]["id"] == res[1]["out"]["result"]["id"]
    assert res[1]["out"]["result"]["duplicate"] is True
    assert len(h.q("select * from messages where sender='claude-1'")) == 1


def test_human_idempotency_key(make):
    h = make()
    h.plan_claude({})
    a = h.send("claude-1", "once", idem="k1")
    b = h.send("claude-1", "once", idem="k1")
    assert a["id"] == b["id"]
    h.wait_quiet()
    assert len(h.turns()) == 1


def test_large_context_session_is_resumed_not_rotated(make):
    h = make()
    h.plan_claude({"context": 900_000}, {"context": 900_000})
    h.send("claude-1", "a")
    h.wait_quiet()
    h.send("claude-1", "b")
    h.wait_quiet()
    c1, c2 = h.claude_calls()
    assert "--resume" in c2["argv"] and c1["argv"][c1["argv"].index("--session-id") + 1] ==         c2["argv"][c2["argv"].index("--resume") + 1]
    assert h.q("select state, context_tokens from sessions") == [{"state": "current", "context_tokens": 900_000}]
    assert [t["fresh"] for t in h.turns()] == [1, 0]


def test_fork_detection_notes_the_turn(make):
    h = make()
    h.plan_claude({}, {"fork": True})
    h.send("claude-1", "a")
    h.wait_quiet()
    h.send("claude-1", "b")
    h.wait_quiet()
    t2 = h.turns()[1]
    assert t2["state"] == "succeeded" and "fork_detected" in t2["error"]
    assert any("fork_detected" in n["body"] for n in h.q("select body from messages where kind='notice'"))


def test_permission_denials_are_reported(make):
    h = make()
    h.plan_claude({"denied": ["Bash"]})
    h.send("claude-1", "push it")
    h.wait_quiet()
    assert "permission_denied: Bash" in h.turns()[0]["error"]


def test_agent_hourly_turn_cap_pauses_agent(make):
    h = make(agent_hourly_turns=2)
    h.plan_claude({}, {}, {}, {})
    for body in ("a", "b", "c"):
        h.send("claude-1", body)
        h.wait_quiet()
    assert len(h.turns()) == 2
    assert h.q("select paused from agents")[0]["paused"] == 1
    assert h.q("select state from deliveries order by id desc limit 1")[0]["state"] == "queued"
    with h.conn() as c:
        c.execute("update turns set started_at=0")
    h.admin("resume", agent="claude-1")
    h.wait_quiet()
    assert len(h.turns()) == 3


def test_restart_requeues_running_turns(make, tmp_path):
    h = make()
    h.plan_claude({"sleep": 30}, {})
    m = h.send("claude-1", "survive a restart")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.hub.stopping.set()
    h.hub.loop.join(5)
    from xmuse.engine import Engine
    eng = Engine(h.state, h.hub.cfg, h.hub.db, {}, h.ws)
    assert h.q("select state, error from turns")[0] == {"state": "failed", "error": "hub restarted"}
    assert h.q("select state, turn_id from deliveries where message_id=?", m["id"])[0] == {"state": "queued",
                                                                                          "turn_id": None}
    assert eng.q.empty()


def test_start_failure_fails_the_turn(make):
    h = make()
    h.hub.engine.drivers["claude"].headless.bin = "/nonexistent/claude"
    m = h.send("claude-1", "x")
    h.wait_quiet()
    assert h.turns()[0]["state"] == "failed" and "start failed" in h.turns()[0]["error"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "failed"


def test_turn_that_reaches_no_one_is_flagged(make):
    h = make()
    h.plan_claude({}, {"as": "claude-1", "calls": [["xmuse_send", {"to": "human", "body": "hi"}]]})
    h.send("claude-1", "one")
    h.wait_quiet()
    [n] = h.q("select * from messages where kind='notice'")
    assert "ended without xmuse_send or xmuse_done" in n["body"] and n["thread_id"] == "dm:claude-1+human"
    h.send("claude-1", "two")
    h.wait_quiet()
    assert len(h.q("select * from messages where kind='notice'")) == 1


def _paused(h):
    from xmuse import db
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1 where id='claude-1'")


def test_mail_already_handled_mid_turn_wakes_nobody(make):
    """Audit B2-3: acked mail, and read mail answered in its thread, cause no 'nothing new' wake."""
    h = make()
    h.plan_claude({})
    _paused(h)  # stands in for "claude-1 is in another turn": nothing is admitted meanwhile
    a = h.send("claude-1", "one")
    b = h.send("claude-1", "two")
    ids = {m["id"] for m in h.tool("claude-1", "xmuse_inbox")["result"]}
    assert ids == {a["id"], b["id"]}
    h.tool("claude-1", "xmuse_ack", ids=[a["id"]])
    h.tool("claude-1", "xmuse_send", to="human", body="got both")
    h.admin("resume", agent="claude-1")
    h.wait_quiet()
    assert h.turns() == []
    assert {d["state"] for d in h.q("select state from deliveries where recipient='claude-1'")} == {"done"}


def test_pause_set_while_a_kick_is_mid_admission_still_blocks_the_wake(make, monkeypatch):
    """A kick that already selected the agent as unpaused must not start a turn once the agent got paused
    (preset.pause runs on another thread; the pause is a safety switch, so no window may let a wake through)."""
    import threading
    from xmuse import mail
    h = make()
    h.plan_claude({})
    orig, entered, go = mail.running_turn, threading.Event(), threading.Event()
    stalled = []

    def stall_once(conn, agent_id):  # the engine thread has selected claude-1 (paused=0) and stops right here
        r = orig(conn, agent_id)
        if not stalled:
            stalled.append(1)
            entered.set()
            assert go.wait(10)
        return r
    monkeypatch.setattr(mail, "running_turn", stall_once)
    h.hub.engine.kick()
    assert entered.wait(10)
    _paused(h)
    h.send("claude-1", "one")
    go.set()
    h.hub.engine.call(lambda: None)  # every kick queued so far (the stalled one and the one from send) has run
    assert h.turns() == []
    assert [d["state"] for d in h.q("select state from deliveries where recipient='claude-1'")] == ["queued"]
    h.admin("resume", agent="claude-1")
    h.wait_quiet()
    assert len(h.turns()) == 1
    assert {d["state"] for d in h.q("select state from deliveries where recipient='claude-1'")} == {"done"}


def test_read_but_unanswered_mail_still_wakes(make):
    h = make()
    h.plan_claude({})
    _paused(h)
    h.send("claude-1", "one")
    assert len(h.tool("claude-1", "xmuse_inbox")["result"]) == 1  # read, then the turn ended without replying
    h.admin("resume", agent="claude-1")
    h.wait_quiet()
    assert len(h.turns()) == 1
