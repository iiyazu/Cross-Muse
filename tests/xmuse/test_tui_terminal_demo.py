from __future__ import annotations

import json
from pathlib import Path

from xmuse.tui import terminal_demo as terminal_demo_cli
from xmuse_core.chat.terminal_tui_demo import (
    TerminalCommandResult,
    TerminalTuiDemoResult,
    _scripted_terminal_inputs,
    _terminal_demo_exit_code,
    record_terminal_tui_demo_evidence,
    run_terminal_tui_demo,
)


def test_terminal_tui_demo_recorder_requires_resume_surface(tmp_path: Path, monkeypatch) -> None:
    _install_terminal_demo_surfaces(
        tmp_path,
        monkeypatch,
        command_events=[
            _command_event("/overview"),
            _command_event("/discussion"),
            _command_event("/blockers"),
        ],
    )

    result = record_terminal_tui_demo_evidence(
        xmuse_root=tmp_path,
        conversation_id="conv-v14",
        command="uv run python -m xmuse.tui",
        exit_code=0,
        started_at="2099-01-01T00:00:00Z",
        completed_at="2099-01-01T00:00:05Z",
        terminal_run_id="terminal-run-v14",
    )

    assert result.written is False
    assert "resume" in result.missing_surfaces
    assert not (tmp_path / "tui_terminal_demo.json").exists()


def test_terminal_tui_demo_recorder_writes_validator_payload(tmp_path: Path, monkeypatch) -> None:
    _install_terminal_demo_surfaces(
        tmp_path,
        monkeypatch,
        command_events=[
            _command_event("/resume"),
            _command_event("/overview"),
            _command_event("/discussion"),
            _command_event("/blockers"),
        ],
    )

    result = record_terminal_tui_demo_evidence(
        xmuse_root=tmp_path,
        conversation_id="conv-v14",
        command="uv run python -m xmuse.tui",
        exit_code=0,
        started_at="2099-01-01T00:00:00Z",
        completed_at="2099-01-01T00:00:05Z",
        terminal_run_id="terminal-run-v14",
    )

    assert result.written is True
    assert result.evidence["mode"] == "terminal"
    assert result.evidence["evidence_source"] == "xmuse_tui_terminal_demo_harness"
    assert result.evidence["harness_version"] == 1
    assert result.evidence["terminal_run_id"] == "terminal-run-v14"
    assert result.evidence["exit_code"] == 0
    assert result.evidence["scripted_inputs"] == [
        "/resume conv-v14",
        "/overview",
        "/discussion",
        "/blockers",
    ]
    assert set(result.evidence["visible_surfaces"]) == {
        "init",
        "overview",
        "discussion",
        "blockers",
        "dispatch",
        "provider_writeback",
        "resume",
    }
    assert result.evidence["runtime_timeline_event_ids"] == [
        "collab-v14",
        "blocker-v14",
        "gate-blocked",
        "gate-allowed",
        "dispatch-v14",
        "inbox-v14",
    ]
    assert result.evidence["observed_command_event_ids"] == [
        "terminal-event-1",
        "terminal-event-2",
        "terminal-event-3",
        "terminal-event-4",
    ]
    persisted = json.loads((tmp_path / "tui_terminal_demo.json").read_text())
    assert persisted["terminal_tui_demo"] == result.evidence


def test_terminal_tui_demo_recorder_rejects_non_terminal_launch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_terminal_demo_surfaces(
        tmp_path,
        monkeypatch,
        command_events=[
            _command_event("/resume"),
            _command_event("/overview"),
            _command_event("/discussion"),
            _command_event("/blockers"),
        ],
    )

    result = record_terminal_tui_demo_evidence(
        xmuse_root=tmp_path,
        conversation_id="conv-v14",
        command="echo uv run python -m xmuse.tui",
        exit_code=0,
        started_at="2099-01-01T00:00:00Z",
        completed_at="2099-01-01T00:00:05Z",
        terminal_run_id="terminal-run-v14",
    )

    assert result.written is False
    assert "terminal_launch_command" in result.missing_surfaces
    assert not (tmp_path / "tui_terminal_demo.json").exists()


