from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.platform.lane_context import (
    build_lane_context_bundle,
    load_retry_context_for_prompt,
    retry_context_for_prompt,
    write_lane_context_bundle,
)
from xmuse_core.platform.memory_refs import MemoryCategory, MemoryRef, MemoryScope
from xmuse_core.platform.run_health import summarize_run_health


def test_build_lane_context_bundle_summarizes_retry_context(tmp_path: Path) -> None:
    lane = {
        "feature_id": "lane-1",
        "status": "gated",
        "prompt": "implement inbox",
        "retry_count": 2,
        "review_retry_count": 1,
        "review_decision": "rework",
        "review_summary": "Fix terminal inbox state overwrite.",
        "review_history": [
            {
                "decision": "rework",
                "summary": "First review found missing terminal guard.",
                "fallback": "stdout",
                "fallback_reason": "explicit_rework",
            }
        ],
        "failure_reason": "review_no_verdict",
        "gate_passed": True,
        "branch": "lane-1",
        "worktree": "/tmp/lane-1",
        "source_plan": "docs/plan.md",
        "depends_on": ["base-lane"],
    }
    gate_dir = tmp_path / "logs" / "gates" / "lane-1"
    gate_dir.mkdir(parents=True)
    (gate_dir / "report.json").write_text(json.dumps({"passed": True}))
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-1"
    spawn_dir.mkdir(parents=True)
    (spawn_dir / "20260529T000000Z.stdout.log").write_text("stdout")
    (spawn_dir / "20260529T000000Z.result.json").write_text("{}")
    (spawn_dir / "20260529T000001Z.stderr.log").write_text(
        "review stderr tail\nOPENAI_API_KEY=should-not-leak"
    )

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["lane_id"] == "lane-1"
    assert bundle["retry_count"] == 2
    assert bundle["review_retry_count"] == 1
    assert bundle["gate_report_ref"] == "logs/gates/lane-1/report.json"
    assert bundle["gate_report_path"] == str(gate_dir / "report.json")
    assert bundle["gate_report_summary"] == "- passed: True\n- blocking_passed: None"
    assert bundle["recent_agent_spawn_refs"] == [
        "logs/agent_spawns/lane-1/20260529T000000Z.result.json",
        "logs/agent_spawns/lane-1/20260529T000000Z.stdout.log",
        "logs/agent_spawns/lane-1/20260529T000001Z.stderr.log",
    ]
    assert bundle["recent_agent_spawn_paths"] == [
        str(spawn_dir / "20260529T000000Z.result.json"),
        str(spawn_dir / "20260529T000000Z.stdout.log"),
        str(spawn_dir / "20260529T000001Z.stderr.log"),
    ]
    assert "review stderr tail" in bundle["recent_agent_spawn_excerpt"]
    assert "should-not-leak" not in bundle["recent_agent_spawn_excerpt"]
    assert "[redacted sensitive log line]" in bundle["recent_agent_spawn_excerpt"]
    assert "Retry count: 2" in bundle["retry_context"]
    assert "Review decision: rework" in bundle["retry_context"]
    assert "Fix terminal inbox state overwrite." in bundle["retry_context"]
    assert "### Recent Review History" in bundle["retry_context"]
    assert "First review found missing terminal guard." in bundle["retry_context"]
    assert "### Context Bundle References" in bundle["retry_context"]
    assert "Gate refs: logs/gates/lane-1/report.json" in bundle["retry_context"]
    assert (
        "Worker refs: logs/agent_spawns/lane-1/20260529T000000Z.result.json, "
        "logs/agent_spawns/lane-1/20260529T000000Z.stdout.log, "
        "logs/agent_spawns/lane-1/20260529T000001Z.stderr.log"
    ) in bundle["retry_context"]
    assert "### Gate Report Summary" not in bundle["retry_context"]
    assert f"Gate report absolute path: {gate_dir / 'report.json'}" not in (
        bundle["retry_context"]
    )
    assert f"{spawn_dir / '20260529T000000Z.stdout.log'}" not in bundle["retry_context"]
    assert "### Recent Agent Output Excerpt" not in bundle["retry_context"]
    assert "Branch/worktree evidence: branch=lane-1 worktree=/tmp/lane-1" in (
        bundle["retry_context"]
    )


