"""xmuse command line. Writes go through the hub (so the engine is kicked); reads go straight to hub.db."""
import argparse
import codecs
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, db, mail, preflight, proc
from .env import clean_env

HUB_START_TIMEOUT_S = 600  # a module constant so tests can shorten it


def call(state: Path, path: str, body: dict | None = None, token: str = "_admin") -> dict:
    hub = state / "hub.json"
    if not hub.exists():
        raise SystemExit("hub is not running (xmuse hub start)")
    port = json.loads(hub.read_text(encoding="utf-8"))["port"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=json.dumps(body or {}).encode(),
                                 headers={"authorization": "Bearer " + (state / "tokens" / token).read_text(encoding="utf-8").strip(),
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:  # the hub answers 400/401 with a JSON error body too
        try:
            out = json.loads(e.read())
        except ValueError:
            raise SystemExit(f"error: http {e.code}")
    if "error" in out:
        raise SystemExit(f"error: {out['error']['code']}: {out['error']['message']}")
    return out["result"]


def act(state: Path, body: dict) -> dict:
    """POST /v1/act with the admin token (the sidebar API: HTTP statuses, {"error": code, "message"})."""
    hub = state / "hub.json"
    if not hub.exists():
        raise SystemExit("hub is not running (xmuse hub start)")
    port = json.loads(hub.read_text(encoding="utf-8"))["port"]
    tok = (state / "tokens" / "_admin").read_text(encoding="utf-8").strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/act", method="POST", data=json.dumps(body).encode(),
                                 headers={"authorization": "Bearer " + tok, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
        except ValueError:
            raise SystemExit(f"error: http {e.code}")
        raise SystemExit(f"error: {err.get('error')}: {err.get('message')}")


def hub_start(state: Path, unit: str | None = None) -> None:
    """Start the hub after the preflight (preflight.py): detached, or as the systemd user unit `unit` (a unit outlives
    the wsl.exe call that started it; a detached child does not)."""
    if (state / "hub.json").exists():
        pid = json.loads((state / "hub.json").read_text(encoding="utf-8"))["pid"]
        if proc.alive(pid):
            print(f"hub already running (pid {pid})")
            return
        (state / "hub.json").unlink()
    checks, fixed = preflight.run(state)
    for line in fixed:
        print(f"fixed: {line}")
    for c in checks:
        if c.level != "ok":
            print(f"{c.level:4} {c.name}: {c.detail}" + (f"\n     fix: {c.fix}" if c.fix else ""))
    if any(c.level == "FAIL" for c in checks):
        raise SystemExit("hub not started: fix the FAIL lines above (xmuse doctor shows them all)")
    log_path = state / "logs" / "hub.log"
    env = preflight.host_env(state)
    if proc.WINDOWS:
        env["PYTHONUTF8"] = "1"  # files and pipes in UTF-8, whatever the ANSI code page
    if unit:
        subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True)  # a previous run of this unit
        subprocess.run(["systemctl", "--user", "reset-failed", unit], capture_output=True)
        cmd = ["systemd-run", "--user", f"--unit={unit}", "--collect",
               f"--working-directory={config.load(state)['workspace']}"]
        cmd += [f"--setenv={k}={v}" for k, v in env.items()]
        cmd += ["bash", "-c", f"exec {shlex.quote(sys.executable)} -m xmuse hub run >> {shlex.quote(str(log_path))} 2>&1"]
        subprocess.run(cmd, check=True)

        def gone() -> bool:
            return subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True,
                                  text=True).stdout.strip() != "active"
    else:
        with log_path.open("a", encoding="utf-8") as log:  # the child keeps its own copy of the descriptor
            p = proc.popen([sys.executable, "-m", "xmuse", "hub", "run"], env=clean_env(env),
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, detach=True)

        def gone() -> bool:
            return p.poll() is not None
    # model prechecks run first: dsh about 10 s, but a cold start may be retried once after the 180 s first-event
    # watchdog, so allow 600 s
    deadline = time.time() + HUB_START_TIMEOUT_S
    while time.time() < deadline:
        if (state / "hub.json").exists():
            print(f"hub started: {json.loads((state / 'hub.json').read_text(encoding='utf-8'))}")
            return
        if gone():
            tail = log_path.read_text(encoding="utf-8").strip().splitlines()[-6:]
            raise SystemExit("hub exited:\n" + "\n".join(tail))
        time.sleep(0.25)
    if unit:
        subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True)
    else:
        proc.kill_tree(p, "term")  # never leave a hub running that its caller has given up on
    raise SystemExit(f"hub did not start in {HUB_START_TIMEOUT_S} s (stopped it); see {log_path}")


