#!/usr/bin/env python3
"""M2b experiment runner: one scenario, one run.   usage: experiments/run.py <scenario> <run-no>

A scenario (experiments/scenarios/<scenario>.env, KEY=VALUE lines) names a seed task, an agent line-up and a
group (README section 4). The runner rebuilds the workspace under $E2E_WS_ROOT (default
/mnt/c/Users/$USER/xmuse-exp: dsh needs a native C:\\ path, and never the home directory itself), switches the
hub into the group's mode, sends the task, injects the rot message at its moment, waits for the hub to go
quiet and collects everything into experiments/results/<scenario>-<n>/ (hub state: experiments/state-*/).

Scenario keys: SEED | SEEDS (group L: tasks in order, same hub and same sessions), GROUP (A|B|C|L), MODE (run|review),
IMPL, REVIEW (one id, or two separated by a comma), GOAL (optional), AGENTS ("id:vendor[:model] ..."; a claude agent
MUST carry a model, there is no fallback to the default Opus), ROT (1|2|none), ROT_AT (review_request |
review_reply | turn:N), ROT_MATCH (regex over active entries; the newest match is superseded by the rot decision),
MAX_CHAIN_WAKES, TIMEOUT, SETTLE, BUG (MODE=review: planted bug number), HUB_CFG (JSON merged into config.json),
MEMORYOS (on: start a MemoryOS service for this run and point the hub at it; anything else: off).
Environment AGENTS / E2E_WS_ROOT override the scenario.
MemoryOS env: MEMORYOS_CMD (default `memoryos api --host 127.0.0.1 --port <free port>`; use {port} for the port),
MEMORYOS_DIR (required when MEMORYOS=on), plus MEMORYOS_EMBEDDING_PROVIDER=fastembed, HF_HUB_OFFLINE=1,
MEMORYOS_CURATE_TIMEOUT_S=200 forced; FASTEMBED_CACHE_PATH, MEMORYOS_LLM_PROVIDER, OPENCODE_API_KEY inherited.
"""
import atexit
import json
import os
import re
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EXP = Path(__file__).resolve().parent
REPO = EXP.parent
XMUSE = [str(REPO / "bin" / "xmuse")]
GROUPS = {"A": ("all", "off"), "B": ("mention", "off"), "C": ("mention", "on"), "L": ("mention", "on")}
PKG = {"ledger": "ledger", "minisql": "minisql", "pipeline": "pipeline"}
VENDORS = ("claude", "opencode", "dsh")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def memoryos_cmd(port: int) -> list[str]:
    raw = os.environ.get("MEMORYOS_CMD")
    if not raw:
        return ["memoryos", "api", "--host", "127.0.0.1", "--port", str(port)]
    parts = shlex.split(raw)
    if "{port}" in raw:
        return [a.replace("{port}", str(port)) for a in parts]
    if "--port" not in parts:
        return [*parts, "--port", str(port)]
    return parts


def memoryos_env() -> dict:
    d = os.environ.get("MEMORYOS_DIR")
    if not d:
        raise SystemExit("MEMORYOS=on needs MEMORYOS_DIR set to your MemoryOS checkout "
                         "(the directory where `uv sync --frozen --no-dev --extra remote --extra full-local` was run)")
    return {**os.environ, "MEMORYOS_EMBEDDING_PROVIDER": "fastembed",
            "HF_HUB_OFFLINE": "1", "MEMORYOS_CURATE_TIMEOUT_S": "200"}


