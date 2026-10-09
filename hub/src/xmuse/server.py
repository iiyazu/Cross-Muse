"""xmuse-hub process: loopback HTTP for the shim, hooks and the CLI; runs the engine thread.

Auth: every agent holds a locally issued bearer token (tokens/<agent>, 0600; only its sha256 is in
hub.db); the CLI uses tokens/_admin and speaks as 'human'. Simplified from v1 plugin grants +
pairing: one workspace, one user, no remote hosts, so no pairing codes, scopes or expiry.
"""
import hashlib
import hmac
import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, db, mail
from .adapters.claude import ClaudeDriver
from .adapters.opencode import OpenCodeDriver, Server
from .engine import Engine
from .tools import ToolError, validate


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Hub:
    def __init__(self, state: Path, claude_bin: str | None = None, oc_base: str | None = None):
        self.state, self.cfg = state, config.load(state)
        claude_bin = claude_bin or self.cfg.get("claude_bin", "claude")
        self.ws = Path(self.cfg["workspace"])
        self.db = db.Pool(state / "hub.db")
        db.init(state / "hub.db").close()
        self.admin = digest((state / "tokens" / "_admin").read_text().strip())
        self.engine = Engine(state, self.cfg, self.db, {}, self.ws)
        self.engine.drivers["claude"] = ClaudeDriver(self.engine, self.db, claude_bin)
        if self.db().execute("select 1 from agents where vendor='opencode'").fetchone():
            srv = Server(self.ws, state, base=oc_base)
            if oc_base is None:
                srv.start()
            self.engine.drivers["opencode"] = OpenCodeDriver(self.engine, srv)

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
    def tool(self, agent: str, name: str, args: dict):
        args = validate(name, args)
        conn = self.db()
        if name == "xmuse_send":
            out = mail.send(conn, self.cfg, agent, args["to"], args["body"], args.get("kind", "message"),
                            args.get("mentions"), args.get("why"))
            self.engine.kick()
            return {"id": out["id"], "thread": out["thread_id"], "woken": out.get("woken", []),
                    **({"duplicate": True} if out.get("duplicate") else {})}
        if name == "xmuse_inbox":
            return mail.inbox(conn, agent, args.get("unread_only", True))
        if name == "xmuse_ack":
            return {"acked": mail.ack(conn, agent, args["ids"], args.get("outcome"))}
        if name == "xmuse_thread":
            return mail.thread(conn, agent, args["id"], args.get("query"), args.get("limit", 20))
        if name == "xmuse_context":
            return mail.context(conn, agent, args.get("topic"))
        if name == "xmuse_done":
            return mail.done(conn, agent, args["summary"], args["next"])
        return mail.whoami(conn, agent, str(self.ws))

    def hook(self, agent: str, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        if self.engine.drivers[a["vendor"]].on_hook(a, body["event"], body):
            self.engine.kick()
        return {"ok": True}

    def register(self, agent: str, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (agent,)))
        self.engine.drivers[a["vendor"]].register_shim(a, body)
        self.engine.kick()
        return {"ok": True}

    def admin_send(self, body: dict):
        out = mail.send(self.db(), self.cfg, config.HUMAN, body["to"], body["body"], body.get("kind", "message"),
                        body.get("mentions"), body.get("why"), body.get("idem"))
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

    def admin_approve(self, body: dict):
        conn = self.db()
        a = db.row(conn.execute("select * from approvals where id=?", (body["id"],)))
        if a is None:
            raise ToolError("unknown_approval", f"no approval {body['id']}")
        self.engine.drivers["opencode"].approve(a["vendor_session"], a["id"], body["decision"])
        with db.tx(conn):
            conn.execute("update approvals set state='decided', decision=?, decided_at=? where id=?",
                         (body["decision"], db.now(), a["id"]))
        return {"ok": True}

    def admin_attach(self, body: dict):
        a = db.row(self.db().execute("select * from agents where id=?", (body["agent"],)))
        s = self.db().execute("select vendor_session from sessions where agent_id=? and state='current'",
                              (a["id"],)).fetchone()
        return {"command": self.engine.drivers[a["vendor"]].attach_command(a, s and s[0])}

    def route(self, method: str, path: str, caller: str, body: dict):
        if path.startswith("/v1/tools/") and caller != config.HUMAN:
            return self.tool(caller, path.rsplit("/", 1)[1], body.get("args", {}))
        if path == "/v1/hooks/claude" and caller != config.HUMAN:
            return self.hook(caller, body)
        if path == "/v1/shim/register" and caller != config.HUMAN:
            return self.register(caller, body)
        if path.startswith("/v1/admin/") and caller == config.HUMAN:
            fn = getattr(self, "admin_" + path.rsplit("/", 1)[1], None)
            if fn:
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
                    self._send(200, {"result": hub.route("POST", self.path, caller, body)})
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
        self.stopping = threading.Event()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.loop = threading.Thread(target=self.engine.run_forever, args=(self.stopping,), daemon=True)
        self.loop.start()
        (self.state / "hub.json").write_text(json.dumps({"port": self.httpd.server_address[1], "pid": os.getpid()}))
        self.engine.kick()

    def shutdown(self) -> None:
        self.stopping.set()
        self.loop.join(10)
        self.httpd.shutdown()
        for d in self.engine.drivers.values():
            d.close()
        (self.state / "hub.json").unlink(missing_ok=True)

    def serve(self) -> None:
        self.start()
        done = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: done.set())
        signal.signal(signal.SIGINT, lambda *_: done.set())
        done.wait()
        self.shutdown()
