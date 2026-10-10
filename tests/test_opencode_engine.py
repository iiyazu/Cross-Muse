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


def test_large_context_session_is_kept(make):
    h = make(OC)
    h.oc.plan = [{}, {}]
    h.send("opencode-1", "first")
    h.wait_quiet()
    h.send("opencode-1", "second")
    h.wait_quiet()
    assert [p["session"] for p in h.oc.prompts] == ["ses_fake1", "ses_fake1"]  # no automatic rotation
    assert "Earlier in" not in h.oc.prompts[1]["text"]
    s = h.q("select state, context_tokens from sessions")
    assert [x["state"] for x in s] == ["current"] and s[0]["context_tokens"] > 1000  # still recorded


def test_compaction_ended_resets_the_watermark_failed_does_not(make):
    h = make(OC)
    h.oc.plan = [{}]
    h.send("opencode-1", "first")
    h.wait_quiet()
    assert len(h.q("select * from seen")) == 1
    h.oc._frame("ses_other", "session.compaction.ended")
    h.oc._frame("ses_fake1", "session.compaction.failed", error={"message": "template"})
    h.oc._frame("ses_fake1", "session.compaction.started", reason="auto")
    time.sleep(0.5)
    assert len(h.q("select * from seen")) == 1
    h.oc._frame("ses_fake1", "session.compaction.ended", reason="auto")
    h.wait(lambda: not h.q("select * from seen"), what="watermark reset")


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


def test_shell_auto_ok_strips_env_prefix_but_keeps_consequential_asks():
    from xmuse.adapters.opencode import shell_auto_ok, strip_env
    assert strip_env("A=1 B=/x/y python -m unittest") == "python -m unittest"
    assert shell_auto_ok("shell", ["PYTHONPATH=x python -m unittest"])
    assert shell_auto_ok("shell", ["PYTHONPATH=/a/b python3 /tmp/p.py", "echo ---", "tail -4"])
    assert not shell_auto_ok("shell", ["rm -rf /"])
    assert not shell_auto_ok("shell", ["PYTHONPATH=x python -m unittest", "rm -rf /tmp/x"])
    assert not shell_auto_ok("shell", ["FOO=1 git push origin main"])
    assert not shell_auto_ok("shell", ["git push origin main"])
    assert not shell_auto_ok("edit", ["a.py"])
    assert not shell_auto_ok("shell", [])


# audit B2-2: every one of these got past the old fnmatch blocklist; the allowlist sends them to the human
BYPASSES = [
    "cd sub && git push", "true; git push", "git status || git push", "git status & git push",
    "bash -c 'git push'", "sh -c 'git push origin main'", "env git push", "command git push", "exec git push",
    "git -C . push", "git -c core.pager=sh push", "/usr/bin/git push", "./git push", "\\git push",
    "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\"])'", "python -c 'print(1)'",
    "python3 -m pip install x", "python3 /home/u/elsewhere.py", "python3 ../up.py",
    "gh pr merge 1", "npm publish", "scp a b:", "ssh host ls", "curl https://x", "wget x", "sudo ls",
    "echo $(git push)", "echo `git push`", "echo hi > ~/.bashrc", "cat < /etc/passwd", "ls >> x",
    "git status\ngit push", "find . -exec git push \\;", "find . -delete", "sed -i s/a/b/ f.py",
    "xargs git push", "git status | sh", "git log | xargs rm", "cat x | /bin/sh", "git reset --hard",
    "git merge main", "git rebase main", "git clean -fdx", "git branch -D x", "git checkout -- .",
    "rm -rf /tmp/x", "rm -f /etc/passwd", "FOO=1 bash -c 'git push'", "nohup git push", "timeout 5 git push",
    # r7 review (T8): writers and launchers hiding in read-only tools
    "sed -ni s/a/b/ f.py", "sed -Ei s/a/b/ f.py", "sed -n 'w /tmp/x' f.py", "sed -n '1e date' f.py", "sed 1d f.py",
    "sed -n 1p /etc/passwd", "git grep -O vim foo", "git grep -Ovim foo", "git grep --open-files-in-pager=sh foo",
    "git diff --output=/tmp/x", "git log --output /tmp/x", "git show --output=x HEAD", "git restore .",
    "git diff --ext-diff", "rg --pre sh foo", "rg --pre=./x foo", "rg --pre-glob '*' --pre sh foo",
    "sort -o x y", "sort -uo x y", "sort --output=x y", "tree -o x", "find . -fprintf x %p", "find . -fprint0 x",
    "ls | sort -o x",
]
ALLOWED = [
    "python -m pytest -q", "PYTHONPATH=src python3 -m unittest -v", "pytest tests/test_a.py -x",
    "python3 /tmp/probe.py", "python3 scripts/check.py", "python3 -m pytest -q 2>&1 | tail -20",
    "git status --short", "git diff HEAD~1", "git log --oneline -5", "git add a.py", "git commit -m 'x y'",
    "ls -la", "cat SPEC.md", "grep -n foo src/a.py | head -5", "find . -name '*.py'", "sed -n 1,20p a.py",
    "rm -f /tmp/opencode_probe.py", "mkdir -p build/out", "wc -l a.py b.py",
    "git log --oneline -5", "grep -o foo a.py", "sort -u a.txt", "sed -n 5p a.py", "rg -n foo src",
]


