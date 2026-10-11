"""T13: the plan-split-integrate state machine, driven by scripted fake agents (one behaviour per agent)."""
import json
import subprocess
import threading
from pathlib import Path

from xmuse.adapters.base import Presence, TurnEnd, Usage

WHY = {k: "x" for k in ("what", "why", "tradeoff", "open_questions", "next_action")}
TEAM = [("plan", "claude"), ("e1", "claude"), ("e2", "claude")]
FAST = {"P0": 4, "P1": 6, "P2": 4, "P3": 4, "rounds": 2, "total": 60}
OWNERS = {"e1": ["src/a.py"], "e2": ["src/b.py"]}


class Scripted:
    """Driver whose turns run a Python behaviour: behave[agent](h, agent, prompt, cwd, stop) -> 'failed' or None."""
    vendor, push, name = "claude", None, "scripted"

    def __init__(self, h, behave):
        self.h, self.behave, self.stops, self.prompts = h, behave, {}, []
        self.headless = self

    def presence(self, agent, session):
        return Presence()

    def on_hook(self, *a):
        return False

    def start(self, spec):
        self.stops[spec.turn_id] = threading.Event()
        self.prompts.append((spec.agent["id"], spec.prompt, str(spec.cwd)))
        threading.Thread(target=self._run, args=(spec,), daemon=True).start()
        return {"handle": f"s-{spec.agent['id']}", "cwd": str(spec.cwd)}

    def _run(self, spec):
        stop = self.stops[spec.turn_id]
        try:
            status = self.behave[spec.agent["id"]](self.h, spec.agent["id"], spec.prompt, Path(spec.cwd), stop)
        except Exception as e:  # a behaviour bug shows up as a failed turn plus this text
            status = f"failed: {e!r}"
        if stop.is_set():
            status = "interrupted"
        st = "failed" if str(status).startswith("failed") else status if status == "interrupted" else "succeeded"
        self.h.hub.engine.turn_ended(TurnEnd(spec.turn_id, st, f"s-{spec.agent['id']}", Usage(calls=1),
                                             None if st == "succeeded" else str(status)))

    def interrupt(self, turn_id):
        if turn_id in self.stops:
            self.stops[turn_id].set()

    def close(self):
        pass


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def setup(make, behave, **cfg):
    h = make(TEAM, preset_tick=0.1, **cfg)
    for f, t in (("src/a.py", "a = 0\n"), ("src/b.py", "b = 0\n"), ("src/shared.py", "x = 0\n")):
        write(h.ws / f, t)
    git(h.ws, "add", "src")
    git(h.ws, "commit", "-q", "-m", "base")
    drv = Scripted(h, behave)
    h.hub.engine.drivers["claude"] = drv
    return h, drv


def start(h, limits=FAST):
    out = h.admin("run", task="make a and b", planner="plan", executors=["e1", "e2"], limits=limits)
    assert "result" in out, out
    return out["result"]


def status(h):
    return h.admin("runs")["result"]


def wait_end(h, timeout=40):
    h.wait(lambda: status(h)["state"] != "running", timeout, "preset run end")
    return status(h)


def kinds(st, kind):
    return [e for e in st["events"] if e["kind"] == kind]


def planner(h, aid, prompt, cwd, stop, integrate=None):
    if "Phase P0" in prompt:
        write(cwd / ".xmuse-plan.json", json.dumps({"owners": OWNERS, "acceptance": ["a and b set"]}))
        if h.hub.cfg.get("info_layer") == "off":
            h.tool(aid, "xmuse_send", to="#team", body="e1: src/a.py a=1; e2: src/b.py b=2", mentions=["e1", "e2"])
        else:
            for e, m in (("e1", "a"), ("e2", "b")):
                out = h.tool(aid, "xmuse_send", to="#team", body=f"implement {m}", kind="handoff", why=WHY,
                             mentions=[e], scope=f"module:{m}")
                assert "result" in out, out
        h.tool(aid, "xmuse_done", summary="planned", next="e1", stage="plan")
    elif "Phase P2" in prompt or "re-run the checks" in prompt:
        return (integrate or (lambda: h.tool(aid, "xmuse_done", summary="all pass", next="none",
                                             stage="integrated")))()


