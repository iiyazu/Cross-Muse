from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xmuse_core.agents.opencode_persistent as opencode_persistent
from xmuse_core.agents.launchers import OpenCodeLauncher, build_default_launchers
from xmuse_core.agents.opencode_persistent import (
    RunnerConfig,
    _build_chat_post_message_payload,
    _build_collaboration_response_payload,
    _build_review_update_lane_status_payload,
    _filter_review_evidence_refs,
    _format_turn_prompt,
    _opencode_command,
    _parse_opencode_json_output,
    _parse_peer_chat_callback_action,
    _parse_review_callback_action,
    _post_peer_chat_writeback,
    _post_review_writeback,
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


def test_peer_chat_prompt_requests_structured_callback_for_collaboration_response(
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
                    "@review For collaboration run "
                    "`collab_abc123`, record a formal collaboration response."
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
    assert '"run_id":"collab_abc123"' in prompt
    assert "Return exactly one JSON object and no markdown" in prompt
    assert "Return only the structured JSON object requested above" in prompt
    assert "## Recent Transcript" in prompt
    assert "uv run pytest tests/xmuse/test_package_boundaries.py -q" in prompt
    assert "Do not substitute or invent a different command" in prompt
    assert "concise natural-language content" not in prompt


def test_peer_chat_prompt_requests_callback_for_formal_review_response(
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
                    "For collaboration run `collab_review123`, please record "
                    "a formal review response that preserves the exact command."
                ),
            },
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context),
    )

    assert "## Structured Callback" in prompt
    assert '"run_id":"collab_review123"' in prompt
    assert "chat_record_collaboration_response" in prompt


def test_peer_chat_prompt_requests_callback_for_durable_review_response(
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
                    "Please review collaboration `collab_durable123` for scope "
                    "and proof boundary. Record your response durably on the "
                    "collaboration run."
                ),
            },
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context),
    )

    assert "## Structured Callback" in prompt
    assert '"run_id":"collab_durable123"' in prompt
    assert "chat_record_collaboration_response" in prompt


def test_review_prompt_requests_update_lane_status_callback(tmp_path) -> None:
    (tmp_path / "feature_lanes.json").write_text("{}", encoding="utf-8")
    gate_report = tmp_path / "logs" / "gates" / "lane-review-callback" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text("{}", encoding="utf-8")
    config = RunnerConfig(
        model="opencode-go/deepseek-v4-flash",
        variant="max",
        mcp_port=8100,
        worktree=tmp_path,
        role="review",
        timeout_s=30,
        opencode_binary="opencode",
    )

    prompt = _format_turn_prompt(
        config,
        msg_type="review",
        prompt=(
            "Review the lane.\n\n## Persistent Review Routing\n\n"
            "- review_request_id: review-req-1\n"
        ),
        context=(
            "## Lane Review Context\n\n"
            "- Lane ID: lane-review-callback\n\n"
            "Gate report: logs/gates/lane-review-callback/report.json\n"
        ),
    )

    assert "## Structured Review Callback" in prompt
    assert '"callback_action":"review_update_lane_status"' in prompt
    assert '"lane_id":"lane-review-callback"' in prompt
    assert '"request_id":"review-req-1"' in prompt
    assert "feature_lanes.json#lane=lane-review-callback" in prompt
    assert "logs/gates/lane-review-callback/report.json" in prompt
    assert "Stdout alone is not review truth" in prompt


def test_review_evidence_ref_filter_drops_missing_local_artifacts(tmp_path) -> None:
    (tmp_path / "feature_lanes.json").write_text("{}", encoding="utf-8")
    prompt_ref = tmp_path / "logs" / "lane_prompts" / "lane-review-callback.md"
    prompt_ref.parent.mkdir(parents=True)
    prompt_ref.write_text("review prompt", encoding="utf-8")
    weak_cache_ref = tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids"
    weak_cache_ref.parent.mkdir(parents=True)
    weak_cache_ref.write_text("[]", encoding="utf-8")

    assert _filter_review_evidence_refs(
        [
            "feature_lanes.json#lane=lane-review-callback",
            "logs/lane_prompts/lane-review-callback.md",
            "logs/gates/lane-review-callback/report.json",
            str(weak_cache_ref),
        ],
        root=tmp_path,
    ) == [
        "feature_lanes.json#lane=lane-review-callback",
        "logs/lane_prompts/lane-review-callback.md",
    ]