def hub_stop(state: Path) -> None:
    if not (state / "hub.json").exists():
        print("hub not running")
        return
    pid = json.loads((state / "hub.json").read_text(encoding="utf-8"))["pid"]
    if proc.WINDOWS:  # no SIGTERM on Windows: ask the hub itself, so it still shuts down cleanly
        try:
            call(state, "/v1/admin/shutdown")
        except SystemExit:  # not answering: end the process
            proc.terminate(pid)
            (state / "hub.json").unlink(missing_ok=True)
    else:
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
    agents, desktop = q("select a.id, a.vendor, a.model, a.paused, s.vendor_session session, s.context_tokens context,"
                        " s.wakes, a.settings, a.bound_session from agents a left join sessions s on s.agent_id=a.id"
                        " and s.state='current'"), set()
    for a in agents:
        if db.polled(a):
            desktop.add(a["id"])
            a.update({"foreground": True} if db.settings(a).get("foreground") else {"desktop": True},
                     **mail.pending(conn, a["id"]))
        a.update({k: v for k, v in db.settings(a).items() if k in ("cwd", "effort")})  # a Claude member's directory
        del a["settings"]
    return {
        "hub": json.loads((state / "hub.json").read_text(encoding="utf-8")) if (state / "hub.json").exists() else None,
        "agents": agents,
        "running": q("select id, agent_id, adapter, chain_id, started_at from turns where state='running'"),
        "queued": [r for r in q("select recipient, count(*) n from deliveries where state='queued' and wake=1"
                                " group by recipient") if r["recipient"] not in desktop],  # desktop agents poll
        "leases": q("select pid, agent_id, vendor_session, holder, human_turn, channel_url is not null push"
                    " from leases"),
        "chains": q("select id, thread_id, state, wakes, tokens, note from chains where origin='human'"
                    " order by id desc limit 5"),
        "approvals": q("select id, agent_id, action, resources from approvals where state='pending'"),
    }


def watch(state: Path, agent: str, interval: float, out=None, once: bool = False) -> int:
    """Long-running, read-only: one stdout line per poll that found new deliveries for .

    Reads hub.db directly like  (no token, nothing marked read or acked). Starts after the current
    newest delivery, so only arrivals during the watch are reported; exits when hub.json disappears.

    once: for a foreground agent that runs this as a background task whose completion wakes it. Unacked, unread
    deliveries already waiting are printed at once; otherwise block for the first new one. Print, return 0; return 1
    when the hub stopped."""
    out = out or sys.stdout
    conn = db.connect(state / "hub.db")
    last = conn.execute("select coalesce(max(id), 0) from deliveries where recipient=?", (agent,)).fetchone()[0]
    sel = ("select d.id, m.thread_id, m.sender, m.kind, m.body from deliveries d join messages m on m.id=d.message_id"
           " where d.recipient=? and d.state != 'canceled' and ")

    def report(rs) -> None:
        items = "; ".join(f'{r["thread_id"]} from {r["sender"]} [{r["kind"]}] "{" ".join(r["body"].split())[:80]}"'
                          for r in rs)
        print(f"[xmuse] {len(rs)} new for {agent}: {items}", file=out, flush=True)

    if once:
        rs = db.rows(conn.execute(sel + "d.acked_at is null and d.read_at is null order by d.id", (agent,)))
        if rs:
            report(rs)
            return 0
    while True:
        if not (state / "hub.json").exists():
            print("[xmuse] hub stopped", file=out, flush=True)
            return 1 if once else 0
        rs = db.rows(conn.execute(sel + "d.id>? order by d.id", (agent, last)))
        if rs:
            last = rs[-1]["id"]
            report(rs)
            if once:
                return 0
        time.sleep(interval)


