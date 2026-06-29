from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import run_fullchain_docs_sentinel as sentinel
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.store import ChatStore


def test_wait_for_lane_treats_exec_failed_as_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-exec-failed",
                        "status": "exec_failed",
                        "failure_reason": "execution_infra_unavailable",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fail_on_sleep(_seconds: float) -> None:
        raise AssertionError("exec_failed should be treated as terminal")

    monkeypatch.setattr(sentinel.time, "sleep", fail_on_sleep)

    lane = sentinel._wait_for_lane(
        lanes_path,
        feature_id="lane-exec-failed",
        timeout_s=30,
    )

    assert lane["status"] == "exec_failed"


def test_main_writes_expected_note_content_into_command_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run-root"
    execution_worktree = tmp_path / "execution-worktree"
    feature_id = "docs-sentinel-note"
    repo_head_sha_calls = 0

    def fake_repo_head_sha() -> str:
        nonlocal repo_head_sha_calls
        repo_head_sha_calls += 1
        return "abc123repohead"

    monkeypatch.setattr(
        sentinel,
        "_parse_args",
        lambda: argparse.Namespace(
            run_root=run_root,
            execution_worktree=execution_worktree,
            feature_id=feature_id,
            lane_kind="docs",
            target_path=None,
            expected_content=None,
            chat_port=43111,
            mcp_port=43112,
            proposal_timeout_s=900.0,
            proposal_review_timeout_s=900.0,
            lane_timeout_s=1200.0,
            max_hours=0.75,
            architect_model="gpt-5.4",
            executor_model="gpt-5.4-mini",
            peer_chat_response_wait_s=sentinel.DEFAULT_PEER_CHAT_RESPONSE_WAIT_S,
            peer_chat_post_writeback_grace_s=sentinel.DEFAULT_PEER_CHAT_POST_WRITEBACK_GRACE_S,
            peer_god_backend="ray",
            ray_god_mcp=True,
            review_provider="auto",
        ),
    )
    monkeypatch.setattr(sentinel, "_repo_head_sha", fake_repo_head_sha)
    monkeypatch.setattr(
        sentinel,
        "_provider_readiness",
        lambda *, review_provider_policy, ray_god_mcp: {
            "providers": {
                "codex": {"available": True},
                "opencode": {"available": False},
            },
            "mcp": {"ray_god_mcp_enabled": ray_god_mcp},
            "review_provider_selection": {
                "policy": review_provider_policy,
                "selected_provider": "codex",
                "fallback_reason": "opencode_unavailable",
            },
        },
    )

    def stop_after_command_artifacts(*_args, **_kwargs):
        raise RuntimeError("stop after commands")

    monkeypatch.setattr(sentinel, "_start_chat_api", stop_after_command_artifacts)

    assert sentinel.main() == 1

    commands_json = json.loads(
        (run_root / "loop_driver_artifacts" / "commands.json").read_text(
            encoding="utf-8"
        )
    )
    commands_txt = (run_root / "commands.txt").read_text(encoding="utf-8")
    expected_note_content = sentinel._expected_note_content(feature_id)

    assert repo_head_sha_calls == 1
    assert commands_json["expected_note_content"] == expected_note_content
    assert commands_json["expected_content"] == expected_note_content
    assert commands_json["lane_kind"] == "docs"
    assert commands_json["target_path"] == f"docs/xmuse/{feature_id}.md"
    assert commands_json["repo_head_sha"] == "abc123repohead"
    assert commands_json["peer_chat_response_wait_s"] == 900.0
    assert commands_json["peer_chat_post_writeback_grace_s"] == 8.0
    assert commands_json["peer_god_backend"] == "ray"
    assert commands_json["ray_god_mcp"] is True
    assert commands_json["review_provider_policy"] == "auto"
    assert commands_json["selected_review_provider"] == "codex"
    assert commands_json["review_provider_fallback_reason"] == "opencode_unavailable"
    provider_readiness = json.loads(
        (run_root / "loop_driver_artifacts" / "provider_readiness.json").read_text(
            encoding="utf-8"
        )
    )
    assert provider_readiness["review_provider_selection"] == {
        "policy": "auto",
        "selected_provider": "codex",
        "fallback_reason": "opencode_unavailable",
    }
    assert f"expected_note_content={expected_note_content}\n" in commands_txt
    assert "repo_head_sha=abc123repohead\n" in commands_txt
    assert "peer_chat_response_wait_s=900.0\n" in commands_txt
    assert "peer_chat_post_writeback_grace_s=8.0\n" in commands_txt
    assert "peer_god_backend=ray\n" in commands_txt
    assert "ray_god_mcp=True\n" in commands_txt
    assert "selected_review_provider=codex\n" in commands_txt