def test_lane_context_bundle_keeps_memory_refs_alongside_primary_evidence_refs(
    tmp_path: Path,
) -> None:
    ref = MemoryRef(
        scope=MemoryScope.CONVERSATION,
        category=MemoryCategory.CONVERSATION_SUMMARY,
        session_id="ses_conv_1",
        title="Conversation Summary",
        conversation_id="conv-1",
        primary_evidence_refs=["logs/gates/lane-1/report.json"],
    )
    lane = {
        "feature_id": "lane-1",
        "feature_plan_feature_id": "feature-alpha",
        "status": "reworking",
        "review_summary": "Primary evidence refs stay auditable.",
        "review_decision": "rework",
        "review_fallback_reason": "blocking_finding",
        "memory_refs": [ref.model_dump(mode="json")],
    }

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["memory_refs"] == [ref.model_dump(mode="json")]
    assert "lane.review_summary" in bundle["primary_evidence_refs"]
    assert bundle["context_contract"]["memory_refs"] == [ref.model_dump(mode="json")]
    assert "Memory refs: memoryos://conversation/conv-1/ses_conv_1" in bundle["retry_context"]
    assert (
        "Memory ref evidence refs: logs/gates/lane-1/report.json"
        in bundle["retry_context"]
    )


def test_lane_context_bundle_carries_dispatch_authority_refs(
    tmp_path: Path,
) -> None:
    source_refs = [
        "proposal:prop-1",
        "collaboration:run-1",
        "resolution:res-1",
        "chat_dispatch_queue:dispatch:conv-1:res-1:execute",
    ]
    lane = {
        "feature_id": "lane-dispatch-authority",
        "status": "pending",
        "source_refs": source_refs,
        "dispatch_queue_entry_id": "dispatch:conv-1:res-1:execute",
    }

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["dispatch_authority"] == {
        "dispatch_queue_entry_id": "dispatch:conv-1:res-1:execute",
        "source_refs": source_refs,
        "proof_boundary": (
            "Dispatch authority refs identify approved xmuse handoff inputs; "
            "they are not lane execution proof."
        ),
    }
    assert bundle["context_contract"]["dispatch_authority"] == bundle["dispatch_authority"]
    assert "Dispatch queue entry: dispatch:conv-1:res-1:execute" in (
        bundle["retry_context"]
    )
    assert "Dispatch authority refs: proposal:prop-1, collaboration:run-1" in (
        bundle["retry_context"]
    )
    assert "not lane execution proof" in bundle["retry_context"]


def test_retry_context_includes_merge_conflict_details(tmp_path: Path) -> None:
    lane = {
        "feature_id": "lane-merge-conflict",
        "status": "reworking",
        "retry_count": 1,
        "merge_failure_reason": "merge_conflict_or_failed",
        "merge_failure_detail": (
            "git merge stdout:\n"
            "CONFLICT (content): Merge conflict in src/example.py\n\n"
            "unmerged paths:\nsrc/example.py"
        ),
        "branch": "lane-merge-conflict",
        "worktree": "/tmp/lane-merge-conflict",
    }

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["merge_failure_reason"] == "merge_conflict_or_failed"
    assert "### Merge Failure" in bundle["retry_context"]
    assert "CONFLICT (content)" in bundle["retry_context"]
    assert "src/example.py" in bundle["retry_context"]


def test_write_lane_context_bundle_persists_latest_json(tmp_path: Path) -> None:
    lane = {
        "feature_id": "lane/with spaces",
        "status": "pending",
        "prompt": "do it",
        "depends_on": ["base-lane"],
    }
    all_lanes = [
        lane,
        {"feature_id": "base-lane", "status": "merged"},
        {"feature_id": "dependent-lane", "status": "pending", "depends_on": ["lane/with spaces"]},
    ]

    path = write_lane_context_bundle(lane, xmuse_root=tmp_path, all_lanes=all_lanes)

    assert path == tmp_path / "logs" / "lane_context" / "lane-with-spaces" / "latest.json"
    payload = json.loads(path.read_text())
    assert payload["lane_id"] == "lane/with spaces"
    assert payload["status"] == "pending"
    assert payload["dependency_states"] == {
        "depends_on": [
            {"lane_id": "base-lane", "status": "merged", "found": True},
        ],
        "dependents": [
            {"lane_id": "dependent-lane", "status": "pending"},
        ],
    }
    assert payload["context_contract"]["dependency_states"] == payload["dependency_states"]


