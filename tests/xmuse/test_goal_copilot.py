from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from xmuse_core.platform.goal_copilot import (
    GoalCopilotReviewEntry,
    append_goal_copilot_review_entry,
    build_goal_copilot_intake_decision,
    build_goal_copilot_launch_prompt,
    default_goal_copilot_review_board_path,
)


def test_default_goal_copilot_board_path_is_ignored_goal_artifact(tmp_path: Path) -> None:
    board_path = default_goal_copilot_review_board_path(
        tmp_path,
        run_date=date(2026, 6, 28),
    )

    assert board_path == (
        tmp_path / ".goal-runs" / "2026-06-28" / "production-goal-copilot-review-board.md"
    )


def test_append_goal_copilot_entry_only_writes_review_board(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    lanes_projection = tmp_path / "feature_lanes.json"
    chat_db.write_bytes(b"chat authority")
    lanes_projection.write_text('{"projection": true}', encoding="utf-8")
    before_chat = chat_db.read_bytes()
    before_lanes = lanes_projection.read_text(encoding="utf-8")
    board_path = default_goal_copilot_review_board_path(
        tmp_path,
        run_date=date(2026, 6, 28),
    )
    entry = GoalCopilotReviewEntry(
        reviewed_at=datetime(2026, 6, 28, 10, 40, tzinfo=UTC),
        scope=["Track D read-only copilot audit"],
        facts_inspected=[
            "docs/xmuse/goal-copilot-behavior-policy.md",
            "github:pr/246#head=7dca60b",
        ],
        observed=["No product helper exists for append-only copilot board intake."],
        risks=["Copilot output could be mistaken for review or merge truth."],
        recommendations=["Add a guarded board append helper and intake classifier."],
        questions=[],
        claims_to_avoid=["copilot output proves production readiness"],
    )

    written_path = append_goal_copilot_review_entry(
        repo_root=tmp_path,
        board_path=board_path,
        entry=entry,
    )
    append_goal_copilot_review_entry(
        repo_root=tmp_path,
        board_path=board_path,
        entry=entry,
    )

    assert written_path == board_path
    assert chat_db.read_bytes() == before_chat
    assert lanes_projection.read_text(encoding="utf-8") == before_lanes
    content = board_path.read_text(encoding="utf-8")
    assert content.count("## Review 2026-06-28 10:40 UTC") == 2
    assert "Scope:" in content
    assert "- Track D read-only copilot audit" in content
    assert "Facts inspected:" in content
    assert "- github:pr/246#head=7dca60b" in content
    assert "Claims to avoid:" in content
    assert "- copilot output proves production readiness" in content


def test_copilot_board_append_rejects_non_review_board_paths(tmp_path: Path) -> None:
    entry = GoalCopilotReviewEntry(
        reviewed_at=datetime(2026, 6, 28, 10, 45, tzinfo=UTC),
        scope=["bad path check"],
        facts_inspected=["chat.db:messages/1"],
        observed=["path rejected"],
        risks=[],
        recommendations=[],
        questions=[],
        claims_to_avoid=[],
    )

    with pytest.raises(ValueError, match="production-goal-copilot-review-board.md"):
        append_goal_copilot_review_entry(
            repo_root=tmp_path,
            board_path=tmp_path / "docs" / "review.md",
            entry=entry,
        )

    with pytest.raises(ValueError, match="production-goal-copilot-review-board.md"):
        append_goal_copilot_review_entry(
            repo_root=tmp_path,
            board_path=tmp_path / ".goal-runs" / "2026-06-28" / "notes.md",
            entry=entry,
        )

    with pytest.raises(ValueError, match=r"\.goal-runs/<date>/"):
        append_goal_copilot_review_entry(
            repo_root=tmp_path,
            board_path=(
                tmp_path
                / ".goal-runs"
                / "2026-06-28"
                / "nested"
                / "production-goal-copilot-review-board.md"
            ),
            entry=entry,
        )

    with pytest.raises(ValueError, match=r"\.goal-runs/<date>/"):
        append_goal_copilot_review_entry(
            repo_root=tmp_path,
            board_path=(
                tmp_path / ".goal-runs" / "latest" / "production-goal-copilot-review-board.md"
            ),
            entry=entry,
        )


def test_goal_copilot_intake_acceptance_requires_durable_authority_refs() -> None:
    with pytest.raises(ValueError, match="durable authority"):
        build_goal_copilot_intake_decision(
            recommendation_id="rec-1",
            classification="accepted",
            reason="subagent agreed",
            verified_authority_refs=["subagent:audit#ok", "local-test:pytest"],
        )

    with pytest.raises(ValueError, match="durable authority"):
        build_goal_copilot_intake_decision(
            recommendation_id="rec-git",
            classification="accepted",
            reason="local commit exists",
            verified_authority_refs=["git:HEAD"],
        )

    for evidence_ref in (
        "mcp_writeback:dispatch-inbox",
        "chat_dispatch_queue#entry=legacy-dispatch-evidence",
    ):
        with pytest.raises(ValueError, match="durable authority"):
            build_goal_copilot_intake_decision(
                recommendation_id=f"rec-evidence-only-{evidence_ref.split(':', 1)[0]}",
                classification="accepted",
                reason="execution evidence alone is not authority",
                verified_authority_refs=[evidence_ref],
            )

    accepted = build_goal_copilot_intake_decision(
        recommendation_id="rec-2",
        classification="accepted",
        reason="verified through current PR and chat authority",
        verified_authority_refs=[
            "github:pr/246#head=7dca60ba72409482a3d7b084cc28f88c91448b53",
            "chat.db:messages/42",
            "subagent:audit#candidate",
            "local-test:pytest",
        ],
    )

    assert accepted["schema_version"] == "goal_copilot_intake/v1"
    assert accepted["advisory_only"] is True
    assert accepted["classification"] == "accepted"
    assert accepted["verified_authority_refs"] == [
        "github:pr/246#head=7dca60ba72409482a3d7b084cc28f88c91448b53",
        "chat.db:messages/42",
    ]
    assert accepted["candidate_input_refs"] == [
        "subagent:audit#candidate",
        "local-test:pytest",
    ]
    assert accepted["intake_boundary"] == {
        "producer": "goal_copilot_review_board",
        "consumer": "main_goal_agent",
        "condition": "main_agent_verified_durable_authority_refs",
        "proof_boundary": "advisory_intake_not_review_dispatch_merge_or_execution_truth",
        "failure_boundary": "accepted_without_durable_authority_refs_rejected",
    }
    dispatch_accepted = build_goal_copilot_intake_decision(
        recommendation_id="rec-dispatch",
        classification="accepted",
        reason="verified dispatch queue authority and separated execution evidence",
        verified_authority_refs=[
            "chat_dispatch_queue:dispatch:conv:resolution:execute",
            "review_trigger_verdict:msg-review",
            "mcp_writeback:dispatch-inbox",
            "chat_dispatch_queue#entry=legacy-dispatch-evidence",
        ],
    )

    assert dispatch_accepted["verified_authority_refs"] == [
        "chat_dispatch_queue:dispatch:conv:resolution:execute",
        "review_trigger_verdict:msg-review",
    ]
    assert dispatch_accepted["candidate_input_refs"] == [
        "mcp_writeback:dispatch-inbox",
        "chat_dispatch_queue#entry=legacy-dispatch-evidence",
    ]
    assert accepted["forbidden_truth_surfaces"] == [
        "provider stdout",
        "worker output",
        "local tests",
        "subagent output",
        "copilot output",
    ]


def test_goal_copilot_launch_prompt_preserves_read_only_boundaries(tmp_path: Path) -> None:
    board_path = default_goal_copilot_review_board_path(
        tmp_path,
        run_date=date(2026, 6, 28),
    )

    prompt = build_goal_copilot_launch_prompt(
        repo_path=tmp_path,
        active_goal_prompt="Advance Tracks A/B/C/D without treating stdout as proof.",
        review_board_path=board_path,
    )

    assert "read-only observer" in prompt
    assert "Only append review entries" in prompt
    assert "not proof truth" in prompt
    assert "subagent output, worker output, and local tests are candidate input only" in prompt
    assert (
        "chat.db / inbox / proposal / review verdict / dispatch queue / GitHub server facts"
        in prompt
    )
    assert "files, commits, runtime artifacts" not in prompt
    assert "Do not edit source code." in prompt
    assert "Do not create branches, commits, pushes, PRs, or merges." in prompt
    assert str(board_path.relative_to(tmp_path)) in prompt
    assert "Advance Tracks A/B/C/D" in prompt


def test_goal_copilot_launch_prompt_rejects_non_board_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production-goal-copilot-review-board.md"):
        build_goal_copilot_launch_prompt(
            repo_path=tmp_path,
            active_goal_prompt="Keep Track D read-only.",
            review_board_path=tmp_path / "docs" / "review.md",
        )