def read_args(path: str | None) -> dict:
    """Tool arguments from a file or piped stdin; UTF-8 (BOM or not) and BOM-marked UTF-16 (Windows PowerShell)."""
    if path:
        raw = Path(path).read_bytes()
    elif not sys.stdin.isatty():
        raw = sys.stdin.buffer.read()
    else:
        return {}
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise SystemExit(f"error: args are not UTF-8 or BOM-marked UTF-16: {e}")
    if not text.strip():
        return {}
    try:
        args = json.loads(text)
    except ValueError as e:
        raise SystemExit(f"error: args are not valid JSON: {e}")
    if not isinstance(args, dict):
        raise SystemExit("error: args must be a JSON object")
    return args


def who(name: str, via: str | None) -> str:
    return f"{name} (via {via})" if via else name


def align_lines(state: Path, show_all: bool) -> list[str]:
    return [f"E{e['id']} [{e['kind']}] {e['status']} {e['scope']} {who(e['author'], e['via'])}"
            f"{' -> ' + e['assignee'] if e['assignee'] else ''}: {e['statement']}"
            for e in db.rows(db.connect(state / "hub.db").execute(
                "select * from entries" + ("" if show_all else " where status in ('active','proposed')") + " order by id"))]


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
            head = f"#{x['id']} {ts(x['created_at'])} {who(x['sender'], x['via'])} → {x['thread_id']} [{x['kind']}]" + \
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


