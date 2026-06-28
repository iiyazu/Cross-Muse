from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs" / "xmuse"
OBSERVED_BASELINE_MAIN_SHA = "5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d"
OBSERVED_BASELINE_PR_HEAD_SHA = "f3212bba613693cdbb38249fd746fb760064d3c8"
OBSERVED_BASELINE_MAIN_CI_RUN = "28323650818"
HISTORICAL_DISPATCH_PROOF_SPLIT_SHA = "53dbeb9ace749510e9cb0f82f73cbd4df11ec190"


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
