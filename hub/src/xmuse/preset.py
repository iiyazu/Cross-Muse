"""Orchestration preset plan-split-integrate (design XMUSE2-TEAM-PRESET §3 and §8; T13).

A planner P reads the task and splits it; executors implement their parts in parallel, each in its own git worktree
on branch xmuse/<id>; P integrates on the main workspace. The hub drives the phases:

  P0 plan (P)  ->  P1 parallel work (executors; P answers questions)  ->  P2 integrate (P)
  ->  P3 targeted fixes (owners fix, the hub merges, P re-checks; at most `rounds` rounds)  ->  F

- Every phase has a time limit; on timeout the hub stops the phase's agents and moves on, recording an event.
  A run also has a total limit. P without a valid plan at the end of P0 fails the run (the hub never splits).
- A phase ends early when its agents call xmuse_done with that phase's stage (plan, part, integrated, fix).
- Snapshots S-E<k>, S-int, S-fix-<k> and F are `git diff --binary <base> <commit>` patches with their times.
- File ownership comes from the plan file P writes (PLAN_FILE): executor changes outside their globs are recorded
  as violations, never blocked.
- A failed turn (crash) of a phase agent is retried once (a hub message wakes it again); a second failure degrades:
  an executor's part goes to the other executor, or is skipped; P failing twice ends the run (P0) or the phase.
- Executors stay paused while it is not their phase, so P's handoffs reach them when P1 starts.

The orchestrator only polls hub.db (tick), so it never runs inside the engine thread.
"""
import fnmatch
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

from . import config, db, mail
from .config import HUB
from .tools import ToolError

log = logging.getLogger("xmuse.preset")

PRESET = "plan-split-integrate"
LIMITS = {"P0": 600, "P1": 1500, "P2": 600, "P3": 480, "rounds": 2, "total": 3600}
PLAN_FILE = ".xmuse-plan.json"
WT_DIR = ".xmuse-wt"
THREAD = "#team"
# generated, per-workspace files an agent needs in its worktree (all but AGENTS.md / CLAUDE.md are git-excluded)
COPY = [".xmuse.json", "AGENTS.md", "CLAUDE.md", ".mcp.json", "opencode.json", ".claude", ".opencode", ".agents",
        ".dsh"]
NOT_ADD = [":(exclude)AGENTS.md", ":(exclude)CLAUDE.md"]  # generated, untracked: never committed by the hub
NOT_WORK = [*NOT_ADD, f":(exclude){PLAN_FILE}"]  # never part of a snapshot (the plan file is git-excluded already:
# naming an ignored path in `git add` is an error, so it is only listed for diffs)
GIT_ID = ["-c", "user.name=xmuse-hub", "-c", "user.email=hub@xmuse.invalid"]


def git(cwd: Path, *args, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} in {cwd}: {r.stderr.strip() or r.stdout.strip()}")
    return r


