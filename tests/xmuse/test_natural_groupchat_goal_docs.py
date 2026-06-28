from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs" / "xmuse"
CURRENT_MAIN_SHA = "8ae7600991371783658829900cda59ecdbed7a57"
CURRENT_PR_HEAD_SHA = "f67d34035d78eeb662b8f927e5a22dcd7328b080"
CURRENT_MAIN_CI_RUN = "28318943411"
HISTORICAL_DISPATCH_PROOF_SPLIT_SHA = "53dbeb9ace749510e9cb0f82f73cbd4df11ec190"


def _read_doc(name: str) -> str:
    return (DOCS_ROOT / name).read_text(encoding="utf-8")


def test_natural_groupchat_goal_docs_track_current_main_calibration() -> None:
    docs = {
        "README.md": _read_doc("README.md"),
        "natural-groupchat-a2a-goal.md": _read_doc("natural-groupchat-a2a-goal.md"),
        "natural-groupchat-a2a-task-plan.md": _read_doc("natural-groupchat-a2a-task-plan.md"),
        "natural-groupchat-a2a-goal-prompt.md": _read_doc("natural-groupchat-a2a-goal-prompt.md"),
    }

    for name, content in docs.items():
        assert CURRENT_MAIN_SHA in content, name
        assert "#273" in content, name
        assert "#259" in content

    assert CURRENT_PR_HEAD_SHA in docs["natural-groupchat-a2a-goal.md"]
    assert HISTORICAL_DISPATCH_PROOF_SPLIT_SHA in docs["natural-groupchat-a2a-goal.md"]
    assert HISTORICAL_DISPATCH_PROOF_SPLIT_SHA in docs["natural-groupchat-a2a-task-plan.md"]
    assert CURRENT_MAIN_CI_RUN in docs["natural-groupchat-a2a-goal.md"]
    assert CURRENT_MAIN_CI_RUN in docs["natural-groupchat-a2a-task-plan.md"]
    assert "track-a-post273-sentinel-20260628" in docs["natural-groupchat-a2a-task-plan.md"]
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
