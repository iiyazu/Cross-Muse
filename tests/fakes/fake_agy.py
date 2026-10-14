#!/usr/bin/env python3
"""Fake `agy` CLI for hub tests: simulates prompt execution, tool calls, and failure cases.

Two ways to run, like agy: `-p <prompt>` runs one turn and exits; `--input-format stream-json --print=` stays up and
runs one turn per {"event": "user", "message": {"content": ...}} line on stdin (one init event at start, a result
event per turn; a failed turn reports status ERROR and the process goes on). Each turn takes the next step of
plan.json and appends {n, argv, prompt, cwd, step, pid} to calls.jsonl. Like agy, the result's usage is the
conversation's running total; each model step carries its own.
"""
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

home = Path(os.environ.get("HOME", os.environ.get("USERPROFILE", "."))) / "fake-agy"
home.mkdir(parents=True, exist_ok=True)
argv = sys.argv[1:]

# Extract session id and prompt
sid = None
for a in argv:
    if a.startswith("--conversation="):
        sid = a.split("=", 1)[1]
    elif a == "--conversation":
        idx = argv.index(a)
        if idx + 1 < len(argv):
            sid = argv[idx + 1]

prompt = ""
if "-p" in argv:
    idx = argv.index("-p")
    if idx + 1 < len(argv):
        prompt = argv[idx + 1]

if "--version" in argv:  # the registry probe: no turn, no counter
    print("agy 0.0-fake")
    sys.exit(0)

stream_in = "--input-format" in argv and argv[argv.index("--input-format") + 1] == "stream-json"
stream_out = "--output-format" in argv and "stream-json" in argv
store = home / "sessions.json"
total = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "cache_read_tokens": 0, "total_tokens": 0}


def emit(o):
    print(json.dumps(o), flush=True)


def next_step(prompt):
    n_file = home / "n"
    n = int(n_file.read_text(encoding="utf-8")) if n_file.exists() else 0
    n_file.write_text(str(n + 1), encoding="utf-8")
    plan_file = home / "plan.json"
    plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else []
    step = plan[n] if n < len(plan) else {}
    with (home / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"n": n, "argv": argv, "prompt": prompt, "cwd": os.getcwd(), "step": step,
                            "pid": os.getpid()}) + "\n")
    return step


def tool(step, name, args):
    ws_file = Path.cwd() / ".xmuse.json"
    if ws_file.exists():
        state = Path(json.loads(ws_file.read_text(encoding="utf-8"))["state"])
    else:
        state = Path(os.environ.get("XMUSE_STATE", "."))
    port = json.loads((state / "hub.json").read_text(encoding="utf-8"))["port"]
    agent_id = step.get("as", "agy-1")
    token = (state / "tokens" / agent_id).read_text(encoding="utf-8").strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tools/{name}", method="POST",
                                 data=json.dumps({"args": args}).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def known(sid, step):
    sessions = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    return not (sid is not None and sid not in sessions and step.get("unknown", True) and not sid.startswith("session-"))


def remember(sid):
    sessions = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    sessions[sid] = os.getcwd()
    store.write_text(json.dumps(sessions), encoding="utf-8")


def turn(step, sid):
    """One turn's work and its stream-json events (after init). Returns an error text, or None."""
    if step.get("result") == "quota":
        return "RESOURCE_EXHAUSTED: quota exceeded"
    if step.get("result") == "error":
        return "Error: model execution failed"
    if step.get("result") == "hang":
        time.sleep(step.get("sleep", 60))
    if step.get("sleep"):
        time.sleep(step["sleep"])
    for name, args in step.get("calls", []):
        tool(step, name, args)
    if not stream_out:
        if step.get("code"):
            print("Executing tool: run_command")
        print(f"Created conversation {sid}")
        print("Response: OK")
        return None
    if step.get("code"):
        emit({"event": "step_update", "step_update": {"conversation_id": sid, "step_index": 1, "state": "ACTIVE",
                                                      "step_type": "tool", "tool_name": "run_command"}})
        emit({"event": "step_update", "step_update": {"conversation_id": sid, "step_index": 1, "state": "DONE",
                                                      "step_type": "tool", "tool_name": "run_command"}})
    use = {"input_tokens": 100, "output_tokens": 30, "thinking_tokens": 10, "cache_read_tokens": 20,
           "total_tokens": 130}
    for k in total:
        total[k] += use[k]
    emit({"event": "step_update", "step_update": {"conversation_id": sid, "step_index": 2, "state": "ACTIVE",
                                                  "step_type": "agent_response", "text_delta": "Response: OK"}})
    emit({"event": "step_update", "step_update": {"conversation_id": sid, "step_index": 2, "state": "DONE",
                                                  "step_type": "agent_response", "usage": use}})
    emit({"event": "result", "result": {"conversation_id": sid, "status": "SUCCESS", "response": "Response: OK\n",
                                        "duration_seconds": 0.5, "num_turns": 1, "usage": dict(total)}})
    return None


if not stream_in:  # agy -p: one turn
    step = next_step(prompt)
    if step.get("result") == "unknown" or not known(sid, step):
        print(f"Conversation {sid} not found, ignoring --conversation flag", file=sys.stderr)
        sys.exit(1)
    sid = sid or step.get("session") or f"session-{uuid.uuid4()}"
    remember(sid)
    if stream_out:
        emit({"event": "init", "conversation_id": sid, "init": {"tools": ["xmuse_send", "xmuse_done"]}})
    err = turn(step, sid)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

# resident: init once, then a turn per stdin line
if sid is not None and not known(sid, {}):
    print(f"Conversation {sid} not found, ignoring --conversation flag", file=sys.stderr)
    sys.exit(1)
sid = sid or f"session-{uuid.uuid4()}"
remember(sid)
emit({"event": "init", "conversation_id": sid, "init": {"tools": ["xmuse_send", "xmuse_done"]}})
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("event") != "user":
        print(f"warning: ignoring unsupported stream input message event {msg.get('event')!r}", file=sys.stderr)
        continue
    step = next_step(msg["message"]["content"])
    if step.get("result") == "unknown":
        print(f"Conversation {sid} not found", file=sys.stderr)
        sys.exit(1)
    if step.get("result") == "exit":  # the process dies mid-turn
        sys.exit(2)
    err = turn(step, sid)
    if err:
        print(err, file=sys.stderr, flush=True)
        emit({"event": "result", "result": {"conversation_id": sid, "status": "ERROR", "response": "", "error": err,
                                            "usage": dict(total)}})
sys.exit(0)
