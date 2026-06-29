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
        "document-status.md": _read_doc("document-status.md"),
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
    assert "last_observed_baseline" in docs["document-status.md"]
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
    status = docs["document-status.md"]
    assert "Keep `docs/xmuse/README.md` short" in status
    assert "Rung4 promoted runtime sentinel code was removed" in status
    assert "Sentinel artifacts are not product modules" in status
    assert "docs/xmuse/archive/2026-06-rung-sentinel-artifacts.md" in status
    assert "#279" in status
    assert "#259" in status


def test_natural_groupchat_goal_docs_record_post_abc_starting_state() -> None:
    docs = {
        "README.md": _read_doc("README.md"),
        "document-status.md": _read_doc("document-status.md"),
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


def test_one_off_rung_sentinel_artifacts_are_archived_not_product_source() -> None:
    archive = _read_doc("archive/2026-06-rung-sentinel-artifacts.md")

    for removed_path in (
        PROJECT_ROOT / "src" / "xmuse_core" / "platform" / "rung4_beta_sentinel.py",
        PROJECT_ROOT / "tests" / "xmuse" / "test_rung4_beta_sentinel.py",
        DOCS_ROOT / "rung4-alpha-20260629-02.md",
        DOCS_ROOT / "rung4-beta-20260629-02.md",
        DOCS_ROOT / "rung4-alpha-runtime-20260629-01.md",
        DOCS_ROOT / "rung4-isolation-alpha-success-20260629-05.md",
        DOCS_ROOT / "track-a-post288-sentinel-20260629.md",
        DOCS_ROOT / "track-abc-integrated-memoryos-degraded-20260629-01.md",
    ):
        assert not removed_path.exists(), removed_path

    for fragment in (
        "Sentinel Artifacts",
        "Runtime sentinel artifact for the xmuse Rung 4 beta lane",
        "Rung4 isolation alpha lane stayed successful while beta failed gate.",
        "not product documentation entrypoints",
        "not reusable product modules",
    ):
        assert fragment in archive
