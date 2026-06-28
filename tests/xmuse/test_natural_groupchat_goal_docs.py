from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs" / "xmuse"


def _read_doc(name: str) -> str:
    return (DOCS_ROOT / name).read_text(encoding="utf-8")


def test_natural_groupchat_goal_docs_track_current_main_calibration() -> None:
    docs = {
        "README.md": _read_doc("README.md"),
        "natural-groupchat-a2a-goal.md": _read_doc("natural-groupchat-a2a-goal.md"),
        "natural-groupchat-a2a-task-plan.md": _read_doc("natural-groupchat-a2a-task-plan.md"),
        "natural-groupchat-a2a-goal-prompt.md": _read_doc("natural-groupchat-a2a-goal-prompt.md"),
    }

    for content in docs.values():
        assert "53dbeb9ace749510e9cb0f82f73cbd4df11ec190" in content
        assert "#259" in content

    assert "4b82536830b48d055a613f747391c737a4cb6713" in docs["natural-groupchat-a2a-goal.md"]
    assert "28314524612" in docs["natural-groupchat-a2a-task-plan.md"]
    assert "#250" in docs["README.md"]
    assert "#251" in docs["README.md"]
    assert "#252" in docs["README.md"]
    assert "#254" in docs["README.md"]
    assert "#255" in docs["README.md"]
    assert "#257" in docs["README.md"]
    assert "#258" in docs["README.md"]
    assert "#259" in docs["README.md"]


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
