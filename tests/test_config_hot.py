"""Hourly caps are tunable on a running hub (config refresh + `xmuse config set`)."""
import json

import pytest


def _write_cfg(h, **kv):
    p = h.state / "config.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw.update(kv)
    p.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def test_raising_cap_unpauses_on_resume(make):
    h = make(agent_hourly_turns=2)
    h.plan_claude({}, {}, {}, {})
    for body in ("a", "b", "c"):
        h.send("claude-1", body)
        h.wait_quiet()
    assert h.q("select paused from agents")[0]["paused"] == 1
    _write_cfg(h, agent_hourly_turns=100)
    h.admin("resume", agent="claude-1")
    h.wait_quiet()
    assert h.q("select paused from agents")[0]["paused"] == 0
    assert len(h.turns()) == 3


def test_lowering_cap_pauses_on_next_kick(make):
    h = make(agent_hourly_turns=100)
    h.plan_claude({}, {})
    h.send("claude-1", "a")
    h.wait_quiet()
    assert h.q("select paused from agents")[0]["paused"] == 0
    _write_cfg(h, agent_hourly_turns=1)
    h.send("claude-1", "b")
    h.wait(lambda: h.q("select paused from agents")[0]["paused"] == 1, what="paused by lowered cap")
    assert len(h.turns()) == 1


def test_broken_config_keeps_old_values_and_warns_once(make, caplog):
    h = make(agent_hourly_turns=100)
    h.plan_claude({}, {})
    (h.state / "config.json").write_text("{broken", encoding="utf-8")
    h.send("claude-1", "hi")
    h.wait_quiet()
    assert len(h.turns()) == 1  # the hub kept running
    assert h.hub.engine.cfg["agent_hourly_turns"] == 100
    assert sum("keeping previous values" in r.getMessage() for r in caplog.records) == 1
    h.send("claude-1", "again")
    h.wait_quiet()
    assert sum("keeping previous values" in r.getMessage() for r in caplog.records) == 1


def test_wrong_typed_value_keeps_old(make, caplog):
    h = make()
    assert h.hub.engine.cfg["agent_hourly_turns"] == 40  # default untouched
    _write_cfg(h, agent_hourly_turns="lots")
    h.plan_claude({})
    h.send("claude-1", "hi")
    h.wait_quiet()
    assert h.hub.engine.cfg["agent_hourly_turns"] == 40
    assert any("ignoring agent_hourly_turns='lots'" in r.getMessage() for r in caplog.records)


def test_config_set_parses_types_writes_atomically_and_notes_restart(make, capsys):
    from xmuse import cli
    h = make()
    cli.main(["--ws", str(h.ws), "config", "set", "agent_hourly_turns", "30000000"])
    out = capsys.readouterr().out
    assert "agent_hourly_turns = 30000000" in out and "restart" not in out  # hot key: no restart note
    raw = json.loads((h.state / "config.json").read_text(encoding="utf-8"))
    assert raw["agent_hourly_turns"] == 30000000
    assert not (h.state / "config.json.tmp").exists()
    cli.main(["--ws", str(h.ws), "config", "set", "wake", "all"])
    assert json.loads((h.state / "config.json").read_text(encoding="utf-8"))["wake"] == "all"
    cli.main(["--ws", str(h.ws), "config", "set", "sweep_interval", "99"])
    out = capsys.readouterr().out
    assert "restart the hub" in out  # not a hot key: still written, but flagged
    assert json.loads((h.state / "config.json").read_text(encoding="utf-8"))["sweep_interval"] == 99
    with pytest.raises(SystemExit, match="broken"):
        (h.state / "config.json").write_text("{broken", encoding="utf-8")
        cli.main(["--ws", str(h.ws), "config", "set", "agent_hourly_turns", "5"])


def test_config_set_keeps_mode_and_unicode(make):
    import os
    from xmuse import cli
    h = make()
    (h.state / "config.json").chmod(0o600)
    cli.main(["--ws", str(h.ws), "config", "set", "wake", "全部"])
    raw = (h.state / "config.json").read_text(encoding="utf-8")
    assert "全部" in raw and "\\u" not in raw  # no \u escapes
    assert json.loads(raw)["wake"] == "全部"
    assert os.stat(h.state / "config.json").st_mode & 0o777 == 0o600
