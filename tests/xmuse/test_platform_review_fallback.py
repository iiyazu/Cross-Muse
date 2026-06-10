from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.agent_spawner import GodConfig, SpawnResult
from xmuse_core.platform.execution.review import (
    infer_review_fallback,
    review_fallback_positive_reason,
    review_fallback_rework_reason,
    review_infra_failure_reason,
)
from xmuse_core.platform.messages import ExecuteRequest, ReviewRequest, ReviewVerdict


def test_infer_review_fallback_rejects_unknown_review_text() -> None:
    decision, summary, reason = infer_review_fallback(
        "I reviewed the lane and have several notes below.\n"
        "The current implementation changes lifecycle behavior."
    )

    assert decision == "rejected"
    assert "several notes" in summary
    assert reason == "unknown_review_text"


def test_infer_review_fallback_accepts_explicit_merge_verdict() -> None:
    decision, _summary, reason = infer_review_fallback(
        "Findings: none\nVerdict: merge"
    )

    assert decision == "reviewed"
    assert reason == "verdict_merge"


def test_infer_review_fallback_accepts_markdown_merge_verdict() -> None:
    decision, _summary, reason = infer_review_fallback(
        "Findings:\n- Prior issue resolved.\n\n### Verdict: **MERGE**"
    )

    assert decision == "reviewed"
    assert reason == "verdict_merge"


def test_infer_review_fallback_extracts_cli_json_result_before_classification() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "result": (
                "## Review\n\n"
                "**Status:** gated — previous `review_decision: rework`.\n\n"
                "All prior findings are now resolved.\n\n"
                "### Verdict: **MERGE**"
            ),
        }
    )

    decision, summary, reason = infer_review_fallback(stdout)

    assert decision == "reviewed"
    assert reason == "verdict_merge"
    assert "previous `review_decision: rework`" in summary


def test_infer_review_fallback_accepts_pass_merge_decision_line() -> None:
    decision, _summary, reason = infer_review_fallback(
        "Findings: None.\n\nReview decision: **pass / merge**."
    )

    assert decision == "reviewed"
    assert reason == "explicit_merge_decision"


def test_review_fallback_rework_reason_detects_blocking_finding() -> None:
    assert (
        review_fallback_rework_reason(
            "Findings:\n- High: the retry loop still reproduces the failure."
        )
        == "reproduced_finding"
    )


def test_review_fallback_rework_reason_ignores_negated_blocking_finding() -> None:
    assert (
        review_fallback_rework_reason(
            "Findings:\nNone. I did not find a blocking issue in the current lane state."
        )
        is None
    )


def test_review_fallback_positive_reason_detects_empty_findings() -> None:
    assert (
        review_fallback_positive_reason(
            "Findings: No blocking findings in the current diff."
        )
        == "positive_no_blocking"
    )


def test_review_fallback_positive_reason_detects_none_findings_prose() -> None:
    assert (
        review_fallback_positive_reason("Findings:\nNone. I did not find any issues.")
        == "positive_none"
    )


def test_review_fallback_positive_reason_detects_no_blocking_issues_prose() -> None:
    assert (
        review_fallback_positive_reason(
            "Findings:\nNone. I found no blocking issues in commit `abc123`."
        )
        == "positive_none"
    )


def test_review_infra_failure_reason_detects_usage_limit() -> None:
    result = SpawnResult(
        exit_code=1,
        stdout="",
        stderr="ERROR: You've hit your usage limit. Try again later.",
    )

    assert review_infra_failure_reason(result) == "usage_limit"


def test_review_infra_failure_reason_ignores_successful_prompt_echo() -> None:
    result = SpawnResult(
        exit_code=0,
        stdout="MCP unavailable; fallback status executed.",
        stderr=(
            "Reading prompt from stdin...\n"
            "user\n"
            "Add a regression test containing: "
            "ERROR: You've hit your usage limit. Try again later.\n"
        ),
    )

    assert review_infra_failure_reason(result) is None


def test_review_infra_failure_reason_ignores_normal_rejection() -> None:
    result = SpawnResult(
        exit_code=1,
        stdout="Findings:\nHigh: missing test coverage.",
        stderr="",
    )

    assert review_infra_failure_reason(result) is None


def test_platform_message_contracts_are_explicit_dataclasses(tmp_path: Path) -> None:
    god = GodConfig(
        name="review-god",
        runtime="codex",
        timeout_s=30,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    execute = ExecuteRequest(
        lane_id="lane-1",
        prompt="implement",
        worktree=tmp_path,
        capabilities=["code"],
        god_config=god,
        mcp_url="http://localhost:8100",
        env_overrides={"XMUSE_LANE_ID": "lane-1"},
    )
    review = ReviewRequest(
        lane_id="lane-1",
        prompt="review",
        worktree=tmp_path,
        evidence_refs=["logs/gates/lane-1/report.json"],
        god_config=god,
        mcp_url="http://localhost:8100",
    )
    verdict = ReviewVerdict(
        passed=True,
        verdict="merge",
        feedback="No findings.",
        raw_output="Findings: none\nVerdict: merge",
    )

    assert execute.god_config.runtime == "codex"
    assert execute.worktree == tmp_path
    assert review.evidence_refs == ["logs/gates/lane-1/report.json"]
    assert verdict.passed is True
    assert verdict.verdict == "merge"
