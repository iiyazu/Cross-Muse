from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xmuse_core.agents import codex_persistent
from xmuse_core.agents.session import LocalSession


def test_codex_persistent_formats_review_prompt_with_context(tmp_path: Path) -> None:
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=900,
    )

    prompt = codex_persistent._format_turn_prompt(
        config,
        msg_type="review",
        prompt="Review lane-1",
        context="Gate report passed.",
    )

    assert "Role: review" in prompt
    assert "Message type: review" in prompt
    assert "Gate report passed." in prompt
    assert "Review lane-1" in prompt
    assert "Verdict: merge" in prompt


def test_codex_persistent_formats_execute_prompt_with_child_result_contract(
    tmp_path: Path,
) -> None:
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="execute",
        timeout_s=900,
    )

    prompt = codex_persistent._format_turn_prompt(
        config,
        msg_type="execute",
        prompt=(
            "## Persistent Execute Routing\n\n"
            "- execute_request_id: execute-conv-feature-lane-a\n\n"
            "Implement lane."
        ),
        context=(
            "## Feature Context\n\n"
            "- Feature scope id: feature-alpha\n\n"
            "## Lane Execution Context\n\n"
            "- Lane ID: lane-a"
        ),
    )

    assert "Role: execute" in prompt
    assert "Message type: execute" in prompt
    assert "execute_request_id: execute-conv-feature-lane-a" in prompt
    assert "Lane ID: lane-a" in prompt
    assert "Feature scope id: feature-alpha" in prompt
    assert "expected result contract" in prompt
    assert "artifacts.execute_result" in prompt
    assert "lane_request_id" in prompt
    assert "exit_code" in prompt
    assert "If MCP tools are not exposed" in prompt
    assert "stdout fallback" in prompt
    assert "exit with status 0" in prompt
    assert "exit non-zero" in prompt


def test_codex_peer_chat_uses_layered_xmuse_prompt_when_present(tmp_path: Path) -> None:
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="architect",
        timeout_s=900,
    )
    context = json.dumps(
        {
            "xmuse_prompt": {
                "version": "xmuse-peer-chat-prompt-v2",
                "text": "## xmuse_governance_l0\n\nDurable chat state is reply truth.\n",
            }
        }
    )

    prompt = codex_persistent._format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="legacy fallback",
        context=context,
    )

    assert prompt == "## xmuse_governance_l0\n\nDurable chat state is reply truth.\n"
    assert "legacy fallback" not in prompt