def test_shell_allowlist_blocks_every_known_bypass():
    from xmuse.adapters.opencode import command_auto_ok
    leaked = [c for c in BYPASSES if command_auto_ok(c)]
    assert leaked == []
    blocked = [c for c in ALLOWED if not command_auto_ok(c)]
    assert blocked == []


def test_experiment_policy_is_the_old_blocklist_and_only_by_name():
    from xmuse.adapters.opencode import shell_auto_ok
    probe = ["cat > /tmp/p.py <<'PY'\nprint(1)\nPY", "python3 -c 'print(1)'"]
    assert not shell_auto_ok("shell", probe)  # default: the human decides
    assert shell_auto_ok("shell", probe, "blocklist-experiment")  # unattended experiments, as in M2b
    assert not shell_auto_ok("shell", ["git push origin main"], "blocklist-experiment")
    assert not shell_auto_ok("shell", probe, "anything-else")


def test_hub_takes_the_policy_from_its_environment_only(make, monkeypatch):
    import pytest
    monkeypatch.setenv("XMUSE_SHELL_POLICY", "blocklist-experiment")
    h = make(OC)
    assert h.hub.engine.shell_policy == "blocklist-experiment"
    assert json.loads((h.state / "hub.json").read_text())["shell_policy"] == "blocklist-experiment"
    monkeypatch.setenv("XMUSE_SHELL_POLICY", "yolo")
    from xmuse.server import Hub
    with pytest.raises(SystemExit, match="XMUSE_SHELL_POLICY"):  # refused before any driver starts
        Hub(h.state, oc_base=h.oc.base)


def test_hub_start_passes_host_facts_and_policy(monkeypatch, tmp_path):
    from xmuse import cli
    seen = {}

    class P:
        pid = 1
        def poll(self): return 0
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **kw: seen.update(kw) or P())
    monkeypatch.setenv("XMUSE_SHELL_POLICY", "blocklist-experiment")
    monkeypatch.setenv("SECRET_THING", "x")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "hub.log").write_text("")
    with __import__("pytest").raises(SystemExit):  # the fake process "exits" at once
        cli.hub_start(tmp_path)
    env = seen["env"]
    assert env["WSL_DISTRO_NAME"] == "Ubuntu-Test" and env["XMUSE_SHELL_POLICY"] == "blocklist-experiment"
    assert "SECRET_THING" not in env


def test_opencode_asks_for_every_shell_command(tmp_path):
    from xmuse.adapters.opencode import write_config
    write_config(tmp_path, {"id": "oc"}, tmp_path / "state")
    perms = json.loads((tmp_path / "opencode.json").read_text())["permissions"]
    assert {"action": "shell", "resource": "*", "effect": "ask"} in perms
    assert not any(p["action"] == "shell" and p["effect"] == "allow" for p in perms)


def test_safe_rm_f_is_auto_approved_and_everything_riskier_still_asks():
    from xmuse.adapters.opencode import shell_auto_ok
    ok = lambda *cmds: shell_auto_ok("shell", list(cmds))  # noqa: E731
    assert ok("rm -f /tmp/opencode_probe.py")
    assert ok("rm -f build/x.o")
    assert ok("FOO=1 rm -f /tmp/a /tmp/b")
    for bad in ("rm -f ../x", "rm -f /etc/passwd", "rm -rf /tmp/x", "rm -f -r x", "rm -f /tmp/*.py", "rm -f",
                "rm -f /tmp/../etc/passwd", "rm -f ~/x", "rm -f x /etc/passwd", "rm -f /tmp/x; rm -rf /",
                "rm -f /tmp/x && git push", "rm -f $(echo /etc/passwd)"):
        assert not ok(bad), bad
    assert ok("python3 /tmp/p.py", "git status --short", "rm -f /tmp/opencode_minisql_probe.py")
    assert not ok("python3 -c 'print(1)'")  # inline code hides what runs: the human decides (T5)
    assert not ok("git status --short", "rm -f /tmp/x", "git push origin main")


def test_env_prefixed_harmless_shell_is_auto_approved(make):
    h = make(OC)
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "go")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_a", "PYTHONPATH=x python -m unittest")
    h.wait(lambda: h.oc.replies, what="auto reply")
    assert h.oc.replies == [{"session": "ses_fake1", "request": "per_a", "decision": "once"}]
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "once"}
    assert not any("per_a" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    h.admin("stop")
