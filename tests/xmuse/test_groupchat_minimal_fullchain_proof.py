from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from xmuse import platform_runner
from xmuse.chat_api import create_app
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.agent_spawner import AgentSpawner, SpawnResult
from xmuse_core.platform.proof_artifacts import write_minimal_fullchain_proof


@pytest.mark.asyncio
async def test_minimal_groupchat_fullchain_proof_records_authority_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_sleep = platform_runner.asyncio.sleep
    root = tmp_path / "xmuse"
    execution_worktree = tmp_path / "worker"
    execution_worktree.mkdir()
    (execution_worktree / "placeholder.txt").write_text(
        "bounded proof worker placeholder\n",
        encoding="utf-8",
    )
    chat = ChatStore(root / "chat.db")
    conversation = chat.create_conversation("Minimal fullchain proof")
    demand = chat.add_message(
        conversation.id,
        author="human",
        role="user",
        content="Make the proof lane write a bounded local evidence marker.",
        envelope_type="human_demand",
        envelope_json={"type": "human_demand", "scope": "minimal_fullchain_proof"},
    )
    client = TestClient(create_app(root, execution_worktree=execution_worktree))
    proposal_response = client.post(
        f"/api/chat/conversations/{conversation.id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "type": "lane_graph",
                    "summary": "Minimal real positive proof",
                    "lanes": [
                        {
                            "feature_id": "proof-minimal-positive-chain",
                            "prompt": "Write one bounded proof marker and stop.",
                            "depends_on": [],
                            "capabilities": ["docs"],
                        }
                    ],
                }
            ),
            "references": [f"message:{demand.id}"],
        },
    )
    assert proposal_response.status_code == 201
    proposal_id = proposal_response.json()["id"]
    approval_response = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "bounded_proof",
            "goal_summary": "Approve minimal real positive proof.",
        },
    )
    assert approval_response.status_code == 200
    resolution_id = approval_response.json()["id"]
    projected = json.loads((root / "feature_lanes.json").read_text(encoding="utf-8"))
    lane_id = projected["lanes"][0]["feature_id"]

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    async def fake_execution_god(**kwargs) -> None:
        lane_id_arg = kwargs["lane_id"]
        xmuse_root = Path(kwargs["xmuse_root"])
        evidence_ref = f"logs/execution/{lane_id_arg}/proof.json"
        evidence_path = xmuse_root / evidence_ref
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(
                {
                    "lane_id": lane_id_arg,
                    "source": "deterministic bounded proof executor",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        kwargs["sm"].transition(
            lane_id_arg,
            "executed",
            metadata={
                "execution_evidence_refs": [evidence_ref],
                "changed_files": [evidence_ref],
            },
        )
        await kwargs["on_executed"](lane_id_arg)

    async def fast_sleep(_: float) -> None:
        await original_sleep(0)

    review_result = SpawnResult(
        exit_code=0,
        stdout="Findings: bounded proof evidence is present.\nVerdict: merge\n",
        stderr="",
    )
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", fast_sleep)
    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new=fake_execution_god,
    ), patch.object(
        AgentSpawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=review_result,
    ):
        await platform_runner.run(
            lanes_path=root / "feature_lanes.json",
            xmuse_root=root,
            mcp_port=9999,
            max_hours=1,
            max_concurrent=1,
            require_final_action_approval=True,
        )

    proof = write_minimal_fullchain_proof(
        root,
        conversation_id=conversation.id,
        proposal_id=proposal_id,
        resolution_id=resolution_id,
        lane_id=lane_id,
        proof_path=root / "proofs" / "minimal-fullchain-proof.json",
        command_evidence=[
            {
                "command": "uv run pytest tests/xmuse/test_groupchat_minimal_fullchain_proof.py -q",
                "exit_code": 0,
            }
        ],
    )

    assert proof["status"] == "awaiting_final_action"
    assert proof["conversation"]["id"] == conversation.id
    assert proof["human_demand_message"]["id"] == demand.id
    assert proof["proposal"]["id"] == proposal_id
    assert proof["proposal"]["references"] == [f"message:{demand.id}"]
    assert proof["resolution"]["id"] == resolution_id
    assert proof["lane"]["feature_id"] == lane_id
    assert proof["lane"]["resolution_id"] == resolution_id
    assert proof["review_task"]["status"] == "verdict_emitted"
    assert proof["review_verdict"]["decision"] == "merge"
    assert proof["final_action_hold"]["status"] == "pending"
    assert proof["authority_refs"]["chat_db"] == str(root / "chat.db")
    assert proof["authority_refs"]["feature_lanes"] == str(root / "feature_lanes.json")
    assert proof["authority_refs"]["review_plane"] == str(root / "review_plane.json")
    assert proof["authority_refs"]["final_actions"] == str(root / "final_actions.json")
    assert proof["command_evidence"][0]["exit_code"] == 0
    assert (root / "proofs" / "minimal-fullchain-proof.json").exists()
