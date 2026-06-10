from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.platform.memory_refs import MemoryCategory, MemoryRef, MemoryScope
from xmuse_core.platform.orchestrator import PlatformOrchestrator


class _FakeMemoryOSClient:
    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.ingested: list[tuple[str, str, str]] = []

    async def create_session(self, title: str) -> str:
        self.created_titles.append(title)
        return f"ses_{len(self.created_titles)}"

    async def ingest(self, session_id: str, role: str, content: str) -> None:
        self.ingested.append((session_id, role, content))

    async def build_context(self, session_id: str, task: str, budget: int = 4096) -> str:
        return f"context for {session_id}: {task}"


@pytest.fixture
def xmuse_setup(tmp_path: Path) -> tuple[Path, Path]:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    gates_dir = tmp_path / "logs" / "gates"
    gates_dir.mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    return tmp_path, lanes_path


@pytest.mark.asyncio
async def test_dispatch_lane_records_feature_memory_for_meaningful_planning(
    xmuse_setup: tuple[Path, Path],
) -> None:
    tmp_path, lanes_path = xmuse_setup
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-plan",
                        "status": "pending",
                        "conversation_id": "conv-1",
                        "feature_plan_feature_id": "feature-alpha",
                        "feature_title": "Feature Alpha",
                        "prompt": "Implement the planning contract.",
                        "acceptance_criteria": ["Keep primary evidence auditable."],
                        "blueprint_refs": ["docs/spec.md"],
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _FakeMemoryOSClient()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        memoryos_client=client,
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=type("R", (), {"exit_code": 0, "stdout": "", "stderr": ""})(),
    ):
        with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=True):
            await orch.dispatch_lane("lane-plan")

    lane = orch._sm.get_lane("lane-plan")
    assert client.created_titles == ["xmuse-memory:feature:conv-1:feature-alpha"]
    assert len(client.ingested) == 1
    assert lane["memory_refs"][0]["scope"] == "feature"
    assert lane["memory_refs"][0]["category"] == "feature_history"
    assert lane["memory_refs"][0]["feature_id"] == "feature-alpha"
    assert lane["memory_refs"][0]["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_on_lane_reviewed_records_peer_memory_for_meaningful_review(
    xmuse_setup: tuple[Path, Path],
) -> None:
    tmp_path, lanes_path = xmuse_setup
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-review",
                        "status": "reviewed",
                        "conversation_id": "conv-1",
                        "feature_plan_feature_id": "feature-alpha",
                        "review_peer_id": "peer-review-1",
                        "review_decision": "merge",
                        "review_summary": "No blocking findings after checking the gate report.",
                        "review_verdict_id": "verdict-1",
                        "worktree": str(tmp_path),
                        "branch": "lane-review",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _FakeMemoryOSClient()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        memoryos_client=client,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-review")

    lane = orch._sm.get_lane("lane-review")
    assert lane["status"] == "merged"
    assert len(client.ingested) == 1
    assert lane["memory_refs"][0]["scope"] == "peer"
    assert lane["memory_refs"][0]["category"] == "review_rework_lesson"
    assert lane["memory_refs"][0]["participant_id"] == "peer-review-1"
    assert lane["memory_refs"][0]["primary_evidence_refs"] == [
        "lane.review_summary",
        "lane.review_verdict_id",
    ]


@pytest.mark.asyncio
async def test_on_lane_reviewed_does_not_emit_memory_from_memory_only_review_evidence(
    xmuse_setup: tuple[Path, Path],
) -> None:
    tmp_path, lanes_path = xmuse_setup
    prior_ref = MemoryRef(
        scope=MemoryScope.PEER,
        category=MemoryCategory.REVIEW_REWORK_LESSON,
        session_id="ses_existing_review",
        title="Prior Review Memory",
        conversation_id="conv-1",
        participant_id="peer-review-1",
        feature_id="feature-alpha",
        primary_evidence_refs=["logs/gates/lane-review/report.json"],
    )
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-review",
                        "status": "reviewed",
                        "conversation_id": "conv-1",
                        "feature_plan_feature_id": "feature-alpha",
                        "review_peer_id": "peer-review-1",
                        "review_decision": "merge",
                        "memory_refs": [prior_ref.model_dump(mode="json")],
                        "worktree": str(tmp_path),
                        "branch": "lane-review",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _FakeMemoryOSClient()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        memoryos_client=client,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-review")

    lane = orch._sm.get_lane("lane-review")
    assert lane["status"] == "merged"
    assert client.ingested == []
    assert lane["memory_refs"] == [prior_ref.model_dump(mode="json")]


@pytest.mark.asyncio
async def test_redispatch_records_peer_memory_for_takeover_context(
    xmuse_setup: tuple[Path, Path],
) -> None:
    tmp_path, lanes_path = xmuse_setup
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-takeover",
                        "status": "reworking",
                        "conversation_id": "conv-1",
                        "feature_plan_feature_id": "feature-alpha",
                        "execute_peer_id": "peer-exec-1",
                        "prompt": "Fix takeover context.",
                        "failure_reason": "non_zero_exit",
                        "review_summary": "Prior attempt missed dependency status.",
                        "retry_count": 1,
                        "review_retry_count": 1,
                        "worktree": str(tmp_path),
                        "branch": "lane-takeover",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _FakeMemoryOSClient()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        memoryos_client=client,
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=type("R", (), {"exit_code": 0, "stdout": "", "stderr": ""})(),
    ):
        with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=True):
            await orch.dispatch_lane("lane-takeover")

    lane = orch._sm.get_lane("lane-takeover")
    assert len(client.ingested) == 1
    assert lane["memory_refs"][0]["scope"] == "peer"
    assert lane["memory_refs"][0]["category"] == "peer_lesson"
    assert lane["memory_refs"][0]["participant_id"] == "peer-exec-1"
    assert "lane.failure_reason" in lane["memory_refs"][0]["primary_evidence_refs"]
