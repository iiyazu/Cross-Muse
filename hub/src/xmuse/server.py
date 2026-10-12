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
import re
import shutil
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import agents, align, config, db, dispatch, mail, memoryos, peer, preset, registry, share, threads, wakepack
from . import room as rooms
from .adapters.claude import ClaudeDriver
from .adapters.dsh import DshDriver
from .adapters.opencode import POLICIES, OpenCodeDriver, Server
from .engine import Engine
from .tools import ToolError, tools_for, validate


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
        from .init import write_prompts  # init imports this module
        self.tools = tools_for(self.cfg)  # info layer off: only what T-plain may use, here and in tools.json
        write_prompts(self.ws, state, self.cfg)
        if not config.info_on(self.cfg):
            log.warning("information layer off: plain messages only (no entries, injection, routing or dependency wake)")
        self.db = db.Pool(state / "hub.db")
        db.init(state / "hub.db").close()
        from .init import sync_member_dirs
        sync_member_dirs(self.ws, state, self.cfg)  # Claude members' worktrees outside the workspace
        with db.tx(self.db()) as c:  # databases from before T8 stored the shell's family; peers see the model's
            for aid, vendor, model in c.execute("select id, vendor, model from agents").fetchall():
                c.execute("update agents set family=? where id=?", (config.family(vendor, model), aid))
        self.mo = self.cfg["_mo"] = memoryos.Client(self.cfg["memoryos_url"])  # align.view reads it from cfg
        self.curator = memoryos.Curator(self.mo, self.db, self.cfg)
        self.relay_cv = threading.Condition()  # notified after every request; /v1/relay/poll re-checks the db
        self.stopping = threading.Event()
        self.done = threading.Event()  # serve() returns when set (signal, or /v1/admin/shutdown)
        self.admin = digest((state / "tokens" / "_admin").read_text(encoding="utf-8").strip())
        self.view_lock, self.view_fp = threading.Lock(), None  # sidebar view version (room.fingerprint)
        self.join_lock, self.started_at = threading.Lock(), time.time()
        self.version = rooms.stored_version(self.db())
        self.engine = Engine(state, self.cfg, self.db, {}, self.ws)
        policy = os.environ.get("XMUSE_SHELL_POLICY") or "allowlist"
        if policy not in POLICIES:
            raise SystemExit(f"XMUSE_SHELL_POLICY must be one of {', '.join(POLICIES)}, not {policy!r}")
        self.engine.shell_policy = policy
        if policy != "allowlist":
            log.warning("shell approval policy %s: %s", policy,
                        "everything approved, build/test runners flagged, no human" if policy ==
                        "open-experiment" else "bypassable blocklist for unattended experiments")
        self.preset = preset.Orchestrator(self)
        self.engine.drivers["claude"] = ClaudeDriver(self.engine, self.db, claude_bin, self.ws)
        ocs = [r[0] for r in self.db().execute("select id from agents where vendor='opencode' order by id")]
        if ocs:  # one server per OpenCode agent (T12); oc_base: an already running server (tests), str or {agent: url}
            binary = self.cfg.get("opencode_bin", "opencode")
            servers = {a: Server(self.ws, state, a, binary=binary,
                                 base=oc_base.get(a) if isinstance(oc_base, dict) else oc_base) for a in ocs}
            if oc_base is None:
                for srv in servers.values():
                    srv.start()
            self.engine.drivers["opencode"] = OpenCodeDriver(self.engine, servers, start=oc_base is None)
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
        args = validate(name, args, self.tools)
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
                            args.get("resolves"), args.get("depends_on"), via, new_members=args.get("members"),
                            notify=args.get("notify"), reply_to=args.get("reply_to"))
            self.curator.kick(out["thread_id"])
            self.engine.kick()
            return {"id": out["id"], "thread": out["thread_id"], "woken": out.get("woken", []),
                    **({"pushed": out["pushed"]} if out.get("pushed") else {}),
                    **({"entries": out["entries"]} if out.get("entries") else {}),
                    **{k: out[k] for k in ("blocked", "released", "routed_to") if out.get(k)},
                    **({"duplicate": True} if out.get("duplicate") else {})}
        if name == "xmuse_inbox":
            return mail.inbox(conn, agent, args.get("unread_only", True))
        if name == "xmuse_ack":
            return {"acked": mail.ack(conn, agent, args["ids"], args.get("outcome"))}
        if name == "xmuse_thread":
            return mail.thread(conn, agent, args["id"], args.get("query"), args.get("limit", 20))
        if name == "xmuse_leave_thread":
            return threads.leave(conn, agent, args["thread"])
        if name == "xmuse_context" and not config.alignment_on(self.cfg):  # M1 behaviour: recent messages only
            tids = [args["topic"]] if args.get("topic") else [r[0] for r in conn.execute(
                "select thread_id from thread_members where member=? order by 1", (agent,))]
            return {"threads": [mail.thread(conn, agent, t) for t in tids]}
        if name == "xmuse_context":
            return align.view(conn, self.cfg, agent, args.get("topic"), args.get("topic") or "")
        if name == "xmuse_done":
            out = mail.done(conn, agent, args["summary"], args["next"], args.get("declares"), args.get("stage"),
                            outcome=args.get("outcome"), evidence=args.get("evidence"), cfg=self.cfg)
            self.engine.kick()  # a result for the host, or a review handoff, may wake someone
            return out
        if name == "xmuse_share":
            out = share.request(conn, self.cfg, agent, args)
            self.engine.kick()
            return out
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
        out = mail.send(self.db(), self.cfg, config.HUMAN, body.get("to") or "#room", body["body"],
                        body.get("kind", "message"), body.get("mentions"), body.get("why"), body.get("idem"),
                        body.get("scope"), body.get("supersedes"), via=config.VIA_CLI)
        self.curator.kick(out["thread_id"])
        self.engine.kick()
        return {"id": out["id"], "thread": out["thread_id"], "chain": out["chain_id"], "woken": out.get("woken", []),
                **({"pushed": out["pushed"]} if out.get("pushed") else {}),
                **({"routed_to": out["routed_to"]} if out.get("routed_to") else {})}

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
        out = align.review(self.db(), body["op"], body["id"])
        self.engine.kick()  # a confirmed entry may unblock a handoff (align.release)
        return out

    def admin_close(self, body: dict):
        self.curator.kick(body["id"], closed=True)  # reads the thread's entries before they are archived
        out = align.close_thread(self.db(), body["id"])
        self.engine.kick()
        return out

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
        if str(body["id"]).startswith("share:"):  # a DM share request (T3), not an OpenCode permission
            return self.approve_share(body["id"], body["decision"], via, user_said)
        a = db.row(conn.execute("select * from approvals where id=?", (body["id"],)))
        if a is None:
            raise ToolError("unknown_approval", f"no approval {body['id']}")
        if a["state"] == "decided":
            raise ToolError("invalid_arguments", f"approval {a['id']} was already decided ({a['decision']})")
        self.engine.drivers["opencode"].approve(a["vendor_session"], a["id"], body["decision"], a["agent_id"])
        with db.tx(conn):
            conn.execute("update approvals set state='decided', decision=?, decided_at=? where id=?",
                         (body["decision"], db.now(), a["id"]))
        who = f"the user via {via}" + (f' ("{user_said}")' if user_said else "") if via else "the user (terminal)"
        mail.notice(conn, mail.dm_id(a["agent_id"] or "unknown", config.HUMAN),
                    f"approval {a['id']} ({a['action']} {a['resources']}): {body['decision']}, decided by {who}")
        return {"ok": True}

    def approve_share(self, aid: str, decision: str, via: str | None = None, user_said: str | None = None):
        out = share.decide(self.db(), self.cfg, aid, decision)
        self.engine.kick()  # a delivered share may wake its target
        return {"ok": True, **out}

    def admin_run(self, body: dict):
        """Start an orchestration preset run (`xmuse run --preset plan-split-integrate`)."""
        return self.preset.start(body["task"], body["planner"], body["executors"], body.get("limits"),
                                 body.get("preset", preset.PRESET))

    def admin_runs(self, body: dict):
        return self.preset.status(body.get("id"))

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
        srv = drv.server_for(body["session"], body.get("agent"))
        sid, out, cursor = urllib.parse.quote(body["session"], safe=""), [], None
        for _ in range(100):  # pages of 200
            page = srv.api("GET", f"/api/session/{sid}/message?limit=200"
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
        return {"cursor": rs[-1]["did"], "text": wakepack.relayed(self.db(), rs, self.cfg),
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
        for srv in getattr(self.engine.drivers.get("opencode"), "servers", {}).values():  # one per instance (T12)
            if srv.proc is not None:
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

    # ---- sidebars (D2, contract XMUSE2-VIEW-API v0): own error format and HTTP statuses ----------------------
    SIDEBAR = {("GET", "/v1/view"), ("GET", "/v1/timeline"), ("POST", "/v1/act"), ("POST", "/v1/rooms"),
               ("GET", "/v1/rooms"), ("POST", "/v1/join"), ("POST", "/v1/rebind"), ("POST", "/v1/leave"),
               ("GET", "/v1/agents"), ("POST", "/v1/agents/scan"), ("POST", "/v1/agents/trial"),
               ("POST", "/v1/agents/model")}

    def view_version(self) -> int:
        conn = self.db()
        with self.view_lock:
            fp = rooms.fingerprint(conn)
            if fp != self.view_fp:
                self.view_fp, self.version = fp, self.version + 1
                rooms.save_version(conn, self.version)
            return self.version

    def wait_change(self, v: int, wait: float) -> int:
        """Long poll: requests notify relay_cv; engine-side changes (turns, statuses) are seen within 0.5 s."""
        deadline = time.monotonic() + wait
        while not self.stopping.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                break
            with self.relay_cv:
                self.relay_cv.wait(min(0.5, left))
            nv = self.view_version()
            if nv != v:
                return nv
        return v

    def sidebar(self, method: str, path: str, query: dict, body: dict, auth: str | None,
                session: str | None, key: str | None = None) -> tuple[int, dict | None]:
        if not isinstance(body, dict):
            raise rooms.ApiError(400, "bad_request", "the body must be a JSON object")
        if path in ("/v1/rooms", "/v1/join"):  # local sidebars: the sidebar key; an agent's member token never works
            p = rooms.principal(self.db(), self.admin, auth)
            if p is not None and p.kind == "member":
                raise rooms.ApiError(403, "member_forbidden", f"{path} is for sidebars, not for members")
            keyed = path == "/v1/rooms" or not str(body.get("code") or "").strip()
            if keyed and not registry.check_key(key):
                raise rooms.ApiError(401, "bad_sidebar_key", "missing or wrong x-xmuse-sidebar key")
            if path == "/v1/join":
                return 200, self.join_local(body) if keyed else self.join(body)
            return 200, self.create_room(body) if method == "POST" else self.list_rooms()
        if path in ("/v1/agents", "/v1/agents/scan", "/v1/agents/trial", "/v1/agents/model"):
            # machine-local assistant registry: the sidebar key only, like GET /v1/rooms
            p = rooms.principal(self.db(), self.admin, auth)
            if p is not None and p.kind == "member":
                raise rooms.ApiError(403, "member_forbidden", f"{path} is for sidebars, not for members")
            if not registry.check_key(key):
                raise rooms.ApiError(401, "bad_sidebar_key", "missing or wrong x-xmuse-sidebar key")
            if path == "/v1/agents":
                return 200, {"agents": agents.entries()}
            if path == "/v1/agents/scan":
                return 200, {"agents": agents.scan()}
            if path == "/v1/agents/trial":
                return 200, self.agents_trial(body)
            return 200, self.agents_model(body)
        conn = self.db()
        p = rooms.principal(conn, self.admin, auth)
        if p is None:
            raise rooms.ApiError(401, "unauthorized", "bad or missing token")
        if p.kind == "member" and path != "/v1/rebind":
            self.check_bound(p.member, session)
        if path == "/v1/view":
            since, wait = int(query.get("since") or 0), min(max(float(query.get("wait", 25)), 0.0), 30.0)
            v = self.view_version()
            if since == v and wait:
                v = self.wait_change(v, wait)
            if since == v:
                return 204, None
            return 200, rooms.view(conn, self.cfg, self.ws, p, v)
        if path == "/v1/timeline":
            before = query.get("before")
            return 200, rooms.timeline(conn, p.reader, int(before) if before else None, int(query.get("limit") or 50),
                                       restrict=p.kind == "member")
        if path == "/v1/act":
            return 200, self.act(p, body)
        if p.kind != "member":
            raise rooms.ApiError(403, "member_only", f"{path} takes the member token")
        if path == "/v1/rebind":
            sid = body.get("session_id")
            if not isinstance(sid, str) or not sid:
                raise rooms.ApiError(400, "bad_request", "rebind needs session_id (string)")
            with db.tx(conn):
                conn.execute("update agents set bound_session=? where id=?", (sid, p.member))
            return 200, {"ok": True, "member_id": p.member}
        with db.tx(conn):  # /v1/leave: unbound; undelivered mail stays
            conn.execute("update agents set bound_session=null where id=?", (p.member,))
        rooms.notice(conn, f"{p.member} left its sidebar session (still a member; mail is kept)")
        return 200, {"ok": True}

    def check_bound(self, member: str, session: str | None) -> None:
        bound = self.db().execute("select bound_session from agents where id=?", (member,)).fetchone()[0]
        if bound and session != bound:
            raise rooms.ApiError(409, "not_bound_session", f"{member} is bound to another session; send its id in "
                                                           "x-xmuse-session, or /v1/rebind from the new session")

    def _via(self, p: rooms.Principal) -> str:
        if p.kind == "admin":
            return config.VIA_CLI
        vendor = self.db().execute("select vendor from agents where id=?", (p.member,)).fetchone()[0]
        return f"{vendor} sidebar"

    def _member(self, mid) -> dict:
        a = db.row(self.db().execute("select * from agents where id=? and removed=0", (mid,)))
        if a is None:
            raise rooms.ApiError(404, "unknown_member", f"no member {mid!r}")
        return a

    def act(self, p: rooms.Principal, body: dict) -> dict:
        name = body.get("act")
        if name not in rooms.ACTS:
            raise rooms.ApiError(400, "unknown_act", f"act must be one of: {', '.join(sorted(rooms.ACTS))}")
        if p.kind == "member" and name not in rooms.MEMBER_ACTS and not (
                name == "brief" and dispatch.host(self.db()) == p.member):
            # T8a2 H12: brief is the operator's, but the host may also (re)write it with its own token
            raise rooms.ApiError(403, "operator_only", f"{name} needs the operator token (the user, from a sidebar)")
        try:
            return getattr(self, "act_" + name)(p, body)
        except ToolError as e:
            raise rooms.ApiError(threads.STATUS.get(e.code) or (404 if e.code.startswith("unknown_") else 400),
                                 e.code, e.message)

    def act_say(self, p: rooms.Principal, b: dict) -> dict:
        to, text, mentions = b.get("to") or "#room", b.get("text"), b.get("mentions") or []  # no to: the room (§8.4)
        if not isinstance(to, str) or not isinstance(text, str) or not text.strip() or not isinstance(mentions, list):
            raise rooms.ApiError(400, "bad_request", "say needs to (string), text (string), mentions (list)")
        sender, via = (p.member, None) if p.kind == "member" else (config.HUMAN, self._via(p))
        if to.startswith("dm:"):  # a DM thread id: say it to the other side
            ends = to[3:].split("+")
            if sender not in ends or len(ends) != 2:
                raise rooms.ApiError(400, "bad_target", f"{to} is not a conversation of {sender}")
            to = ends[0] if ends[1] == sender else ends[1]
        if p.kind == "member" and len(text) > self.cfg["body_limit"]:
            raise ToolError("body_too_long", f"text is {len(text)} chars, the limit is {self.cfg['body_limit']}")
        out = mail.send(self.db(), self.cfg, sender, to, text, "message", mentions, via=via,
                          reply_to=b.get("reply_to"))
        self.curator.kick(out["thread_id"])
        self.engine.kick()
        return {"id": out["id"], "thread": out["thread_id"], **({"routed_to": out["routed_to"]} if out.get("routed_to")
                                                                 else {})}

    def act_wake_host(self, p: rooms.Principal, b: dict) -> dict:
        n = dispatch.wake_host(self.db(), self.cfg)  # the host's held results go out now (§8.4)
        self.engine.kick()
        return {"ok": True, "released": n}

    def act_ack(self, p: rooms.Principal, b: dict) -> dict:
        ids = b.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise rooms.ApiError(400, "bad_request", "ack needs ids (list of message ids)")
        return {"ok": True, "acked": mail.ack(self.db(), p.reader, ids, None)}

    def act_approve(self, p: rooms.Principal, b: dict) -> dict:
        aid, decision = str(b.get("id") or ""), b.get("decision")
        if decision not in ("once", "always", "reject"):
            raise rooms.ApiError(400, "bad_request", "decision must be once, always or reject")
        if re.fullmatch(r"E\d+", aid):  # an alignment proposal (approvals[].kind alignment)
            self.admin_align({"op": "reject" if decision == "reject" else "confirm", "id": aid})
        elif aid.startswith("resume:"):  # a paused member (approvals[].kind resume)
            if decision != "reject":
                self.admin_resume({"agent": self._member(aid[7:])["id"]})
        elif aid.startswith("share:"):  # a member asks to share a user DM (approvals[].kind share)
            return self.approve_share(aid, decision)
        else:
            if "opencode" not in self.engine.drivers:
                raise rooms.ApiError(404, "unknown_approval", f"no approval {aid}")
            self.admin_approve({"id": aid, "decision": decision}, via=self._via(p))
        return {"ok": True}

    def act_invite(self, p: rooms.Principal, b: dict) -> dict:
        vendor, name = b.get("vendor"), b.get("name") or None
        if vendor not in rooms.VENDORS:
            raise rooms.ApiError(400, "bad_request", f"vendor must be one of: {', '.join(rooms.VENDORS)}")
        if name is not None and not rooms.valid_id(name):
            raise rooms.ApiError(400, "bad_request", "name: letters, digits and '-', not 'human' or 'hub'")
        conn = self.db()
        rooms.room_row(conn, self.ws)
        code, t = rooms.new_code(conn), db.now()
        exp = t + float(self.cfg.get("invite_ttl", 600))
        with db.tx(conn):
            conn.execute("insert into invites(code, vendor, role, description, name, created_by, created_at, expires_at)"
                         " values(?,?,?,?,?,?,?,?)", (code, vendor, str(b.get("role") or ""),
                                                      str(b.get("description") or ""), name, p.reader, t, exp))
        return {"code": code, "expires_at": exp, "command": f"/xmuse join {code}"}

    def act_remove(self, p: rooms.Principal, b: dict) -> dict:
        a, conn = self._member(b.get("member")), self.db()
        if rooms.room_row(conn, self.ws)["host"] == a["id"]:
            raise rooms.ApiError(409, "is_host", f"{a['id']} hosts the room: transfer_host first")
        with db.tx(conn):  # history stays; the token stops working and the member gets no more mail
            conn.execute("update agents set removed=1, paused=1, bound_session=null, token_digest=? where id=?",
                         ("removed:" + a["token_digest"], a["id"]))
            conn.execute("delete from operators where member_id=?", (a["id"],))
        self.engine.call(self.engine.stop, a["id"], None)
        rooms.notice(conn, f"{a['id']} was removed from the room")
        return {"ok": True}

    def act_pause(self, p: rooms.Principal, b: dict) -> dict:
        a = self._member(b.get("member"))
        with db.tx(self.db()) as c:
            c.execute("update agents set paused=1 where id=?", (a["id"],))
        return {"ok": True}

    def act_resume(self, p: rooms.Principal, b: dict) -> dict:
        return self.admin_resume({"agent": self._member(b.get("member"))["id"]})

    def act_transfer_host(self, p: rooms.Principal, b: dict) -> dict:
        a, conn = self._member(b.get("member")), self.db()
        rooms.room_row(conn, self.ws)
        with db.tx(conn):
            conn.execute("update room set host=?", (a["id"],))
        rooms.notice(conn, f"{a['id']} now hosts the room")
        self.reg_sync()
        return {"ok": True}

    def act_thread_new(self, p: rooms.Principal, b: dict) -> dict:
        return threads.act_new(self.db(), b)

    def act_thread_add(self, p: rooms.Principal, b: dict) -> dict:
        return threads.act_add(self.db(), b)

    def act_thread_remove(self, p: rooms.Principal, b: dict) -> dict:
        return threads.act_remove(self.db(), b)

    def act_align(self, p: rooms.Principal, b: dict) -> dict:
        if b.get("decision") not in ("confirm", "reject"):
            raise rooms.ApiError(400, "bad_request", "decision must be confirm or reject")
        self.admin_align({"op": b["decision"], "id": str(b.get("id") or "")})
        return {"ok": True}

    def act_share_mark(self, p: rooms.Principal, b: dict) -> dict:
        try:
            return share.mark(self.db(), b.get("message_id"), b.get("to") or None)
        except ToolError as e:
            if e.code == "not_shareable":
                raise rooms.ApiError(403, e.code, e.message)
            raise

    def act_brief(self, p: rooms.Principal, b: dict) -> dict:
        """T8a2 H12: the project brief as a global convention entry (operator, or the host itself).
        Replaces the previous brief; the panel writes it, newcomers read it in their entry pack."""
        text = b.get("text")
        if not isinstance(text, str) or not text.strip():
            raise rooms.ApiError(400, "bad_request", "brief needs text (string)")
        text = text.strip()
        statement = text if text.startswith("[brief]") else "[brief] " + text
        author = p.member or config.HUMAN  # the acting sidebar's member (admin: the user)
        conn = self.db()
        with db.tx(conn):
            old = conn.execute("select id from entries where kind='convention' and scope='global'"
                               " and status='active' and statement like '[brief]%' order by id desc limit 1").fetchone()
            eid = align.declare(conn, author, "#room", [], "convention", statement, "global",
                                old[0] if old else None)
        rooms.notice(conn, f"项目简介已更新 E{eid}")
        return {"entry": f"E{eid}"}

    def _text(self, b: dict, key: str) -> str | None:
        v = b.get(key)
        if v is not None and not isinstance(v, str):
            raise rooms.ApiError(400, "bad_request", f"{key} must be a string")
        return v

    def _model_ok(self, vendor: str, model: str) -> None:
        if not model.strip() or vendor == "opencode" and "/" not in model:
            raise rooms.ApiError(400, "bad_request", "model: a non-empty name (opencode: <provider>/<model>)")

    def act_member_add(self, p: rooms.Principal, b: dict) -> dict:
        """Register a member the hub runs turns for: `xmuse agent add` without --desktop (the same add_agent)."""
        vendor, name = b.get("vendor"), self._text(b, "name") or None
        if vendor not in rooms.VENDORS:
            raise rooms.ApiError(400, "bad_vendor", f"vendor must be one of: {', '.join(rooms.VENDORS)}")
        role, desc, model = self._text(b, "role"), self._text(b, "description"), self._text(b, "model") or None
        if name is not None and not rooms.valid_id(name):
            raise rooms.ApiError(400, "bad_request", "name: letters, digits and '-', not 'human' or 'hub'")
        if model:
            self._model_ok(vendor, model)
        else:
            model = agents.default_model(vendor)  # T8a2 H11: the registry's model, else the config default
        conn = self.db()
        mid = name or rooms.free_id(conn, vendor)
        if conn.execute("select 1 from agents where id=?", (mid,)).fetchone():
            raise rooms.ApiError(409, "member_exists", f"{mid} is already a member; pick another name")
        from .init import add_agent
        try:
            add_agent(self.state, mid, vendor, model, role or "", None, desc or "")
        except SystemExit as e:
            raise rooms.ApiError(400, "cannot_add", str(e))
        self.ensure_driver(vendor)
        self._member_joined(conn, mid, vendor, model)
        self.engine.kick()
        return {"member_id": mid}

    def _member_joined(self, conn, mid: str, vendor: str, model: str | None) -> None:
        """T8a2 H12: one join event in #room (no repeats) plus a wake delivery for the host, which can
        hand work out at once. A desktop host is never woken by the hub itself; it keeps the delivery."""
        text = f"{mid} 已加入（{vendor} · {model or '?'}）"
        if conn.execute("select 1 from messages where thread_id='#room' and kind='notice' and body=?",
                        (text,)).fetchone():
            return
        rooms.notice(conn, text)
        host = dispatch.host(conn)
        if host and host != mid:
            mid_ = conn.execute("select id from messages where thread_id='#room' and kind='notice' and body=?"
                                " order by id desc limit 1", (text,)).fetchone()[0]
            # The notice itself leaves a passive row for desktop members: upgrade it, don't duplicate it.
            conn.execute("insert into deliveries(message_id, recipient, wake, state, updated_at)"
                         " values(?,?,1,'queued',?) on conflict(message_id, recipient) do update set wake=1,"
                         " state='queued', updated_at=excluded.updated_at", (mid_, host, db.now()))

    def agents_trial(self, b: dict) -> dict:
        """POST /v1/agents/trial (sidebar key): one minimal round with the default (or given) model."""
        from .tools import ToolError
        vendor, model = b.get("vendor"), b.get("model") or None
        if model is not None and not isinstance(model, str):
            raise rooms.ApiError(400, "bad_request", "model must be a string")
        try:
            if vendor == "dsh":
                return self._trial_dsh(model)
            return agents.trial(vendor, model)
        except ToolError as e:
            raise rooms.ApiError(threads.STATUS.get(e.code) or 400, e.code, e.message)

    def _trial_dsh(self, model: str | None) -> dict:
        """A dsh trial through the adapter's minimal no-tools round (precheck). No bare dsh one-shot exists."""
        import tempfile
        from .tools import ToolError
        by = {e["vendor"]: e for e in agents.entries()}
        if not (by.get("dsh") or {}).get("path"):
            raise ToolError("not_installed", "dsh is not installed")
        try:
            self.ensure_driver("dsh")
            precheck = getattr(self.engine.drivers.get("dsh"), "precheck", None)
            if precheck is None:
                return agents.trial("dsh", model, dsh_run=None)
            ws = tempfile.mkdtemp(prefix="xmuse-trial-")
            try:
                err = precheck({"id": "trial-dsh", "model": model or agents.default_model("dsh"),
                                "settings": {}}, Path(ws))
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - a trial records instead of failing the request
            err = f"{type(e).__name__}: {e}"
        return agents.trial("dsh", model, dsh_run=lambda _a, _w: err)

    def agents_model(self, b: dict) -> dict:
        """POST /v1/agents/model (sidebar key): an explicit default model (trial re-verifies it)."""
        vendor, model = b.get("vendor"), b.get("model")
        if vendor not in rooms.VENDORS:
            raise rooms.ApiError(400, "bad_vendor", f"vendor must be one of: {', '.join(rooms.VENDORS)}")
        if not isinstance(model, str) or not model.strip():
            raise rooms.ApiError(400, "bad_request", "model must be a non-empty name")
        self._model_ok(vendor, model)
        return agents.set_model(vendor, model)

    def act_member_edit(self, p: rooms.Principal, b: dict) -> dict:
        a, conn = self._member(b.get("member")), self.db()
        new = {k: self._text(b, k) for k in ("role", "description", "model")}
        if all(v is None for v in new.values()):
            raise rooms.ApiError(400, "bad_request", "member_edit needs role, description or model")
        if new["model"] is not None:
            self._model_ok(a["vendor"], new["model"])
        with db.tx(conn):
            for k, v in new.items():
                if v is not None:
                    conn.execute(f"update agents set {k}=? where id=?", (v, a["id"]))
            if new["model"] is not None:
                fam = config.family(a["vendor"], new["model"])
                conn.execute("update agents set family=? where id=?", (fam, a["id"]))
        short = lambda s: s if len(s) <= 80 else s[:79] + "…"  # noqa: E731
        changes = ", ".join(f"{k} = {short(v)}" for k, v in new.items() if v is not None)
        rooms.notice(conn, f"{a['id']} was edited: {changes}")
        return {"ok": True}

    def act_promote(self, p: rooms.Principal, b: dict) -> dict:
        """T8a H10: turn a bus message into a decision entry (operator only)."""
        mid = b.get("message_id")
        if isinstance(mid, bool) or not isinstance(mid, int):
            raise rooms.ApiError(400, "bad_request", "promote needs message_id (integer)")
        scope = b.get("scope") or "global"
        if not isinstance(scope, str):
            raise rooms.ApiError(400, "bad_request", "scope must be a string")
        conn = self.db()
        m = db.row(conn.execute("select * from messages where id=?", (mid,)))
        if m is None:
            raise rooms.ApiError(404, "unknown_message", f"no message {mid}")
        with db.tx(conn):
            eid = align.declare(conn, m["sender"], m["thread_id"], mid, "decision", m["body"],
                                scope, via=config.HUMAN)  # promoted by the user
        rooms.notice(conn, f"#{mid} 已设为决定 E{eid}")
        return {"entry": f"E{eid}"}

    def act_read(self, p: rooms.Principal, b: dict) -> dict:
        """T8a H6: move the user's read cursor for a thread forward (operator only)."""
        thread = b.get("thread")
        if not isinstance(thread, str) or not thread:
            raise rooms.ApiError(400, "bad_request", "read needs thread (string)")
        upto = b.get("upto")
        if upto is not None and (isinstance(upto, bool) or not isinstance(upto, int)):
            raise rooms.ApiError(400, "bad_request", "upto must be a message id")
        conn = self.db()
        if upto is None:
            upto = conn.execute("select coalesce(max(id), 0) from messages where thread_id=?",
                               (thread,)).fetchone()[0]
        with db.tx(conn):
            conn.execute("insert into human_reads values(?, ?) on conflict(thread_id) do update"
                         " set last_read_id=max(last_read_id, excluded.last_read_id)", (thread, upto))
            cur = conn.execute("select last_read_id from human_reads where thread_id=?", (thread,)).fetchone()[0]
        return {"ok": True, "thread": thread, "last_read_id": cur}

    def list_rooms(self) -> dict:
        """GET /v1/rooms (sidebar key): this hub's room and who is in it, for the sidebar's room list."""
        conn = self.db()
        r = db.row(conn.execute("select * from room"))
        return {"room": r and {k: r[k] for k in ("id", "name", "dir", "host", "created_at")},
                "members": [{k: m[k] for k in ("id", "vendor", "role", "online")}
                            for m in rooms.members(conn, self.cfg)]}

    def join_local(self, b: dict) -> dict:
        """POST /v1/join without a code (sidebar key checked): a sidebar on this machine joins by directory or room
        id. A named member that exists, has the same vendor and no session is taken over; bound or other: 409."""
        conn, vendor, sid = self.db(), b.get("vendor"), b.get("session_id")
        d, rid, name = b.get("dir"), b.get("room_id"), self._text(b, "name") or None
        role, desc = self._text(b, "role") or "", self._text(b, "description") or ""
        if vendor not in rooms.VENDORS or not isinstance(sid, str) or not sid:
            raise rooms.ApiError(400, "bad_request", "join needs dir or room_id, vendor and session_id")
        if d is None and rid is None:
            raise rooms.ApiError(400, "bad_request", "join needs dir or room_id")
        if d is not None and not isinstance(d, str):
            raise rooms.ApiError(400, "bad_request", "dir must be a string")
        if d is not None and not rooms.same_dir(d, self.ws):
            raise rooms.ApiError(400, "wrong_dir", f"this hub serves {self.ws}, not {d}")
        if rid is not None and rid != rooms.room_id(self.ws):
            raise rooms.ApiError(404, "unknown_room", f"this hub serves room {rooms.room_id(self.ws)}, not {rid!r}")
        if name is not None and not rooms.valid_id(name):
            raise rooms.ApiError(400, "bad_request", "name: letters, digits and '-', not 'human' or 'hub'")
        desktops = db.rows(conn.execute("select settings from agents where removed=0"))
        has_desktop = any(db.settings(a).get("desktop") for a in desktops)
        if not has_desktop and not conn.execute("select 1 from room").fetchone():
            raise rooms.ApiError(404, "no_room", "this hub has no room yet: open it with POST /v1/rooms")
        with self.join_lock:  # name checks and the insert in add_member must not interleave with another join
            rooms.room_row(conn, self.ws)
            mid = name or rooms.free_id(conn, vendor)
            self.add_member(mid, vendor, role, desc, sid)
            if role:
                with db.tx(conn):
                    conn.execute("update agents set role=? where id=?", (role, mid))
        rooms.notice(conn, f"{mid} joined the room ({vendor}{', ' + role if role else ''})"
                           + (f": {desc}" if desc else ""))
        r = rooms.room_row(conn, self.ws)
        return {"member_id": mid, "member_token": self._token_of(mid),
                "operator_token": rooms.operator_token(conn, mid),
                "room": {k: r[k] for k in ("id", "name", "dir", "host", "created_at")}}

    # rooms and invitations: no token (the caller has none yet)
    def create_room(self, b: dict) -> dict:
        conn = self.db()
        if conn.execute("select 1 from room").fetchone():
            raise rooms.ApiError(409, "room_exists", "this hub already has a room: join it with an invitation code")
        vendor, sid, d = b.get("vendor"), b.get("session_id"), b.get("dir")
        if vendor not in rooms.VENDORS or not isinstance(sid, str) or not sid or not isinstance(d, str):
            raise rooms.ApiError(400, "bad_request", "rooms needs dir, vendor (claude|opencode|dsh) and session_id")
        if not rooms.same_dir(d, self.ws):
            raise rooms.ApiError(400, "wrong_dir", f"this hub serves {self.ws}, not {d}")
        mid = b.get("member_id") or vendor
        if not rooms.valid_id(mid):
            raise rooms.ApiError(400, "bad_request", "member_id: letters, digits and '-', not 'human' or 'hub'")
        self.add_member(mid, vendor, "coordinator", b.get("description"), sid)
        with db.tx(conn):
            conn.execute("insert into room(id, name, dir, host, created_at) values(?,?,?,?,?)",
                         (rooms.room_id(self.ws), str(b.get("name") or self.ws.name), str(self.ws), mid, db.now()))
        rooms.notice(conn, f"{mid} opened the room ({vendor} sidebar)")
        self.reg_sync()
        r = rooms.room_row(conn, self.ws)
        brief_missing = conn.execute("select 1 from entries where kind='convention' and scope='global'"
                                     " and status='active' and statement like '[brief]%'").fetchone() is None
        return {"room": {k: r[k] for k in ("id", "name", "dir", "host", "created_at")}, "member_id": mid,
                "member_token": self._token_of(mid), "operator_token": rooms.operator_token(conn, mid),
                "brief_missing": brief_missing}

    def join(self, b: dict) -> dict:
        conn, code, vendor, sid = self.db(), str(b.get("code") or "").strip().upper(), b.get("vendor"), b.get("session_id")
        if not isinstance(sid, str) or not sid:
            raise rooms.ApiError(400, "bad_request", "join needs code, vendor and session_id")
        inv = db.row(conn.execute("select * from invites where code=?", (code,)))
        if inv is None:
            raise rooms.ApiError(404, "unknown_code", "no such invitation code")
        if inv["used_at"]:
            raise rooms.ApiError(409, "code_used", "this invitation code was already used")
        if inv["expires_at"] < db.now():
            raise rooms.ApiError(410, "code_expired", "this invitation code has expired: ask for a new one")
        if vendor != inv["vendor"]:
            raise rooms.ApiError(403, "vendor_mismatch", f"this code is for a {inv['vendor']} member, not {vendor}")
        mid = inv["name"] or rooms.free_id(conn, vendor)
        with db.tx(conn):  # claim the code first: two sidebars racing on one code get one member
            if not conn.execute("update invites set used_at=?, used_by=? where code=? and used_at is null",
                                (db.now(), mid, code)).rowcount:
                raise rooms.ApiError(409, "code_used", "this invitation code was already used")
        try:
            self.add_member(mid, vendor, inv["role"], inv["description"], sid)
        except rooms.ApiError:
            with db.tx(conn):  # nothing was joined: the code stays usable
                conn.execute("update invites set used_at=null, used_by=null where code=?", (code,))
            raise
        desc = f": {inv['description']}" if inv["description"] else ""
        rooms.notice(conn, f"{mid} joined the room ({vendor}{', ' + inv['role'] if inv['role'] else ''}){desc}")
        r = rooms.room_row(conn, self.ws)
        return {"member_id": mid, "member_token": self._token_of(mid), "operator_token": rooms.operator_token(conn, mid),
                "room": {k: r[k] for k in ("id", "name", "dir", "host", "created_at")}}

    def add_member(self, mid: str, vendor: str, role: str, description, session: str) -> None:
        """A sidebar's member. An existing member of the same vendor no session holds is taken over (e.g. one
        `xmuse agent add` registered); otherwise a new one: Claude and dsh live in the user's own session (the hub
        never runs them), OpenCode runs on a hub-owned server its TUI attaches to."""
        conn = self.db()
        old = db.row(conn.execute("select * from agents where id=?", (mid,)))
        if old and (old["vendor"] != vendor or old["removed"] or old["bound_session"]):
            raise rooms.ApiError(409, "member_exists", f"{mid} is already a member; pick another name")
        if old is None:
            from .init import add_agent
            settings = {"desktop": True} if vendor == "claude" else {"foreground": True} if vendor == "dsh" else {}
            try:
                add_agent(self.state, mid, vendor, role=role or "", settings=settings, description=description or "")
            except SystemExit as e:
                if vendor != "claude" or "already has a claude agent" not in str(e):
                    raise rooms.ApiError(400, "cannot_add", str(e))
                self._add_plain(mid, vendor, role, settings, description)  # the mod's tools; .mcp.json is another's
            self.ensure_driver(vendor)
        with db.tx(conn):
            conn.execute("update agents set bound_session=?, description=coalesce(?, description) where id=?",
                         (session, description or None, mid))

    def _add_plain(self, mid, vendor, role, settings, description) -> None:
        from .init import _token
        tok = _token(self.state / "tokens" / mid)
        m = config.MODELS[vendor]
        with db.tx(self.db()) as c:
            c.execute("insert into agents(id, vendor, model, family, role, settings, token_digest, created_at,"
                      " description) values(?,?,?,?,?,?,?,?,?)", (mid, vendor, m, config.family(vendor, m), role or "",
                                                                   json.dumps(settings), digest(tok), db.now(),
                                                                   description or ""))

    def ensure_driver(self, vendor: str) -> None:
        """A vendor first seen through a sidebar: its driver starts now (on the engine thread)."""
        if vendor in self.engine.drivers:
            return
        def add():
            if vendor == "opencode":
                self.engine.drivers[vendor] = OpenCodeDriver(self.engine, {})
            elif vendor == "dsh":
                self.engine.drivers[vendor] = DshDriver(self.engine, self.state, self.cfg)
        self.engine.call(add)

    def _token_of(self, mid: str) -> str:
        return (self.state / "tokens" / mid).read_text(encoding="utf-8").strip()

    # ---- process -----------------------------------------------------------------------
    def reg_sync(self) -> None:
        """This hub's entry in the machine registry (section 8.1); a registry we cannot write never stops the hub."""
        try:
            r = db.row(self.db().execute("select * from room"))
            registry.register({"room_id": rooms.room_id(self.ws), "name": r["name"] if r else self.ws.name,
                               "dir": str(self.ws), "url": f"http://127.0.0.1:{self.httpd.server_address[1]}",
                               "host": r["host"] if r else None, "pid": os.getpid(), "started_at": self.started_at})
        except (OSError, ValueError):
            log.warning("cannot write the hub registry in %s", registry.directory(), exc_info=True)

    def start(self) -> None:
        hub = self

        class H(BaseHTTPRequestHandler):
            def _sidebar(self, method: str, path: str, query: dict, body):
                try:
                    status, out = hub.sidebar(method, path, query, body, self.headers.get("authorization"),
                                              self.headers.get("x-xmuse-session") or None,
                                              self.headers.get("x-xmuse-sidebar"))
                except rooms.ApiError as e:
                    status, out = e.status, {"error": e.code, "message": e.message}
                except ToolError as e:
                    status, out = 400, {"error": e.code, "message": e.message}
                except (KeyError, TypeError, ValueError) as e:
                    status, out = 400, {"error": "bad_request", "message": repr(e)}
                if status == 204:
                    self.send_response(204)
                    self.end_headers()
                    return
                self._send(status, out)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if ("GET", u.path) not in hub.SIDEBAR:
                    return self._send(404, {"error": "not_found", "message": f"GET {u.path}"})
                self._sidebar("GET", u.path, dict(urllib.parse.parse_qsl(u.query)), {})

            def do_POST(self):
                u = urllib.parse.urlsplit(self.path)
                if ("POST", u.path) in hub.SIDEBAR:
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                    except ValueError:
                        return self._send(400, {"error": "bad_json", "message": "the body is not JSON"})
                    self._sidebar("POST", u.path, {}, body)
                    with hub.relay_cv:
                        hub.relay_cv.notify_all()
                    return
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
        threading.Thread(target=preset.loop, args=(self.preset, self.stopping, self.cfg.get("preset_tick", 2.0)),
                         daemon=True).start()
        (self.state / "hub.json").write_text(json.dumps({"port": self.httpd.server_address[1], "pid": os.getpid(),
                                                         "shell_policy": self.engine.shell_policy}), encoding="utf-8")
        try:
            registry.ensure_key()
        except OSError:
            log.warning("cannot create the sidebar key in %s", registry.directory(), exc_info=True)
        self.reg_sync()
        self.engine.kick()

    def shutdown(self) -> None:
        try:  # first: sidebars stop finding a hub that is going away (hub.json goes last: `hub stop` waits for it)
            registry.unregister(rooms.room_id(self.ws))
        except OSError:
            log.warning("cannot update the hub registry", exc_info=True)
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
        done = self.done
        signal.signal(signal.SIGTERM, lambda *_: done.set())
        signal.signal(signal.SIGINT, lambda *_: done.set())
        if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break, and what a console close turns into
            signal.signal(signal.SIGBREAK, lambda *_: done.set())
        while not done.wait(1.0):  # a timed wait: on Windows a blocked wait never returns to run signal handlers
            pass
        self.shutdown()

    def admin_shutdown(self, body: dict):
        """`xmuse hub stop` on Windows, which has no SIGTERM: the reply goes out, then serve() shuts down."""
        self.done.set()
        return {"ok": True}
