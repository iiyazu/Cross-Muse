"""OpenCode driver against a fake v2 server replaying recorded SSE (prompt + /api/event)."""
import json
import time

from conftest import FAKE_CLAUDE

OC = [("opencode-1", "opencode")]


def recorded_usage(name):
    tot, seen, last = dict(input=0, cache_read=0, cache_write=0, output=0, calls=0), set(), None
    for line in (FAKE_CLAUDE.parent.parent / "fixtures" / name).open():
        ev = json.loads(line)
        if ev.get("type") != "session.step.ended" or ev["id"] in seen:
            continue
        seen.add(ev["id"])
        t = ev["data"]["tokens"]
        tot["input"] += t["input"]
        tot["cache_read"] += t["cache"]["read"]
        tot["cache_write"] += t["cache"]["write"]
        tot["output"] += t["output"] + t["reasoning"]
        tot["calls"] += 1
        last = t["input"] + t["cache"]["read"] + t["cache"]["write"]
    return tot, last


def test_turn_posts_queue_prompt_with_metadata_and_explicit_model(make):
    h = make(OC)
    h.oc.plan = [{"as": "opencode-1", "calls": [["xmuse_send", {"to": "human", "body": "pong"}]]}]
    m = h.send("opencode-1", "ping")
    h.wait_quiet()
    [p] = h.oc.prompts
    assert p["delivery"] == "queue" and p["metadata"]["xmuse"] == {"turn": 1, "agent": "opencode-1"}
    assert "ping" in p["text"] and "You are opencode-1" in p["text"]
    assert h.oc.sessions["ses_fake1"]["model"] == {"providerID": "opencode-go", "id": "muse-spark-1.3-contributor"}
    assert h.oc.sessions["ses_fake1"]["location"] == {"directory": str(h.ws)}
    [t] = h.turns()
    assert t["state"] == "succeeded" and t["adapter"] == "opencode" and t["handle"] == "ses_fake1"
    tot, ctx = recorded_usage("oc-chat.events.jsonl")
    assert {k: t[k] for k in tot} == tot and t["context"] == ctx and t["mode"] == "chat"
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert h.q("select body from messages where sender='opencode-1'")[0]["body"] == "pong"
    assert (h.state / "runs" / "turn-1.jsonl").read_text().count("session.step.ended") == tot["calls"]


def test_code_turn_and_session_reuse(make):
    h = make(OC)
    h.oc.plan = [{"fixture": "oc-code.events.jsonl"}, {}]
    h.send("opencode-1", "edit")
    h.wait_quiet()
    h.send("opencode-1", "again")
    h.wait_quiet()
    assert [t["mode"] for t in h.turns()] == ["code", "chat"]
    assert [p["session"] for p in h.oc.prompts] == ["ses_fake1", "ses_fake1"] and len(h.oc.sessions) == 1
    assert "You are opencode-1" not in h.oc.prompts[1]["text"]


def test_failed_execution(make):
    h = make(OC)
    h.oc.plan = [{"result": "failed"}]
    m = h.send("opencode-1", "x")
    h.wait_quiet()
    [t] = h.turns()
    assert t["state"] == "failed" and "provider error" in t["error"]
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "failed"


def test_stop_interrupts_through_the_api(make):
    h = make(OC)
    h.oc.plan = [{"result": "hang"}]
    m = h.send("opencode-1", "long")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.admin("stop", agent="opencode-1")
    h.wait_quiet()
    assert h.oc.interrupts == ["ses_fake1"]
    assert h.turns()[0]["state"] == "interrupted"
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "canceled"


def test_human_input_defers_admission(make):
    h = make(OC)
    h.oc.plan = [{}, {}]
    h.send("opencode-1", "warm up")
    h.wait_quiet()
    h.oc.human("ses_fake1", seconds=0.8)
    drv = h.hub.engine.drivers["opencode"]
    h.wait(lambda: drv.headless.human.get("ses_fake1"), what="human seen")
    h.send("opencode-1", "peer while human types")
    time.sleep(0.3)
    assert len(h.oc.prompts) == 1  # waits for the human's execution to end
    h.wait_quiet()
    assert len(h.oc.prompts) == 2 and "peer while human types" in h.oc.prompts[1]["text"]


def test_queued_messages_merge(make):
    h = make(OC)
    h.oc.plan = [{"sleep": 0.6}, {}]
    h.send("opencode-1", "one")
    h.wait(lambda: h.q("select 1 from turns where state='running'"), what="running")
    h.send("opencode-1", "two")
    h.send("opencode-1", "three")
    h.wait_quiet()
    assert len(h.oc.prompts) == 2
    assert "two" in h.oc.prompts[1]["text"] and "three" in h.oc.prompts[1]["text"]


def test_rotation_creates_a_new_session(make):
    h = make([("opencode-1", "opencode", {"rotate_at": 1000})])
    h.oc.plan = [{}, {}]
    h.send("opencode-1", "first")
    h.wait_quiet()
    h.send("opencode-1", "second")
    h.wait_quiet()
    assert [p["session"] for p in h.oc.prompts] == ["ses_fake1", "ses_fake2"]
    assert "first" in h.oc.prompts[1]["text"]  # bootstrap pack carries the thread's recent messages
    assert [s["state"] for s in h.q("select state from sessions order by id")] == ["retired", "current"]


def test_permission_request_is_forwarded_and_approved(make):
    h = make(OC)
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "ship it")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_9")
    h.wait(lambda: h.q("select 1 from approvals"), what="approval")
    [a] = h.q("select * from approvals")
    assert (a["agent_id"], a["action"], json.loads(a["resources"])) == ("opencode-1", "shell", ["git push origin main"])
    assert any("xmuse approve per_9" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    assert h.admin("approve", id="per_9", decision="once")["result"]["ok"]
    assert h.oc.replies == [{"session": "ses_fake1", "request": "per_9", "decision": "once"}]
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "once"}
    assert h.admin("approve", id="nope", decision="once")["error"]["code"] == "unknown_approval"
    h.admin("stop")


def test_claude_reviews_what_opencode_wrote(make):
    """Cross-vendor chain: OpenCode implements, asks Claude to review in a group, Claude approves."""
    h = make([("claude-1", "claude"), ("opencode-1", "opencode")])
    h.oc.plan = [{"fixture": "oc-code.events.jsonl", "as": "opencode-1", "calls": [
        ["xmuse_send", {"to": "#task", "body": "done, please review", "kind": "review_request",
                        "mentions": ["claude-1"]}]]}]
    h.plan_claude({"as": "claude-1", "calls": [["xmuse_send", {"to": "#task", "body": "approved"}],
                                                ["xmuse_done", {"summary": "reviewed", "next": "none"}]]})
    m = h.send("#task", "implement sub()", mentions=["opencode-1"])
    h.wait_quiet()
    assert [(t["agent_id"], t["mode"]) for t in h.turns()] == [("opencode-1", "code"), ("claude-1", "chat")]
    assert 'kind="review_request"' in h.claude_calls()[0]["prompt"]
    assert {c["id"]: c["wakes"] for c in h.q("select id, wakes from chains")}[m["chain"]] == 2
