"""Task prompt helpers for the legacy Xmuse master loop."""

from __future__ import annotations

import json
from typing import Any

from xmuse_core.agents.consumer import TaskDescriptor


def clone_task_with_prompt(
    task: TaskDescriptor,
    *,
    task_type: str | None = None,
    prompt: str,
) -> TaskDescriptor:
    return TaskDescriptor(
        feature_id=task.feature_id,
        task_type=task_type or task.task_type,
        prompt=prompt,
        worktree=task.worktree,
        required_capabilities=task.required_capabilities,
        developed_by_runtime=task.developed_by_runtime,
        priority=task.priority,
        gate_profile=task.gate_profile,
        gate_profiles=task.gate_profiles,
        lane_metadata=task.lane_metadata,
        base_head_sha=task.base_head_sha,
    )


def format_gate_context(gate_result: Any | None) -> str:
    if gate_result is None:
        return ""
    context = {
        "passed": bool(getattr(gate_result, "passed", False)),
        "errors": list(getattr(gate_result, "errors", []))[:5],
        "gate_report": getattr(gate_result, "gate_report", None),
        "gate_warnings": list(getattr(gate_result, "gate_warnings", []) or [])[:5],
    }
    return json.dumps(context, ensure_ascii=False, default=str)[:2000]


def render_review_rejection_prompt(review_verdict: Any) -> str:
    concerns = "\n".join(f"- {c}" for c in review_verdict.concerns)
    return (
        "Code review rejected this implementation.\n\n"
        f"## Concerns\n{concerns}\n\n"
        f"## Summary\n{review_verdict.summary}\n\n"
        "Fix these concerns. Do NOT start from scratch."
    )


def build_review_rework_task(
    task: TaskDescriptor,
    review_verdict: Any,
    *,
    error_context: str,
    diff_context: str,
) -> TaskDescriptor:
    rejected_context = error_context or render_review_rejection_prompt(review_verdict)
    full_rework = (
        f"## Original Task\n{task.prompt[:2000]}\n\n"
        f"## Current Diff\n{diff_context[:3000]}\n\n"
        f"## Why Rejected\n{rejected_context}"
    )
    return clone_task_with_prompt(task, task_type="rework", prompt=full_rework)


def with_scope_constraint(task: TaskDescriptor) -> TaskDescriptor:
    """Append a scope constraint to prevent codex from modifying unrelated files."""
    constraint = (
        "\n\n## SCOPE CONSTRAINT (MANDATORY)\n"
        "Only modify files directly related to this task. "
        "Do NOT touch files outside the scope of this requirement. "
        "Specifically:\n"
        "- Do NOT modify xmuse/master_loop.py, src/xmuse_core/agents/manager.py, "
        "or src/xmuse_core/gates/review_gate.py unless this task explicitly requires it.\n"
        "- Do NOT change default timeouts, authentication logic, or review gate behavior.\n"
        "- Do NOT refactor, rename, or reorganize code outside the stated task.\n"
        "- If you believe a change to another file is necessary, add a comment explaining why "
        "but do NOT make the change.\n"
    )
    return clone_task_with_prompt(task, prompt=task.prompt + constraint)
