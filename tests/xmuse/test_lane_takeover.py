from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.platform.lane_takeover import build_lane_takeover_bundle


def test_build_lane_takeover_bundle_collects_failed_lane_decision_context(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-takeover",
        "status": "exec_failed",
        "prompt": "Fix takeover context.",
        "feature_plan_feature_id": "failed-lane-takeover",
        "acceptance_criteria": [
            "Bundle includes retry metadata.",
            "Large worker logs are referenced or excerpted.",
        ],
        "blueprint_refs": [
            "docs/spec.md",
            "xmuse/work/c_class_autonomous_blueprint_execution_graph_preview.md",
        ],
        "graph_id": "graph-f4",
        "graph_set_id": "graph-set-f4",
        "conversation_id": "conv-1",
        "feature_plan_id": "plan-1",
        "plan_feature_id": "failed-lane-takeover",
        "lease_id": "lease-1",
        "lease_owner": "runner-1",
        "lease_expires_at": "2026-06-01T12:34:56Z",
        "evidence_bundle_id": "evbundle_123",
        "evidence_bundle_hash": "evidence-bundle-hash",
        "max_attempts_by_reason": {"execution_infra_failure": 2},
        "takeover_attempt_cap": 3,
        "takeover_cooldown_seconds": 90,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
        "gate_report_ref": "logs/gates/lane-takeover/report.json",
        "review_summary": "Review found missing dependency status.",
        "review_decision": "rework",
        "review_history": [
            {
                "decision": "rework",
                "summary": "Prior review flagged missing dependency evidence.",
                "recorded_at": "2026-05-31T00:00:00Z",
            }
        ],
        "review_retry_count": 1,
        "retry_count": 2,
        "failure_reason": "non_zero_exit",
        "branch": "lane-takeover-branch",
        "worktree": "/tmp/lane-takeover",
        "diff_ref": "logs/diffs/lane-takeover.patch",
        "depends_on": ["lane-base", "lane-missing"],
    }
    all_lanes = [
        lane,
        {"feature_id": "lane-base", "status": "merged"},
        {"feature_id": "lane-dependent", "status": "pending", "depends_on": ["lane-takeover"]},
    ]
    gate_report = tmp_path / "logs" / "gates" / "lane-takeover" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(
        json.dumps(
            {
                "passed": False,
                "blocking_passed": False,
                "command_results": [
                    {
                        "command_id": "pytest",
                        "blocking": True,
                        "returncode": 1,
                        "argv": ["uv", "run", "pytest", "tests/test_x.py", "-q"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-takeover"
    spawn_dir.mkdir(parents=True)
    (spawn_dir / "20260530T000000Z.stdout.log").write_text(
        "x" * 5000 + "USEFUL_TAIL",
        encoding="utf-8",
    )
    (spawn_dir / "20260530T000001Z.stderr.log").write_text(
        "first line\nOPENAI_API_KEY=secret\nsemantic traceback",
        encoding="utf-8",
    )

    bundle = build_lane_takeover_bundle(
        lane,
        all_lanes=all_lanes,
        xmuse_root=tmp_path,
        max_log_excerpt_chars=700,
    )

    assert bundle.lane_id == "lane-takeover"
    assert bundle.prompt == "Fix takeover context."
    assert bundle.acceptance_criteria == [
        "Bundle includes retry metadata.",
        "Large worker logs are referenced or excerpted.",
    ]
    assert bundle.lane_metadata == {
        "lane_id": "lane-takeover",
        "status": "exec_failed",
        "graph_id": "graph-f4",
        "conversation_id": "conv-1",
        "feature_plan_id": "plan-1",
        "feature_plan_feature_id": "failed-lane-takeover",
        "blueprint_refs": [
            "docs/spec.md",
            "xmuse/work/c_class_autonomous_blueprint_execution_graph_preview.md",
        ],
    }
    assert bundle.feature_refs == [
        "conversation:conv-1",
        "graph:graph-f4",
        "feature_plan:plan-1",
        "feature:failed-lane-takeover",
        "lane:lane-takeover",
    ]
    assert bundle.blueprint_refs == [
        "docs/spec.md",
        "xmuse/work/c_class_autonomous_blueprint_execution_graph_preview.md",
    ]
    assert bundle.gate_report_refs == [
        {
            "ref": "logs/gates/lane-takeover/report.json",
            "path": str(gate_report),
            "exists": True,
            "summary": "- passed: False\n- blocking_passed: False\n- commands:\n"
            "  - pytest blocking=True returncode=1 cmd=uv run pytest tests/test_x.py -q",
        }
    ]
    assert bundle.review_summary == "Review found missing dependency status."
    assert bundle.review_history == [
        {
            "decision": "rework",
            "summary": "Prior review flagged missing dependency evidence.",
            "recorded_at": "2026-05-31T00:00:00Z",
        }
    ]
    assert bundle.worker_diff_refs == ["logs/diffs/lane-takeover.patch"]
    assert bundle.worktree_ref == {
        "branch": "lane-takeover-branch",
        "worktree": "/tmp/lane-takeover",
    }
    assert bundle.retry_metadata == {
        "retry_count": 2,
        "review_retry_count": 1,
        "failure_reason": "non_zero_exit",
        "review_decision": "rework",
        "review_rework_alignment": {
            "lane_id": "lane-takeover",
            "status": "exec_failed",
            "reason_category": "execution_infra",
            "retry_count": 2,
            "review_retry_count": 1,
            "fallback_reason": "unknown_review_text",
            "primary_evidence_refs": ["lane.failure_reason"],
        },
    }
    assert bundle.dependency_status == {
        "depends_on": [
            {"lane_id": "lane-base", "status": "merged", "found": True},
            {"lane_id": "lane-missing", "status": "missing", "found": False},
        ],
        "dependents": [
            {"lane_id": "lane-dependent", "status": "pending"},
        ],
    }
    assert bundle.run_health_summary == {
        "counts": {
            "live": 0,
            "stale": 0,
            "retrying": 0,
            "blocked": 0,
            "infra_failed": 0,
            "terminal": 2,
            "unsafe_to_release_dependents": 1,
            "takeover_context_needed": 1,
            "degraded_fallback": 0,
        },
        "takeover_counts_by_reason": {"execution_infra_failure": 1},
        "takeover_needed_lane_ids": ["lane-takeover"],
    }
    assert bundle.evidence_requirements == [
        "takeover_context_bundle",
        "repair_diff_or_invalid_abandon_rationale",
        "focused_tests_or_gate_report",
        "review_verdict",
        "audit_event",
        "chat_takeover_or_terminal_card",
    ]
    assert [log["ref"] for log in bundle.worker_logs] == [
        "logs/agent_spawns/lane-takeover/20260530T000000Z.stdout.log",
        "logs/agent_spawns/lane-takeover/20260530T000001Z.stderr.log",
    ]
    assert all(log["truncated"] for log in bundle.worker_logs)
    assert "USEFUL_TAIL" in bundle.worker_logs[0]["excerpt"]
    assert "x" * 1200 not in bundle.worker_logs[0]["excerpt"]
    assert "semantic traceback" in bundle.worker_logs[1]["excerpt"]
    assert "secret" not in bundle.worker_logs[1]["excerpt"]
    assert "[redacted sensitive log line]" in bundle.worker_logs[1]["excerpt"]

    prompt_context = bundle.as_prompt_context()

    assert "## Failed Lane Takeover Context" in prompt_context
    assert "Fix takeover context." in prompt_context
    assert "Bundle includes retry metadata." in prompt_context
    assert "conversation:conv-1" in prompt_context
    assert "docs/spec.md" in prompt_context
    assert "logs/diffs/lane-takeover.patch" in prompt_context
    assert "logs/gates/lane-takeover/report.json" in prompt_context
    assert "Review found missing dependency status." in prompt_context
    assert "Prior review flagged missing dependency evidence." in prompt_context
    assert "lane-base: merged" in prompt_context
    assert "lane-missing: missing" in prompt_context
    assert "takeover_context_bundle" in prompt_context
    assert "execution_infra_failure" in prompt_context
    assert "USEFUL_TAIL" in prompt_context
    assert "x" * 1200 not in prompt_context


def test_build_lane_takeover_bundle_finds_unsanitized_gate_report_for_colon_lane_id(
    tmp_path: Path,
) -> None:
    lane_id = (
        "lane:conv_c_class_autonomous_blueprint_execution_mvp_v1:"
        "graph-C7:C7-01-takeover-context-and-actions:3fbc25cd65b4"
    )
    gate_report = tmp_path / "logs" / "gates" / lane_id / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(
        json.dumps({"passed": True, "blocking_passed": True}),
        encoding="utf-8",
    )

    bundle = build_lane_takeover_bundle(
        {
            "feature_id": lane_id,
            "status": "gate_failed",
            "graph_set_id": "graph-set-1",
            "feature_plan_id": "plan-1",
            "feature_plan_feature_id": "feature-1",
            "lease_id": "lease-1",
            "lease_owner": "runner-1",
            "lease_expires_at": "2026-06-01T12:34:56Z",
            "evidence_bundle_id": "evbundle_123",
            "evidence_bundle_hash": "evidence-bundle-hash",
            "max_attempts_by_reason": {"gate_failure": 1},
            "takeover_attempt_cap": 3,
            "takeover_cooldown_seconds": 90,
            "terminal_escalation_policy": "escalate_to_human_or_outer_god",
        },
        all_lanes=[
            {
                "feature_id": lane_id,
                "status": "gate_failed",
                "graph_set_id": "graph-set-1",
                "feature_plan_id": "plan-1",
                "feature_plan_feature_id": "feature-1",
                "lease_id": "lease-1",
                "lease_owner": "runner-1",
                "lease_expires_at": "2026-06-01T12:34:56Z",
                "evidence_bundle_id": "evbundle_123",
                "evidence_bundle_hash": "evidence-bundle-hash",
                "max_attempts_by_reason": {"gate_failure": 1},
                "takeover_attempt_cap": 3,
                "takeover_cooldown_seconds": 90,
                "terminal_escalation_policy": "escalate_to_human_or_outer_god",
            }
        ],
        xmuse_root=tmp_path,
    )

    assert any(
        ref["ref"] == f"logs/gates/{lane_id}/report.json" and ref["exists"] is True
        for ref in bundle.gate_report_refs
    )


def test_build_lane_takeover_bundle_includes_guard_context_contract_sections(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-takeover",
        "status": "exec_failed",
        "graph_id": "graph-1",
        "conversation_id": "conv-1",
        "feature_plan_id": "plan-1",
        "feature_plan_feature_id": "feature-1",
        "graph_set_id": "graph-set-1",
        "plan_feature_id": "feature-1",
        "projection_revision": 7,
        "projection_source": "feature_lanes.json",
        "takeover_attempt_id": "takeover-attempt-1",
        "lease_id": "lease-1",
        "lease_owner": "runner-1",
        "lease_expires_at": "2026-06-01T12:34:56Z",
        "takeover_cooldown_seconds": 90,
        "evidence_bundle_id": "evbundle_123",
        "evidence_bundle_hash": "evidence-bundle-hash",
        "max_attempts_by_reason": {"execution_infra_failure": 2},
        "takeover_attempt_cap": 3,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
        "diff_ref": "logs/diffs/lane-takeover.patch",
        "review_history": [{"decision": "rework", "summary": "Need stronger guards."}],
    }

    bundle = build_lane_takeover_bundle(
        lane,
        all_lanes=[lane],
        xmuse_root=tmp_path,
    )

    assert bundle.context_contract["schema_version"] == "takeover-context-contract/v1"
    assert bundle.context_contract["attempt"] == {
        "takeover_attempt_id": "takeover-attempt-1",
        "retry_count": 0,
        "review_retry_count": 0,
    }
    assert bundle.context_contract["lease"] == {
        "lease_id": "lease-1",
        "lease_owner": "runner-1",
        "lease_expires_at": "2026-06-01T12:34:56Z",
    }
    assert bundle.context_contract["projection"] == {
        "projection_revision": 7,
        "projection_source": "feature_lanes.json",
    }
    assert bundle.context_contract["lane"] == {
        "lane_id": "lane-takeover",
        "lane_status": "exec_failed",
        "graph_id": "graph-1",
        "conversation_id": "conv-1",
    }
    assert bundle.context_contract["evidence"]["evidence_bundle_id"] == "evbundle_123"
    assert bundle.context_contract["evidence"]["evidence_bundle_hash"] == (
        "evidence-bundle-hash"
    )
    assert bundle.context_contract["evidence"]["worker_diff_refs"] == [
        "logs/diffs/lane-takeover.patch"
    ]
    assert bundle.context_contract["graph_set"] == {
        "graph_set_id": "graph-set-1",
        "graph_id": "graph-1",
    }
    assert bundle.context_contract["feature_plan"] == {
        "feature_plan_id": "plan-1",
        "plan_feature_id": "feature-1",
    }
    assert bundle.context_contract["max_attempt"] == {
        "max_attempts_by_reason": {"execution_infra_failure": 2},
        "takeover_attempt_cap": 3,
        "cooldown_seconds": 90,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
    }


@pytest.mark.parametrize(
    ("fields", "expected_missing_field"),
    [
        (("lease_expires_at",), "lease.lease_expires_at"),
        (("lease_id",), "lease.lease_id"),
        (("lease_owner",), "lease.lease_owner"),
        (("evidence_bundle_id",), "evidence.evidence_bundle_id"),
        ("evidence_bundle_hash", "evidence.evidence_bundle_hash"),
        (("feature_plan_id",), "feature_plan.feature_plan_id"),
        (
            ("plan_feature_id", "feature_plan_feature_id"),
            "feature_plan.plan_feature_id",
        ),
        ("graph_set_id", "graph_set.graph_set_id"),
        (("max_attempts_by_reason",), "max_attempt.max_attempts_by_reason"),
        (("takeover_cooldown_seconds",), "max_attempt.cooldown_seconds"),
        ("takeover_attempt_cap", "max_attempt.takeover_attempt_cap"),
        ("terminal_escalation_policy", "max_attempt.terminal_escalation_policy"),
    ],
)
def test_build_lane_takeover_bundle_marks_missing_required_guards_without_blocking_context(
    tmp_path: Path,
    fields: tuple[str, ...] | str,
    expected_missing_field: str,
) -> None:
    lane = {
        "feature_id": "lane-takeover",
        "status": "exec_failed",
        "graph_id": "graph-1",
        "conversation_id": "conv-1",
        "feature_plan_id": "plan-1",
        "feature_plan_feature_id": "feature-1",
        "graph_set_id": "graph-set-1",
        "plan_feature_id": "feature-1",
        "projection_revision": 7,
        "projection_source": "feature_lanes.json",
        "takeover_attempt_id": "takeover-attempt-1",
        "lease_id": "lease-1",
        "lease_owner": "runner-1",
        "lease_expires_at": "2026-06-01T12:34:56Z",
        "takeover_cooldown_seconds": 90,
        "evidence_bundle_id": "evbundle_123",
        "evidence_bundle_hash": "evidence-bundle-hash",
        "max_attempts_by_reason": {"execution_infra_failure": 2},
        "takeover_attempt_cap": 3,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
    }
    for field in (fields,) if isinstance(fields, str) else fields:
        del lane[field]

    bundle = build_lane_takeover_bundle(
        lane,
        all_lanes=[lane],
        xmuse_root=tmp_path,
    )

    assert bundle.context_contract["guard_status"]["mutation_ready"] is False
    assert expected_missing_field in bundle.context_contract["guard_status"][
        "missing_required_fields"
    ]


def test_build_lane_takeover_bundle_marks_incomplete_guards_for_read_only_context(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-takeover",
        "status": "exec_failed",
        "graph_id": "graph-1",
        "conversation_id": "conv-1",
        "feature_plan_id": "plan-1",
        "feature_plan_feature_id": "feature-1",
        "review_summary": "Missing guard metadata should not break read-only context.",
    }

    bundle = build_lane_takeover_bundle(
        lane,
        all_lanes=[lane],
        xmuse_root=tmp_path,
    )

    assert bundle.context_contract["schema_version"] == "takeover-context-contract/v1"
    assert bundle.context_contract["attempt"] == {
        "takeover_attempt_id": "takeover-lane-takeover",
        "retry_count": 0,
        "review_retry_count": 0,
    }
    assert bundle.context_contract["lease"] == {
        "lease_id": None,
        "lease_owner": None,
        "lease_expires_at": None,
    }
    assert bundle.context_contract["graph_set"] == {
        "graph_set_id": None,
        "graph_id": "graph-1",
    }
    assert bundle.context_contract["guard_status"] == {
        "mutation_ready": False,
        "escalation_action": "escalate_to_human_or_outer_god",
        "missing_required_fields": [
            "lease.lease_expires_at",
            "lease.lease_id",
            "lease.lease_owner",
            "evidence.evidence_bundle_hash",
            "evidence.evidence_bundle_id",
            "graph_set.graph_set_id",
            "max_attempt.max_attempts_by_reason",
            "max_attempt.cooldown_seconds",
            "max_attempt.takeover_attempt_cap",
            "max_attempt.terminal_escalation_policy",
        ],
    }