def test_bundle_includes_r1_review_rework_alignment_and_lane_context_refs(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-approved-retry",
        "status": "reworking",
        "retry_count": 1,
        "review_decision": "rework",
        "review_summary": "Review decision: no blocking findings",
        "review_fallback_reason": "unknown_review_text",
        "branch": "lane-approved-retry",
        "worktree": "/tmp/lane-approved-retry",
        "blueprint_refs": [
            "docs/superpowers/specs/2026-05-30-xmuse-review-rework-alignment-preview.md"
        ],
        "acceptance_criteria": [
            "Lane context bundle JSON includes review_rework_alignment from R1.",
        ],
    }
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-approved-retry"
    spawn_dir.mkdir(parents=True)
    (spawn_dir / "20260530T000000Z.stdout.log").write_text(
        "x" * 5000 + "FULL_STDOUT_SENTINEL",
        encoding="utf-8",
    )

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["review_rework_alignment"] == {
        "lane_id": "lane-approved-retry",
        "status": "reworking",
        "reason_category": "approved_review",
        "retry_count": 1,
        "review_retry_count": 0,
        "fallback_reason": "unknown_review_text",
        "primary_evidence_refs": ["lane.review_summary"],
        "context_category": "approved_review",
    }
    assert bundle["blueprint_refs"] == [
        "docs/superpowers/specs/2026-05-30-xmuse-review-rework-alignment-preview.md"
    ]
    assert bundle["acceptance_criteria"] == [
        "Lane context bundle JSON includes review_rework_alignment from R1."
    ]
    assert "FULL_STDOUT_SENTINEL" in bundle["recent_agent_spawn_excerpt"]
    assert len(bundle["recent_agent_spawn_excerpt"]) < 4000


def test_retry_context_separates_alignment_categories_and_approved_review_is_resolved(
    tmp_path: Path,
) -> None:
    bundle = build_lane_context_bundle(
        {
            "feature_id": "lane-approved-retry",
            "status": "reworking",
            "retry_count": 1,
            "review_decision": "rework",
            "review_summary": "Review decision: no blocking findings",
            "review_fallback_reason": "unknown_review_text",
            "failure_reason": "review_no_verdict",
            "branch": "lane-approved-retry",
            "worktree": "/tmp/lane-approved-retry",
        },
        xmuse_root=tmp_path,
    )

    context = retry_context_for_prompt(bundle)

    assert "### Infra Failure" in context
    assert "- Review infra: review_no_verdict" in context
    assert "### Parser/Fallback Classification" in context
    assert "- Category: approved_review" in context
    assert "- Fallback reason: unknown_review_text" in context
    assert "### Real Semantic Findings" in context
    assert "- None identified by review/rework alignment." in context
    assert "### Resolved Prior Findings" in context
    assert "- Prior review evidence indicates approval/no blocking findings." in context
    assert "Review decision: rework" not in context
    assert "Required continuation: address prior review/failure" not in context


def test_retry_context_keeps_rework_decision_for_real_semantic_findings(
    tmp_path: Path,
) -> None:
    bundle = build_lane_context_bundle(
        {
            "feature_id": "lane-real-rework",
            "status": "reworking",
            "retry_count": 1,
            "review_decision": "rework",
            "review_summary": "Blocking: retry context is still flat.",
            "review_fallback_reason": "blocking_finding",
        },
        xmuse_root=tmp_path,
    )

    context = retry_context_for_prompt(bundle)

    assert "Review decision: rework" in context
    assert "### Real Semantic Findings" in context
    assert "- Blocking: retry context is still flat." in context
    assert "Required continuation: address prior review/failure" in context