def test_review_writeback_falls_back_when_provider_refs_are_weak(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "feature_lanes.json").write_text("{}", encoding="utf-8")
    spawn_ref = tmp_path / "logs" / "agent_spawns" / "lane-review-callback" / (
        "20260618T104545Z.stdout.log"
    )
    spawn_ref.parent.mkdir(parents=True)
    spawn_ref.write_text("16 passed", encoding="utf-8")
    weak_ref = tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids"
    weak_ref.parent.mkdir(parents=True)
    weak_ref.write_text("[]", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_call_mcp_platform_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        captured["port"] = port
        captured["payload"] = payload
        return {"content": []}

    monkeypatch.setattr(
        opencode_persistent,
        "_call_mcp_platform_tool",
        fake_call_mcp_platform_tool,
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
    context = "\n".join(
        [
            "- Lane ID: lane-review-callback",
            "logs/agent_spawns/lane-review-callback/20260618T104545Z.stdout.log",
        ]
    )

    result = _post_review_writeback(
        config=config,
        context=context,
        request_id="review-req-1",
        content=json.dumps(
            {
                "callback_action": "review_update_lane_status",
                "lane_id": "lane-review-callback",
                "status": "reviewed",
                "current_status": "gated",
                "summary": "Reviewed bounded evidence.",
                "request_id": "review-req-1",
                "evidence_refs": [str(weak_ref)],
            }
        ),
    )

    assert result is not None
    assert captured["port"] == 8100
    args = captured["payload"]["params"]["arguments"]
    assert args["metadata"]["review_evidence_refs"] == [
        "feature_lanes.json#lane=lane-review-callback",
        "logs/agent_spawns/lane-review-callback/20260618T104545Z.stdout.log",
    ]


def test_review_writeback_supplements_context_refs_with_current_spawn_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "feature_lanes.json").write_text("{}", encoding="utf-8")
    lane_context = tmp_path / "logs" / "lane_context" / "lane-review-callback" / "latest.json"
    lane_context.parent.mkdir(parents=True)
    lane_context.write_text("{}", encoding="utf-8")
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-review-callback"
    spawn_dir.mkdir(parents=True)
    (spawn_dir / "20260618T112357Z.stdout.log").write_text("16 passed", encoding="utf-8")
    (spawn_dir / "20260618T112357Z.result.json").write_text("{}", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_call_mcp_platform_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {"content": []}

    monkeypatch.setattr(
        opencode_persistent,
        "_call_mcp_platform_tool",
        fake_call_mcp_platform_tool,
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

    result = _post_review_writeback(
        config=config,
        context="\n".join(
            [
                "- Lane ID: lane-review-callback",
                "logs/lane_context/lane-review-callback/latest.json",
            ]
        ),
        request_id="review-req-1",
        content=json.dumps(
            {
                "callback_action": "review_update_lane_status",
                "lane_id": "lane-review-callback",
                "status": "reviewed",
                "current_status": "gated",
                "summary": "Reviewed bounded evidence.",
                "request_id": "review-req-1",
                "evidence_refs": [
                    "feature_lanes.json#lane=lane-review-callback",
                    "logs/lane_context/lane-review-callback/latest.json",
                ],
            }
        ),
    )

    assert result is not None
    args = captured["payload"]["params"]["arguments"]
    assert args["metadata"]["review_evidence_refs"] == [
        "feature_lanes.json#lane=lane-review-callback",
        "logs/lane_context/lane-review-callback/latest.json",
        "logs/agent_spawns/lane-review-callback/20260618T112357Z.stdout.log",
        "logs/agent_spawns/lane-review-callback/20260618T112357Z.result.json",
    ]


def test_review_callback_action_builds_update_lane_status_payload() -> None:
    action = _parse_review_callback_action(
        json.dumps(
            {
                "callback_action": "review_update_lane_status",
                "lane_id": "lane-review-callback",
                "status": "reviewed",
                "current_status": "gated",
                "summary": "Reviewed the bounded lane evidence.",
                "request_id": "review-req-1",
                "evidence_refs": [
                    "feature_lanes.json#lane=lane-review-callback",
                    "feature_lanes.json#lane=lane-review-callback",
                ],
            }
        ),
        expected_lane_id="lane-review-callback",
        fallback_request_id="fallback-req",
        fallback_evidence_refs=[],
    )

    assert action == {
        "callback_action": "review_update_lane_status",
        "lane_id": "lane-review-callback",
        "status": "reviewed",
        "current_status": "gated",
        "summary": "Reviewed the bounded lane evidence.",
        "request_id": "review-req-1",
        "evidence_refs": ["feature_lanes.json#lane=lane-review-callback"],
    }

    payload = _build_review_update_lane_status_payload(
        action=action,
        request_id="review-req-1",
    )

    assert payload["params"]["name"] == "update_lane_status"
    args = payload["params"]["arguments"]
    assert args["lane_id"] == "lane-review-callback"
    assert args["status"] == "reviewed"
    assert args["guard"] == {"current_status": "gated"}
    assert args["audit"]["actor"] == "opencode-review-callback"
    metadata = args["metadata"]
    assert metadata["review_evidence_refs"] == [
        "feature_lanes.json#lane=lane-review-callback"
    ]
    assert metadata["review_provider_summary"] == "Reviewed the bounded lane evidence."
    assert metadata["review_summary_proof_level"] == (
        "provider_prose_bounded_by_evidence_refs"
    )
    assert metadata["review_summary"] == "Reviewed the bounded lane evidence."


def test_review_writeback_bounds_success_summary_and_preserves_provider_prose(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "feature_lanes.json").write_text("{}", encoding="utf-8")
    lane_context = tmp_path / "logs" / "lane_context" / "lane-review-callback" / "latest.json"
    lane_context.parent.mkdir(parents=True)
    lane_context.write_text("{}", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_call_mcp_platform_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {"content": []}

    monkeypatch.setattr(
        opencode_persistent,
        "_call_mcp_platform_tool",
        fake_call_mcp_platform_tool,
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
    provider_summary = (
        "All checks passed: test_package_boundaries.py 16 passed; "
        "new test_peer_chat_review_trigger.py 1 passed; diff scoped and correct."
    )

    result = _post_review_writeback(
        config=config,
        context="\n".join(
            [
                "- Lane ID: lane-review-callback",
                "logs/lane_context/lane-review-callback/latest.json",
            ]
        ),
        request_id="review-req-1",
        content=json.dumps(
            {
                "callback_action": "review_update_lane_status",
                "lane_id": "lane-review-callback",
                "status": "reviewed",
                "current_status": "gated",
                "summary": provider_summary,
                "request_id": "review-req-1",
                "evidence_refs": [
                    "feature_lanes.json#lane=lane-review-callback",
                    "logs/lane_context/lane-review-callback/latest.json",
                ],
            }
        ),
    )

    assert result is not None
    args = captured["payload"]["params"]["arguments"]
    metadata = args["metadata"]
    assert metadata["review_provider_summary"] == provider_summary
    assert "test_peer_chat_review_trigger" not in metadata["review_summary"]
    assert "diff scoped and correct" not in metadata["review_summary"]
    assert "durable evidence refs:" in metadata["review_summary"]
    assert metadata["review_summary_proof_level"] == (
        "provider_prose_bounded_by_evidence_refs"
    )
    assert args["audit"]["reason"] == metadata["review_summary"]


def test_peer_chat_prompt_requests_callback_for_respond_on_collaboration(
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
                    "Please respond on collaboration `collab_respond123` with "
                    "scope and proof-boundary review for one eventual lane_graph "
                    "proposal only."
                ),
            },
        },
    }

    prompt = _format_turn_prompt(
        config,
        msg_type="peer_chat_nudge",
        prompt="fallback",
        context=json.dumps(context),
    )

    assert "## Structured Callback" in prompt
    assert '"run_id":"collab_respond123"' in prompt
    assert "chat_record_collaboration_response" in prompt


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


def test_parse_peer_chat_callback_action_accepts_final_markdown_callback() -> None:
    action = _parse_peer_chat_callback_action(
        "\n".join(
            [
                "```json",
                json.dumps(
                    {
                        "callback_action": "chat_record_collaboration_response",
                        "run_id": "collab_abc123",
                        "status": "received",
                        "content": "Initial response.",
                    }
                ),
                "```",
                "Let me correct the formal response.",
                "```json",
                json.dumps(
                    {
                        "callback_action": "chat_record_collaboration_response",
                        "run_id": "collab_abc123",
                        "status": "received",
                        "content": "Final response.",
                        "chat_reply": "Recorded final response.",
                    }
                ),
                "```",
            ]
        ),
        expected_run_id="collab_abc123",
    )

    assert action == {
        "callback_action": "chat_record_collaboration_response",
        "run_id": "collab_abc123",
        "status": "received",
        "content": "Final response.",
        "chat_reply": "Recorded final response.",
    }


def test_parse_peer_chat_callback_action_rejects_conflicting_run_ids() -> None:
    assert (
        _parse_peer_chat_callback_action(
            "\n".join(
                [
                    json.dumps(
                        {
                            "callback_action": "chat_record_collaboration_response",
                            "run_id": "collab_abc123",
                            "content": "First response.",
                        }
                    ),
                    json.dumps(
                        {
                            "callback_action": "chat_record_collaboration_response",
                            "run_id": "collab_other",
                            "content": "Other response.",
                        }
                    ),
                ]
            )
        )
        is None
    )


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


def test_parse_peer_chat_callback_action_rejects_plain_chat_text() -> None:
    assert (
        _parse_peer_chat_callback_action(
            "Scope reviewed for baseline; status received."
        )
        is None
    )


def test_peer_chat_writeback_formalizes_plain_collaboration_response(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_mcp_chat_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"content": []}

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
                    "Please respond on `collab_plain123` confirming that the "
                    "registered OpenCode review participant should be selected "
                    "by setting `review_runtime=opencode`."
                )
            },
        },
    }

    result = _post_peer_chat_writeback(
        config=config,
        context=json.dumps(context),
        content="Review readiness: READY for this bounded lane.",
        request_id="req-plain",
    )

    assert result["status"] == "ok"
    assert result["tools"] == ["chat_record_collaboration_response", "chat_post_message"]
    assert result["synthesized_collaboration_response"] is True
    assert [call["params"]["name"] for call in calls] == [
        "chat_record_collaboration_response",
        "chat_post_message",
    ]
    response_args = calls[0]["params"]["arguments"]
    assert response_args["run_id"] == "collab_plain123"
    assert response_args["content"] == "Review readiness: READY for this bounded lane."
    message_args = calls[1]["params"]["arguments"]
    assert message_args["content"] == "Review readiness: READY for this bounded lane."
    assert message_args["envelope"]["callback_action"] == (
        "chat_record_collaboration_response"
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
    arguments = payload["params"]["arguments"]
    assert arguments == {
        "conversation_id": "conv_1",
        "participant_id": "part_review",
        "god_session_id": "god_review",
        "run_id": "collab_abc123",
        "content": "Scope reviewed for baseline.",
        "status": "received",
    }


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