class Orchestrator:
    def __init__(self, hub):
        self.hub, self.db, self.engine, self.ws, self.state = hub, hub.db, hub.engine, hub.ws, hub.state

    @property
    def cfg(self) -> dict:
        return self.hub.cfg

    # ---- start ---------------------------------------------------------------------------------------------
    def start(self, task: str, planner: str, executors: list[str], limits: dict | None = None,
              preset: str = PRESET) -> dict:
        if preset != PRESET:
            raise ToolError("invalid_arguments", f"preset must be {PRESET}")
        conn = self.db()
        roster = mail.agents(conn)
        bad = [a for a in [planner, *executors] if a not in roster]
        if bad or not executors or planner in executors or len(set(executors)) != len(executors):
            raise ToolError("invalid_arguments", f"planner and executors must be distinct agents of this workspace "
                                                 f"(unknown: {bad})")
        if conn.execute("select 1 from preset_runs where state='running'").fetchone():
            raise ToolError("invalid_arguments", "a preset run is already running in this workspace")
        lim = {**LIMITS, **(limits or {})}
        base = git(self.ws, "rev-parse", "HEAD").stdout.strip()
        branch = git(self.ws, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        from .init import _exclude
        _exclude(self.ws, [f"{WT_DIR}/", PLAN_FILE])
        wts = {}
        for a in executors:
            wt = self.ws / WT_DIR / a
            if wt.exists():
                git(self.ws, "worktree", "remove", "--force", str(wt), check=False)
            git(self.ws, "worktree", "add", "-q", "-B", f"xmuse/{a}", str(wt), base)
            for name in COPY:
                src = self.ws / name
                if src.is_dir():
                    shutil.copytree(src, wt / name, dirs_exist_ok=True)
                elif src.exists():
                    shutil.copy2(src, wt / name)
            if roster[a]["vendor"] == "claude":  # the workspace's .mcp.json may belong to another Claude member
                from .adapters import claude
                claude.write_config(self.ws, {**roster[a], "settings": json.dumps(
                    {**db.settings(roster[a]), "cwd": str(wt)})}, self.state)
            wts[a] = str(wt)
        with db.tx(conn):
            for a in executors:  # executors wait for P1; their worktree is their cwd from the first turn on
                s = db.settings(roster[a])
                conn.execute("update agents set paused=1, settings=? where id=?",
                              (json.dumps({**s, "cwd": wts[a]}), a))
            rid = conn.execute(
                "insert into preset_runs(preset, task, planner, executors, base, branch, phase, phase_at, limits, data,"
                " created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                (preset, task, planner, json.dumps(executors), base, branch, "P0", db.now(), json.dumps(lim),
                 json.dumps({"worktrees": wts, "retries": {}, "degraded": [], "handled": [], "snapshots": [],
                             "takeover": {}}), db.now())).lastrowid
        self.event(rid, "P0", "start", {"base": base, "branch": branch, "planner": planner, "executors": executors,
                                        "limits": lim, "info_layer": self.cfg.get("info_layer", "on")})
        self.say(rid, [planner], self.p0_text(task, planner, executors, lim))
        return {"run": rid, "base": base, "worktrees": wts}

    # ---- texts (what the hub tells the agents) ---------------------------------------------------------------
    def info(self) -> bool:
        return config.info_on(self.cfg)

    def p0_text(self, task: str, planner: str, executors: list[str], lim: dict) -> str:
        ex = ", ".join(executors)
        owners = ", ".join(f'"{e}": ["<glob>", ...]' for e in executors)
        if self.info():
            dispatch = ("record each cross-module convention (interfaces, data formats, naming) as kind=decision with "
                        "scope module:<name> (or all); hand each executor its part with kind=handoff (mention it, "
                        "scope=module:<the modules it owns>, depends_on if it must wait, Why-First fields filled)")
        else:
            dispatch = (f"send ONE message in {THREAD} that mentions {ex} with the split, who owns which files, the "
                        "conventions they must share and the acceptance checklist")
        return (f"[plan-split-integrate] You are the planner of a team. Executors: {ex}; each works in its own git "
                f"worktree on branch xmuse/<id>. You work in the main workspace and never write feature code there "
                f"(only merge conflicts and wiring).\n\nTask:\n{task}\n\n"
                f"Phase P0 (limit {lim['P0'] // 60} min): read the task and the code, then\n"
                f"1. write {PLAN_FILE} in the workspace root: {{\"owners\": {{{owners}}}, \"acceptance\": [\"...\"]}}; "
                f"every file an executor may change must match one of its globs;\n"
                f"2. {dispatch};\n"
                f"3. call xmuse_done(stage=\"plan\", next=\"{executors[0]}\").\n"
                f"The executors start when you call xmuse_done(stage=\"plan\"); while they work you are woken for "
                f"their questions.")

    def p1_text(self, run: dict, a: str, globs: list[str]) -> str:
        ask = ("send the planner a kind=question" if self.info() else "message the planner")
        return (f"[plan-split-integrate] Phase P1 (limit {self.limits(run)['P1'] // 60} min). You are executor {a}: "
                f"you work in {self.wt(run, a)} on branch xmuse/{a} (the hub commits it). Change only your files "
                f"({', '.join(globs) or 'see the plan'}); to touch another file, first {ask}. When your part is done "
                f"and your own checks pass, call xmuse_done(stage=\"part\", next=\"{run['planner']}\") with what you did, "
                f"why, what is left and how you verified it.")

    # ---- helpers ---------------------------------------------------------------------------------------------
    def limits(self, run: dict) -> dict:
        return json.loads(run["limits"])

    def data(self, run: dict) -> dict:
        return json.loads(run["data"])

    def wt(self, run: dict, a: str) -> Path:
        return Path(self.data(run)["worktrees"][a])

    def event(self, rid: int, phase: str | None, kind: str, detail: dict | None = None) -> None:
        with db.tx(self.db()) as c:
            c.execute("insert into preset_events(run_id, at, phase, kind, detail) values(?,?,?,?,?)",
                      (rid, db.now(), phase, kind, json.dumps(detail or {})))
        log.info("preset run %s %s %s %s", rid, phase, kind, detail or "")

    def say(self, rid: int, to: list[str], text: str) -> None:
        """A hub message in the team thread that wakes `to`."""
        mail.send(self.db(), self.cfg, HUB, THREAD, text, mentions=to)
        self.engine.kick()

    def update(self, rid: int, **cols) -> None:
        if "data" in cols:
            cols["data"] = json.dumps(cols["data"])
        with db.tx(self.db()) as c:
            c.execute(f"update preset_runs set {', '.join(k + '=?' for k in cols)} where id=?", (*cols.values(), rid))

    def pause(self, agents: list[str], paused: bool) -> None:
        with db.tx(self.db()) as c:
            c.executemany("update agents set paused=? where id=?", [(int(paused), a) for a in agents])
        self.engine.kick()

    def stop(self, agents: list[str]) -> None:
        for a in agents:
            self.engine.call(self.engine.stop, a, None)

    def staged(self, run: dict, agent: str, stage: str) -> dict | None:
        """The agent's xmuse_done(stage=...) since the current phase began (or since it took over a part)."""
        since = max(run["phase_at"], self.data(run).get("took_over_at", {}).get(agent, 0))
        return db.row(self.db().execute(
            "select * from messages where sender=? and kind='done' and stage=? and created_at>=? order by id desc",
            (agent, stage, since)))

    def idle(self, agents: list[str]) -> bool:
        """No running turn: an agent that called xmuse_done finishes its turn before the hub commits its work."""
        return not agents or self.db().execute(
            f"select 1 from turns where state='running' and agent_id in ({','.join('?' * len(agents))})",
            agents).fetchone() is None

    def finished(self, run: dict, agents: list[str], stage: str) -> bool:
        return all(self.staged(run, a, stage) for a in agents) and self.idle(agents)

    def active(self, run: dict) -> list[str]:
        gone = set(self.data(run)["degraded"])
        return [a for a in json.loads(run["executors"]) if a not in gone]

    def plan(self) -> dict | None:
        try:
            p = json.loads((self.ws / PLAN_FILE).read_text())
        except (OSError, ValueError):
            return None
        owners = p.get("owners") if isinstance(p, dict) else None
        if not isinstance(owners, dict) or not all(isinstance(v, list) and all(isinstance(g, str) for g in v)
                                                   for v in owners.values()):
            return None
        return p

    def commit(self, cwd: Path, label: str) -> str:
        git(cwd, "add", "-A", "--", ".", *NOT_ADD)
        if git(cwd, "diff", "--cached", "--quiet", check=False).returncode:
            git(cwd, "commit", "-q", "--no-verify", "-m", label)
        return git(cwd, "rev-parse", "HEAD").stdout.strip()

    def snapshot(self, run: dict, name: str, commit: str) -> None:
        d = self.state / "runs" / f"preset-{run['id']}"
        d.mkdir(parents=True, exist_ok=True)
        patch = git(self.ws, "diff", "--binary", run["base"], commit, "--", ".", *NOT_WORK).stdout
        (d / f"{name}.patch").write_text(patch)
        files = [f for f in git(self.ws, "diff", "--name-only", run["base"], commit, "--", ".", *NOT_WORK)
                 .stdout.splitlines() if f]
        snap = {"name": name, "at": db.now(), "phase": run["phase"], "commit": commit, "files": files,
                "patch": str(d / f"{name}.patch")}
        data = self.data(run)
        data["snapshots"].append(snap)
        self.update(run["id"], data=data)
        run["data"] = json.dumps(data)
        self.event(run["id"], run["phase"], "snapshot", {k: snap[k] for k in ("name", "commit", "files")})

    def violations(self, run: dict, a: str, commit: str) -> None:
        plan, data = self.plan() or {}, self.data(run)
        globs = list((plan.get("owners") or {}).get(a, []))
        for other in data["takeover"].get(a, []):
            globs += (plan.get("owners") or {}).get(other, [])
        changed = [f for f in git(self.ws, "diff", "--name-only", run["base"], commit, "--", ".", *NOT_WORK)
                   .stdout.splitlines() if f]
        out = [f for f in changed if not any(fnmatch.fnmatch(f, g) for g in globs)]
        for f in out:
            self.event(run["id"], run["phase"], "violation", {"agent": a, "file": f, "owned": globs})

    def merge(self, run: dict, agents: list[str]) -> dict:
        """Merge the executors' branches into the main workspace. A conflicting merge is aborted and left to P."""
        self.commit(self.ws, f"xmuse: main before merging ({run['phase']})")
        out = {}
        for a in agents:
            r = git(self.ws, "merge", "--no-ff", "--no-edit", "-m", f"xmuse: merge xmuse/{a}", f"xmuse/{a}",
                    check=False)
            if r.returncode == 0:
                out[a] = "merged"
                continue
            files = git(self.ws, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
            git(self.ws, "merge", "--abort", check=False)
            out[a] = {"conflict": files}
            self.event(run["id"], run["phase"], "merge_conflict", {"agent": a, "files": files})
        return out

    def merge_text(self, merged: dict) -> str:
        lines = []
        for a, r in merged.items():
            lines.append(f"- xmuse/{a}: merged" if r == "merged" else
                         f"- xmuse/{a}: CONFLICT in {', '.join(r['conflict'])}; run `git merge xmuse/{a}` in the "
                         f"workspace, resolve, commit")
        return "\n".join(lines) or "- nothing to merge"

    def go(self, run: dict, phase: str, **extra) -> dict:
        self.update(run["id"], phase=phase, phase_at=db.now(), **extra)
        self.event(run["id"], phase, "phase", extra or None)
        return db.row(self.db().execute("select * from preset_runs where id=?", (run["id"],)))

    # ---- the state machine ---------------------------------------------------------------------------------------
    def tick(self) -> None:
        for run in db.rows(self.db().execute("select * from preset_runs where state='running'")):
            try:
                self._tick(run)
            except Exception as e:  # never let one bad step kill the loop; the run records it
                log.exception("preset run %s", run["id"])
                self.event(run["id"], run["phase"], "error", {"error": repr(e)})

    def _tick(self, run: dict) -> None:
        lim, now = self.limits(run), db.now()
        if now - run["created_at"] > lim["total"] and run["phase"] != "F":
            self.event(run["id"], run["phase"], "total_timeout", {"limit": lim["total"]})
            return self.finish(run, stop=True)
        phase = run["phase"]
        late = now - run["phase_at"] > lim.get(phase[:2], lim["P3"])
        if phase == "P0":
            return self.p0(run, late)
        if phase == "P1":
            return self.p1(run, late)
        if phase in ("P2", "P3int"):
            return self.integrated(run, late)
        if phase == "P3fix":
            return self.p3fix(run, late)

    def crashes(self, run: dict, agents: list[str]) -> list[str]:
        """Handle failed turns of `agents` in this phase; returns those degraded now."""
        data, out = self.data(run), []
        for t in db.rows(self.db().execute(
                f"select * from turns where state='failed' and started_at>=? and agent_id in"
                f" ({','.join('?' * len(agents))}) order by id", (run["phase_at"], *agents))):
            if t["id"] in data["handled"]:
                continue
            data["handled"].append(t["id"])
            a = t["agent_id"]
            n = data["retries"][a] = data["retries"].get(a, 0) + 1
            if n == 1:
                self.update(run["id"], data=data)
                self.event(run["id"], run["phase"], "crash_retry", {"agent": a, "turn": t["id"], "error": t["error"]})
                self.say(run["id"], [a], f"[plan-split-integrate] Your last turn failed ({(t['error'] or '')[:200]}). "
                                         "Continue where you left off.")
            elif a not in data["degraded"]:
                data["degraded"].append(a)
                out.append(a)
                self.event(run["id"], run["phase"], "degraded", {"agent": a, "turn": t["id"], "error": t["error"]})
        self.update(run["id"], data=data)
        run["data"] = json.dumps(data)
        return out

    def p0(self, run: dict, late: bool) -> None:
        if self.crashes(run, [run["planner"]]):
            self.event(run["id"], "P0", "failed", {"why": "planner failed twice"})
            return self.fail(run)
        done = self.staged(run, run["planner"], "plan")
        plan = self.plan()
        if done and plan is None and not self.data(run).get("asked_plan"):
            data = self.data(run)
            data["asked_plan"] = True
            self.update(run["id"], data=data)
            self.event(run["id"], "P0", "plan_invalid", {})
            self.say(run["id"], [run["planner"]], f"[plan-split-integrate] {PLAN_FILE} is missing or not "
                                                  "{\"owners\": {<executor>: [<glob>...]}, \"acceptance\": [...]}; "
                                                  "write it, then call xmuse_done(stage=\"plan\") again.")
            return
        if done and plan is not None and done["id"] >= self._asked(run) and self.idle([run["planner"]]):
            self.event(run["id"], "P0", "plan", {"owners": plan["owners"], "acceptance": plan.get("acceptance", [])})
            run = self.go(run, "P1")
            ex = self.active(run)
            for a in ex:
                self.say(run["id"], [a], self.p1_text(run, a, plan["owners"].get(a, [])))
            self.pause(ex, False)
            return
        if late:
            self.event(run["id"], "P0", "phase_timeout", {"plan": plan is not None})
            self.stop([run["planner"]])
            self.event(run["id"], "P0", "failed", {"why": "no plan within the P0 limit"})
            self.fail(run)

    def _asked(self, run: dict) -> int:
        """Message id of the hub's 'plan invalid' note (a later done counts); 0 when never asked."""
        r = self.db().execute("select max(id) from messages where sender=? and body like ? and created_at>=?",
                              (HUB, f"%{PLAN_FILE} is missing%", run["phase_at"])).fetchone()[0]
        return r or 0

    def p1(self, run: dict, late: bool) -> None:
        for a in self.crashes(run, self.active(run)):
            self.pause([a], True)
            rest = self.active(run)
            if rest:  # degrade: the other executor takes the part over
                data = self.data(run)
                data["takeover"].setdefault(rest[0], []).append(a)
                data.setdefault("took_over_at", {})[rest[0]] = db.now()  # its earlier done no longer ends P1
                self.update(run["id"], data=data)
                run["data"] = json.dumps(data)
                owners = (self.plan() or {}).get("owners", {}).get(a, [])
                self.event(run["id"], "P1", "takeover", {"from": a, "to": rest[0]})
                self.say(run["id"], [rest[0]], f"[plan-split-integrate] {a} failed twice. Take over its part too "
                                               f"(files: {', '.join(owners) or 'see the plan'}), in your worktree.")
            else:
                self.event(run["id"], "P1", "skipped", {"agent": a})
        ex = self.active(run)
        if ex and not late and not self.finished(run, ex, "part"):
            return
        executors = json.loads(run["executors"])
        if late:
            self.event(run["id"], "P1", "phase_timeout", {"waiting": [a for a in ex if not self.staged(run, a, "part")]})
            self.stop(executors)
        self.pause(executors, True)
        for i, a in enumerate(executors, 1):
            c = self.commit(self.wt(run, a), f"xmuse: {a} part (P1)")
            self.snapshot(run, f"S-E{i}", c)
            self.violations(run, a, c)
        run = self.go(run, "P2")
        merged = self.merge(run, executors)
        self.say(run["id"], [run["planner"]], self.integrate_text(run, merged, first=True))

    def integrate_text(self, run: dict, merged: dict, first: bool) -> str:
        lim, k = self.limits(run), run["round"]
        head = (f"Phase P2 (limit {lim['P2'] // 60} min): integrate." if first else
                f"Fix round {k} is merged (limit {lim['P3'] // 60} min): re-run the checks.")
        fix = ("send each failure to the executor who owns it (mention them" +
               (", kind=message or handoff" if self.info() else "") + ")")
        return (f"[plan-split-integrate] {head} The hub merged the executors' branches into the main workspace:\n"
                f"{self.merge_text(merged)}\nRun the full checks and your acceptance checklist. Report what passes "
                f"and what fails and whose part each failure is; {fix}; then call xmuse_done(stage=\"integrated\", "
                f"next=<an owner you asked to fix, or \"none\" when everything passes>). Fix rounds left: "
                f"{lim['rounds'] - k}.")

    def integrated(self, run: dict, late: bool) -> None:
        if self.crashes(run, [run["planner"]]):
            self.event(run["id"], run["phase"], "failed", {"why": "planner failed twice while integrating"})
            return self.finish(run)
        done = self.staged(run, run["planner"], "integrated")
        if not late and not (done and self.idle([run["planner"]])):
            return
        if late:
            self.event(run["id"], run["phase"], "phase_timeout", {})
            self.stop([run["planner"]])
        c = self.commit(self.ws, f"xmuse: integrated ({run['phase']}, round {run['round']})")
        if run["phase"] == "P2":
            self.snapshot(run, "S-int", c)
        nxt = done and done["body"].rsplit("\nnext: ", 1)[-1].strip()
        fixers = self.fixers(run)
        if done and nxt not in ("none", "") and nxt in self.active(run) and nxt not in fixers:
            fixers.append(nxt)
        if not done or nxt == "none" or not fixers or run["round"] >= self.limits(run)["rounds"]:
            return self.finish(run)
        run = self.go(run, "P3fix", round=run["round"] + 1)
        data = self.data(run)
        data["fixers"] = fixers
        self.update(run["id"], data=data)
        for a in fixers:
            r = git(self.wt(run, a), "merge", "--no-edit", "-m", f"xmuse: main into xmuse/{a}", run["branch"],
                    check=False)
            if r.returncode:
                git(self.wt(run, a), "merge", "--abort", check=False)
                self.event(run["id"], "P3fix", "merge_conflict", {"agent": a, "into": f"xmuse/{a}"})
            self.say(run["id"], [a], f"[plan-split-integrate] Phase P3, fix round {run['round']} (limit "
                                     f"{self.limits(run)['P3'] // 60} min): fix what the planner sent you, in your "
                                     f"worktree (the integrated main is merged into it). Then call "
                                     f"xmuse_done(stage=\"fix\", next=\"{run['planner']}\").")
        self.pause(fixers, False)

    def fixers(self, run: dict) -> list[str]:
        """Executors the planner messaged since this integration step began (its fix requests)."""
        return [r[0] for r in self.db().execute(
            "select distinct d.recipient from deliveries d join messages m on m.id=d.message_id where m.sender=?"
            " and m.created_at>=? and d.wake=1 and d.state in ('queued','held','blocked') order by 1",
            (run["planner"], run["phase_at"])) if r[0] in self.active(run)]

    def p3fix(self, run: dict, late: bool) -> None:
        fixers = [a for a in self.data(run).get("fixers", []) if a in self.active(run)]
        self.crashes(run, fixers)
        fixers = [a for a in fixers if a in self.active(run)]
        if fixers and not late and not self.finished(run, fixers, "fix"):
            return
        if late:
            self.event(run["id"], "P3fix", "phase_timeout", {"waiting": [a for a in fixers
                                                                         if not self.staged(run, a, "fix")]})
            self.stop(fixers)
        self.pause(json.loads(run["executors"]), True)
        for a in fixers:
            c = self.commit(self.wt(run, a), f"xmuse: {a} fix round {run['round']}")
            self.violations(run, a, c)
        run = self.go(run, "P3int")
        merged = self.merge(run, fixers)
        c = self.commit(self.ws, f"xmuse: fix round {run['round']} merged")
        self.snapshot(run, f"S-fix-{run['round']}", c)
        self.say(run["id"], [run["planner"]], self.integrate_text(run, merged, first=False))

    def finish(self, run: dict, state: str = "finished", stop: bool = False) -> None:
        run = self.go(run, "F")
        executors = json.loads(run["executors"])
        self.pause(executors, True)
        # leftover requests to executors are canceled; P is interrupted only when time ran out (it may be ending
        # the turn in which it called xmuse_done)
        self.stop([run["planner"], *executors] if stop else executors)
        c = self.commit(self.ws, "xmuse: final")
        self.snapshot(run, "F", c)
        self.pause(executors, False)
        self.update(run["id"], state=state, ended_at=db.now())
        self.event(run["id"], "F", state, {"commit": c})

    def fail(self, run: dict) -> None:
        run = self.go(run, "F")
        executors = json.loads(run["executors"])
        self.stop([run["planner"], *executors])
        self.pause(executors, False)
        self.update(run["id"], state="failed", ended_at=db.now())
        self.event(run["id"], "F", "failed", {})

    # ---- status ------------------------------------------------------------------------------------------------
    def status(self, rid: int | None = None) -> dict:
        conn = self.db()
        run = db.row(conn.execute("select * from preset_runs where id=?" if rid else
                                  "select * from preset_runs order by id desc limit 1", (rid,) if rid else ()))
        if run is None:
            raise ToolError("invalid_arguments", "no preset run")
        ev = db.rows(conn.execute("select at, phase, kind, detail from preset_events where run_id=? order by id",
                                  (run["id"],)))
        return {**{k: run[k] for k in ("id", "preset", "planner", "base", "branch", "phase", "round", "state",
                                       "created_at", "ended_at")},
                "executors": json.loads(run["executors"]), "limits": json.loads(run["limits"]),
                "data": json.loads(run["data"]),
                "events": [{**e, "detail": json.loads(e["detail"])} for e in ev]}


def loop(orch: Orchestrator, stop, interval: float) -> None:
    while not stop.wait(interval):
        orch.tick()
