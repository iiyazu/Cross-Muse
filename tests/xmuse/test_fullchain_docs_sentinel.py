from __future__ import annotations

import argparse
import json
from pathlib import Path

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

    monkeypatch.setattr(
        sentinel,
        "_parse_args",
        lambda: argparse.Namespace(
            run_root=run_root,
            execution_worktree=execution_worktree,
            feature_id=feature_id,
            chat_port=43111,
            mcp_port=43112,
            proposal_timeout_s=900.0,
            proposal_review_timeout_s=900.0,
            lane_timeout_s=1200.0,
            max_hours=0.75,
            architect_model="gpt-5.4",
            executor_model="gpt-5.4-mini",
            peer_chat_post_writeback_grace_s=sentinel.DEFAULT_PEER_CHAT_POST_WRITEBACK_GRACE_S,
            peer_god_backend="ray",
            ray_god_mcp=True,
        ),
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

    assert commands_json["expected_note_content"] == expected_note_content
    assert commands_json["peer_chat_post_writeback_grace_s"] == 8.0
    assert commands_json["peer_god_backend"] == "ray"
    assert commands_json["ray_god_mcp"] is True
    assert f"expected_note_content={expected_note_content}\n" in commands_txt
    assert "peer_chat_post_writeback_grace_s=8.0\n" in commands_txt
    assert "peer_god_backend=ray\n" in commands_txt
    assert "ray_god_mcp=True\n" in commands_txt


def test_start_runner_uses_configured_peer_chat_writeback_grace(
    tmp_path: Path,
    monkeypatch,
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
        peer_chat_post_writeback_grace_s=13.5,
        peer_god_backend="ray",
        ray_god_mcp=True,
    )

    command = captured["command"]
    assert result is not None
    assert isinstance(command, list)
    flag_index = command.index("--peer-chat-post-writeback-grace-s")
    assert command[flag_index + 1] == "13.5"
    env = captured["env"]
    assert env["XMUSE_PEER_GOD_BACKEND"] == "ray"
    assert env["XMUSE_RAY_GOD_MCP"] == "1"


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