def test_target_spec_defaults_to_docs_sentinel_path_and_content() -> None:
    target = sentinel._target_spec(
        feature_id="docs-target",
        lane_kind="docs",
        target_path=None,
        expected_content=None,
    )

    assert target == {
        "path": "docs/xmuse/docs-target.md",
        "expected_content": (
            "Post-main fullchain sentinel docs-target reached isolated execution."
        ),
    }


def test_target_spec_requires_explicit_code_artifact() -> None:
    with pytest.raises(ValueError, match="--target-path is required"):
        sentinel._target_spec(
            feature_id="code-target",
            lane_kind="code",
            target_path=None,
            expected_content="value = 1",
        )
    with pytest.raises(ValueError, match="--expected-content is required"):
        sentinel._target_spec(
            feature_id="code-target",
            lane_kind="code",
            target_path="src/xmuse_core/code_target.py",
            expected_content=None,
        )


def test_code_lane_demand_names_code_boundary() -> None:
    demand = sentinel._sentinel_demand(
        feature_id="code-target",
        lane_kind="code",
        target_path="src/xmuse_core/code_target.py",
        expected_content='SENTINEL = "code-target"',
        provider_readiness={
            "review_provider_selection": {
                "selected_provider": "codex",
                "fallback_reason": "opencode_unavailable",
            }
        },
    )

    assert "real low-risk xmuse code-change runtime sentinel" in demand
    assert "not a docs-only sentinel" in demand
    assert "src/xmuse_core/code_target.py" in demand
    assert 'SENTINEL = "code-target"' in demand
    assert "opencode_unavailable" in demand


@pytest.mark.parametrize(
    ("peer_god_backend", "ray_god_mcp", "expected_ray_god_mcp"),
    [
        ("native", False, "0"),
        ("ray", True, "1"),
    ],
)
def test_start_runner_uses_configured_peer_chat_writeback_grace(
    tmp_path: Path,
    monkeypatch,
    peer_god_backend: str,
    ray_god_mcp: bool,
    expected_ray_god_mcp: str,
) -> None:
    captured: dict[str, object] = {}

    def fake_spawn(command, *, env, stdout_path):
        captured["command"] = command
        captured["env"] = env
        captured["stdout_path"] = stdout_path
        return object()

    monkeypatch.setattr(sentinel, "_spawn", fake_spawn)

    result = sentinel._start_runner(
        run_root=tmp_path / "run-root",
        mcp_port=43112,
        chat_port=43111,
        logs_dir=tmp_path / "logs",
        max_hours=0.75,
        peer_chat_response_wait_s=456.0,
        peer_chat_post_writeback_grace_s=13.5,
        peer_god_backend=peer_god_backend,
        ray_god_mcp=ray_god_mcp,
    )

    command = captured["command"]
    assert result is not None
    assert isinstance(command, list)
    wait_flag_index = command.index("--peer-chat-response-wait-s")
    assert command[wait_flag_index + 1] == "456.0"
    flag_index = command.index("--peer-chat-post-writeback-grace-s")
    assert command[flag_index + 1] == "13.5"
    backend_flag_index = command.index("--peer-god-backend")
    assert command[backend_flag_index + 1] == peer_god_backend
    env = captured["env"]
    assert env["XMUSE_PEER_GOD_BACKEND"] == peer_god_backend
    assert env["XMUSE_REVIEW_GOD_BACKEND"] == peer_god_backend
    assert env["XMUSE_EXECUTE_GOD_BACKEND"] == peer_god_backend
    assert env["XMUSE_RAY_GOD_MCP"] == expected_ray_god_mcp


def test_wait_for_proposal_review_trigger_waits_until_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Review wait")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="architect",
        proposal_type="lane_graph",
        content=json.dumps({"summary": "review me", "lanes": []}),
        references=["collaboration:run-1"],
    )
    message = chat.add_message(
        conv.id,
        "architect",
        "assistant",
        "[proposal] review me",
        envelope_type="proposal",
        envelope_json={"proposal_id": proposal.id},
    )
    inbox = ChatInboxStore(tmp_path / "chat.db")
    trigger = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id="review-participant",
        target_role="review",
        target_address="@review",
        sender_participant_id="architect-participant",
        sender_address="@architect",
        source_message_id=message.id,
        item_type="review_trigger",
        payload={"content": "Review this proposal."},
    )
    sleeps = 0

    def mark_read_after_first_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        inbox.mark_read(trigger.id, responded_message_id=message.id)

    monkeypatch.setattr(sentinel.time, "sleep", mark_read_after_first_sleep)

    result = sentinel._wait_for_proposal_review_trigger_terminal(
        tmp_path / "chat.db",
        conversation_id=conv.id,
        proposal_id=proposal.id,
        timeout_s=30,
    )

    assert sleeps == 1
    assert result["id"] == trigger.id
    assert result["status"] == "read"


