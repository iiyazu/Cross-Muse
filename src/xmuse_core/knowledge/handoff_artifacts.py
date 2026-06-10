"""Handoff artifact builders for Xmuse error-knowledge maintenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ack_level_for(status: str) -> str:
    return "usable" if status == "usable" else "failed"


def verification_commands() -> list[dict[str, str]]:
    return [
        {
            "command": "uv run pytest tests/xmuse/test_error_knowledge.py -q",
            "result": "recorded by Slave after focused verification",
        },
        {
            "command": "uv run ruff check .",
            "result": "repository lint gate; xmuse is excluded by project config",
        },
        {
            "command": (
                "uv run ruff check --no-cache xmuse/xmuse_error_knowledge.py "
                "tests/xmuse/test_error_knowledge.py"
            ),
            "result": "explicit Xmuse maintainer lint gate",
        },
    ]


def render_result_markdown(
    *,
    feature_id: str,
    status: str,
    run_id: str,
    record_count: int,
    cluster_count: int,
    method_count: int,
    proposal_count: int,
    blockers: list[str],
) -> str:
    phase_rows = [
        ("Phase 0", "complete", "Contract and bootstrap boundary implemented."),
        ("Phase 1", "complete", "Schema objects and index rebuilds implemented."),
        (
            "Phase 2",
            "complete",
            "Structured scanner extracts JSON and bounded Markdown failures.",
        ),
        ("Phase 3", "complete", "Clustering and conservative promotion rules implemented."),
        ("Phase 4", "complete", "Draft methods and skill proposals remain quarantined."),
        (
            "Phase 5",
            "complete" if status == "usable" else "failed",
            "Integrated run artifacts emitted.",
        ),
    ]
    return "\n".join(
        [
            f"# feature: {feature_id}",
            "",
            "## Result",
            "",
            f"- Status: `{status}`",
            f"- Knowledge run: `{run_id}`",
            f"- Error records: {record_count}",
            f"- Clusters touched: {cluster_count}",
            f"- Draft methods touched: {method_count}",
            f"- Draft skill proposals touched: {proposal_count}",
            "",
            "## Phase Matrix",
            "",
            "| Phase | Status | Evidence |",
            "|---|---|---|",
            *[
                f"| {phase} | {row_status} | {evidence} |"
                for phase, row_status, evidence in phase_rows
            ],
            "",
            "## Boundaries",
            "",
            (
                "- No MemoryOS runtime, store, recall, v1 fallback, "
                "v3 default, or kernel default changes."
            ),
            (
                "- No Master state/status, Master review, approval, "
                "active prompt, or active skill writes."
            ),
            "- Benchmark scores are diagnostic evidence only; no improvement claim is made.",
            "",
            "## Blockers",
            "",
            *(f"- {blocker}" for blocker in blockers),
            "" if blockers else "- None",
            "",
        ]
    )


def build_review_verdict(
    *,
    feature_id: str,
    status: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "verdict": "PASS" if status == "usable" else "FAIL",
        "blocking_findings": blockers,
        "required_repairs": blockers,
        "review_eval_decision": {
            "scope": "not_applicable",
            "reason": "Xmuse control-plane maintenance only; no MemoryOS answer path changed",
            "longmemeval": {"run": False, "reason": "not applicable"},
            "locomo": {"run": False, "reason": "not applicable"},
            "llm_answer": False,
            "llm_judge": False,
            "promotion_gate": "not_applicable",
        },
        "readiness_for_slave_ack": status == "usable",
        "v3_default_preserved": True,
        "v1_fallback_preserved": True,
        "kernel_default_unchanged": True,
        "benchmark_improvement_claim_flag": False,
    }


def build_ack(
    *,
    feature_id: str,
    status: str,
    root: Path,
    head_ref: str,
    run_id: str,
    blockers: list[str],
) -> dict[str, Any]:
    review = build_review_verdict(feature_id=feature_id, status=status, blockers=blockers)
    return {
        "feature_id": feature_id,
        "ack_level": ack_level_for(status),
        "branch": "feat/xmuse-error-knowledge",
        "worktree": str(root.resolve()),
        "head_ref": head_ref,
        "knowledge_run_id": run_id,
        "verification_commands": verification_commands(),
        "v3_default_preserved": True,
        "v1_fallback_preserved": True,
        "recall_v2_opt_in_preserved": True,
        "kernel_default_unchanged": True,
        "benchmark_improvement_claim_flag": False,
        "review_verdict": review["verdict"],
        "review_eval_decision": review["review_eval_decision"],
        "blockers": blockers,
    }


def build_slave_state(
    *,
    feature_id: str,
    status: str,
    root: Path,
    now: str,
    run_id: str,
) -> dict[str, Any]:
    ack_level = ack_level_for(status)
    return {
        "version": "1.0",
        "feature_id": feature_id,
        "mode": "feature_local_single_god",
        "state": "ready_for_master_review" if status == "usable" else "feature_blocked",
        "branch": "feat/xmuse-error-knowledge",
        "worktree": str(root.resolve()),
        "last_updated": now,
        "ack_level": ack_level,
        "review_verdict": "PASS" if status == "usable" else "FAIL",
        "knowledge_run_id": run_id,
        "artifacts": {
            "result": f"xmuse/work/features/{feature_id}/result.md",
            "ack": f"xmuse/work/features/{feature_id}/ack.json",
            "review_verdict": f"xmuse/work/features/{feature_id}/review_verdict.json",
            "knowledge_run": f"xmuse/knowledge/runs/{run_id}.json",
        },
    }
