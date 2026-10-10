"""experiments/metrics.py on forged results directories (run: cd hub && .venv/bin/python -m pytest ../tests/test_metrics.py)."""
import csv
import importlib.util
import json
from pathlib import Path

EXP = Path(__file__).resolve().parents[1] / "experiments"
spec = importlib.util.spec_from_file_location("exp_metrics", EXP / "metrics.py")
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def turn(i, agent, mode, align, view, inp=1000, cr=9000):
    return {"id": i, "agent_id": agent, "state": "succeeded", "align_mode": mode, "align_tokens": align, "view_entries": view,
            "input": inp, "cache_read": cr, "cache_write": 0, "output": 100}


def forge(root: Path, name, group="C", rot=None, tests=None, review=None, bug="1", seed="ledger", entries=(), hidden_ids=None, rot_tests=None):
    d = root / name
    d.mkdir(parents=True)
    scenario = {"GROUP": group, "SEED": seed, **({"MODE": "review", "BUG": bug} if review else {})}
    rot = rot or {"expected": False, "injected": False}
    (d / "meta.json").write_text(json.dumps({
        "run": name, "seed": seed, "group": group, "scenario": scenario, "first_message_id": 1, "seconds": 60, "quiet": True,
        "agents": [["opencode-1", "opencode", None], ["dsh-1", "dsh", None]], "rot": rot}))
    msgs = [{"id": 1, "sender": "human", "kind": "message"}, {"id": 2, "sender": "opencode-1", "kind": "review_request"}]
    if rot.get("injected"):
        msgs.append({"id": 3, "sender": "human", "kind": "decision"})
    msgs.append({"id": 9, "sender": "hub", "kind": "notice"})
    ts = [turn(1, "opencode-1", "snapshot", 400, 4), turn(2, "dsh-1", "delta", 100, 6), turn(3, "opencode-1", "none", 0, 6)]
    (d / "log.json").write_text(json.dumps({"messages": msgs, "turns": ts}))
    (d / "entries.json").write_text(json.dumps({"entries": [
        {"kind": k, "author": a, "statement": s, "refs": "[2]"} for k, a, s in entries], "events": []}))
    if tests is not None:
        (d / "public.status").write_text("pass")
        (d / "hidden.status").write_text(tests)
    if rot.get("injected"):
        (d / "rot-tests.json").write_text(json.dumps({"tests": rot_tests or {"test_rot1_a": "ok", "test_rot1_b": "fail", "test_rot2_c": "fail"}}))
    if hidden_ids is not None:
        (d / "hidden-tests.json").write_text(json.dumps({"ids": hidden_ids}))
    if review:
        (d / "review.md").write_text(review)
    return d


def test_run_metrics_and_groups(tmp_path):
    rot = {"expected": True, "injected": True, "n": 1, "kind": "decision", "supersedes": "E1"}
    hid = {"TestParseAmountHidden.test_exact_cents_never_through_float": "fail", "TestRulesHidden.test_a": "ok", "TestRulesHidden.test_b": "ok"}
    forge(tmp_path, "ledger-C-1", rot=rot, tests="fail", hidden_ids=hid, entries=[
        ("decision", "opencode-1", "Amounts are integer cents everywhere"), ("decision", "human", "wildcard rules"),
        ("question", "dsh-1", "float?"), ("assumption", "dsh-1", "Currencies are never mixed in a bucket")])
    forge(tmp_path, "ledger-B-1", group="B", rot={"expected": True, "injected": False}, tests="fail")
    out = tmp_path / "out"
    metrics.main([str(tmp_path / "ledger-C-1"), str(tmp_path / "ledger-B-1"), "--out", str(out)])
    m = json.loads((out / "metrics.json").read_text())
    c, b = m["runs"]
    assert (c["completed"], c["turns"], c["tokens"]) == (False, 3, 3 * 10100)  # rot only partial -> not complete
    assert c["hidden"] == "fail" and c["hidden_unaffected"] == {"passed": 2, "total": 2, "excluded": 11, "failed": []}
    assert c["human_messages"] == 2 and c["human_interventions"] == 0 and c["notices"] == 1  # the rot message is not an intervention
    inj = c["injection"]
    assert inj["modes"] == {"snapshot": 1, "delta": 1, "none": 1} and inj["align_tokens"] == 500
    assert abs(inj["share_total"] - 500 / 30000) < 1e-9 and inj["share_max"] == 0.04 and inj["share_median"] == 0.01
    assert c["rot"]["verdict"] == "partial" and (c["rot"]["passed"], c["rot"]["total"]) == (1, 2)  # only test_rot1_* count
    assert c["declaration"]["declared"] == 2 and "line-numbers-1-based" in c["declaration"]["missing"]
    assert c["view_curve"] == {"opencode-1": [4, 6], "dsh-1": [6]}
    assert b["completed"] is False and b["rot"]["verdict"] == "not_injected" and b["review"] is None
    assert m["groups"]["C"]["completion_rate"] == 0.0 and m["groups"]["B"]["completion_rate"] == 0.0
    assert m["groups"]["C"]["rot"] == {"partial": 1}
    rows = list(csv.reader((out / "view-curve.csv").open()))
    assert rows[0][-2:] == ["wake_no", "view_entries"] and ["ledger-C-1", "ledger", "C", "opencode-1", "2", "6"] in rows
    md = (out / "metrics.md").read_text()
    assert "| ledger-C-1/ledger | C |" in md and "## Groups" in md and "| fail | 2/2 |" in md