def transcript(state: Path, agent: str, path: Path | None = None, clip: int = 2000,
               thread: str | None = None) -> str:
    """An agent's current session as readable text (read-only; see transcript.py)."""
    from . import transcript as tr
    if path is not None:  # an explicit file: a Claude JSONL transcript or a dsh session log
        return tr.render((tr.dsh if path.name.endswith(".zstd") else tr.claude)(path), clip)
    conn = db.connect(state / "hub.db")
    a = db.row(conn.execute("select * from agents where id=?", (agent,)))
    if a is None:
        raise SystemExit(f"no agent {agent}")
    from . import compact as _compact_mod
    s = _compact_mod.session_for(conn, agent, thread)
    if s is None or not s["vendor_session"]:
        raise SystemExit(f"{agent} has no current session yet" + (f" for {thread}" if thread else ""))
    sid, cfg = s["vendor_session"], config.load(state)
    if a["vendor"] == "claude":
        from .adapters.claude import transcript as claude_path
        p = claude_path(Path(s["cwd"] or cfg["workspace"]), sid)
        if not p.exists():
            raise SystemExit(f"no transcript at {p}" + (" (a desktop session's transcript is on the Windows side:"
                                                        " pass --path)" if db.settings(a).get("desktop") else ""))
        return tr.render(tr.claude(p), clip)
    if a["vendor"] == "dsh":
        from .host import win_home
        home = Path(cfg.get("dsh_home") or win_home() / ".dsh")
        logs = sorted(home.glob(f"sessions/*/{sid}/session.v4.jsonl.zstd"))
        if not logs:
            raise SystemExit(f"no dsh session log for {sid} under {home}/sessions (set dsh_home in config.json"
                             " or pass --path)")
        return tr.render(tr.dsh(logs[-1]), clip)
    return tr.render(tr.opencode(call(state, "/v1/admin/oc_messages", {"session": sid, "agent": agent})["messages"]), clip)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="xmuse")
    ap.add_argument("--ws", type=Path, help="workspace (default: search upward from cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("workspace", type=Path)
    p = sub.add_parser("agent")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("id", nargs="?")
    p.add_argument("--vendor", choices=["claude", "opencode", "dsh", "agy"])
    p.add_argument("--model")
    p.add_argument("--role", default="")
    p.add_argument("--description", help="what this member is responsible for (peers and the sidebars see it)")
    p.add_argument("--desktop", action="store_true", help="desktop session the hub never runs: Claude coordinator (--vendor claude) or dsh foreground (--vendor dsh)")
    p.add_argument("--allow", action="append", help="extra Claude --allowedTools rule (headless)")
    p.add_argument("--cwd", type=Path, help="--vendor claude: the member's own directory (its .mcp.json and .claude/ "
                                            "go there, its turns run there): inside the workspace, or a git worktree "
                                            "of its repository; default: the workspace root (one Claude per directory)")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"],
                   help="--vendor claude headless: passed to claude --effort; ignored for other vendors")
    p.add_argument("--extra-mcp", type=Path, help="dsh / opencode headless: JSON file with a list of extra stdio MCP "
                                                  'servers [{"name", "command", "args", "env"}] (dsh run overlay, '
                                                  "opencode instance config)")
    p = sub.add_parser("hub")
    p.add_argument("action", choices=["start", "stop", "status", "run"])
    p.add_argument("--unit", help="start: run the hub as this systemd --user unit (survives the caller)")
    p = sub.add_parser("invite", help="an invitation code for a sidebar to join this room (/xmuse join <code>)")
    p.add_argument("vendor", choices=["claude", "opencode", "dsh"])
    p.add_argument("--role", default="")
    p.add_argument("--description", default="")
    p.add_argument("--name", help="member id (default: <vendor>, <vendor>-2, ...)")
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
    p.add_argument("--thread", help="the thread whose bound session to attach (default: latest current session)")
    p = sub.add_parser("new-session", help="retire a thread's session so its next wake starts fresh")
    p.add_argument("--agent", required=True)
    p.add_argument("--thread", required=True)
    p = sub.add_parser("watch", help="print a line per batch of new messages for an agent (read-only; for Monitor)")
    p.add_argument("--agent", required=True)
    p.add_argument("--interval", type=float, default=5)
    p.add_argument("--once", action="store_true", help="print waiting or the first new messages, then exit (0; 1 if the hub stopped)")
    p = sub.add_parser("tool", help="call a hub tool as an agent (for foreground sessions without MCP)")
    p.add_argument("--agent", required=True)
    p.add_argument("name", help="send, inbox, ack, thread, context, whoami, done (with or without xmuse_)")
    p.add_argument("--args-file", help="JSON arguments (default: piped stdin, else {})")
    sub.add_parser("doctor", help="check the install and this workspace; prints a fix for each problem (read-only)")
    p = sub.add_parser("transcript", help="an agent's current session as readable text (read-only)")
    p.add_argument("agent")
    p.add_argument("--thread", help="the thread whose bound session to read (default: latest current session)")
    p.add_argument("--path", type=Path, help="read this Claude .jsonl or dsh .jsonl.zstd file instead")
    p.add_argument("--clip", type=int, default=2000, help="max characters per entry (0: no limit)")
    p = sub.add_parser("run", help="start an orchestration preset: --preset plan-split-integrate --planner P "
                                   "--executors E1,E2 --task-file F")
    p.add_argument("--preset", default="plan-split-integrate", choices=["plan-split-integrate"])
    p.add_argument("--planner", required=True)
    p.add_argument("--executors", required=True, help="comma-separated agent ids")
    p.add_argument("--task-file", type=Path, required=True)
    p.add_argument("--limits", default="{}", help='JSON seconds, e.g. {"P0": 600, "P1": 1500, "P2": 600, "P3": 480, '
                                                 '"rounds": 2, "total": 3600}')
    p = sub.add_parser("run-status", help="phase, snapshots and events of a preset run (default: the latest)")
    p.add_argument("id", nargs="?", type=int)
    p = sub.add_parser("hook", help="compact: Claude SessionStart(compact) hook; stdin is the hook JSON")
    p.add_argument("kind", choices=["compact"])
    a = ap.parse_args(argv)
    if proc.WINDOWS:  # pipes get UTF-8 and \n whatever the ANSI code page (a console uses WriteConsoleW anyway)
        for s in (sys.stdout, sys.stderr):
            if hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    if a.cmd == "hook":  # re-inject the alignment after Claude compacted; never blocks Claude, whatever fails
        try:
            sid = json.load(sys.stdin).get("session_id")
            text = sid and call(config.find_state(a.ws), "/v1/admin/compact", {"session_id": sid})["snapshot"]
            if text:
                print(text)
        except (Exception, SystemExit):
            pass
        return

    if a.cmd == "doctor":  # also runs outside any workspace (fresh clone)
        from . import doctor
        sys.exit(doctor.report(doctor.run(doctor.find_state(a.ws))))
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
        st = {("foreground" if a.vendor == "dsh" else "desktop"): True} if a.desktop else {}
        if a.extra_mcp:
            if a.vendor not in ("dsh", "opencode") or a.desktop:
                raise SystemExit("--extra-mcp is only for headless --vendor dsh or opencode agents")
            from .adapters.dsh import extra_mcp
            try:
                st["extra_mcp"] = extra_mcp({"settings": {"extra_mcp": json.loads(a.extra_mcp.read_text(encoding="utf-8"))}})
            except (OSError, ValueError, AttributeError) as e:
                raise SystemExit(f"--extra-mcp {a.extra_mcp}: {e}")
        if a.cwd:
            st["cwd"] = str(a.cwd)
        if a.effort:
            st["effort"] = a.effort
        agent = add_agent(state, a.id, a.vendor, a.model, a.role, st or None, a.description)
        if a.allow:
            conn = db.connect(state / "hub.db")
            st = db.settings(agent)
            st["allowed_tools"] = st.get("allowed_tools", []) + a.allow
            with db.tx(conn):
                conn.execute("update agents set settings=? where id=?", (json.dumps(st), a.id))
        print(f"agent {a.id} ({a.vendor}, {agent['model']}) added; restart the hub to pick up a new vendor")
    elif a.cmd == "hub":
        {"start": lambda s: hub_start(s, a.unit), "stop": hub_stop,
         "status": lambda s: print(json.dumps(status(s), indent=1))}[a.action](state)
    elif a.cmd == "invite":  # the sidebar API: no {"result": ...} envelope
        print(json.dumps(act(state, {"act": "invite", "vendor": a.vendor, "role": a.role,
                                     "description": a.description, "name": a.name}), indent=1, ensure_ascii=False))
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
        for line in align_lines(state, a.all):
            print(line)
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
    elif a.cmd == "watch":
        sys.exit(watch(state, a.agent, a.interval, once=a.once))
    elif a.cmd == "tool":
        name = a.name if a.name.startswith("xmuse_") else "xmuse_" + a.name
        print(json.dumps(call(state, "/v1/tools/" + name, {"args": read_args(a.args_file)}, a.agent),
                         indent=2, ensure_ascii=False))
    elif a.cmd == "transcript":
        print(transcript(state, a.agent, a.path, a.clip, a.thread))
    elif a.cmd == "attach":
        print(call(state, "/v1/admin/attach", {"agent": a.agent, "thread": a.thread})["command"])
    elif a.cmd == "new-session":
        print(json.dumps(call(state, "/v1/admin/new_session", {"agent": a.agent, "thread": a.thread})))
    elif a.cmd == "run":
        print(json.dumps(call(state, "/v1/admin/run", {
            "preset": a.preset, "planner": a.planner, "executors": [x for x in a.executors.split(",") if x],
            "task": a.task_file.read_text(encoding="utf-8"), "limits": json.loads(a.limits)}), indent=1))
    elif a.cmd == "run-status":
        print(json.dumps(call(state, "/v1/admin/runs", {"id": a.id}), indent=1, ensure_ascii=False))
