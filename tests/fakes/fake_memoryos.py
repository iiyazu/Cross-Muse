"""Fake MemoryOS 0.4.0 for hub tests: /health, /recall, /similar, /curate (profile collab) and /audit per
XMUSE2-M2-MO-CONTRACT, on a random port in a thread. Records every request in `calls` as (path, body).

Knobs: `caps` (what /health reports), `fail[path]` = "500" | "slow" | "garbage" | "empty", `curate` (callable
request -> response; default proposes nothing), `pairs` (what /similar returns).
Its /recall ranking is deterministic: more query words in the text first, then newer seq, then id. A real
MemoryOS ranks better; this one exists to make "the ranking was used" observable.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeMemoryOS:
    def __init__(self, caps=("curate", "curate.collab", "recall", "similar")):
        self.caps, self.calls, self.fail, self.pairs = list(caps), [], {}, []
        self.curate = lambda req: {"schema_version": "memoryos_curate/v1", "scope_id": req["scope_id"], "memories": []}
        self.audit = lambda req: {"schema": "memoryos_audit/v1", "flagged": [],
                                  "candidates": [i["id"] for i in req["items"]][:req["k"]],
                                  "diagnostics": {"queries": 1, "expanded": 0, "dense": False, "judged": 0,
                                                  "dropped_quotes": 0}}
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self._reply("/health", None)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                fake.calls.append((self.path, body))
                self._reply(self.path, body)

            def _reply(self, path, body):
                mode = fake.fail.get(path)
                if mode == "500":
                    return self._send(500, {"error": "boom"})
                if mode == "slow":
                    time.sleep(1.5)
                if mode == "garbage":
                    return self._send(200, {"ranked": [{"id": "E999"}]})
                if mode == "empty":
                    return self._send(200, {"ranked": [], "pairs": []})
                self._send(200, {"/health": lambda: {"status": "ok", "version": "0.4.0", "capabilities": fake.caps},
                                 "/recall": lambda: fake.recall(body), "/curate": lambda: fake.curate(body),
                                 "/audit": lambda: fake.audit(body),
                                 "/similar": lambda: {"schema": "memoryos_similar/v1", "pairs": fake.pairs,
                                                      "diagnostics": {"dense": True}}}[path]())

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        ThreadingHTTPServer.daemon_threads = True
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def paths(self):
        return [p for p, _ in self.calls]

    def recall(self, req):
        words = set(req["query"].lower().split())
        score = lambda i: (-len(words & set(i["text"].lower().split())), -i["seq"], i["id"])  # noqa: E731
        ranked = sorted(req["items"], key=score)[:req["k"]]
        return {"schema": "memoryos_recall/v1", "ranked": [{"id": i["id"], "score": 1.0, "why": ["bm25"]} for i in ranked],
                "dropped": [i["id"] for i in req["items"] if i not in ranked], "tokens_used": 0,
                "diagnostics": {"dense": False, "token_estimator": "fake"}}

    def close(self):
        self.httpd.shutdown()
