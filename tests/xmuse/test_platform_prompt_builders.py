"""Snapshot tests for platform/prompts/builders.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.platform.prompts.builders import (
    build_execution_prompt,
    build_review_prompt,
    build_review_verdict,
)
from xmuse_core.structuring.models import ReviewDecision


@pytest.fixture
def xmuse_root(tmp_path: Path) -> Path:
    prompts_dir = tmp_path / "xmuse" / "god_prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "execution_god.md").write_text("You are the execution god.")
    (prompts_dir / "review_god.md").write_text("You are the review god.")
    return tmp_path


def test_build_execution_prompt_includes_skill_and_task(xmuse_root: Path):
    lane = {"feature_id": "lane-42", "prompt": "implement caching"}
    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )
    assert "You are the execution god." in result
    assert "Lane ID: lane-42" in result
    assert "implement caching" in result


def test_build_execution_prompt_starts_with_noninteractive_worker_override(
    xmuse_root: Path,
):
    result = build_execution_prompt(
        {"feature_id": "lane-automation", "prompt": "implement the lane"},
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert result.startswith("## Xmuse Child Worker Automation Override")
    assert "skip that instruction for this child-worker invocation" in result
    assert "Do not ask the human user for approval" in result
    assert "Do not start or offer a browser, visual companion, mockup companion" in result
    assert "If the lane is too vague to implement safely, exit non-zero" in result
    assert result.index("## Xmuse Child Worker Automation Override") < result.index(
        "You are the execution god."
    )


def test_build_execution_prompt_missing_skill_file(tmp_path: Path):
    lane = {"feature_id": "lane-1", "prompt": "do stuff"}
    result = build_execution_prompt(
        lane,
        xmuse_root=tmp_path,
        skill_prompt_path="nonexistent/path.md",
    )
    assert "Lane ID: lane-1" in result
    assert "do stuff" in result


def test_build_execution_prompt_falls_back_to_repo_prompt_when_runtime_root_is_external(
    tmp_path: Path,
):
    result = build_execution_prompt(
        {"feature_id": "lane-live-root", "prompt": "do live-root work"},
        xmuse_root=tmp_path,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "temporary child worker" in result
    assert "Expected Result Contract" in result
    assert "Lane ID: lane-live-root" in result


def test_build_execution_prompt_resolves_repo_root_skill_path_when_xmuse_root_is_nested(
    xmuse_root: Path,
):
    result = build_execution_prompt(
        {"feature_id": "lane-nested-skill", "prompt": "do nested skill work"},
        xmuse_root=xmuse_root / "xmuse",
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "You are the execution god." in result
    assert "do nested skill work" in result


def test_build_execution_prompt_includes_prior_attempt_context(xmuse_root: Path):
    lane = {
        "feature_id": "lane-rework",
        "status": "reworking",
        "prompt": "fix inbox",
        "retry_count": 1,
        "review_decision": "rework",
        "review_summary": "Preserve terminal read and failed inbox rows.",
        "branch": "lane-rework",
        "worktree": "/tmp/lane-rework",
    }

    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "## Prior Attempt Context" in result
    assert "Retry count: 1" in result
    assert "Review decision: rework" in result
    assert "Preserve terminal read and failed inbox rows." in result


def test_build_execution_prompt_cites_evidence_refs_without_absolute_log_paths(
    xmuse_root: Path,
):
    gate_report = xmuse_root / "logs" / "gates" / "lane-rework-evidence" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text('{"passed": true}', encoding="utf-8")
    spawn_dir = xmuse_root / "logs" / "agent_spawns" / "lane-rework-evidence"
    spawn_dir.mkdir(parents=True)
    spawn_log = spawn_dir / "20260530T000000Z.stdout.log"
    spawn_log.write_text("worker output", encoding="utf-8")
    lane = {
        "feature_id": "lane-rework-evidence",
        "status": "reworking",
        "prompt": "fix inbox",
        "retry_count": 1,
        "review_decision": "rework",
        "review_summary": "Use the gate and worker evidence.",
        "branch": "lane-rework-evidence",
        "worktree": "/tmp/lane-rework-evidence",
    }

    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "Gate refs: logs/gates/lane-rework-evidence/report.json" in result
    assert (
        "Worker refs: logs/agent_spawns/lane-rework-evidence/20260530T000000Z.stdout.log"
        in result
    )
    assert str(gate_report) not in result
    assert str(spawn_log) not in result


def test_build_execution_prompt_includes_blueprint_acceptance_context(
    xmuse_root: Path,
):
    blueprint = xmuse_root / "docs" / "mission.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text(
        "Mission blueprint\nExecution workers need this context.",
        encoding="utf-8",
    )
    lane = {
        "feature_id": "lane-exec-blueprint",
        "prompt": "implement the feature",
        "blueprint_refs": ["docs/mission.md"],
        "acceptance_criteria": [
            "Execution and review use the same acceptance criteria.",
        ],
    }

    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "## Mission Blueprint References" in result
    assert "Execution workers need this context." in result
    assert "## Feature Acceptance Criteria" in result
    assert "- Execution and review use the same acceptance criteria." in result


def test_build_execution_prompt_includes_bounded_worker_delegation_contract(
    xmuse_root: Path,
):
    lane = {
        "feature_id": "lane-tiered-contract",
        "prompt": "implement the bounded worker handoff",
        "model_policy_enabled": True,
        "model_policy_runtime": "codex",
        "review_model": "gpt-5.5",
        "coordinator_model": "gpt-5.4",
        "worker_model": "gpt-5.4-mini",
        "delegation_mode": "bounded_worker",
        "delegation_contract": "bounded_code_writing_v1",
    }

    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "## Model Policy" in result
    assert "- delegation_contract: bounded_code_writing_v1" in result
    assert "## Bounded Worker Delegation Contract" in result
    assert "delegate bounded code-writing work" in result
    assert "configured worker_model gpt-5.4-mini" in result
    assert "collect diffs, changed files, tests run, and summaries" in result
    assert "do not choose other runtimes or autonomously optimize model/cost" in result


def test_build_execution_prompt_retry_context_carries_alignment_and_lane_refs(
    xmuse_root: Path,
):
    blueprint = xmuse_root / "docs" / "mission.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text("Mission blueprint\nRetry workers need this.", encoding="utf-8")
    lane = {
        "feature_id": "lane-exec-approved-retry",
        "status": "reworking",
        "prompt": "finish retry context bundle",
        "retry_count": 1,
        "review_decision": "rework",
        "review_summary": "Review decision: no blocking findings",
        "review_fallback_reason": "unknown_review_text",
        "branch": "lane-exec-approved-retry",
        "worktree": "/tmp/lane-exec-approved-retry",
        "blueprint_refs": ["docs/mission.md"],
        "acceptance_criteria": [
            "Retry context separates infra, parser, semantic, and resolved findings.",
        ],
    }

    result = build_execution_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    assert "## Mission Blueprint References" in result
    assert "Retry workers need this." in result
    assert "## Feature Acceptance Criteria" in result
    assert (
        "- Retry context separates infra, parser, semantic, and resolved findings."
        in result
    )
    assert "### Parser/Fallback Classification" in result
    assert "- Category: approved_review" in result
    assert "### Real Semantic Findings" in result
    assert "- None identified by review/rework alignment." in result
    assert "### Resolved Prior Findings" in result
    assert "Review decision: rework" not in result
    assert "non-existent semantic blocker" not in result
    assert "Required continuation: address prior review/failure" not in result


def test_build_review_prompt_includes_skill_and_lane_id(xmuse_root: Path):
    lane = {"feature_id": "lane-review-7", "prompt": "implement the review target"}
    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )
    assert "You are the review god." in result
    assert "Review lane: lane-review-7" in result
    assert "## Lane Task" in result
    assert "implement the review target" in result


def test_build_review_prompt_starts_with_noninteractive_worker_override(
    xmuse_root: Path,
):
    result = build_review_prompt(
        {"feature_id": "lane-review-automation", "prompt": "review the lane"},
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert result.startswith("## Xmuse Child Worker Automation Override")
    assert "skip that instruction for this child-worker invocation" in result
    assert "Do not ask the human user for approval" in result
    assert "Do not start or offer a browser, visual companion, mockup companion" in result
    assert "If the lane is too vague to implement safely, exit non-zero" in result
    assert result.index("## Xmuse Child Worker Automation Override") < result.index(
        "You are the review god."
    )


def test_build_review_prompt_resolves_repo_root_skill_path_when_xmuse_root_is_nested(
    xmuse_root: Path,
):
    result = build_review_prompt(
        {"feature_id": "lane-review-nested-skill", "prompt": "review nested skill work"},
        xmuse_root=xmuse_root / "xmuse",
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "You are the review god." in result
    assert "review nested skill work" in result


def test_build_review_prompt_falls_back_to_repo_prompt_when_runtime_root_is_external(
    tmp_path: Path,
):
    result = build_review_prompt(
        {"feature_id": "lane-review-live-root", "prompt": "review live-root work"},
        xmuse_root=tmp_path,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "You are the Review God of xmuse" in result
    assert "Verdict: merge" in result
    assert "Review lane: lane-review-live-root" in result


def test_review_god_prompt_forbids_file_edits_and_requires_parseable_verdict():
    prompt = Path("xmuse/god_prompts/review_god.md").read_text(encoding="utf-8")

    assert "Do not edit files" in prompt
    assert "Do not run implementation commands" in prompt
    assert "Do not commit changes" in prompt
    assert "Do not call apply_patch" in prompt
    assert "Do not run `git add`" in prompt
    assert "Do not run `git commit`" in prompt
    assert "Findings:" in prompt
    assert "Verdict:" in prompt
    assert "Verdict: merge" in prompt
    assert "Verdict: rework" in prompt
    assert "Verdict: terminate" in prompt


def test_execution_prompt_identifies_one_shot_worker_as_temporary_child() -> None:
    prompt = Path("xmuse/god_prompts/execution_god.md").read_text(encoding="utf-8")

    assert "temporary child worker" in prompt
    assert "persistent Execute GOD" in prompt
    assert "You are the Execution God" not in prompt


def test_execution_prompt_has_mcp_unavailable_fallback() -> None:
    prompt = Path("xmuse/god_prompts/execution_god.md").read_text(encoding="utf-8")

    assert "If MCP tools are not exposed" in prompt
    assert "stdout fallback" in prompt
    assert "exit with status 0" in prompt
    assert "exit non-zero" in prompt


def test_execution_prompt_describes_child_result_contract() -> None:
    prompt = Path("xmuse/god_prompts/execution_god.md").read_text(encoding="utf-8")

    assert "Expected Result Contract" in prompt
    assert "lane request id" in prompt
    assert "lane id" in prompt
    assert "tests run" in prompt
    assert "changed files" in prompt
    assert "executed" in prompt
    assert "exec_failed" in prompt


def test_review_prompt_has_mcp_unavailable_fallback() -> None:
    prompt = Path("xmuse/god_prompts/review_god.md").read_text(encoding="utf-8")

    assert "If MCP tools are not exposed" in prompt
    assert "stdout fallback" in prompt


def test_build_review_prompt_includes_prior_attempt_context(xmuse_root: Path):
    lane = {
        "feature_id": "lane-review-rework",
        "status": "gated",
        "retry_count": 2,
        "review_decision": "rework",
        "review_summary": "Previous review found missing merge evidence.",
    }

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "## Prior Attempt Context" in result
    assert "Retry count: 2" in result
    assert "Previous review found missing merge evidence." in result


def test_build_review_prompt_cites_context_bundle_refs_not_raw_worker_logs(
    xmuse_root: Path,
):
    spawn_dir = xmuse_root / "logs" / "agent_spawns" / "lane-review-compact"
    spawn_dir.mkdir(parents=True)
    spawn_log = spawn_dir / "20260531T000000Z.stdout.log"
    spawn_log.write_text("RAW_REVIEW_WORKER_LOG_SENTINEL", encoding="utf-8")
    lane = {
        "feature_id": "lane-review-compact",
        "status": "reworking",
        "retry_count": 1,
        "review_summary": "Blocking: use compact refs.",
        "review_fallback_reason": "blocking_finding",
    }

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "## Prior Attempt Context" in result
    assert "### Context Bundle References" in result
    assert (
        "- Worker refs: logs/agent_spawns/lane-review-compact/20260531T000000Z.stdout.log"
        in result
    )
    assert "- Primary evidence refs: lane.review_fallback_reason, lane.review_summary" in result
    assert "RAW_REVIEW_WORKER_LOG_SENTINEL" not in result
    assert str(spawn_log) not in result
    assert "### Recent Agent Output Excerpt" not in result


def test_build_review_prompt_includes_dependency_states_from_context_bundle(
    xmuse_root: Path,
):
    lane = {
        "feature_id": "lane-review-deps",
        "status": "reworking",
        "retry_count": 1,
        "review_summary": "Blocking: preserve dependency states.",
        "review_fallback_reason": "blocking_finding",
        "depends_on": ["base-lane"],
    }
    all_lanes = [
        lane,
        {"feature_id": "base-lane", "status": "merged"},
        {"feature_id": "child-lane", "status": "pending", "depends_on": ["lane-review-deps"]},
    ]

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
        all_lanes=all_lanes,
    )

    assert "### Context Contract" in result
    assert "- dependency base-lane: merged" in result
    assert "- dependent child-lane: pending" in result


def test_build_review_prompt_includes_bounded_blueprint_acceptance_and_retry(
    xmuse_root: Path,
):
    blueprint = xmuse_root / "docs" / "mission.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text(
        "Mission blueprint\n"
        "Review prompt includes mission blueprint context.\n"
        "This extra detail should still be bounded.\n"
        + ("x" * 5000)
        + "UNBOUNDED_SENTINEL",
        encoding="utf-8",
    )
    unreadable_ref = xmuse_root / "docs" / "directory-ref"
    unreadable_ref.mkdir()
    lane = {
        "feature_id": "lane-review-blueprint",
        "status": "gated",
        "retry_count": 1,
        "review_summary": "Previous review needs retry context.",
        "blueprint_refs": [
            "docs/mission.md",
            "docs/missing-blueprint.md",
            "docs/directory-ref",
        ],
        "acceptance_criteria": [
            "Review prompt includes mission blueprint and feature acceptance criteria.",
            "Controller does not synthesize semantic approval.",
        ],
    }

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "## Mission Blueprint References" in result
    assert "### docs/mission.md" in result
    assert "Review prompt includes mission blueprint context." in result
    assert "UNBOUNDED_SENTINEL" not in result
    assert "<truncated>" in result
    assert "### docs/missing-blueprint.md" in result
    assert "unavailable: missing file" in result
    assert "### docs/directory-ref" in result
    assert "unavailable: unreadable" in result
    assert "## Feature Acceptance Criteria" in result
    assert "- Review prompt includes mission blueprint and feature acceptance criteria." in result
    assert "- Controller does not synthesize semantic approval." in result
    assert "## Prior Attempt Context" in result
    assert "Retry count: 1" in result
    assert "Previous review needs retry context." in result


def test_build_review_prompt_resolves_repo_root_blueprint_refs_when_xmuse_root_is_nested(
    xmuse_root: Path,
):
    nested_xmuse_root = xmuse_root / "xmuse"
    blueprint = xmuse_root / "docs" / "mission-from-repo-root.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text(
        "Repo-root mission blueprint content.",
        encoding="utf-8",
    )

    result = build_review_prompt(
        {
            "feature_id": "lane-review-repo-root-blueprint",
            "blueprint_refs": ["docs/mission-from-repo-root.md"],
        },
        xmuse_root=nested_xmuse_root,
        skill_prompt_path="god_prompts/review_god.md",
    )

    assert "### docs/mission-from-repo-root.md" in result
    assert "Repo-root mission blueprint content." in result
    assert "unavailable: missing file" not in result


def test_build_review_prompt_shows_invalid_blueprint_ref_without_crashing(
    xmuse_root: Path,
):
    blueprint = xmuse_root / "docs" / "invalid-encoding.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_bytes(b"\xff\xfe\xfa")
    lane = {
        "feature_id": "lane-review-invalid-blueprint",
        "blueprint_refs": ["docs/invalid-encoding.md"],
    }

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "## Mission Blueprint References" in result
    assert "### docs/invalid-encoding.md" in result
    assert "unavailable: unreadable" in result


def test_build_review_prompt_shows_unresolvable_blueprint_ref_without_crashing(
    xmuse_root: Path,
):
    symlink_ref = xmuse_root / "docs" / "loop"
    symlink_ref.parent.mkdir(parents=True)
    symlink_ref.symlink_to("loop")
    lane = {
        "feature_id": "lane-review-symlink-loop",
        "blueprint_refs": ["docs/loop"],
    }

    result = build_review_prompt(
        lane,
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "## Mission Blueprint References" in result
    assert "### docs/loop" in result
    assert "unavailable: unresolvable" in result


def test_build_review_prompt_reads_blueprint_with_bounded_io(
    xmuse_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    blueprint = xmuse_root / "docs" / "large-blueprint.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text(
        "Mission blueprint\n" + ("x" * 5000) + "UNBOUNDED_SENTINEL",
        encoding="utf-8",
    )
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):
        if path == blueprint:
            raise AssertionError("blueprint refs must use bounded reads")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = build_review_prompt(
        {
            "feature_id": "lane-review-large-blueprint",
            "blueprint_refs": ["docs/large-blueprint.md"],
        },
        xmuse_root=xmuse_root,
        skill_prompt_path="xmuse/god_prompts/review_god.md",
    )

    assert "Mission blueprint" in result
    assert "UNBOUNDED_SENTINEL" not in result
    assert "<truncated>" in result


def test_build_review_verdict_defaults_to_merge():
    lane = {"feature_id": "lane-x"}
    verdict = build_review_verdict(lane)
    assert verdict.decision == ReviewDecision.MERGE
    assert verdict.lane_id == "lane-x"
    assert verdict.id == "verdict-lane-x"
    assert verdict.summary == "reviewed"


def test_build_review_verdict_with_rework_decision():
    lane = {
        "feature_id": "lane-y",
        "review_decision": "rework",
        "review_summary": "needs fixes",
        "review_verdict_id": "v-123",
        "review_evidence_refs": ["ref-a", "ref-b"],
        "patch_instructions": "fix the tests",
    }
    verdict = build_review_verdict(lane)
    assert verdict.decision == ReviewDecision.REWORK
    assert verdict.id == "v-123"
    assert verdict.summary == "needs fixes"
    assert verdict.evidence_refs == ["ref-a", "ref-b"]
    assert verdict.patch_instructions == "fix the tests"
    assert verdict.terminate_reason is None
