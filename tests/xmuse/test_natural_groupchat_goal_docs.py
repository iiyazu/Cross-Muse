from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs" / "xmuse"
OBSERVED_BASELINE_MAIN_SHA = "5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d"
OBSERVED_BASELINE_PR_HEAD_SHA = "f3212bba613693cdbb38249fd746fb760064d3c8"
OBSERVED_BASELINE_MAIN_CI_RUN = "28323650818"
HISTORICAL_DISPATCH_PROOF_SPLIT_SHA = "53dbeb9ace749510e9cb0f82f73cbd4df11ec190"
POST_ABC_BASELINE_MAIN_SHA = "07630131dcb6e26c8dc09dcf41690381e5cd0ee6"
POST_ABC_PR_HEAD_SHA = "9be3b17190380171756bd8375fcb946247217d7c"
POST_ABC_PR_CI_RUN = "28332878486"
POST_ABC_MAIN_CI_RUN = "28332906024"
POST_ABC_RUN_ID = "track-abc-integrated-memoryos-degraded-20260629-01"
POST_ABC_CONVERSATION_ID = "conv_c7528fbf03b84755b8d4eb65166aa0a1"
POST_ABC_FINAL_ACTION_ID = "final-cce17cc5e0e7"
POST_ABC_GITHUB_GATE_REF = (
    "github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49"
)


def _read_doc(name: str) -> str:
    return (DOCS_ROOT / name).read_text(encoding="utf-8")


def test_natural_groupchat_goal_docs_record_observed_baseline_contract() -> None:
    docs = {
        "README.md": _read_doc("README.md"),
        "natural-groupchat-a2a-goal.md": _read_doc("natural-groupchat-a2a-goal.md"),
        "natural-groupchat-a2a-task-plan.md": _read_doc("natural-groupchat-a2a-task-plan.md"),
        "natural-groupchat-a2a-goal-prompt.md": _read_doc("natural-groupchat-a2a-goal-prompt.md"),
    }

    for name, content in docs.items():
        assert OBSERVED_BASELINE_MAIN_SHA in content, name
        assert "#279" in content, name
        assert "#259" in content
        assert "current main calibration" not in content.lower(), name

    assert "last_observed_baseline" in docs["README.md"]
    assert "last_observed_baseline" in docs["natural-groupchat-a2a-goal.md"]
    assert "last_observed_baseline" in docs["natural-groupchat-a2a-task-plan.md"]
    assert "last_observed_baseline" in docs["natural-groupchat-a2a-goal-prompt.md"]
    assert "The latest merged PR is #279" not in docs["natural-groupchat-a2a-goal.md"]
    assert "not live GitHub truth" in docs["natural-groupchat-a2a-goal.md"]
    assert "not live GitHub truth" in docs["natural-groupchat-a2a-task-plan.md"]

    assert OBSERVED_BASELINE_PR_HEAD_SHA in docs["natural-groupchat-a2a-goal.md"]
    assert HISTORICAL_DISPATCH_PROOF_SPLIT_SHA in docs["natural-groupchat-a2a-goal.md"]
    assert HISTORICAL_DISPATCH_PROOF_SPLIT_SHA in docs["natural-groupchat-a2a-task-plan.md"]
    assert OBSERVED_BASELINE_MAIN_CI_RUN in docs["natural-groupchat-a2a-goal.md"]
    assert OBSERVED_BASELINE_MAIN_CI_RUN in docs["natural-groupchat-a2a-task-plan.md"]
    assert "track-a-post273-sentinel-20260628" in docs["natural-groupchat-a2a-task-plan.md"]
    assert "track-a-docs-only-gate-final2-20260628" in docs[
        "natural-groupchat-a2a-task-plan.md"
    ]
    assert "default native" in docs["natural-groupchat-a2a-task-plan.md"]
    assert "28314524612" in docs["natural-groupchat-a2a-task-plan.md"]
    assert "#250" in docs["README.md"]
    assert "#251" in docs["README.md"]
    assert "#252" in docs["README.md"]
    assert "#254" in docs["README.md"]
    assert "#255" in docs["README.md"]
    assert "#257" in docs["README.md"]
    assert "#258" in docs["README.md"]
    assert "#259" in docs["README.md"]
    assert "#260" in docs["README.md"]
    assert "#261" in docs["README.md"]
    assert "#262" in docs["README.md"]
    assert "#263" in docs["README.md"]
    assert "#264" in docs["README.md"]
    assert "#265" in docs["README.md"]
    assert "#266" in docs["README.md"]
    assert "#267" in docs["README.md"]
    assert "#268" in docs["README.md"]
    assert "#269" in docs["README.md"]
    assert "#270" in docs["README.md"]
    assert "#271" in docs["README.md"]
    assert "#272" in docs["README.md"]
    assert "#273" in docs["README.md"]
    assert "#274" in docs["README.md"]
    assert "#275" in docs["README.md"]
    assert "#276" in docs["README.md"]
    assert "#277" in docs["README.md"]
    assert "#278" in docs["README.md"]
    assert "#279" in docs["README.md"]


def test_natural_groupchat_goal_docs_record_post_abc_starting_state() -> None:
    docs = {
        "README.md": _read_doc("README.md"),
        "natural-groupchat-a2a-goal.md": _read_doc("natural-groupchat-a2a-goal.md"),
        "natural-groupchat-a2a-task-plan.md": _read_doc("natural-groupchat-a2a-task-plan.md"),
        "natural-groupchat-a2a-goal-prompt.md": _read_doc("natural-groupchat-a2a-goal-prompt.md"),
    }

    for name, content in docs.items():
        assert "post_abc_closure_baseline" in content, name
        assert POST_ABC_BASELINE_MAIN_SHA in content, name
        assert POST_ABC_PR_HEAD_SHA in content, name
        assert POST_ABC_PR_CI_RUN in content, name
        assert POST_ABC_MAIN_CI_RUN in content, name
        assert POST_ABC_RUN_ID in content, name
        assert POST_ABC_CONVERSATION_ID in content, name
        assert POST_ABC_FINAL_ACTION_ID in content, name
        assert POST_ABC_GITHUB_GATE_REF in content, name
        assert "docs-only" in content, name

    task_plan = docs["natural-groupchat-a2a-task-plan.md"]
    assert "Current Source-Derived Starting State" not in task_plan
    assert "Current final-report notes for the #284" not in task_plan


def test_github_server_gate_docs_describe_exact_head_check_run_evidence() -> None:
    server_gate = _read_doc("github-server-side-gate.md")

    for fragment in (
        "PR head SHA",
        "check run names",
        "check run head SHAs",
        "missing per-check-run head SHA",
        "duplicate check names",
        "`manual_gap`",
    ):
        assert fragment in server_gate


def test_goal_behavior_docs_define_throughput_discipline() -> None:
    behavior = _read_doc("natural-groupchat-a2a-behavior.md")
    task_plan = _read_doc("natural-groupchat-a2a-task-plan.md")

    for fragment in (
        "Goal Throughput Discipline",
        "Track A is the default primary Track",
        "core-chain progress",
        "support progress",
        "one primary authority boundary",
        "Do not count support surfaces as core-chain completion",
        "Subagent or copilot audit should be sampled at decision points",
    ):
        assert fragment in behavior

    for fragment in (
        "Execution Throughput Gate",
        "primary_track",
        "support_tracks",
        "primary_authority_boundary",
        "core_chain_progress_target",
        "support_progress_target",
        "Track A is the default primary track",
        "Support work must not be reported as core-chain completion",
        "forbidden progress claims",
    ):
        assert fragment in task_plan