def parse_env(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = " ".join(shlex.split(v))
    return out


def parse_agents(spec: str) -> list[tuple[str, str, str | None]]:
    out = []
    for a in spec.split():
        aid, vendor, *model = a.split(":", 2)
        if vendor not in VENDORS:
            raise SystemExit(f"AGENTS: {a!r}: vendor must be one of {', '.join(VENDORS)}")
        if vendor == "claude" and not (model and model[0]):
            raise SystemExit(f"AGENTS: {a!r}: a claude agent needs an explicit model (id:claude:<model>), "
                             "e.g. claude-haiku-5-5 or claude-sonnet-5-5; the default Opus is not allowed here")
        out.append((aid, vendor, model[0] if model else None))
    return out


def rot_text(seed: str, n: int) -> str:
    """The injected message: the blockquote under '## ROT-<n>' in rot/<seed>.md."""
    lines, on = [], False
    for ln in (EXP / "rot" / f"{seed}.md").read_text().splitlines():
        if ln.startswith("## "):
            on = ln.startswith(f"## ROT-{n}")
        elif on and ln.startswith(">"):
            lines.append(ln[1:].strip())
    if not lines:
        raise SystemExit(f"no ROT-{n} blockquote in rot/{seed}.md")
    return "\n".join(lines)


def parse_counts(text: str) -> dict:
    """unittest -v output -> {test name: ok|fail}, plus totals."""
    found = list(re.finditer(r"^(\w+) \(([^)]*)\)(?:\n.*?)? \.\.\. (ok|FAIL|ERROR)", text, re.M))
    tests = {m[1]: "ok" if m[3] == "ok" else "fail" for m in found}
    ids = {(m[2].split(".", 1)[-1] if "." in m[2] else m[1]): "ok" if m[3] == "ok" else "fail" for m in found}  # Class.method
    return {"tests": tests, "ids": ids, "passed": sum(v == "ok" for v in tests.values()),
            "failed": sum(v == "fail" for v in tests.values())}


def match_entry(listing: str, pattern: str) -> str | None:
    """Newest active decision-like entry from `xmuse align list` whose line matches the regex."""
    ids = [m[1] for ln in listing.splitlines()
           if (m := re.match(r"(E\d+) \[(decision|convention|assumption|lesson)\] active ", ln)) and re.search(pattern, ln, re.I)]
    return ids[-1] if ids else None


def sh(cmd, cwd=None, env=None, timeout=600, check=True) -> str:
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(map(str, cmd))[:200]} failed:\n{r.stdout[-800:]}{r.stderr[-800:]}")
    return r.stdout + r.stderr


def git(ws: Path, *args, check=True) -> str:
    return sh(["git", "-c", "user.name=exp", "-c", "user.email=exp@local", *args], cwd=ws, check=check)


def scrub(src: str, module: str) -> str:
    """Neutral module docstring and no comment-only lines (applied to every module alike)."""
    src = re.sub(r'\A""".*?"""\n', f'"""{module}."""\n', src, count=1, flags=re.S)
    return "".join(ln for ln in src.splitlines(True) if not ln.lstrip().startswith("#"))


def add_seed(ws: Path, seed: str, sub: str, review_bug: str | None = None) -> None:
    """Copy seeds/<seed> to ws/<sub>; review mode: the finished reference implementation with the planted bug."""
    dst = ws / sub if sub else ws
    shutil.copytree(EXP / "seeds" / seed, dst, dirs_exist_ok=True)
    if review_bug:
        shutil.rmtree(dst / PKG[seed], ignore_errors=True)
        shutil.copytree(EXP / "reference" / seed / PKG[seed], dst / PKG[seed])
        shutil.copytree(EXP / "planted" / seed / f"bug-{review_bug}", dst, dirs_exist_ok=True)
        for f in (dst / PKG[seed]).glob("*.py"):  # the planted/reference files narrate the bug; the reviewer must not see that
            f.write_text(scrub(f.read_text(), f.stem))
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", f"seed {seed}" + (f" + planted bug-{review_bug}" if review_bug else ""))


def task_text(sc: dict, seed: str, sub: str, thread: str) -> str:
    impl, review = sc["IMPL"], sc["REVIEW"]
    where = f"Work in the directory {sub}/ of this repo (it holds the {seed} project). " if sub else ""
    if sc.get("MODE") == "review":
        return (f"Task: {where}the repo already contains a finished {seed} implementation. {review} reviews it against SPEC.md: "
                "run the tests, read every module and probe every SPEC rule with edge cases of your own (in a throwaway "
                "script, not committed), then report concrete findings in " + thread + ": file, function, what is wrong "
                "and why, or an explicit statement that a module is correct. Do not fix anything, do not push or merge.")
    goal = sc.get("GOAL") or (f"complete the {seed} project per README.md and SPEC.md: replace every NotImplementedError "
                              "in the package with a working implementation; tests/test_public.py must pass")
    revs = review.split(",")
    run = f"(run: {'cd ' + sub + ' && ' if sub else ''}python3 -m unittest discover -s tests)"
    who = (f"{revs[0]} and {revs[1]} both review" if len(revs) > 1 else f"{review} reviews")
    roles = (f"Roles: {impl} implements; {who}. When the implementation is ready, {impl} sends a review_request in "
             f"{thread} that mentions {' and '.join(revs)}. Each reviewer checks the code against SPEC.md, runs the tests, "
             "and probes every SPEC rule with edge cases of its own (in a throwaway script, not committed), then replies "
             f"in {thread} with concrete findings or an explicit approval. {impl} fixes every finding and asks again "
             f"until all reviewers approve. Then {impl} reports the result to human.")
    return f"Task: {where}{goal} {run}. {roles} Do not push, merge or touch files outside this repo."