def executor(file, text, extra=None):
    def f(h, aid, prompt, cwd, stop):
        if "Phase P1" in prompt or "Take over" in prompt or "last turn failed" in prompt:
            write(cwd / file, text)
            for p, t in (extra or {}).items():
                write(cwd / p, t)
            h.tool(aid, "xmuse_done", summary=f"wrote {file}; tests pass", next="plan", stage="part")
    return f


def test_normal_path_plans_splits_integrates_and_snapshots(make):
    h, drv = setup(make, {"plan": planner, "e1": executor("src/a.py", "a = 1\n"), "e2": executor("src/b.py", "b = 2\n")})
    run = start(h)
    wts = run["worktrees"]
    st = wait_end(h)
    assert st["state"] == "finished", st["events"]
    phases = [e["phase"] for e in kinds(st, "phase")]
    assert phases == ["P1", "P2", "F"]
    assert [s["name"] for s in st["data"]["snapshots"]] == ["S-E1", "S-E2", "S-int", "F"]
    snaps = {s["name"]: s for s in st["data"]["snapshots"]}
    assert snaps["S-E1"]["files"] == ["src/a.py"] and snaps["S-E2"]["files"] == ["src/b.py"]
    assert snaps["F"]["files"] == ["src/a.py", "src/b.py"]
    assert "+a = 1" in Path(snaps["F"]["patch"]).read_text(encoding="utf-8") and "+b = 2" in Path(snaps["F"]["patch"]).read_text(encoding="utf-8")
    assert (h.ws / "src/a.py").read_text(encoding="utf-8") == "a = 1\n" and (h.ws / "src/b.py").read_text(encoding="utf-8") == "b = 2\n"
    assert not kinds(st, "violation") and not kinds(st, "merge_conflict") and not kinds(st, "phase_timeout")
    # executors worked in their own worktrees, only after the plan; the handoffs reached them in their first turn
    cwd = {a: c for a, _, c in drv.prompts}
    assert cwd["e1"] == wts["e1"] and cwd["e2"] == wts["e2"] and cwd["plan"] == str(h.ws)
    first = {a: p for a, p, _ in reversed(drv.prompts)}
    assert "implement a" in first["e1"] and "Phase P1" in first["e1"]
    assert h.q("select modules from entries where kind='assignment' and assignee='e1'")[0]["modules"] == '["a"]'
    assert h.q("select paused from agents where id in ('e1','e2')") == [{"paused": 0}, {"paused": 0}]


def test_no_plan_within_p0_fails_the_run(make):
    h, _ = setup(make, {"plan": lambda *a: None, "e1": executor("src/a.py", "a"), "e2": executor("src/b.py", "b")})
    start(h, {**FAST, "P0": 1})
    st = wait_end(h)
    assert st["state"] == "failed" and kinds(st, "phase_timeout")[0]["phase"] == "P0"
    assert kinds(st, "failed")[0]["detail"] == {"why": "no plan within the P0 limit"}
    assert not h.q("select 1 from turns where agent_id in ('e1','e2')")  # the executors never started


def test_invalid_plan_is_sent_back_once(make):
    calls = {"n": 0}

    def p(h, aid, prompt, cwd, stop):
        calls["n"] += 1
        if calls["n"] == 1:
            write(cwd / ".xmuse-plan.json", "{not json")
            return h.tool(aid, "xmuse_done", summary="planned", next="e1", stage="plan") and None
        return planner(h, aid, prompt.replace("is missing", "Phase P0 is missing"), cwd, stop)
    h, _ = setup(make, {"plan": p, "e1": executor("src/a.py", "a = 1\n"), "e2": executor("src/b.py", "b = 2\n")})
    start(h)
    st = wait_end(h)
    assert kinds(st, "plan_invalid") and st["state"] == "finished"


