"""Single-instance hub lock (hublock.py): one hub per state dir, in the process itself."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import set_home
from xmuse import cli, hublock, init as xinit

HOLDER = ("import sys, time; from pathlib import Path; from xmuse import hublock; "
          "f = hublock.acquire(Path(sys.argv[1])); print('locked', flush=True); time.sleep(60)")


def spawn_holder(state: Path) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", HOLDER, str(state)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "locked"
    return p


def stop(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    for s in (p.stdout, p.stderr):
        if s:
            s.close()


def test_lock_refused_in_other_process_then_free(tmp_path):
    state = tmp_path / "state"
    assert hublock.holder(state) is None
    p = spawn_holder(state)
    try:
        assert hublock.holder(state) == p.pid
        with pytest.raises(hublock.HubLocked) as e:
            hublock.acquire(state)
        assert e.value.pid == p.pid
    finally:
        stop(p)
    assert hublock.holder(state) is None
    f = hublock.acquire(state)  # free after the holder died: the OS dropped the lock
    assert hublock.holder(state) == os.getpid()
    f.close()
    assert hublock.holder(state) is None
    assert (state / "hub.lock").exists()  # never deleted


def test_second_hub_refused_and_hub_start_does_not_spawn(tmp_path, monkeypatch, capsys):
    set_home(monkeypatch, tmp_path / "home")
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("XMUSE_REGISTRY_DIR", str(tmp_path / "registry"))
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    state = xinit.init(ws)
    env = {**os.environ, "XMUSE_STATE": str(state)}
    cmd = [sys.executable, "-m", "xmuse", "hub", "run"]
    procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    try:
        deadline = time.time() + 60
        while time.time() < deadline and not (state / "hub.json").exists() and all(p.poll() is None for p in procs):
            time.sleep(0.1)
        loser = None
        while time.time() < deadline and loser is None:
            loser = next((p for p in procs if p.poll() is not None), None)
            time.sleep(0.1)
        assert loser is not None, "neither hub exited"
        winner = next(p for p in procs if p is not loser)
        err = loser.stderr.read()
        assert loser.returncode == cli.HUB_LOCKED_EXIT == 3, err
        assert "another hub already runs" in err and f"pid {winner.pid}" in err and "Traceback" not in err
        while time.time() < deadline and not (state / "hub.json").exists():
            time.sleep(0.1)
        assert winner.poll() is None
        assert json.loads((state / "hub.json").read_text(encoding="utf-8"))["pid"] == winner.pid
        assert hublock.holder(state) == winner.pid

        spawned = []
        monkeypatch.setattr(cli.proc, "popen", lambda *a, **k: spawned.append(a))
        cli.hub_start(state)
        assert "hub already running" in capsys.readouterr().out
        assert not spawned
    finally:
        for p in procs:
            stop(p)
    assert not (state / "hub.json").exists()  # the winner shut down cleanly on SIGTERM
    assert hublock.holder(state) is None


def test_hub_start_while_another_hub_still_starting(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"  # lock held, no hub.json yet: the other hub is in its precheck
    p = spawn_holder(state)
    try:
        monkeypatch.setattr(cli.preflight, "run", lambda s: pytest.fail("preflight must not run"))
        cli.hub_start(state)
        out = capsys.readouterr().out
        assert "hub already running" in out and str(p.pid) in out
    finally:
        stop(p)


def test_shutdown_leaves_another_hubs_hub_json(tmp_path):
    from xmuse.server import Hub
    hub = Hub.__new__(Hub)  # only _drop_hub_json: no setup, no lock
    hub.state = tmp_path
    path = tmp_path / "hub.json"
    path.write_text(json.dumps({"port": 1, "pid": os.getpid() + 1}), encoding="utf-8")
    hub._drop_hub_json()
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid() + 1  # another hub's: kept
    path.write_text(json.dumps({"port": 1, "pid": os.getpid()}), encoding="utf-8")
    hub._drop_hub_json()
    assert not path.exists()  # ours: removed
    path.write_text("{not json", encoding="utf-8")
    hub._drop_hub_json()
    assert not path.exists()  # unreadable: removed as before
    hub._drop_hub_json()  # already gone: no error
