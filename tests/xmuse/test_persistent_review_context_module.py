from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.execution import persistent_review_context
from xmuse_core.platform.execution.review_god import (
    _persistent_review_prompt as legacy_persistent_review_prompt,
)
from xmuse_core.platform.execution.review_god import (
    _review_request_id as legacy_review_request_id,
)


def test_persistent_review_context_module_owns_review_request_ids() -> None:
    request_id = persistent_review_context.review_request_id(
        "review god/session",
        "lane:conv:graph:feature",
    )

    assert request_id == "review-review-god-session-lane-conv-graph-feature"


def test_persistent_review_context_module_appends_routing_block() -> None:
    prompt = persistent_review_context.persistent_review_prompt(
        "Review this lane.  \n",
        review_request_id="review-1",
        identity_key="feature-review",
    )

    assert prompt.startswith("Review this lane.\n\n## Persistent Review Routing")
    assert "- review_request_id: review-1" in prompt
    assert "- persistent_review_identity: feature-review" in prompt


def test_persistent_review_context_reports_missing_chat_db(tmp_path: Path) -> None:
    assert persistent_review_context.conversation_history_for_prompt(
        "conv-1",
        xmuse_root=tmp_path,
    ) == "## Conversation History\n\n- unavailable: chat.db missing"


def test_persistent_review_context_grounds_review_in_gate_and_worker_refs(
    tmp_path: Path,
) -> None:
    lane_id = "lane-grounding"
    gate_report = tmp_path / "logs" / "gates" / lane_id / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(
        json.dumps(
            {
                "passed": True,
                "blocking_passed": True,
                "command_results": [
                    {
                        "command_id": "pytest",
                        "profile_id": "strict-product",
                        "blocking": True,
                        "returncode": 0,
                        "argv": [
                            "uv",
                            "run",
                            "pytest",
                            "-q",
                            "tests/xmuse/test_package_boundaries.py",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spawn_log = tmp_path / "logs" / "agent_spawns" / lane_id / "run.stdout.log"
    spawn_log.parent.mkdir(parents=True)
    spawn_log.write_text("16 passed", encoding="utf-8")

    context = persistent_review_context.persistent_review_context(
        {
            "feature_id": lane_id,
            "status": "gated",
            "gate_passed": True,
            "prompt": "Review the package-boundary lane.",
            "recent_agent_spawn_refs": [
                f"logs/agent_spawns/{lane_id}/run.stdout.log",
            ],
        },
        conversation_id="conv-1",
        xmuse_root=tmp_path,
        all_lanes=[],
    )

    assert "## Review Artifact Grounding" in context
    assert "- Current lane status: gated" in context
    assert "- Gate passed: True" in context
    assert f"- Gate report: logs/gates/{lane_id}/report.json" in context
    assert "cmd=uv run pytest -q tests/xmuse/test_package_boundaries.py" in context
    assert f"- logs/agent_spawns/{lane_id}/run.stdout.log" in context
    assert "do not state that logs, gate reports, or execution artifacts are absent" in context


def test_review_god_preserves_persistent_review_compat_exports() -> None:
    assert legacy_review_request_id is persistent_review_context.review_request_id
    assert (
        legacy_persistent_review_prompt
        is persistent_review_context.persistent_review_prompt
    )
