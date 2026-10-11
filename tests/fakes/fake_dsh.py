#!/usr/bin/env python3
"""Fake `dsh --profile headless --json` for hub tests: replays a recorded M0-dsh NDJSON run and acts like the
agent would through the shim (POST /v1/tools/... with the agent's token).

Invoked exactly like the real exe: <exe> --expose-internals <cli.js> --profile headless --patch <win path>
--json [--session-id <id>] -   (task text on stdin). The plan comes from $HOME/fake-dsh/plan.json, one step
per invocation (counter in $HOME/fake-dsh/n). Step keys:
  as        agent id whose token to use for tool calls
  fixture   recorded stream (default dsh-chat.jsonl)
  calls     [[tool, args], ...] made through the hub before turn_end
  sleep     seconds to wait before finishing
  owned     true: refuse like a second writer ("already owned"), exit 1
  result    "error": end the turn with turn_end{error}, exit 1
  fail_start true: exit 1 at once with no output (the flaky cold start)
  fail_mid  true: exit 1 right after the first tool_call event (agent already acted)
  stall     seconds to sleep after the session/turn_start/step_start events were printed (started, then stuck)
  hang      seconds to sleep before any output (stuck launch)
Sessions live in $HOME/fake-dsh/sessions.json ({id: cwd}); an unknown --session-id is an error, as in dsh.
A model containing "bogus" replays the INVALID_REQUEST recording. Every invocation is logged to calls.jsonl.
"""
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
home = Path(os.environ["HOME"]) / "fake-dsh"
home.mkdir(exist_ok=True)
argv = sys.argv[1:]
prompt = sys.stdin.read()
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else None
win_patch = argv[argv.index("--patch") + 1]
patch = Path("/" + win_patch.split("\\", 4)[4].replace("\\", "/")) if win_patch.startswith("\\\\") else Path(win_patch)
overlay = json.loads(patch.read_text())
n = int((home / "n").read_text()) if (home / "n").exists() else 0
(home / "n").write_text(str(n + 1))
plan = json.loads((home / "plan.json").read_text()) if (home / "plan.json").exists() else []
step = plan[n] if n < len(plan) else {}
with (home / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"n": n, "argv": argv, "prompt": prompt, "cwd": os.getcwd(), "overlay": overlay,
                        "env": {k: os.environ.get(k) for k in ("DSH_TELEMETRY_DISABLED", "ELECTRON_RUN_AS_NODE",
                                                               "WSLENV")}}) + "\n")
store = home / "sessions.json"
sessions = json.loads(store.read_text()) if store.exists() else {}


def fail(msg):
    print(json.dumps({"type": "error", "message": msg}), flush=True)
    print(f"dsh: {msg}", file=sys.stderr)
    sys.exit(1)


if sid is not None and sid not in sessions:
    fail(f'session "{sid}" does not exist')
if step.get("owned"):
    time.sleep(0.2)
    fail(f'session "{sid}" is already owned by an active write handle')
if step.get("hang"):  # stuck launch: nothing on stdout for this many seconds
    time.sleep(step["hang"])
if step.get("fail_start"):  # bare `exit 1`, empty stderr, no NDJSON at all
    sys.exit(1)
model = next(r for r in overlay if r.get("id") == "agent-default-model")["config"]["model"]
fixture = "dsh-bogus.jsonl" if "bogus" in model else step.get("fixture", "dsh-chat.jsonl")
sid = sid or f"session-{uuid.uuid4()}"
sessions[sid] = os.getcwd()
store.write_text(json.dumps(sessions))


def tool(name, args):
    state = Path(json.loads((Path.cwd() / ".xmuse.json").read_text())["state"])
    port = json.loads((state / "hub.json").read_text())["port"]
    token = (state / "tokens" / step["as"]).read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tools/{name}", method="POST",
                                 data=json.dumps({"args": args}).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


lines = [json.loads(x) for x in (HERE.parent / "fixtures" / fixture).open()]
for i, o in enumerate(lines):
    if o["type"] == "session":
        o.update(sessionId=sid, cwd=os.getcwd())
    if o["type"] == "status" and o.get("phase") == "turn_end":
        for name, args in step.get("calls", []):
            tool(name, args)
        time.sleep(step.get("sleep", 0))
        if step.get("result") == "error":
            o["reason"] = {"kind": "error", "error": {"code": "PROVIDER_ERROR", "message": "upstream 500"}}
    print(json.dumps(o), flush=True)
    if step.get("stall") and i == 2:  # session + turn_start + step_start are out, then silence (stuck run)
        time.sleep(step["stall"])
    if step.get("fail_mid") and o["type"] == "tool_call":  # died after the agent already acted
        sys.exit(1)
ok = all(o.get("reason", {}).get("kind", "completed") == "completed" for o in lines if o.get("phase") == "turn_end")
sys.exit(0 if ok else 1)