@pytest.mark.parametrize(
    ("lane", "expected_category", "expected_refs"),
    [
        (
            {
                "feature_id": "lane-review-rejection",
                "status": "reworking",
                "review_decision": "rework",
                "review_summary": "Verdict: rework",
                "review_fallback_reason": "verdict_rework",
            },
            "review_rejection",
            ["lane.review_fallback_reason", "lane.review_summary"],
        ),
        (
            {
                "feature_id": "lane-semantic-rework",
                "status": "reworking",
                "review_decision": "rework",
                "review_summary": "High: context bundle omits dependency states.",
                "review_fallback_reason": "blocking_finding",
            },
            "semantic_rework",
            ["lane.review_fallback_reason", "lane.review_summary"],
        ),
        (
            {
                "feature_id": "lane-gate-failure",
                "status": "gate_failed",
                "failure_reason": "gate_failed",
                "gate_passed": False,
            },
            "gate_failure",
            ["lane.failure_reason"],
        ),
        (
            {
                "feature_id": "lane-execution-infra",
                "status": "exec_failed",
                "failure_reason": "execution_infra_unavailable",
            },
            "execution_infra_failure",
            ["lane.failure_reason"],
        ),
        (
            {
                "feature_id": "lane-review-infra",
                "status": "gate_failed",
                "failure_reason": "review_infra_unavailable",
            },
            "review_infra_failure",
            ["lane.failure_reason"],
        ),
        (
            {
                "feature_id": "lane-merge-conflict",
                "status": "reworking",
                "merge_failure_reason": "merge_conflict_or_failed",
                "merge_failure_detail": "CONFLICT (content): src/x.py",
            },
            "merge_conflict",
            ["lane.merge_failure_reason", "lane.merge_failure_detail"],
        ),
        (
            {
                "feature_id": "lane-prompt-mismatch",
                "status": "reworking",
                "review_summary": "Findings: approach targets the wrong subsystem",
                "review_fallback_reason": "verdict_terminate",
            },
            "prompt_subsystem_mismatch",
            ["lane.review_summary"],
        ),
    ],
)
def test_context_contract_distinguishes_a3_rework_takeover_categories(
    tmp_path: Path,
    lane: dict,
    expected_category: str,
    expected_refs: list[str],
) -> None:
    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["context_contract"]["failure_category"] == expected_category
    assert bundle["context_contract"]["primary_evidence_refs"] == expected_refs
    assert bundle["review_rework_alignment"]["context_category"] == expected_category


def test_context_contract_includes_compact_refs_and_dependency_states(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-contract",
        "status": "reworking",
        "graph_id": "graph-x1",
        "feature_plan_feature_id": "feature-x1",
        "depends_on": ["base-lane", "missing-lane"],
        "acceptance_criteria": ["Context bundle has compact refs."],
        "blueprint_refs": ["docs/spec.md#A3"],
        "review_summary": "Blocking: dependency states missing.",
        "review_fallback_reason": "blocking_finding",
        "branch": "lane-contract",
        "worktree": "/tmp/lane-contract",
    }
    all_lanes = [
        lane,
        {"feature_id": "base-lane", "status": "merged", "graph_id": "graph-x1"},
        {"feature_id": "child-lane", "status": "pending", "depends_on": ["lane-contract"]},
    ]
    gate_report = tmp_path / "logs" / "gates" / "lane-contract" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(json.dumps({"passed": False, "blocking_passed": False}))
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-contract"
    spawn_dir.mkdir(parents=True)
    (spawn_dir / "20260531T000000Z.stdout.log").write_text("worker tail")

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path, all_lanes=all_lanes)

    assert bundle["feature_id"] == "feature-x1"
    assert bundle["graph_id"] == "graph-x1"
    assert bundle["dependency_states"] == {
        "depends_on": [
            {"lane_id": "base-lane", "status": "merged", "found": True},
            {"lane_id": "missing-lane", "status": "missing", "found": False},
        ],
        "dependents": [
            {"lane_id": "child-lane", "status": "pending"},
        ],
    }
    assert bundle["gate_refs"] == [
        {
            "ref": "logs/gates/lane-contract/report.json",
            "exists": True,
        }
    ]
    assert bundle["worker_refs"] == [
        {
            "ref": "logs/agent_spawns/lane-contract/20260531T000000Z.stdout.log",
            "kind": "spawn_log",
        }
    ]
    contract = bundle["context_contract"]
    assert contract["feature_id"] == "feature-x1"
    assert contract["graph_id"] == "graph-x1"
    assert contract["blueprint_refs"] == ["docs/spec.md#A3"]
    assert contract["acceptance_criteria"] == ["Context bundle has compact refs."]
    assert contract["gate_refs"] == bundle["gate_refs"]
    assert contract["worker_refs"] == bundle["worker_refs"]
    assert contract["primary_evidence_refs"] == [
        "lane.review_fallback_reason",
        "lane.review_summary",
    ]

    context = retry_context_for_prompt(bundle)

    assert "### Context Contract" in context
    assert "- Failure category: semantic_rework" in context
    assert "- Feature ID: feature-x1" in context
    assert "- Graph ID: graph-x1" in context
    assert "- dependency base-lane: merged" in context
    assert "- dependency missing-lane: missing" in context