def test_terminal_tui_demo_recorder_rejects_stale_command_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_terminal_demo_surfaces(
        tmp_path,
        monkeypatch,
        command_events=[
            _command_event("/resume", created_at="2098-01-01T00:00:01Z"),
            _command_event("/overview", created_at="2098-01-01T00:00:01Z"),
            _command_event("/discussion", created_at="2098-01-01T00:00:01Z"),
            _command_event("/blockers", created_at="2098-01-01T00:00:01Z"),
        ],
    )

    result = record_terminal_tui_demo_evidence(
        xmuse_root=tmp_path,
        conversation_id="conv-v14",
        command="uv run python -m xmuse.tui",
        exit_code=0,
        started_at="2099-01-01T00:00:00Z",
        completed_at="2099-01-01T00:00:05Z",
        terminal_run_id="terminal-run-v14",
    )

    assert result.written is False
    assert {"resume", "overview", "discussion", "blockers"}.issubset(
        set(result.missing_surfaces)
    )
    assert not (tmp_path / "tui_terminal_demo.json").exists()


def test_terminal_tui_demo_runner_injects_conversation_for_scripted_terminal_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setenv("TERM", "dumb")

    def _runner(args, env, timeout_s):
        calls.append((args, env, timeout_s))
        return TerminalCommandResult(exit_code=0, output="terminal ok")

    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo._persisted_tui_command_events",
        lambda root, conversation_id: [
            _command_event(
                "/resume",
                terminal_run_id=calls[0][1]["XMUSE_TUI_TERMINAL_RUN_ID"],
                event_id="terminal-event-1",
            ),
            _command_event(
                "/overview",
                terminal_run_id=calls[0][1]["XMUSE_TUI_TERMINAL_RUN_ID"],
                event_id="terminal-event-2",
            ),
            _command_event(
                "/discussion",
                terminal_run_id=calls[0][1]["XMUSE_TUI_TERMINAL_RUN_ID"],
                event_id="terminal-event-3",
            ),
            _command_event(
                "/blockers",
                terminal_run_id=calls[0][1]["XMUSE_TUI_TERMINAL_RUN_ID"],
                event_id="terminal-event-4",
            ),
        ],
    )
    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo.build_conversation_inspector_payload",
        lambda conversation_id, root: _terminal_demo_inspector(),
    )
    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo._conversation_runtime_timeline_detail",
        lambda root, conversation_id: _terminal_demo_timeline(),
    )
    now_values = iter([
        "2099-01-01T00:00:00Z",
        "2099-01-01T00:00:05Z",
    ])
    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo._utc_now",
        lambda: next(now_values),
    )

    result = run_terminal_tui_demo(
        xmuse_root=tmp_path,
        conversation_id="conv-v14",
        runner=_runner,
        timeout_s=7,
    )

    assert result.written is True
    assert calls
    args, env, timeout_s = calls[0]
    assert list(args) == ["uv", "run", "python", "-m", "xmuse.tui"]
    assert env["XMUSE_TUI_DEMO_CONVERSATION_ID"] == "conv-v14"
    assert env["XMUSE_TUI_TERMINAL_RUN_ID"].startswith("terminal-tui-demo:")
    assert env["XMUSE_TUI_TERMINAL_DEMO_AUTORUN"] == "1"
    assert env["TERM"] == "xterm-256color"
    assert timeout_s == 7


def test_terminal_tui_demo_scripted_pty_inputs_include_newlines_and_quit() -> None:
    inputs = _scripted_terminal_inputs(
        {"XMUSE_TUI_DEMO_CONVERSATION_ID": "conv-v14"}
    )

    assert inputs == [
        "/resume conv-v14\x1b\r",
        "/overview\x1b\r",
        "/discussion\x1b\r",
        "/blockers\x1b\r",
        "\x11",
    ]


