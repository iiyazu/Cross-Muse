from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.agents.launchers import OpenCodeLauncher, build_default_launchers
from xmuse_core.agents.opencode_persistent import (
    RunnerConfig,
    _build_chat_post_message_payload,
    _format_turn_prompt,
    _opencode_command,
    _parse_opencode_json_output,
)
from xmuse_core.agents.registry import AgentRuntime


def test_default_launchers_include_opencode_persistent_launcher() -> None:
    launchers = build_default_launchers(mcp_port=8111)

    launcher = launchers[AgentRuntime.OPENCODE]
    assert isinstance(launcher, OpenCodeLauncher)
    assert launcher.supports_persistent_sessions is True
    assert launcher.persistent_model() == "opencode-go/deepseek-v4-flash"
    assert "--mcp-port" in launcher.build_persistent_command("review", Path("."))


def test_opencode_persistent_command_uses_canonical_run_form_and_session(tmp_path) -> None:
    config = RunnerConfig(
        model="opencode-go/deepseek-v4-flash",
        variant="max",
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        opencode_binary="opencode",
        session_id="ses_123",
    )

    command = _opencode_command(config, "reply only")

    assert command == [
        "opencode",
        "run",
        "--model",
        "opencode-go/deepseek-v4-flash",
        "--variant",
        "max",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
        "--session",
        "ses_123",
        "reply only",
    ]


def test_parse_opencode_json_output_collects_text_and_session() -> None:
    stdout = "\n".join(
        [
            '{"type":"step_start","sessionID":"ses_abc","part":{"type":"step-start"}}',
            (
                '{"type":"text","sessionID":"ses_abc",'
                '"part":{"type":"text","text":"OPENCODE"}}'
            ),
            (
                '{"type":"text","sessionID":"ses_abc",'
                '"part":{"type":"text","text":"_READY"}}'
            ),
        ]
    )

    text, session_id = _parse_opencode_json_output(stdout)

    assert text == "OPENCODE_READY"
    assert session_id == "ses_abc"


def test_build_chat_post_message_payload_uses_callback_bridge_envelope() -> None:
    context = {
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "inbox_item": {"id": "inbox_1"},
    }

    payload = _build_chat_post_message_payload(
        context=json.dumps(context),
        content="Review GOD reply",
        request_id="req-1",
    )

    arguments = payload["params"]["arguments"]
    assert payload["method"] == "tools/call"
    assert payload["params"]["name"] == "chat_post_message"
    assert arguments["conversation_id"] == "conv_1"
    assert arguments["participant_id"] == "part_review"
    assert arguments["god_session_id"] == "god_review"
    assert arguments["reply_to_inbox_item_id"] == "inbox_1"
    assert arguments["envelope"]["writeback_path"] == "opencode_callback_bridge"


def test_peer_chat_prompt_does_not_forward_codex_mcp_tool_instruction(tmp_path) -> None:
    config = RunnerConfig(
        model="opencode-go/deepseek-v4-flash",
        variant="max",
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        opencode_binary="opencode",
    )
    context = {
        "inbox_item": {
            "payload": {
                "content": "@review Reply exactly OPENCODE_READY.",
            },
        },
        "group_chat": {
            "participants": [
                {"role": "architect", "display_name": "architect-god"},
                {"role": "review", "display_name": "review-opencode-god"},
            ],
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="call chat_post_message directly with reply_to_inbox_item_id",
        context=json.dumps(context),
    )

    assert "@review Reply exactly OPENCODE_READY." in prompt
    assert "@architect=architect-god" in prompt
    assert "chat_post_message" not in prompt
    assert "Do not call tools." in prompt


def test_opencode_run_does_not_inherit_persistent_control_stdin(
    tmp_path,
    monkeypatch,
) -> None:
    from xmuse_core.agents import opencode_persistent

    captured: dict[str, Any] = {}

    class FakeProcess:
        args = ["opencode"]
        returncode = 0

        def communicate(self, timeout):
            return (
                '{"type":"text","sessionID":"ses_1",'
                '"part":{"type":"text","text":"READY"}}\n',
                "",
            )

        def poll(self):
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(opencode_persistent.subprocess, "Popen", fake_popen)
    config = RunnerConfig(
        model="opencode-go/deepseek-v4-flash",
        variant="max",
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        opencode_binary="opencode",
    )

    result = opencode_persistent._run_opencode(config, "reply")

    assert result.reply_text == "READY"
    assert captured["kwargs"]["stdin"] is opencode_persistent.subprocess.DEVNULL