def test_completion_after_rot_ignores_only_the_listed_hidden_cases(tmp_path):
    rot = {"expected": True, "injected": True, "n": 1, "kind": "decision", "supersedes": None}
    listed = "TestParseAmountHidden.test_exact_cents_never_through_float"
    all_ok = {"test_rot1_a": "ok", "test_rot1_b": "ok"}
    forge(tmp_path, "followed", rot=rot, tests="fail", rot_tests=all_ok, hidden_ids={listed: "fail", "TestX.t": "ok"})
    forge(tmp_path, "broke-unlisted", rot=rot, tests="fail", rot_tests=all_ok, hidden_ids={listed: "fail", "TestX.t": "fail"})
    forge(tmp_path, "not-followed", rot=rot, tests="pass", hidden_ids={"TestX.t": "ok"})
    forge(tmp_path, "no-per-case-data", rot=rot, tests="pass", rot_tests=all_ok)
    forge(tmp_path, "no-rot", tests="pass")  # unchanged: public + raw hidden
    runs = {r["run"]: r for r in (metrics.run_metrics(tmp_path / n) for n in
                                  ("followed", "broke-unlisted", "not-followed", "no-per-case-data", "no-rot"))}
    assert runs["followed"]["completed"] is True and runs["followed"]["hidden"] == "fail"
    assert runs["broke-unlisted"]["completed"] is False and runs["broke-unlisted"]["hidden_unaffected"]["failed"] == ["TestX.t"]
    assert runs["not-followed"]["completed"] is False  # raw hidden passes, but the rot was not followed
    assert runs["no-per-case-data"]["completed"] is None and runs["no-per-case-data"]["hidden_unaffected"] is None
    assert runs["no-rot"]["completed"] is True and runs["no-rot"]["hidden_unaffected"] is None


def test_review_detection_and_false_positives(tmp_path):
    hit = ("## #4 dsh-1 -> #task [message]\nBug in ledger/parse.py parse_amount: int(float(text) * 100) truncates 1.15 to 114.\n\n"
           "## #5 dsh-1 -> #task [message]\nreport.py render_report is correct, no issues.")
    miss = ("## #4 dsh-1 -> #task [message]\nparse.py looks fine.\n\n"
            "## #5 dsh-1 -> #task [message]\nreport.py: render_report output is wrong, it fails on empty reports.\n"
            "rules.py apply_rules is incorrect for EUR.")
    forge(tmp_path, "review-1", review=hit)
    forge(tmp_path, "review-2", review=miss)
    metrics.main([str(tmp_path / "review-1"), str(tmp_path / "review-2"), "--out", str(tmp_path / "o")])
    r1, r2 = json.loads((tmp_path / "o" / "metrics.json").read_text())["runs"]
    assert r1["review"] == {"planted": "bug-1", "detected": True, "false_positives": [], "modules_without_bug": 2}
    assert r2["review"]["detected"] is False and r2["review"]["false_positives"] == ["report\\.py", "rules\\.py"]
    g = json.loads((tmp_path / "o" / "metrics.json").read_text())["groups"]["review-C"]
    assert g["review_detection_rate"] == 0.5 and g["review_false_positive_rate"] == 0.5


def test_parent_dir_with_stages_is_expanded(tmp_path):
    parent = tmp_path / "long-L-1"
    forge(parent, "ledger", group="L", tests="pass")
    forge(parent, "minisql", group="L", seed="minisql", tests="pass")
    assert [p.name for p in metrics.units([parent])] == ["ledger", "minisql"]