def test_review_provider_auto_falls_back_to_codex_when_opencode_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sentinel.shutil,
        "which",
        lambda binary: "/usr/bin/codex" if binary == "codex" else None,
    )

    def fake_run(command, **_kwargs):
        assert command == ["/usr/bin/codex", "--version"]
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "codex-cli test", "stderr": ""},
        )()

    monkeypatch.setattr(sentinel.subprocess, "run", fake_run)

    readiness = sentinel._provider_readiness(
        review_provider_policy="auto",
        ray_god_mcp=True,
    )

    assert readiness["providers"]["codex"]["available"] is True
    assert readiness["providers"]["opencode"]["available"] is False
    assert readiness["review_provider_selection"] == {
        "policy": "auto",
        "selected_provider": "codex",
        "fallback_reason": "opencode_unavailable",
    }
    assert sentinel._review_participant_spec(readiness) == {
        "role": "review",
        "provider_id": "codex",
        "profile_id": "review",
        "cli_kind": "codex",
        "model": "gpt-5.4",
        "display_name": "Codex Review GOD runtime sentinel",
    }


def test_forced_opencode_review_provider_fails_when_opencode_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sentinel.shutil, "which", lambda _binary: None)

    try:
        sentinel._provider_readiness(
            review_provider_policy="opencode",
            ray_god_mcp=True,
        )
    except RuntimeError as exc:
        assert "opencode_unavailable" in str(exc)
    else:
        raise AssertionError("forced opencode should fail closed when unavailable")


def test_success_checks_accept_selected_codex_review_fallback() -> None:
    snapshot = {
        "selected_review_provider": "codex",
        "review_provider_fallback_reason": "opencode_unavailable",
        "provider_readiness": {
            "review_provider_selection": {
                "policy": "auto",
                "selected_provider": "codex",
                "fallback_reason": "opencode_unavailable",
            }
        },
        "related_lane_graph_proposals": [{"id": "prop-1"}],
        "proposal": {
            "status": "accepted",
            "accepted_resolution_id": "res-1",
        },
        "proposal_has_review_runtime": False,
        "lane": {
            "resolution_id": "res-1",
            "status": "awaiting_final_action",
            "gate_passed": True,
            "peer_delivery_mode": "configured_peer",
            "peer_result_status": "completed",
            "peer_degraded_reason": None,
            "review_peer_cli_kind": "codex",
        },
        "review_peer_participant": {"cli_kind": "codex"},
        "review_verdict": {"status": "finalized"},
        "review_task": {"status": "verdict_emitted"},
        "final_action_hold": {"status": "pending"},
        "execution_artifact": {"matches_expected": True},
    }

    assert all(sentinel._success_checks(snapshot).values())


def test_success_checks_reject_stdout_review_authority() -> None:
    snapshot = {
        "selected_review_provider": "codex",
        "review_provider_fallback_reason": "opencode_unavailable",
        "provider_readiness": {
            "review_provider_selection": {
                "policy": "auto",
                "selected_provider": "codex",
                "fallback_reason": "opencode_unavailable",
            }
        },
        "related_lane_graph_proposals": [{"id": "prop-1"}],
        "proposal": {
            "status": "accepted",
            "accepted_resolution_id": "res-1",
        },
        "proposal_has_review_runtime": False,
        "lane": {
            "resolution_id": "res-1",
            "status": "awaiting_final_action",
            "gate_passed": True,
            "peer_delivery_mode": "configured_peer",
            "peer_result_status": "completed",
            "peer_degraded_reason": None,
            "review_peer_cli_kind": "codex",
            "review_summary": "MCP unavailable; stdout fallback review authority used.",
            "review_history": [
                {
                    "fallback": "persistent",
                    "fallback_reason": "verdict_merge",
                    "summary": "MCP unavailable; stdout fallback review authority used.",
                }
            ],
        },
        "review_peer_participant": {"cli_kind": "codex"},
        "review_verdict": {
            "status": "finalized",
            "summary": "MCP unavailable; stdout fallback review authority used.",
        },
        "review_task": {"status": "verdict_emitted"},
        "final_action_hold": {
            "status": "pending",
            "summary": "MCP unavailable; stdout fallback review authority used.",
        },
        "execution_artifact": {"matches_expected": True},
    }

    checks = sentinel._success_checks(snapshot)
    assert checks["review_authority_not_stdout_fallback"] is False
    assert not all(checks.values())
