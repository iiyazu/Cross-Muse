"""experiments/run.py: scenario parsing, the claude-needs-a-model guard, rot extraction, review workspace."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
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


def test_long_L_mo_copies_long_L_plus_memoryos():
    base = run.parse_env(EXP / "scenarios" / "long-L.env")
    mo = run.parse_env(EXP / "scenarios" / "long-L-mo.env")
    assert mo.get("MEMORYOS") == "on"
    assert {k: v for k, v in mo.items() if k != "MEMORYOS"} == base


def test_memoryos_cmd_default_and_port(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORYOS_CMD", raising=False)
    monkeypatch.delenv("MEMORYOS_DIR", raising=False)
    cmd = run.memoryos_cmd(8123)
    assert cmd == ["memoryos", "api", "--host", "127.0.0.1", "--port", "8123"]
    monkeypatch.setenv("MEMORYOS_DIR", str(tmp_path))  # no .venv/bin/memoryos there: still PATH
    assert run.memoryos_cmd(8123)[0] == "memoryos"
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "memoryos").write_text("#!/bin/sh\n")
    assert run.memoryos_cmd(8123) == [str(tmp_path / ".venv" / "bin" / "memoryos"), "api", "--host", "127.0.0.1",
                                      "--port", "8123"]
    monkeypatch.delenv("MEMORYOS_DIR")
    monkeypatch.setenv("MEMORYOS_CMD", "python f.py --port {port} --host 127.0.0.1")
    assert run.memoryos_cmd(8123) == ["python", "f.py", "--port", "8123", "--host", "127.0.0.1"]
    monkeypatch.setenv("MEMORYOS_CMD", "python f.py")
    assert run.memoryos_cmd(8123)[-2:] == ["--port", "8123"]
    assert run.free_port() > 0


def _mo_run(tmp_path, monkeypatch):
    fake = EXP.parent / "tests" / "fakes" / "fake_memoryos_cmd.py"
    monkeypatch.setenv("MEMORYOS_CMD", f"{sys.executable} {fake}")
    monkeypatch.setenv("MEMORYOS_DIR", str(tmp_path))
    r = run.Run.__new__(run.Run)
    r.sc = {"MEMORYOS": "on"}
    r.res = tmp_path / "results"
    r.res.mkdir(parents=True, exist_ok=True)
    r.mo_proc, r.mo_log, r.mo_url, r.mo_caps = None, None, "", []
    return r


def test_memoryos_off_does_nothing(tmp_path):
    r = run.Run.__new__(run.Run)
    r.sc = {}
    r.res = tmp_path
    r.mo_proc, r.mo_log, r.mo_url, r.mo_caps = None, None, "", []
    r.mo_start()
    assert r.mo_proc is None and r.mo_url == "" and r.mo_caps == []
    r.mo_stop()
    assert r.mo_collect(tmp_path) == {}


def test_memoryos_needs_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORYOS_DIR", raising=False)
    r = run.Run.__new__(run.Run)
    r.sc = {"MEMORYOS": "on"}
    r.res = tmp_path
    r.mo_proc, r.mo_log, r.mo_url, r.mo_caps = None, None, "", []
    with pytest.raises(SystemExit, match="MEMORYOS_DIR"):
        r.mo_start()


def test_memoryos_starts_passes_health_writes_config_and_stops(tmp_path, monkeypatch):
    r = _mo_run(tmp_path, monkeypatch)
    r.mo_start()
    try:
        assert r.mo_url.startswith("http://127.0.0.1:")
        port = int(r.mo_url.rsplit(":", 1)[1])
        with urllib.request.urlopen(r.mo_url + "/health", timeout=5) as resp:
            body = json.loads(resp.read())
        assert body["status"] == "ok" and "recall" in body["capabilities"]
        assert set(r.mo_caps) == set(body["capabilities"])
        cfgf = tmp_path / "config.json"
        cfgf.write_text(json.dumps({"memoryos_url": ""}))
        cfg = {**json.loads(cfgf.read_text()), "memoryos_url": r.mo_url}
        cfgf.write_text(json.dumps(cfg))
        assert json.loads(cfgf.read_text())["memoryos_url"] == r.mo_url
        time.sleep(0.3)  # let the fake flush its startup line
        assert "fake-memoryos" in (r.res / "memoryos.log").read_bytes().decode(errors="replace")
        proc = r.mo_proc
        assert proc is not None and proc.poll() is None
    finally:
        r.mo_stop()
    assert r.mo_proc is None
    assert proc.poll() is not None  # SIGTERMed, SIGKILL after 10 s if needed
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_memoryos_stops_on_exception(tmp_path, monkeypatch):
    r = _mo_run(tmp_path, monkeypatch)
    r.mo_start()
    port = int(r.mo_url.rsplit(":", 1)[1])
    proc = r.mo_proc
    try:
        with pytest.raises(RuntimeError, match="boom"):
            try:
                raise RuntimeError("boom")
            finally:
                r.mo_stop()
    finally:
        r.mo_stop()
    assert proc.poll() is not None
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_mo_parse_hub_log_and_collect(tmp_path):
    r = run.Run.__new__(run.Run)
    r.sc = {"MEMORYOS": "on"}
    out = tmp_path / "out"
    out.mkdir()
    (out / "hub.log").write_text(
        "INFO:xmuse.memoryos:memoryos-call {\"path\": \"/recall\", \"ms\": 20, \"ok\": true}\n"
        "INFO:xmuse.memoryos:memoryos-call {\"path\": \"/recall\", \"ms\": 40, \"ok\": false}\n"
        "INFO:xmuse.memoryos:memoryos-call {\"path\": \"/curate\", \"ms\": 15000, \"ok\": true}\n"
        "INFO:xmuse.memoryos:curate #task usage {\"prompt_tokens\": 100, \"completion_tokens\": 50, \"attempts\": 1, \"unmetered_attempts\": 1}\n"
        "WARNING:xmuse.memoryos:memoryos /recall failed: Timeout\n")
    (out / "entries.json").write_text(json.dumps({"entries": [
        {"author": "curate", "status": "proposed"}, {"author": "curate", "status": "rejected"},
        {"author": "opencode-1", "status": "proposed"}], "events": []}))
    (out / "log.json").write_text(json.dumps({"messages": [
        {"kind": "notice", "body": "curate: E1 and E2 may contradict each other: x"},
        {"kind": "notice", "body": "something else"}, {"kind": "message", "body": "hi"}]}))
    calls = r.mo_parse_hub_log(out / "hub.log")
    assert [(c["path"], c["ok"]) for c in calls] == [("/recall", True), ("/recall", False), ("/curate", True)]
    assert calls[0]["ms"] == 20 and calls[2]["usage"]["prompt_tokens"] == 100
    stats = r.mo_collect(out)
    assert stats == {"proposals": 1, "conflicts": 1}
    assert (out / "memoryos-calls.json").exists()
