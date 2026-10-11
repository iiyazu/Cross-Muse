"""Fake OpenCode 2.x server for hub tests: the v2 API surface the hub uses, replaying recorded SSE.

Each POST /prompt consumes one plan step: {"fixture", "calls": [[tool, args], ...], "as", "result":
"succeeded"|"failed"|"hang", "sleep"}. Events are the recorded ones with the sessionID rewritten,
framed by inbox.enqueued (carrying the prompt's metadata) / execution.started / inbox.delivered and a
session.execution.* end event, as the real server does.
"""
import base64
import json
import queue
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIX = Path(__file__).resolve().parent.parent / "fixtures"
FRAME = {"session.inbox.enqueued", "session.inbox.delivered", "session.execution.started",
         "session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"}


class FakeOpenCode:
    def __init__(self, state: Path | None = None, port: int = 0, password: str | None = None,
                 record: Path | None = None):
        """port/password/record: the subprocess form (fake_opencode_serve.py) binds the port the hub chose, checks
        the hub's Basic auth, and appends every prompt and tool result to `record` (JSON lines)."""
        self.state, self.plan, self.n, self.record = state, [], 0, record
        self.subs: list[queue.Queue] = []
        self.sessions, self.prompts, self.replies, self.interrupts = {}, [], [], []
        self.stop_flags: dict[str, threading.Event] = {}
        self.messages: dict[str, list] = {}
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _authed(self) -> bool:
                if password is None:
                    return True
                want = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()
                if self.headers.get("authorization") == want:
                    return True
                self._json(401, {"error": "unauthorized"})
                return False

            def do_GET(self):
                if not self._authed():
                    return
                if self.path == "/api/session":
                    return self._json(200, {"data": [{"id": s} for s in fake.sessions]})
                if self.path == "/api/model":
                    return self._json(200, {"data": [{"providerID": "opencode-go", "id": "muse-spark-1.3-contributor"}]})
                m = re.fullmatch(r"/api/session/([^/?]+)/message(\?.*)?", self.path)
                if m:  # the v2 shape, one page; messages are whatever a test put in fake.messages[sid]
                    return self._json(200, {"data": fake.messages.get(m.group(1), []),
                                            "cursor": {"previous": None, "next": None}})
                if self.path != "/api/event":
                    return self._json(404, {})
                q = queue.Queue()
                fake.subs.append(q)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                q.put({"type": "server.connected", "data": {}})
                try:
                    while True:
                        ev = q.get()
                        if ev is None:
                            return
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    fake.subs.remove(q)

            def do_POST(self):
                if not self._authed():
                    return
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if self.path == "/api/session":
                    sid = f"ses_fake{len(fake.sessions) + 1}"
                    fake.sessions[sid] = body
                    return self._json(200, {"data": {"id": sid}})
                m = re.fullmatch(r"/api/session/([^/]+)/(prompt|interrupt|permission/([^/]+)/reply)", self.path)
                if not m:
                    return self._json(404, {})
                sid = m.group(1)
                if m.group(2) == "prompt":
                    fake.prompts.append({"session": sid, **body})
                    fake._record({"prompt": sid, "for": ((body.get("metadata") or {}).get("xmuse") or {}).get("agent")})
                    threading.Thread(target=fake._run, args=(sid, body), daemon=True).start()
                    return self._json(200, {"data": {"id": "msg_x", "sessionID": sid}})
                if m.group(2) == "interrupt":
                    fake.interrupts.append(sid)
                    fake.stop_flags.setdefault(sid, threading.Event()).set()
                    return self._json(200, {"interrupted": True})
                fake.replies.append({"session": sid, "request": m.group(3), **body})
                fake.emit({"type": "permission.replied", "data": {"sessionID": sid, "requestID": m.group(3),
                                                                   "reply": body["decision"]}})
                return self._json(200, {})

            def _json(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        for q in list(self.subs):
            q.put(None)
        self.httpd.shutdown()

    def emit(self, ev: dict):
        for q in list(self.subs):
            q.put(ev)

    def _frame(self, sid, typ, **data):
        self.emit({"type": typ, "data": {"sessionID": sid, **data}})

    def _run(self, sid: str, body: dict):
        step = self.plan[self.n] if self.n < len(self.plan) else {}
        self.n += 1
        stop = self.stop_flags[sid] = threading.Event()
        item = {"type": "user", "payload": {"text": body["text"], **({"metadata": body["metadata"]}
                                                                     if "metadata" in body else {})},
                "delivery": body.get("delivery")}
        self._frame(sid, "session.inbox.enqueued", inboxID="msg_in", item=item)
        self._frame(sid, "session.execution.started")
        self._frame(sid, "session.inbox.delivered", inboxID="msg_in")
        for line in (FIX / step.get("fixture", "oc-chat.events.jsonl")).open(encoding="utf-8"):
            ev = json.loads(line)
            if ev.get("type") in FRAME:
                continue
            if "sessionID" in (ev.get("data") or {}):
                ev["data"]["sessionID"] = sid
            self.emit(ev)
        for name, args in step.get("calls", []):
            self.tool(step["as"], name, args)
        end = time.time() + step.get("sleep", 0)
        while time.time() < end and not stop.is_set():
            time.sleep(0.02)
        if step.get("result") == "hang":
            stop.wait(30)
        if stop.is_set():
            return self._frame(sid, "session.execution.interrupted")
        if step.get("result") == "failed":
            return self._frame(sid, "session.execution.failed", error={"message": "provider error"})
        self._frame(sid, "session.execution.succeeded")

    def human(self, sid: str, seconds: float = 0.3):
        """A human types in the TUI: enqueued without metadata.xmuse, one execution, then idle."""
        def go():
            self._frame(sid, "session.viewed", idle=0)
            self._frame(sid, "session.inbox.enqueued", inboxID="msg_h",
                        item={"type": "user", "payload": {"text": "human here"}, "delivery": "steer"})
            self._frame(sid, "session.execution.started")
            self._frame(sid, "session.inbox.delivered", inboxID="msg_h")
            time.sleep(seconds)
            self._frame(sid, "session.execution.succeeded")
        threading.Thread(target=go, daemon=True).start()

    def ask_permission(self, sid: str, rid: str = "per_1", command: str = "git push origin main"):
        self.emit({"type": "permission.asked", "data": {"id": rid, "sessionID": sid, "action": "shell",
                                                         "resources": [command], "save": ["git push *"]}})

    def tool(self, agent: str, name: str, args: dict):
        port = json.loads((self.state / "hub.json").read_text(encoding="utf-8"))["port"]
        token = (self.state / "tokens" / agent).read_text(encoding="utf-8").strip()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tools/{name}", method="POST",
                                     data=json.dumps({"args": args}).encode(),
                                     headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self._record({"tool": name, "as": agent, "result": out.get("result")})
        return out

    def _record(self, obj: dict):
        if self.record is not None:
            with self.record.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")