def test_phase_timeout_interrupts_and_moves_on(make):
    def slow(h, aid, prompt, cwd, stop):
        if "Phase P1" in prompt:
            write(cwd / "src/b.py", "b = 'half'\n")
            stop.wait(30)  # never calls done
    h, _ = setup(make, {"plan": planner, "e1": executor("src/a.py", "a = 1\n"), "e2": slow})
    start(h, {**FAST, "P1": 2})
    st = wait_end(h)
    t = kinds(st, "phase_timeout")
    assert t and t[0]["phase"] == "P1" and t[0]["detail"] == {"waiting": ["e2"]}
    assert h.q("select state from turns where agent_id='e2'")[-1]["state"] == "interrupted"
    snaps = {s["name"]: s for s in st["data"]["snapshots"]}
    assert snaps["S-E2"]["files"] == ["src/b.py"]  # the partial work is in the snapshot
    assert st["state"] == "finished"


def test_crash_is_retried_once_then_the_part_is_taken_over(make):
    tries = {"e1": 0}

    def e1(h, aid, prompt, cwd, stop):
        tries["e1"] += 1
        if tries["e1"] == 1:
            return "failed: provider error"
        if "Take over" in prompt:
            write(cwd / "src/b.py", "b = 'e1 did it'\n")
        return executor("src/a.py", "a = 1\n")(h, aid, "Phase P1", cwd, stop)
    h, _ = setup(make, {"plan": planner, "e1": e1, "e2": lambda *a: "failed: crash"})
    start(h, {**FAST, "P1": 10})
    st = wait_end(h)
    retries = {e["detail"]["agent"] for e in kinds(st, "crash_retry")}
    assert retries == {"e1", "e2"}
    assert [e["detail"]["agent"] for e in kinds(st, "degraded")] == ["e2"]
    assert kinds(st, "takeover")[0]["detail"] == {"from": "e2", "to": "e1"}
    assert st["data"]["degraded"] == ["e2"]
    assert (h.ws / "src/b.py").read_text(encoding="utf-8") == "b = 'e1 did it'\n" and not kinds(st, "violation")
    assert not kinds(st, "phase_timeout")


def test_out_of_bounds_edits_are_recorded_and_conflicts_go_to_the_planner(make):
    def integrate(h, cwd):
        def go():
            r = subprocess.run(["git", "-c", "user.name=p", "-c", "user.email=p@p", "merge", "xmuse/e2"], cwd=cwd,
                               capture_output=True, text=True)
            assert r.returncode != 0
            write(cwd / "src/shared.py", "x = 3\n")
            git(cwd, "add", "src/shared.py")
            git(cwd, "commit", "-q", "--no-edit")
            h.tool("plan", "xmuse_done", summary="merged e2 by hand", next="none", stage="integrated")
        return go

    def p(h, aid, prompt, cwd, stop):
        if "Phase P2" in prompt:
            assert "CONFLICT in src/shared.py" in prompt
        return planner(h, aid, prompt, cwd, stop, integrate(h, cwd))
    h, _ = setup(make, {"plan": p, "e1": executor("src/a.py", "a = 1\n", {"src/shared.py": "x = 1\n"}),
                        "e2": executor("src/b.py", "b = 2\n", {"src/shared.py": "x = 2\n"})})
    start(h)
    st = wait_end(h)
    assert sorted((e["detail"]["agent"], e["detail"]["file"]) for e in kinds(st, "violation")) == [
        ("e1", "src/shared.py"), ("e2", "src/shared.py")]
    assert kinds(st, "merge_conflict")[0]["detail"] == {"agent": "e2", "files": ["src/shared.py"]}
    assert (h.ws / "src/shared.py").read_text(encoding="utf-8") == "x = 3\n" and (h.ws / "src/b.py").read_text(encoding="utf-8") == "b = 2\n"
    assert st["state"] == "finished"


