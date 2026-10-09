#!/usr/bin/env python3
"""Fake `claude -p` for hub tests: replays a recorded stream-json run (tests/fixtures) and acts like
the agent would through the shim (POST /v1/tools/... with the agent's token).

The hub spawns agents with a clean env, so the plan comes from $HOME/fake-claude/plan.json: a list
of steps consumed one per invocation (counter in $HOME/fake-claude/n). Step keys:
  as        agent id whose token to use for tool calls (required when it sends)
  fixture   recorded stream to replay (default claude-chat.jsonl)
  calls     [[tool, args], ...] made through the hub before the result event
  sleep     seconds to wait before finishing (interrupt tests)
  result    "success" (default) | "error" | "none" (exit without a result event)
  exit      exit code (default 0)
  fork      true: add a second child to the transcript's last parent (simulates a concurrent writer)
  context   override the last assistant usage so the turn's context equals this many tokens
Every invocation's argv and prompt are appended to $HOME/fake-claude/calls.jsonl.
"""
import json
import os
import re
import signal
import sys
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
home = Path(os.environ["HOME"]) / "fake-claude"
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
sid = argv[argv.index("--resume") + 1] if "--resume" in argv else argv[argv.index("--session-id") + 1]
n = int((home / "n").read_text()) if (home / "n").exists() else 0
(home / "n").write_text(str(n + 1))
plan = json.loads((home / "plan.json").read_text())
step = plan[n] if n < len(plan) else {}
with (home / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"n": n, "argv": argv, "prompt": prompt, "cwd": os.getcwd(), "pid": os.getpid()}) + "\n")

signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
cwd = Path.cwd()
transcript = Path(os.environ["HOME"]) / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd)) / f"{sid}.jsonl"
transcript.parent.mkdir(parents=True, exist_ok=True)


def tool(name, args):
    state = Path(json.loads((cwd / ".xmuse.json").read_text())["state"])
    port = json.loads((state / "hub.json").read_text())["port"]
    token = (state / "tokens" / step["as"]).read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tools/{name}", method="POST",
                                 data=json.dumps({"args": args}).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


lines = [json.loads(x) for x in (HERE.parent / "fixtures" / step.get("fixture", "claude-chat.jsonl")).open()]
result = None
parent = None
if transcript.exists():
    rows = [json.loads(x) for x in transcript.open()]
    parent = rows[-1]["uuid"] if rows else None
with transcript.open("a") as t:
    u = str(uuid.uuid4())
    t.write(json.dumps({"type": "user", "uuid": u, "parentUuid": parent, "message": {"content": prompt}}) + "\n")
    if step.get("fork") and parent:
        t.write(json.dumps({"type": "user", "uuid": str(uuid.uuid4()), "parentUuid": parent,
                            "message": {"content": "concurrent"}}) + "\n")
    a = str(uuid.uuid4())
    t.write(json.dumps({"type": "assistant", "uuid": a, "parentUuid": u, "message": {"content": "ok"}}) + "\n")

assistants = [i for i, o in enumerate(lines) if o.get("type") == "assistant"]
for i, o in enumerate(lines):
    if "session_id" in o:
        o["session_id"] = sid
    if o.get("type") == "result":
        result = o
        continue
    if step.get("context") and assistants and i == assistants[-1]:
        o["message"]["usage"].update(input_tokens=0, cache_creation_input_tokens=0,
                                     cache_read_input_tokens=step["context"])
    print(json.dumps(o), flush=True)
for name, args in step.get("calls", []):
    out = tool(name, args)
    with (home / "tool-results.jsonl").open("a") as f:
        f.write(json.dumps({"n": n, "tool": name, "out": out}) + "\n")
time.sleep(step.get("sleep", 0))
mode = step.get("result", "success")
if mode != "none" and result is not None:
    if mode == "error":
        result.update(subtype="error_during_execution", is_error=True)
    if step.get("denied"):
        result["permission_denials"] = [{"tool_name": d} for d in step["denied"]]
    print(json.dumps(result), flush=True)
sys.exit(step.get("exit", 0))
