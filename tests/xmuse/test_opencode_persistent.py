from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.agents.launchers import OpenCodeLauncher, build_default_launchers
from xmuse_core.agents.opencode_persistent import (
    RunnerConfig,
    _build_chat_post_message_payload,
    _build_collaboration_response_payload,
    _format_turn_prompt,
    _opencode_command,
    _parse_opencode_json_output,
    _parse_peer_chat_callback_action,
    _post_peer_chat_writeback,
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


def test_peer_chat_prompt_requests_callback_for_collaboration_response(
    tmp_path,
) -> None:
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
                "content": (
                    "Collaboration run `collab_d2e3b35a2af44f0f9e319706d8c98105`: "
                    "review scope and proof boundary only. Confirm whether a single "
                    "lane stays within local runtime contract proof. Record your "
                    "durable collaboration response against the run."
                ),
            },
        },
        "group_chat": {
            "participants": [
                {"role": "review", "display_name": "review-opencode-god"},
            ],
            "recent_messages": [
                {
                    "role": "human",
                    "author": "operator",
                    "content": (
                        "The lane must run exactly "
                        "`uv run pytest tests/xmuse/test_package_boundaries.py -q`."
                    ),
                },
            ],
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context),
    )

    assert "## Structured Callback" in prompt
    assert '"callback_action":"chat_record_collaboration_response"' in prompt
    assert '"run_id":"collab_d2e3b35a2af44f0f9e319706d8c98105"' in prompt
    assert "## Recent Transcript" in prompt
    assert "uv run pytest tests/xmuse/test_package_boundaries.py -q" in prompt
    assert "Do not substitute or invent a different command" in prompt


def test_peer_chat_prompt_requests_callback_for_chinese_collaboration_tool_request(
    tmp_path,
) -> None:
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
                "content": (
                    "请处理协作 run `collab_5fc77b42f7284d47ab5c6d26ea236e3a`。"
                    "请用 `chat_record_collaboration_response` 记录简明审查意见，"
                    "聚焦 proposal 形状是否合规、是否需要 blocker。"
                ),
            },
        },
        "group_chat": {
            "participants": [
                {"role": "review", "display_name": "review-opencode-god"},
            ],
            "recent_messages": [],
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context, ensure_ascii=False),
    )

    assert "## Structured Callback" in prompt
    assert '"callback_action":"chat_record_collaboration_response"' in prompt
    assert '"run_id":"collab_5fc77b42f7284d47ab5c6d26ea236e3a"' in prompt


def test_peer_chat_prompt_requests_callback_for_chinese_collaboration_tool_fill_request(
    tmp_path,
) -> None:
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
                "content": (
                    "请审看协作 run `collab_6b6adc941aa74afb89320099f19a20e1` "
                    "的 proposal 约束是否完整。请用协作响应工具回填你的"
                    "审查结论与任何 blocker。"
                ),
            },
        },
        "group_chat": {
            "participants": [
                {"role": "review", "display_name": "review-opencode-god"},
            ],
            "recent_messages": [],
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context, ensure_ascii=False),
    )

    assert "## Structured Callback" in prompt
    assert '"callback_action":"chat_record_collaboration_response"' in prompt
    assert '"run_id":"collab_6b6adc941aa74afb89320099f19a20e1"' in prompt


def test_parse_peer_chat_callback_action_accepts_strict_collaboration_json() -> None:
    action = _parse_peer_chat_callback_action(
        json.dumps(
            {
                "callback_action": "chat_record_collaboration_response",
                "run_id": "collab_abc123",
                "status": "received",
                "content": "Scope reviewed for baseline.",
                "chat_reply": "Formal review response recorded.",
            }
        )
    )

    assert action == {
        "callback_action": "chat_record_collaboration_response",
        "run_id": "collab_abc123",
        "status": "received",
        "content": "Scope reviewed for baseline.",
        "chat_reply": "Formal review response recorded.",
    }


def test_parse_peer_chat_callback_action_rejects_unexpected_run_id() -> None:
    assert (
        _parse_peer_chat_callback_action(
            json.dumps(
                {
                    "callback_action": "chat_record_collaboration_response",
                    "run_id": "collab_other",
                    "content": "Other response.",
                }
            ),
            expected_run_id="collab_abc123",
        )
        is None
    )


