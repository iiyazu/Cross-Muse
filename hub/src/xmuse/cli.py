"""xmuse command line. Writes go through the hub (so the engine is kicked); reads go straight to hub.db."""
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, db
from .env import clean_env

HUB_START_TIMEOUT_S = 600  # a module constant so tests can shorten it


def call(state: Path, path: str, body: dict | None = None) -> dict:
    hub = state / "hub.json"
    if not hub.exists():
        raise SystemExit("hub is not running (xmuse hub start)")
    port = json.loads(hub.read_text())["port"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=json.dumps(body or {}).encode(),
                                 headers={"authorization": "Bearer " + (state / "tokens" / "_admin").read_text().strip(),
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise SystemExit(f"error: {out['error']['code']}: {out['error']['message']}")
    return out["result"]


def hub_start(state: Path) -> None:
    if (state / "hub.json").exists():
        pid = json.loads((state / "hub.json").read_text())["pid"]
        if Path(f"/proc/{pid}").exists():
            print(f"hub already running (pid {pid})")
            return
        (state / "hub.json").unlink()
    log = (state / "logs" / "hub.log").open("a")
    p = subprocess.Popen([sys.executable, "-m", "xmuse", "hub", "run"], env=clean_env({"XMUSE_STATE": str(state)}),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    # model prechecks run first: dsh about 10 s, but a cold start may be retried once after the 180 s first-event
    # watchdog, so allow 600 s
    deadline = time.time() + HUB_START_TIMEOUT_S
    while time.time() < deadline:
        if (state / "hub.json").exists():
            print(f"hub started: {json.loads((state / 'hub.json').read_text())}")
            return
        if p.poll() is not None:
            tail = (state / "logs" / "hub.log").read_text().strip().splitlines()[-6:]
            raise SystemExit("hub exited:\n" + "\n".join(tail))
        time.sleep(0.25)
    os.killpg(p.pid, signal.SIGTERM)  # never leave a hub running that its caller has given up on
    raise SystemExit(f"hub did not start in {HUB_START_TIMEOUT_S} s (stopped it); see {state / 'logs' / 'hub.log'}")


def hub_stop(state: Path) -> None:
    if not (state / "hub.json").exists():
        print("hub not running")
        return
    pid = json.loads((state / "hub.json").read_text())["pid"]
    os.kill(pid, signal.SIGTERM)
    for _ in range(120):
        if not (state / "hub.json").exists():
            print("hub stopped")
            return
        time.sleep(0.25)
    raise SystemExit("hub did not stop")


def status(state: Path) -> dict:
    conn = db.connect(state / "hub.db")
    q = lambda sql, *a: db.rows(conn.execute(sql, a))  # noqa: E731
    return {
        "hub": json.loads((state / "hub.json").read_text()) if (state / "hub.json").exists() else None,
        "agents": q("select a.id, a.vendor, a.model, a.paused, s.vendor_session session, s.context_tokens context,"
                    " s.wakes from agents a left join sessions s on s.agent_id=a.id and s.state='current'"),
        "running": q("select id, agent_id, adapter, chain_id, started_at from turns where state='running'"),
        "queued": q("select recipient, count(*) n from deliveries where state='queued' and wake=1 group by recipient"),
        "leases": q("select pid, agent_id, vendor_session, holder, human_turn, channel_url is not null push"
                    " from leases"),
        "chains": q("select id, thread_id, state, wakes, tokens, note from chains where origin='human'"
                    " order by id desc limit 5"),
        "approvals": q("select id, agent_id, action, resources from approvals where state='pending'"),
    }


def quiet(state: Path) -> bool:
    s = status(state)
    return not s["running"] and not s["queued"]


def log(state: Path, thread: str | None, as_json: bool) -> None:
    conn = db.connect(state / "hub.db")
    msgs = db.rows(conn.execute("select * from messages" + (" where thread_id=?" if thread else "") + " order by id",
                                (thread,) if thread else ()))
    turns = db.rows(conn.execute("select t.*, u.mode, u.input, u.cache_read, u.cache_write, u.output, u.context,"
                                 " u.calls, u.model umodel from turns t left join usage u on u.turn_id=t.id"
                                 " order by t.id"))
    if thread:
        chains = {m["chain_id"] for m in msgs}
        turns = [t for t in turns if t["chain_id"] in chains]
    if as_json:
        agents = db.rows(conn.execute("select id, vendor, model from agents order by id"))
        print(json.dumps({"agents": agents, "messages": msgs, "turns": turns}, indent=1, ensure_ascii=False))
        return
    ts = lambda x: datetime.fromtimestamp(x).strftime("%H:%M:%S") if x else "--:--:--"  # noqa: E731
    ev = [(m["created_at"], 0, m) for m in msgs] + [(t["started_at"], 1, t) for t in turns]
    for _, kind, x in sorted(ev, key=lambda e: (e[0], e[1])):
        if kind == 0:
            mentions = json.loads(x["mentions"])
            head = f"#{x['id']} {ts(x['created_at'])} {x['sender']} → {x['thread_id']} [{x['kind']}]" + \
                   (f" @{','.join(mentions)}" if mentions else "") + f" (chain {x['chain_id']}, depth {x['depth']})"
            print(head)
            for line in x["body"].splitlines()[:12]:
                print("    " + line)
            if x["why"]:
                for k, v in json.loads(x["why"]).items():
                    print(f"    {k}: {v}")
        else:
            tot = sum(x[k] or 0 for k in ("input", "cache_read", "cache_write", "output"))
            print(f"  ↳ turn {x['id']} {x['agent_id']} {x['adapter']}{' fresh' if x['fresh'] else ''}"
                  f" {ts(x['started_at'])}–{ts(x['ended_at'])} {x['state']} {x['mode'] or '-'}"
                  f" tokens={tot:,} ctx={x['context'] or 0:,} calls={x['calls'] or 0}"
                  f"{' error=' + x['error'] if x['error'] else ''}")


def usage(state: Path, as_json: bool) -> None:
    conn = db.connect(state / "hub.db")
    rs = db.rows(conn.execute(
        "select vendor, agent_id, mode, count(*) wakes, sum(input) input, sum(cache_read) cache_read,"
        " sum(cache_write) cache_write, sum(output) output, sum(input+cache_read+cache_write+output) total,"
        " max(context) max_context from usage group by vendor, agent_id, mode order by vendor, mode"))
    for r in rs:
        r["per_wake"] = r["total"] // r["wakes"]
    if as_json:
        print(json.dumps(rs, indent=1))
        return
    print(f"{'agent':14} {'mode':5} {'wakes':>5} {'total':>12} {'per wake':>10} {'cache_read':>11} {'output':>8} {'max ctx':>8}")
    for r in rs:
        print(f"{r['agent_id']:14} {r['mode']:5} {r['wakes']:5} {r['total']:12,} {r['per_wake']:10,}"
              f" {r['cache_read']:11,} {r['output']:8,} {r['max_context']:8,}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="xmuse")
    ap.add_argument("--ws", type=Path, help="workspace (default: search upward from cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("workspace", type=Path)
    p = sub.add_parser("agent")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("id", nargs="?")
    p.add_argument("--vendor", choices=["claude", "opencode", "dsh"])
    p.add_argument("--model")
    p.add_argument("--role", default="")
    p.add_argument("--allow", action="append", help="extra Claude --allowedTools rule (headless)")
    p = sub.add_parser("hub")
    p.add_argument("action", choices=["start", "stop", "status", "run"])
    p = sub.add_parser("send")
    p.add_argument("to")
    p.add_argument("body")
    p.add_argument("--mention", action="append", default=[])
    p.add_argument("--kind", default="message")
    p.add_argument("--idem")
    p.add_argument("--scope")
    p.add_argument("--supersedes", help="E<id> this decision replaces (kind decision|assumption|question)")
    p = sub.add_parser("stop")
    p.add_argument("--agent")
    p.add_argument("--thread")
    p = sub.add_parser("resume")
    p.add_argument("--agent", required=True)
    p = sub.add_parser("thread", help="thread <id> --owner <agent> | thread close <id>")
    p.add_argument("id")
    p.add_argument("tid", nargs="?")
    p.add_argument("--owner")
    p = sub.add_parser("align", help="list [--all] | confirm E<id> | reject E<id>")
    p.add_argument("action", choices=["list", "confirm", "reject"])
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("log")
    p.add_argument("--thread")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("usage")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("wait", help="block until no turn runs and nothing is queued")
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--settle", type=float, default=8)
    p = sub.add_parser("approve")
    p.add_argument("id")
    p.add_argument("decision", choices=["once", "always", "reject"])
    p = sub.add_parser("attach")
    p.add_argument("agent")
    p = sub.add_parser("hook", help="compact: Claude SessionStart(compact) hook; stdin is the hook JSON")
    p.add_argument("kind", choices=["compact"])
    a = ap.parse_args(argv)
    if a.cmd == "hook":  # re-inject the alignment after Claude compacted; never blocks Claude, whatever fails
        try:
            sid = json.load(sys.stdin).get("session_id")
            text = sid and call(config.find_state(a.ws), "/v1/admin/compact", {"session_id": sid})["snapshot"]
            if text:
                print(text)
        except (Exception, SystemExit):
            pass
        return

    if a.cmd == "init":
        from .init import init
        print(f"state: {init(a.workspace)}")
        return
    if a.cmd == "hub" and a.action == "run":
        from .server import Hub
        logging.basicConfig(level=logging.INFO)  # hub service process only: stderr is hub.log (memoryos-call lines)
        Hub(Path(os.environ["XMUSE_STATE"])).serve()
        return
    state = config.find_state(a.ws)
    if a.cmd == "agent":
        if a.action == "list":
            print(json.dumps(status(state)["agents"], indent=1))
            return
        from .init import add_agent
        agent = add_agent(state, a.id, a.vendor, a.model, a.role)
        if a.allow:
            conn = db.connect(state / "hub.db")
            st = db.settings(agent)
            st["allowed_tools"] = st.get("allowed_tools", []) + a.allow
            with db.tx(conn):
                conn.execute("update agents set settings=? where id=?", (json.dumps(st), a.id))
        print(f"agent {a.id} ({a.vendor}, {agent['model']}) added; restart the hub to pick up a new vendor")
    elif a.cmd == "hub":
        {"start": hub_start, "stop": hub_stop,
         "status": lambda s: print(json.dumps(status(s), indent=1))}[a.action](state)
    elif a.cmd == "send":
        print(json.dumps(call(state, "/v1/admin/send", {"to": a.to, "body": a.body, "kind": a.kind,
                                                         "mentions": a.mention, "idem": a.idem,
                                                         "scope": a.scope, "supersedes": a.supersedes})))
    elif a.cmd == "stop":
        print(json.dumps(call(state, "/v1/admin/stop", {"agent": a.agent, "thread": a.thread})))
    elif a.cmd == "resume":
        print(json.dumps(call(state, "/v1/admin/resume", {"agent": a.agent})))
    elif a.cmd == "thread" and a.id == "close":
        print(json.dumps(call(state, "/v1/admin/close", {"id": a.tid})))
    elif a.cmd == "thread":
        print(json.dumps(call(state, "/v1/admin/thread", {"id": a.id, "owner": a.owner})))
    elif a.cmd == "align" and a.action == "list":
        for e in db.rows(db.connect(state / "hub.db").execute(
                "select * from entries" + ("" if a.all else " where status in ('active','proposed')") + " order by id")):
            print(f"E{e['id']} [{e['kind']}] {e['status']} {e['scope']} {e['author']}"
                  f"{' -> ' + e['assignee'] if e['assignee'] else ''}: {e['statement']}")
    elif a.cmd == "align":
        print(json.dumps(call(state, "/v1/admin/align", {"op": a.action, "id": a.id})))
    elif a.cmd == "log":
        log(state, a.thread, a.json)
    elif a.cmd == "usage":
        usage(state, a.json)
    elif a.cmd == "wait":
        end, calm = time.time() + a.timeout, None
        while time.time() < end:
            if quiet(state):
                calm = calm or time.time()
                if time.time() - calm >= a.settle:
                    print("quiet")
                    return
            else:
                calm = None
            time.sleep(1)
        raise SystemExit("timeout")
    elif a.cmd == "approve":
        print(json.dumps(call(state, "/v1/admin/approve", {"id": a.id, "decision": a.decision})))
    elif a.cmd == "attach":
        print(call(state, "/v1/admin/attach", {"agent": a.agent})["command"])