def test_codex_persistent_run_turn_emits_protocol_result(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    captured = {}

    def fake_run_codex_exec(config, full_prompt):
        captured["config"] = config
        captured["prompt"] = full_prompt
        return subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout="Findings: none\nVerdict: merge\n",
            stderr="",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.4",
        mcp_port=8123,
        worktree=tmp_path,
        role="review",
        timeout_s=123,
    )

    codex_persistent._run_codex_turn(
        config,
        {"type": "review", "prompt": "Review this", "context": "ctx"},
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "result"
    assert payload["status"] == "success"
    assert payload["message"] == "Findings: none\nVerdict: merge\n"
    assert payload["artifacts"]["message_type"] == "review"
    assert codex_persistent._codex_command(config) == [
        "codex",
        "exec",
        "-m",
        "gpt-5.4",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        'mcp_servers.xmuse-platform.type="sse"',
        "-c",
        'mcp_servers.xmuse-platform.url="http://localhost:8123/sse"',
        "-C",
        str(tmp_path),
    ]
    assert captured["config"] == config
    assert "Review this" in captured["prompt"]


def test_codex_persistent_execute_success_includes_structured_result_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_run_codex_exec(config, full_prompt):
        return subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout="child worker completed\n",
            stderr="",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="execute",
        timeout_s=123,
    )

    codex_persistent._run_codex_turn(
        config,
        {
            "type": "execute",
            "prompt": "- execute_request_id: execute-conv-feature-lane-a",
            "context": "- Lane ID: lane-a",
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "result"
    execute_result = payload["artifacts"]["execute_result"]
    assert execute_result["lane_request_id"] == "execute-conv-feature-lane-a"
    assert execute_result["execute_request_id"] == "execute-conv-feature-lane-a"
    assert execute_result["lane_id"] == "lane-a"
    assert execute_result["exit_code"] == 0
    assert execute_result["stdout"] == "child worker completed\n"
    assert execute_result["stderr"] == ""
    assert execute_result["timed_out"] is False


def test_codex_persistent_execute_failure_includes_structured_error_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_run_codex_exec(config, full_prompt):
        return subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=2,
            stdout="",
            stderr="child worker failed\n",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="execute",
        timeout_s=123,
    )

    codex_persistent._run_codex_turn(
        config,
        {
            "type": "execute",
            "prompt": "- execute_request_id: execute-conv-feature-lane-a",
            "context": "- Lane ID: lane-a",
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "error"
    assert payload["code"] == "codex_exit_2"
    execute_result = payload["artifacts"]["execute_result"]
    assert execute_result["lane_request_id"] == "execute-conv-feature-lane-a"
    assert execute_result["exit_code"] == 2
    assert execute_result["stderr"] == "child worker failed\n"
    assert execute_result["timed_out"] is False


def test_codex_persistent_execute_timeout_error_includes_runner_returncode(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_run_codex_exec(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["codex", "exec"],
            timeout=1,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="execute",
        timeout_s=1,
    )

    codex_persistent._run_codex_turn(
        config,
        {
            "type": "execute",
            "lane_request_id": "execute-conv-feature-lane-timeout",
            "lane_id": "lane-timeout",
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "error"
    assert payload["code"] == "codex_timeout"
    assert payload["artifacts"]["returncode"] == 1
    assert payload["artifacts"]["message_type"] == "execute"
    execute_result = payload["artifacts"]["execute_result"]
    assert execute_result["lane_request_id"] == "execute-conv-feature-lane-timeout"
    assert execute_result["lane_id"] == "lane-timeout"
    assert execute_result["exit_code"] == 1
    assert execute_result["transport_error"] == "codex_timeout"
    assert execute_result["timed_out"] is True


def test_codex_persistent_execute_spawn_error_includes_runner_returncode(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_run_codex_exec(*args, **kwargs):
        raise OSError("codex missing")

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="execute",
        timeout_s=1,
    )

    codex_persistent._run_codex_turn(
        config,
        {
            "type": "execute",
            "lane_request_id": "execute-conv-feature-lane-spawn",
            "lane_id": "lane-spawn",
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "error"
    assert payload["code"] == "codex_spawn_failed"
    assert payload["artifacts"]["returncode"] == 1
    assert payload["artifacts"]["message_type"] == "execute"
    execute_result = payload["artifacts"]["execute_result"]
    assert execute_result["lane_request_id"] == "execute-conv-feature-lane-spawn"
    assert execute_result["lane_id"] == "lane-spawn"
    assert execute_result["exit_code"] == 1
    assert execute_result["transport_error"] == "codex_spawn_failed"
    assert execute_result["timed_out"] is False


def test_codex_persistent_run_turn_emits_timeout_error_for_review(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_run_codex_exec(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["codex", "exec"],
            timeout=1,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="architect",
        timeout_s=1,
    )

    codex_persistent._run_codex_turn(config, {"type": "review"})

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "error"
    assert payload["code"] == "codex_timeout"
    assert payload["artifacts"]["message_type"] == "review"


def test_codex_persistent_peer_chat_nudge_emits_transport_errors(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls = 0

    def fake_run_codex_exec(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(
            cmd=["codex", "exec"],
            timeout=1,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run_codex_exec)
    config = codex_persistent.RunnerConfig(
        model="gpt-5.5",
        mcp_port=8100,
        worktree=tmp_path,
        role="architect",
        timeout_s=1,
    )

    codex_persistent._run_codex_turn(
        config,
        {
            "type": "peer_chat_nudge",
            "request_id": "inbox-1",
        },
    )

    assert calls == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "error"
    assert payload["code"] == "codex_timeout"
    assert payload["request_id"] == "inbox-1"
    assert payload["artifacts"]["message_type"] == "peer_chat_nudge"


def test_codex_persistent_shutdown_signal_terminates_active_child(monkeypatch) -> None:
    calls: list[tuple[str, int, int | None]] = []

    class FakeProcess:
        pid = 12345

        def __init__(self) -> None:
            self.returncode = None
            self.wait_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            calls.append(("terminate", self.pid, None))

        def kill(self) -> None:
            calls.append(("kill", self.pid, None))
            self.returncode = -9

        def wait(self, timeout=None):
            self.wait_calls += 1
            calls.append(("wait", self.pid, timeout))
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd=["codex"], timeout=timeout)
            self.returncode = -9
            return self.returncode

    process = FakeProcess()

    def fake_killpg(pid, signum):
        calls.append(("killpg", pid, signum))

    monkeypatch.setattr(codex_persistent.os, "killpg", fake_killpg)
    monkeypatch.setattr(codex_persistent, "_ACTIVE_CHILD", process)

    with pytest.raises(SystemExit) as exc:
        codex_persistent._handle_shutdown_signal(15, None)

    assert exc.value.code == 143
    assert ("killpg", 12345, 15) in calls
    assert ("killpg", 12345, 9) in calls


@pytest.mark.asyncio
async def test_codex_persistent_module_speaks_local_session_protocol(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "prompt = sys.stdin.read()\n"
        "print('Findings: none')\n"
        "print('Verdict: merge')\n"
        "print('PROMPT_HAS_CONTEXT=' + str('Gate report passed.' in prompt))\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    session = await LocalSession.spawn(
        [
            sys.executable,
            "-m",
            "xmuse_core.agents.codex_persistent",
            "--model",
            "gpt-test",
            "--mcp-port",
            "8123",
            "--worktree",
            str(tmp_path),
            "--role",
            "review",
            "--timeout-s",
            "5",
        ],
        env=env,
    )
    try:
        await session.send_typed("hello", protocol_version="1.0")
        hello = await session.receive()
        assert hello is not None
        assert hello.type == "hello_ack"
        assert hello.protocol_version == "1.0"

        await session.send_typed(
            "review",
            prompt="Review lane-1.",
            context="Gate report passed.",
        )
        result = await session.receive()
        assert result is not None
        assert result.type == "result"
        assert result.status == "success"
        assert "Verdict: merge" in str(result.message)
        assert "PROMPT_HAS_CONTEXT=True" in str(result.message)
        assert result.artifacts["message_type"] == "review"
    finally:
        if session.is_alive():
            await session.abort(grace_period=2.0)
