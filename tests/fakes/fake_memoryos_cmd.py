#!/usr/bin/env python3
"""Fake MemoryOS process for experiments/run.py MEMORYOS tests.

Uses tests/fakes/fake_memoryos.py for request behaviour, but listens on the
port the runner passes on the command line (so it can serve as MEMORYOS_CMD).

Usage: fake_memoryos_cmd.py --port <port> [--host 127.0.0.1]
"""
import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_memoryos import FakeMemoryOS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    args, _ = ap.parse_known_args()
    # Reuse the fake's behaviour (recall ranking, empty curate, caps).
    tmp = FakeMemoryOS()
    fake_caps, fake_calls = tmp.caps, tmp.calls
    fake_recall, fake_curate = tmp.recall, tmp.curate
    try:
        tmp.close()
    except Exception:
        pass
    fake = type("F", (), {})()
    fake.caps, fake.calls, fake.fail, fake.pairs = fake_caps, fake_calls, {}, []
    fake.recall, fake.curate = fake_recall, fake_curate

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self._reply("/health", None)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            fake.calls.append((self.path, body))
            self._reply(self.path, body)

        def _reply(self, path, body):
            self._send(200, {"/health": lambda: {"status": "ok", "version": "0.4.0",
                                                 "capabilities": fake.caps},
                             "/recall": lambda: fake.recall(body),
                             "/curate": lambda: fake.curate(body),
                             "/similar": lambda: {"schema": "memoryos_similar/v1", "pairs": [],
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
    httpd = ThreadingHTTPServer((args.host, args.port), H)
    print(f"fake-memoryos on {args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