def test_fix_round_goes_back_to_the_owner_and_is_merged(make):
    rounds = {"n": 0}

    def p(h, aid, prompt, cwd, stop):
        def integrate():
            rounds["n"] += 1
            if rounds["n"] == 1:
                h.tool(aid, "xmuse_send", to="#team", body="a must be 10", mentions=["e1"])
                return h.tool(aid, "xmuse_done", summary="a fails", next="e1", stage="integrated") and None
            assert "Fix round 1 is merged" in prompt
            h.tool(aid, "xmuse_done", summary="all pass", next="none", stage="integrated")
        return planner(h, aid, prompt, cwd, stop, integrate)

    def e1(h, aid, prompt, cwd, stop):
        if "Phase P3" in prompt:
            assert "a must be 10" in prompt and (cwd / "src/b.py").read_text(encoding="utf-8") == "b = 2\n"  # main merged in
            write(cwd / "src/a.py", "a = 10\n")
            return h.tool(aid, "xmuse_done", summary="fixed", next="plan", stage="fix") and None
        return executor("src/a.py", "a = 1\n")(h, aid, prompt, cwd, stop)
    h, _ = setup(make, {"plan": p, "e1": e1, "e2": executor("src/b.py", "b = 2\n")})
    start(h)
    st = wait_end(h)
    assert [s["name"] for s in st["data"]["snapshots"]] == ["S-E1", "S-E2", "S-int", "S-fix-1", "F"]
    assert [e["phase"] for e in kinds(st, "phase")] == ["P1", "P2", "P3fix", "P3int", "F"]
    assert st["round"] == 1 and (h.ws / "src/a.py").read_text(encoding="utf-8") == "a = 10\n"
    assert not h.q("select 1 from turns where agent_id='e2' and started_at>?", kinds(st, "phase")[2]["at"])


def test_plain_team_runs_without_the_information_layer(make):
    h, drv = setup(make, {"plan": planner, "e1": executor("src/a.py", "a = 1\n"), "e2": executor("src/b.py", "b = 2\n")},
                   info_layer="off")
    start(h)
    st = wait_end(h)
    assert st["state"] == "finished" and kinds(st, "start")[0]["detail"]["info_layer"] == "off"
    p0 = next(p for a, p, _ in drv.prompts if a == "plan")
    assert "kind=handoff" not in p0 and "send ONE message" in p0
    assert h.q("select count(*) n from entries")[0]["n"] == 0


def test_planner_crashing_twice_in_p0_fails_the_run(make):
    h, _ = setup(make, {"plan": lambda *a: "failed: boom", "e1": executor("src/a.py", "a"),
                        "e2": executor("src/b.py", "b")})
    start(h)
    st = wait_end(h)
    assert [e["kind"] for e in st["events"] if e["kind"] in ("crash_retry", "degraded", "failed")] == [
        "crash_retry", "degraded", "failed", "failed"]
    assert kinds(st, "failed")[0]["detail"] == {"why": "planner failed twice"} and st["state"] == "failed"


def test_cli_starts_a_run_and_reports_it(make, tmp_path):
    h, _ = setup(make, {"plan": planner, "e1": executor("src/a.py", "a = 1\n"), "e2": executor("src/b.py", "b = 2\n")})
    from xmuse import cli
    task = tmp_path / "task.txt"
    task.write_text("make a and b", encoding="utf-8")
    cli.main(["--ws", str(h.ws), "run", "--planner", "plan", "--executors", "e1,e2", "--task-file", str(task),
              "--limits", json.dumps(FAST)])
    st = wait_end(h)
    assert st["state"] == "finished"
    e = h.admin("run", task="again", planner="plan", executors=["plan"])
    assert "distinct agents" in e["error"]["message"]