def test_retry_context_cites_bundle_refs_without_dumping_worker_logs(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-compact-context",
        "status": "reworking",
        "retry_count": 1,
        "review_summary": "Blocking: fix the prompt surface.",
        "review_fallback_reason": "blocking_finding",
        "gate_report_ref": "logs/gates/lane-compact-context/report.json",
        "branch": "lane-compact-context",
        "worktree": "/tmp/lane-compact-context",
    }
    report_path = tmp_path / "logs" / "gates" / "lane-compact-context" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "passed": False,
                "blocking_passed": False,
                "command_results": [
                    {
                        "command_id": "pytest",
                        "blocking": True,
                        "returncode": 1,
                        "argv": ["uv", "run", "pytest", "tests/test_big.py", "-q"],
                        "stdout": "RAW_GATE_LOG_SENTINEL",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spawn_dir = tmp_path / "logs" / "agent_spawns" / "lane-compact-context"
    spawn_dir.mkdir(parents=True)
    spawn_log = spawn_dir / "20260531T000000Z.stdout.log"
    spawn_log.write_text("RAW_WORKER_LOG_SENTINEL", encoding="utf-8")

    bundle = build_lane_context_bundle(lane, xmuse_root=tmp_path)

    assert bundle["primary_evidence_refs"] == [
        "lane.review_fallback_reason",
        "lane.review_summary",
    ]
    assert bundle["compact_primary_evidence_refs"] == [
        {"ref": "lane.review_fallback_reason", "kind": "lane_metadata"},
        {"ref": "lane.review_summary", "kind": "lane_metadata"},
    ]
    assert bundle["context_contract"]["compact_primary_evidence_refs"] == (
        bundle["compact_primary_evidence_refs"]
    )

    context = retry_context_for_prompt(bundle)

    assert "### Context Bundle References" in context
    assert "- Gate refs: logs/gates/lane-compact-context/report.json" in context
    assert (
        "- Worker refs: "
        "logs/agent_spawns/lane-compact-context/20260531T000000Z.stdout.log"
        in context
    )
    assert "- Primary evidence refs: lane.review_fallback_reason, lane.review_summary" in context
    assert "RAW_WORKER_LOG_SENTINEL" not in context
    assert "RAW_GATE_LOG_SENTINEL" not in context
    assert str(spawn_log) not in context
    assert str(report_path) not in context
    assert "### Recent Agent Output Excerpt" not in context
    assert "### Gate Report Summary" not in context


def test_persistent_peer_loads_retry_context_for_takeover_scenarios_without_log_grep(
    tmp_path: Path,
) -> None:
    gate_report = tmp_path / "logs" / "gates" / "gate-retry" / "report.json"
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
                        "argv": ["uv", "run", "pytest", "tests/test_gate.py", "-q"],
                        "stdout": "RAW_GATE_SENTINEL",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    lanes = [
        {
            "feature_id": "semantic-rework",
            "status": "reworking",
            "retry_count": 1,
            "review_summary": "Blocking: takeover prompt omits dependency states.",
            "review_fallback_reason": "blocking_finding",
            "review_history": [
                {
                    "decision": "rework",
                    "summary": "Previous review found missing dependency context.",
                    "fallback_reason": "blocking_finding",
                }
            ],
        },
        {
            "feature_id": "infra-requeue",
            "status": "reworking",
            "retry_count": 1,
            "failure_reason": "execution_infra_unavailable",
        },
        {
            "feature_id": "stale-worker",
            "status": "dispatched",
            "dispatched_at": 100.0,
            "worker_pid": 4242,
        },
        {
            "feature_id": "gate-retry",
            "status": "gate_failed",
            "retry_count": 1,
            "failure_reason": "gate_failed",
            "gate_passed": False,
            "gate_report_ref": "logs/gates/gate-retry/report.json",
        },
        {
            "feature_id": "merge-conflict",
            "status": "reworking",
            "retry_count": 1,
            "merge_failure_reason": "merge_conflict_or_failed",
            "merge_failure_detail": (
                "CONFLICT (content): Merge conflict in src/x.py\n"
                "unmerged paths:\nsrc/x.py"
            ),
        },
        {
            "feature_id": "base-lane",
            "status": "merged",
        },
    ]
    for lane in lanes[:5]:
        lane.update(
            {
                "feature_plan_feature_id": "feature-x1",
                "graph_id": "graph-x1",
                "depends_on": ["base-lane"],
                "blueprint_refs": ["docs/superpowers/specs/x1-blueprint.md"],
                "acceptance_criteria": [
                    "Persistent peers can retry from context bundle refs."
                ],
                "branch": f"{lane['feature_id']}-branch",
                "worktree": f"/tmp/{lane['feature_id']}",
            }
        )
        spawn_dir = tmp_path / "logs" / "agent_spawns" / str(lane["feature_id"])
        spawn_dir.mkdir(parents=True)
        (spawn_dir / "20260531T000000Z.stdout.log").write_text(
            f"RAW_WORKER_SENTINEL_{lane['feature_id']}",
            encoding="utf-8",
        )
        context_path = write_lane_context_bundle(
            lane,
            xmuse_root=tmp_path,
            all_lanes=lanes,
        )
        lane["lane_context_ref"] = str(context_path.relative_to(tmp_path))

    health = summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
        live_pids=set(),
        xmuse_root=tmp_path,
    )

    assert [
        (item["lane_id"], item["reason"], item["lane_context_ref"])
        for item in health["takeover_context"]["needed_lanes"]
    ] == [
        (
            "semantic-rework",
            "semantic_rework",
            "logs/lane_context/semantic-rework/latest.json",
        ),
        (
            "infra-requeue",
            "execution_infra_retry",
            "logs/lane_context/infra-requeue/latest.json",
        ),
        (
            "stale-worker",
            "stale_worker",
            "logs/lane_context/stale-worker/latest.json",
        ),
        (
            "gate-retry",
            "gate_failure",
            "logs/lane_context/gate-retry/latest.json",
        ),
        (
            "merge-conflict",
            "merge_conflict",
            "logs/lane_context/merge-conflict/latest.json",
        ),
    ]

    expected_prompt_markers = {
        "semantic-rework": [
            "- Failure category: semantic_rework",
            "Blocking: takeover prompt omits dependency states.",
            "- Review history refs: lane.review_history[0]",
        ],
        "infra-requeue": [
            "- Failure category: execution_infra_failure",
            "- Execution infra: execution_infra_unavailable",
        ],
        "stale-worker": [
            "- Failure category: not_review_related",
            "- Previous status: dispatched",
        ],
        "gate-retry": [
            "- Failure category: gate_failure",
            "- Gate failure: gate_failed",
            "- Gate refs: logs/gates/gate-retry/report.json",
        ],
        "merge-conflict": [
            "- Failure category: merge_conflict",
            "### Merge Failure",
            "CONFLICT (content): Merge conflict in src/x.py",
        ],
    }
    for lane in lanes[:5]:
        context = load_retry_context_for_prompt(lane, xmuse_root=tmp_path)

        assert context is not None
        assert "- Feature ID: feature-x1" in context
        assert "- Graph ID: graph-x1" in context
        assert "- dependency base-lane: merged" in context
        assert "- Blueprint refs: docs/superpowers/specs/x1-blueprint.md" in context
        assert "- Persistent peers can retry from context bundle refs." in context
        assert "RAW_WORKER_SENTINEL" not in context
        assert "RAW_GATE_SENTINEL" not in context
        for marker in expected_prompt_markers[str(lane["feature_id"])]:
            assert marker in context
