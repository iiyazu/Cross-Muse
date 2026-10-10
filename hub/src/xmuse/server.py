"""xmuse-hub process: loopback HTTP for the shim, hooks and the CLI; runs the engine thread.

Auth: every agent holds a locally issued bearer token (tokens/<agent>, 0600; only its sha256 is in
hub.db); the CLI uses tokens/_admin and speaks as 'human'. Simplified from v1 plugin grants +
pairing: one workspace, one user, no remote hosts, so no pairing codes, scopes or expiry.
"""
import hashlib
import hmac
import json
import logging
import os
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import align, config, db, mail, memoryos, peer, wakepack
from .adapters.claude import ClaudeDriver
from .adapters.dsh import DshDriver
from .adapters.opencode import POLICIES, OpenCodeDriver, Server
from .engine import Engine
from .tools import ToolError, validate


log = logging.getLogger("xmuse.hub")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Hub:
    def __init__(self, state: Path, claude_bin: str | None = None, oc_base: str | None = None,
                 human_check: bool = True):
        # human_check is a constructor argument, never config: an agent can edit config.json, not the hub's argv
        self.state, self.cfg, self.human_check = state, config.load(state), human_check
        claude_bin = claude_bin or self.cfg.get("claude_bin", "claude")
        self.ws = Path(self.cfg["workspace"])
        self.db = db.Pool(state / "hub.db")
        db.init(state / "hub.db").close()
        self.mo = self.cfg["_mo"] = memoryos.Client(self.cfg["memoryos_url"])  # align.view reads it from cfg
        self.curator = memoryos.Curator(self.mo, self.db, self.cfg)
        self.relay_cv = threading.Condition()  # notified after every request; /v1/relay/poll re-checks the db
        self.stopping = threading.Event()
        self.admin = digest((state / "tokens" / "_admin").read_text().strip())
        self.engine = Engine(state, self.cfg, self.db, {}, self.ws)
        policy = os.environ.get("XMUSE_SHELL_POLICY") or "allowlist"
        if policy not in POLICIES:
            raise SystemExit(f"XMUSE_SHELL_POLICY must be one of {', '.join(POLICIES)}, not {policy!r}")
        self.engine.shell_policy = policy
        if policy != "allowlist":
            log.warning("shell approval policy %s: bypassable blocklist for unattended experiments", policy)
        self.engine.drivers["claude"] = ClaudeDriver(self.engine, self.db, claude_bin, self.ws)
        if self.db().execute("select 1 from agents where vendor='opencode'").fetchone():
            srv = Server(self.ws, state, base=oc_base)
            if oc_base is None:
                srv.start()
            self.engine.drivers["opencode"] = OpenCodeDriver(self.engine, srv)
        if self.db().execute("select 1 from agents where vendor='dsh'").fetchone():
            self.engine.drivers["dsh"] = DshDriver(self.engine, state, self.cfg)

    def precheck(self) -> list[str]:
        """Each agent's explicit model must exist before anything is delivered (dsh: about 10 s per model)."""
        errors = []
        for a in db.rows(self.db().execute("select * from agents order by id")):
            check = getattr(self.engine.drivers[a["vendor"]], "precheck", None)
            err = check and not db.polled(a) and check(a, self.ws)  # polled agents never run in the background
            if err:
                errors.append(f"{a['id']}: model {a['model']} unusable: {err}")
        return errors

    def who(self, header: str | None) -> str | None:
        token = (header or "").removeprefix("Bearer ").strip()
        if not token:
            return None
        d = digest(token)
        if hmac.compare_digest(d, self.admin):
            return config.HUMAN
        r = self.db().execute("select id from agents where token_digest=?", (d,)).fetchone()
        return r and r[0]

    # ---- request handlers: (caller, body) -> result -----------------------------------
    def tool(self, agent: str, name: str, args: dict, session: str | None = None):
        self.check_session(agent, session)
        args = validate(name, args)
        conn = self.db()
        if name == "xmuse_send":
            if len(args["body"]) > self.cfg["body_limit"]:
                raise ToolError("body_too_long", f"body is {len(args['body'])} chars, the limit is "
                                f"{self.cfg['body_limit']}: write the content to a file in the workspace and send its path")
            sender, via = agent, None
            if args.get("on_behalf_of"):  # a desktop coordinator relaying the user's own words
                a = db.row(conn.execute("select * from agents where id=?", (agent,)))
                if not db.settings(a).get("desktop"):
                    raise ToolError("invalid_arguments", "on_behalf_of is only for the desktop coordinator session")
                sender, via = config.HUMAN, agent
            out = mail.send(conn, self.cfg, sender, args["to"], args["body"], args.get("kind", "message"),
                            args.get("mentions"), args.get("why"), None, args.get("scope"), args.get("supersedes"),
                            args.get("resolves"), args.get("depends_on"), via)
            self.curator.kick(out["thread_id"])
            self.engine.kick()
            return {"id": out["id"], "thread": out["thread_id"], "woken": out.get("woken", []),
                    **({"entries": out["entries"]} if out.get("entries") else {}),
                    **({"duplicate": True} if out.get("duplicate") else {})}
        if name == "xmuse_inbox":
            return mail.inbox(conn, agent, args.get("unread_only", True))
        if name == "xmuse_ack":
            return {"acked": mail.ack(conn, agent, args["ids"], args.get("outcome"))}
        if name == "xmuse_thread":
            return mail.thread(conn, agent, args["id"], args.get("query"), args.get("limit", 20))
        if name == "xmuse_context" and self.cfg["alignment"] == "off":  # M1 behaviour: recent messages only
            tids = [args["topic"]] if args.get("topic") else [r[0] for r in conn.execute(
                "select thread_id from thread_members where member=? order by 1", (agent,))]
            return {"threads": [mail.thread(conn, agent, t) for t in tids]}
        if name == "xmuse_context":
            return align.view(conn, self.cfg, agent, args.get("topic"), args.get("topic") or "")
        if name == "xmuse_done":
            return mail.done(conn, agent, args["summary"], args["next"], args.get("declares"))
        if name == "xmuse_approve":  # the user's decision, relayed by the coordinator; recorded with its words
            a = db.row(conn.execute("select * from agents where id=?", (agent,)))
            if not db.settings(a).get("desktop"):
                raise ToolError("invalid_arguments", "xmuse_approve is only for the desktop coordinator session; "
                                                     "ask the user, who decides through the coordinator")
            out = self.admin_approve({"id": args["id"], "decision": args["decision"]},
                                     via=agent, user_said=args["user_said"])
            return out
        return mail.whoami(conn, agent, str(self.ws))

    def hook(self, agent: str, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        if self.engine.drivers[a["vendor"]].on_hook(a, body["event"], body):
            self.engine.kick()
        if body.get("desktop"):  # the hook prints a reminder from these counts (stdout reaches the model)
            out = {"ok": True, **mail.pending(self.db(), agent)}
            if body["event"] == "UserPromptSubmit":
                out["context"] = self._desktop_context(a)
            return out
        return {"ok": True}

    def _desktop_context(self, agent: dict) -> str:
        """Alignment snapshot/delta plus unread list for a desktop coordinator's prompt; advances the session
        watermark (a turn-less wake). Nothing is marked read."""
        conn = self.db()
        s = db.row(conn.execute("select id from sessions where agent_id=? and state='current'", (agent["id"],)))
        inj = wakepack.inject(conn, self.cfg, agent, s and s["id"])
        if s:
            with db.tx(conn):
                conn.execute("insert or replace into seen values(?,?)", (s["id"], inj.seq))
        log.info("desktop-inject %s mode=%s tokens=%d", agent["id"], inj.mode, inj.tokens)
        return inj.text

    def register(self, agent: str, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        self.engine.drivers[a["vendor"]].register_shim(a, body)
        self.engine.kick()
        return {"ok": True}

    def admin_send(self, body: dict):
        # `xmuse send` is the admin token, readable by any local process: recorded as the user's, but visibly via the CLI
        out = mail.send(self.db(), self.cfg, config.HUMAN, body["to"], body["body"], body.get("kind", "message"),
                        body.get("mentions"), body.get("why"), body.get("idem"), body.get("scope"), body.get("supersedes"),
                        via=config.VIA_CLI)
        self.curator.kick(out["thread_id"])
        self.engine.kick()
        return {"id": out["id"], "thread": out["thread_id"], "chain": out["chain_id"], "woken": out.get("woken", [])}

    def admin_stop(self, body: dict):
        return self.engine.call(self.engine.stop, body.get("agent"), body.get("thread"))

    def admin_resume(self, body: dict):
        with db.tx(self.db()) as c:
            c.execute("update agents set paused=0, paused_until=null where id=?", (body["agent"],))
        self.engine.kick()
        return {"ok": True}

    def admin_thread(self, body: dict):
        with db.tx(self.db()) as c:
            c.execute("update threads set owner=? where id=?", (body.get("owner"), body["id"]))
        return {"ok": True}

    def admin_align(self, body: dict):
        return align.review(self.db(), body["op"], body["id"])

    def admin_close(self, body: dict):
        self.curator.kick(body["id"], closed=True)  # reads the thread's entries before they are archived
        return align.close_thread(self.db(), body["id"])

    def admin_compact(self, body: dict):
        """Claude's SessionStart(compact) hook: the session is re-told the alignment right now, so its
        watermark is the current version (the next wake sends only a delta)."""
        return self.engine.call(self._compact, body["session_id"])

    def _compact(self, vendor_session: str):
        conn = self.db()
        s = db.row(conn.execute("select id, agent_id from sessions where vendor_session=? order by id desc limit 1",
                                (vendor_session,)))
        if s is None:
            return {"snapshot": None}
        seq = align.current_seq(conn)
        text = wakepack.snapshot(conn, self.cfg, s["agent_id"])
        with db.tx(conn):
            conn.execute("insert or replace into seen values(?,?)", (s["id"], seq))
        return {"snapshot": text}

    def admin_approve(self, body: dict, via: str | None = None, user_said: str | None = None):
        conn = self.db()
        a = db.row(conn.execute("select * from approvals where id=?", (body["id"],)))
        if a is None:
            raise ToolError("unknown_approval", f"no approval {body['id']}")
        if a["state"] == "decided":
            raise ToolError("invalid_arguments", f"approval {a['id']} was already decided ({a['decision']})")
        self.engine.drivers["opencode"].approve(a["vendor_session"], a["id"], body["decision"])
        with db.tx(conn):
            conn.execute("update approvals set state='decided', decision=?, decided_at=? where id=?",
                         (body["decision"], db.now(), a["id"]))
        who = f"the user via {via}" + (f' ("{user_said}")' if user_said else "") if via else "the user (terminal)"
        mail.notice(conn, mail.dm_id(a["agent_id"] or "unknown", config.HUMAN),
                    f"approval {a['id']} ({a['action']} {a['resources']}): {body['decision']}, decided by {who}")
        return {"ok": True}

    def admin_attach(self, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (body["agent"],)))
        s = self.db().execute("select vendor_session from sessions where agent_id=? and state='current'",
                              (a["id"],)).fetchone()
        return {"command": self.engine.drivers[a["vendor"]].attach_command(a, s and s[0])}

    def admin_oc_messages(self, body: dict):
        """`xmuse transcript` for an OpenCode agent: its session's messages from the hub-owned server (read-only)."""
        drv = self.engine.drivers.get("opencode")
        if drv is None:
            raise ToolError("invalid_arguments", "no opencode server in this hub")
        sid, out, cursor = urllib.parse.quote(body["session"], safe=""), [], None
        for _ in range(100):  # pages of 200
            page = drv.server.api("GET", f"/api/session/{sid}/message?limit=200"
                                  + (f"&cursor={urllib.parse.quote(cursor, safe='')}" if cursor else ""))
            out += page.get("data") or []
            cursor = (page.get("cursor") or {}).get("next")
            if not cursor or not page.get("data"):
                break
        return {"messages": out}

    # ---- dsh relay: a polled (foreground) agent's bundle long-polls instead of the engine waking it ----
    def _polled_agent(self, agent: str) -> dict:
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        if a is None or not db.polled(a):
            raise ToolError("invalid_arguments", "relay is only for polled agents (xmuse agent add <id> --vendor dsh --desktop)")
        return a

    def check_session(self, agent: str, session: str | None, required: bool = False) -> None:
        """Identity enforcement for foreground agents: once /v1/relay/bind named the dsh session that acts as this
        agent, every tool call must carry that session id (header x-xmuse-session). With no binding, tool calls stay
        open (`xmuse tool --agent <id>` for a foreground session without the bundle); relay calls always need one."""
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        if a is None or not db.settings(a).get("foreground"):
            return
        bound = a["bound_session"]
        if bound is None and not required:
            return
        if bound is None:
            raise ToolError("not_bound_session", f"{agent} is not bound to a dsh session; run /xmuse bind {agent} in the "
                                                 f"session that should act as {agent}")
        if session != bound:
            raise ToolError("not_bound_session", f"this agent is bound to dsh session {bound}; run /xmuse bind in the "
                                                 f"session that should act as {agent}")

    def relay_bind(self, agent: str, body: dict, session: str | None = None):
        a = self._polled_agent(agent)
        sid = body.get("session_id")
        if not isinstance(sid, str) or not sid:
            raise ToolError("invalid_arguments", "relay/bind needs session_id (string)")
        if session is not None and session != sid:
            raise ToolError("invalid_arguments", "session_id differs from the x-xmuse-session header")
        old = a["bound_session"]
        if old == sid:
            return {"bound": sid, "replaced": None}
        conn = self.db()
        with db.tx(conn):
            conn.execute("update agents set bound_session=? where id=?", (sid, agent))
        mail.notice(conn, mail.dm_id(agent, config.HUMAN),
                    f"{agent} is now bound to dsh session {sid}" + (f" (was {old}): only that session can act as {agent}"
                                                                     if old else ": only that session can act as " + agent))
        return {"bound": sid, "replaced": old}

    def relay_unbind(self, agent: str, body: dict, session: str | None = None):
        a = self._polled_agent(agent)
        old = a["bound_session"]
        if old is None:
            return {"unbound": None}
        self.check_session(agent, session, True)
        conn = self.db()
        with db.tx(conn):
            conn.execute("update agents set bound_session=null where id=?", (agent,))
        mail.notice(conn, mail.dm_id(agent, config.HUMAN), f"{agent} is no longer bound to dsh session {old}")
        return {"unbound": old}

    def relay_poll(self, agent: str, body: dict, session: str | None = None):
        self._polled_agent(agent)
        self.check_session(agent, session, True)
        cursor = int(body.get("cursor") or 0)
        deadline = time.monotonic() + max(0.0, min(float(body.get("wait_s") or 0), 25.0))
        while True:
            rs = db.rows(self.db().execute(
                "select d.id did, d.wake, m.* from deliveries d join messages m on m.id=d.message_id"
                " where d.recipient=? and d.id>? and d.state='queued' and d.wake=1 and d.acked_at is null"
                " order by d.id limit 20", (agent, cursor)))
            if rs or time.monotonic() >= deadline or self.stopping.is_set():
                break
            with self.relay_cv:
                self.relay_cv.wait(min(0.5, max(0.0, deadline - time.monotonic())))
        if not rs:
            return {"cursor": cursor, "items": [], "text": ""}
        return {"cursor": rs[-1]["did"], "text": wakepack.relayed(self.db(), rs),
                "items": [{"delivery_id": r["did"], "message_id": r["id"], "thread": r["thread_id"], "from": r["sender"],
                           "kind": r["kind"], "mentions": json.loads(r["mentions"]), "wake": bool(r["wake"]),
                           **({"via": r["via"]} if r["via"] else {})}
                          for r in rs]}

    def relay_delivered(self, agent: str, body: dict, session: str | None = None):
        self._polled_agent(agent)
        self.check_session(agent, session, True)
        ids, sid = body.get("delivery_ids"), body.get("session_id")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids) or not isinstance(sid, str) or not sid:
            raise ToolError("invalid_arguments", "relay/delivered needs delivery_ids (integers) and session_id (string)")
        conn, t = self.db(), db.now()
        with db.tx(conn):
            n = sum(conn.execute("update deliveries set state='delivered', delivered_at=?, delivered_session=?,"
                                 " read_at=coalesce(read_at, ?), updated_at=? where id=? and recipient=?"
                                 " and state in ('queued', 'held', 'passive')", (t, sid, t, t, i, agent)).rowcount
                    for i in ids)
            cur = db.row(conn.execute("select * from sessions where agent_id=? and state='current'", (agent,)))
            if cur is None or cur["vendor_session"] != sid:  # the bundle's bound dsh session; the engine never runs it
                conn.execute("update sessions set state='retired', retired_at=? where agent_id=? and state='current'",
                             (t, agent))
                conn.execute("insert into sessions(agent_id, vendor_session, cwd, origin, created_at) values(?,?,?,?,?)",
                             (agent, sid, str(self.ws), "relay", t))
            conn.execute("update sessions set wakes=wakes+1 where agent_id=? and state='current'", (agent,))
        return {"delivered": n, "session": sid}

    RELAY = {"/v1/relay/bind": "relay_bind", "/v1/relay/unbind": "relay_unbind", "/v1/relay/poll": "relay_poll",
             "/v1/relay/delivered": "relay_delivered"}

    HUMAN_ONLY = {"approve", "align", "resume"}  # admin actions that grant power: a person, not just the token

    def agent_pids(self) -> set[int]:
        conn = self.db()
        pids = {r[0] for r in conn.execute("select pid from turns where state='running' and pid is not null")}
        pids |= {r[0] for r in conn.execute("select pid from leases where pid is not null")}
        srv = getattr(self.engine.drivers.get("opencode"), "server", None)
        if srv is not None and srv.proc is not None:
            pids.add(srv.proc.pid)
        return {int(p) for p in pids if str(p).isdigit()}

    def require_human(self, name: str, client_port: int | None) -> None:
        if not self.human_check or name not in self.HUMAN_ONLY:
            return
        why = peer.human_check(client_port or 0, self.httpd.server_address[1], self.agent_pids())
        if why:
            raise ToolError("human_only", f"{name} needs a person: {why}. Run `xmuse {name} ...` in your own "
                                          "terminal, or tell the desktop coordinator your decision so it relays it")

    def route(self, method: str, path: str, caller: str, body: dict, session: str | None = None,
              client_port: int | None = None):
        if path in self.RELAY and caller != config.HUMAN:
            return getattr(self, self.RELAY[path])(caller, body, session)
        if path.startswith("/v1/tools/") and caller != config.HUMAN:
            return self.tool(caller, path.rsplit("/", 1)[1], body.get("args", {}), session)
        if path in ("/v1/hooks/claude", "/v1/hooks/dsh") and caller != config.HUMAN:
            return self.hook(caller, body)
        if path == "/v1/shim/register" and caller != config.HUMAN:
            return self.register(caller, body)
        if path.startswith("/v1/admin/") and caller == config.HUMAN:
            fn = getattr(self, "admin_" + path.rsplit("/", 1)[1], None)
            if fn:
                self.require_human(path.rsplit("/", 1)[1], client_port)
                return fn(body)
        raise ToolError("not_found", f"{method} {path}")

    # ---- process -----------------------------------------------------------------------
    def start(self) -> None:
        hub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                caller = hub.who(self.headers.get("authorization"))
                if caller is None:
                    return self._send(401, {"error": {"code": "unauthorized", "message": "bad or missing token"}})
                n = int(self.headers.get("content-length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                    out = hub.route("POST", self.path, caller, body, self.headers.get("x-xmuse-session") or None,
                                    self.client_address[1])
                    if not self.path.startswith("/v1/relay/"):
                        with hub.relay_cv:
                            hub.relay_cv.notify_all()
                    self._send(200, {"result": out})
                except ToolError as e:
                    self._send(200, {"error": {"code": e.code, "message": e.message}})
                except (KeyError, TypeError, ValueError) as e:
                    self._send(400, {"error": {"code": "bad_request", "message": repr(e)}})

            def _send(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.loop = threading.Thread(target=self.engine.run_forever, args=(self.stopping,), daemon=True)
        self.loop.start()
        (self.state / "hub.json").write_text(json.dumps({"port": self.httpd.server_address[1], "pid": os.getpid(),
                                                         "shell_policy": self.engine.shell_policy}))
        self.engine.kick()

    def shutdown(self) -> None:
        self.stopping.set()
        self.engine.q.put(("stop",))
        self.loop.join(10)
        self.curator.stop()
        self.httpd.shutdown()
        for d in self.engine.drivers.values():
            d.close()
        (self.state / "hub.json").unlink(missing_ok=True)

    def serve(self) -> None:
        errors = self.precheck()
        if errors:
            for d in self.engine.drivers.values():
                d.close()
            raise SystemExit("precheck failed:\n" + "\n".join(errors))
        self.start()
        done = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: done.set())
        signal.signal(signal.SIGINT, lambda *_: done.set())
        done.wait()
        self.shutdown()
