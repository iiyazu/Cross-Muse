from __future__ import annotations

from types import SimpleNamespace

from xmuse_core.agents.consumer import TaskDescriptor
from xmuse_core.platform import master_loop_tasks


def _task(prompt: str = "implement") -> TaskDescriptor:
    return TaskDescriptor(
        feature_id="lane-1",
        task_type="execute",
        prompt=prompt,
        worktree="/tmp/worktree",
        required_capabilities=["code"],
        priority=7,
        gate_profile="profile-a",
        gate_profiles=["profile-a"],
        lane_metadata={"source": "test"},
        base_head_sha="base-sha",
    )


def test_task_helpers_format_gate_context_and_scope_constraint() -> None:
    context = master_loop_tasks.format_gate_context(
        SimpleNamespace(
            passed=False,
            errors=["pytest failed"],
            gate_report={"suite": "unit"},
            gate_warnings=["slow"],
        )
    )
    scoped = master_loop_tasks.with_scope_constraint(_task("do it"))

    assert '"passed": false' in context
    assert '"suite": "unit"' in context
    assert scoped.prompt.startswith("do it")
    assert "SCOPE CONSTRAINT" in scoped.prompt
    assert scoped.feature_id == "lane-1"
    assert scoped.lane_metadata == {"source": "test"}


def test_task_helpers_build_review_rework_task_with_diff_and_error_context() -> None:
    review = SimpleNamespace(
        concerns=["missing tests", "bad boundary"],
        summary="needs cleanup",
    )

    rework = master_loop_tasks.build_review_rework_task(
        _task("original task"),
        review,
        error_context="LESSONS\n\n"
        + master_loop_tasks.render_review_rejection_prompt(review),
        diff_context="diff --stat\nfile.py | 1 +",
    )

    assert rework.task_type == "rework"
    assert "## Original Task\noriginal task" in rework.prompt
    assert "## Current Diff\ndiff --stat" in rework.prompt
    assert "- missing tests" in rework.prompt
    assert "LESSONS" in rework.prompt