def test_build_collaboration_response_payload_uses_peer_identity() -> None:
    context = {
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "inbox_item": {"id": "inbox_1"},
    }
    action = {
        "callback_action": "chat_record_collaboration_response",
        "run_id": "collab_abc123",
        "status": "received",
        "content": "Scope reviewed for baseline.",
    }

    payload = _build_collaboration_response_payload(
        context=json.dumps(context),
        action=action,
        request_id="req-1",
    )

    assert payload["params"]["name"] == "chat_record_collaboration_response"
    assert payload["id"] == "req-1:collaboration_response"
    assert payload["params"]["arguments"] == {
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "run_id": "collab_abc123",
        "content": "Scope reviewed for baseline.",
        "status": "received",
    }


def test_peer_chat_writeback_records_plain_collaboration_reply(
    tmp_path,
    monkeypatch,
) -> None:
    from xmuse_core.agents import opencode_persistent

    calls: list[dict[str, Any]] = []

    def fake_call_mcp_chat_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append({"port": port, "payload": payload})
        name = payload["params"]["name"]
        if name == "chat_record_collaboration_response":
            return {
                "content": [
                    {
                        "text": json.dumps(
                            {"run": {"run_id": payload["params"]["arguments"]["run_id"]}}
                        )
                    }
                ]
            }
        return {"content": [{"text": json.dumps({"message": {"id": "msg_1"}})}]}

    monkeypatch.setattr(
        opencode_persistent,
        "_call_mcp_chat_tool",
        fake_call_mcp_chat_tool,
    )
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
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "inbox_item": {
            "id": "inbox_1",
            "payload": {
                "content": (
                    "Collaboration run `collab_plain123`: review scope and proof "
                    "boundary only. Record your durable collaboration response "
                    "against the run."
                ),
            },
        },
    }

    result = _post_peer_chat_writeback(
        config=config,
        context=json.dumps(context),
        content="Boundary accepted. No blocker raised.",
        request_id="req-1",
    )

    assert result["tools"] == ["chat_record_collaboration_response", "chat_post_message"]
    assert [call["payload"]["params"]["name"] for call in calls] == [
        "chat_record_collaboration_response",
        "chat_post_message",
    ]
    response_args = calls[0]["payload"]["params"]["arguments"]
    assert response_args["run_id"] == "collab_plain123"
    assert response_args["content"] == "Boundary accepted. No blocker raised."
    message_args = calls[1]["payload"]["params"]["arguments"]
    assert message_args["envelope"]["callback_action"] == (
        "chat_record_collaboration_response"
    )


def test_peer_chat_writeback_records_plain_chinese_collaboration_reply(
    tmp_path,
    monkeypatch,
) -> None:
    from xmuse_core.agents import opencode_persistent

    calls: list[dict[str, Any]] = []

    def fake_call_mcp_chat_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append({"port": port, "payload": payload})
        name = payload["params"]["name"]
        if name == "chat_record_collaboration_response":
            return {
                "content": [
                    {
                        "text": json.dumps(
                            {"run": {"run_id": payload["params"]["arguments"]["run_id"]}}
                        )
                    }
                ]
            }
        return {"content": [{"text": json.dumps({"message": {"id": "msg_1"}})}]}

    monkeypatch.setattr(
        opencode_persistent,
        "_call_mcp_chat_tool",
        fake_call_mcp_chat_tool,
    )
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
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "inbox_item": {
            "id": "inbox_1",
            "payload": {
                "content": (
                    "请处理协作 run `collab_cn123`。"
                    "请用 `chat_record_collaboration_response` 记录简明审查意见。"
                ),
            },
        },
    }

    result = _post_peer_chat_writeback(
        config=config,
        context=json.dumps(context, ensure_ascii=False),
        content="审查通过，无 blocker。",
        request_id="req-cn",
    )

    assert result["tools"] == ["chat_record_collaboration_response", "chat_post_message"]
    assert [call["payload"]["params"]["name"] for call in calls] == [
        "chat_record_collaboration_response",
        "chat_post_message",
    ]
    response_args = calls[0]["payload"]["params"]["arguments"]
    assert response_args["run_id"] == "collab_cn123"
    assert response_args["content"] == "审查通过，无 blocker。"


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
