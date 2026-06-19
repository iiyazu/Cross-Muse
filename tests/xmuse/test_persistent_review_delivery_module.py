from __future__ import annotations

import json

import pytest

from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.platform.execution import persistent_review_delivery
from xmuse_core.platform.execution.review_god import (
    PersistentReviewReceiveError as LegacyPersistentReviewReceiveError,
)
from xmuse_core.platform.execution.review_god import (
    _persistent_verdict_payload as legacy_persistent_verdict_payload,
)
from xmuse_core.platform.state_machine import LaneStateMachine


def test_persistent_review_delivery_module_owns_verdict_payload_parsing() -> None:
    message = StdoutMessage(
        type="result",
        message="done",
        artifacts={
            "review_verdict": {
                "decision": "patch-forward",
                "summary": "Needs a bounded follow-up patch.",
            }
        },
    )

    assert persistent_review_delivery.persistent_verdict_payload(message) == {
        "decision": "rework",
        "summary": "Needs a bounded follow-up patch.",
    }


def test_persistent_review_delivery_rejects_non_result_messages() -> None:
    message = StdoutMessage(type="progress", message="still working")

    assert persistent_review_delivery.persistent_verdict_payload(message) is None


def test_review_god_preserves_persistent_review_delivery_compat_exports() -> None:
    assert (
        legacy_persistent_verdict_payload
        is persistent_review_delivery.persistent_verdict_payload
    )
    assert (
        LegacyPersistentReviewReceiveError
        is persistent_review_delivery.PersistentReviewReceiveError
    )


@pytest.mark.asyncio
async def test_apply_persistent_review_message_records_evidence_refs(tmp_path) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "gated",
                        "review_task_id": "task-lane-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    evidence_refs = [
        "feature_lanes.json#lane=lane-1",
        "review_plane.json#task=task-lane-1",
        "logs/gates/lane-1/report.json",
    ]
    captured: dict[str, object] = {}

    def stable_verdict_id(lane_id: str) -> str:
        assert lane_id == "lane-1"
        return "verdict-merge-task-lane-1"

    def ingest_merge_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        captured["lane_id"] = lane_id
        captured["summary"] = summary
        captured["evidence_refs"] = refs

    def ingest_rework_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected rework verdict for {lane_id}: {summary}")

    async def on_reviewed(lane_id: str) -> None:
        captured["reviewed"] = lane_id

    async def on_rejected(lane_id: str) -> None:
        raise AssertionError(f"unexpected rejected lane {lane_id}")

    delivered = await persistent_review_delivery.apply_persistent_review_message(
        lane_id="lane-1",
        sm=sm,
        message=StdoutMessage(type="result", message="No findings.\nVerdict: merge"),
        stable_verdict_id=stable_verdict_id,
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id="review-request-1",
        persistent_review_identity="configured:review-peer-1",
        evidence_refs=[*evidence_refs, evidence_refs[0], ""],
    )

    lane = sm.get_lane("lane-1")
    assert delivered is True
    assert lane["status"] == "reviewed"
    assert lane["review_evidence_refs"] == evidence_refs
    assert captured["evidence_refs"] == evidence_refs
    assert captured["reviewed"] == "lane-1"


