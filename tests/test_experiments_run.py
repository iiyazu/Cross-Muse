"""experiments/run.py: scenario parsing, the claude-needs-a-model guard, rot extraction, review workspace."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

EXP = Path(__file__).resolve().parents[1] / "experiments"
spec = importlib.util.spec_from_file_location("exp_run", EXP / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_every_scenario_parses_and_its_agents_are_valid():
    for f in (EXP / "scenarios").glob("*.env"):
        sc = run.parse_env(f)
        ids = {a[0] for a in run.parse_agents(sc.get("AGENTS", "opencode-1:opencode dsh-1:dsh"))}
        assert sc["GROUP"] in run.GROUPS and {sc["IMPL"], *sc["REVIEW"].split(",")} <= ids, f.name
        assert all(s in run.PKG for s in sc.get("SEEDS", sc.get("SEED", "")).split()), f.name


def test_claude_without_a_model_is_refused():
    with pytest.raises(SystemExit, match="explicit model"):
        run.parse_agents("opencode-1:opencode claude-1:claude")
    with pytest.raises(SystemExit, match="explicit model"):
        run.parse_agents("claude-1:claude:")
    assert run.parse_agents("claude-1:claude:claude-haiku-5-5 dsh-1:dsh") == [
        ("claude-1", "claude", "claude-haiku-5-5"), ("dsh-1", "dsh", None)]


def test_rot_text_is_the_blockquote_of_that_rot():
    for seed in run.PKG:
        for n in (1, 2):
            t = run.rot_text(seed, n)
            assert t.startswith("决定（supersedes") and "\n" in t
            assert t.endswith("把涉及这条约定的断言改成新约定，其余测试不要动。")  # what to do with the old-convention tests
    assert "十进制字符串" in run.rot_text("ledger", 1) and "uncategorized" in run.rot_text("ledger", 2)


def test_match_entry_takes_the_newest_active_decision():
    listing = ("E1 [decision] active global claude-1: amounts are integer cents\n"
               "E2 [question] active thread:#task dsh-1: integer or float cents?\n"
               "E3 [decision] active thread:#task dsh-1: use Integer Cents everywhere\n"
               "E4 [decision] active thread:#task dsh-1: sort by name\n")
    assert run.match_entry(listing, "cent|integer") == "E3"
    assert run.match_entry(listing, "decimal") is None


def test_parse_counts_reads_verbose_unittest_output():
    txt = ("test_rot1_a (post_rot_test_ledger.R.test_rot1_a) ... ok\n"
           "test_rot1_b (post_rot_test_ledger.R.test_rot1_b)\nA docstring line ... FAIL\n"
           "test_rot2_c (post_rot_test_ledger.R.test_rot2_c) ... ERROR\n")
    c = run.parse_counts(txt)
    assert c["tests"] == {"test_rot1_a": "ok", "test_rot1_b": "fail", "test_rot2_c": "fail"}
    assert (c["passed"], c["failed"]) == (1, 2)
    assert c["ids"] == {"R.test_rot1_a": "ok", "R.test_rot1_b": "fail", "R.test_rot2_c": "fail"}  # Class.method


@pytest.mark.parametrize("seed,bug", [("ledger", "1"), ("ledger", "2"), ("minisql", "1"), ("pipeline", "2")])
def test_review_workspace_has_the_bug_and_no_trace_of_it(tmp_path, seed, bug):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run.add_seed(tmp_path, seed, "", bug)
    leaks = [p for p in (tmp_path / run.PKG[seed]).glob("*.py")
             if any(w in p.read_text().lower() for w in ("planted", "bug", "reference"))]
    assert leaks == [] and not (tmp_path / "BUGS.md").exists()
    (tmp_path / "tests" / f"test_hidden_{seed}.py").write_text((EXP / "hidden" / f"test_hidden_{seed}.py").read_text())
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_hidden_*.py"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0 and "FAILED" in r.stderr  # the planted bug is live


def test_task_text_for_each_mode():
    sc = {"IMPL": "a", "REVIEW": "b", "MODE": "run"}
    t = run.task_text(sc, "ledger", "", "#task")
    assert "a implements; b reviews" in t and "review_request" in t and "cd " not in t
    t = run.task_text({**sc, "REVIEW": "b,c"}, "minisql", "minisql", "#task-minisql")
    assert "b and c both review" in t and "cd minisql &&" in t and "directory minisql/" in t
    t = run.task_text({**sc, "MODE": "review"}, "ledger", "", "#task")
    assert "b reviews it against SPEC.md" in t and "BUGS" not in t
