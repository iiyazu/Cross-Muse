#!/usr/bin/env python3
"""Tests for replay_mo.py + fake_mo_server.py (standard library only).

    pytest tests/test_replay_mo.py
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

EXP = Path(__file__).resolve().parents[1] / "experiments"
sys.path.insert(0, str(EXP))
import fake_mo_server as fake  # noqa: E402
import replay_mo as rmo  # noqa: E402

KIND = "message"


def msg(i, body="body", kind=KIND, sender="opencode-1", thread="#task", at=None, why=None):
    return {"id": i, "thread_id": thread, "sender": sender, "kind": kind, "body": f"{body} {i}", "why": why,
            "mentions": "[]", "chain_id": 1, "depth": 0, "turn_id": 1, "idem_key": None,
            "created_at": 100.0 + i if at is None else at}


def entry(i, kind="decision", scope="thread:#task", author="opencode-1", status="active", seq=None, at=None,
          statement=None):
    t = 100.0 + i if at is None else at
    return {"id": i, "kind": kind, "scope": scope, "thread_id": "#task",
            "statement": statement or f"convention {i}: something cross-cutting", "refs": "[1]", "author": author,
            "status": status, "supersedes": None, "assignee": None, "depends_on": None, "resolves": None,
            "valid_at": t, "recorded_at": t, "invalid_at": None, "seq": i if seq is None else seq}


def ev(seq, eid, op, at):
    return {"seq": seq, "entry_id": eid, "op": op, "at": at}


def synthetic(seed="minisql", n=9, handoff=None, kind=KIND, entries=None, events=None, close=None):
    """A run shaped like the real recordings: `n` qualifying messages (plus `close` kind=done noise) and entries."""
    msgs = [msg(i + 1, kind=kind) for i in range(n)]
    msgs[0]["sender"] = "human"                                       # the /recall query comes from here
    msgs.append(msg(n + 1, kind="done", sender="dsh-1"))              # not in MSGS: must not count as new
    msgs.append(msg(n + 2, kind="done", sender="dsh-1"))
    if handoff:
        msgs.append(msg(n + 3, kind="handoff", sender="opencode-1", why='{"what": "hand over", "why": "x"}'))
    ents = entries if entries is not None else [entry(1, at=101.0, seq=1), entry(2, at=102.0, author="dsh-1", seq=2)]
    evs = events if events is not None else [ev(e["id"], e["id"], "add", e["recorded_at"]) for e in ents]
    meta = {"run": f"{seed}-X-1", "seed": seed, "group": "C", "agents": [["opencode-1", "opencode", None],
                                                                          ["dsh-1", "dsh", None]],
            "first_message_id": 1, "rot": {"injected": False}}
    return {"name": f"{seed}-X-1", "dir": "mem", "meta": meta, "messages": msgs, "entries": ents, "events": evs}


def write_run(root: Path, run: dict) -> Path:
    d = root / run["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({**run["meta"], "run": run["name"]}), encoding="utf-8")
    (d / "log.json").write_text(json.dumps({"agents": [], "messages": run["messages"]}), encoding="utf-8")
    (d / "entries.json").write_text(json.dumps({"entries": run["entries"], "events": run["events"]}),
                                   encoding="utf-8")
    return d


class Server:
    """The fake service on a random port, in-process (no subprocess, nothing outside 127.0.0.1)."""

    def __init__(self, requests=None):
        self.httpd = fake.serve(0, EXP, requests)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()   # release the socket, otherwise unittest reports ResourceWarning


def call(*argv) -> int:
    try:
        return rmo.main(list(argv))
    except SystemExit as e:  # main is the CLI: a fatal error shows up as a SystemExit here
        return e.code if isinstance(e.code, int) else 1


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="replaymo-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        fake.Handler.calls.clear()   # the fake records requests in a class attribute
        self.results = self.tmp / "results"

    def build(self, run, out=None, root=None):
        """One run per test: a stale run folder from an earlier test would keep its old curate-*.json files."""
        root = root or self.results
        shutil.rmtree(root, ignore_errors=True)
        write_run(root, run)
        out = out or self.results.parent / "out"
        self.assertEqual(call("build", str(root), "--out", str(out)), 0)
        return out

    # ---- build determinism -------------------------------------------------
    def test_build_is_byte_identical(self):
        run = synthetic()
        a, b = self.tmp / "a", self.tmp / "b"
        self.build(run, out=a, root=self.tmp / "ra")
        self.build(run, out=b, root=self.tmp / "rb")
        files = sorted(p.relative_to(a).as_posix() for p in a.rglob("*.json"))
        self.assertTrue(files)
        for f in files:
            self.assertEqual((a / f).read_bytes(), (b / f).read_bytes(), f"{f} differs between builds")
        self.assertEqual(json.loads((a / "index.json").read_text(encoding="utf-8"))["curate_per_run"][run["name"]], 1)

    # ---- trigger rules ----------------------------------------------------
    def test_trigger_after_eight_messages(self):
        out = self.build(synthetic(n=7))
        self.assertEqual(len(list((out / "minisql-X-1").glob("curate-*.json"))), 0, "7 new messages must not trigger")
        out = self.build(synthetic(n=8), out=self.tmp / "out8", root=self.tmp / "r8")
        idx = json.loads((out / "index.json").read_text(encoding="utf-8"))["requests"]
        cur = [r for r in idx if r["type"] == "curate"]
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]["reason"], "every8")
        self.assertEqual(cur[0]["message_id"], 8)

    def test_trigger_on_handoff(self):
        out = self.build(synthetic(n=3, handoff=True))
        idx = json.loads((out / "index.json").read_text(encoding="utf-8"))["requests"]
        cur = [r for r in idx if r["type"] == "curate"]
        self.assertEqual([r["reason"] for r in cur], ["handoff"])
        self.assertEqual(cur[0]["message_id"], 6)

    def test_no_trigger_without_new_messages(self):
        run = synthetic(n=2, kind="done")   # done is not in MSGS
        out = self.build(run)
        self.assertEqual(list((out / run["name"]).glob("curate-*.json")), [])
        self.assertTrue((out / run["name"] / "recall.json").exists())

    # ---- active reconstruction -------------------------------------------
    def test_active_drops_superseded_entry(self):
        ents = [entry(1, at=101.0, seq=1), entry(2, at=103.0, seq=2, author="dsh-1"),
                entry(3, at=115.0, seq=3, statement="decision 3 supersedes 2")]
        evs = [ev(1, 1, "add", 101.0), ev(2, 2, "add", 103.0), ev(3, 3, "add", 115.0), ev(4, 2, "supersede", 116.0)]
        ents[1]["status"] = "superseded"
        run = synthetic(n=20, entries=ents, events=evs)
        out = self.build(run)
        reqs = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((out / run["name"]).glob("curate-*.json"),
                                key=lambda p: int(p.stem.split("-")[1]))]
        self.assertEqual(len(reqs), 2)
        self.assertEqual([e["id"] for e in reqs[0]["active"]], ["E2", "E1"], "both entries exist before the supersede")
        self.assertEqual([e["id"] for e in reqs[1]["active"]], ["E3", "E1"], "E2 must be gone after the supersede")
        self.assertNotIn("E2", reqs[1]["_replay"]["active_ids"])
        self.assertEqual(reqs[1]["window"][-1]["kind"], "message")
        self.assertEqual(reqs[1]["max_repairs"], 1)
        self.assertEqual(reqs[1]["active"][0]["topic_key"], "e3")
        self.assertEqual(reqs[1]["schema"], "memoryos_curate/v1")
        self.assertEqual(reqs[1]["profile"], "collab")

    def test_handoff_why_is_appended_like_the_hub(self):
        out = self.build(synthetic(n=3, handoff=True))
        req = json.loads((out / "minisql-X-1" / "curate-1.json").read_text(encoding="utf-8"))
        ho = [w for w in req["window"] if w["kind"] == "handoff"][0]
        self.assertIn("what: hand over", ho["text"])
        self.assertEqual(ho["id"], "m6")
        self.assertEqual(ho["type"], "message")

    # ---- validate ---------------------------------------------------------
    def test_validate_rejects_assignment_in_active(self):
        run = synthetic(entries=[entry(1, kind="assignment", at=101.0, seq=1)], events=[ev(1, 1, "add", 101.0)])
        req = rmo.curate_request(run, "#task", run["messages"][:8], [], [run["entries"][0]], 110.0)
        self.assertIn("E1", [a["id"] for a in req["active"]])
        with self.assertRaises(rmo.BadRequest):
            rmo.validate(req, "curate")

    def test_validate_rejects_oversized_window_and_items(self):
        req = rmo.curate_request(synthetic(), "#task", [rmo.act(m) for m in synthetic(n=40)["messages"]], [], [], 150.0)
        self.assertEqual(len(req["window"]), 32)
        self.assertLessEqual(len(req["window"]), 32)
        req["window"] = req["window"] + [req["window"][0]]
        with self.assertRaises(rmo.BadRequest) as cm:
            rmo.validate(req, "curate")
        self.assertIn("window", str(cm.exception))
        bad = {"schema": "memoryos_recall/v1", "query": "", "hints": {}, "budget_tokens": 100, "k": 3,
               "items": [{"id": "E1", "text": "x" * 2001, "seq": 1}]}
        with self.assertRaises(rmo.BadRequest):
            rmo.validate(bad, "recall")

    def test_validate_accepts_the_real_build(self):
        out = self.build(synthetic(n=20, handoff=True))
        idx = json.loads((out / "index.json").read_text(encoding="utf-8"))["requests"]
        self.assertEqual({r["type"] for r in idx}, {"curate", "recall", "similar"})
        for r in idx:   # build() validates every request it writes; re-validate the files on disk
            rmo.validate(json.loads((out / r["file"]).read_text(encoding="utf-8")), r["type"])

    def _first(self, kind):
        out = self.build(synthetic(n=20, entries=[entry(1, kind="decision", at=101.0, seq=1)],
                                   events=[ev(1, 1, "add", 101.0)]))
        idx = json.loads((out / "index.json").read_text(encoding="utf-8"))["requests"]
        f = [r for r in idx if r["type"] == kind][0]["file"]
        return json.loads((out / f).read_text(encoding="utf-8"))

    def test_recall_request_shape(self):
        req = self._first("recall")
        self.assertEqual(req["schema"], "memoryos_recall/v1")
        self.assertEqual(req["k"], max(3, len(req["items"]) // 2))
        self.assertEqual(req["items"][0]["kind"], "decision")
        self.assertIn("body", req["query"])            # query = last human message
        self.assertNotIn("assignment", [i["kind"] for i in req["items"]])
        sim = self._first("similar")
        self.assertEqual(sim["threshold"], 0.88)
        self.assertTrue(all(set(i) == {"id", "text"} for i in sim["items"]))

    # ---- send + score -----------------------------------------------------
    def test_send_and_score_end_to_end(self):
        ents = [entry(1, kind="assumption", at=101.0, seq=1, statement="values are int or str"),
                entry(2, at=105.0, author="dsh-1", seq=2, statement="values are int or str")]
        evs = [ev(1, 1, "add", 101.0), ev(2, 2, "add", 105.0)]
        # seq order and id order differ on purpose: the /recall comparison must show different survivors
        # one label per entry that the checklist really matches; "tsv output" avoids the "tab" inside "stable"
        labels = ["tsv output", "stable output", "stable output", "stable output"]
        for i, text in enumerate(labels, start=3):
            ents.append(entry(i, at=100.0 + i, seq=(7 - i), statement=f"convention {i}: {text}"))
            evs.append(ev(i, i, "add", 100.0 + i))
        run = synthetic(n=20, handoff=True, entries=ents, events=evs)
        out = self.build(run)
        srv = Server(out)
        self.addCleanup(srv.close)
        self.assertEqual(call("send", str(out), "--url", srv.url, "--max-calls", "40"), 0)
        self.assertEqual(len(fake.Handler.calls), 5)
        self.assertTrue(all("_replay" not in body for _, body in fake.Handler.calls),
                        "offline metadata must not reach the service")
        self.assertIn("_replay", json.loads((out / run["name"] / "curate-1.json").read_text(encoding="utf-8")))
        for name in ("curate-1", "curate-2", "curate-3", "recall", "similar"):
            self.assertTrue((out / run["name"] / f"{name}.resp.json").exists(), name)
        report = self.score(out)
        r = report["runs"][0]
        self.assertEqual(r["requests"]["curate"], 3)
        self.assertEqual(r["requests"]["similar"], 1)
        self.assertGreaterEqual(r["declaration"]["labels"], 1)
        # /curate re-proposes the value-types convention the duplicate active entry already carries, and its
        # checklist proposal; "sort-stable" is declared by the agents but never proposed, so it stays declared-only
        self.assertEqual(r["declaration"]["curate_covered"], sorted({"values-int-str-none", "rot-tsv"}))
        self.assertEqual(r["declaration"]["curate_new"], [])            # the agents had declared both already
        self.assertIn("null-ordering", r["declaration"]["still_missing"])   # nothing proposed or declared nulls
        self.assertGreaterEqual(r["noise"]["proposals"], 3)
        self.assertGreaterEqual(r["noise"]["duplicates_of_active"], 1)
        self.assertEqual(len(r["recall"]["compared"]), 1)
        cmp = r["recall"]["compared"][0]
        self.assertEqual(len(r["recall"]["memoryos_only"]), len(cmp["kept_by_memoryos"]) - len(cmp["shared"]))
        self.assertEqual(len(r["recall"]["newest_only"]), len(cmp["kept_by_newest"]) - len(cmp["shared"]))
        self.assertEqual(set(r["recall"]["memoryos_only"]) & set(r["recall"]["newest_only"]), set())
        self.assertGreaterEqual(r["cost"]["curate"][0]["usage"]["output_tokens"], 1)
        self.assertEqual(r["cost"]["unmetered_attempts"], 0)
        self.assertTrue((out / "report.md").read_text(encoding="utf-8").startswith("# MemoryOS offline replay report"))
        # the response files carry status and seconds so an interrupted run can be diagnosed
        resp = json.loads((out / run["name"] / "recall.resp.json").read_text(encoding="utf-8"))
        self.assertEqual(resp["status"], 200)
        self.assertIsInstance(resp["seconds"], float)
        self.assertGreater(len(resp["body"]["ranked"]), 0)

    def test_send_is_resumable_and_health_gated(self):
        out = self.build(synthetic(n=20))
        srv = Server(out)
        self.addCleanup(srv.close)
        call("send", str(out), "--url", srv.url, "--max-calls", "1")
        answered = len(list((out / "minisql-X-1").glob("*.resp.json")))
        self.assertEqual((len(fake.Handler.calls), answered), (1, 1))
        left = len(json.loads((out / "index.json").read_text(encoding="utf-8"))["requests"]) - answered
        fake.Handler.calls.clear()
        call("send", str(out), "--url", srv.url, "--max-calls", "40")
        self.assertEqual(len(fake.Handler.calls), left, "only requests without a response file are sent again")
        fake.Handler.calls.clear()
        call("send", str(out), "--url", srv.url, "--only", "recall")
        self.assertEqual([p for p, _ in fake.Handler.calls], [])   # every response file is already there

    def test_max_calls_limits_the_spend(self):
        out = self.build(synthetic(n=20))
        srv = Server(out)
        self.addCleanup(srv.close)
        fake.Handler.calls.clear()
        self.assertEqual(call("send", str(out), "--url", srv.url, "--max-calls", "2"), 0)
        self.assertEqual(len(fake.Handler.calls), 2)
        self.assertEqual(len(list((out / "minisql-X-1").glob("*.resp.json"))), 2)

    def test_send_reports_errors_without_stopping(self):
        out = self.build(synthetic(n=20))
        rc = call("send", str(out), "--url", "http://127.0.0.1:1", "--max-calls", "2")
        self.assertEqual(rc, 2, "/health on a dead port is fatal: nothing to spend budget on")
        self.assertFalse(list((out / "minisql-X-1").glob("*.resp.json")))

    def score(self, out, results=None) -> dict:
        self.assertEqual(call("score", str(out), "--results", str(results or self.results),
                              "--checklist", str(EXP)), 0)
        return json.loads((out / "report.json").read_text(encoding="utf-8"))

    # ---- real data --------------------------------------------------------
    def test_real_runs_build_send_score(self):
        results = EXP.parents[1] / "data" / "results"
        if not (results / "minisql-C-1" / "meta.json").exists():
            self.skipTest("data/results not present")
        runs = [d for d in sorted(results.iterdir()) if rmo.is_run(d)]
        out = self.tmp / "real"
        self.assertEqual(call("build", *[str(d) for d in runs], "--out", str(out)), 0)
        idx = json.loads((out / "index.json").read_text(encoding="utf-8"))
        requests = idx["requests"]
        self.assertEqual(set(idx["curate_per_run"]), {r["run"] for r in requests})
        self.assertGreater(sum(idx["curate_per_run"].values()), 0)
        self.assertEqual(len(idx["curate_per_run"]), len(runs), "one output folder per run, even with no trigger")
        for r in requests:
            req = json.loads((out / r["file"]).read_text(encoding="utf-8"))
            rmo.validate(req, r["type"])
            if r["type"] == "curate":
                self.assertNotIn("assignment", [a["kind"] for a in req["active"]])
                self.assertTrue(1 <= len(req["window"]) <= 32)
        srv = Server(out)
        self.addCleanup(srv.close)
        self.assertEqual(call("send", str(out), "--url", srv.url, "--max-calls", "40"), 0)
        report = self.score(out, results=results)
        self.assertEqual(len(report["runs"]), len(runs))
        self.assertGreater(report["totals"]["proposals"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