@pytest.mark.asyncio
async def test_apply_persistent_review_message_sanitizes_merge_truth_claims(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-merge-boundary",
                        "status": "gated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    captured: dict[str, object] = {}

    def ingest_merge_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        captured["lane_id"] = lane_id
        captured["summary"] = summary
        captured["evidence_refs"] = refs

    def ingest_rework_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected rework verdict for {lane_id}: {summary}")

    async def on_reviewed(lane_id: str) -> None:
        captured["reviewed"] = lane_id

    async def on_rejected(lane_id: str) -> None:
        raise AssertionError(f"unexpected rejected lane {lane_id}")

    delivered = await persistent_review_delivery.apply_persistent_review_message(
        lane_id="lane-merge-boundary",
        sm=sm,
        message=StdoutMessage(
            type="result",
            artifacts={
                "review_verdict": {
                    "decision": "merge",
                    "summary": (
                        "Verdict: merge. Lane reviewed and merged. "
                        "ready_to_merge=true; pr_merged=true."
                    ),
                }
            },
        ),
        stable_verdict_id=lambda lane_id: f"verdict-{lane_id}",
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id="review-request-1",
        persistent_review_identity="configured:review-peer-1",
        evidence_refs=["review://configured-peer"],
    )

    lane = sm.get_lane("lane-merge-boundary")
    summary = str(lane["review_summary"])
    assert delivered is True
    assert lane["status"] == "reviewed"
    assert "Proof boundary: review acceptance is not merge truth" in summary
    lowered = summary.lower()
    assert "reviewed and merged" not in lowered
    assert "ready_to_merge" not in lowered
    assert "pr_merged" not in lowered
    assert str(captured["summary"]) == summary
    assert lane["review_history"][-1]["summary"] == summary


@pytest.mark.asyncio
async def test_apply_persistent_review_message_is_idempotent_after_native_mcp_review(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reviewed",
                        "review_history": [
                            {
                                "decision": "merge",
                                "summary": "native MCP review accepted",
                                "fallback": "mcp",
                                "fallback_reason": "update_lane_status",
                                "recorded_at": 1.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    captured: dict[str, object] = {}

    async def on_reviewed(lane_id: str) -> None:
        captured["reviewed"] = lane_id

    def ingest_merge_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        captured["lane_id"] = lane_id
        captured["summary"] = summary
        captured["evidence_refs"] = refs

    def ingest_rework_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected rework verdict for {lane_id}: {summary}")

    async def on_rejected(lane_id: str) -> None:
        raise AssertionError(f"unexpected rejected lane {lane_id}")

    delivered = await persistent_review_delivery.apply_persistent_review_message(
        lane_id="lane-1",
        sm=sm,
        message=StdoutMessage(
            type="result",
            artifacts={
                "review_verdict": {
                    "decision": "merge",
                    "summary": "callback review accepted",
                }
            },
        ),
        stable_verdict_id=lambda lane_id: f"verdict-{lane_id}",
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id="review-request-1",
        persistent_review_identity="configured:review-peer-1",
        evidence_refs=["review://native-mcp"],
    )

    lane = sm.get_lane("lane-1")
    assert delivered is True
    assert lane["status"] == "reviewed"
    assert lane["review_verdict_id"] == "verdict-lane-1"
    assert lane["review_history"][0]["fallback"] == "mcp"
    assert lane["review_history"][1]["fallback"] == "persistent"
    assert captured["reviewed"] == "lane-1"
    assert captured["summary"] == "callback review accepted"


@pytest.mark.asyncio
async def test_apply_persistent_review_message_is_idempotent_after_final_action_hold(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-final-hold",
                        "status": "awaiting_final_action",
                        "review_verdict_id": "verdict-lane-final-hold",
                        "final_action_hold_id": "final-1",
                        "review_history": [
                            {
                                "decision": "merge",
                                "summary": "review accepted",
                                "fallback": "mcp",
                                "fallback_reason": "update_lane_status",
                                "recorded_at": 1.0,
                            },
                            {
                                "decision": "merge",
                                "summary": "review accepted",
                                "fallback": "structured",
                                "fallback_reason": "review_verdict",
                                "verdict_id": "verdict-lane-final-hold",
                                "recorded_at": 2.0,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)

    def ingest_merge_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected duplicate merge verdict for {lane_id}")

    def ingest_rework_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected rework verdict for {lane_id}: {summary}")

    async def on_reviewed(lane_id: str) -> None:
        raise AssertionError(f"unexpected duplicate reviewed callback for {lane_id}")

    async def on_rejected(lane_id: str) -> None:
        raise AssertionError(f"unexpected rejected lane {lane_id}")

    delivered = await persistent_review_delivery.apply_persistent_review_message(
        lane_id="lane-final-hold",
        sm=sm,
        message=StdoutMessage(
            type="result",
            artifacts={
                "review_verdict": {
                    "decision": "merge",
                    "summary": "review accepted",
                }
            },
        ),
        stable_verdict_id=lambda lane_id: f"verdict-{lane_id}",
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id="review-request-1",
        persistent_review_identity="configured:review-peer-1",
        evidence_refs=["review://configured-peer"],
    )

    lane = sm.get_lane("lane-final-hold")
    assert delivered is True
    assert lane["status"] == "awaiting_final_action"
    assert lane["final_action_hold_id"] == "final-1"
    assert lane["review_verdict_id"] == "verdict-lane-final-hold"
    assert lane["review_delivery_mode"] == "persistent"
    assert lane["persistent_review_degraded"] is False
    assert lane["review_evidence_refs"] == ["review://configured-peer"]
    assert lane["review_history"][-1]["fallback"] == "persistent"
    assert lane["review_history"][-1]["summary"] == "review accepted"


@pytest.mark.asyncio
async def test_apply_persistent_review_message_ignores_late_rework_after_acceptance(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-reviewed",
                        "status": "reviewed",
                        "review_decision": "merge",
                        "review_verdict_id": "verdict-lane-reviewed",
                        "review_history": [
                            {
                                "decision": "merge",
                                "summary": "review accepted",
                                "fallback": "mcp",
                                "fallback_reason": "update_lane_status",
                                "recorded_at": 1.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)

    def ingest_merge_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"unexpected duplicate merge verdict for {lane_id}")

    def ingest_rework_verdict(
        lane_id: str,
        summary: str,
        refs: list[str] | None = None,
    ) -> None:
        raise AssertionError(f"late rework must not replace accepted review: {lane_id}")

    async def on_reviewed(lane_id: str) -> None:
        raise AssertionError(f"unexpected duplicate reviewed callback for {lane_id}")

    async def on_rejected(lane_id: str) -> None:
        raise AssertionError(f"late rework must not reject accepted lane {lane_id}")

    delivered = await persistent_review_delivery.apply_persistent_review_message(
        lane_id="lane-reviewed",
        sm=sm,
        message=StdoutMessage(
            type="result",
            artifacts={
                "review_verdict": {
                    "decision": "rework",
                    "summary": "late structured rework after accepted MCP update",
                }
            },
        ),
        stable_verdict_id=lambda lane_id: f"verdict-{lane_id}",
        ingest_merge_verdict=ingest_merge_verdict,
        ingest_rework_verdict=ingest_rework_verdict,
        on_reviewed=on_reviewed,
        on_rejected=on_rejected,
        review_request_id="review-request-1",
        persistent_review_identity="configured:review-peer-1",
        evidence_refs=["review://configured-peer"],
    )

    lane = sm.get_lane("lane-reviewed")
    assert delivered is True
    assert lane["status"] == "reviewed"
    assert lane["review_decision"] == "merge"
    assert lane["review_verdict_id"] == "verdict-lane-reviewed"
    assert lane["review_delivery_mode"] == "persistent"
    assert lane["persistent_review_degraded"] is False
    assert lane["review_evidence_refs"] == ["review://configured-peer"]
    assert lane["review_conflict_ignored"] is True
    assert lane["review_conflict_ignored_reason"] == "review_already_accepted"
    assert lane["ignored_review_decision"] == "rework"
    assert lane["ignored_review_summary"] == "late structured rework after accepted MCP update"
    assert lane["ignored_review_conflicts"][-1]["decision"] == "rework"