class Run:
    def __init__(self, scenario: str, n: str):
        self.sc = {**parse_env(EXP / "scenarios" / f"{scenario}.env")}
        if os.environ.get("AGENTS"):
            self.sc["AGENTS"] = os.environ["AGENTS"]
        sc = self.sc
        self.name = f"{scenario}-{n}"
        self.group = sc["GROUP"]
        self.agents = parse_agents(sc.get("AGENTS", "opencode-1:opencode dsh-1:dsh"))
        ids = {a[0] for a in self.agents}
        if self.group not in GROUPS or not {sc["IMPL"], *sc["REVIEW"].split(",")} <= ids:
            raise SystemExit(f"{scenario}: GROUP must be A|B|C|L and IMPL/REVIEW must be in AGENTS ({', '.join(sorted(ids))})")
        self.seeds = sc["SEEDS"].split() if self.group == "L" else [sc["SEED"]]
        self.root = Path(os.environ.get("E2E_WS_ROOT") or f"/mnt/c/Users/{os.environ['USER']}/xmuse-exp")
        self.ws, self.res = self.root / f"ws-{self.name}", EXP / "results" / self.name
        self.state_root = EXP / f"state-{self.name}"
        self.env = {**os.environ, "XMUSE_STATE_ROOT": str(self.state_root)}
        self.db = None
        self.mo_proc, self.mo_log, self.mo_url, self.mo_caps = None, None, "", []

    def x(self, *args, check=True) -> str:
        return sh([*XMUSE, *map(str, args)], cwd=self.ws, env=self.env, check=check)

    def q(self, sql, *args) -> list:
        if self.db is None:
            self.db = sqlite3.connect(f"file:{next(self.state_root.glob('*/hub.db'))}?mode=ro", uri=True, timeout=30)
        return self.db.execute(sql, args).fetchall()

    def quiet(self) -> bool:
        return not self.q("select 1 from turns where state='running'") and not self.q(
            "select 1 from deliveries d join agents a on a.id=d.recipient"
            " where d.state='queued' and d.wake=1 and a.paused=0")

    def mo_enabled(self) -> bool:
        return self.sc.get("MEMORYOS") == "on"

    def mo_start(self) -> None:
        if not self.mo_enabled():
            return
        env = memoryos_env()
        mdir = env["MEMORYOS_DIR"]
        port = free_port()
        cmd = memoryos_cmd(port)
        self.res.mkdir(parents=True, exist_ok=True)
        self.mo_log = (self.res / "memoryos.log").open("wb")
        self.mo_proc = subprocess.Popen(cmd, cwd=mdir, env=env, stdout=self.mo_log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
        self.mo_url = f"http://127.0.0.1:{port}"
        atexit.register(self.mo_stop)
        caps, last, deadline = [], "", time.time() + 120
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.mo_url + "/health", timeout=5) as r:
                    body = json.loads(r.read())
                if isinstance(body, dict) and body.get("status") == "ok":
                    c = body.get("capabilities")
                    caps = list(c) if isinstance(c, (list, tuple)) else []
                    break
                last = f"bad /health: {str(body)[:200]}"
            except Exception as e:
                last = repr(e)[:200]
            if self.mo_proc.poll() is not None:
                raise SystemExit(f"MemoryOS exited during startup; see {self.res / 'memoryos.log'}")
            time.sleep(1)
        else:
            self.mo_stop()
            raise SystemExit(f"MemoryOS did not become ready in 120s ({last}); see {self.res / 'memoryos.log'}")
        self.mo_caps = caps

    def mo_stop(self) -> None:
        p, self.mo_proc = getattr(self, "mo_proc", None), None
        if not p:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=10)
        except Exception:
            pass
        finally:
            try:
                if getattr(self, "mo_log", None):
                    self.mo_log.close()
            except Exception:
                pass
            self.mo_log = None

    def mo_parse_hub_log(self, hublog: Path) -> list:
        calls, usages = [], []
        if not hublog.exists():
            return calls
        call_re = re.compile(r"memoryos-call (\{.*\})")
        use_re = re.compile(r"curate (\S+) usage (\{.*\})")
        for line in hublog.read_text(errors="replace").splitlines():
            m = call_re.search(line)
            if m:
                try:
                    o = json.loads(m.group(1))
                    calls.append({"path": o.get("path"), "ms": o.get("ms"), "ok": bool(o.get("ok")),
                                  "usage": None, "raw": line[-500:]})
                except Exception:
                    continue
                continue
            m2 = use_re.search(line)
            if m2:
                try:
                    usages.append(json.loads(m2.group(2)))
                except Exception:
                    pass
        ui = 0
        for c in calls:
            if c["path"] == "/curate" and ui < len(usages):
                c["usage"] = usages[ui]
                ui += 1
        for u in usages[ui:]:
            calls.append({"path": "/curate", "ms": None, "ok": True, "usage": u, "raw": "curate usage"})
        return calls

    def mo_collect(self, out: Path) -> dict:
        if not self.mo_enabled():
            return {}
        calls = self.mo_parse_hub_log(out / "hub.log")
        (out / "memoryos-calls.json").write_text(json.dumps(calls, indent=1, ensure_ascii=False))
        proposals, conflicts = 0, 0
        try:
            ej = json.loads((out / "entries.json").read_text())
            proposals = sum(1 for e in ej.get("entries", [])
                            if e.get("author") == "curate" and e.get("status") == "proposed")
        except Exception:
            pass
        try:
            lj = json.loads((out / "log.json").read_text())
            conflicts = sum(1 for m in lj.get("messages", [])
                            if m.get("kind") == "notice" and isinstance(m.get("body"), str) and "curate:" in m["body"])
        except Exception:
            pass
        return {"proposals": proposals, "conflicts": conflicts}

    # ---- setup ---------------------------------------------------------------------
    def setup(self) -> None:
        for d in (self.ws, self.res, self.state_root):
            shutil.rmtree(d, ignore_errors=True)
        self.res.mkdir(parents=True)
        self.mo_start()
        self.ws.mkdir(parents=True)
        git(self.ws, "init", "-q")
        review = self.sc.get("BUG") if self.sc.get("MODE") == "review" else None
        add_seed(self.ws, self.seeds[0], self.seeds[0] if self.group == "L" else "", review)
        self.x("init", ".")
        cfgf = next(self.state_root.glob("*/config.json"))
        wake, alignment = GROUPS[self.group]
        cfg = {**json.loads(cfgf.read_text()), "wake": wake, "alignment": alignment,
               "max_chain_wakes": int(self.sc.get("MAX_CHAIN_WAKES", 20)), **json.loads(self.sc.get("HUB_CFG", "{}"))}
        if self.mo_enabled():
            cfg["memoryos_url"] = self.mo_url
        cfgf.write_text(json.dumps(cfg, indent=2))
        for aid, vendor, model in self.agents:
            self.x("agent", "add", aid, "--vendor", vendor, *(["--model", model] if model else []))
        self.x("hub", "start")

    # ---- one task ---------------------------------------------------------------------
    def stage(self, seed: str, idx: int) -> dict:
        sc, L = self.sc, self.group == "L"
        sub, thread = (seed if L else ""), (f"#task-{seed}" if L else "#task")
        out = self.res / seed if L else self.res
        out.mkdir(exist_ok=True)
        first_turn = (self.q("select coalesce(max(id),0) from turns")[0][0]) + 1
        first_msg = (self.q("select coalesce(max(id),0) from messages")[0][0]) + 1
        base = git(self.ws, "rev-parse", "HEAD").strip()
        task = task_text(sc, seed, sub, thread)
        (out / "task.txt").write_text(task)
        start = time.time()
        self.x("send", thread, task, "--mention", sc["IMPL"] if sc.get("MODE") != "review" else sc["REVIEW"].split(",")[0])
        rot = {"injected": False}
        rot_n = sc.get("ROT", "1" if sc.get("MODE") != "review" else "none")
        at, timeout, settle = sc.get("ROT_AT", "review_reply"), float(sc.get("TIMEOUT", 3600)), float(sc.get("SETTLE", 30))
        revs, calm, rc = sc["REVIEW"].split(","), None, 1
        while time.time() - start < timeout:
            if rot_n != "none" and not rot["injected"] and self.rot_due(at, revs, first_msg, first_turn):
                rot = self.inject(seed, int(rot_n), thread)
            if self.quiet():
                calm = calm or time.time()
                if time.time() - calm >= settle:
                    rc = 0
                    break
            else:
                calm = None
            time.sleep(3)
        elapsed = int(time.time() - start)
        rot["expected"] = rot_n != "none"
        self.collect(seed, sub, out, base, first_turn, first_msg, elapsed, rc, rot)
        return {"seed": seed, "seconds": elapsed, "quiet": rc == 0, "rot": rot}

    def rot_due(self, at: str, revs: list, first_msg: int, first_turn: int) -> bool:
        if at.startswith("turn:"):
            return self.q("select count(*) from turns where id>=? and state!='running'", first_turn)[0][0] >= int(at[5:])
        rr = self.q("select min(id) from messages where kind='review_request' and id>=?", first_msg)[0][0]
        if at == "review_request" or rr is None:
            return rr is not None
        return bool(self.q(f"select 1 from messages where id>? and kind!='notice' and sender in ({','.join('?' * len(revs))})",
                           rr, *revs))

    def inject(self, seed: str, n: int, thread: str) -> dict:
        """The rot message, from human: a decision (superseding the matching entry) in C/L, a plain message in A/B.
        Every group mentions the implementer and the reviewers, as a person announcing a change would, so delivery
        is equal across groups and what differs is only how the change is carried (alignment entry or not)."""
        text, kind = rot_text(seed, n), "decision" if self.group in ("C", "L") else "message"
        ment = [a for m in [self.sc["IMPL"], *self.sc["REVIEW"].split(",")] for a in ("--mention", m)]
        sup = match_entry(self.x("align", "list"), self.sc["ROT_MATCH"]) if kind == "decision" and self.sc.get("ROT_MATCH") else None
        out = self.x("send", thread, text, "--kind", kind, *ment, *(["--supersedes", sup] if sup else []), check=False)
        if sup and "error" in out:  # the entry changed under us; send without
            sup, out = None, self.x("send", thread, text, "--kind", kind, *ment)
        return {"injected": True, "n": n, "kind": kind, "supersedes": sup, "text": text, "at": time.time(), "reply": out.strip()}

    # ---- collect ---------------------------------------------------------------------
    def collect(self, seed, sub, out, base, first_turn, first_msg, elapsed, rc, rot) -> None:
        w = self.ws / sub if sub else self.ws
        full = json.loads(self.x("log", "--json"))
        (out / "log-full.json").write_text(json.dumps(full, indent=1, ensure_ascii=False))
        stage_log = {**full, "messages": [m for m in full["messages"] if m["id"] >= first_msg],
                     "turns": [t for t in full["turns"] if t["id"] >= first_turn]}
        (out / "log.json").write_text(json.dumps(stage_log, indent=1, ensure_ascii=False))
        (out / "log.txt").write_text(self.x("log"))
        (out / "usage.txt").write_text(self.x("usage"))
        (out / "status.json").write_text(self.x("hub", "status"))
        self.dump_tables(out, first_turn)
        (out / "align.txt").write_text(self.x("align", "list", "--all"))
        log = next(self.state_root.glob("*/logs/hub.log"), None)
        if log:
            shutil.copy(log, out / "hub.log")
        mo_stats = self.mo_collect(out)
        git(self.ws, "add", "-A")
        (out / "git-diff-stat.txt").write_text(git(self.ws, "diff", "--cached", "--stat", base, "--", sub or "."))
        (out / "git-status.txt").write_text(git(self.ws, "status", "--short"))
        if self.sc.get("MODE") == "review":
            revs = self.sc["REVIEW"].split(",")
            (out / "review.md").write_text("\n\n".join(
                f"## #{m['id']} {m['sender']} -> {m['thread_id']} [{m['kind']}]\n{m['body']}" for m in stage_log["messages"]
                if m["sender"] in revs and m["kind"] != "notice"))
        else:
            self.run_tests(seed, w, out)
            r =subprocess.run([sys.executable, str(REPO / "e2e" / "check.py"), str(out), self.sc["IMPL"], self.sc["REVIEW"],
                                (out / "public.status").read_text(), (out / "hidden.status").read_text(), str(elapsed),
                                str(rc)], capture_output=True, text=True)
            (out / "summary.json").write_text(r.stdout)
        meta = {"run": self.name, "seed": seed, "scenario": self.sc, "group": self.group, "agents": self.agents,
                "first_turn_id": first_turn, "first_message_id": first_msg, "seconds": elapsed, "quiet": rc == 0,
                "rot": rot}
        if self.mo_enabled():
            meta["memoryos"] = {"enabled": True, "url": self.mo_url, "capabilities": self.mo_caps, **mo_stats}
        (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))

    def dump_tables(self, out: Path, first_turn: int) -> None:
        db = sqlite3.connect(f"file:{next(self.state_root.glob('*/hub.db'))}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        dump = lambda sql, *a: [dict(r) for r in db.execute(sql, a)]  # noqa: E731
        (out / "turns.json").write_text(json.dumps(dump(
            "select t.*, u.mode, u.input, u.cache_read, u.cache_write, u.output, u.context, u.calls from turns t"
            " left join usage u on u.turn_id=t.id where t.id>=? order by t.id", first_turn), indent=1))
        (out / "entries.json").write_text(json.dumps({
            "entries": dump("select * from entries order by id"),
            "events": dump("select * from entry_events order by seq")}, indent=1, ensure_ascii=False))
        db.close()

    def run_tests(self, seed: str, w: Path, out: Path) -> None:
        def run(args) -> tuple[str, str]:
            r = subprocess.run(["python3", "-m", "unittest", *args], cwd=w, capture_output=True,
                               text=True, timeout=300, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            return ("pass" if r.returncode == 0 else "fail"), r.stdout + r.stderr
        st, txt = run(["discover", "-s", "tests"])
        (out / "tests-public.txt").write_text(txt)
        (out / "public.status").write_text(st)
        hid = w / "tests" / f"test_hidden_{seed}.py"
        shutil.copy(EXP / "hidden" / hid.name, hid)
        st, txt = run(["discover", "-s", "tests", "-p", "test_hidden_*.py", "-v"])
        hid.unlink()
        (out / "tests-hidden.txt").write_text(txt)
        (out / "hidden-tests.json").write_text(json.dumps(parse_counts(txt), indent=1))  # per case: metrics.py drops the rot-affected ones
        (out / "hidden.status").write_text(st)
        rt = w / f"post_rot_test_{seed}.py"
        shutil.copy(EXP / "rot" / rt.name, rt)
        _, txt = run(["discover", "-s", ".", "-p", "post_rot_test_*.py", "-v"])
        rt.unlink()
        (out / "tests-rot.txt").write_text(txt)
        (out / "rot-tests.json").write_text(json.dumps(parse_counts(txt), indent=1))

    def go(self) -> None:
        t0 = time.time()
        try:
            self.setup()
            stages = []
            for i, seed in enumerate(self.seeds):
                if i:  # long session: same hub, same sessions; the finished task's thread is closed, the next seed added
                    git(self.ws, "add", "-A")
                    git(self.ws, "commit", "-qm", f"end of {self.seeds[i - 1]}", check=False)
                    self.x("thread", "close", f"#task-{self.seeds[i - 1]}")
                    add_seed(self.ws, seed, seed)
                stages.append(self.stage(seed, i))
        finally:
            try:
                self.x("hub", "stop", check=False)
            except Exception:
                pass
            self.mo_stop()
        self.db = None
        (self.res / "run.json").write_text(json.dumps({"run": self.name, "group": self.group, "stages": stages,
                                                       "seconds": int(time.time() - t0),
                                                       "memoryos": {"enabled": self.mo_enabled(),
                                                                    "url": self.mo_url,
                                                                    "capabilities": self.mo_caps} if self.mo_enabled() else {"enabled": False}}, indent=1, default=str))
        print(json.dumps({k: v for k, v in stages[-1].items() if k != "rot"} | {"rot_injected": stages[-1]["rot"]["injected"],
                                                                                 "results": str(self.res)}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    Run(sys.argv[1], sys.argv[2]).go()
