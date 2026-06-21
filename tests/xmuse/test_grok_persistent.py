from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xmuse_core.agents.grok_persistent as grok_persistent
from xmuse_core.agents.grok_persistent import (
    DEFAULT_GROK_MODEL_ID,
    RunnerConfig,
    _build_chat_post_message_payload,
    _format_turn_prompt,
    _grok_command,
    _parse_grok_json_output,
    _post_peer_chat_writeback,
)


def test_grok_persistent_command_uses_composer_fast_json_form(tmp_path: Path) -> None:
    config = RunnerConfig(
        model=DEFAULT_GROK_MODEL_ID,
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        grok_binary="grok",
        session_id="019ee5ce-d001-74d0-ad38-5915e0d749c1",
    )

    command = _grok_command(config, "reply only")

    assert command == [
        "grok",
        "-m",
        "grok-composer-2.5-fast",
        "-p",
        "reply only",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--no-wait-for-background",
        "--disable-web-search",
        "-r",
        "019ee5ce-d001-74d0-ad38-5915e0d749c1",
        "-w",
        str(tmp_path),
    ]


def test_parse_grok_json_output_collects_text_and_session() -> None:
    stdout = json.dumps(
        {
            "text": "GROK_READY",
            "sessionId": "019ee5ce-d001-74d0-ad38-5915e0d749c1",
            "stopReason": "EndTurn",
        }
    )

    text, session_id = _parse_grok_json_output(stdout)

    assert text == "GROK_READY"
    assert session_id == "019ee5ce-d001-74d0-ad38-5915e0d749c1"


def test_build_chat_post_message_payload_uses_grok_callback_bridge() -> None:
    context = {
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "inbox_item": {"id": "inbox_1"},
    }

    payload = _build_chat_post_message_payload(
        context=json.dumps(context),
        content="Grok peer reply",
        request_id="req-1",
    )

    arguments = payload["params"]["arguments"]
    assert payload["method"] == "tools/call"
    assert payload["params"]["name"] == "chat_post_message"
    assert arguments["conversation_id"] == "conv_1"
    assert arguments["participant_id"] == "part_review"
    assert arguments["god_session_id"] == "god_review"
    assert arguments["reply_to_inbox_item_id"] == "inbox_1"
    assert arguments["envelope"]["writeback_path"] == "grok_callback_bridge"
    assert arguments["envelope"]["request_id"] == "req-1"


def test_peer_chat_prompt_does_not_forward_mcp_tool_instruction(tmp_path: Path) -> None:
    config = RunnerConfig(
        model=DEFAULT_GROK_MODEL_ID,
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        grok_binary="grok",
    )
    context = {
        "inbox_item": {
            "payload": {
                "content": "@review Reply exactly GROK_READY.",
            },
        },
        "group_chat": {
            "participants": [
                {"role": "architect", "display_name": "architect-god"},
                {"role": "review", "display_name": "review-grok-god"},
            ],
            "recent_messages": [
                {"role": "human", "author": "operator", "content": "Please respond."}
            ],
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="call chat_post_message directly with reply_to_inbox_item_id",
        context=json.dumps(context),
    )

    assert "@review Reply exactly GROK_READY." in prompt
    assert "@architect=architect-god" in prompt
    assert "chat_post_message" not in prompt
    assert "Do not call tools." in prompt


def test_peer_chat_writeback_posts_to_mcp_callback(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_call_mcp_platform_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        captured["port"] = port
        captured["payload"] = payload
        return {"content": []}

    monkeypatch.setattr(
        grok_persistent,
        "_call_mcp_platform_tool",
        fake_call_mcp_platform_tool,
    )
    config = RunnerConfig(
        model=DEFAULT_GROK_MODEL_ID,
        mcp_port=8111,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        grok_binary="grok",
    )
    context = json.dumps(
        {
            "conversation_id": "conv_1",
            "participant_id": "part_review",
            "god_session_id": "god_review",
            "inbox_item": {"id": "inbox_1"},
        }
    )

    result = _post_peer_chat_writeback(
        config=config,
        context=context,
        content="Grok durable reply",
        request_id="req-1",
    )

    assert result["status"] == "posted"
    assert captured["port"] == 8111
    args = captured["payload"]["params"]["arguments"]
    assert args["content"] == "Grok durable reply"
    assert args["reply_to_inbox_item_id"] == "inbox_1"