def test_terminal_tui_demo_treats_scripted_interrupt_as_clean_exit() -> None:
    assert _terminal_demo_exit_code(-2, sent_inputs=True) == 0
    assert _terminal_demo_exit_code(130, sent_inputs=True) == 0
    assert _terminal_demo_exit_code(1, sent_inputs=True) == 1
    assert _terminal_demo_exit_code(-2, sent_inputs=False) == -2


def test_terminal_tui_demo_cli_reports_evidence_path(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = []

    def _run_terminal_tui_demo(**kwargs):
        calls.append(kwargs)
        return TerminalTuiDemoResult(written=True, evidence={"conversation_id": "conv-v14"})

    monkeypatch.setattr(terminal_demo_cli, "run_terminal_tui_demo", _run_terminal_tui_demo)

    exit_code = terminal_demo_cli.main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--conversation-id",
            "conv-v14",
            "--timeout-s",
            "3",
        ]
    )

    assert exit_code == 0
    assert calls[0]["xmuse_root"] == tmp_path
    assert calls[0]["conversation_id"] == "conv-v14"
    assert calls[0]["timeout_s"] == 3.0
    assert "tui_terminal_demo.json" in capsys.readouterr().out


def _command_event(
    command: str,
    *,
    created_at: str = "2099-01-01T00:00:01Z",
    terminal_run_id: str = "terminal-run-v14",
    event_id: str | None = None,
) -> dict[str, str]:
    event_number = {
        "/resume": "1",
        "/overview": "2",
        "/discussion": "3",
        "/blockers": "4",
    }.get(command, "0")
    return {
        "event_id": event_id or f"terminal-event-{event_number}",
        "terminal_run_id": terminal_run_id,
        "command": command,
        "conversation_id": "conv-v14",
        "read_surface_authority": "chat_inspector",
        "surface_ref": "chat_inspector:conv-v14",
        "created_at": created_at,
    }


def _install_terminal_demo_surfaces(
    root: Path,
    monkeypatch,
    *,
    command_events: list[dict[str, str]],
) -> None:
    (root / "tui_command_events.json").write_text(
        json.dumps({"command_events": command_events}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo.build_conversation_inspector_payload",
        lambda conversation_id, root: _terminal_demo_inspector(),
    )
    monkeypatch.setattr(
        "xmuse_core.chat.terminal_tui_demo._conversation_runtime_timeline_detail",
        lambda root, conversation_id: _terminal_demo_timeline(),
    )


def _terminal_demo_inspector() -> dict:
    return {
        "participants": {
            "summary": {"init": 1, "architect": 1, "review": 1, "execute": 1},
        },
        "collaboration": {"runs": [{"run_id": "collab-v14"}]},
        "blockers": {"items": [{"blocker_id": "blocker-v14", "active": False}]},
        "dispatch_queue": {
            "entries": [
                {
                    "entry_id": "dispatch-v14",
                    "status": "dispatched",
                    "dispatch_evidence": "mcp_writeback:inbox-v14",
                }
            ],
        },
        "peer_latency": {
            "recent_turns": [
                {
                    "inbox_item_id": "inbox-v14",
                    "delivery_mode": "mcp_writeback",
                }
            ],
        },
    }


def _terminal_demo_timeline() -> dict:
    return {
        "conversation_id": "conv-v14",
        "events": [
            {"event_id": "collab-v14", "event_type": "collaboration_run"},
            {"event_id": "blocker-v14", "event_type": "blocker"},
            {"event_id": "gate-blocked", "event_type": "dispatch_gate"},
            {"event_id": "gate-allowed", "event_type": "dispatch_gate"},
            {"event_id": "dispatch-v14", "event_type": "dispatch_queue"},
            {"event_id": "inbox-v14", "event_type": "provider_writeback"},
        ],
    }
